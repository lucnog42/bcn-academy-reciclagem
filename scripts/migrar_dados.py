#!/usr/bin/env python3
"""Traz o estado do layout antigo (`<acervo>/_reciclagem/` e `<acervo>/_motion/`) para
`dados/marcas/<marca>/`. Só COPIA: nada no acervo é apagado nem alterado, e nada que já exista
em dados/ é sobrescrito. Sem --aplicar, só mostra o que faria.

    python3 scripts/migrar_dados.py                      # marca ativa, acervo da config
    python3 scripts/migrar_dados.py --marca bcn --antigo ~/arquivo/BCN/bcn_academy/_reciclagem
    python3 scripts/migrar_dados.py --aplicar

As referências gravadas nos momentos (imagens em `<item>/motion/`) continuam valendo, porque os
arquivos originais ficam onde estão. A chave da IA (`config.local.toml` antigo) vai para
`config/local.toml` só se ele ainda não existir; o `.venv-asr` não é copiado (recrie ou mova à mão).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))


def planejar(antigo: str, acervo: str, dados: str, raiz: str) -> list[tuple[str, str]]:
    """(origem, destino) de cada arquivo a copiar."""
    pares: list[tuple[str, str]] = []

    def arq(o: str, *d: str) -> None:
        if os.path.isfile(o):
            pares.append((o, os.path.join(dados, *d)))

    def pasta(o: str, *d: str) -> None:
        if not os.path.isdir(o):
            return
        for r, _, arqs in os.walk(o):
            for a in arqs:
                f = os.path.join(r, a)
                pares.append((f, os.path.join(dados, *d, os.path.relpath(f, o))))

    arq(os.path.join(antigo, "estados.json"), "marcacoes", "estados.json")
    for n in ("movimentos.csv", "renomeacoes.csv"):
        arq(os.path.join(antigo, n), "historico", n)
    pasta(os.path.join(antigo, "projetos_antigos"), "historico", "projetos_antigos")
    for n in ("catalogo.csv", "catalogo.sqlite", "videos.csv", "imagens.csv", "cortes.csv"):
        arq(os.path.join(antigo, n), "indice", n)
    arq(os.path.join(antigo, "projetos.csv"), "fila", "projetos.csv")
    arq(os.path.join(antigo, "srt_fila.csv"), "transcricao", "srt_fila.csv")
    pasta(os.path.join(antigo, "srt_antigo"), "transcricao", "srt_antigo")
    arq(os.path.join(antigo, "plano_reciclagem.csv"), "reciclagem", "plano_reciclagem.csv")
    arq(os.path.join(antigo, "PLANO.md"), "reciclagem", "PLANO.md")
    pasta(os.path.join(antigo, "rascunhos"), "reciclagem", "rascunhos")
    # a fila do motion e os filmes prontos (antes em <acervo>/_motion/)
    velho_motion = os.path.join(acervo, "_motion")
    for n in ("fila.json",):
        arq(os.path.join(velho_motion, n), "motion", n)
    pasta(os.path.join(velho_motion, "prontos"), "motion", "prontos")
    pasta(os.path.join(velho_motion, "quadros"), "motion", "quadros")
    # o trabalho de motion de cada item (antes em <item>/motion/)
    for r, dirs, _ in os.walk(acervo):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_reciclagem", "_motion"))]
        if os.path.basename(r) == "motion" and os.path.exists(os.path.join(r, "sugestoes.json")):
            item = os.path.relpath(os.path.dirname(r), acervo)
            chave = item.replace(os.sep, "__").strip("_.") or "raiz"
            pasta(r, "motion", "itens", chave)
            dirs[:] = []
    # a chave da IA: só se ainda não houver config/local.toml
    local = os.path.join(raiz, "config", "local.toml")
    velho = os.path.join(antigo, "config.local.toml")
    if os.path.isfile(velho) and not os.path.exists(local):
        pares.append((velho, local))
    return pares


def _vazio(d: str) -> bool:
    """Um arquivo que o app criou vazio antes da migração ({} ou []) pode ser trocado."""
    try:
        with open(d, encoding="utf-8") as fh:
            return os.path.getsize(d) < 16 and fh.read().strip() in ("", "{}", "[]")
    except (OSError, UnicodeDecodeError):
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--marca")
    ap.add_argument("--antigo", help="pasta _reciclagem antiga (padrão: <acervo>/_reciclagem)")
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    if a.marca:
        os.environ["NG3_MARCA"] = a.marca
    from nucleo import caminhos
    acervo = caminhos.acervo()
    antigo = os.path.expanduser(a.antigo or os.path.join(acervo, "_reciclagem"))
    dados = caminhos.dados()
    pares = planejar(antigo, acervo, dados, caminhos.raiz())
    novos = [(o, d) for o, d in pares if not os.path.exists(d) or _vazio(d)]
    print(f"marca {caminhos.marca()} · acervo {acervo}\nde {antigo}\npara {dados}\n")
    for o, d in novos:
        print(f"  {os.path.relpath(o, acervo) if o.startswith(acervo) else o}  ->  {os.path.relpath(d, caminhos.raiz())}")
    print(f"\n{len(novos)} arquivo(s) a copiar, {len(pares) - len(novos)} já existiam (ficam como estão)")
    if not a.aplicar:
        print("nada copiado: rode com --aplicar")
        return
    for o, d in novos:
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(o, d)
        if d.endswith("local.toml"):
            os.chmod(d, 0o600)
    print("copiado. Os originais continuam no acervo.")


if __name__ == "__main__":
    main()
