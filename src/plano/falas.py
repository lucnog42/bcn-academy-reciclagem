#!/usr/bin/env python3
"""Banco de falas do cliente: cada frase já gravada e transcrita, com o vídeo e o tempo exato.

É a matéria-prima dos roteiros: posts com vídeo, pastas de cortes e as fontes importadas do tipo
"falas". As frases saem do words.json (tempo por palavra): uma frase termina numa pausa longa,
num ponto final ou quando passa de 12 s. Ficam num SQLite FTS em dados/marcas/<marca>/indice/.

    python3 src/plano/falas.py                     # refaz o banco
    python3 src/plano/falas.py --buscar "bolsa de estudos"
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import hashlib
import os
import random
import sqlite3
import time

from nucleo import caminhos, config  # noqa: E402

PAUSA = 0.7        # s de silêncio que fecha a frase
MINIMO = 1.2       # s: frase mais curta que isso cola na seguinte
MAXIMO = 12.0      # s: frase mais longa que isso é quebrada
COLUNAS = ("id", "texto", "video", "ini", "fim", "item", "fonte", "pilar", "data")


def caminho_db() -> str:
    return caminhos.dados("indice", "falas.sqlite")


def abrir(db: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(db or caminho_db())
    con.execute("create virtual table if not exists frases using fts5(id unindexed, texto, video unindexed, "
                "ini unindexed, fim unindexed, item unindexed, fonte unindexed, pilar unindexed, data unindexed, "
                "tokenize = 'unicode61 remove_diacritics 2')")
    con.execute("create table if not exists meta (k text primary key, v text)")
    return con


def frases_de(palavras: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Agrupa palavras em frases pelo silêncio, pela pontuação e pelo tamanho."""
    out: list[list] = []
    atual: list = []
    for i, (a, b, t) in enumerate(palavras):
        if atual and (a - atual[-1][1] >= PAUSA or b - atual[0][0] > MAXIMO):
            out.append(atual)
            atual = []
        atual.append((a, b, t))
        fim_de_frase = t.rstrip().endswith((".", "!", "?", "…"))
        if fim_de_frase and atual[-1][1] - atual[0][0] >= MINIMO:
            out.append(atual)
            atual = []
    if atual:
        out.append(atual)
    # frase curta demais cola na seguinte (ou na anterior, se for a última)
    juntas: list[list] = []
    for f in out:
        if juntas and juntas[-1][-1][1] - juntas[-1][0][0] < MINIMO and f[0][0] - juntas[-1][-1][1] < 1.5:
            juntas[-1] = juntas[-1] + f
        else:
            juntas.append(f)
    return [(round(f[0][0], 2), round(f[-1][1], 2), " ".join(w[2].strip() for w in f).strip()) for f in juntas if f]


def _videos() -> list[dict]:
    """Os vídeos com fala do cliente: posts, cortes e fontes importadas do tipo falas."""
    from acervo import fontes, listas
    out = []
    # o material bruto primeiro (cortes, fontes): o post publicado costuma repetir a mesma fala, e
    # a frase fica com quem tem o vídeo inteiro
    posts = []
    for p in listas.montar_dados(limite_fala=10, limite_legenda=10):
        for m in p.get("midias") or []:
            if os.path.splitext(m)[1].lower() in fontes.VIDEO:
                posts.append({"video": m, "item": p["pasta"], "fonte": "posts", "pilar": p.get("pilar", ""),
                              "data": p.get("data", "")})
    for c in listas.montar_cortes(limite_fala=10):
        for v in c.get("videos") or []:
            out.append({"video": v, "item": c["arquivo"], "fonte": "cortes", "pilar": c.get("pilar", ""), "data": ""})
    for f in config.carregar().get("fontes") or []:
        if f.get("tipo") == "falas" and f.get("ativo", True):
            for arq, tipo in fontes.arquivos(f):
                if tipo == "video":
                    out.append({"video": arq, "item": f["id"] + ":" + os.path.relpath(os.path.dirname(arq), f["raiz"]),
                                "fonte": f["id"], "pilar": "", "data": ""})
    return out + posts


def indexar(db: str | None = None) -> int:
    from plano import momentos
    import re
    import unicodedata

    def chave(t: str) -> str:
        t = unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]+", " ", t).strip()
    linhas, vistas = [], set()
    for v in _videos():
        try:
            ws = momentos._palavras(v["video"])
        except Exception:
            ws = []
        for a, b, t in frases_de(ws):
            if len(t.split()) < 2 or chave(t) in vistas:
                continue
            vistas.add(chave(t))
            fid = hashlib.sha1(f"{v['video']}|{a:.2f}".encode()).hexdigest()[:10]
            linhas.append((fid, t, v["video"], a, b, v["item"], v["fonte"], v["pilar"], v["data"]))
    con = abrir(db)
    con.execute("delete from frases")
    con.executemany(f"insert into frases ({', '.join(COLUNAS)}) values ({', '.join('?' * len(COLUNAS))})", linhas)
    con.execute("insert or replace into meta values ('quando', ?)", (str(time.time()),))
    con.commit()
    con.close()
    return len(linhas)


def garantir(db: str | None = None, idade: float = 12 * 3600) -> None:
    """Refaz o banco se ele não existe ou tem mais de 12 h."""
    if os.path.exists(db or caminho_db()):
        con = abrir(db)
        r = con.execute("select v from meta where k = 'quando'").fetchone()
        n = con.execute("select count(*) from frases").fetchone()[0]
        con.close()
        if r and n and time.time() - float(r[0]) < idade:
            return
    indexar(db)


def _linha(r) -> dict:
    d = dict(zip(COLUNAS, r))
    d["ini"], d["fim"] = float(d["ini"]), float(d["fim"])
    return d


def buscar(termos: list[str], limite: int = 60, por_item: int = 6, db: str | None = None) -> list[dict]:
    from achar import indice
    q = indice.consulta_fts(termos)
    if not q:
        return []
    con = abrir(db)
    try:
        rs = con.execute(f"select {', '.join(COLUNAS)} from frases where frases match ? order by bm25(frases) limit ?",
                         (q, limite * 4)).fetchall()
    except sqlite3.OperationalError:
        rs = []
    con.close()
    out, cont = [], {}
    for r in rs:
        d = _linha(r)
        if cont.get(d["item"], 0) >= por_item:
            continue
        cont[d["item"]] = cont.get(d["item"], 0) + 1
        out.append(d)
        if len(out) >= limite:
            break
    return out


def por_ids(ids: list[str], db: str | None = None) -> dict[str, dict]:
    if not ids:
        return {}
    con = abrir(db)
    rs = con.execute(f"select {', '.join(COLUNAS)} from frases where id in ({', '.join('?' * len(ids))})", ids).fetchall()
    con.close()
    return {r[0]: _linha(r) for r in rs}


def vizinhas(f: dict, n: int = 2, db: str | None = None) -> list[dict]:
    """As frases ao redor de uma (mesmo vídeo), em ordem: o contexto de onde ela foi tirada."""
    con = abrir(db)
    rs = con.execute(f"select {', '.join(COLUNAS)} from frases where video = ?", (f["video"],)).fetchall()
    con.close()
    todas = sorted((_linha(r) for r in rs), key=lambda x: x["ini"])
    i = next((k for k, x in enumerate(todas) if x["id"] == f["id"]), 0)
    return todas[max(0, i - n): i + n + 1]


def amostra(n: int = 120, semente: int | None = None, db: str | None = None) -> list[dict]:
    """Frases variadas do banco inteiro (no máximo 4 por item), para a IA ter uma visão do que existe."""
    con = abrir(db)
    rs = [_linha(r) for r in con.execute(f"select {', '.join(COLUNAS)} from frases").fetchall()]
    con.close()
    rnd = random.Random(semente if semente is not None else int(time.time() // 3600))
    rnd.shuffle(rs)
    rs.sort(key=lambda d: -len(d["texto"].split()))           # as mais completas primeiro
    out, cont = [], {}
    for d in rs:
        if cont.get(d["item"], 0) >= 4 or len(d["texto"].split()) < 6:
            continue
        cont[d["item"]] = cont.get(d["item"], 0) + 1
        out.append(d)
        if len(out) >= n:
            break
    return out


def total(db: str | None = None) -> dict:
    if not os.path.exists(db or caminho_db()):
        return {"frases": 0, "videos": 0, "itens": 0}
    con = abrir(db)
    f, v, i = con.execute("select count(*), count(distinct video), count(distinct item) from frases").fetchone()
    con.close()
    return {"frases": f, "videos": v, "itens": i}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--buscar")
    a = ap.parse_args()
    if a.buscar:
        garantir()
        for f in buscar(a.buscar.split(), 20):
            print(f"{f['id']}  {f['ini']:6.1f}–{f['fim']:<6.1f} {f['item'][:40]:<40} {f['texto'][:80]}")
        return
    print(f"{indexar()} frases")


if __name__ == "__main__":
    main()
