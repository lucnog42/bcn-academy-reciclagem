//! Plugins em Luau: uma pasta por plugin em `_reciclagem/plugins/<id>/init.luau`.
//!
//! O script devolve uma tabela com:
//!   info()               -> { id, nome, descricao, aplicaA = {"video","imagem","corte"}, params = {...}, painel = bool }
//!   rodar(itens, params) -> chama `ng3.processo{...}` / `ng3.gerar(...)` / `ng3.avisar(...)`
//!   render(view)         -> (opcional) um painel próprio desenhado com @rune/ui
//!
//! O módulo `@ng3` é o que o app oferece. Nada roda direto do Luau: os pedidos entram numa fila
//! que o app passa para a api.py, que só aceita comandos da lista permitida e dentro do acervo.
//! Salvar o `.luau` recarrega o plugin na hora.

use rune::{Cx, El, Tx};
use rune_luau::mlua::{self, Lua, Table};
use rune_luau::{Data, Script, ScriptOptions, Sources};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

#[derive(Clone, Debug, PartialEq)]
pub enum Valor {
    Num(f64),
    Txt(String),
    Bool(bool),
}

impl Valor {
    pub fn texto(&self) -> String {
        match self {
            Valor::Num(n) if n.fract() == 0.0 => format!("{n:.0}"),
            Valor::Num(n) => format!("{n:.2}"),
            Valor::Txt(s) => s.clone(),
            Valor::Bool(b) => if *b { "sim".into() } else { "não".into() },
        }
    }
    fn data(&self) -> Data {
        match self {
            Valor::Num(n) => Data::Number(*n),
            Valor::Txt(s) => Data::String(s.clone()),
            Valor::Bool(b) => Data::Bool(*b),
        }
    }
}

#[derive(Clone, Debug)]
pub enum Tipo {
    Numero { min: f64, max: f64, passo: f64 },
    Escolha(Vec<String>),
    Booleano,
}

#[derive(Clone, Debug)]
pub struct Param {
    pub id: String,
    pub rotulo: String,
    pub ajuda: String,
    pub tipo: Tipo,
    pub padrao: Valor,
}

pub struct Plugin {
    pub id: String,
    pub nome: String,
    pub descricao: String,
    pub aplica_a: Vec<String>,
    pub params: Vec<Param>,
    pub valores: HashMap<String, Valor>,
    pub painel: bool,
    pub script: Script,
    pub pasta: PathBuf,
}

/// O que um script pediu ao app.
#[derive(Debug)]
pub enum Acao {
    Processo { dono: String, cmd: Vec<String> },
    Gerar { itens: Vec<String>, cortes: bool, forcar: bool },
    Aviso(String),
}

#[derive(Default)]
pub struct Plugins {
    pub lista: Vec<Plugin>,
    pub erros: Vec<String>,
    fila: Arc<Mutex<Vec<Acao>>>,
    pub concluidas: Vec<(String, bool)>,
}

fn d_str(d: &Data, k: &str) -> String { d.get(k).as_str().unwrap_or("").to_string() }
fn d_num(d: &Data, k: &str, padrao: f64) -> f64 { d.get(k).as_f64().unwrap_or(padrao) }
fn d_lista(d: &Data, k: &str) -> Vec<Data> {
    match d.get(k) { Data::List(v) => v.clone(), _ => vec![] }
}

fn param(d: &Data) -> Option<Param> {
    let id = d_str(d, "id");
    if id.is_empty() { return None; }
    let rotulo = match d_str(d, "rotulo") { s if s.is_empty() => id.clone(), s => s };
    let (tipo, padrao) = match d_str(d, "tipo").as_str() {
        "numero" => (Tipo::Numero { min: d_num(d, "min", f64::MIN), max: d_num(d, "max", f64::MAX), passo: d_num(d, "passo", 1.0) },
                     Valor::Num(d_num(d, "padrao", 0.0))),
        "escolha" => {
            let ops: Vec<String> = d_lista(d, "opcoes").iter().filter_map(|o| o.as_str().map(str::to_string)).collect();
            let p = d.get("padrao").as_str().map(str::to_string).or_else(|| ops.first().cloned()).unwrap_or_default();
            (Tipo::Escolha(ops), Valor::Txt(p))
        }
        _ => (Tipo::Booleano, Valor::Bool(matches!(d.get("padrao"), Data::Bool(true)))),
    };
    Some(Param { id, rotulo, ajuda: d_str(d, "ajuda"), tipo, padrao })
}

/// `@ng3`, montado em cada VM nova (inclusive a cada recarga).
fn modulo_ng3(lua: &Lua, dono: &str, base: &Path, fila: Arc<Mutex<Vec<Acao>>>) -> mlua::Result<Table> {
    let t = lua.create_table()?;
    t.set("acervo", base.display().to_string())?;
    let (f1, d1) = (fila.clone(), dono.to_string());
    t.set("processo", lua.create_function(move |_, cmd: Vec<String>| {
        if cmd.is_empty() { return Err(mlua::Error::runtime("ng3.processo: comando vazio")); }
        f1.lock().unwrap().push(Acao::Processo { dono: d1.clone(), cmd });
        Ok(())
    })?)?;
    let f2 = fila.clone();
    t.set("gerar", lua.create_function(move |_, (itens, cortes, forcar): (Vec<String>, Option<bool>, Option<bool>)| {
        f2.lock().unwrap().push(Acao::Gerar { itens, cortes: cortes.unwrap_or(false), forcar: forcar.unwrap_or(false) });
        Ok(())
    })?)?;
    let f3 = fila;
    let d3 = dono.to_string();
    t.set("avisar", lua.create_function(move |_, msg: String| {
        f3.lock().unwrap().push(Acao::Aviso(format!("{d3}: {msg}")));
        Ok(())
    })?)?;
    Ok(t)
}

impl Plugins {
    /// Os plugins de `<raiz>/plugins/<nome>/init.luau`; `base` é o acervo (`ng3.acervo` no Luau).
    pub fn carregar(raiz: &Path, base: &Path) -> Plugins {
        let mut out = Plugins::default();
        let dir = raiz.join("plugins");
        let Ok(entradas) = std::fs::read_dir(&dir) else { return out };
        let mut pastas: Vec<PathBuf> = entradas.filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.join("init.luau").exists()).collect();
        pastas.sort();
        for pasta in pastas {
            let id = pasta.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
            match out.abrir(base, &id, &pasta) {
                Ok(p) => out.lista.push(p),
                Err(e) => out.erros.push(format!("{id}: {e}")),
            }
        }
        out
    }

    fn abrir(&self, base: &Path, id: &str, pasta: &Path) -> Result<Plugin, String> {
        let sources = Sources::from_dir(pasta).map_err(|e| e.to_string())?;
        let (fila, dono, base2) = (self.fila.clone(), id.to_string(), base.to_path_buf());
        let opcoes = ScriptOptions::new()
            .setup(move |host| host.register_module("@ng3", modulo_ng3(host.lua(), &dono, &base2, fila.clone())?))
            .on_log({ let id = id.to_string(); move |nivel, linha| eprintln!("plugin {id} {nivel:?}: {linha}") });
        let script = Script::with_options(id, sources, opcoes);
        #[cfg(not(target_arch = "wasm32"))]
        let _ = script.watch(pasta);
        if let Some(e) = script.error() { return Err(e.message.clone()); }
        let info = script.query("info", []).map_err(|e| e.message)?;
        let params: Vec<Param> = d_lista(&info, "params").iter().filter_map(param).collect();
        let valores = params.iter().map(|p| (p.id.clone(), p.padrao.clone())).collect();
        Ok(Plugin {
            id: match d_str(&info, "id") { s if s.is_empty() => id.to_string(), s => s },
            nome: match d_str(&info, "nome") { s if s.is_empty() => id.to_string(), s => s },
            descricao: d_str(&info, "descricao"),
            aplica_a: d_lista(&info, "aplicaA").iter().filter_map(|x| x.as_str().map(str::to_string)).collect(),
            painel: matches!(info.get("painel"), Data::Bool(true)),
            params, valores, script, pasta: pasta.to_path_buf(),
        })
    }

    pub fn quantos(&self) -> usize { self.lista.len() }

    pub fn set_waker(&self, w: &rune::Waker) {
        for p in &self.lista { p.script.set_waker(w.clone()); }
    }

    pub fn poll(&self, agora: f64, tx: &mut Tx) -> bool {
        self.lista.iter().fold(false, |m, p| p.script.poll(agora, tx) || m)
    }

    pub fn drenar(&mut self) -> Vec<Acao> { std::mem::take(&mut *self.fila.lock().unwrap()) }

    pub fn tarefa_terminou(&mut self, dono: &str, ok: bool) {
        if self.lista.iter().any(|p| p.id == dono) {
            self.concluidas.push((dono.to_string(), ok));
        }
    }

    /// O plugin serve para este tipo de item? ("video", "imagem", "corte", "post")
    pub fn serve(p: &Plugin, tipo: &str) -> bool {
        p.aplica_a.is_empty() || p.aplica_a.iter().any(|a| a == tipo)
    }

    pub fn rodar(&mut self, id: &str, itens: Vec<Value>) -> Result<(), String> {
        let p = self.lista.iter().find(|p| p.id == id).ok_or("plugin sumiu")?;
        let itens = Data::List(itens.iter().map(json_data).collect());
        let params = Data::Map(p.valores.iter().map(|(k, v)| (k.clone(), v.data())).collect::<BTreeMap<_, _>>());
        p.script.call("rodar", [itens, params]).map_err(|e| e.message)
    }

    pub fn ajustar(&mut self, id: &str, param: &str, v: Valor) {
        if let Some(p) = self.lista.iter_mut().find(|p| p.id == id) {
            p.valores.insert(param.to_string(), v);
        }
    }

    pub fn painel<S: 'static>(&self, id: &str, cx: &Cx<S>) -> Option<El> {
        let p = self.lista.iter().find(|p| p.id == id && p.painel)?;
        Some(p.script.surface(cx, "render"))
    }
}

pub fn json_data(v: &Value) -> Data {
    match v {
        Value::Null => Data::Nil,
        Value::Bool(b) => Data::Bool(*b),
        Value::Number(n) => n.as_i64().map(Data::Integer).unwrap_or_else(|| Data::Number(n.as_f64().unwrap_or(0.0))),
        Value::String(s) => Data::String(s.clone()),
        Value::Array(a) => Data::List(a.iter().map(json_data).collect()),
        Value::Object(o) => Data::Map(o.iter().map(|(k, v)| (k.clone(), json_data(v))).collect()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// Carrega os plugins de verdade do repositório e confere o que cada um pede.
    fn plugins() -> Plugins {
        let raiz = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
        let base = std::env::var("NG3_ACERVO_TESTE").unwrap_or_else(|_| raiz.into());
        let p = Plugins::carregar(Path::new(raiz), Path::new(&base));
        assert!(p.erros.is_empty(), "erros: {:?}", p.erros);
        p
    }

    fn item() -> Vec<Value> {
        vec![json!({"tipo": "post", "nome": "2024-01-01_MIC_x", "videos": ["_posts/2024/x/videos/01.mp4"], "imagens": [],
                    "projeto": "_posts/2024/x/2024-01-01_MIC_x.fcproj"}),
             json!({"tipo": "corte", "nome": "_Cortes/A", "arquivo": "_Cortes/A", "videos": ["_Cortes/A/c.mp4", "_Cortes/A/d.mp4"], "imagens": [],
                    "projeto": ""})]
    }

    #[test]
    fn os_quatro_carregam_com_parametros() {
        let p = plugins();
        let ids: Vec<&str> = p.lista.iter().map(|p| p.id.as_str()).collect();
        for id in ["gerar-projeto", "legendar", "normalizar-audio", "silencecut"] {
            assert!(ids.contains(&id), "falta {id} em {ids:?}");
        }
        let sc = p.lista.iter().find(|p| p.id == "silencecut").unwrap();
        assert_eq!(sc.valores["limiar"], Valor::Num(-40.0));
        assert_eq!(sc.valores["modo"], Valor::Txt("join".into()));
    }

    #[test]
    fn silencecut_vira_um_processo_por_item_com_todos_os_videos() {
        let mut p = plugins();
        p.ajustar("silencecut", "limiar", Valor::Num(-35.0));
        p.ajustar("silencecut", "onde", Valor::Txt("só arquivo".into()));
        p.rodar("silencecut", item()).unwrap();
        let acoes = p.drenar();
        let cmds: Vec<&Vec<String>> = acoes.iter().filter_map(|a| match a { Acao::Processo { cmd, .. } => Some(cmd), _ => None }).collect();
        assert_eq!(cmds.len(), 2);
        assert!(cmds[0].windows(2).any(|w| w[0] == "-t" && w[1] == "-35.000"), "{:?}", cmds[0]);
        assert!(cmds[0].windows(2).any(|w| w[0] == "--onde" && w[1] == "só arquivo"), "{:?}", cmds[0]);
        assert!(cmds[0].windows(2).any(|w| w[0] == "--post" && w[1] == "2024-01-01_MIC_x"), "{:?}", cmds[0]);
        assert!(cmds[1].windows(2).any(|w| w[0] == "--corte" && w[1] == "_Cortes/A"), "{:?}", cmds[1]);
        assert!(cmds[1].windows(2).any(|w| w[0] == "_Cortes/A/c.mp4" && w[1] == "_Cortes/A/d.mp4"), "{:?}", cmds[1]);
        assert!(cmds[0].windows(2).any(|w| w[0] == "--detector" && w[1] == "fala"), "{:?}", cmds[0]);
        assert!(acoes.iter().any(|a| matches!(a, Acao::Aviso(_))));
    }

    #[test]
    fn gerar_separa_posts_e_cortes() {
        let mut p = plugins();
        p.rodar("gerar-projeto", item()).unwrap();
        let acoes = p.drenar();
        let g: Vec<(Vec<String>, bool)> = acoes.into_iter().filter_map(|a| match a { Acao::Gerar { itens, cortes, .. } => Some((itens, cortes)), _ => None }).collect();
        assert_eq!(g, vec![(vec!["2024-01-01_MIC_x".to_string()], false), (vec!["_Cortes/A".to_string()], true)]);
    }

    #[test]
    fn legendar_e_normalizar_montam_o_comando() {
        let mut p = plugins();
        p.rodar("legendar", item()).unwrap();
        p.rodar("normalizar-audio", item()).unwrap();
        let cmds: Vec<String> = p.drenar().into_iter().filter_map(|a| match a { Acao::Processo { cmd, .. } => Some(cmd.join(" ")), _ => None }).collect();
        // com projeto, o legendar troca a legenda dentro do .fcproj; sem projeto, só o arquivo
        assert!(cmds.iter().any(|c| c.ends_with("legendar/aplicar.py _posts/2024/x/videos/01.mp4 --modo refinar --projeto _posts/2024/x/2024-01-01_MIC_x.fcproj")), "{cmds:?}");
        assert!(cmds.iter().any(|c| c.ends_with("legendar/aplicar.py _Cortes/A/c.mp4 --modo refinar")), "{cmds:?}");
        // normalizar: no projeto e no arquivo, quando há projeto
        assert!(cmds.iter().any(|c| c.contains("normalizar.py _posts/2024/x/videos/01.mp4 --lufs -14 --pico -1.5 --projeto _posts/2024/x/2024-01-01_MIC_x.fcproj")), "{cmds:?}");
        assert!(cmds.iter().any(|c| c.ends_with("normalizar.py _Cortes/A/c.mp4 --lufs -14 --pico -1.5")), "{cmds:?}");
    }
}
