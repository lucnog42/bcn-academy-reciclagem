//! Clientes (trocar e criar), a aba Importar (pastas apontadas, sem cópia), a aba Roteiros
//! (roteiros recomendados a partir das falas transcritas) e os motions com HyperFrames.

use crate::app::{Aba, Alvo, App};
use crate::dados::{Banco, Cliente, Fonte, FonteConta, FormatoRoteiro, FuncaoRoteiro, Ideia, MotionPronto, Roteiro, RoteiroResumo};
use crate::ponte::Pedido;
use rune::TextEdit;
use serde_json::{Value, json};
use std::collections::HashMap;

pub struct Extra {
    // clientes
    pub clientes: Vec<Cliente>,
    pub clientes_aberto: bool,
    pub novo_cliente: TextEdit,
    pub novo_cliente_acervo: TextEdit,
    pub criando_cliente: bool,
    /// onde a chave/IA salva vale: "marca" (só o cliente ativo) ou "geral"
    pub chave_escopo: String,
    // importar
    pub fontes: Vec<Fonte>,
    pub tipos: Vec<(String, String)>,
    pub contagens: HashMap<String, FonteConta>,
    pub nova_raiz: TextEdit,
    pub novo_nome: TextEdit,
    pub novo_tipo: String,
    pub adicionando: bool,
    // roteiros
    pub roteiros: Vec<RoteiroResumo>,
    pub ideias: Vec<Ideia>,
    pub formatos: Vec<FormatoRoteiro>,
    pub funcoes: Vec<FuncaoRoteiro>,
    pub banco: Banco,
    pub aberto: Option<Roteiro>,
    pub tema: TextEdit,
    pub formato: String,
    pub duracao: u32,
    pub pensando_ideias: bool,
    pub escrevendo: bool,
    pub aprovando: bool,
    /// texto das falas novas em edição, por parte
    pub textos: HashMap<usize, TextEdit>,
    // motions prontos do cliente
    pub biblioteca: Vec<MotionPronto>,
}

impl Extra {
    pub fn novo() -> Extra {
        Extra {
            clientes: vec![], clientes_aberto: false, novo_cliente: TextEdit::new(""), novo_cliente_acervo: TextEdit::new(""),
            criando_cliente: false, chave_escopo: "marca".into(),
            fontes: vec![], tipos: vec![], contagens: HashMap::new(), nova_raiz: TextEdit::new(""), novo_nome: TextEdit::new(""),
            novo_tipo: "falas".into(), adicionando: false,
            roteiros: vec![], ideias: vec![], formatos: vec![], funcoes: vec![], banco: Banco::default(), aberto: None,
            tema: TextEdit::new(""), formato: String::new(), duracao: 0, pensando_ideias: false, escrevendo: false,
            aprovando: false, textos: HashMap::new(), biblioteca: vec![],
        }
    }
}

impl App {
    // ------------------------------------------------------------ clientes
    pub fn criar_cliente(&mut self) {
        let nome = self.x.novo_cliente.text.trim().to_string();
        if nome.is_empty() { self.aviso = Some("dê um nome ao cliente".into()); return; }
        self.x.criando_cliente = true;
        self.pedir(Pedido::CriarMarca, "criar_marca", json!({"nome": nome, "acervo": self.x.novo_cliente_acervo.text.trim()}));
    }

    pub fn nome_cliente(&self) -> String {
        if !self.nome_marca.is_empty() { self.nome_marca.clone() } else if !self.marca.is_empty() { self.marca.clone() }
        else { "Video Automation NG3".into() }
    }

    // ------------------------------------------------------------ importar
    pub fn fontes_recarregar(&mut self) { self.pedir(Pedido::Fontes, "fontes", json!({})); }

    pub fn fonte_adicionar(&mut self) {
        let raiz = self.x.nova_raiz.text.trim().to_string();
        if raiz.is_empty() { self.aviso = Some("cole o caminho da pasta (ou arraste a pasta para cá)".into()); return; }
        self.x.adicionando = true;
        self.pedir(Pedido::FonteAcao("+".into()), "fonte_adicionar",
                   json!({"raiz": raiz, "tipo": self.x.novo_tipo, "nome": self.x.novo_nome.text.trim()}));
    }

    pub fn fonte_acao(&mut self, id: &str, metodo: &str, extra: Value) {
        let mut d = json!({"id": id});
        if let (Some(o), Some(e)) = (d.as_object_mut(), extra.as_object()) { for (k, v) in e { o.insert(k.clone(), v.clone()); } }
        if metodo == "fonte_contar" {
            self.pedir(Pedido::FonteContar(id.into()), metodo, d);
        } else if metodo == "fonte_transcrever" {
            self.pedir(Pedido::FonteTranscrever(id.into()), metodo, d);
        } else {
            self.pedir(Pedido::FonteAcao(id.into()), metodo, d);
        }
    }

    pub fn soltar_pasta(&mut self, caminhos: &[std::path::PathBuf]) {
        if let Some(p) = caminhos.iter().find(|p| p.is_dir()) {
            self.x.nova_raiz = TextEdit::new(&p.display().to_string());
            if self.x.novo_nome.text.trim().is_empty() {
                self.x.novo_nome = TextEdit::new(&p.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default());
            }
        } else {
            self.aviso = Some("arraste uma PASTA (os arquivos dela são apontados, não copiados)".into());
        }
    }

    // ------------------------------------------------------------ roteiros
    pub fn roteiros_recarregar(&mut self) { self.pedir(Pedido::Roteiros, "roteiros", json!({})); }

    pub fn banco_atualizar(&mut self) {
        self.x.banco.montando = true;
        self.pedir(Pedido::FonteAcao("banco".into()), "falas_indexar", json!({}));
    }

    pub fn roteiro_ideias(&mut self) {
        if !self.claude { self.aviso = Some("sem chave da IA: veja chaves e config".into()); return; }
        self.x.pensando_ideias = true;
        self.pedir(Pedido::RoteiroIdeias, "roteiro_ideias", json!({"tema": self.x.tema.text.trim()}));
    }

    pub fn roteiro_escrever(&mut self, ideia: &str) {
        if !self.claude { self.aviso = Some("sem chave da IA: veja chaves e config".into()); return; }
        self.x.escrevendo = true;
        self.pedir(Pedido::RoteiroEscrever, "roteiro_escrever",
                   json!({"tema": if ideia.is_empty() { self.x.tema.text.trim().to_string() } else { String::new() },
                          "formato": self.x.formato, "duracao": self.x.duracao, "ideia": ideia}));
    }

    pub fn roteiro_abrir(&mut self, id: &str) { self.pedir(Pedido::Roteiro(id.into()), "roteiro", json!({"id": id})); }

    pub fn roteiro_editar(&mut self, acao: &str, i: usize, valor: Value) {
        let Some(id) = self.x.aberto.as_ref().map(|r| r.id.clone()) else { return };
        self.pedir(Pedido::RoteiroAcao(id.clone()), "roteiro_editar", json!({"id": id, "acao": acao, "i": i, "valor": valor}));
    }

    pub fn roteiro_texto_salvar(&mut self, i: usize) {
        let Some(t) = self.x.textos.get(&i).map(|e| e.text.trim().to_string()) else { return };
        self.roteiro_editar("texto", i, json!(t));
    }

    pub fn roteiro_excluir(&mut self) {
        let Some(id) = self.x.aberto.as_ref().map(|r| r.id.clone()) else { return };
        self.pedir(Pedido::RoteiroAcao(id.clone()), "roteiro_excluir", json!({"id": id}));
    }

    pub fn roteiro_aprovar(&mut self) {
        let Some(id) = self.x.aberto.as_ref().map(|r| r.id.clone()) else { return };
        self.x.aprovando = true;
        self.pedir(Pedido::RoteiroAprovar(id.clone()), "roteiro_aprovar", json!({"id": id}));
    }

    pub fn roteiro_exportar(&mut self) {
        let Some(id) = self.x.aberto.as_ref().map(|r| r.id.clone()) else { return };
        self.pedir(Pedido::RoteiroExportar(id.clone()), "roteiro_exportar", json!({"id": id}));
    }

    /// O projeto de um roteiro aprovado abre no preview, com os momentos de cada parte.
    pub fn roteiro_projeto(&mut self, pasta: &str) { self.abrir_preview(Alvo::Roteiro(pasta.to_string())); }

    // ------------------------------------------------------------ motion
    pub fn motion_hf(&mut self, id: &str, so_render: bool) {
        let Some(pasta) = self.motion.as_ref().map(|m| m.pasta.clone()) else { return };
        if !self.claude && !so_render { self.aviso = Some("sem chave da IA: ela escreve a composição".into()); return; }
        self.pedir(Pedido::MotionHf(id.into()), "motion_hf", json!({"pasta": pasta, "id": id, "so_render": so_render}));
        self.tarefas_abertas = true;
    }

    pub fn biblioteca_abrir(&mut self, id: &str) {
        if let Some(m) = self.motion.as_mut() {
            m.biblioteca_para = if m.biblioteca_para.as_deref() == Some(id) { None } else { Some(id.to_string()) };
        }
        self.pedir(Pedido::Biblioteca, "motion_biblioteca", json!({}));
    }

    pub fn motion_reusar(&mut self, id: &str, origem: &str) {
        let Some(pasta) = self.motion.as_ref().map(|m| m.pasta.clone()) else { return };
        if let Some(m) = self.motion.as_mut() { m.biblioteca_para = None; }
        self.pedir(Pedido::MotionReusar(id.into()), "motion_reusar", json!({"pasta": pasta, "id": id, "origem": origem}));
    }

    pub fn inserir_no_projeto(&mut self) {
        let Some(pasta) = self.motion.as_ref().map(|m| m.pasta.clone()) else { return };
        self.rodar_processo("inserir", vec!["python3".into(), "src/plano/momentos.py".into(), "inserir".into(), pasta,
                                            "--onde".into(), "projeto".into()]);
    }

    // ------------------------------------------------------------ respostas
    pub(crate) fn resposta_extra(&mut self, p: Pedido, r: Value) {
        match p {
            Pedido::CriarMarca => {
                self.x.criando_cliente = false;
                self.x.clientes_aberto = false;
                self.x.novo_cliente = TextEdit::new("");
                self.x.novo_cliente_acervo = TextEdit::new("");
                self.aviso = Some(format!("cliente criado: {} — edite config/marcas/{}/ para descrever a marca",
                                          r["nome"].as_str().unwrap_or(""), r["slug"].as_str().unwrap_or("")));
                self.reiniciar = true;
            }
            Pedido::Fontes => {
                self.x.fontes = serde_json::from_value(r["fontes"].clone()).unwrap_or_default();
                let mut tipos: Vec<(String, String)> = r["tipos"].as_object()
                    .map(|o| o.iter().map(|(k, v)| (k.clone(), v.as_str().unwrap_or("").to_string())).collect()).unwrap_or_default();
                let ordem = ["falas", "broll", "fotos", "referencias"];
                tipos.sort_by_key(|(k, _)| ordem.iter().position(|o| o == k).unwrap_or(9));
                self.x.tipos = tipos;
                let faltam: Vec<String> = self.x.fontes.iter()
                    .filter(|f| f.origem == "importada" && f.existe && !self.x.contagens.contains_key(&f.id))
                    .map(|f| f.id.clone()).collect();
                for id in faltam { self.fonte_acao(&id, "fonte_contar", json!({})); }
            }
            Pedido::FonteAcao(id) => {
                if id == "+" {
                    self.x.adicionando = false;
                    self.x.nova_raiz = TextEdit::new("");
                    self.x.novo_nome = TextEdit::new("");
                    self.aviso = Some(format!("pasta apontada: {} ({} arquivo(s) no índice). Nada foi copiado.",
                                              r["nome"].as_str().unwrap_or(""), r["indexados"].as_u64().unwrap_or(0)));
                    if let Some(fid) = r["id"].as_str() { let fid = fid.to_string(); self.fonte_acao(&fid, "fonte_contar", json!({})); }
                } else if id == "banco" {
                    self.aviso = Some("montando o banco de falas a partir das transcrições…".into());
                    return;
                } else {
                    self.aviso = Some("pronto".into());
                }
                self.fontes_recarregar();
            }
            Pedido::FonteContar(id) => {
                if let Ok(c) = serde_json::from_value::<FonteConta>(r) { self.x.contagens.insert(id, c); }
            }
            Pedido::FonteTranscrever(_) => {
                let cmd: Vec<String> = serde_json::from_value(r["cmd"].clone()).unwrap_or_default();
                if !cmd.is_empty() { self.rodar_processo("transcrever", cmd); }
            }
            Pedido::Roteiros => {
                self.x.roteiros = serde_json::from_value(r["roteiros"].clone()).unwrap_or_default();
                self.x.ideias = serde_json::from_value(r["ideias"].clone()).unwrap_or_default();
                self.x.formatos = serde_json::from_value(r["formatos"].clone()).unwrap_or_default();
                self.x.funcoes = serde_json::from_value(r["funcoes"].clone()).unwrap_or_default();
                self.x.banco = serde_json::from_value(r["banco"].clone()).unwrap_or_default();
                if self.x.formato.is_empty() && let Some(f) = self.x.formatos.first() {
                    self.x.formato = f.id.clone();
                    self.x.duracao = f.duracao;
                }
            }
            Pedido::RoteiroIdeias => {
                self.x.pensando_ideias = false;
                self.x.ideias = serde_json::from_value(r).unwrap_or_default();
            }
            Pedido::RoteiroEscrever | Pedido::Roteiro(_) | Pedido::RoteiroAcao(_) => {
                if matches!(p, Pedido::RoteiroEscrever) { self.x.escrevendo = false; }
                if r.get("partes").is_some() {
                    self.x.textos.clear();
                    self.x.aberto = serde_json::from_value(r).ok();
                    self.miniaturas_roteiro();
                } else {
                    self.x.aberto = None;                       // excluído
                    self.aviso = Some("roteiro excluído (fica em dados/…/roteiros/excluidos/)".into());
                }
                self.roteiros_recarregar();
            }
            Pedido::RoteiroAprovar(_) => {
                self.x.aprovando = false;
                let rot: Option<Roteiro> = serde_json::from_value(r).ok();
                if let Some(pasta) = rot.as_ref().and_then(|r| r.pasta.clone()) {
                    self.aviso = Some("roteiro aprovado: projeto criado com o primeiro corte (só material do acervo)".into());
                    self.x.aberto = rot;
                    self.roteiro_projeto(&pasta);
                }
                self.roteiros_recarregar();
            }
            Pedido::RoteiroExportar(_) => {
                self.aviso = Some(format!("roteiro em texto: {}", r["arquivo"].as_str().unwrap_or("")));
            }
            Pedido::MotionHf(_) => self.aviso = Some("HyperFrames: escrevendo e renderizando o motion (veja tarefas)".into()),
            Pedido::Biblioteca => self.x.biblioteca = serde_json::from_value(r).unwrap_or_default(),
            Pedido::MotionReusar(_) => { self.aviso = Some("motion reaproveitado neste momento".into()); self.motion_recarregar(); }
            _ => {}
        }
        self.versao += 1;
    }

    /// As miniaturas dos candidatos de cada parte já vêm prontas (caminho do .jpg).
    fn miniaturas_roteiro(&mut self) {
        let cs: Vec<String> = self.x.aberto.as_ref()
            .map(|r| r.partes.iter().flat_map(|p| p.cobertura.iter().map(|c| c.miniatura.clone())).filter(|c| !c.is_empty()).collect())
            .unwrap_or_default();
        for c in cs {
            if !self.miniaturas.contains_key(&c) {
                let im = self.imagens.file(&c, 160.0, 2.0);
                self.miniaturas.insert(c, im);
            }
        }
    }

    pub(crate) fn erro_extra(&mut self, p: Pedido, erro: String) {
        match p {
            Pedido::RoteiroIdeias => self.x.pensando_ideias = false,
            Pedido::RoteiroEscrever => self.x.escrevendo = false,
            Pedido::RoteiroAprovar(_) => self.x.aprovando = false,
            Pedido::CriarMarca => self.x.criando_cliente = false,
            Pedido::FonteAcao(_) => self.x.adicionando = false,
            _ => {}
        }
        self.aviso = Some(erro);
    }

    /// Ao entrar numa aba nova, o que ela precisa.
    pub fn ao_entrar(&mut self, aba: Aba) {
        match aba {
            Aba::Roteiros => self.roteiros_recarregar(),
            Aba::Importar => {
                self.x.contagens.clear();
                self.fontes_recarregar();
            }
            _ => {}
        }
    }
}
