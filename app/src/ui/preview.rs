//! O preview de um post ou corte: mídias, tira de quadros do vídeo, legenda, fala, ações.

use super::comum::{botao, etiqueta, imagem, texto_bloco};
use super::tema::{self, Tema};
use crate::app::{Alvo, App};
use crate::dados::{data_br, duracao};
use rune::{Cursor, El, SurfaceFit, col, el, row, spacer, text};

pub fn preview(s: &App, t: Tema, tira_w: Option<f32>) -> Option<El> {
    let p = s.preview.as_ref()?;
    let corpo = match &p.alvo {
        Alvo::Post(n) => corpo_post(s, n, t, tira_w)?,
        Alvo::Corte(a) => corpo_corte(s, a, t, tira_w)?,
        Alvo::Roteiro(p) => corpo_roteiro(s, p, t, tira_w),
    };
    let folha = col().key("folha").w_full().max_w(1080.0).gap(14.0).padding(18.0).radius(14.0)
        .fill(t.card).border(1.0, t.linha)
        .child(corpo)
        .on_press(|_: &mut App| {}); // um clique na folha não fecha
    Some(col().key("preview").w_full().h_full().absolute(0.0, 0.0).fill(rune::Color::BLACK.alpha(0.78))
        .scroll(rune::ScrollSpec { stick_bottom: false })
        .child(col().w_full().padding(24.0).items_center().child(folha))
        .on_press(|s: &mut App| s.preview = None)
        .modal(true, |s: &mut App| s.preview = None))
}

fn cabecalho(titulo: &str, sub: String, t: Tema) -> El {
    row().w_full().gap(12.0).center_y()
        .child(col().grow(1.0).min_w(0.0).gap(4.0)
            .child(text(titulo.to_string()).font(tema::TITULO).color(t.txt).selectable(true).wrap_anywhere())
            .child(text(sub).font(tema::PEQ).color(t.dim).wrap()))
        .child(botao("fechar", "fechar  esc", t.dim, false, t, |s: &mut App| s.preview = None))
}

fn corpo_post(s: &App, nome: &str, t: Tema, tira_w: Option<f32>) -> Option<El> {
    let p = s.post(nome)?;
    let (ni, rp) = s.estado(nome);
    let sel = s.selecao.contains(nome);
    let sub = format!("{} · {} · ♥ {} · score {:.0} (alcance {:.0} · evergreen {:.0} · material {:.0} · maturidade {:.0} · penal {:.0}) · {} · {}",
        data_br(&p.data), p.pilar, p.curtidas, p.score, p.partes.alcance, p.partes.evergreen,
        p.partes.material, p.partes.maturidade, p.partes.penal, p.seq, p.tipo);
    let mut c = col().w_full().gap(14.0).child(cabecalho(&p.nome, sub, t));

    // ações
    let (n1, n2, n3, n4) = (p.nome.clone(), p.nome.clone(), p.nome.clone(), p.nome.clone());
    let url = p.url.clone();
    let mut acoes = row().w_full().gap(8.0).center_y()
        .child(botao("p-ni", "NI · não interessante", t.erro, ni, t, move |s: &mut App| { let v = !s.estado(&n1).0; s.marcar(&n1, Some(v), None) }))
        .child(botao("p-rp", "RP · já repostado", t.rep, rp, t, move |s: &mut App| { let v = !s.estado(&n2).1; s.marcar(&n2, None, Some(v)) }))
        .child(botao("p-sel", if sel { "✓ na seleção" } else { "＋ selecionar" }, t.acento, sel, t, move |s: &mut App| s.alternar_selecao(&n3)))
        .child(spacer());
    if !url.is_empty() {
        acoes = acoes.child(row().key("p-ig").h(24.0).px(8.0).center_y().radius(6.0).border(1.0, t.linha)
            .cursor(Cursor::Pointer).hover(t.linha_forte.alpha(0.2))
            .child(text("abrir no Instagram ↗").font(tema::PEQ_M).color(t.txt))
            .on_press_tx(move |_: &mut App, tx| { let _ = tx.open_url(&url); }));
    }
    let pasta = p.pasta.clone();
    acoes = acoes.child(botao("p-pasta", "abrir pasta", t.txt, false, t, move |s: &mut App| s.abrir_pasta(&pasta)));
    if !p.arquivo_projeto.is_empty() {
        let arq = p.arquivo_projeto.clone();
        acoes = acoes.child(botao("p-abrir", format!("abrir projeto (.{})", p.tipo), t.acento, false, t,
                                  move |s: &mut App| s.abrir_projeto(&arq)));
    }
    acoes = acoes.child(botao("p-gerar", if p.projeto { "gerar de novo" } else { "gerar projeto" }, t.alerta, false, t,
                              move |s: &mut App| s.gerar_um(n4.clone(), false)));
    c = c.child(acoes).child(botoes_plugins(s, Alvo::Post(p.nome.clone()), t));

    if p.videos().next().is_some() {
        c = c.child(painel_video(s, p.videos().cloned().collect(), t, tira_w));
        c = c.child(painel_motion(s, t));
    }
    let imgs: Vec<&String> = p.imagens().collect();
    if !imgs.is_empty() {
        let mut mosaico = row().w_full().gap(8.0).flex_wrap();
        for (i, m) in imgs.iter().enumerate() {
            mosaico = mosaico.child(col().key(format!("img-{i}")).w(240.0).radius(9.0).clip_rounded(9.0)
                .fill(t.card2).border(1.0, t.linha)
                // enquanto a versão de 720 px não chega, mostra a miniatura da grade (se já houver)
                .child(el().w(240.0).h(240.0).child(imagem(
                    s.originais.get(*m).filter(|i| i.is_ready()).or_else(|| s.miniaturas.get(*m)), "carregando", t)))
                .child(text(m.rsplit('/').next().unwrap_or(m).to_string()).font(tema::PEQ).color(t.dim).padding(6.0)));
        }
        c = c.child(mosaico);
    }
    if !p.gancho.is_empty() { c = c.child(texto_bloco("legenda original", &p.gancho, t)); }
    if !p.fala.is_empty() { c = c.child(texto_bloco("o que é dito no vídeo", &p.fala, t)); }
    c = c.child(text(format!("{} · {} mídias · ~{:.1} MB de projeto", p.pasta, p.midias.len(), p.peso))
        .font(tema::MONO).color(t.dim).selectable(true).wrap_anywhere());
    Some(c)
}

fn corpo_corte(s: &App, arq: &str, t: Tema, tira_w: Option<f32>) -> Option<El> {
    let k = s.corte(arq)?;
    let sel = s.selecao.contains(arq);
    let sub = format!("{} · {} · {} vídeo(s) — um projeto só · {:.1} MB", k.pilar, duracao(k.seg), k.videos.len(), k.mb);
    let (a1, a2) = (arq.to_string(), arq.to_string());
    let mut acoes = row().w_full().gap(8.0)
        .child(botao("c-sel", if sel { "✓ na seleção" } else { "＋ selecionar" }, t.acento, sel, t, move |s: &mut App| s.alternar_selecao(&a1)))
        .child(spacer());
    let pasta = arq.to_string();
    acoes = acoes.child(botao("c-pasta", "abrir pasta", t.txt, false, t, move |s: &mut App| s.abrir_pasta(&pasta)));
    if !k.arquivo_projeto.is_empty() {
        let arq = k.arquivo_projeto.clone();
        acoes = acoes.child(botao("c-abrir", "abrir projeto (.fcproj)", t.acento, false, t, move |s: &mut App| s.abrir_projeto(&arq)));
    }
    let acoes = acoes
        .child(botao("c-gerar", if k.projeto { "gerar de novo" } else { "gerar projeto" }, t.alerta, false, t,
                     move |s: &mut App| s.gerar_um(a2.clone(), true)));
    let mut c = col().w_full().gap(14.0).child(cabecalho(&k.nome_arq, sub, t)).child(acoes)
        .child(botoes_plugins(s, Alvo::Corte(arq.to_string()), t))
        .child(painel_video(s, k.videos.clone(), t, tira_w))
        .child(painel_motion(s, t));
    if !k.fala.is_empty() { c = c.child(texto_bloco("o que é dito", &k.fala, t)); }
    Some(c)
}

/// O projeto de um roteiro aprovado: os vídeos de onde vêm as falas e um momento por parte.
fn corpo_roteiro(s: &App, pasta: &str, t: Tema, tira_w: Option<f32>) -> El {
    let e = s.motion.as_ref().and_then(|m| m.estado.as_ref());
    let titulo = s.x.aberto.as_ref().filter(|r| r.pasta.as_deref() == Some(pasta)).map(|r| r.titulo.clone())
        .unwrap_or_else(|| pasta.rsplit('/').next().unwrap_or(pasta).to_string());
    let mut videos: Vec<String> = vec![];
    for m in e.map(|e| e.sugestoes.as_slice()).unwrap_or(&[]) {
        if !videos.contains(&m.video) { videos.push(m.video.clone()); }
    }
    let projeto = e.map(|e| e.projeto.clone()).unwrap_or_default();
    let p2 = pasta.to_string();
    let mut acoes = row().w_full().gap(8.0)
        .child(text("roteiro aprovado · o primeiro corte já está no projeto (falas + b-roll do acervo)").font(tema::PEQ).color(t.dim))
        .child(spacer())
        .child(botao("r-pasta", "abrir pasta", t.txt, false, t, move |s: &mut App| s.abrir_pasta(&p2)));
    if !projeto.is_empty() {
        acoes = acoes.child(botao("r-abrir", "abrir projeto (.fcproj)", t.acento, false, t, move |s: &mut App| s.abrir_projeto(&projeto)));
    }
    acoes = acoes.child(botao("r-montar", "atualizar o projeto (b-roll + motion)", t.alerta, false, t, |s: &mut App| s.inserir_no_projeto()));
    col().w_full().gap(14.0)
        .child(cabecalho(&titulo, format!("{} · {} parte(s)", pasta, e.map_or(0, |e| e.sugestoes.len())), t))
        .child(acoes)
        .child(if videos.is_empty() { el() } else { painel_video(s, videos, t, tira_w) })
        .child(painel_motion(s, t))
}

/// Motion de um momento: gerar com HyperFrames (a IA escreve a composição, o HyperFrames renderiza
/// um MOV transparente) ou reaproveitar um motion que o cliente já tem.
fn motion_opcoes(s: &App, m: &crate::app::MotionUi, mo: &crate::dados::Momento, t: Tema) -> El {
    if mo.status == "descartado" || mo.formato == "acervo" || mo.formato == "video" && mo.video_ia.is_some() { return el(); }
    let (i1, i2, i3) = (mo.id.clone(), mo.id.clone(), mo.id.clone());
    let tem_comp = mo.motion_hf.as_ref().is_some_and(|h| !h.composicao.is_empty());
    let mut r = row().w_full().gap(6.0).center_y()
        .child(text("MOTION").font(tema::MINI).color(t.dim))
        .child(match mo.motion_hf.as_ref() {
            Some(h) if !h.renderizado_em.is_empty() => text(format!("HyperFrames · renderizado em {}", h.renderizado_em.replace('T', " ")))
                .font(tema::PEQ).color(t.acento),
            Some(_) => text("composição escrita, falta renderizar").font(tema::PEQ).color(t.alerta),
            None => text("feito em HTML pelo HyperFrames, com fundo transparente").font(tema::PEQ).color(t.dim),
        })
        .child(spacer())
        .child(botao(format!("hf-bib-{}", mo.id), "usar um motion que já existe", t.txt, m.biblioteca_para.as_deref() == Some(&mo.id), t,
                     move |s: &mut App| s.biblioteca_abrir(&i1)));
    if tem_comp {
        r = r.child(botao(format!("hf-ren-{}", mo.id), "só renderizar de novo", t.dim, false, t, move |s: &mut App| s.motion_hf(&i2, true)));
    }
    r = r.child(botao(format!("hf-ger-{}", mo.id), if tem_comp { "escrever e renderizar de novo" } else { "gerar motion (HyperFrames)" },
                      t.acento, false, t, move |s: &mut App| s.motion_hf(&i3, false)));
    let mut c = col().w_full().gap(6.0).child(r);
    if m.biblioteca_para.as_deref() == Some(&mo.id) {
        let lista: Vec<_> = s.x.biblioteca.iter().filter(|b| b.id != mo.id).take(12).collect();
        if lista.is_empty() {
            c = c.child(text("este cliente ainda não tem motions prontos: gere um com o HyperFrames").font(tema::PEQ).color(t.dim));
        }
        for b in lista {
            let (id, origem) = (mo.id.clone(), b.id.clone());
            c = c.child(row().key(format!("bib-{}-{}", mo.id, b.id)).w_full().gap(8.0).padding(6.0).radius(6.0).fill(t.card2)
                .border(1.0, t.linha).cursor(Cursor::Pointer).hover(t.linha_forte.alpha(0.2))
                .child(etiqueta(if b.tipo.is_empty() { "motion".to_string() } else { b.tipo.clone() }, t.rep))
                .child(text(if b.texto.is_empty() { b.id.clone() } else { b.texto.clone() }).font(tema::PEQ).color(t.txt).truncate().grow(1.0).min_w(0.0))
                .child(text(format!("{:.1} s · {}", b.dur, b.item.replace("__", "/"))).font(tema::MINI).color(t.dim).truncate())
                .child(text("usar").font(tema::MINI).color(t.acento))
                .on_press(move |s: &mut App| s.motion_reusar(&id, &origem)));
        }
    }
    c
}

/// Quadro grande + tira de quadros (clique para escolher) + legenda no tempo + tocar no mpv.
fn painel_video(s: &App, videos: Vec<String>, t: Tema, tira_w: Option<f32>) -> El {
    let p = s.preview.as_ref();
    let foco = p.and_then(|p| p.video.clone()).or_else(|| videos.first().cloned()).unwrap_or_default();
    let q = p.map_or(0, |p| p.quadro);
    let tira = s.tiras.get(&foco);
    // o quadro escolhido; enquanto decodifica, o vizinho mais próximo que já está pronto
    let pronto = |k: usize| s.quadros.get(&(foco.clone(), k)).filter(|i| i.is_ready());
    let grande = pronto(q)
        .or_else(|| (1..16).find_map(|d| pronto(q.saturating_sub(d)).or_else(|| pronto(q + d))))
        .or_else(|| s.miniaturas.get(&foco));
    let tempo = tira.and_then(|(tr, _)| tr.tempos.get(q).copied()).unwrap_or(0.0);
    let dur = tira.map_or(0.0, |(tr, _)| tr.duracao);

    let mut c = col().w_full().gap(10.0);
    if videos.len() > 1 {
        let mut abas = row().w_full().gap(6.0).flex_wrap();
        for (i, v) in videos.iter().enumerate() {
            let v2 = v.clone();
            abas = abas.child(botao(format!("v{i}"), format!("{} · {}", i + 1, v.rsplit('/').next().unwrap_or(v)), t.rep, *v == foco, t,
                                    move |s: &mut App| s.focar_video(v2.clone())));
        }
        c = c.child(abas);
    }
    let quadro = match grande {
        Some(im) if im.is_ready() => el().w_full().h(420.0).radius(9.0).clip_rounded(9.0).fill(rune::Color::BLACK)
            .pixels_fit(im.pixels(), SurfaceFit::Fit),
        _ => el().w_full().h(420.0).radius(9.0).fill(t.card2).center()
            .child(text("carregando quadro…").font(tema::PEQ).color(t.dim)),
    };
    // legenda que está no ar nesse instante
    let falando: String = p.map(|p| p.palavras.iter().filter(|w| w.0 <= tempo + 1.2 && w.1 >= tempo - 0.2)
        .map(|w| w.2.as_str()).collect::<Vec<_>>().join(" ")).unwrap_or_default();
    c = c.child(quadro);
    c = c.child(row().w_full().gap(10.0).center_y()
        .child(botao("tocar", "▶ tocar com som (mpv)", t.acento, false, t, |s: &mut App| s.tocar()))
        .child(botao("exportar", "exportar quadro (PNG)", t.txt, false, t, |s: &mut App| s.exportar_quadro()))
        .child(text(format!("{} / {}", duracao(tempo), duracao(dur))).font(tema::MONO).color(t.dim))
        .child(text(falando).font(tema::NORMAL).color(t.txt).grow(1.0).truncate()));
    if let (Some((tr, _)), Some(w), Some(e)) = (tira, tira_w, s.motion.as_ref().and_then(|m| m.estado.as_ref())) {
        // os momentos de motion deste vídeo, como faixas sobre a tira
        let mut faixa = el().key("marcas-motion").w_full().h(10.0);
        let d = tr.duracao.max(0.1);
        for m in e.sugestoes.iter().filter(|m| m.video == foco && m.status != "descartado") {
            let cor = cor_status(&m.status, t);
            let id = m.id.clone();
            faixa = faixa.child(el().absolute(w * m.ini / d, 1.0).w((w * (m.fim - m.ini) / d).max(4.0)).h(8.0)
                .radius(3.0).fill(cor).cursor(Cursor::Pointer)
                .on_press(move |s: &mut App| s.motion_ir(&id)));
        }
        c = c.child(faixa);
    }
    if let Some((tr, im)) = tira {
        let mut fita = row().key("tira").w_full().h(64.0).gap(2.0).clip_rounded(4.0);
        let gap = 2.0;
        let cel_w = tira_w.map(|w| (w - gap * (tr.n as f32 - 1.0)) / tr.n as f32);
        for i in 0..tr.n {
            let on = i == q;
            let mut cel = el().key(format!("q{i}")).grow(1.0).h_full().radius(4.0).clip_rounded(4.0)
                .opacity(if on { 1.0 } else { 0.5 }).hover(rune::Color::WHITE.alpha(0.15)).cursor(Cursor::Pointer)
                .on_press(move |s: &mut App| s.escolher_quadro(i));
            if let (true, Some(cw)) = (im.is_ready(), cel_w) {
                // recorta o quadro i da tira: a imagem inteira deslocada dentro da célula
                cel = cel.child(el().w(cw * tr.n as f32).h(64.0).absolute(-cw * i as f32, 0.0)
                    .pixels(im.pixels()));
            } else {
                cel = cel.fill(t.card2);
            }
            fita = fita.child(cel);
        }
        c = c.child(fita);
    }
    let mut rodape = row().w_full().gap(8.0).center_y()
        .child(text(foco.clone()).font(tema::MONO).color(t.dim).wrap_anywhere().grow(1.0).min_w(0.0));
    if s.ultimo_exportado.is_some() {
        rodape = rodape.child(botao("pasta-quadros", "abrir pasta dos quadros", t.dim, false, t, |s: &mut App| s.abrir_pasta_quadros()));
    }
    c.child(rodape)
}

/// Os plugins que servem para este item, um botão cada (roda com os parâmetros da aba plugins).
fn botoes_plugins(s: &App, alvo: Alvo, t: Tema) -> El {
    let itens = s.itens_plugin(Some(&alvo));
    let mut r = row().w_full().gap(8.0).center_y().flex_wrap();
    let mut algum = false;
    for p in &s.plugins.lista {
        if s.servem(&p.aplica_a, &itens) == 0 { continue; }
        algum = true;
        let (id, a) = (p.id.clone(), alvo.clone());
        r = r.child(botao(format!("pl-{}", p.id), p.nome.clone(), t.rep, false, t,
                          move |s: &mut App| s.rodar_plugin(&id, Some(a.clone()))));
    }
    if algum { row().w_full().gap(10.0).center_y().child(text("plugins").font(tema::PEQ).color(t.dim)).child(r) } else { el() }
}

fn cor_status(status: &str, t: Tema) -> rune::Color {
    match status {
        "aprovado" => t.alerta,
        "pronto" => t.acento,
        "descartado" => t.dim,
        _ => t.rep,
    }
}

fn rotulo_status(status: &str, formato: &str) -> &'static str {
    match status {
        "aprovado" if formato == "acervo" => "b-roll do acervo ✓",
        "aprovado" => "motion aprovado",
        "pronto" => "pronto ✓",
        "descartado" => "descartado",
        _ => "sugerido",
    }
}

/// Motion: o contexto e as imagens que você dá, os momentos que o Claude sugere e a fila.
fn painel_motion(s: &App, t: Tema) -> El {
    let Some(m) = s.motion.as_ref() else { return el() };
    let k = tema::kit();
    let e = m.estado.as_ref();
    let mut c = col().key("motion").w_full().gap(10.0).padding(12.0).radius(9.0)
        .fill(if m.arrastando { t.acento.alpha(0.08) } else { t.card2 })
        .border(1.0, if m.arrastando { t.acento } else { t.linha })
        .on_drop_files(|s: &mut App, arquivos, _| s.motion_referencias(arquivos))
        .accepts_extensions(&["png", "jpg", "jpeg", "webp"])
        .on_drop_hover(|s: &mut App, sobre, _| { if let Some(m) = s.motion.as_mut() { m.arrastando = sobre; } });

    // cabeçalho
    let n_fila = e.map_or(0, |e| e.na_fila);
    c = c.child(row().w_full().gap(8.0).center_y().flex_wrap()
        .child(text("MOTION").font(tema::MINI).color(t.dim))
        .child(text(match e {
            Some(e) if !e.gerado_em.is_empty() => format!("sugerido em {}", e.gerado_em.replace('T', " ")),
            Some(_) => "sem sugestões ainda".into(),
            None => "carregando…".into(),
        }).font(tema::PEQ).color(t.dim))
        .child(spacer())
        .child(if n_fila > 0 { etiqueta(format!("{n_fila} na fila do Claude"), t.alerta) } else { el() })
        .child(botao("mo-novo", "+ momento aqui", t.txt, false, t, |s: &mut App| s.motion_novo_aqui()))
        .child(botao("mo-atualizar", "atualizar", t.dim, false, t, |s: &mut App| s.motion_recarregar()))
        .child(botao("mo-sugerir", if m.sugerindo { "pedindo à IA…" } else { "sugerir momentos" },
                     t.acento, m.sugerindo, t, |s: &mut App| { if !s.motion.as_ref().is_some_and(|m| m.sugerindo) { s.motion_sugerir() } })));

    c = c.child(text("Cada momento vira uma de duas coisas: «motion» = gráfico por cima do vídeo, em HTML renderizado \
        pelo HyperFrames com fundo transparente (nome, número, frase, lugar, chamada; o falante continua aparecendo) · «b-roll do \
        acervo» = imagens que você já tem · «gerar vídeo com IA» = uma cena nova do OpenRouter, quando nada no acervo serve. \
        ★ = o que a IA sugere.")
        .font(tema::PEQ.lh(16.0)).color(t.dim).wrap());
    if let Some(e) = e {
        c = c.child(if e.projeto.is_empty() {
            text("Base das sugestões: o vídeo cru — gere o projeto do FilmCraft para que a IA veja a timeline \
                montada (cortes, abertura, logo, legendas, ending) e posicione melhor.").font(tema::PEQ).color(t.alerta).wrap()
        } else {
            text(format!("Base das sugestões: o projeto {} ({}) — tempos, cortes, abertura, legendas e motions já \
                montados. Os tempos mostrados são da timeline.", e.projeto.rsplit('/').next().unwrap_or(&e.projeto),
                duracao(e.duracao_projeto))).font(tema::PEQ).color(t.dim).wrap()
        });
    }
    // contexto
    c = c.child(text("Contexto para a geração (quem fala, nomes, clube, lugar, o que destacar, o tom):")
        .font(tema::PEQ).color(t.dim).wrap());
    let campo = rune_kit::TextArea::new(&m.contexto)
        .placeholder("ex.: quem aparece e qual o papel, o lugar, o que destacar, o tom (animado, sério...).")
        .width(None).auto_grow(2, 8)
        .on_edit(|s: &mut App| &mut s.motion.as_mut().expect("motion").contexto)
        .build(&k)
        .key("mo-contexto").w_full();
    c = c.child(campo);
    let alterado = m.contexto.text != m.contexto_salvo;
    c = c.child(row().w_full().gap(8.0).center_y().flex_wrap()
        .child(if alterado { botao("mo-salvar", "salvar contexto", t.alerta, false, t, |s: &mut App| s.motion_salvar_contexto()) } else { el() })
        .child(botao("mo-quadro", "usar este quadro como referência", t.txt, false, t, |s: &mut App| s.motion_quadro_ref()))
        .child(botao("mo-pasta", "abrir pasta de referências", t.txt, false, t, |s: &mut App| s.motion_abrir_referencias()))
        .child(text("ou arraste imagens para cá").font(tema::PEQ).color(t.dim)));

    // referências
    if let Some(e) = e && !e.referencias.is_empty() {
        let mut fotos = row().w_full().gap(8.0).flex_wrap();
        for r in &e.referencias {
            let r2 = r.clone();
            fotos = fotos.child(col().key(format!("ref-{r}")).w(110.0).gap(4.0)
                .child(el().w(110.0).h(110.0).radius(6.0).clip_rounded(6.0).fill(t.card)
                    .child(super::comum::imagem(s.miniaturas.get(r), "…", t)))
                .child(row().w_full().gap(4.0).center_y()
                    .child(text(r.rsplit('/').next().unwrap_or(r).to_string()).font(tema::MINI).color(t.dim).truncate().grow(1.0).min_w(0.0))
                    .child(botao(format!("tirar-{r}"), "×", t.erro, false, t, move |s: &mut App| s.motion_tirar(&r2)))));
        }
        c = c.child(fotos);
    }

    // momentos
    if let Some(e) = e {
        for mo in &e.sugestoes {
            let cor = cor_status(&mo.status, t);
            let n_video = e.videos.iter().position(|v| *v == mo.video).map_or(0, |i| i + 1);
            let (i1, i2, i3, i4, i5, i6) = (mo.id.clone(), mo.id.clone(), mo.id.clone(), mo.id.clone(), mo.id.clone(), mo.id.clone());
            let editavel = mo.status == "sugerido";
            let texto: El = if editavel {
                let id = mo.id.clone();
                rune_kit::TextArea::new(m.textos.get(&mo.id).unwrap_or(&rune::TextEdit::new(&mo.texto)))
                    .width(None).auto_grow(1, 3)
                    .on_edit(move |s: &mut App| s.motion.as_mut().expect("motion").textos
                        .entry(id.clone()).or_insert_with(|| rune::TextEdit::new("")))
                    .build(&k).key(format!("mo-txt-{}", mo.id)).w_full()
            } else {
                text(mo.texto.clone()).font(tema::NORMAL_M).color(t.txt).wrap()
            };
            let iv = mo.id.clone();
            let form_aberto = s.video_form.as_ref().is_some_and(|f| f.id == mo.id);
            let sugere_video = mo.formato == "video";
            let mut acoes = row().w_full().gap(6.0).center_y().flex_wrap()
                .child(botao(format!("ir-{}", mo.id), "ver", t.txt, false, t, move |s: &mut App| s.motion_ir(&i1)));
            if editavel {
                // a escolha: o mesmo momento vira motion (Claude) ou vídeo gerado (OpenRouter)
                acoes = acoes
                    .child(botao(format!("menos-{}", mo.id), "−0,5 s", t.dim, false, t, move |s: &mut App| s.motion_mover(&i5, -0.5)))
                    .child(botao(format!("mais-{}", mo.id), "+0,5 s", t.dim, false, t, move |s: &mut App| s.motion_mover(&i6, 0.5)))
                    .child(spacer())
                    .child(botao(format!("desc-{}", mo.id), "descartar", t.erro, false, t, move |s: &mut App| s.motion_status(&i2, "descartado")))
                    .child(botao(format!("vid-{}", mo.id), if sugere_video { "gerar vídeo com IA ★" } else { "gerar vídeo com IA" },
                                 t.rep, form_aberto, t, move |s: &mut App| s.video_abrir(&iv)))
                    .child(botao(format!("apr-{}", mo.id), if sugere_video { "fazer como motion" } else { "fazer como motion ★" },
                                 t.acento, false, t, move |s: &mut App| s.motion_status(&i3, "aprovado")));
            } else {
                acoes = acoes.child(spacer())
                    .child(botao(format!("vid-{}", mo.id), "gerar vídeo com IA", t.rep, form_aberto, t, move |s: &mut App| s.video_abrir(&iv)));
                if mo.status != "pronto" {
                    acoes = acoes.child(botao(format!("volta-{}", mo.id), "voltar a sugerido", t.dim, false, t,
                                              move |s: &mut App| s.motion_status(&i4, "sugerido")));
                }
            }
            let refs_el = refs_do_momento(s, mo, &e.referencias, t);
            let id_drop = mo.id.clone();
            c = c.child(col().key(format!("mo-{}", mo.id)).w_full().gap(6.0).padding(10.0).radius(8.0)
                .fill(t.card).border(1.0, cor.alpha(0.5))
                .on_drop_files(move |s: &mut App, arquivos, _| s.motion_ref_arquivos(&id_drop, arquivos))
                .accepts_extensions(&["png", "jpg", "jpeg", "webp"])
                .child(row().w_full().gap(6.0).center_y().flex_wrap()
                    .child(etiqueta(rotulo_status(&mo.status, &mo.formato), cor))
                    .child(etiqueta(mo.tipo.clone(), t.rep))
                    .child(if editavel && !mo.formato.is_empty() {
                        etiqueta(match mo.formato.as_str() { "video" => "IA sugere: vídeo com IA", "acervo" => "b-roll do acervo", _ => "IA sugere: motion" }, t.alerta)
                    } else { el() })
                    .child(text(match mo.t_projeto.as_deref() {
                        Some([a, b, ..]) => format!("no projeto {} → {} · vídeo {n_video} · {}", duracao_fina(*a), duracao_fina(*b), mo.posicao),
                        _ if !e.projeto.is_empty() => format!("fora do projeto (trecho cortado) · vídeo {n_video} {} · {}", duracao_fina(mo.ini), mo.posicao),
                        _ => format!("vídeo {n_video} · {} → {} · {}", duracao_fina(mo.ini), duracao_fina(mo.fim), mo.posicao),
                    }).font(tema::MONO).color(t.dim)))
                .child(texto)
                .child(if mo.apoio.is_empty() { el() } else { text(mo.apoio.clone()).font(tema::PEQ).color(t.dim).wrap() })
                .child(if mo.motivo.is_empty() { el() } else { text(format!("por quê: {}", mo.motivo)).font(tema::PEQ).color(t.dim.alpha(0.8)).wrap() })
                .child(if mo.arquivo_pronto.is_empty() { el() } else {
                    text(mo.arquivo_pronto.clone()).font(tema::MONO).color(t.acento).wrap_anywhere() })
                .child(refs_el)
                .child(if mo.status == "descartado" || mo.status == "pronto" && mo.briefing.is_empty() { el() } else { briefing_motion(s, m, mo, t, &k) })
                .child(if mo.status == "descartado" { el() } else { broll_acervo(s, m, mo, t) })
                .child(motion_opcoes(s, m, mo, t))
                .child(estado_video(mo, t))
                .child(if form_aberto { form_video(s, mo, t, &k) } else { el() })
                .child(acoes));
        }
        if e.sugestoes.iter().any(|m| m.status == "aprovado") {
            c = c.child(text("Motions aprovados: em cada um, «gerar motion (HyperFrames)» escreve e renderiza o MOV; depois «atualizar o \
                projeto» (ou o plugin Inserir motion) põe tudo na faixa Motion. O Claude também pode fazer os da fila (motion/fila.json).")
                .font(tema::PEQ).color(t.dim).wrap());
        }
    }
    c
}

fn duracao_fina(seg: f32) -> String {
    let s = seg.max(0.0);
    format!("{}:{:04.1}", (s / 60.0) as u32, s % 60.0)
}

/// As imagens de referência de UM momento: as dele (arrastadas para o card, o quadro do
/// preview, ou copiadas na pasta dele) e as gerais do item que você ligar a ele.
fn refs_do_momento(s: &App, mo: &crate::dados::Momento, gerais: &[String], t: Tema) -> El {
    let mut c = col().w_full().gap(6.0);
    let mut fotos = row().w_full().gap(6.0).flex_wrap().center_y();
    for r in &mo.referencias {
        let (id, r2) = (mo.id.clone(), r.clone());
        fotos = fotos.child(col().key(format!("mref-{}-{r}", mo.id)).w(72.0).gap(2.0)
            .child(el().w(72.0).h(72.0).radius(5.0).clip_rounded(5.0).fill(t.card2)
                .child(super::comum::imagem(s.miniaturas.get(r), "…", t))
                .child(row().absolute(48.0, 2.0)
                    .child(botao(format!("mtirar-{}-{r}", mo.id), "×", t.erro, false, t,
                                 move |s: &mut App| s.motion_ref(&id, "tirar", serde_json::json!({"arquivo": r2}))))))
            .child(text(r.rsplit('/').next().unwrap_or(r).to_string()).font(tema::MINI).color(t.dim).truncate()));
    }
    let (i1, i2) = (mo.id.clone(), mo.id.clone());
    fotos = fotos
        .child(botao(format!("mquadro-{}", mo.id), "+ quadro atual", t.txt, false, t, move |s: &mut App| s.motion_ref(&i1, "quadro", serde_json::json!({}))))
        .child(botao(format!("mpasta-{}", mo.id), "pasta deste momento", t.dim, false, t, move |s: &mut App| s.motion_ref(&i2, "pasta", serde_json::json!({}))));
    c = c.child(row().w_full().gap(6.0).center_y()
        .child(text(if mo.referencias.is_empty() { "REFERÊNCIAS DESTE MOMENTO — arraste imagens para o card" } else { "REFERÊNCIAS DESTE MOMENTO" })
            .font(tema::MINI).color(t.dim)));
    c = c.child(fotos);
    // as gerais do item, para ligar com um clique
    if !gerais.is_empty() {
        let mut chips = row().w_full().gap(6.0).flex_wrap().center_y()
            .child(text("usar também:").font(tema::PEQ).color(t.dim));
        for g in gerais {
            let on = mo.referencias.contains(g);
            let (id, g2) = (mo.id.clone(), g.clone());
            chips = chips.child(botao(format!("mger-{}-{g}", mo.id), g.rsplit('/').next().unwrap_or(g).to_string(),
                                      t.rep, on, t, move |s: &mut App| s.motion_ref(&id, "alternar", serde_json::json!({"arquivo": g2}))));
        }
        c = c.child(chips);
    }
    c
}

/// O que aconteceu com o vídeo gerado por IA deste momento.
fn estado_video(mo: &crate::dados::Momento, t: Tema) -> El {
    let Some(v) = mo.video_ia.as_ref() else { return el() };
    let (cor, txt) = match v.status.as_str() {
        "completed" => (t.acento, format!("vídeo IA pronto · {}{}", v.modelo,
                                         v.custo.map(|c| format!(" · US$ {c:.2}")).unwrap_or_default())),
        "failed" | "cancelled" | "expired" => (t.erro, format!("vídeo IA falhou ({}): {}", v.modelo, v.erro)),
        st => (t.alerta, format!("vídeo IA: {} em {} — acompanhe nas tarefas", if st.is_empty() { "enviando" } else { st }, v.modelo)),
    };
    text(txt).font(tema::PEQ).color(cor).wrap()
}

/// Gerar um vídeo (b-roll) com IA no OpenRouter para este momento.
fn form_video(s: &App, mo: &crate::dados::Momento, t: Tema, k: &rune_kit::Kit) -> El {
    let Some(f) = s.video_form.as_ref() else { return el() };
    let rot = |x: &str| text(x.to_string()).font(tema::MINI).color(t.dim);
    let mut c = col().key(format!("form-video-{}", mo.id)).w_full().gap(8.0).padding(10.0).radius(8.0)
        .fill(t.card2).border(1.0, t.rep.alpha(0.5))
        .child(text("VÍDEO COM IA · OPENROUTER — um b-roll que entra por cima do vídeo neste momento; a fala continua por baixo")
            .font(tema::MINI).color(t.rep).wrap());
    if !s.tem_chave_video() {
        c = c.child(row().w_full().gap(8.0).center_y()
            .child(text("Falta a chave do vídeo (OpenRouter): ela fica no painel das chaves, no botão da IA no topo.")
                .font(tema::PEQ).color(t.alerta).wrap().grow(1.0).min_w(0.0))
            .child(botao("video-abrir-chaves", "configurar chave", t.alerta, false, t, |s: &mut App| s.chave_aberta = true)));
    }
    let pensando = s.motion.as_ref().is_some_and(|m| m.pensando.contains(&format!("{}#video", mo.id)));
    let idp = mo.id.clone();
    c = c.child(row().w_full().gap(8.0).center_y()
            .child(rot("PROMPT (o que aparece no vídeo)"))
            .child(spacer())
            .child(botao("video-prompt-ia", if pensando { "a IA está escrevendo…" } else if f.prompt.text.trim().is_empty() { "escrever com IA" } else { "melhorar com IA" },
                         t.alerta, pensando, t, move |s: &mut App| { if !pensando { s.prompt_ia(&idp, "video") } })))
        .child(estilos(s, mo, "video", t))
        .child(rune_kit::TextArea::new(&f.prompt).width(None).auto_grow(3, 8)
            .placeholder("carregando uma sugestão de prompt…")
            .on_edit(|s: &mut App| { let f = s.video_form.as_mut().expect("form"); f.prompt_mexido = true; &mut f.prompt })
            .build(k).key("video-prompt").w_full())
        .child(alternativas_ia(s, &mo.id, "video", t));
    // modelos
    c = c.child(rot("MODELO"));
    if s.video_modelos.is_empty() {
        c = c.child(text("carregando os modelos de vídeo do OpenRouter…").font(tema::PEQ).color(t.dim));
    } else {
        let mut ms = row().w_full().gap(6.0).flex_wrap();
        for m in &s.video_modelos {
            let id = m.id.clone();
            let vertical = m.formatos.is_empty() || m.formatos.iter().any(|x| x == "9:16");
            let rotulo = if vertical { m.nome.clone() } else { format!("{} (só horizontal)", m.nome) };
            ms = ms.child(botao(format!("vm-{}", m.id), rotulo, t.acento, f.modelo == m.id, t, move |s: &mut App| s.video_modelo(&id)));
        }
        c = c.child(ms);
    }
    if let Some(m) = s.video_modelos.iter().find(|m| m.id == f.modelo) {
        let duracoes: Vec<i64> = m.duracoes.iter().copied().filter(|d| *d > 0).collect();
        if !duracoes.is_empty() {
            let mut r = row().gap(6.0).center_y().child(rot("DURAÇÃO"));
            for d in duracoes {
                r = r.child(botao(format!("vd-{d}"), format!("{d} s"), t.txt, f.duracao == Some(d), t,
                                  move |s: &mut App| { if let Some(f) = s.video_form.as_mut() { f.duracao = Some(d) } }));
            }
            c = c.child(r);
        }
        if m.resolucoes.len() > 1 {
            let mut r = row().gap(6.0).center_y().child(rot("RESOLUÇÃO"));
            for res in &m.resolucoes {
                let r2 = res.clone();
                r = r.child(botao(format!("vr-{res}"), res.clone(), t.txt, f.resolucao == *res, t,
                                  move |s: &mut App| { if let Some(f) = s.video_form.as_mut() { f.resolucao = r2.clone() } }));
            }
            c = c.child(r);
        }
        let mut r = row().w_full().gap(6.0).center_y().flex_wrap().child(rot("IMAGENS DO MOMENTO"));
        let opcoes: [(&str, &str); 3] = [("primeiro_quadro", "1ª imagem como início do vídeo"),
                                          ("referencias", "imagens como referência"), ("nenhuma", "só o prompt")];
        for (id, nome) in opcoes {
            let id2 = id.to_string();
            r = r.child(botao(format!("vref-{id}"), nome, t.txt, f.refs == id, t,
                              move |s: &mut App| { if let Some(f) = s.video_form.as_mut() { f.refs = id2.clone() } }));
        }
        c = c.child(r);
        if mo.referencias.is_empty() && f.refs != "nenhuma" {
            c = c.child(text("Este momento ainda não tem imagens: ponha uma em \"referências deste momento\" (ou use + quadro atual).")
                .font(tema::PEQ).color(t.dim).wrap());
        }
        if m.audio {
            c = c.child(row().gap(6.0).center_y()
                .child(botao("vaudio", if f.audio { "com som gerado" } else { "sem som (a fala continua)" }, t.txt, f.audio, t,
                             |s: &mut App| { if let Some(f) = s.video_form.as_mut() { f.audio = !f.audio } })));
        }
        let preco = m.precos.iter().map(|(k, v)| format!("{k}: US$ {v}")).collect::<Vec<_>>().join(" · ");
        c = c.child(text(format!("Preço do modelo (OpenRouter): {}. O custo real aparece aqui quando terminar.",
                                 if preco.is_empty() { "não informado".into() } else { preco }))
            .font(tema::PEQ).color(t.dim).wrap());
    }
    c.child(row().w_full().gap(8.0).center_y()
        .child(spacer())
        .child(botao("video-cancelar", "fechar", t.dim, false, t, |s: &mut App| s.video_form = None))
        .child(botao("video-gerar", "gerar vídeo", t.acento, false, t, |s: &mut App| s.video_gerar())))
}

/// O briefing do filme Motion: o que o Claude anima neste momento. Você escreve, ou pede à IA das
/// sugestões para escrever ou melhorar; vai para a fila junto do pedido.
fn briefing_motion(s: &App, m: &crate::app::MotionUi, mo: &crate::dados::Momento, t: Tema, k: &rune_kit::Kit) -> El {
    let chave = format!("{}#motion", mo.id);
    let pensando = m.pensando.contains(&chave);
    let atual = m.briefings.get(&mo.id).map(|e| e.text.clone()).unwrap_or_default();
    let mudou = atual.trim() != mo.briefing.trim();
    let (i1, i2, i3) = (mo.id.clone(), mo.id.clone(), mo.id.clone());
    col().w_full().gap(6.0)
        .child(row().w_full().gap(8.0).center_y()
            .child(text("DIREÇÃO DO MOTION (briefing para o Claude)").font(tema::MINI).color(t.dim))
            .child(spacer())
            .child(if mudou { botao(format!("bsalvar-{}", mo.id), "salvar", t.acento, false, t, move |s: &mut App| s.salvar_briefing(&i3)) } else { el() })
            .child(botao(format!("bia-{}", mo.id),
                         if pensando { "a IA está escrevendo…" } else if atual.trim().is_empty() { "sugerir com IA" } else { "melhorar com IA" },
                         t.alerta, pensando, t, move |s: &mut App| { if !s.motion.as_ref().is_some_and(|m| m.pensando.contains(&format!("{i1}#motion"))) { s.prompt_ia(&i1, "motion") } })))
        .child(estilos(s, mo, "motion", t))
        .child(rune_kit::TextArea::new(m.briefings.get(&mo.id).unwrap_or(&rune::TextEdit::new("")))
            .placeholder("ex.: nome entra da esquerda com uma faixa vermelha, fica 2 s, sai para cima; fonte grossa em caixa alta…")
            .width(None).auto_grow(2, 6)
            .on_edit(move |s: &mut App| s.motion.as_mut().expect("motion").briefings
                .entry(i2.clone()).or_insert_with(|| rune::TextEdit::new("")))
            .build(k).key(format!("brief-{}", mo.id)).w_full())
        .child(alternativas_ia(s, &mo.id, "motion", t))
}

/// B-roll do acervo: procurar (todas as fontes), ver 3–5 candidatos, escolher 1–3 em ordem.
fn broll_acervo(s: &App, m: &crate::app::MotionUi, mo: &crate::dados::Momento, t: Tema) -> El {
    let buscando = m.pensando.contains(&format!("{}#broll", mo.id));
    let b = mo.broll.clone().unwrap_or_default();
    let sel = m.broll_sel.get(&mo.id).cloned().unwrap_or_default();
    let (i1, i2) = (mo.id.clone(), mo.id.clone());
    let mut cab = row().w_full().gap(8.0).center_y()
        .child(text("B-ROLL DO ACERVO").font(tema::MINI).color(t.dim))
        .child(if b.buscas.is_empty() { el() } else {
            text(format!("buscas: {}", b.buscas.join(" · "))).font(tema::MINI).color(t.dim.alpha(0.7)).truncate().grow(1.0).min_w(0.0) })
        .child(spacer())
        .child(botao(format!("bproc-{}", mo.id), if buscando { "procurando…" } else if b.candidatos.is_empty() { "procurar" } else { "procurar de novo" },
                     t.txt, buscando, t, move |s: &mut App| s.broll_procurar(&i1, false)));
    if s.claude {
        cab = cab.child(botao(format!("bproc-ia-{}", mo.id), "procurar com IA", t.alerta, buscando, t,
                              move |s: &mut App| s.broll_procurar(&i2, true)));
    }
    let mut c = col().w_full().gap(6.0).child(cab);
    if !b.candidatos.is_empty() {
        let mut fila = row().w_full().gap(8.0).flex_wrap();
        for cand in &b.candidatos {
            let ordem = sel.iter().position(|x| *x == cand.id);
            let (id, cid) = (mo.id.clone(), cand.id.clone());
            let quando = if cand.tipo == "video" && cand.fim > 0.0 { format!(" {}–{}", duracao_fina(cand.ini), duracao_fina(cand.fim)) } else { String::new() };
            fila = fila.child(col().key(format!("bc-{}-{}", mo.id, cand.id)).w(112.0).gap(3.0).padding(4.0).radius(6.0)
                .fill(if ordem.is_some() { t.acento.alpha(0.15) } else { t.card2 })
                .border(1.0, if ordem.is_some() { t.acento } else { t.linha })
                .cursor(Cursor::Pointer).hover(t.linha_forte.alpha(0.2))
                .child(el().w(104.0).h(104.0).radius(4.0).clip_rounded(4.0).fill(t.card)
                    .child(super::comum::imagem(s.miniaturas.get(&cand.miniatura), &cand.tipo, t))
                    .child(match ordem { Some(i) => row().absolute(4.0, 4.0).child(etiqueta(format!("{}", i + 1), t.acento)), None => el() }))
                .child(text(format!("{} · {}{quando}", cand.fonte, cand.tipo)).font(tema::MINI).color(t.rep).truncate())
                .child(text(cand.texto.clone()).font(tema::MINI).color(t.dim).truncate())
                .on_press(move |s: &mut App| s.broll_alternar(&id, &cid)));
        }
        c = c.child(fila);
    }
    let dur = (mo.fim - mo.ini).max(1.0);
    if !sel.is_empty() {
        let (i3, i4) = (mo.id.clone(), mo.id.clone());
        c = c.child(row().w_full().gap(8.0).center_y()
            .child(text(format!("sequência: {} pedaço(s), ~{:.1} s cada (o momento tem {:.1} s)", sel.len(), dur / sel.len() as f32, dur))
                .font(tema::PEQ).color(t.txt).grow(1.0).min_w(0.0))
            .child(botao(format!("blimpa-{}", mo.id), "desmarcar", t.dim, false, t, move |s: &mut App| {
                if let Some(m) = s.motion.as_mut() { m.broll_sel.remove(&i4); } }))
            .child(botao(format!("busar-{}", mo.id), "usar esta sequência ★", t.acento, false, t, move |s: &mut App| s.broll_usar(&i3, false))));
    } else if !b.sequencia.is_empty() {
        let i5 = mo.id.clone();
        let nomes: Vec<String> = b.sequencia.iter().map(|p| format!("{} ({:.1} s)", p.arquivo.rsplit('/').next().unwrap_or(&p.arquivo), p.dur)).collect();
        c = c.child(row().w_full().gap(8.0).center_y()
            .child(text(format!("no ar: {}", nomes.join(" → "))).font(tema::PEQ).color(t.acento).wrap().grow(1.0).min_w(0.0))
            .child(botao(format!("btira-{}", mo.id), "tirar b-roll", t.erro, false, t, move |s: &mut App| s.broll_usar(&i5, true))));
    }
    c
}

/// Antes de gerar: os estilos prontos para o tipo do momento (um clique escreve o texto a partir do
/// modelo) e o pedido de três abordagens diferentes à IA, cada uma com nome e ideia, para escolher.
fn estilos(s: &App, mo: &crate::dados::Momento, alvo: &str, t: Tema) -> El {
    let tipo = if alvo == "video" && mo.tipo != "broll" { "broll" } else { mo.tipo.as_str() };
    let mut mods = s.modelos_para(alvo, &mo.tipo);
    if mods.is_empty() { mods = s.modelos_para(alvo, tipo); }
    let escolhido = if alvo == "video" { &mo.modelo_video } else { &mo.modelo_motion };
    let chave = format!("{}#{alvo}#abordagens", mo.id);
    let pensando = s.motion.as_ref().is_some_and(|m| m.pensando.contains(&chave));
    let mut linha = row().w_full().gap(6.0).center_y().wrap()
        .child(text("ESTILO").font(tema::MINI).color(t.dim));
    for m in &mods {
        let (id, alvo2, mid) = (mo.id.clone(), alvo.to_string(), m.id.clone());
        linha = linha.child(botao(format!("est-{}-{alvo}-{}", mo.id, m.id), m.nome.clone(), t.acento, *escolhido == m.id, t,
                                  move |s: &mut App| s.aplicar_modelo(&id, &alvo2, &mid)));
    }
    let (id, alvo2) = (mo.id.clone(), alvo.to_string());
    linha = linha.child(spacer())
        .child(botao(format!("abord-{}-{alvo}", mo.id), if pensando { "a IA está pensando…" } else { "IA: 3 abordagens" },
                     t.alerta, pensando, t, move |s: &mut App| { if !pensando { s.pedir_abordagens(&id, &alvo2) } }));
    let mut c = col().w_full().gap(4.0).child(linha);
    if let Some(m) = mods.iter().find(|m| m.id == *escolhido) && !m.descricao.is_empty() {
        c = c.child(text(m.descricao.clone()).font(tema::PEQ).color(t.dim).wrap());
    }
    if let Some(ops) = s.motion.as_ref().and_then(|m| m.abordagens.get(&chave)) {
        for (i, o) in ops.iter().enumerate() {
            let (id, alvo2, txt) = (mo.id.clone(), alvo.to_string(), o.texto.clone());
            c = c.child(col().key(format!("abo-{}-{alvo}-{i}", mo.id)).w_full().gap(3.0).padding(8.0).radius(6.0)
                .fill(t.card).border(1.0, t.alerta.alpha(0.4)).cursor(Cursor::Pointer).hover(t.linha_forte.alpha(0.2))
                .child(row().w_full().gap(8.0).center_y()
                    .child(text(o.nome.clone()).font(tema::NORMAL_M).color(t.alerta))
                    .child(text(o.ideia.clone()).font(tema::PEQ).color(t.dim).wrap().grow(1.0).min_w(0.0))
                    .child(text("usar esta").font(tema::MINI).color(t.acento)))
                .child(text(o.texto.clone()).font(tema::PEQ).color(t.txt).wrap())
                .on_press(move |s: &mut App| s.usar_abordagem(&id, &alvo2, &txt)));
        }
    }
    c
}

/// As outras versões que a IA deu (clique para usar) e a nota dela.
fn alternativas_ia(s: &App, id: &str, alvo: &str, t: Tema) -> El {
    let Some((alts, nota)) = s.motion.as_ref().and_then(|m| m.alternativas.get(&format!("{id}#{alvo}"))) else { return el() };
    let mut c = col().w_full().gap(4.0);
    if !nota.is_empty() {
        c = c.child(text(format!("IA: {nota}")).font(tema::PEQ).color(t.dim).wrap());
    }
    for (i, a) in alts.iter().enumerate() {
        let (id2, alvo2, a2) = (id.to_string(), alvo.to_string(), a.clone());
        c = c.child(row().key(format!("alt-{id}-{alvo}-{i}")).w_full().gap(8.0).padding(6.0).radius(6.0)
            .fill(t.card).border(1.0, t.linha).cursor(Cursor::Pointer).hover(t.linha_forte.alpha(0.2))
            .child(text(format!("outra versão {}:", i + 1)).font(tema::MINI).color(t.alerta))
            .child(text(a.clone()).font(tema::PEQ).color(t.txt).wrap().grow(1.0).min_w(0.0))
            .on_press(move |s: &mut App| s.usar_alternativa(&id2, &alvo2, &a2)));
    }
    c
}
