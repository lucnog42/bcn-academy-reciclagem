//! A janela: topo (abas, busca, filtros), conteúdo da aba, rodapé (seleção e tarefas), preview.

mod comum;
mod grade;
mod lista;
mod plugins;
mod preview;
pub mod tema;
pub use grade::GAP;

use crate::app::{Aba, App, POR_PAGINA, Tamanho};
use crate::filtro::{self, Ordem, Status};
use comum::{botao, botao_tx, pastilha};
use rune::{Cursor, Cx, El, ScrollSpec, col, el, row, spacer, text};
use rune_kit::TextInput;
use tema::Tema;

pub fn view(s: &App, cx: &mut Cx<App>) -> El {
    let t = tema::tema();
    let k = tema::kit();
    let corpo = match (&s.erro_ponte, s.carregando) {
        (Some(e), _) if s.posts.is_empty() => aviso_central(&format!(
            "Não consegui falar com o motor Python.\n\n{e}\n\nO painel procura o acervo em {}.\n\
             Rode de dentro da pasta do acervo ou passe --acervo <pasta>.", s.base.display()), t),
        (_, true) => aviso_central("carregando o acervo…", t),
        _ => match s.aba {
            Aba::Posts | Aba::Cortes => grade::grade(s, t)
                .on_layout(|s: &mut App, r| {
                    s.largura = r[2] - 32.0;
                    let c = grade::colunas(s.largura, s.tamanho);
                    if c != s.colunas { s.colunas = c; s.versao += 1; }
                }),
            Aba::Recomendados => lista::recomendados(s),
            Aba::Plugins => plugins::aba(s, t, cx),
            Aba::Config => col().key("aba-config").w_full().grow(1.0).min_h(0.0).padding(24.0)
                .scroll(ScrollSpec { stick_bottom: false }).fill(t.bg)
                .child(row().w_full().child(spacer()).child(conteudo_chaves(s, t, &k).w(640.0)).child(spacer())),
        },
    };
    let mut raiz = col().key("raiz").w_full().h_full().fill(t.bg)
        .child(topo(s, t, &k))
        .child(corpo)
        .child(rodape(s, t));
    if s.tarefas_abertas {
        raiz = raiz.child(tarefas(s, t));
    }
    let mut camadas = vec![];
    let tira_w = cx.layout_size("tira").map(|v| v[0]);
    if let Some(p) = preview::preview(s, t, tira_w) {
        camadas.push(p);
    }
    if s.chave_aberta {
        camadas.push(painel_chave(s, t, &k));
    }
    if let Some(a) = &s.aviso {
        camadas.push(toast(a, t));
    }
    rune_kit::root(raiz, camadas)
}

fn aviso_central(msg: &str, t: Tema) -> El {
    col().w_full().grow(1.0).center().padding(40.0)
        .child(text(msg.to_string()).font(tema::NORMAL.lh(20.0)).color(t.dim).max_w(640.0))
}

fn topo(s: &App, t: Tema, k: &rune_kit::Kit) -> El {
    // abas
    let mut abas = row().h(32.0).padding(3.0).gap(4.0).radius(9.0).fill(t.card2).border(1.0, t.linha);
    for a in Aba::TODAS {
        let on = a == s.aba;
        let n = match a {
            Aba::Posts => s.posts.len(),
            Aba::Cortes => s.cortes.len(),
            Aba::Recomendados => 0,
            Aba::Plugins => s.plugins.quantos(),
            Aba::Config => 0,
        };
        let rot = if n > 0 { format!("{} {}", a.rotulo(), n) } else { a.rotulo().to_string() };
        abas = abas.child(row().key(format!("aba-{}", a.rotulo())).h_full().px(12.0).center_y().radius(6.0)
            .fill(if on { t.acento } else { rune::Color::TRANSPARENT })
            .hover(t.linha_forte.alpha(0.2)).cursor(Cursor::Pointer)
            .child(text(rot).font(tema::PEQ_M).color(if on { tema::TINTA_ACENTO } else { t.dim }))
            .on_press(move |s: &mut App| s.trocar_aba(a)));
    }
    let led = if s.ponte.is_some() { t.acento } else { t.alerta };
    let estado = if s.ponte.is_some() { "motor Python ligado" } else { "sem motor Python" };
    let linha1 = row().w_full().h(36.0).gap(14.0).center_y()
        .child(text(if s.nome_marca.is_empty() { "Video Automation NG3".to_string() } else { s.nome_marca.clone() })
            .font(tema::TITULO).color(t.txt))
        .child(text(format!("{} posts · {} cortes", s.posts.len(), s.cortes.len())).font(tema::PEQ).color(t.dim))
        .child(abas)
        .child(spacer())
        .child(row().gap(6.0).center_y()
            .child(el().size(7.0, 7.0).radius(4.0).fill(led))
            .child(text(estado).font(tema::PEQ).color(t.dim)))
        .child(botao_claude(s, t));

    let busca = TextInput::new(&s.busca)
        .placeholder("buscar na pasta, na legenda e no que é falado")
        .on_edit(|s: &mut App| &mut s.busca)
        .on_change(|s: &mut App, tx| s.tecla_busca(tx))
        .build(k)
        .key("busca").w(340.0);
    let mut filtros = row().w_full().gap(8.0).center_y().flex_wrap().child(busca);

    if !s.aba.sem_lista() {
        if s.aba != Aba::Cortes {
            // anos
            let mut anos: Vec<&str> = s.posts.iter().map(|p| p.ano.as_str()).collect();
            anos.sort_unstable();
            anos.dedup();
            for a in anos.into_iter().rev() {
                let on = s.filtro.anos.contains(a);
                let a2 = a.to_string();
                filtros = filtros.child(pastilha(format!("ano-{a}"), a.to_string(), on, t, move |s: &mut App| s.alternar_ano(&a2)));
            }
        }
        // pilares (com contagem)
        let cont = if s.aba == Aba::Cortes {
            filtro::contagem(s.cortes.iter().map(|c| c.pilar.as_str()))
        } else {
            filtro::contagem(s.posts.iter().map(|p| p.pilar.as_str()))
        };
        for (p, n) in cont {
            let on = s.filtro.pilares.contains(&p);
            let p2 = p.clone();
            filtros = filtros.child(pastilha(format!("pilar-{p}"), format!("{p} {n}"), on, t, move |s: &mut App| s.alternar_pilar(&p2)));
        }
        if s.aba == Aba::Posts {
            for tipo in ["fcproj", "pcraft"] {
                let on = s.filtro.tipo == tipo;
                filtros = filtros.child(pastilha(format!("tipo-{tipo}"), tipo.into(), on, t, move |s: &mut App| {
                    s.filtro.tipo = if s.filtro.tipo == tipo { String::new() } else { tipo.into() };
                    s.refiltrar();
                }));
            }
            for st in Status::TODOS {
                filtros = filtros.child(pastilha(format!("st-{}", st.rotulo()), st.rotulo().into(), s.filtro.status == st, t,
                                                 move |s: &mut App| s.status(st)));
            }
        }
        // ordem e tamanho dos cards
        if s.aba != Aba::Recomendados {
            filtros = filtros.child(text("ordem").font(tema::PEQ).color(t.dim));
            for o in Ordem::TODAS {
                if s.aba == Aba::Cortes && matches!(o, Ordem::Score | Ordem::Curtidas) { continue; }
                filtros = filtros.child(pastilha(format!("ord-{}", o.rotulo()), o.rotulo().into(), s.filtro.ordem == o, t,
                                                 move |s: &mut App| s.ordenar(o)));
            }
            filtros = filtros.child(text("cards").font(tema::PEQ).color(t.dim));
            for tm in Tamanho::TODOS {
                filtros = filtros.child(pastilha(format!("tam-{}", tm.rotulo()), tm.rotulo().into(), s.tamanho == tm, t,
                                                 move |s: &mut App| s.tamanho(tm)));
            }
        }
        filtros = filtros
            .child(pastilha("sem-projeto".into(), "só sem projeto".into(), s.filtro.so_sem_projeto, t, |s: &mut App| {
                s.filtro.so_sem_projeto = !s.filtro.so_sem_projeto;
                s.refiltrar();
            }))
            .child(botao("limpar", "limpar filtros", t.dim, false, t, |s: &mut App| s.limpar_filtros()))
            .child(text(format!("{} na tela", s.visiveis.len())).font(tema::PEQ).color(t.dim));
    }
    col().key("topo").w_full().gap(9.0).px(16.0).py(10.0).fill(t.bg).border_sides([0.0, 0.0, 1.0, 0.0], t.linha)
        .child(linha1).child(filtros)
}

fn rodape(s: &App, t: Tema) -> El {
    let n = s.selecao.len();
    let rodando = s.tarefas.iter().filter(|t| t.fim.is_none()).count();
    let mut r = row().key("rodape").w_full().h(52.0).px(16.0).gap(10.0).center_y()
        .fill(t.bg).border_sides([1.0, 0.0, 0.0, 0.0], t.linha)
        .child(text(s.rotulo_selecao()).font(tema::NORMAL_M).color(if n > 0 { t.acento } else { t.dim }));
    if n > 0 {
        if s.aba != Aba::Cortes {
            r = r.child(text(format!("~{:.0} MB de projeto", s.mb_projeto())).font(tema::PEQ).color(t.dim));
        }
        r = r.child(botao("limpar-sel", "limpar seleção", t.dim, false, t, |s: &mut App| { s.selecao.clear(); s.versao += 1; }));
    }
    r = r.child(spacer());
    if !s.aba.sem_lista() && !s.visiveis.is_empty() {
        r = r.child(paginador(s, t)).child(spacer());
    }
    let rot_tarefas = if rodando > 0 { format!("tarefas · {rodando} rodando") } else { format!("tarefas {}", s.tarefas.len()) };
    r = r.child(botao("ver-tarefas", rot_tarefas, if rodando > 0 { t.alerta } else { t.dim }, s.tarefas_abertas, t,
                      |s: &mut App| s.tarefas_abertas = !s.tarefas_abertas));
    let pode = n > 0 && s.ponte.is_some();
    r.child(row().key("gerar").h(32.0).px(14.0).center_y().radius(8.0)
        .fill(if pode { t.acento } else { t.card2 }).cursor(if pode { Cursor::Pointer } else { Cursor::NotAllowed })
        .child(text(format!("gerar projeto ({n})")).font(tema::NORMAL_M).color(if pode { tema::TINTA_ACENTO } else { t.dim }))
        .on_press(|s: &mut App| s.gerar_selecao()))
}

pub fn colunas(largura: f32, tm: Tamanho) -> usize { grade::colunas(largura, tm) }

/// ‹ 1 2 … 7 8 9 … 26 › · por página
fn paginador(s: &App, t: Tema) -> El {
    let n = s.n_paginas();
    let atual = s.pagina;
    let mut r = row().key("paginador").gap(4.0).center_y();
    if n > 1 {
        r = r.child(botao_tx("pag-ant", "‹", t.txt, false, t, move |s: &mut App, tx| s.ir_pagina(atual.saturating_sub(1), tx)));
        let mut mostrar: Vec<usize> = vec![0, n - 1];
        mostrar.extend(atual.saturating_sub(2)..(atual + 3).min(n));
        mostrar.sort_unstable();
        mostrar.dedup();
        let mut ant = None;
        for p in mostrar {
            if let Some(a) = ant && p > a + 1 {
                r = r.child(text("…").font(tema::PEQ).color(t.dim));
            }
            r = r.child(botao_tx(format!("pag-{p}"), (p + 1).to_string(), if p == atual { t.acento } else { t.txt }, p == atual, t,
                                 move |s: &mut App, tx| s.ir_pagina(p, tx)));
            ant = Some(p);
        }
        r = r.child(botao_tx("pag-prox", "›", t.txt, false, t, move |s: &mut App, tx| s.ir_pagina(atual + 1, tx)));
    }
    let faixa = filtro::pagina(s.visiveis.len(), s.pagina, s.por_pagina);
    r = r.child(text(format!("{}–{} de {}", faixa.start + 1, faixa.end, s.visiveis.len())).font(tema::PEQ).color(t.dim).px(6.0));
    for pp in POR_PAGINA {
        let rot = if pp == 0 { "todos".to_string() } else { pp.to_string() };
        r = r.child(pastilha(format!("pp-{pp}"), rot, s.por_pagina == pp, t, move |s: &mut App| s.por_pagina(pp)));
    }
    r
}

/// No fim da grade: selecionar a página inteira e ir para a próxima.
pub fn fim_de_pagina(s: &App, t: Tema) -> El {
    let n = s.n_paginas();
    let atual = s.pagina;
    let mut r = row().key("fim-pagina").w_full().gap(10.0).py(18.0).center();
    r = r.child(botao("sel-pagina", "selecionar / tirar a página toda", t.acento, false, t, |s: &mut App| s.selecionar_pagina()));
    if atual + 1 < n {
        r = r.child(botao_tx("prox-pagina", format!("próxima página ({} de {}) ›", atual + 2, n), t.txt, false, t,
                             move |s: &mut App, tx| s.ir_pagina(atual + 1, tx)));
    }
    r
}

fn tarefas(s: &App, t: Tema) -> El {
    let mut c = col().key("tarefas").w_full().h(220.0).gap(10.0).px(16.0).py(10.0).fill(t.card).border_sides([1.0, 0.0, 0.0, 0.0], t.linha)
        .scroll(ScrollSpec { stick_bottom: true });
    if s.tarefas.is_empty() {
        c = c.child(text("nenhuma tarefa ainda: gerar projeto e os plugins aparecem aqui, com a saída linha a linha")
            .font(tema::PEQ).color(t.dim));
    }
    for tf in s.tarefas.iter().rev().take(6) {
        let (cor, st) = match tf.fim {
            None => (t.alerta, "rodando"),
            Some(true) => (t.acento, "ok"),
            Some(false) => (t.erro, "falhou"),
        };
        let ultimas: Vec<&str> = tf.linhas.iter().rev().take(12).map(String::as_str).collect::<Vec<_>>().into_iter().rev().collect();
        c = c.child(col().key(format!("t-{}", tf.id)).w_full().gap(4.0)
            .child(row().gap(8.0).center_y()
                .child(comum::etiqueta(st, cor))
                .child(text(tf.dono.clone()).font(tema::PEQ_M).color(t.txt))
                .child(text(tf.comando.clone()).font(tema::MONO).color(t.dim).truncate().grow(1.0).min_w(0.0)))
            .child(text(ultimas.join("\n")).font(tema::MONO.lh(16.0)).color(t.dim).selectable(true).wrap_anywhere()));
    }
    c
}

fn toast(msg: &str, t: Tema) -> El {
    col().key("toast-camada").w_full().h_full().absolute(0.0, 0.0).inert()
        .child(spacer())
        .child(row().w_full().pb(70.0).center()
            .child(row().key("toast").px(14.0).py(9.0).radius(9.0).fill(t.card2).border(1.0, t.linha_forte)
                .child(text(msg.to_string()).font(tema::PEQ).color(t.txt).max_w(700.0).wrap_anywhere())))
}

/// No topo: qual IA faz as sugestões e se a chave dela funciona; um clique abre o painel.
fn botao_claude(s: &App, t: Tema) -> El {
    let i = &s.chave_info;
    let nome = if i.nome.is_empty() { "IA".to_string() } else { i.nome.clone() };
    let fim = if i.fim.is_empty() { String::new() } else { format!(" …{}", i.fim) };
    let (cor, rotulo) = match (s.claude, i.valida) {
        (false, _) => (t.alerta, format!("{nome}: sem chave")),
        (true, Some(false)) => (t.erro, format!("{nome}{fim}: erro")),
        (true, _) => (t.acento, format!("{nome} ✓{fim}")),
    };
    row().key("claude-chave").h(26.0).px(10.0).gap(6.0).center_y().radius(7.0)
        .border(1.0, if s.chave_aberta { cor } else { t.linha })
        .fill(if s.chave_aberta { cor.alpha(0.15) } else { rune::Color::TRANSPARENT })
        .hover(t.linha_forte.alpha(0.2)).cursor(Cursor::Pointer)
        .child(el().size(7.0, 7.0).radius(4.0).fill(cor))
        .child(text(rotulo).font(tema::PEQ_M).color(t.txt))
        .on_press(|s: &mut App| s.chave_aberta = !s.chave_aberta)
}

/// A IA das sugestões: provedor (Claude, DeepSeek, OpenRouter, Ollama, outra), modelo,
/// endereço e chave. Salvar grava em config.local.toml e testa.
fn painel_chave(s: &App, t: Tema, k: &rune_kit::Kit) -> El {
    let painel = conteudo_chaves(s, t, k).w(500.0);
    col().key("camada-chave").w_full().h_full().absolute(0.0, 0.0)
        .on_press(|s: &mut App| s.chave_aberta = false)
        .child(row().w_full().padding(16.0).child(spacer())
            .child(painel.mt(44.0).on_press(|_: &mut App| {})))
}

/// As chaves de API (sugestões e vídeo): no painel do botão do topo e na aba "chaves e config".
fn conteudo_chaves(s: &App, t: Tema, k: &rune_kit::Kit) -> El {
    let i = &s.chave_info;
    let sel = s.provedor_em_edicao().cloned().unwrap_or_default();
    let mudou = s.ia_provedor != i.provedor || s.ia_modelo.text.trim() != i.modelo || s.ia_base.text.trim() != i.base_url;

    let mut provs = row().w_full().gap(6.0).flex_wrap();
    for p in &i.provedores {
        let id = p.id.clone();
        let rot = if p.tem_chave || !p.chave { format!("{} ✓", p.nome) } else { p.nome.clone() };
        provs = provs.child(botao(format!("prov-{}", p.id), rot, t.acento, p.id == s.ia_provedor, t,
                                  move |s: &mut App| s.escolher_provedor(&id)));
    }

    let modelo = TextInput::new(&s.ia_modelo)
        .placeholder(match sel.id.as_str() {
            "openrouter" => "ex.: anthropic/claude-sonnet, google/gemini-…, deepseek/…",
            "ollama" => "um modelo baixado no Ollama (com visão, para ver as imagens)",
            _ => "nome do modelo",
        })
        .on_edit(|s: &mut App| &mut s.ia_modelo).build(k).key("ia-modelo").w_full();
    let base = TextInput::new(&s.ia_base)
        .placeholder("https://…/v1 (formato da OpenAI)")
        .on_edit(|s: &mut App| &mut s.ia_base).build(k).key("ia-base").w_full();
    let campo = TextInput::new(&s.chave)
        .placeholder(if sel.tem_chave { "chave salva — cole outra para trocar" } else { "cole a chave da API" })
        .secure()
        .on_edit(|s: &mut App| &mut s.chave)
        .on_submit(|s: &mut App, _| s.salvar_chave(false))
        .build(k)
        .key("chave-campo").w_full();

    let situacao = match (s.claude, i.origem.as_str(), i.valida) {
        (false, _, _) => format!("Em uso: {} — sem chave. As sugestões de motion precisam dela.", i.nome),
        (true, "ambiente", _) => format!("Em uso: {} · {} · chave …{} da variável de ambiente.", i.nome, i.modelo, i.fim),
        (true, _, Some(true)) if i.erro.is_empty() => format!("Em uso: {} · {} — funcionando.", i.nome, i.modelo),
        (true, _, Some(_)) => format!("Em uso: {} · {} — {}", i.nome, i.modelo, i.erro),
        (true, _, None) => format!("Em uso: {} · {} (ainda não testado).", i.nome, i.modelo),
    };
    let erro = i.valida == Some(false) || !i.erro.is_empty();
    let ocupado = i.testando;
    let rotulo = |txt: &str| text(txt.to_string()).font(tema::MINI).color(t.dim);

    let mut painel = col().key("painel-chave").gap(10.0).padding(16.0).radius(12.0)
        .fill(t.card).border(1.0, t.linha_forte)
        .child(row().w_full().center_y()
            .child(text("Chaves de API").font(tema::TITULO).color(t.txt))
            .child(spacer())
            .child(if s.aba == Aba::Config { el() } else {
                botao("chave-fechar", "fechar", t.dim, false, t, |s: &mut App| s.chave_aberta = false) }))
        .child(text("Sugestões de motion").font(tema::NORMAL_M).color(t.txt))
        .child(text(situacao).font(tema::PEQ.lh(16.0)).color(if erro { t.erro } else { t.dim }).wrap())
        .child(rotulo("PROVEDOR"))
        .child(provs)
        .child(rotulo("MODELO"))
        .child(modelo);
    if !i.modelos.is_empty() && sel.id == i.provedor && sel.id != "claude" {
        painel = painel.child(text(format!("disponíveis: {}", i.modelos.iter().take(12).cloned().collect::<Vec<_>>().join(", ")))
            .font(tema::PEQ).color(t.dim).wrap_anywhere());
    }
    if sel.id != "claude" {
        painel = painel.child(rotulo("ENDEREÇO DA API")).child(base);
    }
    if sel.chave {
        painel = painel.child(rotulo("CHAVE")).child(campo);
    }
    painel = painel
        .child(row().w_full().gap(8.0).center_y()
            .child(botao("chave-salvar", if ocupado { "conferindo…" } else if mudou { "usar esta IA e testar" } else { "salvar e testar" },
                         t.acento, ocupado, t, |s: &mut App| { if !s.chave_info.testando { s.salvar_chave(false) } }))
            .child(if !mudou && s.claude { botao("chave-testar", "testar", t.txt, false, t, |s: &mut App| s.testar_chave()) } else { el() })
            .child(spacer())
            .child(if sel.chave && sel.tem_chave {
                botao("chave-remover", "remover chave", t.erro, false, t, |s: &mut App| s.salvar_chave(true)) } else { el() }))
        .child(text(match sel.id.as_str() {
            "claude" => "Chave em platform.claude.com → API Keys, na organização ligada ao Team: os créditos mensais do plano pagam o uso.",
            "deepseek" => "Chave em platform.deepseek.com. O modelo deepseek-flash aceita imagens (as referências e os quadros do vídeo).",
            "openrouter" => "Uma chave do openrouter.ai dá acesso a vários modelos; escreva o nome como aparece lá.",
            "ollama" => "Roda no seu computador, sem chave e sem custo: instale o Ollama e baixe um modelo. Sem visão, as imagens ficam de fora.",
            _ => "Qualquer API no formato da OpenAI (/chat/completions). Se o modelo não aceitar imagens, o app pergunta só com o texto.",
        }).font(tema::PEQ.lh(16.0)).color(t.dim).wrap())
        .child(el().w_full().h(1.0).fill(t.linha))
        .child(row().w_full().center_y()
            .child(text("Vídeo com IA (OpenRouter)").font(tema::NORMAL_M).color(t.txt))
            .child(spacer())
            .child(if s.tem_chave_video() { comum::etiqueta(format!("chave …{} ✓", s.chave_info.fim_video), t.acento) }
                   else { comum::etiqueta("sem chave", t.alerta) }))
        .child(text("Chave própria do vídeo (openrouter.ai → Keys), separada da chave das sugestões: \
            pode ser outra conta ou outra chave do OpenRouter, com o seu limite de gasto.").font(tema::PEQ.lh(16.0)).color(t.dim).wrap())
        .child(TextInput::new(&s.chave_video)
            .placeholder(if s.tem_chave_video() { "chave salva — cole outra para trocar" } else { "sk-or-…" })
            .secure()
            .on_edit(|s: &mut App| &mut s.chave_video)
            .on_submit(|s: &mut App, _| s.video_salvar_chave(false))
            .build(k).key("chave-video").w_full())
        .child(row().w_full().gap(8.0).center_y()
            .child(botao("chave-video-salvar", "salvar chave do vídeo", t.acento, false, t, |s: &mut App| s.video_salvar_chave(false)))
            .child(spacer())
            .child(if s.tem_chave_video() {
                botao("chave-video-remover", "remover", t.erro, false, t, |s: &mut App| s.video_salvar_chave(true)) } else { el() }))
        .child(text("As chaves ficam só neste computador, em config/local.toml (fora do git, legível só por você); \
            o app nunca as mostra de volta.").font(tema::PEQ.lh(16.0)).color(t.dim.alpha(0.8)).wrap())
        .child(el().w_full().h(1.0).fill(t.linha))
        .child(text("Marca (cliente)").font(tema::NORMAL_M).color(t.txt))
        .child(text("Cada marca tem o seu acervo, pilares, vocabulário e identidade em config/marcas/<marca>/, e o \
            seu estado em dados/marcas/<marca>/. Trocar reinicia o motor.").font(tema::PEQ.lh(16.0)).color(t.dim).wrap())
        .child(marcas(s, t));
    painel
}

fn marcas(s: &App, t: Tema) -> El {
    let mut r = row().w_full().gap(8.0).center_y().wrap();
    for m in &s.marcas {
        let on = *m == s.marca;
        let m2 = m.clone();
        r = r.child(botao(format!("marca-{m}"), m.clone(), t.acento, on, t, move |s: &mut App| s.trocar_marca(&m2)));
    }
    r
}
