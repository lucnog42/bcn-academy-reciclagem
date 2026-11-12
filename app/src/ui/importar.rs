//! Aba "importar": pastas de qualquer disco apontadas como fontes do cliente, sem cópia.

use super::comum::{botao, etiqueta, pastilha};
use super::tema::{self, Tema};
use crate::app::App;
use rune::{El, ScrollSpec, col, el, row, spacer, text};
use rune_kit::TextInput;
use serde_json::json;

pub fn aba(s: &App, t: Tema, k: &rune_kit::Kit) -> El {
    let x = &s.x;
    let mut c = col().key("importar").w_full().grow(1.0).min_h(0.0).px(16.0).py(14.0).gap(12.0)
        .scroll(ScrollSpec { stick_bottom: false })
        .on_drop_files(|s: &mut App, arquivos, _| s.soltar_pasta(arquivos))
        .child(text(format!("Material de {}: pastas em qualquer disco, apontadas (nunca copiadas). O índice, as transcrições e \
            as miniaturas ficam em dados/marcas/{}/; a pasta de origem não é tocada.", s.nome_cliente(), s.marca))
            .font(tema::PEQ.lh(16.0)).color(t.dim).wrap());

    // adicionar
    let mut tipos = row().w_full().gap(6.0).flex_wrap().center_y().child(text("tipo").font(tema::PEQ).color(t.dim));
    for (id, desc) in &x.tipos {
        let id2 = id.clone();
        tipos = tipos.child(pastilha(format!("tipo-fonte-{id}"), id.clone(), x.novo_tipo == *id, t,
                                     move |s: &mut App| s.x.novo_tipo = id2.clone()));
        if x.novo_tipo == *id {
            tipos = tipos.child(text(desc.clone()).font(tema::PEQ).color(t.dim));
        }
    }
    c = c.child(col().key("fonte-nova").w_full().gap(8.0).padding(12.0).radius(9.0).fill(t.card2).border(1.0, t.linha)
        .child(text("APONTAR UMA PASTA — cole o caminho ou arraste a pasta para esta aba").font(tema::MINI).color(t.dim))
        .child(row().w_full().gap(8.0)
            .child(TextInput::new(&x.nova_raiz).placeholder("/run/media/…/Depoimentos 2024")
                .on_edit(|s: &mut App| &mut s.x.nova_raiz).build(k).key("fonte-raiz").grow(1.0))
            .child(TextInput::new(&x.novo_nome).placeholder("nome (opcional)")
                .on_edit(|s: &mut App| &mut s.x.novo_nome).build(k).key("fonte-nome").w(240.0)))
        .child(row().w_full().gap(8.0).center_y()
            .child(tipos.grow(1.0).min_w(0.0))
            .child(botao("fonte-add", if x.adicionando { "apontando e indexando…" } else { "apontar pasta" }, t.acento,
                         x.adicionando, t, |s: &mut App| { if !s.x.adicionando { s.fonte_adicionar() } }))));

    // lista
    if x.fontes.is_empty() {
        c = c.child(text("carregando as fontes…").font(tema::PEQ).color(t.dim));
    }
    for f in &x.fontes {
        let conta = x.contagens.get(&f.id);
        let (i1, i2, i3, i4, i5) = (f.id.clone(), f.id.clone(), f.id.clone(), f.id.clone(), f.id.clone());
        let ativo = f.ativo;
        let mut linha = row().w_full().gap(8.0).center_y()
            .child(text(f.nome.clone()).font(tema::NORMAL_M).color(if f.ativo { t.txt } else { t.dim }))
            .child(etiqueta(f.tipo.clone(), if f.tipo == "referencias" { t.alerta } else { t.rep }))
            .child(if f.origem == "importada" { etiqueta("importada", t.acento) } else { etiqueta("do acervo", t.dim) })
            .child(if !f.existe { etiqueta("pasta não encontrada (disco desmontado?)", t.erro) } else { el() })
            .child(spacer())
            .child(text(format!("{} no índice", f.indexados)).font(tema::PEQ).color(t.dim));
        if let Some(n) = conta {
            linha = linha.child(text(format!("· {} vídeo(s), {} foto(s), {} transcrito(s)", n.videos, n.imagens, n.transcritos))
                .font(tema::PEQ).color(t.dim));
        }
        let mut acoes = row().w_full().gap(6.0).center_y()
            .child(text(if f.raiz.is_empty() { "(acervo publicado)".to_string() } else { f.raiz.clone() })
                .font(tema::MONO).color(t.dim).truncate().grow(1.0).min_w(0.0))
            .child(botao(format!("f-at-{}", f.id), if f.ativo { "ligada" } else { "desligada" }, t.acento, f.ativo, t,
                         move |s: &mut App| s.fonte_acao(&i1, "fonte_ativar", json!({"ativo": !ativo}))))
            .child(botao(format!("f-ix-{}", f.id), "reindexar", t.txt, false, t,
                         move |s: &mut App| s.fonte_acao(&i2, "fonte_indexar", json!({}))));
        if f.origem == "importada" {
            acoes = acoes.child(botao(format!("f-ct-{}", f.id), "contar", t.dim, false, t,
                                      move |s: &mut App| s.fonte_acao(&i3, "fonte_contar", json!({}))));
            if f.tipo == "falas" {
                acoes = acoes.child(botao(format!("f-tr-{}", f.id), "transcrever o que falta", t.alerta, false, t,
                                          move |s: &mut App| s.fonte_acao(&i4, "fonte_transcrever", json!({}))));
            }
            acoes = acoes.child(botao(format!("f-rm-{}", f.id), "tirar do sistema", t.erro, false, t,
                                      move |s: &mut App| s.fonte_acao(&i5, "fonte_remover", json!({}))));
        }
        c = c.child(col().key(format!("fonte-{}", f.id)).w_full().gap(6.0).padding(10.0).radius(8.0).fill(t.card)
            .border(1.0, t.linha).child(linha).child(acoes));
    }
    c.child(text("falas: entram nos roteiros e no b-roll (depois de transcritas) · broll e fotos: só cobertura · referencias: \
        estilo e montagem de outros, nunca usadas como material. \"Tirar do sistema\" só esquece a pasta; nenhum arquivo é apagado.")
        .font(tema::PEQ.lh(16.0)).color(t.dim.alpha(0.8)).wrap())
}
