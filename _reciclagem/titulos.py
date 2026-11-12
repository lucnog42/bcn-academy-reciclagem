#!/usr/bin/env python3
"""Título e subtítulo automáticos para o Lower Third.

Ordem de preferência do título:

    1. confronto           "BCN x ADVA", "Juvenil x Barça"
    2. nome do atleta      "Derli Jr.", "Lucas Alves Júnior"
    3. evento              "Copa Micfootball 2024"
    4. assunto da legenda  primeiras palavras que não são muleta

Subtítulo combina evento + lugar + data (o que existir), no formato
`MIC 2024 · Barcelona · 10/08/2022`.

Descartar muleta importa: "Mais um atleta BCN no Camp Nou" virava título
"Mais um atleta BCN", que não diz nada a quem para o dedo no feed.
"""
from __future__ import annotations

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
NAO_NOMES = {
    "bcn", "barcelona", "mic", "copa", "marcet", "espanha", "españa", "brasil",
    "futebol", "fútbol", "academy", "sports", "intercambio", "intercâmbio",
    "camp", "nou", "lloret", "girona", "madrid", "europa", "copa", "time", "clube",
    "mundial", "copa", "sub", "monday", "instagram",
}
EVENTOS = [
    (r"\bcopa\s+mic(?:football)?\b", "Copa Micfootball"),
    (r"\bmic\s*football\b", "MIC Football"),
    (r"\bmic\s*(20\d\d)\b", "MIC"),
    (r"\bmic\b", "MIC"),
    (r"\bcopa\s+girona\b", "Copa Girona"),
    (r"\bdesafio\s+barcelona\b", "Desafio Barcelona"),
    (r"\bbcn\s*cup\b", "BCN Cup"),
    (r"\bcopa\s+ibero[\w-]*\b|\bibero[\s-]*americano\b", "Ibero Americano"),
    (r"\bnike\s*3\s*x\s*3\b", "Nike 3x3"),
    (r"\bcopa\s+diadora\b", "Copa Diadora"),
    (r"\bmarcet\b", "Marcet"),
    (r"\bcenafe\b", "Cenafe"),
]
LUGARES = [
    ("camp nou", "Camp Nou"), ("masia", "La Masia"), ("lloret", "Lloret de Mar"),
    ("girona", "Girona"), ("tibidabo", "Tibidabo"), ("bacelona", "Barcelona"),
    ("barcelona", "Barcelona"), ("madrid", "Madrid"), ("valencia", "Valência"),
    ("espanha", "Espanha"), ("españa", "Espanha"),
]
PADROES_PESSOA = [
    r"nosso atleta ([A-ZÀ-Ý][\wÀ-ÿ'’.-]*(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'’.-]*){0,3})",
    r"atleta (?:bcn|da bcn) ([A-ZÀ-Ý][\wÀ-ÿ'’.-]*(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'’.-]*){0,3})",
    r"jogador (?:bcn|da bcn) ([A-ZÀ-Ý][\wÀ-ÿ'’.-]*(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'’.-]*){0,3})",
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
    """'BCN x ADVA', 'Juvenil x Barça' — o par que o post anuncia."""
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
    for padrao, nome in EVENTOS:
        m = re.search(padrao, t)
        if not m:
            continue
        ano = re.search(r"20\d\d", t)
        if nome == "MIC" and m.groups() and m.group(1):
            return f"MIC {m.group(1)}"
        if ano and nome in ("MIC", "Copa Micfootball", "Copa Girona", "BCN Cup"):
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
