//! ng3-painel — o painel do Video Automation NG3 como app nativo (Rune).
//!
//! O acervo e a identidade vêm da marca ativa (`config/marca-ativa`); o app só precisa achar a
//! raiz do projeto (a pasta com `src/painel/api.py`).
//!
//!     ng3-painel                                  # raiz: a pasta atual (ou acima), ou a do executável
//!     ng3-painel --raiz ~/Projects/video-automation-ng3 [--acervo <pasta>]
//!     ng3-painel --snap painel.png --scene demo -- --acervo <pasta>   # headless

mod app;
mod dados;
mod filtro;
mod plugins;
mod ponte;
mod ui;

use app::App;
use rune::{AppSpec, Tx};
use std::path::PathBuf;
use std::time::Duration;

fn arg(nome: &str) -> Option<String> {
    let args = rune::extra_args();
    args.iter().position(|a| a == nome).and_then(|i| args.get(i + 1).cloned())
}

fn eh_raiz(p: &std::path::Path) -> bool { p.join("src").join("painel").join("api.py").exists() }

/// Raiz do projeto (onde estão `src/`, `config/`, `plugins/`): --raiz, $NG3_RAIZ, a pasta atual
/// ou uma acima dela, ou uma pasta acima do executável (`app/target/release/ng3-painel`).
pub fn raiz() -> PathBuf {
    if let Some(p) = arg("--raiz").or_else(|| std::env::var("NG3_RAIZ").ok()) {
        return PathBuf::from(p);
    }
    let mut candidatas = vec![];
    if let Ok(cwd) = std::env::current_dir() { candidatas.push(cwd); }
    if let Ok(exe) = std::env::current_exe() { candidatas.push(exe); }
    for c in &candidatas {
        if let Some(r) = c.ancestors().find(|a| eh_raiz(a)) { return r.to_path_buf(); }
    }
    std::env::current_dir().unwrap_or_else(|_| ".".into())
}

/// O acervo, se foi forçado (--acervo ou $NG3_ACERVO). Sem isso, vem da marca ativa (no ping).
pub fn acervo_forcado() -> Option<PathBuf> {
    arg("--acervo").or_else(|| std::env::var("NG3_ACERVO").ok()).map(PathBuf::from)
}

fn setup(s: &mut App, waker: rune::Waker) {
    s.iniciar(waker);
}

fn poll(s: &mut App, agora: f64, tx: &mut Tx) -> bool {
    let mut mudou = s.colher();
    if s.busca_assentou(agora) {
        mudou = true;
    } else if s.busca.text != s.filtro.busca {
        tx.wake_after(Duration::from_millis(60));
    }
    // aviso some sozinho depois de 4 s
    match (&s.aviso, s.aviso_desde) {
        (Some(_), None) => { s.aviso_desde = Some(agora); tx.wake_after(Duration::from_secs(4)); }
        (Some(_), Some(t0)) if agora - t0 >= 4.0 => { s.aviso = None; s.aviso_desde = None; mudou = true; }
        (None, Some(_)) => s.aviso_desde = None,
        _ => {}
    }
    mudou |= s.plugins.poll(agora, tx);
    mudou
}

/// Atalhos: Esc fecha o preview; ← → trocam de página (ou de quadro, no preview);
/// / vai para a busca.
fn tecla(s: &mut App, ev: &rune::KeyEvent, tx: &mut Tx) -> bool {
    use rune::Key;
    if matches!(ev.key, Key::Escape) && s.chave_aberta { s.chave_aberta = false; return true; }
    if tx.focused().is_some() { return false; }
    match (&ev.key, s.preview.is_some()) {
        (Key::Escape, true) => s.preview = None,
        (Key::Left, true) => s.passo_quadro(-1),
        (Key::Right, true) => s.passo_quadro(1),
        (Key::Left, false) => { let p = s.pagina.saturating_sub(1); s.ir_pagina(p, tx) }
        (Key::Right, false) => { let p = s.pagina + 1; s.ir_pagina(p, tx) }
        (Key::Text(c), false) if c == "/" => tx.focus("busca", true),
        _ => return false,
    }
    true
}

fn main() {
    rune::run(AppSpec {
        min_size: Some((900.0, 560.0)),
        setup: Some(setup),
        poll: Some(poll),
        on_key: Some(tecla),
        scenes: &[("demo", cenas::demo), ("preview", cenas::preview), ("config", cenas::config), ("video", cenas::video), ("chave", cenas::chave), ("motion", cenas::motion), ("recomendados", cenas::recomendados),
                  ("cortes", cenas::cortes), ("plugins", cenas::plugins),
                  ("compacto", cenas::compacto), ("legenda", cenas::legenda), ("paginas", cenas::paginas)],
        ..AppSpec::new("Video Automation NG3", (1360.0, 860.0), App::novo, ui::view)
    });
}

/// Cenas para snapshots headless: carregam o acervo de forma síncrona pela api.py.
mod cenas {
    use super::*;
    use serde_json::{Value, json};

    fn chamar(base: &std::path::Path, metodo: &str, dados: Value) -> Value {
        let mut c = std::process::Command::new("python3");
        c.arg(raiz().join("src/painel/api.py")).args(["chamar", metodo, &dados.to_string()]).current_dir(raiz());
        if !base.as_os_str().is_empty() { c.env("NG3_ACERVO", base); }
        let out = c.output().expect("python3");
        let v: Value = serde_json::from_slice(&out.stdout).unwrap_or(Value::Null);
        v["resultado"].clone()
    }

    fn carregar(s: &mut App) {
        let ping = chamar(&s.base, "ping", json!({}));
        s.ler_marca(&ping);
        s.modelos_prompt = serde_json::from_value(chamar(&s.base, "modelos_prompt", json!({}))).unwrap_or_default();
        s.posts = serde_json::from_value(chamar(&s.base, "posts", json!({}))).unwrap_or_default();
        s.cortes = serde_json::from_value(chamar(&s.base, "cortes", json!({}))).unwrap_or_default();
        s.estados = serde_json::from_value(chamar(&s.base, "estados", json!({}))).unwrap_or_default();
        for p in &mut s.posts { p.preparar(); }
        for c in &mut s.cortes { c.preparar(); }
        s.carregando = false;
        s.colunas = 5;
        s.por_pagina = 48;
        s.refiltrar();
        s.querem_miniatura.clear();
        // miniaturas de tudo, já decodificadas (o snapshot não espera o worker)
        let capas: Vec<String> = s.posts.iter().filter_map(|p| p.capa().map(str::to_string))
            .chain(s.cortes.iter().map(|c| c.capa().to_string())).collect();
        for c in capas {
            if let Some(p) = chamar(&s.base, "miniatura", json!({"arquivo": c})).as_str() {
                let im = s.imagens.file(p, 220.0, 2.0);
                let _ = im.wait();
                s.miniaturas.insert(c, im);
            }
        }
    }

    pub fn demo(s: &mut App) {
        carregar(s);
        let a = s.posts[1].nome.clone();
        let b = s.posts[4].nome.clone();
        s.selecao.insert(a);
        s.estados.entry(b).or_default().repostado = true;
    }

    pub fn preview(s: &mut App) {
        carregar(s);
        let post = s.posts.iter().find(|p| p.n_video > 0 && p.n_img > 0).or(s.posts.iter().find(|p| p.n_video > 0)).unwrap().clone();
        s.abrir_preview(app::Alvo::Post(post.nome.clone()));
        for img in post.imagens() {
            if let Some(c) = chamar(&s.base, "miniatura", json!({"arquivo": img, "px": 720})).as_str() {
                let im = s.imagens.file(c, 240.0, 2.0);
                let _ = im.wait();
                s.originais.insert(img.clone(), im);
            }
        }
        let v = s.preview.as_ref().and_then(|p| p.video.clone()).unwrap();
        let t: dados::Tira = serde_json::from_value(chamar(&s.base, "tira", json!({"arquivo": v, "n": 16, "px": 200}))).unwrap();
        let im = s.imagens.file(&t.arquivo, 1600.0, 2.0);
        let _ = im.wait();
        let q = 5;
        let cs: Vec<String> = serde_json::from_value(chamar(&s.base, "quadros", json!({"arquivo": v, "n": 16, "px": 720}))).unwrap();
        let qi = s.imagens.file(&cs[q], 480.0, 2.0);
        let _ = qi.wait();
        s.quadros.insert((v.clone(), q), qi);
        s.caminhos_quadros.insert(v.clone(), cs);
        s.ultimo_exportado = Some("x/quadros/01.png".into());
        s.tiras.insert(v.clone(), (t, im));
        s.preview.as_mut().unwrap().quadro = q;
        s.preview.as_mut().unwrap().palavras = serde_json::from_value(chamar(&s.base, "palavras", json!({"video": v}))).unwrap_or_default();
    }

    /// A aba "chaves e config".
    pub fn config(s: &mut App) {
        carregar(s);
        let r = chamar(&s.base, "ping", json!({}));
        s.ler_chave_info_pub(&r);
        s.trocar_aba(app::Aba::Config);
    }

    /// O painel da chave da API aberto.
    pub fn chave(s: &mut App) {
        carregar(s);
        let r = chamar(&s.base, "ping", json!({}));
        s.ler_chave_info_pub(&r);
        s.escolher_provedor("deepseek");
        s.chave_aberta = true;
    }

    /// O formulário de vídeo com IA aberto num momento (modelos de exemplo, sem rede).
    pub fn video(s: &mut App) {
        motion(s);
        s.video_modelos = serde_json::from_value(json!([
            {"id": "google/veo-3.1", "nome": "Veo 3.1", "duracoes": [4, 6, 8], "resolucoes": ["720p", "1080p"],
             "formatos": ["16:9", "9:16"], "quadros": ["first_frame"], "audio": true, "precos": {"generate": "0.40"}},
            {"id": "bytedance/seedance-2.0", "nome": "Seedance 2.0", "duracoes": [5, 10], "resolucoes": ["480p", "1080p"],
             "formatos": ["9:16", "16:9", "1:1"], "quadros": ["first_frame", "last_frame"], "audio": false, "precos": {}},
            {"id": "x-ai/exemplo-horizontal", "nome": "Exemplo horizontal", "duracoes": [6], "resolucoes": ["720p"],
             "formatos": ["16:9"], "quadros": [], "audio": false, "precos": {}}])).unwrap();
        let id = s.motion.as_ref().and_then(|m| m.estado.as_ref())
            .and_then(|e| e.sugestoes.iter().find(|m| m.status == "sugerido").map(|m| m.id.clone())).unwrap_or_default();
        s.video_abrir(&id);
        if let Some(f) = s.video_form.as_mut() {
            f.prompt = rune::TextEdit::new("B-roll vertical: jovens jogadores em campo, câmera em movimento suave, luz natural.");
        }
    }

    /// Preview de uma pasta de cortes com a seção Motion carregada.
    pub fn motion(s: &mut App) {
        carregar(s);
        let c = s.cortes.iter().find(|c| c.videos.len() > 1).or(s.cortes.first()).unwrap().clone();
        s.abrir_preview(app::Alvo::Corte(c.arquivo.clone()));
        let v = c.videos[0].clone();
        let t: dados::Tira = serde_json::from_value(chamar(&s.base, "tira", json!({"arquivo": v, "n": 16, "px": 200}))).unwrap();
        let im = s.imagens.file(&t.arquivo, 1600.0, 2.0);
        let _ = im.wait();
        s.tiras.insert(v.clone(), (t, im));
        let cs: Vec<String> = serde_json::from_value(chamar(&s.base, "quadros", json!({"arquivo": v, "n": 16, "px": 720}))).unwrap();
        let qi = s.imagens.file(&cs[2], 480.0, 2.0);
        let _ = qi.wait();
        s.quadros.insert((v.clone(), 2), qi);
        s.preview.as_mut().unwrap().quadro = 2;
        let e = chamar(&s.base, "motion", json!({"pasta": c.arquivo}));
        // b-roll do acervo para o primeiro momento ainda sugerido
        if let Some(id) = e["sugestoes"].as_array().and_then(|v| v.iter().find(|m| m["status"] == "sugerido")).and_then(|m| m["id"].as_str()) {
            chamar(&s.base, "broll_candidatos", json!({"pasta": c.arquivo, "id": id}));
        }
        let e = chamar(&s.base, "motion", json!({"pasta": c.arquivo}));
        s.motion_chegou(&c.arquivo, e);
        s.miniaturas_broll_pub();
        let ims: Vec<_> = s.miniaturas.values().cloned().collect();
        for im in ims { let _ = im.wait(); }
        let refs: Vec<String> = s.motion.as_ref().and_then(|m| m.estado.as_ref())
            .map(|e| e.referencias.iter().cloned().chain(e.sugestoes.iter().flat_map(|m| m.referencias.clone())).collect())
            .unwrap_or_default();
        for r in refs {
            if let Some(p) = chamar(&s.base, "miniatura", json!({"arquivo": r})).as_str() {
                let im = s.imagens.file(p, 220.0, 2.0);
                let _ = im.wait();
                s.miniaturas.insert(r, im);
            }
        }
        s.querem_miniatura.clear();
        // o primeiro momento com as três abordagens da IA abertas (para ver o cartão)
        if let Some(m) = s.motion.as_mut() && let Some(id) = m.estado.as_ref().and_then(|e| e.sugestoes.first()).map(|x| x.id.clone()) {
            let ops = serde_json::from_value(json!([
                {"nome": "Faixa lateral", "ideia": "o nome entra numa faixa vinda da esquerda", "texto": "Faixa com o nome entra da esquerda em 0,3 s…"},
                {"nome": "Carimbo", "ideia": "o texto bate como carimbo torto", "texto": "Carimbo de borda dupla, 6° de rotação…"},
                {"nome": "Seta à mão", "ideia": "uma seta desenhada aponta para quem fala", "texto": "Seta curta desenhada à mão em 0,4 s…"}])).unwrap();
            m.abordagens.insert(format!("{id}#motion#abordagens"), ops);
        }
    }

    /// Preview de um post só de imagens com legenda longa (quebra de linha).
    pub fn legenda(s: &mut App) {
        carregar(s);
        let post = s.posts.iter().max_by_key(|p| p.gancho.len()).unwrap().clone();
        s.abrir_preview(app::Alvo::Post(post.nome.clone()));
        for img in post.imagens() {
            if let Some(c) = chamar(&s.base, "miniatura", json!({"arquivo": img, "px": 720})).as_str() {
                let im = s.imagens.file(c, 240.0, 2.0);
                let _ = im.wait();
                s.originais.insert(img.clone(), im);
            }
        }
    }

    pub fn recomendados(s: &mut App) {
        carregar(s);
        s.trocar_aba(app::Aba::Recomendados);
    }

    pub fn cortes(s: &mut App) {
        carregar(s);
        s.trocar_aba(app::Aba::Cortes);
        s.colunas = 4;
        s.refiltrar();
    }

    pub fn compacto(s: &mut App) {
        carregar(s);
        s.por_pagina = 0;
        s.tamanho = app::Tamanho::Compacto;
        s.colunas = 8;
        s.filtro.ordem = crate::filtro::Ordem::Curtidas;
        s.recalcular();
    }

    pub fn paginas(s: &mut App) {
        carregar(s);
        s.por_pagina = 8;
        s.pagina = 1;
        s.recalcular();
    }

    pub fn plugins(s: &mut App) {
        carregar(s);
        s.trocar_aba(app::Aba::Plugins);
    }
}
