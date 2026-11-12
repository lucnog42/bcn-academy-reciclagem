#!/usr/bin/env python3
"""Busca no que é FALADO nos vídeos (transcrições), não só na legenda.

    python3 src/acervo/buscar.py "visto"            # trecho falado
    python3 src/acervo/buscar.py "bolsa de estudos" --pilar <PILAR>
    python3 src/acervo/buscar.py gol --desde 2024 --n 20
    python3 src/acervo/buscar.py --pasta            # lista as pastas com fala

Usa a tabela FTS5 `falas` de catalogo.sqlite (gerada por catalogo.py).
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import os
import sqlite3
import sys

from nucleo import caminhos  # noqa: E402
DB = caminhos.dados("indice", "catalogo.sqlite")


def destacar(texto: str, termos: list[str], largura: int = 220) -> str:
    baixo = texto.lower()
    pos = min((baixo.find(t) for t in termos if t in baixo), default=0)
    ini = max(0, pos - 70)
    trecho = texto[ini:ini + largura].strip()
    return ("…" if ini else "") + trecho + ("…" if ini + largura < len(texto) else "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("termo", nargs="?", help="palavra ou expressão (aceita OR, aspas)")
    ap.add_argument("--pilar")
    ap.add_argument("--desde", type=int)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--pasta", action="store_true", help="lista pastas que têm fala")
    a = ap.parse_args()

    if not os.path.exists(DB):
        sys.exit("rode catalogo.py primeiro")
    con = sqlite3.connect(DB)

    if a.pasta:
        for pasta, n, pilar in con.execute("""
                select substr(arquivo, 1, length(arquivo) - length('videos/01.mp4')) as p,
                       count(*), pilar from falas group by p order by 2 desc limit 40"""):
            print(f"{n:>3}x  {pilar:<12} {pasta}")
        return

    if not a.termo:
        sys.exit("informe um termo (ou use --pasta)")

    sql = """select pilar, data, post_shortcode, arquivo, texto from falas
             where falas match ?"""
    params: list = [a.termo]
    if a.pilar:
        sql += " and pilar = ?"
        params.append(a.pilar.upper())
    if a.desde:
        sql += " and data >= ?"
        params.append(f"{a.desde}-01-01")
    sql += " order by data desc limit ?"
    params.append(a.n)

    try:
        linhas = con.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        sys.exit(f"consulta inválida: {e}\n(dica: para frase use \"aspas\" ou termo OR termo)")
    if not linhas:
        print("nada falado com esse termo")
        return
    termos = [t.strip('"').lower() for t in a.termo.split()]
    for pilar, data, short, arquivo, texto in linhas:
        print(f"\n{data}  [{pilar}]  {short}")
        print(f"  {destacar(texto, termos)}")
        print(f"  {os.path.dirname(arquivo)}")
    print(f"\n{len(linhas)} resultado(s)")


if __name__ == "__main__":
    main()
