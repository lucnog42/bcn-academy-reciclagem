#!/usr/bin/env python3
"""Título e subtítulo automáticos para o Lower Third.

Ordem de preferência do título:

    1. confronto           "Time A x Time B"
    2. nome do atleta      "Fulano Jr."
    3. evento              (os eventos da marca: config/marcas/<marca>/vocabulario.toml)
    4. assunto da legenda  primeiras palavras que não são muleta

Subtítulo combina evento + lugar + data (o que existir), no formato
`Evento 2024 · Cidade · 10/08/2022`.

Descartar muleta importa: "Mais um atleta da marca no estádio" virava título
"Mais um atleta", que não diz nada a quem para o dedo no feed.
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import re
import unicodedata

# palavras que abrem legenda de Instagram e não informam nada no título
MULETAS = {
    "mais", "um", "uma", "uns", "umas", "hoje", "ontem", "amanha", "agora", "aqui",
    "nosso", "nossa", "nossos", "nossas", "esse", "essa", "este", "esta", "isso",
    "e", "eh", "foi", "era", "sera", "vai", "vamos", "tem", "temos", "estamos",
    "muito", "muita", "bom", "boa", "grande", "grandes", "dia", "vez", "coisa",
    "galera", "pessoal", "gente", "todo", "toda", "todos", "todas", "com", "para",
    "pra", "por", "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
    "a", "o", "as", "os", "que", "se", "ja", "tambem", "so", "mais", "novo", "nova",
}
# nomes que aparecem em legenda mas não são pessoa
from nucleo import config  # noqa: E402

_VOC = config.carregar()["vocabulario"]
_SLUG = config.carregar()["marca"].get("slug", "")
# nomes que aparecem em legenda mas não são pessoa (da marca)
NAO_NOMES = set(_VOC.get("nao_nomes") or []) | {"instagram", "monday"}
EVENTOS = [tuple(x) for x in _VOC.get("eventos") or []]
LUGARES = [tuple(x) for x in _VOC.get("lugares") or []]
PADROES_PESSOA = [
    r"nosso atleta ([A-ZÀ-Ý][\wÀ-ÿ'’.-]*(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'’.-]*){0,3})",
    rf"atleta (?:{re.escape(_SLUG)}|da {re.escape(_SLUG)}) ([A-ZÀ-Ý][\wÀ-ÿ'’.-]*(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'’.-]*){{0,3}})",
    rf"jogador (?:{re.escape(_SLUG)}|da {re.escape(_SLUG)}) ([A-ZÀ-Ý][\wÀ-ÿ'’.-]*(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'’.-]*){{0,3}})",
    r"goleiro ([A-ZÀ-Ý][\wÀ-ÿ'’.-]*(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'’.-]*){0,2})",
]


def _limpo(texto: str) -> str:
    t = re.sub(r"https?://\S+|#\w+|@[\w.]+", " ", texto or "")
    t = "".join(ch if unicodedata.category(ch)[0] in "LN" or ch in " -'’.!?" else " "
                for ch in t)
    return re.sub(r"\s+", " ", t).strip()


def _palavras_uteis(texto: str, limite: int = 4) -> str:
    ditas = []
    for bruta in _limpo(texto).split():
        p = bruta.strip(".,!?'’-").lower()
        if len(p) < 3 or p in MULETAS:
            continue
        ditas.append(bruta.strip(".,!?"))
        if len(ditas) >= limite:
            break
    return " ".join(ditas)


def confronto(texto: str) -> str:
    """'Time A x Time B' — o par que o post anuncia."""
    m = re.search(r"([A-ZÀ-Ý][\wÀ-ÿ]{1,14}(?:\s+[A-ZÀ-Ý][\wÀ-ÿ]{1,14})?)\s+[xX×]\s+"
                  r"([A-ZÀ-Ý][\wÀ-ÿ]{1,14}(?:\s+[A-ZÀ-Ý][\wÀ-ÿ]{1,14})?)", texto or "")
    if not m:
        return ""
    a, b = m.group(1).strip(), m.group(2).strip()
    if a.lower() in NAO_NOMES and b.lower() in NAO_NOMES:
        return ""
    return f"{a} x {b}"


def pessoa(texto: str) -> str:
    for padrao in PADROES_PESSOA:
        m = re.search(padrao, texto or "")
        if m:
            nome = m.group(1).strip(" .,-")
            if nome.split()[0].lower() not in NAO_NOMES and len(nome) > 3:
                return nome
    return ""


def evento(texto: str) -> str:
    t = (texto or "").lower()
    # cada evento: [regex, nome] ou [regex, nome, true] = "leva o ano" (do grupo da regex
    # ou de um ano escrito na legenda)
    for ev in EVENTOS:
        padrao, nome = ev[0], ev[1]
        com_ano = len(ev) > 2 and bool(ev[2])
        m = re.search(padrao, t)
        if not m:
            continue
        if m.groups() and m.group(1):
            return f"{nome} {m.group(1)}"
        ano = re.search(r"20\d\d", t)
        if ano and com_ano:
            return f"{nome} {ano.group(0)}"
        return nome
    return ""


def lugar(texto: str) -> str:
    t = (texto or "").lower()
    for chave, nome in LUGARES:
        if chave in t:
            return nome
    return ""


def gerar(post: dict) -> tuple[str, str]:
    """(título, subtítulo) a partir da legenda, da fala e dos metadados."""
    corpo = " ".join(x for x in (post.get("legenda"), post.get("fala")) if x)
    data = (post.get("data") or "")[:10]
    dia, mes, ano = (data.split("-") if data else ("", "", ""))[::-1]

    titulo = (confronto(post.get("legenda") or "")
              or pessoa(post.get("legenda") or "")
              or pessoa(corpo)
              or evento(post.get("legenda") or "")
              or evento(corpo)
              or _palavras_uteis(post.get("legenda") or "", 4)
              or post.get("pilar", "").title())

    partes_sub = []
    ev = evento(post.get("legenda") or "") or evento(corpo)
    if ev and ev.lower() not in titulo.lower():
        partes_sub.append(ev)
    lg = lugar(post.get("local") or "") or lugar(post.get("legenda") or "")
    if lg and lg.lower() not in titulo.lower():
        partes_sub.append(lg)
    if dia and mes and ano:
        partes_sub.append(f"{dia}/{mes}/{ano}")
    if not partes_sub:
        partes_sub.append(post.get("pilar", "").title())
    subtitulo = " · ".join(partes_sub[:3])
    return titulo[:40], subtitulo[:60]
