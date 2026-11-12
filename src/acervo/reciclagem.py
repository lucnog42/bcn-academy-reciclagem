#!/usr/bin/env python3
"""Passo 3 — escolhe o que reciclar e monta o plano + calendário de 4 semanas.

    python3 src/acervo/reciclagem.py                 # top 40
    python3 src/acervo/reciclagem.py --n 80
    python3 src/acervo/reciclagem.py --pilar <PILAR> --desde 2022

Saída em dados/marcas/<marca>/reciclagem/:
    plano_reciclagem.csv   uma linha por post escolhido (abre no Sheets)
    PLANO.md               leitura humana: motivos, ângulo, calendário
    rascunhos/<post>.md    molde de legenda para preencher/gerar
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import csv
import datetime as dt
import os
import statistics
import sys
from collections import Counter, defaultdict
from acervo import colecao  # noqa: E402

from nucleo import caminhos  # noqa: E402
AQUI = caminhos.dados("reciclagem")
BASE = colecao.BASE
RASCUNHOS = os.path.join(AQUI, "rascunhos")

_CFG = colecao._CFG
ANGULO: dict[str, str] = dict(_CFG["pilares"].get("angulo") or {})
HASTAG_BASE = _CFG["vocabulario"].get("hashtags") or ""


def saida(p: dict) -> str:
    f = p["formatos"]
    if p["tem_video"] and "9:16" in f:
        return "REEL — cortar 15-25s do melhor trecho, capa nova, texto na tela"
    if p["tem_video"]:
        return "REEL — vídeo 1:1 com moldura 9:16 e blur de fundo"
    if p["n_midias"] >= 4:
        return "CARROSSEL — 6 a 8 cards, capa nova (3 primeiras decidem o alcance)"
    if p["n_midias"] in (2, 3):
        return "CARROSSEL CURTO — 3 cards + CTA no último"
    return "ESTÁTICO 4:5 + STORY — card único e enquete no story"


def pontuar(posts: list[dict], hoje: dt.date) -> list[dict]:
    """Score vem de colecao.pontuar (mesmo usado no painel); aqui só anota o resto."""
    ranking = colecao.pontuar(posts, hoje)
    for p in ranking:
        p["saida"] = saida(p)
        p["pasta_post"] = pasta_post(p)
        p["angulo"] = ANGULO.get(p["pilar"], ANGULO["OUTROS"])
    return ranking


def cotas(selecionados: list[dict], n: int, teto: float = 0.4) -> list[dict]:
    """Distribui as vagas por pilar proporcionalmente, mas nenhum pilar passa de
    `teto` (40%) — sem isso o plano vira 100% do pilar dominante do acervo."""
    por_pilar = defaultdict(list)
    for p in selecionados:
        por_pilar[p["pilar"]].append(p)
    total = len(selecionados)
    limite = max(1, round(n * teto))
    escolhidos, sobra = [], n
    for pilar, itens in por_pilar.items():
        qtd = min(len(itens), max(1, round(n * len(itens) / total)), limite)
        escolhidos += itens[:qtd]
        sobra -= qtd
    # devolve as vagas que sobraram ao melhor score ainda não escolhido,
    # respeitando o mesmo teto (senão o torneio reaparece pelas sobras)
    usados = {p["post_id"] for p in escolhidos}
    contagem = defaultdict(int)
    for p in escolhidos:
        contagem[p["pilar"]] += 1
    for p in selecionados:
        if sobra <= 0:
            break
        if p["post_id"] in usados or contagem[p["pilar"]] >= limite:
            continue
        escolhidos.append(p)
        usados.add(p["post_id"])
        contagem[p["pilar"]] += 1
        sobra -= 1
    escolhidos.sort(key=lambda p: p["score"], reverse=True)
    return escolhidos[:n]


def pasta_post(p: dict) -> str:
    """Pasta que contém a mídia: _posts/<ano>/<post>/ (ou a subpasta manual)."""
    primeiro = p["midias"][0]
    partes = primeiro.split(os.sep)
    if "imagens" in partes or "videos" in partes:
        return os.sep.join(partes[:-2])
    return os.path.dirname(primeiro) or "(raiz)"


def rascunho(p: dict) -> str:
    return f"""# {p['post_shortcode'] or p['post_id']} — {p['pilar']}

origem: {p['url']}
data original: {p['data']}  ·  curtidas: {p['curtidas']}  ·  midias: {p['n_midias']}
pasta: {p['pasta_post']}

## O que é dito no vídeo
> {p['fala'] or '(sem transcrição — vídeo mudo, sem áudio ou ainda não transcrito)'}

## Gancho (1ª linha, até 8 palavras)
> {p['gancho'] or '(reescrever do zero)'}

## Molde
GANCHO ......... (frase de 1 linha, com o nome do atleta ou a data do evento)
CONTEXTO ....... 2 linhas: onde, quando, com quem
PROVA .......... 1 dado concreto (aprovado, gol, tempo de programa, clube)
CTA ............ "Avaliações abertas: [cidade] — link na bio"
HASHTAGS ....... {p['hashtags'] or HASTAG_BASE}

## Saída
{p['saida']}

## Ângulo
{p['angulo']}

## Por que este pilar
`{p['pilar']}` (confiança {p['confianca']}) — termos que sustentaram: {p['evidencias'] or 'sem legenda'}{f" · também casa com: {p['pilar_secundario']}" if p['pilar_secundario'] else ""}
{"" if p.get('melhor_do_grupo', True) else "ATENÇÃO: legenda repetida em outro post com melhor desempenho — use aquele."}

## Checklist antes de publicar
- [ ] passou de 6 meses desde a publicação original
- [ ] capa nova (o algoritmo não republica igual)
- [ ] legenda reescrita (não copiar e colar)
- [ ] formato correto: 4:5 no feed, 9:16 no reel/story
- [ ] marcar atleta/clube se ainda houver relação
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--pilar")
    ap.add_argument("--desde", type=int, default=2021)
    ap.add_argument("--incluir-marcados", action="store_true",
                    help="ignora as marcacoes do painel (repostado / nao interessante)")
    a = ap.parse_args()

    midias, orfaos, quebrados = colecao.coletar(BASE)
    posts = colecao.marcar_repetidos(colecao.agrupar_posts(midias))
    posts = [p for p in posts if p["data"] and int(p["data"][:4]) >= a.desde]
    if not a.incluir_marcados:
        estados = colecao.carregar_estados()
        antes = len(posts)
        posts = [p for p in posts
                 if not (estados.get(os.path.basename(pasta_post(p)), {}).get("repostado")
                         or estados.get(os.path.basename(pasta_post(p)), {}).get("nao_interessante"))]
        if antes - len(posts):
            print(f"fora da fila por marcacao: {antes - len(posts)} posts "
                  f"(repostado / nao interessante)")
    if a.pilar:
        posts = [p for p in posts if p["pilar"] == a.pilar.upper()]
    hoje = dt.date.today()
    ranking = cotas(pontuar(posts, hoje), a.n)

    os.makedirs(RASCUNHOS, exist_ok=True)
    cols = ["prioridade", "score", "post_id", "post_shortcode", "pilar", "confianca", "data",
            "idade_dias", "curtidas", "vs_mediana", "percentil", "repetido", "melhor_do_grupo", "tipo", "n_midias", "formatos",
            "tem_video", "tem_fala", "local", "pasta_post", "angulo", "saida", "gancho", "url", "midias"]
    caminho = os.path.join(AQUI, "plano_reciclagem.csv")
    with open(caminho, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i, p in enumerate(ranking, 1):
            linha = dict(p)
            linha["prioridade"] = i
            linha["midias"] = " | ".join(p["midias"])
            w.writerow(linha)
            with open(os.path.join(RASCUNHOS, f"{i:02d}_{p['post_shortcode'] or p['post_id']}.md"),
                      "w", encoding="utf-8") as rf:
                rf.write(rascunho(p))

    # calendário: 3 posts/semana, alternando pilar
    por_pilar = defaultdict(list)
    for p in ranking:
        por_pilar[p["pilar"]].append(p)
    ordem = [k for k, _ in Counter(p["pilar"] for p in ranking).most_common()]
    agenda, i_pilar, segunda = [], 0, hoje
    while len(agenda) < min(len(ranking), 12):
        for dia_semana in (0, 2, 4):
            if len(agenda) >= 12:
                break
            tentativas = 0
            while tentativas < len(ordem):
                pilar = ordem[i_pilar % len(ordem)]
                i_pilar += 1
                tentativas += 1
                if por_pilar.get(pilar):
                    p = por_pilar[pilar].pop(0)
                    agenda.append((segunda + dt.timedelta(days=dia_semana), p))
                    break
        segunda += dt.timedelta(days=7)

    linhas = [
        f"# Plano de reciclagem — {_CFG['marca'].get('nome', '')}",
        "",
        f"Gerado em {hoje.isoformat()} · {len(posts)} posts no filtro · "
        f"{len(ranking)} selecionados.",
        "",
        "## Distribuição dos selecionados",
        "",
        "| pilar | posts |",
        "|---|---|",
    ]
    linhas += [f"| {k} | {v} |" for k, v in Counter(p["pilar"] for p in ranking).most_common()]
    conf = [p["confianca"] for p in ranking if p["confianca"]]
    if conf:
        linhas += ["", f"Confiança média do rótulo: **{sum(conf)/len(conf):.2f}** "
                       "(1.0 = um único pilar sustenta a legenda; 0.5 = empate técnico)"]
    linhas += ["", "## Top 15", "",
               "| # | score | data | pilar | curtidas | saída |",
               "|---|---|---|---|---|---|"]
    for i, p in enumerate(ranking[:15], 1):
        linhas.append(f"| {i} | {p['score']} | {p['data'][:10]} | {p['pilar']} | "
                      f"{p['curtidas']} | {p['saida'].split('—')[0].strip()} |")
    linhas += ["", "## Calendário sugerido (3 posts/semana)", "",
               "| semana | data | pilar | post | ângulo |", "|---|---|---|---|---|"]
    for semana, (dia, p) in enumerate(agenda):
        linhas.append(f"| {semana // 3 + 1} | {dia.isoformat()} | {p['pilar']} | "
                      f"{p['post_shortcode']} | {p['angulo'].split('—')[0].strip()} |")
    linhas += [
        "",
        "## Regras que evitam a conta ser penalizada",
        "",
        "1. Não reposte o mesmo arquivo: capa nova, corte diferente, legenda nova.",
        "2. Janela mínima de 6 meses desde a publicação original (o script já penaliza <150 dias).",
        "3. Um pilar por dia; não emende dois posts do mesmo assunto na mesma semana.",
        "4. Áudio em alta só em reel novo; áudio original antigo derruba entrega.",
        "5. Salve o comprovante de desempenho: o `likes` do JSON é a mediana histórica do perfil — "
        "compare sempre com ela (`vs_mediana`), nunca com número absoluto.",
        "",
        f"Detalhe por post: `plano_reciclagem.csv` · moldes: `rascunhos/`",
    ]
    with open(os.path.join(AQUI, "PLANO.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas) + "\n")

    print(f"{len(ranking)} posts selecionados de {len(midias)} midias")
    print("por pilar:", dict(Counter(p["pilar"] for p in ranking)))
    print(f"\nplano_reciclagem.csv · PLANO.md · rascunhos/ ({len(ranking)} moldes)")


if __name__ == "__main__":
    main()
