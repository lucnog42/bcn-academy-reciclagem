//! A conversa com `src/painel/api.py serve`: um processo filho, uma linha JSON por mensagem.
//!
//! Escrever e ler acontecem em threads próprias (nada de E/S no quadro). As respostas e os
//! eventos caem numa fila; o `poll` do app esvazia a fila no thread da interface, e cada
//! resposta volta com o `Pedido` que a originou, para o app saber onde guardar.

use serde_json::{Value, json};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{Sender, channel};
use std::sync::{Arc, Mutex};

pub type Acordar = Arc<Mutex<Option<rune::Waker>>>;

/// Para que serve cada pedido em voo: decide o que fazer com a resposta.
#[derive(Clone, Debug, PartialEq)]
pub enum Pedido {
    Ping,
    Posts,
    Cortes,
    Estados,
    Marcar,
    Miniatura(String),
    Quadro(String),
    Original(String),
    Quadros(String),
    Exportar,
    Abrir,
    Tira(String),
    Palavras(String),
    Gerar,
    Processo(String),
    Claude(String),
    /// estado do motion de um item (a pasta)
    Motion(String),
    /// uma mudança no motion (contexto, referência, aprovar…); a resposta pede o estado de novo
    MotionAcao(String),
    MotionSugerir(String),
    /// gravar/testar a chave da API
    Chave,
    VideoModelos,
    VideoPrompt(String),
    VideoGerar,
    /// a IA das sugestões escrevendo/melhorando o briefing ("id#motion") ou o prompt ("id#video")
    PromptIa(String),
    /// troca a marca ativa; a resposta reinicia o motor
    TrocarMarca,
    ModelosPrompt,
    /// "id#alvo": aplicar um modelo de prompt ao momento
    ModeloAplicar(String),
    /// "id#alvo": a IA propõe três abordagens
    Abordagens(String),
    /// id do momento: procurar b-roll no acervo
    BrollCandidatos(String),
    /// id do momento: gravar a sequência escolhida
    BrollSequencia(String),
    // clientes, importar, roteiros, motion (extra.rs)
    CriarMarca,
    Fontes,
    /// id da fonte: adicionar, ativar, remover, indexar
    FonteAcao(String),
    FonteContar(String),
    FonteTranscrever(String),
    Roteiros,
    RoteiroIdeias,
    RoteiroEscrever,
    Roteiro(String),
    RoteiroAcao(String),
    RoteiroAprovar(String),
    RoteiroExportar(String),
    MotionHf(String),
    Biblioteca,
    MotionReusar(String),
}

#[derive(Debug)]
pub enum Chegada {
    Resposta { pedido: Pedido, ok: bool, resultado: Value, erro: String },
    Evento(Value),
    Caiu(String),
}

pub struct Ponte {
    envio: Sender<String>,
    fila: Arc<Mutex<Vec<Value>>>,
    em_voo: HashMap<u64, Pedido>,
    proximo: u64,
    filho: Option<Child>,
}

impl Ponte {
    /// Sobe `python3 <raiz>/src/painel/api.py serve`. O acervo vem da marca ativa, ou de `acervo`
    /// quando foi forçado (vai como $NG3_ACERVO).
    pub fn abrir(raiz: &Path, acervo: Option<&Path>, acordar: Acordar) -> Result<Ponte, String> {
        let script: PathBuf = raiz.join("src").join("painel").join("api.py");
        if !script.exists() {
            return Err(format!("não achei {} (rode com --raiz <pasta do projeto>)", script.display()));
        }
        let mut cmd = Command::new(std::env::var("NG3_PYTHON").unwrap_or_else(|_| "python3".into()));
        if let Some(a) = acervo { cmd.env("NG3_ACERVO", a); }
        let mut filho = cmd
            .arg(&script)
            .arg("serve")
            .current_dir(raiz)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| format!("não deu para rodar o python3: {e}"))?;
        let mut stdin = filho.stdin.take().ok_or("sem stdin")?;
        let stdout = filho.stdout.take().ok_or("sem stdout")?;
        let (envio, recebe) = channel::<String>();
        std::thread::Builder::new().name("ponte-envio".into()).spawn(move || {
            for linha in recebe {
                if stdin.write_all(linha.as_bytes()).and_then(|_| stdin.write_all(b"\n")).and_then(|_| stdin.flush()).is_err() {
                    break;
                }
            }
        }).map_err(|e| e.to_string())?;
        let fila = Arc::new(Mutex::new(Vec::new()));
        let fila_leitor = fila.clone();
        std::thread::Builder::new().name("ponte-leitura".into()).spawn(move || {
            let acordar_todos = |a: &Acordar| { if let Some(w) = a.lock().unwrap().as_ref() { w() } };
            for linha in BufReader::new(stdout).lines() {
                let Ok(linha) = linha else { break };
                if let Ok(v) = serde_json::from_str::<Value>(&linha) {
                    fila_leitor.lock().unwrap().push(v);
                    acordar_todos(&acordar);
                }
            }
            fila_leitor.lock().unwrap().push(json!({"evento": "caiu"}));
            acordar_todos(&acordar);
        }).map_err(|e| e.to_string())?;
        Ok(Ponte { envio, fila, em_voo: HashMap::new(), proximo: 1, filho: Some(filho) })
    }

    pub fn pedir(&mut self, pedido: Pedido, metodo: &str, dados: Value) {
        let id = self.proximo;
        self.proximo += 1;
        self.em_voo.insert(id, pedido);
        let linha = json!({"id": id, "metodo": metodo, "dados": dados}).to_string();
        let _ = self.envio.send(linha);
    }

    pub fn em_voo(&self, p: &Pedido) -> bool {
        self.em_voo.values().any(|x| x == p)
    }

    /// Tudo que chegou desde a última vez, já casado com o pedido.
    pub fn colher(&mut self) -> Vec<Chegada> {
        let brutos: Vec<Value> = std::mem::take(&mut *self.fila.lock().unwrap());
        let mut out = Vec::with_capacity(brutos.len());
        for v in brutos {
            if let Some(id) = v.get("id").and_then(Value::as_u64) {
                let Some(pedido) = self.em_voo.remove(&id) else { continue };
                out.push(Chegada::Resposta {
                    pedido,
                    ok: v.get("ok").and_then(Value::as_bool).unwrap_or(false),
                    resultado: v.get("resultado").cloned().unwrap_or(Value::Null),
                    erro: v.get("erro").and_then(Value::as_str).unwrap_or("").to_string(),
                });
            } else if v.get("evento").and_then(Value::as_str) == Some("caiu") {
                out.push(Chegada::Caiu("o processo do Python terminou".into()));
            } else {
                out.push(Chegada::Evento(v));
            }
        }
        out
    }
}

impl Drop for Ponte {
    fn drop(&mut self) {
        if let Some(mut f) = self.filho.take() {
            let _ = f.kill();
            let _ = f.wait();
        }
    }
}
