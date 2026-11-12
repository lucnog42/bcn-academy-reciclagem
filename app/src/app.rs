//! Estado do painel e tudo que muda ele: respostas da ponte, filtros, seleção, tarefas.

use crate::dados::{self, Corte, Estados, MotionEstado, Post, Tira, VideoModelo};
use crate::filtro::{self, Filtro, Ordem, Status};
use crate::plugins::{Acao, Plugins};
use crate::ponte::{Acordar, Chegada, Pedido, Ponte};
use rune::{Image, ImageCache, TextEdit};
use serde_json::{Value, json};
use std::collections::{BTreeSet, HashMap, HashSet, VecDeque};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Aba {
    #[default]
    Posts,
    Recomendados,
    Cortes,
    Plugins,
    Config,
}

impl Aba {
    pub const TODAS: [Aba; 5] = [Aba::Posts, Aba::Recomendados, Aba::Cortes, Aba::Plugins, Aba::Config];
    /// abas sem lista de posts/cortes (plugins, configurações)
    pub fn sem_lista(self) -> bool { matches!(self, Aba::Plugins | Aba::Config) }
    pub fn rotulo(self) -> &'static str {
        match self {
            Aba::Posts => "posts",
            Aba::Recomendados => "recomendados",
            Aba::Cortes => "cortes",
            Aba::Plugins => "plugins",
            Aba::Config => "chaves e config",
        }
    }
}

/// O que está aberto no preview.
#[derive(Clone, Debug, PartialEq)]
pub enum Alvo {
    Post(String),  // nome da pasta
    Corte(String), // caminho relativo do corte
}

pub struct Preview {
    pub alvo: Alvo,
    /// vídeo em foco (caminho relativo) e o quadro escolhido na tira
    pub video: Option<String>,
    pub quadro: usize,
    pub palavras: Vec<(f32, f32, String)>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Tamanho {
    Compacto,
    #[default]
    Normal,
    Grande,
}

impl Tamanho {
    pub const TODOS: [Tamanho; 3] = [Tamanho::Compacto, Tamanho::Normal, Tamanho::Grande];
    pub fn rotulo(self) -> &'static str {
        match self { Tamanho::Compacto => "compacto", Tamanho::Normal => "normal", Tamanho::Grande => "grande" }
    }
    /// largura mínima do card (pt)
    pub fn card(self) -> f32 {
        match self { Tamanho::Compacto => 150.0, Tamanho::Normal => 210.0, Tamanho::Grande => 300.0 }
    }
    /// altura da imagem numa linha da grade (as larguras seguem o formato de cada mídia)
    pub fn altura(self) -> f32 {
        match self { Tamanho::Compacto => 230.0, Tamanho::Normal => 300.0, Tamanho::Grande => 400.0 }
    }
    /// card mais estreito que isso não cabe os botões: a imagem é recortada um pouco
    pub fn minimo(self) -> f32 {
        match self { Tamanho::Compacto => 165.0, Tamanho::Normal => 180.0, Tamanho::Grande => 215.0 }
    }
}

/// Uma linha da grade justificada: cada card com a largura do formato da sua mídia.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Linha {
    pub altura: f32,
    /// (posição na página, largura do card)
    pub cards: Vec<(usize, f32)>,
}

/// Linhas justificadas (como um álbum de fotos): as proporções enchem a largura, todas
/// com a mesma altura; a última linha fica na altura alvo, sem esticar.
pub fn justificar(props: &[f32], largura: f32, alvo: f32, minimo: f32, gap: f32) -> Vec<Linha> {
    let largura = largura.max(minimo);
    let props: Vec<f32> = props.iter().map(|p| p.clamp(0.4, 2.4).max(minimo / alvo)).collect();
    let mut linhas = vec![];
    let mut ini = 0;
    while ini < props.len() {
        let mut soma = 0.0;
        let mut fim = ini;
        while fim < props.len() {
            let n = (fim - ini + 1) as f32;
            let com = soma + props[fim];
            if fim > ini && com * alvo + gap * (n - 1.0) > largura {
                // fica com o que deixar a altura mais perto do alvo
                let h_sem = (largura - gap * (n - 2.0)) / soma;
                let h_com = (largura - gap * (n - 1.0)) / com;
                if (h_com - alvo).abs() < (h_sem - alvo).abs() { soma = com; fim += 1; }
                break;
            }
            soma = com;
            fim += 1;
        }
        let n = (fim - ini) as f32;
        let ultima = fim == props.len() && soma * alvo + gap * (n - 1.0) < largura;
        let h = if ultima { alvo } else { (largura - gap * (n - 1.0)) / soma };
        linhas.push(Linha { altura: h, cards: (ini..fim).map(|i| (i, props[i] * h)).collect() });
        ini = fim;
    }
    linhas
}

pub const POR_PAGINA: [usize; 4] = [48, 96, 192, 0];

/// A seção Motion do preview: o item (pasta), o que a api disse e o que se edita aqui.
pub struct MotionUi {
    pub pasta: String,
    pub estado: Option<MotionEstado>,
    pub contexto: TextEdit,
    pub contexto_salvo: String,
    pub textos: HashMap<String, TextEdit>,
    pub sugerindo: bool,
    pub arrastando: bool,
    /// briefing do motion de cada momento, em edição
    pub briefings: HashMap<String, TextEdit>,
    /// o que a IA devolveu por "id#alvo": (alternativas, nota)
    pub alternativas: HashMap<String, (Vec<String>, String)>,
    /// pedidos à IA em andamento ("id#alvo")
    pub pensando: HashSet<String>,
    /// as três abordagens que a IA propôs, por "id#alvo"
    pub abordagens: HashMap<String, Vec<crate::dados::Abordagem>>,
    /// b-roll: os candidatos escolhidos, em ordem, por momento
    pub broll_sel: HashMap<String, Vec<String>>,
}

pub struct Tarefa {
    pub id: String,
    pub dono: String,
    pub comando: String,
    pub linhas: VecDeque<String>,
    pub fim: Option<bool>,
}

pub struct App {
    /// raiz do projeto (src/, config/, plugins/)
    pub raiz: PathBuf,
    /// o acervo da marca ativa (vem no ping; vazio até lá, a menos que --acervo)
    pub base: PathBuf,
    pub acervo_forcado: Option<PathBuf>,
    pub marca: String,
    pub nome_marca: String,
    pub marcas: Vec<String>,
    /// a ponte caiu de propósito (troca de marca): reabrir no próximo colher
    pub reiniciar: bool,
    pub ponte: Option<Ponte>,
    pub erro_ponte: Option<String>,
    pub acordar: Acordar,
    pub imagens: ImageCache,

    pub aba: Aba,
    /// de onde veio a seleção (posts/recomendados ou cortes) quando se está na aba plugins
    pub origem: Aba,
    pub busca: TextEdit,
    pub filtro: Filtro,
    pub posts: Vec<Post>,
    pub cortes: Vec<Corte>,
    pub estados: Estados,
    pub carregando: bool,
    /// índices de `posts` (ou `cortes`) que passam no filtro, na ordem mostrada
    pub visiveis: Vec<usize>,
    pub versao: u64,
    pub colunas: usize,
    pub largura: f32,
    pub tamanho: Tamanho,
    pub pagina: usize,
    pub por_pagina: usize,
    /// busca: cada tecla soma 1; o filtro roda quando a contagem para de mudar por 180 ms
    pub busca_tecla: u64,
    pub busca_vista: (u64, f64),

    pub selecao: BTreeSet<String>,
    /// caminho relativo da mídia -> miniatura (pronta ou carregando)
    pub miniaturas: HashMap<String, Image>,
    /// quadro grande do preview: (vídeo, índice) -> imagem
    pub quadros: HashMap<(String, usize), Image>,
    pub tiras: HashMap<String, (Tira, Image)>,
    pub caminhos_quadros: HashMap<String, Vec<String>>,
    pub ultimo_exportado: Option<String>,
    pub originais: HashMap<String, Image>,
    pub querem_miniatura: Vec<String>,
    pub falhas: HashSet<String>,

    pub preview: Option<Preview>,
    pub tarefas: Vec<Tarefa>,
    pub tarefas_abertas: bool,
    pub aviso: Option<String>,
    pub aviso_desde: Option<f64>,
    pub claude: bool,
    pub plugins: Plugins,
    pub escala: f32,
    /// grade justificada da página, refeita quando a versão, a largura ou o tamanho mudam
    pub grade_cache: std::cell::RefCell<((u64, u32, usize), Vec<Linha>)>,
    pub motion: Option<MotionUi>,
    pub motion_seq: u64,
    /// painel da chave da API do Claude
    pub chave: TextEdit,
    pub chave_aberta: bool,
    pub chave_info: ChaveInfo,
    /// escolha em edição no painel da IA (vira a escolhida ao salvar)
    pub ia_provedor: String,
    pub ia_modelo: TextEdit,
    pub ia_base: TextEdit,
    /// vídeo com IA (OpenRouter): os modelos e o formulário aberto num momento
    pub video_modelos: Vec<VideoModelo>,
    pub modelos_prompt: Vec<crate::dados::ModeloPrompt>,
    pub video_form: Option<VideoForm>,
    /// a chave do OpenRouter para o vídeo, no mesmo painel das chaves (independe da IA das sugestões)
    pub chave_video: TextEdit,
}

pub struct VideoForm {
    pub id: String,
    pub prompt: TextEdit,
    pub prompt_mexido: bool,
    pub modelo: String,
    pub duracao: Option<i64>,
    pub resolucao: String,
    /// "primeiro_quadro" | "referencias" | "nenhuma"
    pub refs: String,
    pub audio: bool,
}

#[derive(Clone, Debug, Default, serde::Deserialize)]
pub struct Provedor {
    pub id: String,
    pub nome: String,
    #[serde(default)]
    pub base_url: String,
    #[serde(default)]
    pub modelo: String,
    /// precisa de chave (o Ollama local não precisa)
    #[serde(default)]
    pub chave: bool,
    #[serde(default)]
    pub tem_chave: bool,
}

#[derive(Clone, Debug, Default)]
pub struct ChaveInfo {
    /// a chave própria do vídeo com IA (separada da IA das sugestões)
    pub chave_video: bool,
    pub fim_video: String,
    pub provedor: String,
    pub nome: String,
    pub base_url: String,
    pub precisa_chave: bool,
    pub provedores: Vec<Provedor>,
    pub modelos: Vec<String>,
    /// "ambiente" (ANTHROPIC_API_KEY), "arquivo" (config.local.toml) ou ""
    pub origem: String,
    /// os 4 últimos caracteres, para reconhecer qual chave está em uso
    pub fim: String,
    pub modelo: String,
    pub valida: Option<bool>,
    pub erro: String,
    pub testando: bool,
}

impl App {
    pub fn novo() -> App {
        let raiz = crate::raiz();
        let acervo_forcado = crate::acervo_forcado();
        let base = acervo_forcado.clone().unwrap_or_default();
        let acordar: Acordar = Arc::new(Mutex::new(None));
        let a2 = acordar.clone();
        let imagens = ImageCache::new(Arc::new(move || {
            if let Some(w) = a2.lock().unwrap().as_ref() { w() }
        }));
        let plugins = Plugins::carregar(&raiz, &base);
        App {
            raiz, base, acervo_forcado, marca: String::new(), nome_marca: String::new(), marcas: vec![], reiniciar: false,
            ponte: None, erro_ponte: None, acordar, imagens,
            aba: Aba::Posts, origem: Aba::Posts, busca: TextEdit::new(""), filtro: Filtro::default(),
            posts: vec![], cortes: vec![], estados: Estados::new(), carregando: true,
            visiveis: vec![], versao: 0, colunas: 4, largura: 1300.0, tamanho: Tamanho::Normal,
            pagina: 0, por_pagina: 96, busca_tecla: 0, busca_vista: (0, 0.0),
            selecao: BTreeSet::new(), miniaturas: HashMap::new(), quadros: HashMap::new(),
            tiras: HashMap::new(), caminhos_quadros: HashMap::new(), ultimo_exportado: None, originais: HashMap::new(), querem_miniatura: vec![],
            falhas: HashSet::new(), preview: None, tarefas: vec![], tarefas_abertas: false,
            aviso: None, aviso_desde: None, claude: false, plugins, escala: 2.0,
            grade_cache: std::cell::RefCell::new(((u64::MAX, 0, 0), vec![])),
            motion: None, motion_seq: 0,
            chave: TextEdit::new(""), chave_aberta: false, chave_info: ChaveInfo::default(),
            ia_provedor: String::new(), ia_modelo: TextEdit::new(""), ia_base: TextEdit::new(""),
            video_modelos: vec![], modelos_prompt: vec![], video_form: None, chave_video: TextEdit::new(""),
        }
    }

    /// Chamado uma vez, com o waker da janela: sobe a ponte e pede os dados.
    pub fn iniciar(&mut self, waker: rune::Waker) {
        self.plugins.set_waker(&waker);
        *self.acordar.lock().unwrap() = Some(waker);
        if self.ponte.is_some() || !self.posts.is_empty() {
            return; // já carregado (cena de teste)
        }
        self.abrir_ponte();
    }

    fn abrir_ponte(&mut self) {
        match Ponte::abrir(&self.raiz, self.acervo_forcado.as_deref(), self.acordar.clone()) {
            Ok(mut p) => {
                p.pedir(Pedido::Ping, "ping", json!({}));
                p.pedir(Pedido::ModelosPrompt, "modelos_prompt", json!({}));
                p.pedir(Pedido::Estados, "estados", json!({}));
                p.pedir(Pedido::Posts, "posts", json!({}));
                p.pedir(Pedido::Cortes, "cortes", json!({}));
                self.ponte = Some(p);
            }
            Err(e) => {
                self.carregando = false;
                self.erro_ponte = Some(e);
            }
        }
    }

    pub fn pedir(&mut self, pedido: Pedido, metodo: &str, dados: Value) {
        if let Some(p) = self.ponte.as_mut() {
            if !p.em_voo(&pedido) {
                p.pedir(pedido, metodo, dados);
            }
        }
    }

    // ------------------------------------------------------------ filtros
    /// Filtro mudou: volta para a 1ª página.
    pub fn refiltrar(&mut self) {
        self.pagina = 0;
        self.recalcular();
        self.prefetch();
    }

    /// Mesma página (marcação, recarga): só recalcula a lista.
    pub fn recalcular(&mut self) {
        self.filtro.busca = self.busca.text.clone();
        self.visiveis = match self.aba {
            Aba::Posts => filtro::posts(&self.posts, &self.estados, &self.filtro),
            Aba::Recomendados => filtro::recomendados(&self.posts, &self.estados, &self.filtro),
            Aba::Cortes => filtro::cortes(&self.cortes, &self.filtro),
            Aba::Plugins | Aba::Config => vec![],
        };
        self.pagina = self.pagina.min(self.n_paginas() - 1);
        self.versao += 1;
    }

    // ------------------------------------------------------------ páginas
    pub fn n_paginas(&self) -> usize { filtro::paginas(self.visiveis.len(), self.por_pagina) }

    /// Os índices (em posts/cortes) da página mostrada.
    pub fn na_pagina(&self) -> &[usize] {
        &self.visiveis[filtro::pagina(self.visiveis.len(), self.pagina, self.por_pagina)]
    }

    /// Proporção (largura/altura) do item `i` de posts ou cortes, conforme a aba.
    pub fn proporcao(&self, i: usize) -> f32 {
        match self.aba {
            Aba::Cortes => self.cortes.get(i).map_or(1.0, |c| c.proporcao()),
            _ => self.posts.get(i).map_or(1.0, |p| p.proporcao()),
        }
    }

    /// As linhas da grade desta página (calculadas uma vez por versão/largura).
    pub fn linhas(&self) -> std::cell::Ref<'_, Vec<Linha>> {
        let chave = (self.versao, self.largura.round() as u32, self.tamanho as usize);
        if self.grade_cache.borrow().0 != chave {
            let props: Vec<f32> = self.na_pagina().iter().map(|&i| self.proporcao(i)).collect();
            let l = justificar(&props, self.largura, self.tamanho.altura(), self.tamanho.minimo(),
                               crate::ui::GAP);
            *self.grade_cache.borrow_mut() = (chave, l);
        }
        std::cell::Ref::map(self.grade_cache.borrow(), |c| &c.1)
    }

    pub fn ir_pagina(&mut self, p: usize, tx: &mut rune::Tx) {
        let p = p.min(self.n_paginas() - 1);
        if p != self.pagina {
            self.pagina = p;
            self.versao += 1;
            self.prefetch();
            tx.scroll_to_y(if self.aba == Aba::Recomendados { "lista" } else { "grade" }, 0.0);
        }
    }

    pub fn por_pagina(&mut self, n: usize) {
        // mantém o 1º item da página atual à vista
        let primeiro = filtro::pagina(self.visiveis.len(), self.pagina, self.por_pagina).start;
        self.por_pagina = n;
        self.pagina = if n == 0 { 0 } else { primeiro / n };
        self.versao += 1;
        self.prefetch();
    }

    pub fn ordenar(&mut self, o: Ordem) {
        self.filtro.ordem = o;
        self.refiltrar();
    }

    pub fn tamanho(&mut self, t: Tamanho) {
        self.tamanho = t;
        self.colunas = crate::ui::colunas(self.largura, t);
        self.versao += 1;
    }

    pub fn selecionar_pagina(&mut self) {
        let chaves: Vec<String> = self.na_pagina().iter().filter_map(|&i| match self.aba {
            Aba::Cortes => self.cortes.get(i).map(|c| c.arquivo.clone()),
            _ => self.posts.get(i).map(|p| p.nome.clone()),
        }).collect();
        let todas = chaves.iter().all(|c| self.selecao.contains(c));
        for c in chaves {
            if todas { self.selecao.remove(&c); } else { self.selecao.insert(c); }
        }
        self.versao += 1;
    }

    /// Miniaturas da página atual e da próxima, antes de rolar até elas; as que ficaram
    /// longe são soltas (a memória das imagens decodificadas volta).
    pub fn prefetch(&mut self) {
        if self.aba.sem_lista() { return; }
        let r = filtro::pagina(self.visiveis.len(), self.pagina, self.por_pagina);
        let fim = if self.por_pagina == 0 { r.end.min(r.start + 200) } else { (r.end + self.por_pagina).min(self.visiveis.len()) };
        let perto: Vec<String> = self.visiveis[r.start..fim].iter().filter_map(|&i| self.capa_de(i)).collect();
        for m in &perto {
            if !self.miniaturas.contains_key(m) && !self.falhas.contains(m) { self.querem_miniatura.push(m.clone()); }
        }
        if self.miniaturas.len() > 900 {
            let manter: HashSet<&String> = perto.iter().collect();
            self.miniaturas.retain(|k, _| manter.contains(k));
        }
    }

    fn capa_de(&self, i: usize) -> Option<String> {
        match self.aba {
            Aba::Cortes => self.cortes.get(i).map(|c| c.capa().to_string()),
            _ => self.posts.get(i).and_then(|p| p.capa().map(str::to_string)),
        }
    }

    /// Chamado a cada tecla na busca; o filtro roda no `poll`, 180 ms depois da última.
    pub fn tecla_busca(&mut self, tx: &mut rune::Tx) {
        self.busca_tecla += 1;
        tx.wake_after(std::time::Duration::from_millis(190));
    }

    pub fn busca_assentou(&mut self, agora: f64) -> bool {
        if self.busca.text == self.filtro.busca { return false; }
        if self.busca_vista.0 != self.busca_tecla {
            self.busca_vista = (self.busca_tecla, agora);
            return false;
        }
        if agora - self.busca_vista.1 >= 0.18 {
            self.refiltrar();
            return true;
        }
        false
    }

    pub fn trocar_aba(&mut self, aba: Aba) {
        if self.aba != aba {
            // a seleção é de posts ou de cortes: só some quando muda o tipo de item
            let tipo = |a: Aba| match a { Aba::Cortes => 1, Aba::Plugins | Aba::Config => 2, _ => 0 };
            if tipo(aba) != 2 && tipo(self.aba) != 2 && tipo(aba) != tipo(self.aba) {
                self.selecao.clear();
            }
            if !aba.sem_lista() { self.origem = aba; }
            self.aba = aba;
            self.refiltrar();
        }
    }

    /// Itens para um plugin: o que está selecionado (ou um item só, vindo do preview).
    pub fn itens_plugin(&self, so: Option<&Alvo>) -> Vec<Value> {
        let posts: Vec<&Post> = match so {
            Some(Alvo::Post(n)) => self.post(n).into_iter().collect(),
            Some(Alvo::Corte(_)) => vec![],
            None if self.origem != Aba::Cortes => self.selecao.iter().filter_map(|n| self.post(n)).collect(),
            None => vec![],
        };
        let cortes: Vec<&Corte> = match so {
            Some(Alvo::Corte(a)) => self.corte(a).into_iter().collect(),
            Some(Alvo::Post(_)) => vec![],
            None if self.origem == Aba::Cortes => self.selecao.iter().filter_map(|a| self.corte(a)).collect(),
            None => vec![],
        };
        let mut v: Vec<Value> = posts.iter().map(|p| json!({
            "tipo": "post", "nome": p.nome, "pasta": p.pasta, "pilar": p.pilar, "data": p.data,
            "videos": p.videos().collect::<Vec<_>>(), "imagens": p.imagens().collect::<Vec<_>>(),
            "legenda": p.gancho, "projeto": p.arquivo_projeto,
        })).collect();
        v.extend(cortes.iter().map(|c| json!({
            "tipo": "corte", "nome": c.arquivo, "arquivo": c.arquivo, "pilar": c.pilar, "tema": c.tema,
            "videos": c.videos, "imagens": [], "projeto": c.arquivo_projeto,
        })));
        v
    }

    /// Quantos dos itens servem para o plugin (pelo `aplicaA` dele).
    pub fn servem(&self, aplica: &[String], itens: &[Value]) -> usize {
        itens.iter().filter(|i| aplica.is_empty() || aplica.iter().any(|a| match a.as_str() {
            "video" => i["videos"].as_array().is_some_and(|v| !v.is_empty()),
            "imagem" => i["imagens"].as_array().is_some_and(|v| !v.is_empty()),
            "corte" => i["tipo"] == "corte",
            "post" => i["tipo"] == "post",
            _ => false,
        })).count()
    }

    pub fn rodar_plugin(&mut self, id: &str, so: Option<Alvo>) {
        let itens = self.itens_plugin(so.as_ref());
        if itens.is_empty() {
            self.aviso = Some("selecione posts ou cortes antes de rodar o plugin".into());
            return;
        }
        match self.plugins.rodar(id, itens) {
            Ok(()) => self.aviso = Some(format!("{id}: rodando")),
            Err(e) => self.aviso = Some(format!("{id}: {e}")),
        }
    }

    pub fn alternar_ano(&mut self, ano: &str) {
        if !self.filtro.anos.remove(ano) { self.filtro.anos.insert(ano.to_string()); }
        self.refiltrar();
    }

    pub fn alternar_pilar(&mut self, pilar: &str) {
        if !self.filtro.pilares.remove(pilar) { self.filtro.pilares.insert(pilar.to_string()); }
        self.refiltrar();
    }

    pub fn status(&mut self, st: Status) {
        self.filtro.status = st;
        self.refiltrar();
    }

    pub fn limpar_filtros(&mut self) {
        self.filtro = Filtro::default();
        self.busca = TextEdit::new("");
        self.refiltrar();
    }

    // ------------------------------------------------------------ marcações
    pub fn estado(&self, nome: &str) -> (bool, bool) {
        self.estados.get(nome).map_or((false, false), |e| (e.nao_interessante, e.repostado))
    }

    pub fn marcar(&mut self, nome: &str, ni: Option<bool>, rp: Option<bool>) {
        let e = self.estados.entry(nome.to_string()).or_default();
        if let Some(v) = ni { e.nao_interessante = v; }
        if let Some(v) = rp { e.repostado = v; }
        let mut dados = json!({"post": nome});
        if let Some(v) = ni { dados["nao_interessante"] = json!(v); }
        if let Some(v) = rp { dados["repostado"] = json!(v); }
        self.pedir(Pedido::Marcar, "marcar", dados);
        self.versao += 1;
    }

    pub fn alternar_selecao(&mut self, chave: &str) {
        if !self.selecao.remove(chave) { self.selecao.insert(chave.to_string()); }
        self.versao += 1;
    }

    pub fn post(&self, nome: &str) -> Option<&Post> { self.posts.iter().find(|p| p.nome == nome) }
    pub fn corte(&self, arq: &str) -> Option<&Corte> { self.cortes.iter().find(|c| c.arquivo == arq) }

    // ------------------------------------------------------------ mídia
    /// Pede miniaturas das mídias que entraram na tela (chamado de `on_visible_rows`).
    pub fn querer_miniaturas(&mut self, linhas: std::ops::Range<usize>) -> bool {
        let pag = self.na_pagina().to_vec();
        let posicoes: Vec<usize> = {
            let ls = self.linhas();
            ls.get(linhas.start.min(ls.len())..(linhas.end + 1).min(ls.len())).unwrap_or(&[])
                .iter().flat_map(|l| l.cards.iter().map(|c| c.0)).collect()
        };
        for k in posicoes {
            let Some(&i) = pag.get(k) else { continue };
            if let Some(m) = self.capa_de(i) && !self.miniaturas.contains_key(&m) && !self.falhas.contains(&m) {
                self.querem_miniatura.push(m);
            }
        }
        false
    }

    pub fn querer_lista(&mut self, linhas: std::ops::Range<usize>) -> bool {
        let pag = self.na_pagina().to_vec();
        for &i in pag.get(linhas.start.min(pag.len())..linhas.end.min(pag.len())).unwrap_or(&[]) {
            if let Some(m) = self.posts.get(i).and_then(|p| p.capa().map(str::to_string))
                && !self.miniaturas.contains_key(&m) && !self.falhas.contains(&m) {
                self.querem_miniatura.push(m);
            }
        }
        false
    }

    pub fn abrir_preview(&mut self, alvo: Alvo) {
        let video = match &alvo {
            Alvo::Post(n) => self.post(n).and_then(|p| p.videos().next().cloned()),
            Alvo::Corte(a) => self.corte(a).map(|c| c.capa().to_string()),
        };
        let imagens: Vec<String> = match &alvo {
            Alvo::Post(n) => self.post(n).map(|p| p.imagens().cloned().collect()).unwrap_or_default(),
            Alvo::Corte(_) => vec![],
        };
        // imagens do carrossel: um .jpg de 720 px do cache, não o original de 1440 px
        for img in imagens {
            if !self.originais.contains_key(&img) {
                self.pedir(Pedido::Original(img.clone()), "miniatura", json!({"arquivo": img, "px": 720}));
            }
        }
        let pasta = match &alvo {
            Alvo::Post(n) => self.post(n).map(|p| p.pasta.clone()),
            Alvo::Corte(a) => Some(a.clone()),
        };
        self.motion = pasta.map(|pasta| {
            self.pedir(Pedido::Motion(pasta.clone()), "motion", json!({"pasta": pasta}));
            MotionUi { pasta, estado: None, contexto: TextEdit::new(""), contexto_salvo: String::new(),
                       textos: HashMap::new(), sugerindo: false, arrastando: false,
                       briefings: HashMap::new(), alternativas: HashMap::new(), pensando: HashSet::new(),
                       abordagens: HashMap::new(), broll_sel: HashMap::new() }
        });
        self.preview = Some(Preview { alvo, video: None, quadro: 0, palavras: vec![] });
        if let Some(v) = video { self.focar_video(v); }
    }

    pub fn focar_video(&mut self, v: String) {
        if let Some(p) = self.preview.as_mut() {
            p.video = Some(v.clone());
            p.quadro = 0;
            p.palavras.clear();
        }
        if !self.tiras.contains_key(&v) {
            self.pedir(Pedido::Tira(v.clone()), "tira", json!({"arquivo": v, "n": 16, "px": 200}));
        }
        self.escolher_quadro(0);
        self.pedir(Pedido::Palavras(v.clone()), "palavras", json!({"video": v}));
    }

    pub fn escolher_quadro(&mut self, i: usize) {
        let Some(p) = self.preview.as_mut() else { return };
        p.quadro = i;
        let Some(v) = p.video.clone() else { return };
        // os 16 quadros vêm de uma vez (só quadros-chave, ~0,3 s); aqui só se decodifica
        // o escolhido e os vizinhos, para as setas serem instantâneas
        match self.caminhos_quadros.get(&v).cloned() {
            Some(cs) => {
                for k in [i, i + 1, i.wrapping_sub(1)] {
                    if let Some(c) = cs.get(k) && !self.quadros.contains_key(&(v.clone(), k)) {
                        let im = self.imagens.file(c, 480.0, self.escala);
                        self.quadros.insert((v.clone(), k), im);
                    }
                }
            }
            None => self.pedir(Pedido::Quadros(v.clone()), "quadros", json!({"arquivo": v, "n": 16, "px": 720})),
        }
        self.versao += 1;
    }

    /// O quadro em resolução cheia, como PNG, na pasta `quadros/` do post (ou do corte).
    pub fn exportar_quadro(&mut self) {
        let Some(v) = self.preview.as_ref().and_then(|p| p.video.clone()) else { return };
        let t = self.tempo_do_quadro();
        self.pedir(Pedido::Exportar, "exportar_quadro", json!({"arquivo": v, "t": t}));
        self.aviso = Some("exportando o quadro…".into());
    }

    pub fn abrir_projeto(&mut self, arquivo: &str) {
        self.pedir(Pedido::Abrir, "abrir", json!({"arquivo": arquivo}));
        self.aviso = Some(format!("abrindo {}", arquivo.rsplit('/').next().unwrap_or(arquivo)));
    }

    /// Abre a pasta do post (ou da pasta de cortes) no gerenciador de arquivos.
    pub fn abrir_pasta(&mut self, rel: &str) {
        self.pedir(Pedido::Abrir, "abrir", json!({"arquivo": rel}));
        self.aviso = Some(format!("abrindo a pasta {}", rel.rsplit('/').next().unwrap_or(rel)));
    }

    pub fn abrir_pasta_quadros(&mut self) {
        if let Some(d) = self.ultimo_exportado.clone() {
            let pasta = d.rsplit_once('/').map(|x| x.0.to_string()).unwrap_or(d);
            self.pedir(Pedido::Abrir, "abrir", json!({"arquivo": pasta}));
        }
    }

    fn preview_imagens(&self) -> Vec<String> {
        match self.preview.as_ref().map(|p| &p.alvo) {
            Some(Alvo::Post(n)) => self.post(n).map(|p| p.imagens().cloned().collect()).unwrap_or_default(),
            _ => vec![],
        }
    }

    /// No preview: anda pela tira de quadros (setas).
    pub fn passo_quadro(&mut self, d: i32) {
        let Some(p) = &self.preview else { return };
        let Some(v) = &p.video else { return };
        let n = self.tiras.get(v).map_or(0, |(t, _)| t.n);
        if n == 0 { return; }
        let q = (p.quadro as i32 + d).rem_euclid(n as i32) as usize;
        self.escolher_quadro(q);
    }

    pub fn tempo_do_quadro(&self) -> f32 {
        let Some(p) = &self.preview else { return 0.0 };
        let Some(v) = &p.video else { return 0.0 };
        self.tiras.get(v).and_then(|(t, _)| t.tempos.get(p.quadro).copied()).unwrap_or(0.0)
    }

    /// Toca no mpv (som e imagem), a partir do quadro escolhido.
    pub fn tocar(&mut self) {
        let Some(v) = self.preview.as_ref().and_then(|p| p.video.clone()) else { return };
        let t = self.tempo_do_quadro();
        let caminho = self.base.join(&v);
        match std::process::Command::new("mpv").arg(format!("--start={t:.2}")).arg("--force-window=yes")
            .arg(&caminho).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).spawn() {
            Ok(_) => {}
            Err(e) => self.aviso = Some(format!("não abriu o mpv ({e}); instale com: sudo pacman -S mpv")),
        }
    }

    // ------------------------------------------------------------ chave da API
    fn ler_chave_info(&mut self, r: &Value) {
        self.claude = r["claude"].as_bool().unwrap_or(false);
        let i = &mut self.chave_info;
        let txt = |k: &str| r[k].as_str().unwrap_or("").to_string();
        i.provedor = txt("provedor");
        i.chave_video = r["chave_video"].as_bool().unwrap_or(false);
        i.fim_video = txt("fim_video");
        i.nome = txt("nome");
        i.base_url = txt("base_url");
        i.precisa_chave = r["precisa_chave"].as_bool().unwrap_or(true);
        i.origem = txt("origem");
        i.fim = txt("fim");
        i.modelo = txt("modelo");
        i.valida = r["valida"].as_bool();
        i.erro = txt("erro");
        i.testando = false;
        if let Ok(ps) = serde_json::from_value::<Vec<Provedor>>(r["provedores"].clone()) { i.provedores = ps; }
        i.modelos = r["modelos"].as_array().map(|v| v.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .unwrap_or_default();
        // o painel passa a mostrar o que está valendo
        self.ia_provedor = i.provedor.clone();
        self.ia_modelo = TextEdit::new(&i.modelo);
        self.ia_base = TextEdit::new(&i.base_url);
        if let Some(m) = self.motion.as_mut() && let Some(e) = m.estado.as_mut() { e.chave = self.claude; }
    }

    pub fn ler_chave_info_pub(&mut self, r: &Value) { self.ler_chave_info(r) }

    /// O ping diz a marca ativa, o acervo dela e a ordem dos pilares.
    pub fn ler_marca(&mut self, r: &Value) {
        let txt = |k: &str| r[k].as_str().unwrap_or("").to_string();
        self.marca = txt("marca");
        self.nome_marca = txt("nome_marca");
        self.marcas = r["marcas"].as_array().map(|v| v.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .unwrap_or_default();
        definir_pilares(r["pilares"].as_array().map(|v| v.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .unwrap_or_default());
        let base = PathBuf::from(txt("base"));
        if !base.as_os_str().is_empty() && base != self.base {
            self.base = base;
            let w = self.acordar.lock().unwrap().clone();
            self.plugins = Plugins::carregar(&self.raiz, &self.base);
            if let Some(w) = w { self.plugins.set_waker(&w); }
        }
    }

    pub fn trocar_marca(&mut self, marca: &str) {
        if marca == self.marca { return; }
        self.pedir(Pedido::TrocarMarca, "trocar_marca", json!({"marca": marca}));
    }

    /// Fecha o motor e carrega tudo de novo (outra marca = outro acervo, outros pilares).
    fn recomecar(&mut self) {
        self.ponte = None;
        self.posts.clear();
        self.cortes.clear();
        self.estados = Estados::new();
        self.selecao.clear();
        self.preview = None;
        self.motion = None;
        self.miniaturas.clear();
        self.falhas.clear();
        self.querem_miniatura.clear();
        self.carregando = true;
        self.refiltrar();
        self.abrir_ponte();
    }

    /// Escolher um provedor no painel: preenche o endereço e o modelo padrão dele.
    pub fn escolher_provedor(&mut self, id: &str) {
        if self.ia_provedor == id { return; }
        let atual = id == self.chave_info.provedor;
        if let Some(p) = self.chave_info.provedores.iter().find(|p| p.id == id).cloned() {
            self.ia_provedor = p.id;
            self.ia_modelo = TextEdit::new(if atual { &self.chave_info.modelo } else { &p.modelo });
            self.ia_base = TextEdit::new(if atual { &self.chave_info.base_url } else { &p.base_url });
            self.chave = TextEdit::new("");
        }
    }

    pub fn provedor_em_edicao(&self) -> Option<&Provedor> {
        self.chave_info.provedores.iter().find(|p| p.id == self.ia_provedor)
    }

    /// Grava a escolha (provedor, modelo, endereço) e a chave digitada, se houver; remover tira a chave.
    pub fn salvar_chave(&mut self, remover: bool) {
        let mut dados = json!({"provedor": self.ia_provedor, "modelo": self.ia_modelo.text.trim(),
                               "base_url": self.ia_base.text.trim()});
        let chave = self.chave.text.trim().to_string();
        if remover {
            dados["chave"] = json!("");
            dados["remover"] = json!(true);
        } else if !chave.is_empty() {
            dados["chave"] = json!(chave);
        } else if self.provedor_em_edicao().is_some_and(|p| p.chave && !p.tem_chave) {
            self.aviso = Some("cole a chave antes de salvar".into());
            return;
        }
        self.chave_info.testando = true;
        self.pedir(Pedido::Chave, "chave", dados);
    }

    pub fn testar_chave(&mut self) {
        self.chave_info.testando = true;
        self.pedir(Pedido::Chave, "chave_testar", json!({}));
    }

    // ------------------------------------------------------------ motion
    fn motion_acao(&mut self, metodo: &str, mut dados: Value) {
        let Some(pasta) = self.motion.as_ref().map(|m| m.pasta.clone()) else { return };
        dados["pasta"] = json!(pasta);
        self.motion_seq += 1;
        self.pedir(Pedido::MotionAcao(format!("{pasta}#{}", self.motion_seq)), metodo, dados);
    }

    pub fn motion_recarregar(&mut self) {
        if let Some(pasta) = self.motion.as_ref().map(|m| m.pasta.clone()) {
            self.pedir(Pedido::Motion(pasta.clone()), "motion", json!({"pasta": pasta}));
        }
    }

    /// Grava o contexto escrito (se mudou desde a última vez).
    pub fn motion_salvar_contexto(&mut self) {
        let Some(m) = self.motion.as_mut() else { return };
        if m.contexto.text == m.contexto_salvo { return; }
        m.contexto_salvo = m.contexto.text.clone();
        let texto = m.contexto.text.clone();
        self.motion_acao("motion_contexto", json!({"texto": texto}));
    }

    pub fn motion_sugerir(&mut self) {
        self.motion_salvar_contexto();
        let Some(m) = self.motion.as_mut() else { return };
        if m.estado.as_ref().is_some_and(|e| !e.chave) {
            self.aviso = Some("sem chave da IA: clique no botão da IA no topo do painel".into());
            return;
        }
        m.sugerindo = true;
        let pasta = m.pasta.clone();
        self.pedir(Pedido::MotionSugerir(pasta.clone()), "motion_sugerir", json!({"pasta": pasta, "max": 4}));
        self.tarefas_abertas = true;
        self.aviso = Some(format!("pedindo os momentos a {}…", self.chave_info.nome));
    }

    /// Aprovar leva o texto e o briefing como estão nos campos (editados ou não).
    pub fn motion_status(&mut self, id: &str, status: &str) {
        let texto = self.motion.as_ref().and_then(|m| m.textos.get(id)).map(|e| e.text.clone());
        let briefing = self.motion.as_ref().and_then(|m| m.briefings.get(id)).map(|e| e.text.clone());
        let mut mud = json!({"status": status});
        if let Some(t) = texto { mud["texto"] = json!(t); }
        if let Some(b) = briefing { mud["briefing"] = json!(b); }
        self.motion_acao("motion_marcar", json!({"id": id, "mudancas": mud}));
    }

    pub fn motion_mover(&mut self, id: &str, delta: f32) {
        let Some(mo) = self.motion.as_ref().and_then(|m| m.estado.as_ref())
            .and_then(|e| e.sugestoes.iter().find(|x| x.id == id)).cloned() else { return };
        let ini = (mo.ini + delta).max(0.0);
        self.motion_acao("motion_marcar", json!({"id": id, "mudancas": {"ini": ini, "fim": ini + (mo.fim - mo.ini)}}));
    }

    pub fn motion_referencias(&mut self, arquivos: &[PathBuf]) {
        let lista: Vec<String> = arquivos.iter().map(|p| p.display().to_string()).collect();
        self.motion_acao("motion_referencias", json!({"arquivos": lista}));
        self.aviso = Some(format!("{} imagem(ns) nas referências", lista.len()));
    }

    pub fn motion_abrir_referencias(&mut self) {
        self.motion_acao("motion_referencias", json!({"arquivos": [], "abrir": true}));
    }

    pub fn motion_quadro_ref(&mut self) {
        let Some(v) = self.preview.as_ref().and_then(|p| p.video.clone()) else { return };
        let t = self.tempo_do_quadro();
        self.motion_acao("motion_quadro", json!({"video": v, "t": t}));
        self.aviso = Some("quadro adicionado às referências".into());
    }

    /// Referências de um momento: "adicionar" (arquivos), "quadro" (o quadro do preview),
    /// "alternar" / "tirar" (arquivo), "pasta" (abre a pasta dele).
    pub fn motion_ref(&mut self, id: &str, acao: &str, mut extra: Value) {
        extra["id"] = json!(id);
        extra["acao"] = json!(acao);
        if acao == "quadro" {
            let Some(v) = self.preview.as_ref().and_then(|p| p.video.clone()) else { return };
            extra["video"] = json!(v);
            extra["t"] = json!(self.tempo_do_quadro());
            self.aviso = Some("quadro ligado a este momento".into());
        }
        self.motion_acao("motion_ref", extra);
    }

    pub fn motion_ref_arquivos(&mut self, id: &str, arquivos: &[PathBuf]) {
        let lista: Vec<String> = arquivos.iter().map(|p| p.display().to_string()).collect();
        self.aviso = Some(format!("{} imagem(ns) ligadas a este momento", lista.len()));
        self.motion_ref(id, "adicionar", json!({"arquivos": lista}));
    }

    /// Um momento novo no quadro escolhido do preview (para um b-roll gerado por IA).
    pub fn motion_novo_aqui(&mut self) {
        let Some(v) = self.preview.as_ref().and_then(|p| p.video.clone()) else { return };
        let t = self.tempo_do_quadro();
        self.motion_acao("motion_novo", json!({"video": v, "ini": t, "fim": t + 4.0, "tipo": "broll"}));
        self.aviso = Some("momento novo no quadro escolhido".into());
    }

    // ------------------------------------------------------------ vídeo com IA (OpenRouter)
    pub fn video_abrir(&mut self, id: &str) {
        if self.video_form.as_ref().is_some_and(|f| f.id == id) { self.video_form = None; return; }
        let Some(pasta) = self.motion.as_ref().map(|m| m.pasta.clone()) else { return };
        let anterior = self.video_form.as_ref().map(|f| (f.modelo.clone(), f.resolucao.clone()));
        let (modelo, resolucao) = anterior.unwrap_or_else(|| {
            let m = self.video_modelos.iter().find(|m| m.formatos.iter().any(|f| f == "9:16")).or(self.video_modelos.first());
            (m.map(|m| m.id.clone()).unwrap_or_default(), m.and_then(|m| m.resolucoes.first().cloned()).unwrap_or_default())
        });
        let duracao = self.video_modelos.iter().find(|m| m.id == modelo).and_then(|m| m.duracoes.iter().copied().find(|d| *d > 0));
        self.video_form = Some(VideoForm { id: id.to_string(), prompt: TextEdit::new(""), prompt_mexido: false,
                                           modelo, duracao, resolucao, refs: "primeiro_quadro".into(), audio: false });
        if self.video_modelos.is_empty() { self.pedir(Pedido::VideoModelos, "video_modelos", json!({})); }
        self.pedir(Pedido::VideoPrompt(id.to_string()), "video_prompt", json!({"pasta": pasta, "id": id}));
    }

    pub fn video_modelo(&mut self, id: &str) {
        let m = self.video_modelos.iter().find(|m| m.id == id).cloned();
        if let (Some(f), Some(m)) = (self.video_form.as_mut(), m) {
            f.modelo = m.id.clone();
            if !f.duracao.is_some_and(|d| m.duracoes.contains(&d)) { f.duracao = m.duracoes.iter().copied().find(|d| *d > 0); }
            if !m.resolucoes.contains(&f.resolucao) { f.resolucao = m.resolucoes.first().cloned().unwrap_or_default(); }
            if !m.audio { f.audio = false; }
        }
    }

    /// Guarda (ou tira) a chave do OpenRouter usada no vídeo, sem trocar a IA das sugestões.
    pub fn video_salvar_chave(&mut self, remover: bool) {
        let chave = self.chave_video.text.trim().to_string();
        if !remover && chave.is_empty() { self.aviso = Some("cole a chave do OpenRouter".into()); return; }
        self.chave_video = TextEdit::new("");
        self.pedir(Pedido::Chave, "chave", json!({"so_chave": "video", "chave": if remover { String::new() } else { chave }}));
        if self.video_modelos.is_empty() && !remover { self.pedir(Pedido::VideoModelos, "video_modelos", json!({})); }
    }

    pub fn tem_chave_video(&self) -> bool { self.chave_info.chave_video }

    pub fn video_gerar(&mut self) {
        let Some(pasta) = self.motion.as_ref().map(|m| m.pasta.clone()) else { return };
        let Some(f) = self.video_form.as_ref() else { return };
        if f.modelo.is_empty() { self.aviso = Some("escolha um modelo de vídeo".into()); return; }
        let formato = self.video_modelos.iter().find(|m| m.id == f.modelo)
            .map(|m| if m.formatos.is_empty() || m.formatos.iter().any(|x| x == "9:16") { "9:16" } else { "16:9" })
            .unwrap_or("9:16");
        let dados = json!({"pasta": pasta, "id": f.id, "modelo": f.modelo, "prompt": f.prompt.text,
                           "duracao": f.duracao, "resolucao": f.resolucao, "refs": f.refs, "audio": f.audio,
                           "formato": formato});
        let aviso = format!("gerando o vídeo em {} (pode levar alguns minutos)", f.modelo);
        self.pedir(Pedido::VideoGerar, "video_gerar", dados);
        self.aviso = Some(aviso);
        self.tarefas_abertas = true;
        self.video_form = None;
    }

    // ------------------------------------------------------------ prompts com a IA das sugestões
    /// Pede à IA das sugestões o briefing do motion ("motion") ou o prompt do vídeo ("video") do
    /// momento, partindo do que já está escrito (vazio = escreve do zero).
    pub fn prompt_ia(&mut self, id: &str, alvo: &str) {
        let Some(pasta) = self.motion.as_ref().map(|m| m.pasta.clone()) else { return };
        if !self.claude { self.aviso = Some("sem chave da IA das sugestões: veja a aba chaves e config".into()); return; }
        let (atual, modelo) = if alvo == "video" {
            let f = self.video_form.as_ref();
            (f.map(|f| f.prompt.text.clone()).unwrap_or_default(), f.map(|f| f.modelo.clone()).unwrap_or_default())
        } else {
            (self.motion.as_ref().and_then(|m| m.briefings.get(id)).map(|e| e.text.clone()).unwrap_or_default(), String::new())
        };
        let chave = format!("{id}#{alvo}");
        if let Some(m) = self.motion.as_mut() { m.pensando.insert(chave.clone()); }
        self.pedir(Pedido::PromptIa(chave), "prompt_ia",
                   json!({"pasta": pasta, "id": id, "alvo": alvo, "atual": atual, "modelo": modelo}));
    }

    /// Procura b-roll para o momento em todas as fontes do acervo (com IA: ela escreve as buscas).
    pub fn broll_procurar(&mut self, id: &str, com_ia: bool) {
        let Some(pasta) = self.motion.as_ref().map(|m| m.pasta.clone()) else { return };
        if com_ia && !self.claude { self.aviso = Some("sem chave da IA das sugestões: veja a aba chaves e config".into()); return; }
        if let Some(m) = self.motion.as_mut() { m.pensando.insert(format!("{id}#broll")); }
        self.pedir(Pedido::BrollCandidatos(id.to_string()), "broll_candidatos",
                   json!({"pasta": pasta, "id": id, "ia": com_ia, "n": 5}));
    }

    /// Clique num candidato: entra no fim da sequência (até 3) ou sai dela.
    pub fn broll_alternar(&mut self, id: &str, cid: &str) {
        let Some(m) = self.motion.as_mut() else { return };
        let sel = m.broll_sel.entry(id.to_string()).or_default();
        if let Some(i) = sel.iter().position(|x| x == cid) { sel.remove(i); }
        else if sel.len() < 3 { sel.push(cid.to_string()); }
        else { self.aviso = Some("no máximo 3 pedaços por momento".into()); }
    }

    /// Grava a sequência escolhida (a duração do momento é dividida entre os pedaços) e aprova.
    pub fn broll_usar(&mut self, id: &str, limpar: bool) {
        let Some(m) = self.motion.as_ref() else { return };
        let pasta = m.pasta.clone();
        let itens: Vec<Value> = if limpar { vec![] } else {
            let cands = m.estado.as_ref().and_then(|e| e.sugestoes.iter().find(|x| x.id == id))
                .and_then(|x| x.broll.as_ref()).map(|b| b.candidatos.clone()).unwrap_or_default();
            m.broll_sel.get(id).cloned().unwrap_or_default().iter()
                .filter_map(|c| cands.iter().find(|x| &x.id == c))
                .map(|c| json!({"arquivo": c.arquivo, "tipo": c.tipo, "ini": c.ini})).collect()
        };
        self.pedir(Pedido::BrollSequencia(id.to_string()), "broll_sequencia",
                   json!({"pasta": pasta, "id": id, "itens": itens, "aprovar": !limpar}));
    }

    /// As miniaturas dos candidatos já vêm prontas (caminho do .jpg): só carregar.
    fn miniaturas_broll(&mut self) {
        let caminhos: Vec<String> = self.motion.as_ref().and_then(|m| m.estado.as_ref())
            .map(|e| e.sugestoes.iter().filter_map(|s| s.broll.as_ref())
                .flat_map(|b| b.candidatos.iter().map(|c| c.miniatura.clone())).filter(|c| !c.is_empty()).collect())
            .unwrap_or_default();
        for c in caminhos {
            if !self.miniaturas.contains_key(&c) {
                let im = self.imagens.file(&c, 160.0, 2.0);
                self.miniaturas.insert(c, im);
            }
        }
    }

    pub fn miniaturas_broll_pub(&mut self) { self.miniaturas_broll() }

    /// Os modelos de prompt que servem para um momento (alvo motion/video, pelo tipo dele).
    pub fn modelos_para(&self, alvo: &str, tipo: &str) -> Vec<crate::dados::ModeloPrompt> {
        self.modelos_prompt.iter().filter(|m| m.alvo == alvo && (m.tipos.is_empty() || m.tipos.iter().any(|t| t == tipo)))
            .cloned().collect()
    }

    /// Escreve o briefing/prompt do momento a partir de um modelo (antes de gerar).
    pub fn aplicar_modelo(&mut self, id: &str, alvo: &str, modelo: &str) {
        let Some(pasta) = self.motion.as_ref().map(|m| m.pasta.clone()) else { return };
        self.pedir(Pedido::ModeloAplicar(format!("{id}#{alvo}")), "modelo_aplicar",
                   json!({"pasta": pasta, "id": id, "modelo": modelo}));
    }

    /// A IA propõe três abordagens diferentes; nada é gravado até você escolher uma.
    pub fn pedir_abordagens(&mut self, id: &str, alvo: &str) {
        let Some(pasta) = self.motion.as_ref().map(|m| m.pasta.clone()) else { return };
        if !self.claude { self.aviso = Some("sem chave da IA das sugestões: veja a aba chaves e config".into()); return; }
        let atual = if alvo == "video" {
            self.video_form.as_ref().map(|f| f.prompt.text.clone()).unwrap_or_default()
        } else {
            self.motion.as_ref().and_then(|m| m.briefings.get(id)).map(|e| e.text.clone()).unwrap_or_default()
        };
        let modelo = if alvo == "video" { self.video_form.as_ref().map(|f| f.modelo.clone()).unwrap_or_default() } else { String::new() };
        let chave = format!("{id}#{alvo}#abordagens");
        if let Some(m) = self.motion.as_mut() { m.pensando.insert(chave.clone()); m.abordagens.remove(&chave); }
        self.pedir(Pedido::Abordagens(chave), "prompt_ia",
                   json!({"pasta": pasta, "id": id, "alvo": alvo, "atual": atual, "modelo": modelo, "abordagens": true}));
    }

    /// Escolher uma abordagem: vira o texto (e o briefing fica gravado); as outras somem.
    pub fn usar_abordagem(&mut self, id: &str, alvo: &str, texto: &str) {
        if let Some(m) = self.motion.as_mut() { m.abordagens.remove(&format!("{id}#{alvo}#abordagens")); }
        self.usar_alternativa(id, alvo, texto);
        if alvo == "video" {
            self.motion_acao("motion_salvar", json!({"id": id, "campos": {"prompt_video": texto}}));
        }
    }

    /// Troca o texto pelo de uma alternativa que a IA deu.
    pub fn usar_alternativa(&mut self, id: &str, alvo: &str, texto: &str) {
        if alvo == "video" {
            if let Some(f) = self.video_form.as_mut() && f.id == id { f.prompt = TextEdit::new(texto); f.prompt_mexido = true; }
        } else if let Some(m) = self.motion.as_mut() {
            m.briefings.insert(id.to_string(), TextEdit::new(texto));
            self.salvar_briefing(id);
        }
    }

    pub fn salvar_briefing(&mut self, id: &str) {
        let Some(b) = self.motion.as_ref().and_then(|m| m.briefings.get(id)).map(|e| e.text.clone()) else { return };
        self.motion_acao("motion_salvar", json!({"id": id, "campos": {"briefing": b}}));
    }

    fn prompt_chegou(&mut self, chave: &str, r: Value) {
        let Some((id, alvo)) = chave.split_once('#') else { return };
        let principal = r["principal"].as_str().unwrap_or("").to_string();
        let alts: Vec<String> = r["alternativas"].as_array()
            .map(|v| v.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default();
        let nota = r["nota"].as_str().unwrap_or("").to_string();
        if alvo == "video" {
            if let Some(f) = self.video_form.as_mut() && f.id == id { f.prompt = TextEdit::new(&principal); f.prompt_mexido = true; }
        }
        if let Some(m) = self.motion.as_mut() {
            m.pensando.remove(chave);
            if alvo == "motion" { m.briefings.insert(id.to_string(), TextEdit::new(&principal)); }
            m.alternativas.insert(chave.to_string(), (alts, nota));
        }
        self.aviso = Some(format!("{} escreveu {}", r["ia"].as_str().unwrap_or("a IA"),
                                  if alvo == "video" { "o prompt do vídeo" } else { "o briefing do motion" }));
        self.versao += 1;
    }

    pub fn motion_tirar(&mut self, arquivo: &str) {
        self.motion_acao("motion_tirar", json!({"arquivo": arquivo}));
    }

    /// Leva o preview ao vídeo e ao quadro mais perto do início do momento.
    pub fn motion_ir(&mut self, id: &str) {
        let Some(mo) = self.motion.as_ref().and_then(|m| m.estado.as_ref())
            .and_then(|e| e.sugestoes.iter().find(|x| x.id == id)).cloned() else { return };
        if self.preview.as_ref().and_then(|p| p.video.as_ref()) != Some(&mo.video) {
            self.focar_video(mo.video.clone());
        }
        if let Some((tr, _)) = self.tiras.get(&mo.video) {
            let q = tr.tempos.iter().enumerate()
                .min_by(|a, b| (a.1 - mo.ini).abs().total_cmp(&(b.1 - mo.ini).abs())).map_or(0, |x| x.0);
            self.escolher_quadro(q);
        }
    }

    pub(crate) fn motion_chegou(&mut self, pasta: &str, r: Value) {
        let Ok(e) = serde_json::from_value::<MotionEstado>(r) else { return };
        let refs = e.referencias.clone();
        let Some(m) = self.motion.as_mut().filter(|m| m.pasta == pasta) else { return };
        // o contexto só é trocado se ninguém está editando (o que está na tela = o gravado)
        if m.contexto.text == m.contexto_salvo {
            m.contexto = TextEdit::new(&e.contexto);
            m.contexto_salvo = e.contexto.clone();
        }
        for s in &e.sugestoes {
            let b = m.briefings.entry(s.id.clone()).or_insert_with(|| TextEdit::new(&s.briefing));
            if b.text.trim().is_empty() && !s.briefing.is_empty() { *b = TextEdit::new(&s.briefing); }
            let campo = m.textos.entry(s.id.clone()).or_insert_with(|| TextEdit::new(&s.texto));
            if s.status != "sugerido" { *campo = TextEdit::new(&s.texto); }
        }
        let refs: Vec<String> = refs.into_iter()
            .chain(e.sugestoes.iter().flat_map(|s| s.referencias.iter().cloned())).collect();
        m.estado = Some(e);
        for r in refs {
            if !self.miniaturas.contains_key(&r) { self.querem_miniatura.push(r); }
        }
        self.versao += 1;
    }

    // ------------------------------------------------------------ tarefas
    pub fn gerar_selecao(&mut self) {
        if self.selecao.is_empty() { return; }
        let itens: Vec<String> = self.selecao.iter().cloned().collect();
        let dados = if self.aba == Aba::Cortes {
            json!({"cortes": itens})
        } else {
            json!({"posts": itens})
        };
        self.pedir(Pedido::Gerar, "gerar", dados);
        self.tarefas_abertas = true;
    }

    pub fn gerar_um(&mut self, chave: String, corte: bool) {
        let dados = if corte {
            json!({"cortes": [chave]})
        } else {
            json!({"posts": [chave]})
        };
        self.pedir(Pedido::Gerar, "gerar", dados);
        self.tarefas_abertas = true;
    }

    pub fn rodar_processo(&mut self, dono: &str, cmd: Vec<String>) {
        let tag = format!("{dono}:{}", self.tarefas.len());
        self.pedir(Pedido::Processo(tag), "processo", json!({"cmd": cmd, "dono": dono}));
        self.tarefas_abertas = true;
    }

    fn evento_tarefa(&mut self, v: &Value) -> bool {
        let id = v["tarefa"].as_str().unwrap_or("").to_string();
        if v.get("inicio").is_some() {
            self.tarefas.push(Tarefa {
                id, dono: v["dono"].as_str().unwrap_or("").into(),
                comando: v["comando"].as_str().unwrap_or("").into(), linhas: VecDeque::new(), fim: None,
            });
            return true;
        }
        let Some(t) = self.tarefas.iter_mut().find(|t| t.id == id) else { return false };
        if let Some(l) = v.get("linha").and_then(Value::as_str) {
            t.linhas.push_back(l.to_string());
            while t.linhas.len() > 400 { t.linhas.pop_front(); }
        }
        if v.get("fim").is_some() {
            let ok = v["ok"].as_bool().unwrap_or(false);
            t.fim = Some(ok);
            let dono = t.dono.clone();
            self.aviso = Some(if ok { format!("{dono}: concluído") } else { format!("{dono}: falhou (veja as tarefas)") });
            if v.get("motion").is_some() {
                if let Some(m) = self.motion.as_mut() { m.sugerindo = false; }
                self.motion_recarregar();
            }
            if dono == "inserir-motion" { self.motion_recarregar(); }
            if dono == "video-ia" && !ok { self.motion_recarregar(); }
            if v.get("recarregar").is_some() {
                self.pedir(Pedido::Posts, "posts", json!({"recarregar": true}));
                self.pedir(Pedido::Cortes, "cortes", json!({"recarregar": true}));
            }
            self.plugins.tarefa_terminou(&dono, ok);
        }
        true
    }

    // ------------------------------------------------------------ poll
    pub fn colher(&mut self) -> bool {
        let mut mudou = false;
        // pedidos de miniatura acumulados pelo on_visible_rows
        for m in std::mem::take(&mut self.querem_miniatura) {
            if !self.miniaturas.contains_key(&m) {
                self.pedir(Pedido::Miniatura(m.clone()), "miniatura", json!({"arquivo": m}));
            }
        }
        for acao in self.plugins.drenar() {
            mudou = true;
            match acao {
                Acao::Processo { dono, cmd } => self.rodar_processo(&dono, cmd),
                Acao::Gerar { itens, cortes, forcar } => {
                    let mut dados = if cortes { json!({"cortes": itens}) } else { json!({"posts": itens}) };
                    dados["forcar"] = json!(forcar);
                    self.pedir(Pedido::Gerar, "gerar", dados);
                    self.tarefas_abertas = true;
                }
                Acao::Aviso(m) => self.aviso = Some(m),
            }
        }
        if self.reiniciar {
            self.reiniciar = false;
            self.recomecar();
            return true;
        }
        let Some(ponte) = self.ponte.as_mut() else { return mudou };
        let chegadas = ponte.colher();
        for c in chegadas {
            mudou = true;
            match c {
                Chegada::Caiu(e) => { self.erro_ponte = Some(e); self.ponte = None; break; }
                Chegada::Evento(v) => {
                    if v["evento"] == "tarefa" { self.evento_tarefa(&v); }
                    if v["evento"] == "posts_atualizados" {
                        self.pedir(Pedido::Posts, "posts", json!({}));
                        self.pedir(Pedido::Cortes, "cortes", json!({}));
                    }
                }
                Chegada::Resposta { pedido, ok: false, erro, .. } => match pedido {
                    Pedido::Miniatura(m) => { self.falhas.insert(m); }
                    Pedido::MotionSugerir(_) => {
                        if let Some(m) = self.motion.as_mut() { m.sugerindo = false; }
                        self.aviso = Some(erro);
                    }
                    Pedido::VideoModelos => self.aviso = Some(format!("modelos de vídeo: {erro}")),
                    Pedido::BrollCandidatos(id) => {
                        if let Some(m) = self.motion.as_mut() { m.pensando.remove(&format!("{id}#broll")); }
                        self.aviso = Some(format!("b-roll: {erro}"));
                    }
                    Pedido::PromptIa(chave) | Pedido::Abordagens(chave) => {
                        if let Some(m) = self.motion.as_mut() { m.pensando.remove(&chave); }
                        self.aviso = Some(format!("a IA não respondeu: {erro}"));
                    }
                    _ => self.aviso = Some(erro),
                },
                Chegada::Resposta { pedido, resultado, .. } => {
                    self.resposta(pedido, resultado);
                    if self.reiniciar { break; }
                }
            }
        }
        if self.reiniciar {
            self.reiniciar = false;
            self.recomecar();
        }
        mudou
    }

    fn resposta(&mut self, pedido: Pedido, r: Value) {
        match pedido {
            Pedido::Ping => { self.ler_marca(&r); self.ler_chave_info(&r) }
            Pedido::TrocarMarca => {
                self.aviso = Some(format!("marca ativa: {}", r["marca"].as_str().unwrap_or("")));
                self.reiniciar = true;
            }
            Pedido::Chave if r.get("so_chave").is_some() => {
                self.ler_chave_info(&r);
                self.aviso = Some(if self.tem_chave_video() { "chave do vídeo salva: já dá para gerar vídeo".into() }
                                  else { "chave do vídeo removida".into() });
            }
            Pedido::Chave => {
                self.ler_chave_info(&r);
                self.chave = TextEdit::new("");
                let nome = self.chave_info.nome.clone();
                self.aviso = Some(match (self.claude, self.chave_info.valida) {
                    (false, _) => format!("{nome}: sem chave"),
                    (true, Some(true)) if self.chave_info.erro.is_empty() => format!("{nome} pronto para as sugestões"),
                    (true, Some(true)) => format!("{nome}: {}", self.chave_info.erro),
                    (true, _) => format!("{nome}: {}", self.chave_info.erro),
                });
            }
            Pedido::Posts => {
                let primeira = self.posts.is_empty();
                self.posts = serde_json::from_value(r).unwrap_or_default();
                for p in &mut self.posts { p.preparar(); }
                self.carregando = false;
                if primeira { self.refiltrar() } else { self.recalcular() }
            }
            Pedido::Cortes => {
                self.cortes = serde_json::from_value(r).unwrap_or_default();
                for c in &mut self.cortes { c.preparar(); }
                self.recalcular();
            }
            Pedido::Estados | Pedido::Marcar => {
                self.estados = serde_json::from_value(r).unwrap_or_default();
                if matches!(self.aba, Aba::Recomendados) || self.filtro.status != Status::Todos {
                    self.recalcular();
                } else {
                    self.versao += 1;
                }
            }
            Pedido::Miniatura(m) => {
                if let Some(c) = r.as_str() {
                    let im = self.imagens.file(c, 320.0, self.escala);
                    self.miniaturas.insert(m, im);
                    self.versao += 1;
                }
            }
            Pedido::Original(img) => {
                if let Some(c) = r.as_str() {
                    let im = self.imagens.file(c, 240.0, self.escala);
                    self.originais.insert(img, im);
                    if self.originais.len() > 60 {
                        let manter: HashSet<String> = self.preview_imagens().into_iter().collect();
                        self.originais.retain(|k, _| manter.contains(k));
                    }
                }
            }
            Pedido::Quadros(v) => {
                let cs: Vec<String> = serde_json::from_value(r).unwrap_or_default();
                self.caminhos_quadros.insert(v.clone(), cs);
                if self.preview.as_ref().and_then(|p| p.video.as_ref()) == Some(&v) {
                    let q = self.preview.as_ref().map_or(0, |p| p.quadro);
                    self.escolher_quadro(q);
                }
            }
            Pedido::Exportar => {
                let rel = r["relativo"].as_str().unwrap_or("").to_string();
                self.aviso = Some(format!("quadro salvo em {rel}"));
                self.ultimo_exportado = Some(rel);
            }
            Pedido::Abrir => {}
            Pedido::Quadro(chave) => {
                if let (Some(c), Some((v, i))) = (r.as_str(), chave.rsplit_once('#')) {
                    let im = self.imagens.file(c, 480.0, self.escala);
                    self.quadros.insert((v.to_string(), i.parse().unwrap_or(0)), im);
                }
            }
            Pedido::Tira(v) => {
                if let Ok(t) = serde_json::from_value::<Tira>(r) {
                    let im = self.imagens.file(&t.arquivo, (t.largura * t.n as u32) as f32 / 2.0, self.escala);
                    self.tiras.insert(v.clone(), (t, im));
                    if self.preview.as_ref().and_then(|p| p.video.as_ref()) == Some(&v) {
                        let q = self.preview.as_ref().map_or(0, |p| p.quadro);
                        self.escolher_quadro(q);
                    }
                }
            }
            Pedido::Palavras(v) => {
                let ws: Vec<(f32, f32, String)> = serde_json::from_value(r).unwrap_or_default();
                if let Some(p) = self.preview.as_mut() && p.video.as_ref() == Some(&v) {
                    p.palavras = ws;
                }
            }
            Pedido::Gerar | Pedido::Processo(_) => {}
            Pedido::Claude(_) => {}
            Pedido::Motion(pasta) => { self.motion_chegou(&pasta, r); self.miniaturas_broll(); }
            Pedido::BrollCandidatos(id) => {
                if let Some(m) = self.motion.as_mut() { m.pensando.remove(&format!("{id}#broll")); m.broll_sel.remove(&id); }
                let n = r["candidatos"].as_array().map(|a| a.len()).unwrap_or(0);
                self.aviso = Some(if n == 0 { "nada no acervo para este momento: tente com IA ou reindexe".into() }
                                  else { format!("{n} candidato(s) de b-roll no acervo") });
                self.motion_recarregar();
            }
            Pedido::BrollSequencia(id) => {
                if let Some(m) = self.motion.as_mut() { m.broll_sel.remove(&id); }
                self.aviso = Some("sequência de b-roll gravada: rode o plugin Inserir motion para montar".into());
                self.motion_recarregar();
            }
            Pedido::MotionAcao(_) => {
                if r.get("abrir").is_some() { self.aviso = Some("abrindo a pasta de referências".into()); }
                self.motion_recarregar();
            }
            Pedido::MotionSugerir(_) => {}
            Pedido::VideoModelos => {
                self.video_modelos = serde_json::from_value(r).unwrap_or_default();
                let sem_modelo = self.video_form.as_ref().is_some_and(|f| f.modelo.is_empty());
                if sem_modelo {
                    let m = self.video_modelos.iter().find(|m| m.formatos.iter().any(|f| f == "9:16"))
                        .or(self.video_modelos.first()).map(|m| m.id.clone());
                    if let Some(m) = m { self.video_modelo(&m); }
                }
            }
            Pedido::VideoPrompt(id) => {
                if let (Some(f), Some(p)) = (self.video_form.as_mut(), r.as_str()) && f.id == id && !f.prompt_mexido {
                    f.prompt = TextEdit::new(p);
                }
            }
            Pedido::VideoGerar => {}
            Pedido::PromptIa(chave) => self.prompt_chegou(&chave, r),
            Pedido::ModelosPrompt => self.modelos_prompt = serde_json::from_value(r).unwrap_or_default(),
            Pedido::ModeloAplicar(chave) => {
                let txt = r["texto"].as_str().unwrap_or("").to_string();
                if let Some((id, alvo)) = chave.split_once('#') {
                    if alvo == "video" {
                        if let Some(f) = self.video_form.as_mut() && f.id == id { f.prompt = TextEdit::new(&txt); f.prompt_mexido = true; }
                    } else if let Some(m) = self.motion.as_mut() {
                        m.briefings.insert(id.to_string(), TextEdit::new(&txt));
                    }
                }
                self.motion_recarregar();
            }
            Pedido::Abordagens(chave) => {
                let ops: Vec<crate::dados::Abordagem> = serde_json::from_value(r["opcoes"].clone()).unwrap_or_default();
                if let Some(m) = self.motion.as_mut() { m.pensando.remove(&chave); m.abordagens.insert(chave, ops); }
                self.versao += 1;
            }
        }
    }

    /// Itens marcados para gerar, já com o rótulo certo para a aba.
    pub fn rotulo_selecao(&self) -> String {
        let n = self.selecao.len();
        match (self.aba, n) {
            (_, 0) => "nada selecionado".into(),
            (Aba::Cortes, 1) => "1 corte".into(),
            (Aba::Cortes, n) => format!("{n} cortes"),
            (_, 1) => "1 post".into(),
            (_, n) => format!("{n} posts"),
        }
    }

    pub fn mb_projeto(&self) -> f32 {
        self.selecao.iter().filter_map(|n| self.post(n)).map(|p| p.peso).sum()
    }
}

/// A ordem dos pilares da marca ativa (do ping): a cor de cada um é a sua posição.
static PILARES: std::sync::RwLock<Vec<String>> = std::sync::RwLock::new(Vec::new());

pub fn definir_pilares(ps: Vec<String>) { *PILARES.write().unwrap() = ps; }

pub fn pilar_cor(pilar: &str) -> usize {
    PILARES.read().unwrap().iter().position(|p| p == pilar).map(|i| i % 6).unwrap_or(6)
}

pub fn eh_video(s: &str) -> bool { dados::eh_video(s) }

#[cfg(test)]
mod grade_tests {
    use super::justificar;

    #[test]
    fn linhas_enchem_a_largura() {
        // 9:16, 4:5, 1:1, 16:9 ... numa largura de 1000
        let props = [0.5625, 0.8, 1.0, 1.777, 0.5625, 0.8, 1.0];
        let ls = justificar(&props, 1000.0, 250.0, 140.0, 12.0);
        assert!(ls.len() >= 2);
        for l in &ls[..ls.len() - 1] {
            let w: f32 = l.cards.iter().map(|c| c.1).sum::<f32>() + 12.0 * (l.cards.len() as f32 - 1.0);
            assert!((w - 1000.0).abs() < 0.5, "linha {w}");
            assert!(l.altura > 170.0 && l.altura < 360.0, "altura {}", l.altura);
        }
        // a proporção de cada card é a da mídia (ou o mínimo de largura)
        let l = &ls[0];
        assert!((l.cards[1].1 / l.altura - 0.8).abs() < 0.01);
        assert_eq!(ls.iter().map(|l| l.cards.len()).sum::<usize>(), props.len());
    }

    #[test]
    fn ultima_linha_nao_estica() {
        let ls = justificar(&[1.0], 1000.0, 250.0, 150.0, 12.0);
        assert_eq!(ls[0].altura, 250.0);
        assert_eq!(ls[0].cards[0].1, 250.0);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{Duration, Instant};

    /// Ponta a ponta com o Python de verdade: NG3_ACERVO_TESTE aponta para um acervo (de teste).
    #[test]
    fn ponte_carrega_marca_e_roda_plugin() {
        let Ok(base) = std::env::var("NG3_ACERVO_TESTE") else { return };
        unsafe {
            std::env::set_var("NG3_ACERVO", &base);
            std::env::set_var("NG3_RAIZ", concat!(env!("CARGO_MANIFEST_DIR"), "/.."));
        }
        let mut a = App::novo();
        a.iniciar(Arc::new(|| {}));
        let esperar = |a: &mut App, ate: &dyn Fn(&App) -> bool| {
            let t0 = Instant::now();
            while !ate(a) && t0.elapsed() < Duration::from_secs(60) {
                a.colher();
                std::thread::sleep(Duration::from_millis(20));
            }
            assert!(ate(a), "tempo esgotado");
        };
        esperar(&mut a, &|a| !a.posts.is_empty() && !a.cortes.is_empty());
        assert_eq!(a.visiveis.len(), a.posts.len());

        // filtro + marcação gravada pela api
        let nome = a.posts[0].nome.clone();
        a.marcar(&nome, None, Some(true));
        esperar(&mut a, &|a| a.ponte.as_ref().is_some_and(|p| !p.em_voo(&Pedido::Marcar)));
        assert!(a.estado(&nome).1);
        a.status(Status::Repostado);
        assert_eq!(a.visiveis.len(), 1);
        a.marcar(&nome, None, Some(false));

        // miniatura de um corte (a pasta é o item; a capa é o 1º vídeo)
        let corte = a.cortes[0].arquivo.clone();
        let capa = a.cortes[0].capa().to_string();
        assert!(!a.cortes[0].videos.is_empty());
        a.querem_miniatura.push(capa.clone());
        esperar(&mut a, &|a| a.miniaturas.contains_key(&capa));

        // plugin normalizar num corte, até a tarefa terminar
        a.trocar_aba(Aba::Cortes);
        a.alternar_selecao(&corte);
        a.trocar_aba(Aba::Plugins);
        a.rodar_plugin("normalizar-audio", None);
        esperar(&mut a, &|a| a.tarefas.iter().any(|t| t.fim.is_some()));
        let t = &a.tarefas[0];
        assert_eq!(t.fim, Some(true), "saída: {:?}", t.linhas);
        assert!(t.linhas.iter().any(|l| l.contains("LUFS")));
        let nome = capa.rsplit('/').next().unwrap().replace(".mp4", "_norm.mp4");
        let norm = std::path::Path::new(&base).join(&corte).join("saidas").join(nome);
        assert!(norm.exists());
        let _ = std::fs::remove_file(norm);
    }
}
