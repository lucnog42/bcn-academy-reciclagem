#!/usr/bin/env python3
"""Índice de b-roll: tudo o que pode cobrir uma fala, de todas as fontes da marca, numa busca só.

Fontes (config/marcas/<marca>/acervo.toml, `[[fontes]]`):
  * posts  -> cada imagem e cada vídeo dos posts publicados; vídeo com transcrição vira trechos
              de ~5 s com o que é falado neles (dá para cobrir com um pedaço exato)
  * cortes -> os vídeos das pastas de cortes, também em trechos
  * pasta  -> uma pasta qualquer (arquivo bruto, HD externo, outro cliente): o texto é o caminho
              (pastas e nome do arquivo). Só entra com `ativo = true`. Nada é copiado: o índice
              guarda o caminho e o projeto aponta para o original.

O índice é SQLite FTS5 em dados/marcas/<marca>/indice/broll.sqlite (sem acento, sem caixa).

    python3 src/achar/indice.py                  # refaz o índice
    python3 src/achar/indice.py --fonte bruto    # só uma fonte
    python3 src/achar/indice.py --buscar "estádio torcida"
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import os
import re
import sqlite3
import time

from nucleo import caminhos, config  # noqa: E402

VIDEO = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts")
IMAGEM = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff")
TRECHO = 5.0          # s por trecho de vídeo transcrito
COLUNAS = ("texto", "fonte", "arquivo", "tipo", "ini", "fim", "item", "pilar", "data")


def caminho_db() -> str:
    return caminhos.dados("indice", "broll.sqlite")


def abrir(db: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(db or caminho_db())
    con.execute("create virtual table if not exists midias using fts5("
                "texto, fonte unindexed, arquivo unindexed, tipo unindexed, ini unindexed, fim unindexed, "
                "item unindexed, pilar unindexed, data unindexed, tokenize = 'unicode61 remove_diacritics 2')")
    con.execute("create table if not exists fontes (id text primary key, quando real, n integer)")
    return con


def _limpar(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_\-./\\#@]+", " ", t or "")).strip()


def _trechos_de_video(video_rel: str) -> list[tuple[float, float, str]]:
    """Trechos de ~5 s com o que é falado, pela transcrição (vazio se não houver)."""
    from plano import momentos
    try:
        ws = momentos._palavras(video_rel)
    except Exception:
        return []
    out, ini, txt = [], None, []
    for a, b, t in ws:
        if ini is None:
            ini = a
        txt.append(t)
        if b - ini >= TRECHO:
            out.append((ini, b, " ".join(txt)))
            ini, txt = None, []
    if ini is not None and txt:
        out.append((ini, ws[-1][1], " ".join(txt)))
    return out


def _linhas_posts() -> list[tuple]:
    from acervo import listas
    linhas = []
    for p in listas.montar_dados(limite_fala=4000, limite_legenda=2000):
        contexto = " ".join([p.get("gancho") or "", _limpar(p.get("nome") or ""), p.get("pilar") or ""])
        for m in p.get("midias") or []:
            ext = os.path.splitext(m)[1].lower()
            if ext in IMAGEM:
                linhas.append((contexto, "posts", m, "imagem", 0.0, 0.0, p["pasta"], p.get("pilar", ""), p.get("data", "")))
            elif ext in VIDEO:
                trechos = _trechos_de_video(m)
                if not trechos:
                    linhas.append((contexto, "posts", m, "video", 0.0, 0.0, p["pasta"], p.get("pilar", ""), p.get("data", "")))
                for a, b, t in trechos:
                    linhas.append((f"{t} {contexto}", "posts", m, "video", a, b, p["pasta"], p.get("pilar", ""), p.get("data", "")))
    return linhas


def _linhas_cortes() -> list[tuple]:
    from acervo import listas
    linhas = []
    for c in listas.montar_cortes(limite_fala=4000):
        contexto = " ".join([_limpar(c.get("tema") or c.get("nome_arq") or ""), c.get("pilar") or ""])
        for v in c.get("videos") or []:
            trechos = _trechos_de_video(v)
            if not trechos:
                linhas.append((f"{contexto} {_limpar(os.path.basename(v))}", "cortes", v, "video", 0.0, 0.0,
                               c["arquivo"], c.get("pilar", ""), ""))
            for a, b, t in trechos:
                linhas.append((f"{t} {contexto}", "cortes", v, "video", a, b, c["arquivo"], c.get("pilar", ""), ""))
    return linhas


def _linhas_pasta(f: dict) -> list[tuple]:
    raiz = os.path.expanduser(f.get("raiz") or "")
    if not raiz or not os.path.isdir(raiz):
        return []
    ignorar = [x.lower() for x in f.get("ignorar") or []]
    linhas = []
    for r, dirs, arqs in os.walk(raiz):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not any(i in d.lower() for i in ignorar))
        rel_dir = os.path.relpath(r, raiz)
        for a in sorted(arqs):
            ext = os.path.splitext(a)[1].lower()
            tipo = "video" if ext in VIDEO else "imagem" if ext in IMAGEM else None
            if not tipo or a.startswith("."):
                continue
            texto = _limpar(f"{rel_dir} {os.path.splitext(a)[0]}")
            ano = re.search(r"(20\d\d)", rel_dir + a)
            linhas.append((texto, f["id"], os.path.join(r, a), tipo, 0.0, 0.0, rel_dir, "", ano.group(1) if ano else ""))
    return linhas


def fontes() -> list[dict]:
    return [f for f in config.carregar().get("fontes") or [] if f.get("ativo", True)]


def indexar(so: str | None = None, db: str | None = None) -> dict[str, int]:
    con = abrir(db)
    feitos = {}
    for f in fontes():
        if so and f["id"] != so:
            continue
        tipo = f.get("tipo") or "pasta"
        linhas = (_linhas_posts() if tipo == "posts" else _linhas_cortes() if tipo == "cortes" else _linhas_pasta(f))
        linhas = [(l[0], f["id"], *l[2:]) for l in linhas]
        con.execute("delete from midias where fonte = ?", (f["id"],))
        con.executemany(f"insert into midias ({', '.join(COLUNAS)}) values ({', '.join('?' * len(COLUNAS))})", linhas)
        con.execute("insert or replace into fontes values (?, ?, ?)", (f["id"], time.time(), len(linhas)))
        feitos[f["id"]] = len(linhas)
    con.commit()
    con.close()
    return feitos


def precisa_indexar(db: str | None = None) -> bool:
    if not os.path.exists(db or caminho_db()):
        return True
    con = abrir(db)
    linhas = con.execute("select id, quando from fontes").fetchall()
    con.close()
    feitas = {i: q for i, q in linhas}
    # fonte nova na config, ou índice com mais de 12 h (o acervo muda com a organização e o scraper)
    return any(f["id"] not in feitas or time.time() - feitas[f["id"]] > 12 * 3600 for f in fontes())


def consulta_fts(termos: list[str]) -> str:
    """Termos soltos -> uma consulta FTS5 com OR (cada termo entre aspas, sem operadores)."""
    limpos = []
    for t in termos:
        t = re.sub(r'["*^():]', " ", t).strip()
        if t and t.lower() not in ("and", "or", "not", "near"):
            limpos.append(f'"{t}"')
    return " OR ".join(dict.fromkeys(limpos))


def buscar(termos: list[str], limite: int = 40, db: str | None = None) -> list[dict]:
    q = consulta_fts(termos)
    if not q:
        return []
    con = abrir(db)
    try:
        rs = con.execute(f"select {', '.join(COLUNAS)}, bm25(midias) from midias where midias match ? "
                         "order by bm25(midias) limit ?", (q, limite)).fetchall()
    except sqlite3.OperationalError:
        rs = []
    con.close()
    return [{**dict(zip(COLUNAS, r[:-1])), "score": -float(r[-1])} for r in rs]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonte")
    ap.add_argument("--buscar")
    a = ap.parse_args()
    if a.buscar:
        for r in buscar(a.buscar.split()):
            print(f"{r['score']:6.2f} {r['fonte']:<7} {r['tipo']:<6} {r['ini']:6.1f} {r['arquivo']}  | {r['texto'][:70]}")
        return
    for f, n in indexar(a.fonte).items():
        print(f"{f}: {n} entradas")


if __name__ == "__main__":
    main()
