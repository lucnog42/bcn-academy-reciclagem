#!/usr/bin/env python3
"""Passo 4 — renomeia as pastas de post para um nome legível, mantendo a data.

    _posts/2023/2023-04-07_CquvCOyNryd/   ->   2023-04-07_partidas-do-time-na-copa-regional

Formato: AAAA-MM-DD_PILAR_nome-legivel. O nome sai da legenda (1ª linha útil),
sem hashtag, sem @menção, sem emoji. Se a legenda não disser nada (vazia ou só
hashtag), o nome vira "sem-legenda".

    python3 src/acervo/renomear.py                    # simula (mostra 20 exemplos)
    python3 src/acervo/renomear.py --aplicar          # renomeia
    python3 src/acervo/renomear.py --desfazer         # volta pelos renomeacoes.csv

Ao renomear, as linhas de `movimentos.csv` são reescritas junto — senão o histórico
das pastas antigas (usado na classificação) apontaria para caminho inexistente.
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import csv
import os
import re
import sys
import unicodedata
from collections import defaultdict
from acervo import colecao  # noqa: E402

from nucleo import caminhos  # noqa: E402
AQUI = caminhos.dados("historico")
BASE = colecao.BASE
LOG_MOV = os.path.join(AQUI, "movimentos.csv")
LOG_REN = os.path.join(AQUI, "renomeacoes.csv")
LIMITE = 56          # caracteres do nome legível, sem contar a data
MANTER = str.maketrans({"–": "-", "—": "-", "|": "-", "•": "-"})


def limpar_linha(linha: str) -> str:
    """Tira hashtag, @menção, link, emoji e pontuação de enfeite."""
    t = re.sub(r"https?://\S+", " ", linha)
    t = re.sub(r"#\w+", " ", t)
    t = re.sub(r"@[\w.]+", " ", t)
    t = t.translate(MANTER)
    saida = []
    for ch in t:
        cat = unicodedata.category(ch)
        if cat.startswith("L") or ch.isdigit() or ch in " -'":
            saida.append(ch)
        elif cat.startswith("M"):       # acento solto de emoji composto
            continue
        else:
            saida.append(" ")
    t = re.sub(r"\s+", " ", "".join(saida)).strip(" -'")
    return t


PARADAS = {"de", "da", "do", "das", "dos", "na", "no", "nas", "nos", "em", "com",
           "para", "pra", "por", "e", "ou", "a", "o", "as", "os", "um", "uma",
           "que", "é", "foi", "ao", "aos", "seu", "sua", "seus", "suas",
           "nosso", "nossa", "nossos", "nossas", "mais", "recém", "pré", "pós",
           "vice", "meio", "além", "até", "sobre", "entre", "sem", "sob", "hoje",
           "ontem", "agora", "aqui"}


def cortar(texto: str, limite: int = LIMITE) -> str:
    """Corta no fim de frase ou de palavra, sem deixar 'de/da/com' pendurado."""
    if len(texto) <= limite:
        return texto
    trecho = texto[:limite]
    for marca in (". ", "! ", "? ", " - ", ": ", ", "):
        pos = trecho.rfind(marca)
        if pos >= 20:
            trecho = trecho[:pos]
            break
    else:
        if " " in trecho:
            trecho = trecho[:trecho.rfind(" ")]
    palavras = trecho.split()
    while len(palavras) > 3 and palavras[-1].lower() in PARADAS:
        palavras.pop()
    return " ".join(palavras)


def nome_legivel(p: dict) -> str:
    for linha in (p["legenda"] or "").splitlines():
        limpa = limpar_linha(linha)
        letras = sum(1 for c in limpa if c.isalpha())
        if letras >= 3 and len(limpa) >= 6:
            break
    else:
        limpa = ""
    if not limpa:
        limpa = "sem-legenda"      # o pilar já vem antes do nome
    limpa = cortar(limpa)
    return re.sub(r"-{2,}", "-", limpa.lower().replace(" ", "-")).strip("-")


def plano(midias, ) -> list[tuple[str, str]]:
    """[(pasta_atual_rel, pasta_nova_rel)] para cada post organizado."""
    movs = []
    vistos: dict[str, int] = defaultdict(int)
    for p in colecao.agrupar_posts([m for m in midias if m.get("organizado")]):
        arq = p["midias"][0]
        partes = arq.split(os.sep)
        if "imagens" not in partes and "videos" not in partes:
            continue
        atual = os.sep.join(partes[:-2])            # _posts/AAAA/<pasta>
        data = os.path.basename(atual)[:10]
        pai = os.path.dirname(atual)
        novo_nome = f"{data}_{p['pilar']}_{nome_legivel(p)}"
        chave = os.path.join(pai, novo_nome)
        vistos[chave] += 1
        if vistos[chave] > 1:
            novo_nome = f"{novo_nome}-{vistos[chave]}"
        novo = os.path.join(pai, novo_nome)
        if novo != atual:
            movs.append((atual, novo))
    return movs


def aplicar(movs: list[tuple[str, str]]) -> None:
    novo_arquivo = not os.path.exists(LOG_REN)
    with open(LOG_REN, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if novo_arquivo:
            w.writerow(["antigo", "novo"])
        for antigo, novo in movs:
            os.rename(os.path.join(BASE, antigo), os.path.join(BASE, novo))
            w.writerow([antigo, novo])

    # move o mesmo prefixo no log de movimentos, para o histórico não quebrar
    if os.path.exists(LOG_MOV):
        mapa = {a + os.sep: n + os.sep for a, n in movs}
        with open(LOG_MOV, encoding="utf-8") as fh:
            linhas = list(csv.DictReader(fh))
        trocas = 0
        for linha in linhas:
            d = linha["destino"]
            for a, n in mapa.items():
                if d.startswith(a):
                    linha["destino"] = n + d[len(a):]
                    trocas += 1
                    break
        with open(LOG_MOV, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["origem", "destino"])
            w.writeheader()
            w.writerows(linhas)
        print(f"movimentos.csv: {trocas} destinos atualizados")


def desfazer() -> None:
    """Volta ao padrão AAAA-MM-DD_shortcode. Recomputa do post.json, então
    funciona mesmo com várias passadas de renomeação no histórico."""
    n = 0
    for ano in sorted(os.listdir(os.path.join(BASE, "_posts"))):
        dir_ano = os.path.join(BASE, "_posts", ano)
        if not os.path.isdir(dir_ano):
            continue
        for nome in os.listdir(dir_ano):
            cam = os.path.join(dir_ano, nome)
            meta = colecao.ler_json(os.path.join(cam, "post.json"))
            if not meta:
                continue
            data = (meta.get("post_date") or meta.get("date") or "")[:10]
            alvo = f"{data}_{meta.get('post_shortcode') or meta.get('post_id')}"
            if alvo != nome and not os.path.exists(os.path.join(dir_ano, alvo)):
                os.rename(cam, os.path.join(dir_ano, alvo))
                n += 1
    print(f"{n} pastas revertidas para AAAA-MM-DD_shortcode")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--desfazer", action="store_true")
    ap.add_argument("--exemplos", type=int, default=20)
    a = ap.parse_args()
    if a.desfazer:
        desfazer()
        return

    midias, _, _ = colecao.coletar(BASE)
    movs = plano(midias)
    print(f"{len(movs)} pastas a renomear de {len({m['post_id'] for m in midias if m.get('organizado')})} posts")
    for antigo, novo in movs[:a.exemplos]:
        print(f"  {os.path.basename(antigo)}")
        print(f"    -> {os.path.basename(novo)}")
    if len(movs) > a.exemplos:
        print(f"  ... +{len(movs) - a.exemplos}")
    if not a.aplicar:
        print("\nDRY-RUN. Use --aplicar.")
        return
    aplicar(movs)
    print(f"\nOK. {len(movs)} pastas renomeadas. Log: {LOG_REN}")


if __name__ == "__main__":
    main()
