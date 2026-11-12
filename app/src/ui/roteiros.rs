//! Aba "roteiros": a IA propõe vídeos novos montados com as falas que já existem; você aprova
//! (vira projeto com o primeiro corte, só material do acervo) ou exclui.

use super::comum::{botao, etiqueta, imagem, pastilha};
use super::tema::{self, Tema};
use crate::app::App;
use crate::dados::Parte;
use rune::{Color, Cursor, El, ScrollSpec, col, el, row, spacer, text};
use rune_kit::TextInput;
use serde_json::json;

fn cor_funcao(f: &str, t: Tema) -> Color {
    match f {
        "provar" => t.acento,
        "clima" => t.rep,
        "contraste" => t.alerta,
        _ => t.dim,
    }
}

fn mmss(s: f32) -> String { format!("{}:{:02}", (s / 60.0) as u32, (s % 60.0).round() as u32 % 60) }

pub fn aba(s: &App, t: Tema, k: &rune_kit::Kit) -> El {
    row().key("roteiros").w_full().grow(1.0).min_h(0.0).gap(0.0)
        .child(lado(s, t, k).w(400.0).h_full())
        .child(el().w(1.0).h_full().fill(t.linha))
        .child(match &s.x.aberto {
            Some(_) => detalhe(s, t, k),
            None => col().w_full().grow(1.0).h_full().center()
                .child(text("Escreva um tema (ou deixe vazio) e peça ideias, ou escreva um roteiro direto.\n\
                             Cada roteiro usa as falas já gravadas; ao aprovar, o projeto nasce com o primeiro corte.")
                    .font(tema::NORMAL.lh(20.0)).color(t.dim).wrap().max_w(520.0)),
        })
}

fn lado(s: &App, t: Tema, k: &rune_kit::Kit) -> El {
    let x = &s.x;
    let mut c = col().key("rot-lado").w_full().gap(10.0).padding(14.0).scroll(ScrollSpec { stick_bottom: false })
        .child(text(format!("Banco de falas: {} frases de {} vídeos ({} itens)", x.banco.frases, x.banco.videos, x.banco.itens))
            .font(tema::PEQ).color(if x.banco.frases == 0 { t.alerta } else { t.dim }).wrap())
        .child(TextInput::new(&x.tema).placeholder("tema ou pedido (ex.: convite para a avaliação de 2027)")
            .on_edit(|s: &mut App| &mut s.x.tema).build(k).key("rot-tema").w_full());
    let mut fmts = row().w_full().gap(6.0).flex_wrap();
    for f in &x.formatos {
        let (id, d) = (f.id.clone(), f.duracao);
        fmts = fmts.child(pastilha(format!("rot-fmt-{}", f.id), f.nome.clone(), x.formato == f.id, t,
                                   move |s: &mut App| { s.x.formato = id.clone(); s.x.duracao = d; }));
    }
    let mut durs = row().w_full().gap(6.0).center_y().child(text("duração").font(tema::PEQ).color(t.dim));
    for d in [15u32, 30, 45, 60, 90] {
        durs = durs.child(pastilha(format!("rot-dur-{d}"), format!("{d} s"), x.duracao == d, t, move |s: &mut App| s.x.duracao = d));
    }
    if let Some(f) = x.formatos.iter().find(|f| f.id == x.formato) {
        fmts = fmts.child(text(f.descricao.clone()).font(tema::PEQ).color(t.dim).wrap());
    }
    c = c.child(fmts).child(durs)
        .child(row().w_full().gap(8.0)
            .child(botao("rot-ideias", if x.pensando_ideias { "pensando…" } else { "sugerir ideias" }, t.alerta, x.pensando_ideias, t,
                         |s: &mut App| { if !s.x.pensando_ideias { s.roteiro_ideias() } }))
            .child(spacer())
            .child(botao("rot-escrever", if x.escrevendo { "escrevendo…" } else { "escrever roteiro" }, t.acento, x.escrevendo, t,
                         |s: &mut App| { if !s.x.escrevendo { s.roteiro_escrever("") } })));

    if !x.ideias.is_empty() {
        c = c.child(text("IDEIAS").font(tema::MINI).color(t.dim));
        for i in &x.ideias {
            let id = i.id.clone();
            c = c.child(col().key(format!("ideia-{}", i.id)).w_full().gap(3.0).padding(8.0).radius(7.0).fill(t.card2)
                .border(1.0, t.linha)
                .child(row().w_full().gap(6.0).center_y()
                    .child(text(i.titulo.clone()).font(tema::NORMAL_M).color(t.txt).wrap().grow(1.0).min_w(0.0))
                    .child(etiqueta(i.formato.clone(), t.rep)))
                .child(if i.gancho.is_empty() { el() } else { text(format!("“{}”", i.gancho)).font(tema::PEQ).color(t.txt).wrap() })
                .child(text(if i.por_que.is_empty() { i.objetivo.clone() } else { i.por_que.clone() }).font(tema::PEQ).color(t.dim).wrap())
                .child(row().w_full().child(spacer())
                    .child(botao(format!("ideia-esc-{}", i.id), "escrever este", t.acento, x.escrevendo, t,
                                 move |s: &mut App| { if !s.x.escrevendo { s.roteiro_escrever(&id) } }))));
        }
    }
    c = c.child(text("ROTEIROS").font(tema::MINI).color(t.dim));
    if x.roteiros.is_empty() {
        c = c.child(text("nenhum ainda").font(tema::PEQ).color(t.dim));
    }
    for r in &x.roteiros {
        let id = r.id.clone();
        let on = x.aberto.as_ref().is_some_and(|a| a.id == r.id);
        let cor = match r.status.as_str() { "aprovado" => t.acento, _ => t.alerta };
        c = c.child(col().key(format!("rot-{}", r.id)).w_full().gap(3.0).padding(8.0).radius(7.0)
            .fill(if on { t.acento.alpha(0.10) } else { t.card }).border(1.0, if on { t.acento } else { t.linha })
            .cursor(Cursor::Pointer).hover(t.linha_forte.alpha(0.2))
            .child(row().w_full().gap(6.0).center_y()
                .child(text(r.titulo.clone()).font(tema::NORMAL_M).color(t.txt).truncate().grow(1.0).min_w(0.0))
                .child(etiqueta(r.status.clone(), cor)))
            .child(text(format!("{} · {} · {} partes{}", r.formato, mmss(r.duracao), r.partes,
                                if r.novas > 0 { format!(" ({} fala(s) nova(s))", r.novas) } else { String::new() }))
                .font(tema::PEQ).color(t.dim))
            .on_press(move |s: &mut App| s.roteiro_abrir(&id)));
    }
    c
}

fn detalhe(s: &App, t: Tema, k: &rune_kit::Kit) -> El {
    let Some(r) = s.x.aberto.as_ref() else { return el() };
    let aprovado = r.status == "aprovado";
    let mut topo = row().w_full().gap(8.0).center_y()
        .child(col().gap(2.0).grow(1.0).min_w(0.0)
            .child(text(r.titulo.clone()).font(tema::TITULO).color(t.txt).wrap())
            .child(text(format!("{} · {} (alvo {}) · {}", r.formato, mmss(r.duracao), mmss(r.duracao_alvo), r.resumo))
                .font(tema::PEQ).color(t.dim).wrap()))
        .child(botao("rot-md", "exportar texto", t.dim, false, t, |s: &mut App| s.roteiro_exportar()));
    if aprovado {
        let pasta = r.pasta.clone().unwrap_or_default();
        topo = topo.child(botao("rot-proj", "abrir projeto e momentos", t.acento, false, t, move |s: &mut App| s.roteiro_projeto(&pasta)));
    } else {
        topo = topo
            .child(botao("rot-exc", "excluir", t.erro, false, t, |s: &mut App| s.roteiro_excluir()))
            .child(botao("rot-apr", if s.x.aprovando { "montando o projeto…" } else { "aprovar e criar projeto ★" }, t.acento,
                         s.x.aprovando, t, |s: &mut App| { if !s.x.aprovando { s.roteiro_aprovar() } }));
    }
    let mut c = col().key("rot-detalhe").w_full().grow(1.0).h_full().min_h(0.0).gap(10.0).padding(16.0)
        .scroll(ScrollSpec { stick_bottom: false })
        .child(topo)
        .child(text(if aprovado {
            "Aprovado: o projeto tem o primeiro corte com as falas na ordem, cartões no lugar das falas novas e o b-roll do acervo \
             escolhido. No projeto, cada parte é um momento: troque o b-roll, ponha motion (HyperFrames) ou gere o que faltar."
        } else {
            "Ao aprovar: projeto do FilmCraft com as falas na ordem, um cartão escuro no lugar de cada fala nova (até ser gravada) \
             e, em cada parte, a imagem do acervo marcada abaixo, cobrindo conforme a função. Nada é gerado."
        }).font(tema::PEQ.lh(16.0)).color(t.dim).wrap());
    let n = r.partes.len();
    for (i, p) in r.partes.iter().enumerate() {
        c = c.child(parte(s, i, n, p, aprovado, t, k));
    }
    c
}

fn parte(s: &App, i: usize, n: usize, p: &Parte, aprovado: bool, t: Tema, k: &rune_kit::Kit) -> El {
    let cor = cor_funcao(&p.funcao, t);
    let nome_func = s.x.funcoes.iter().find(|f| f.id == p.funcao).map(|f| f.nome.clone()).unwrap_or(p.funcao.clone());
    let mut cab = row().w_full().gap(6.0).center_y()
        .child(text(format!("{}", i + 1)).font(tema::NORMAL_M).color(t.dim))
        .child(etiqueta(nome_func, cor))
        .child(if p.tipo == "nova" { etiqueta(format!("FALA NOVA · {}", p.quem), t.alerta) } else {
            etiqueta(format!("{} · {:.1}–{:.1} s", p.item.rsplit('/').next().unwrap_or(&p.item), p.ini, p.fim), t.rep) })
        .child(text(format!("{} · {:.1} s", p.parte, p.dur)).font(tema::PEQ).color(t.dim))
        .child(spacer());
    if !aprovado {
        cab = cab
            .child(if i > 0 { botao(format!("p-up-{i}"), "↑", t.dim, false, t, move |s: &mut App| s.roteiro_editar("mover", i, json!(-1))) } else { el() })
            .child(if i + 1 < n { botao(format!("p-dn-{i}"), "↓", t.dim, false, t, move |s: &mut App| s.roteiro_editar("mover", i, json!(1))) } else { el() })
            .child(botao(format!("p-rm-{i}"), "tirar", t.erro, false, t, move |s: &mut App| s.roteiro_editar("remover", i, json!(null))));
    }
    let mut c = col().key(format!("parte-{i}")).w_full().gap(6.0).padding(10.0).radius(8.0).fill(t.card)
        .border_sides([0.0, 0.0, 0.0, 3.0], cor).child(cab);
    if p.tipo == "nova" && !aprovado {
        let atual = s.x.textos.get(&i).map(|e| e.text.clone()).unwrap_or(p.texto.clone());
        let mudou = atual.trim() != p.texto.trim();
        c = c.child(rune_kit::TextArea::new(s.x.textos.get(&i).unwrap_or(&rune::TextEdit::new(&p.texto)))
                .width(None).auto_grow(1, 4)
                .on_edit(move |s: &mut App| { let txt = s.x.aberto.as_ref().map(|r| r.partes[i].texto.clone()).unwrap_or_default();
                                              s.x.textos.entry(i).or_insert_with(|| rune::TextEdit::new(&txt)) })
                .build(k).key(format!("p-txt-{i}")).w_full())
            .child(if mudou { row().w_full().child(spacer()).child(botao(format!("p-sv-{i}"), "salvar fala", t.acento, false, t,
                                                                           move |s: &mut App| s.roteiro_texto_salvar(i))) } else { el() });
    } else {
        c = c.child(text(if p.tipo == "nova" { p.texto.clone() } else { format!("“{}”", p.texto) })
            .font(tema::NORMAL.lh(19.0)).color(t.txt).wrap());
    }
    if !p.por_que.is_empty() {
        c = c.child(text(p.por_que.clone()).font(tema::PEQ).color(t.dim).wrap());
    }
    if p.funcao == "so-a-pessoa" {
        return c.child(text("sem imagem por cima: a fala segura sozinha").font(tema::PEQ).color(t.dim));
    }
    c = c.child(text(format!("mostrar: {}", if p.mostrar.is_empty() { "—" } else { &p.mostrar })).font(tema::PEQ).color(cor));
    if p.cobertura.is_empty() {
        let pode = s.x.funcoes.iter().any(|f| f.id == p.funcao) && p.funcao != "provar";
        return c.child(text(if pode { "nada no acervo para isso: depois de aprovar, gere no momento (vídeo com IA ou motion)" }
                            else { "nenhuma prova no acervo para isso: considere outra fala ou importe o material" })
            .font(tema::PEQ).color(t.alerta).wrap());
    }
    let mut fila = row().w_full().gap(8.0).flex_wrap();
    for cand in &p.cobertura {
        let on = cand.id == p.escolhida;
        let cid = cand.id.clone();
        let quando = if cand.tipo == "video" && cand.fim > 0.0 { format!(" {:.0}–{:.0}s", cand.ini, cand.fim) } else { String::new() };
        let mut cartao = col().key(format!("p-{i}-c-{}", cand.id)).w(104.0).gap(3.0).padding(4.0).radius(6.0)
            .fill(if on { t.acento.alpha(0.15) } else { t.card2 }).border(1.0, if on { t.acento } else { t.linha })
            .child(el().w(96.0).h(96.0).radius(4.0).clip_rounded(4.0).fill(t.card)
                .child(imagem(s.miniaturas.get(&cand.miniatura), &cand.tipo, t)))
            .child(text(format!("{} · {}{quando}", cand.fonte, cand.tipo)).font(tema::MINI).color(t.rep).truncate());
        if !aprovado {
            cartao = cartao.cursor(Cursor::Pointer).hover(t.linha_forte.alpha(0.2))
                .on_press(move |s: &mut App| s.roteiro_editar("escolher", i, json!(if on { String::new() } else { cid.clone() })));
        }
        fila = fila.child(cartao);
    }
    c.child(fila)
}
