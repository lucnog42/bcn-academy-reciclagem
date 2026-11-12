//! Aba "plugins": cada plugin Luau com seus parâmetros, o botão de rodar e o que ele registrou.

use super::comum::{botao, etiqueta, pastilha};
use super::tema::{self, Tema};
use crate::app::App;
use crate::plugins::{Plugin, Tipo, Valor};
use rune::{Cx, El, ScrollSpec, col, el, row, spacer, text};

pub fn aba(s: &App, t: Tema, cx: &Cx<App>) -> El {
    let itens = s.itens_plugin(None);
    let origem = if s.origem == crate::app::Aba::Cortes { "cortes" } else { "posts" };
    let mut c = col().key("plugins").w_full().grow(1.0).min_h(0.0).px(16.0).py(14.0).gap(12.0)
        .scroll(ScrollSpec { stick_bottom: false })
        .child(text(format!("{} {} selecionados (na aba {}). Os plugins ficam em plugins/<nome>/init.luau (na raiz do projeto); \
                             salvar o arquivo recarrega o plugin.", itens.len(), origem, origem))
            .font(tema::PEQ).color(t.dim).wrap());
    for e in &s.plugins.erros {
        c = c.child(text(format!("não carregou: {e}")).font(tema::MONO).color(t.erro));
    }
    if s.plugins.lista.is_empty() {
        c = c.child(text("nenhum plugin encontrado em plugins/").font(tema::NORMAL).color(t.dim));
    }
    for p in &s.plugins.lista {
        c = c.child(card(s, p, t, cx, s.servem(&p.aplica_a, &itens)));
    }
    c.child(el().h(60.0))
}

fn card(s: &App, p: &Plugin, t: Tema, cx: &Cx<App>, servem: usize) -> El {
    let mut topo = row().w_full().gap(8.0).center_y()
        .child(text(p.nome.clone()).font(tema::TITULO).color(t.txt));
    for a in &p.aplica_a {
        topo = topo.child(etiqueta(a.clone(), t.rep));
    }
    let id = p.id.clone();
    let pode = servem > 0 && s.ponte.is_some();
    topo = topo.child(spacer()).child(
        botao(format!("rodar-{}", p.id), format!("rodar em {servem}"), if pode { t.acento } else { t.dim }, false, t,
              move |s: &mut App| s.rodar_plugin(&id, None)));
    let mut c = col().key(format!("plugin-{}", p.id)).w_full().max_w(1100.0).gap(10.0).padding(14.0).radius(11.0)
        .fill(t.card).border(1.0, t.linha)
        .child(topo);
    if !p.descricao.is_empty() {
        c = c.child(text(p.descricao.clone()).font(tema::NORMAL.lh(19.0)).color(t.dim).wrap());
    }
    for par in &p.params {
        let atual = p.valores.get(&par.id).cloned().unwrap_or(par.padrao.clone());
        let mut linha = row().w_full().gap(8.0).center_y().flex_wrap()
            .child(text(par.rotulo.clone()).font(tema::PEQ_M).color(t.txt).w(220.0));
        match &par.tipo {
            Tipo::Numero { min, max, passo } => {
                let v = if let Valor::Num(n) = atual { n } else { 0.0 };
                let (pid, prm, mn, mx, ps) = (p.id.clone(), par.id.clone(), *min, *max, *passo);
                let (pid2, prm2) = (pid.clone(), prm.clone());
                linha = linha
                    .child(botao(format!("{}-{}-menos", p.id, par.id), "−", t.txt, false, t,
                                 move |s: &mut App| s.plugins.ajustar(&pid, &prm, Valor::Num(((v - ps) * 1000.0).round() / 1000.0).max_num(mn))))
                    .child(text(atual.texto()).font(tema::MONO).color(t.acento).w(56.0))
                    .child(botao(format!("{}-{}-mais", p.id, par.id), "+", t.txt, false, t,
                                 move |s: &mut App| s.plugins.ajustar(&pid2, &prm2, Valor::Num(((v + ps) * 1000.0).round() / 1000.0).min_num(mx))));
            }
            Tipo::Escolha(ops) => {
                for o in ops {
                    let (pid, prm, o2) = (p.id.clone(), par.id.clone(), o.clone());
                    let on = atual == Valor::Txt(o.clone());
                    linha = linha.child(pastilha(format!("{}-{}-{o}", p.id, par.id), o.clone(), on, t,
                                                 move |s: &mut App| s.plugins.ajustar(&pid, &prm, Valor::Txt(o2.clone()))));
                }
            }
            Tipo::Booleano => {
                let on = atual == Valor::Bool(true);
                let (pid, prm) = (p.id.clone(), par.id.clone());
                linha = linha.child(pastilha(format!("{}-{}", p.id, par.id), if on { "sim".into() } else { "não".into() }, on, t,
                                             move |s: &mut App| s.plugins.ajustar(&pid, &prm, Valor::Bool(!on))));
            }
        }
        if !par.ajuda.is_empty() {
            linha = linha.child(text(par.ajuda.clone()).font(tema::PEQ).color(t.dim).wrap());
        }
        c = c.child(linha);
    }
    if let Some(painel) = s.plugins.painel(&p.id, cx) {
        c = c.child(painel);
    }
    if let Some(e) = p.script.error() {
        c = c.child(text(format!("erro: {}", e.message)).font(tema::MONO).color(t.erro).wrap_anywhere());
    }
    let log: Vec<String> = p.script.log().iter().rev().take(4).map(|l| l.message.clone()).collect();
    if !log.is_empty() {
        c = c.child(text(log.into_iter().rev().collect::<Vec<_>>().join("\n")).font(tema::MONO).color(t.dim).wrap_anywhere());
    }
    c
}

trait Limite { fn max_num(self, m: f64) -> Valor; fn min_num(self, m: f64) -> Valor; }
impl Limite for Valor {
    fn max_num(self, m: f64) -> Valor { if let Valor::Num(n) = self { Valor::Num(n.max(m)) } else { self } }
    fn min_num(self, m: f64) -> Valor { if let Valor::Num(n) = self { Valor::Num(n.min(m)) } else { self } }
}
