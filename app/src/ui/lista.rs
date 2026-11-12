//! Aba "recomendados": ranking pelo score do plano.py, com a decomposição de cada nota.

use super::comum::{barra, botao, etiqueta, imagem, miniatura};
use super::tema::{self, Tema};
use crate::app::{Alvo, App, pilar_cor};
use crate::dados::data_br;
use rune::{Cursor, El, GrowthSpec, ScrollSpec, col, el, memo, row, spacer, text};

pub fn recomendados(s: &App) -> El {
    let t = tema::tema();
    let linhas = col().key("rec").gap(8.0).growth(GrowthSpec::default())
        .virtual_rows(s.na_pagina().len(), 92.0,
            |s: &App, i| s.posts[s.na_pagina()[i]].nome.as_str().into(),
            |s: &App, i| linha(s, i, tema::tema()))
        .virtual_rows_version((s.versao, s.pagina))
        .on_visible_rows(|s: &mut App, r| { s.querer_lista(r) });
    col().key("lista").w_full().grow(1.0).min_h(0.0).px(16.0).py(14.0).scroll(ScrollSpec { stick_bottom: false })
        .child(col().w_full().max_w(1100.0).child(linhas)).child(super::fim_de_pagina(s, t)).child(el().h(40.0)).fill(t.bg)
}

fn linha(s: &App, i: usize, t: Tema) -> El {
    let p = &s.posts[s.na_pagina()[i]];
    let posicao = crate::filtro::pagina(s.visiveis.len(), s.pagina, s.por_pagina).start + i;
    let capa = p.capa().map(str::to_string);
    let pronta = miniatura(s, capa.as_deref()).is_some_and(|m| m.is_ready());
    let sel = s.selecao.contains(&p.nome);
    let (ni, rp) = s.estado(&p.nome);
    memo(format!("rec-{}", p.nome), (pronta, sel, ni, rp, posicao), || {
        let (n1, n2, n3, n4) = (p.nome.clone(), p.nome.clone(), p.nome.clone(), p.nome.clone());
        let partes = &p.partes;
        let decomp = format!("alcance {:.0} · evergreen {:.0} · material {:.0} · maturidade {:.0} · penal {:.0}",
            partes.alcance, partes.evergreen, partes.material, partes.maturidade, partes.penal);
        row().key(format!("r-{}", p.nome)).w_full().max_w(1100.0).h(92.0).gap(12.0).padding(8.0).center_y().radius(10.0)
            .fill(t.card).border(1.0, if sel { t.acento } else { t.linha }).cursor(Cursor::Pointer)
            .hover(t.linha_forte.alpha(0.08))
            .child(el().size(74.0, 74.0).radius(7.0).clip_rounded(7.0).child(imagem(miniatura(s, capa.as_deref()), "", t)))
            .child(col().grow(1.0).min_w(0.0).gap(5.0)
                .child(row().gap(8.0).center_y()
                    .child(text(format!("{}.", posicao + 1)).font(tema::PEQ_M).color(t.dim))
                    .child(text(p.nome.clone()).font(tema::NORMAL).color(t.txt).truncate()))
                .child(row().gap(8.0).center_y()
                    .child(etiqueta(p.pilar.clone(), tema::cor_pilar(pilar_cor(&p.pilar))))
                    .child(text(format!("{} · ♥ {} · {} dias", data_br(&p.data), p.curtidas, p.idade)).font(tema::PEQ).color(t.dim))
                    .child(text(decomp).font(tema::PEQ).color(t.dim).truncate()))
                .child(el().max_w(420.0).w_full().child(barra(p.score / 100.0, t.acento, t))))
            .child(col().gap(5.0).items_end()
                .child(text(format!("{:.0}", p.score)).font(tema::NOTA).color(t.alerta))
                .child(row().gap(5.0)
                    .child(botao("ni", "NI", t.erro, ni, t, move |s: &mut App| { let v = !s.estado(&n1).0; s.marcar(&n1, Some(v), None) }))
                    .child(botao("rp", "RP", t.rep, rp, t, move |s: &mut App| { let v = !s.estado(&n2).1; s.marcar(&n2, None, Some(v)) }))
                    .child(botao("sel", if sel { "✓" } else { "＋" }, t.acento, sel, t, move |s: &mut App| s.alternar_selecao(&n3)))))
            .child(spacer().w(0.0))
            .on_press(move |s: &mut App| s.abrir_preview(Alvo::Post(n4.clone())))
    })
}
