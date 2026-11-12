//! Busca e filtros da grade: funções puras, testáveis sem janela.

use crate::dados::{Corte, Estados, Post};
use std::collections::BTreeSet;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Status {
    #[default]
    Todos,
    SemMarca,
    NaoInteressante,
    Repostado,
}

impl Status {
    pub const TODOS: [Status; 4] = [Status::Todos, Status::SemMarca, Status::NaoInteressante, Status::Repostado];
    pub fn rotulo(self) -> &'static str {
        match self {
            Status::Todos => "todos",
            Status::SemMarca => "sem marca",
            Status::NaoInteressante => "NI",
            Status::Repostado => "RP",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Ordem {
    #[default]
    Recentes,
    Antigos,
    Score,
    Curtidas,
}

impl Ordem {
    pub const TODAS: [Ordem; 4] = [Ordem::Recentes, Ordem::Antigos, Ordem::Score, Ordem::Curtidas];
    pub fn rotulo(self) -> &'static str {
        match self {
            Ordem::Recentes => "recentes",
            Ordem::Antigos => "antigos",
            Ordem::Score => "score",
            Ordem::Curtidas => "curtidas",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Filtro {
    pub ordem: Ordem,
    pub busca: String,
    pub anos: BTreeSet<String>,
    pub pilares: BTreeSet<String>,
    /// "fcproj" | "pcraft" | vazio = os dois
    pub tipo: String,
    pub status: Status,
    pub so_sem_projeto: bool,
}

fn casa_busca(texto: &str, busca: &str) -> bool {
    let b = busca.trim().to_lowercase();
    b.is_empty() || b.split_whitespace().all(|t| texto.contains(t))
}

pub fn posts(lista: &[Post], estados: &Estados, f: &Filtro) -> Vec<usize> {
    let mut v = filtrar_posts(lista, estados, f);
    match f.ordem {
        Ordem::Recentes => v.sort_by(|&a, &b| lista[b].data.cmp(&lista[a].data)),
        Ordem::Antigos => v.sort_by(|&a, &b| lista[a].data.cmp(&lista[b].data)),
        Ordem::Score => v.sort_by(|&a, &b| lista[b].score.total_cmp(&lista[a].score)),
        Ordem::Curtidas => v.sort_by(|&a, &b| lista[b].curtidas.cmp(&lista[a].curtidas)),
    }
    v
}

fn filtrar_posts(lista: &[Post], estados: &Estados, f: &Filtro) -> Vec<usize> {
    lista.iter().enumerate().filter(|(_, p)| {
        let e = estados.get(&p.nome);
        let ni = e.is_some_and(|e| e.nao_interessante);
        let rp = e.is_some_and(|e| e.repostado);
        (f.anos.is_empty() || f.anos.contains(&p.ano))
            && (f.pilares.is_empty() || f.pilares.contains(&p.pilar))
            && (f.tipo.is_empty() || f.tipo == p.tipo)
            && (!f.so_sem_projeto || !p.projeto)
            && match f.status {
                Status::Todos => true,
                Status::SemMarca => !ni && !rp,
                Status::NaoInteressante => ni,
                Status::Repostado => rp,
            }
            && casa_busca(&p.busca(), &f.busca)
    }).map(|(i, _)| i).collect()
}

/// Recomendados: mesmo score do plano.py, sem o que já foi marcado, maior primeiro.
pub fn recomendados(lista: &[Post], estados: &Estados, f: &Filtro) -> Vec<usize> {
    let mut v: Vec<usize> = filtrar_posts(lista, estados, &Filtro { status: Status::SemMarca, ..f.clone() });
    v.sort_by(|&a, &b| lista[b].score.total_cmp(&lista[a].score));
    v
}

pub fn cortes(lista: &[Corte], f: &Filtro) -> Vec<usize> {
    let mut v: Vec<usize> = lista.iter().enumerate().filter(|(_, c)| {
        (f.pilares.is_empty() || f.pilares.contains(&c.pilar))
            && (!f.so_sem_projeto || !c.projeto)
            && casa_busca(&c.busca(), &f.busca)
    }).map(|(i, _)| i).collect();
    // cortes não têm curtidas nem score: antigos/recentes pelo nome do arquivo (data)
    if f.ordem == Ordem::Antigos { v.sort_by(|&a, &b| lista[a].nome_arq.cmp(&lista[b].nome_arq)); }
    if f.ordem == Ordem::Recentes { v.sort_by(|&a, &b| lista[b].nome_arq.cmp(&lista[a].nome_arq)); }
    v
}

/// Pedaço da lista que cabe na página `pagina` (0 = primeira); `por_pagina` 0 = tudo.
pub fn pagina(total: usize, pagina: usize, por_pagina: usize) -> std::ops::Range<usize> {
    if por_pagina == 0 { return 0..total; }
    let ini = (pagina * por_pagina).min(total);
    ini..(ini + por_pagina).min(total)
}

pub fn paginas(total: usize, por_pagina: usize) -> usize {
    if por_pagina == 0 { 1 } else { total.div_ceil(por_pagina).max(1) }
}

/// Contagem por pilar (para as pastilhas), sobre a lista inteira.
pub fn contagem<'a>(pilares: impl Iterator<Item = &'a str>) -> Vec<(String, usize)> {
    let mut m = std::collections::BTreeMap::<String, usize>::new();
    for p in pilares {
        *m.entry(p.to_string()).or_default() += 1;
    }
    let mut v: Vec<_> = m.into_iter().collect();
    v.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    v
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dados::Estado;

    fn post(nome: &str, ano: &str, pilar: &str, score: f32, projeto: bool) -> Post {
        serde_json::from_value(serde_json::json!({
            "id": nome, "pasta": format!("_posts/{ano}/{nome}"), "nome": nome, "data": format!("{ano}-01-01"),
            "ano": ano, "pilar": pilar, "tipo": "fcproj", "score": score, "projeto": projeto,
            "gancho": format!("legenda de {nome}"), "fala": "gol na final"
        })).unwrap()
    }

    #[test]
    fn busca_procura_todas_as_palavras_na_legenda_e_na_fala() {
        let l = vec![post("a", "2023", "PILAR1", 1.0, false), post("b", "2024", "PILAR2", 2.0, false)];
        let f = Filtro { busca: "GOL legenda".into(), ..Default::default() };
        assert_eq!(posts(&l, &Estados::new(), &f), vec![1, 0], "recentes primeiro");
        let f = Filtro { busca: "de b".into(), ..Default::default() };
        assert_eq!(posts(&l, &Estados::new(), &f), vec![1]);
    }

    #[test]
    fn filtros_combinam() {
        let l = vec![post("a", "2023", "PILAR1", 1.0, true), post("b", "2023", "PILAR2", 2.0, false),
                     post("c", "2024", "PILAR1", 3.0, false)];
        let f = Filtro { anos: ["2023".to_string()].into(), so_sem_projeto: true, ..Default::default() };
        assert_eq!(posts(&l, &Estados::new(), &f), vec![1]);
    }

    #[test]
    fn paginas_cortam_certo() {
        assert_eq!(pagina(130, 0, 48), 0..48);
        assert_eq!(pagina(130, 2, 48), 96..130);
        assert_eq!(pagina(130, 9, 48), 130..130);
        assert_eq!(pagina(130, 0, 0), 0..130);
        assert_eq!(paginas(130, 48), 3);
        assert_eq!(paginas(0, 48), 1);
    }

    #[test]
    fn ordena_por_curtidas() {
        let mut l = vec![post("a", "2023", "PILAR1", 1.0, false), post("b", "2024", "PILAR1", 2.0, false)];
        l[0].curtidas = 900;
        l[1].curtidas = 10;
        let f = Filtro { ordem: Ordem::Curtidas, ..Default::default() };
        assert_eq!(posts(&l, &Estados::new(), &f), vec![0, 1]);
        let f = Filtro::default();
        assert_eq!(posts(&l, &Estados::new(), &f), vec![1, 0]);
    }

    #[test]
    fn recomendados_sem_marcados_e_por_score() {
        let l = vec![post("a", "2023", "PILAR1", 1.0, false), post("b", "2023", "PILAR1", 5.0, false),
                     post("c", "2023", "PILAR1", 3.0, false)];
        let mut e = Estados::new();
        e.insert("b".into(), Estado { repostado: true, nao_interessante: false });
        assert_eq!(recomendados(&l, &e, &Filtro::default()), vec![2, 0]);
    }
}
