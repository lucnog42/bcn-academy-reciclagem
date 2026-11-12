#!/usr/bin/env python3
"""Passo 1 — indexa a pasta inteira em catalogo.csv + catalogo.sqlite.

Uso:
    python3 src/acervo/catalogo.py            # gera/atualiza catalogo
    sqlite3 dados/marcas/<marca>/indice/catalogo.sqlite "select pilar,count(*) from posts group by 1"
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import csv
import os
import sqlite3
import sys
from acervo import colecao  # noqa: E402

from nucleo import caminhos  # noqa: E402
AQUI = caminhos.dados("indice")
BASE = colecao.BASE

COLS_MIDIA = ["arquivo", "pasta", "ext", "bytes", "post_id", "post_shortcode",
              "media_shortcode", "url", "tipo", "num", "total_midias", "data", "ano",
              "curtidas", "pilar", "confianca", "pilar_secundario", "evidencias",
              "resgatado_por", "fala", "formato",
              "local", "local_slug", "dono", "audio", "w", "h", "hashtags", "tags",
              "coautores", "fixado", "gancho", "legenda"]
COLS_POST = ["post_id", "post_shortcode", "url", "tipo", "data", "ano", "curtidas",
             "n_midias", "formatos", "exts", "tem_video", "tem_imagem", "pilar",
             "confianca", "pilar_secundario", "pilares", "repetido", "melhor_do_grupo",
             "pastas", "tem_fala", "fala", "local", "local_slug", "dono", "bytes", "hashtags", "tags",
             "coautores", "fixado", "gancho", "legenda", "midias"]


def main() -> None:
    midias, orfaos, quebrados = colecao.coletar(BASE)
    posts = colecao.marcar_repetidos(colecao.agrupar_posts(midias))

    csv_m = os.path.join(AQUI, "catalogo.csv")
    with open(csv_m, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS_MIDIA, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(midias, key=lambda m: m["data"]))

    csv_p = os.path.join(AQUI, "posts.csv")
    with open(csv_p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS_POST, extrasaction="ignore")
        w.writeheader()
        for p in posts:
            linha = dict(p)
            linha["midias"] = " | ".join(p["midias"])
            w.writerow(linha)

    db = os.path.join(AQUI, "catalogo.sqlite")
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    tipos = {"arquivo": "TEXT", "pasta": "TEXT", "ext": "TEXT", "bytes": "INTEGER",
             "post_id": "TEXT", "post_shortcode": "TEXT", "media_shortcode": "TEXT",
             "url": "TEXT", "tipo": "TEXT", "num": "INTEGER", "total_midias": "INTEGER",
             "data": "TEXT", "ano": "TEXT", "curtidas": "INTEGER", "pilar": "TEXT",
             "confianca": "REAL", "pilar_secundario": "TEXT", "evidencias": "TEXT",
             "resgatado_por": "TEXT", "fala": "TEXT",
             "formato": "TEXT", "local": "TEXT", "local_slug": "TEXT", "dono": "TEXT",
             "audio": "TEXT", "w": "INTEGER", "h": "INTEGER", "hashtags": "TEXT",
             "tags": "TEXT", "coautores": "TEXT", "fixado": "INTEGER", "gancho": "TEXT",
             "legenda": "TEXT"}
    con.execute("CREATE TABLE midias (%s)" % ", ".join(f'"{c}" {tipos[c]}' for c in COLS_MIDIA))
    con.executemany('INSERT INTO midias VALUES (%s)' % ",".join("?" * len(COLS_MIDIA)),
                    [[m.get(c) for c in COLS_MIDIA] for m in midias])
    tipos_p = {"n_midias": "INTEGER", "tem_video": "INTEGER", "tem_imagem": "INTEGER",
               "bytes": "INTEGER", "fixado": "INTEGER", "curtidas": "INTEGER", "midias": "TEXT",
               "repetido": "INTEGER", "melhor_do_grupo": "INTEGER", "tem_fala": "INTEGER",
               "fala": "TEXT"}
    con.execute("CREATE TABLE posts (%s)" % ", ".join(
        f'"{c}" {tipos_p.get(c, tipos.get(c, "TEXT"))}' for c in COLS_POST))
    for p in posts:
        linha = dict(p)
        linha["midias"] = " | ".join(p["midias"])
        con.execute('INSERT INTO posts VALUES (%s)' % ",".join("?" * len(COLS_POST)),
                    [linha.get(c) for c in COLS_POST])
    con.executescript("""
        CREATE VIRTUAL TABLE falas USING fts5(
            texto, arquivo UNINDEXED, post_id UNINDEXED, post_shortcode UNINDEXED,
            pilar UNINDEXED, data UNINDEXED, pilar_rotulo UNINDEXED, tokenize='unicode61');
    """)
    con.executemany("INSERT INTO falas VALUES (?,?,?,?,?,?,?)",
                    [[m["transcricao"], m["arquivo"], m["post_id"], m["post_shortcode"],
                      m["pilar"], m["data"][:10], ""] for m in midias if m.get("transcricao")])
    con.execute("CREATE INDEX ix_m_pilar ON midias(pilar)")
    con.execute("CREATE INDEX ix_m_ano ON midias(ano)")
    con.execute("CREATE INDEX ix_p_pilar ON posts(pilar)")
    con.commit()
    con.close()

    # listas prontas para lote: abrir no ffmpeg / importar no editor
    for nome, pred in (("videos.csv", lambda m: m["ext"] in ("mp4", "mov", "m4v", "webm")),
                       ("imagens.csv", lambda m: m["ext"] in ("jpg", "jpeg", "webp", "png"))):
        itens = [m for m in midias if pred(m)]
        with open(os.path.join(AQUI, nome), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["caminho_absoluto", "relativo", "pilar", "post_shortcode",
                        "data", "curtidas", "formato", "MB"])
            for m in sorted(itens, key=lambda x: x["data"]):
                w.writerow([os.path.join(BASE, m["arquivo"]), m["arquivo"], m["pilar"],
                            m["post_shortcode"], m["data"][:10], m["curtidas"],
                            m["formato"], round(m["bytes"] / 1e6, 1)])

    # ---- cortes (material bruto para edição) ----
    cortes = colecao.coletar_cortes(base=BASE)
    if cortes:
        with open(os.path.join(AQUI, "cortes.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["arquivo", "tema", "pilar", "segundos",
                                               "bytes", "tem_srt", "gancho", "fala"])
            w.writeheader()
            w.writerows(cortes)
        con = sqlite3.connect(db)
        con.execute("drop table if exists cortes")
        con.execute("""CREATE TABLE cortes (arquivo TEXT, tema TEXT, pilar TEXT,
                       segundos REAL, bytes INTEGER, tem_srt INTEGER, gancho TEXT, fala TEXT)""")
        con.executemany("INSERT INTO cortes VALUES (?,?,?,?,?,?,?,?)",
                        [[c_[kk] for kk in ("arquivo", "tema", "pilar", "segundos",
                                            "bytes", "tem_srt", "gancho", "fala")]
                         for c_ in cortes])
        con.commit()
        con.close()

    rel = os.path.join(AQUI, "relatorio_indexacao.txt")
    with open(rel, "w", encoding="utf-8") as fh:
        fh.write(colecao.resumo(midias, orfaos, quebrados) + "\n")
        if orfaos:
            fh.write("\norfaos (sem json):\n" + "\n".join("  " + o for o in orfaos[:50]) + "\n")
        if quebrados:
            fh.write("\nquebrados:\n" + "\n".join(f"  {q['json']} — {q['motivo']}" for q in quebrados) + "\n")

    print(colecao.resumo(midias, orfaos, quebrados))
    print(f"\ncatalogo.csv  ({len(midias)} linhas)")
    print(f"posts.csv     ({len(posts)} linhas)")
    print("catalogo.sqlite (falas + cortes) · videos.csv · imagens.csv · cortes.csv")


if __name__ == "__main__":
    main()
