//! O que a `api.py` devolve, como structs. Campos com nomes do Python.

use serde::Deserialize;
use std::collections::BTreeMap;

#[derive(Clone, Debug, Default, Deserialize)]
pub struct Partes {
    #[serde(default)]
    pub alcance: f32,
    #[serde(default)]
    pub evergreen: f32,
    #[serde(default)]
    pub material: f32,
    #[serde(default)]
    pub maturidade: f32,
    #[serde(default)]
    pub penal: f32,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Post {
    pub id: String,
    pub pasta: String,
    pub nome: String,
    pub data: String,
    pub ano: String,
    pub pilar: String,
    #[serde(default)]
    pub conf: f32,
    #[serde(default)]
    pub curtidas: i64,
    #[serde(default)]
    pub score: f32,
    #[serde(default)]
    pub partes: Partes,
    #[serde(default)]
    pub percentil: f32,
    #[serde(default)]
    pub idade: i64,
    pub tipo: String,
    #[serde(default)]
    pub seq: String,
    #[serde(default)]
    pub n_video: usize,
    #[serde(default)]
    pub n_img: usize,
    #[serde(default)]
    pub midias: Vec<String>,
    #[serde(default)]
    pub thumb: String,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub gancho: String,
    #[serde(default)]
    pub fala: String,
    #[serde(default)]
    pub projeto: bool,
    #[serde(default)]
    pub arquivo_projeto: String,
    #[serde(default)]
    pub mb: f32,
    #[serde(default)]
    pub peso: f32,
    /// tamanho da capa (para a grade mostrar no formato dela)
    #[serde(default)]
    pub w: u32,
    #[serde(default)]
    pub h: u32,
    /// texto da busca já em minúsculas, montado uma vez ao carregar
    #[serde(skip)]
    pub busca_txt: String,
}

impl Post {
    /// A mídia que representa o post na grade: a 1ª imagem, ou o 1º vídeo.
    pub fn capa(&self) -> Option<&str> {
        if !self.thumb.is_empty() {
            return Some(&self.thumb);
        }
        self.midias.first().map(|s| s.as_str())
    }
    pub fn videos(&self) -> impl Iterator<Item = &String> {
        self.midias.iter().filter(|m| eh_video(m))
    }
    /// largura / altura da capa; sem medida, a do formato da sequência ("1080×1920")
    pub fn proporcao(&self) -> f32 {
        if self.w > 0 && self.h > 0 { return self.w as f32 / self.h as f32; }
        let mut it = self.seq.split('×').filter_map(|x| x.trim().parse::<f32>().ok());
        match (it.next(), it.next()) { (Some(a), Some(b)) if b > 0.0 => a / b, _ => 1.0 }
    }
    pub fn imagens(&self) -> impl Iterator<Item = &String> {
        self.midias.iter().filter(|m| !eh_video(m))
    }
    /// Texto onde a busca procura: pasta, legenda, fala.
    pub fn busca(&self) -> std::borrow::Cow<'_, str> {
        if self.busca_txt.is_empty() {
            format!("{} {} {}", self.nome, self.gancho, self.fala).to_lowercase().into()
        } else {
            self.busca_txt.as_str().into()
        }
    }
    pub fn preparar(&mut self) {
        self.busca_txt = format!("{} {} {}", self.nome, self.gancho, self.fala).to_lowercase();
    }
}

/// Uma pasta de `_Cortes`: os vídeos dela formam um projeto só.
#[derive(Clone, Debug, Deserialize)]
pub struct Corte {
    /// a pasta, relativa ao acervo (é a chave do item)
    pub arquivo: String,
    #[serde(default)]
    pub videos: Vec<String>,
    #[serde(default)]
    pub w: u32,
    #[serde(default)]
    pub h: u32,
    pub nome_arq: String,
    pub tema: String,
    #[serde(default)]
    pub tema_raiz: String,
    pub pilar: String,
    #[serde(default)]
    pub seg: f32,
    #[serde(default)]
    pub mb: f32,
    #[serde(default)]
    pub fala: String,
    #[serde(default)]
    pub gancho: String,
    #[serde(default)]
    pub projeto: bool,
    #[serde(default)]
    pub arquivo_projeto: String,
    #[serde(default)]
    pub nome_projeto: String,
    #[serde(skip)]
    pub busca_txt: String,
}

impl Corte {
    /// a mídia que representa a pasta na grade: o 1º vídeo
    pub fn capa(&self) -> &str { self.videos.first().map_or(self.arquivo.as_str(), |s| s.as_str()) }
    pub fn proporcao(&self) -> f32 {
        if self.w > 0 && self.h > 0 { self.w as f32 / self.h as f32 } else { 9.0 / 16.0 }
    }
    pub fn busca(&self) -> std::borrow::Cow<'_, str> {
        if self.busca_txt.is_empty() {
            format!("{} {} {}", self.tema, self.nome_arq, self.fala).to_lowercase().into()
        } else {
            self.busca_txt.as_str().into()
        }
    }
    pub fn preparar(&mut self) {
        self.busca_txt = format!("{} {} {}", self.tema, self.nome_arq, self.fala).to_lowercase();
    }
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct Estado {
    #[serde(default)]
    pub nao_interessante: bool,
    #[serde(default)]
    pub repostado: bool,
}

pub type Estados = BTreeMap<String, Estado>;

#[derive(Clone, Debug, Deserialize)]
pub struct Tira {
    pub arquivo: String,
    pub n: usize,
    pub largura: u32,
    pub altura: u32,
    pub duracao: f32,
    pub tempos: Vec<f32>,
}

pub fn eh_video(caminho: &str) -> bool {
    let c = caminho.to_lowercase();
    [".mp4", ".mov", ".m4v", ".webm", ".mkv"].iter().any(|e| c.ends_with(e))
}

/// "2023-03-31" -> "31/03/2023"
pub fn data_br(iso: &str) -> String {
    let p: Vec<&str> = iso.split('-').collect();
    if p.len() == 3 { format!("{}/{}/{}", p[2], p[1], p[0]) } else { iso.to_string() }
}

/// 75.5 -> "1:15"
pub fn duracao(seg: f32) -> String {
    let s = seg.max(0.0).round() as u32;
    format!("{}:{:02}", s / 60, s % 60)
}

/// Um momento de motion sugerido (ou aprovado) para um vídeo do item.
#[derive(Clone, Debug, Default, Deserialize)]
pub struct Momento {
    pub id: String,
    pub video: String,
    pub ini: f32,
    pub fim: f32,
    #[serde(default)]
    pub tipo: String,
    #[serde(default)]
    pub texto: String,
    #[serde(default)]
    pub apoio: String,
    #[serde(default)]
    pub posicao: String,
    #[serde(default)]
    pub motivo: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub arquivo_pronto: String,
    /// imagens de referência só deste momento (e as gerais do item ligadas a ele)
    #[serde(default)]
    pub referencias: Vec<String>,
    /// direção do filme Motion (escrita por você ou pela IA), vai para a fila junto do pedido
    #[serde(default)]
    pub briefing: String,
    /// [início, fim] na timeline do projeto do FilmCraft (None: sem projeto ou trecho cortado)
    #[serde(default)]
    pub t_projeto: Option<Vec<f32>>,
    /// o último prompt do vídeo com IA deste momento
    #[serde(default)]
    pub prompt_video: String,
    /// como a IA sugere fazer: "motion" (Claude, gráfico por cima) ou "video" (b-roll gerado)
    #[serde(default)]
    pub formato: String,
    /// o vídeo gerado por IA (OpenRouter) para este momento, se pedido
    #[serde(default)]
    pub video_ia: Option<VideoIa>,
    /// o modelo de prompt escolhido (plano/modelos.py) para o motion e para o vídeo
    #[serde(default)]
    pub modelo_motion: String,
    #[serde(default)]
    pub modelo_video: String,
    /// b-roll do acervo: candidatos achados e a sequência escolhida
    #[serde(default)]
    pub broll: Option<Broll>,
    /// a função da imagem neste momento (provar, clima, contraste, so-a-pessoa), quando vem de um roteiro
    #[serde(default)]
    pub funcao: String,
    /// o motion feito com HyperFrames (composição e render)
    #[serde(default)]
    pub motion_hf: Option<MotionHf>,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct MotionHf {
    #[serde(default)]
    pub composicao: String,
    #[serde(default)]
    pub renderizado_em: String,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct Broll {
    #[serde(default)]
    pub candidatos: Vec<BrollCandidato>,
    #[serde(default)]
    pub sequencia: Vec<BrollPeca>,
    #[serde(default)]
    pub buscas: Vec<String>,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct BrollCandidato {
    pub id: String,
    #[serde(default)]
    pub fonte: String,
    pub arquivo: String,
    #[serde(default)]
    pub tipo: String,
    #[serde(default)]
    pub ini: f32,
    #[serde(default)]
    pub fim: f32,
    #[serde(default)]
    pub item: String,
    #[serde(default)]
    pub texto: String,
    #[serde(default)]
    pub miniatura: String,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct BrollPeca {
    pub arquivo: String,
    #[serde(default)]
    pub tipo: String,
    #[serde(default)]
    pub ini: f32,
    #[serde(default)]
    pub dur: f32,
}

/// Um estilo pronto de briefing/prompt (config/padroes/modelos-prompt.toml + os da marca).
#[derive(Clone, Debug, Default, Deserialize)]
pub struct ModeloPrompt {
    pub id: String,
    pub alvo: String,
    pub nome: String,
    #[serde(default)]
    pub descricao: String,
    #[serde(default)]
    pub tipos: Vec<String>,
}

/// Uma das três abordagens que a IA propõe antes de gerar.
#[derive(Clone, Debug, Default, Deserialize)]
pub struct Abordagem {
    pub nome: String,
    #[serde(default)]
    pub ideia: String,
    pub texto: String,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct VideoIa {
    #[serde(default)]
    pub job: String,
    #[serde(default)]
    pub modelo: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub erro: String,
    #[serde(default)]
    pub custo: Option<f64>,
    #[serde(default)]
    pub prompt: String,
}

/// Um modelo de vídeo do OpenRouter e o que ele aceita.
#[derive(Clone, Debug, Default, Deserialize)]
pub struct VideoModelo {
    pub id: String,
    #[serde(default)]
    pub nome: String,
    #[serde(default)]
    pub duracoes: Vec<i64>,
    #[serde(default)]
    pub resolucoes: Vec<String>,
    #[serde(default)]
    pub formatos: Vec<String>,
    #[serde(default)]
    pub quadros: Vec<String>,
    #[serde(default)]
    pub audio: bool,
    #[serde(default)]
    pub precos: std::collections::BTreeMap<String, String>,
}

/// O que a api devolve em `motion`: contexto, referências e momentos de um item.
#[derive(Clone, Debug, Default, Deserialize)]
pub struct MotionEstado {
    #[serde(default)]
    pub contexto: String,
    #[serde(default)]
    pub referencias: Vec<String>,
    #[serde(default)]
    pub sugestoes: Vec<Momento>,
    #[serde(default)]
    pub gerado_em: String,
    #[serde(default)]
    pub videos: Vec<String>,
    #[serde(default)]
    pub chave: bool,
    #[serde(default)]
    pub na_fila: usize,
    /// o projeto do FilmCraft que serve de base às sugestões ("" = ainda não tem: usa o vídeo)
    #[serde(default)]
    pub projeto: String,
    #[serde(default)]
    pub duracao_projeto: f32,
}

// ------------------------------------------------------------------ clientes, importar, roteiros

#[derive(Clone, Debug, Default, Deserialize)]
pub struct Cliente {
    pub slug: String,
    #[serde(default)]
    pub nome: String,
    #[serde(default)]
    pub molde: bool,
}

/// Uma fonte do cliente: as do acervo.toml (posts, cortes) e as pastas importadas pelo painel.
#[derive(Clone, Debug, Default, Deserialize)]
pub struct Fonte {
    pub id: String,
    #[serde(default)]
    pub nome: String,
    #[serde(default)]
    pub tipo: String,
    #[serde(default)]
    pub raiz: String,
    #[serde(default)]
    pub ativo: bool,
    #[serde(default)]
    pub origem: String,
    #[serde(default)]
    pub existe: bool,
    #[serde(default)]
    pub indexados: u64,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct FonteConta {
    #[serde(default)]
    pub videos: u64,
    #[serde(default)]
    pub imagens: u64,
    #[serde(default)]
    pub transcritos: u64,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct RoteiroResumo {
    pub id: String,
    #[serde(default)]
    pub titulo: String,
    #[serde(default)]
    pub resumo: Option<String>,
    #[serde(default)]
    pub formato: String,
    #[serde(default)]
    pub duracao: f32,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub criado_em: String,
    #[serde(default)]
    pub pasta: Option<String>,
    #[serde(default)]
    pub partes: usize,
    #[serde(default)]
    pub novas: usize,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct Ideia {
    pub id: String,
    #[serde(default)]
    pub titulo: String,
    #[serde(default)]
    pub formato: String,
    #[serde(default)]
    pub objetivo: String,
    #[serde(default)]
    pub gancho: String,
    #[serde(default)]
    pub por_que: String,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct FormatoRoteiro {
    pub id: String,
    #[serde(default)]
    pub nome: String,
    #[serde(default)]
    pub descricao: String,
    #[serde(default)]
    pub duracao: u32,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct FuncaoRoteiro {
    pub id: String,
    #[serde(default)]
    pub nome: String,
    #[serde(default)]
    pub descricao: String,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct Banco {
    #[serde(default)]
    pub montando: bool,
    #[serde(default)]
    pub frases: u64,
    #[serde(default)]
    pub videos: u64,
    #[serde(default)]
    pub itens: u64,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct Parte {
    #[serde(default)]
    pub parte: String,
    #[serde(default)]
    pub tipo: String,
    #[serde(default)]
    pub funcao: String,
    #[serde(default)]
    pub mostrar: String,
    #[serde(default)]
    pub por_que: String,
    #[serde(default)]
    pub texto: String,
    #[serde(default)]
    pub quem: String,
    #[serde(default)]
    pub video: String,
    #[serde(default)]
    pub ini: f32,
    #[serde(default)]
    pub fim: f32,
    #[serde(default)]
    pub item: String,
    #[serde(default)]
    pub dur: f32,
    #[serde(default)]
    pub cobertura: Vec<BrollCandidato>,
    #[serde(default)]
    pub escolhida: String,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct Roteiro {
    pub id: String,
    #[serde(default)]
    pub titulo: String,
    #[serde(default)]
    pub resumo: String,
    #[serde(default)]
    pub formato: String,
    #[serde(default)]
    pub duracao: f32,
    #[serde(default)]
    pub duracao_alvo: f32,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub pasta: Option<String>,
    #[serde(default)]
    pub projeto: Option<String>,
    #[serde(default)]
    pub partes: Vec<Parte>,
}

/// Um motion já renderizado do cliente, para reaproveitar noutro momento.
#[derive(Clone, Debug, Default, Deserialize)]
pub struct MotionPronto {
    pub id: String,
    #[serde(default)]
    pub arquivo: String,
    #[serde(default)]
    pub texto: String,
    #[serde(default)]
    pub tipo: String,
    #[serde(default)]
    pub item: String,
    #[serde(default)]
    pub dur: f32,
}
