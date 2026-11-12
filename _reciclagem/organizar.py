#!/usr/bin/env python3
"""Passo 2 — reorganiza a pasta bagunçada em uma pasta por post.

Destino (vídeos e imagens separados dentro de cada post):
    _posts/AAAA/AAAA-MM-DD_shortcode/
        imagens/01.webp  02.jpg  ...      (ordem original do carrossel)
        videos/01.mp4    ...
        post.json                          (json completo do scraper)
        legenda.md                         (legenda limpa + ficha do post)

Padrão é DRY-RUN: só mostra o plano. Para executar:

    python3 _reciclagem/organizar.py                 # simula
    python3 _reciclagem/organizar.py --aplicar       # move (registra em movimentos.csv)
    python3 _reciclagem/organizar.py --aplicar --copiar   # copia em vez de mover
    python3 _reciclagem/organizar.py --desfazer      # reverte usando movimentos.csv

Nada é apagado. Arquivos sem .json vão para _sem_metadata/.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bcnlib  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = bcnlib.BASE
DEST = os.path.join(BASE, "_posts")
LOG = os.path.join(AQUI, "movimentos.csv")
EXTS_VIDEO = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


def slug(texto: str, limite: int = 48) -> str:
    t = re.sub(r"[^a-zA-Z0-9]+", "-", (texto or "")).strip("-").lower()
    return t[:limite] or "post"


def _proximos(pasta: str) -> dict[str, int]:
    """Continua a numeração a partir do que já existe na pasta de destino —
    entrar com 01.webp num post que já tem 01.webp apagaria a imagem original."""
    cont = {"imagens": 0, "videos": 0}
    for tipo in cont:
        d = os.path.join(BASE, pasta, tipo)
        if os.path.isdir(d):
            cont[tipo] = len([n for n in os.listdir(d)
                              if os.path.splitext(n)[1].lower() in bcnlib.EXTS_MIDIA])
    return cont


def plano(midias: list[dict], orfaos: list[str], fundir: bool = False) -> list[tuple[str, str]]:
    """Devolve [(origem_rel, destino_rel)] pronto para mover.

    Por padrão as subpastas que você já organizou à mão ficam intactas.
    `fundir=True` (--fundir-pastas) traz essas também, desfazendo a curadoria:
    neste modo a numeração de cada post continua de onde a pasta parou, para não
    sobrescrever mídia de um post que existe nas duas estruturas.
    """
    midias = [m for m in midias if not m.get("organizado")]     # já estão no lugar
    if not fundir:
        midias = [m for m in midias if not m["pasta"]]
        orfaos = [o for o in orfaos if os.sep not in o]
    movs = []
    for p in bcnlib.agrupar_posts(midias):
        data = p["data"][:10] or "0000-00-00"
        pasta = os.path.join("_posts", data[:4],
                             f"{data}_{p['post_shortcode'] or p['post_id']}")
        contador = _proximos(pasta)
        for arq in p["midias"]:
            ext = os.path.splitext(arq)[1].lower()
            tipo = "videos" if ext in EXTS_VIDEO else "imagens"
            contador[tipo] += 1
            movs.append((arq, os.path.join(pasta, tipo, f"{contador[tipo]:02d}{ext}")))
        for i, arq in enumerate(p["midias"], 1):
            if i == 1 and not os.path.exists(os.path.join(BASE, pasta, "post.json")):
                alvo = "post.json"
            else:
                alvo = os.path.join("metadados", f"{i:02d}.json")
            movs.append((arq + ".json", os.path.join(pasta, alvo)))
        movs.append((f"__legenda__{p['post_id']}", os.path.join(pasta, "legenda.md")))
    for o in orfaos:
        ext = os.path.splitext(o)[1].lower()
        sub = "videos" if ext in EXTS_VIDEO else "imagens"
        movs.append((o, os.path.join("_sem_metadata", sub, os.path.basename(o))))
    return movs


def escrever_legenda(p: dict) -> str:
    linhas = [
        f"# {p['gancho'] or '(sem legenda)'}",
        "",
        f"- **post:** {p['url']}",
        f"- **data:** {p['data']}  ·  **tipo:** {p['tipo']}  ·  **pilar:** {p['pilar']}",
        f"- **curtidas:** {p['curtidas']}  ·  **midias:** {p['n_midias']} ({p['formatos']})",
        f"- **local:** {p['local'] or '—'}",
        f"- **tags:** {(p['tags'] or '—')}  ·  **coautores:** {(p['coautores'] or '—')}",
        "",
        "## Legenda original",
        "",
        p["legenda"].strip() or "_(vazia)_",
        "",
    ]
    return "\n".join(linhas)


def executar(movs, legendas: dict, aplicar: bool, copiar: bool) -> None:
    """legendas: {post_id: texto} montado ANTES de mover — depois do move a
    varredura não acha mais nada, porque _posts é ignorado pelo coletor."""
    reais = [m for m in movs if not m[0].startswith("__legenda__")]
    vi = [d for _, d in reais if f"{os.sep}videos{os.sep}" in d]
    im = [d for _, d in reais if f"{os.sep}imagens{os.sep}" in d]
    posts = {os.sep.join(d.split(os.sep)[2:3]) for d in vi + im}
    print(f"{len(reais)} arquivos em {len(posts)} pastas de post")
    print(f"  {len(im)} imagens em imagens/  ·  {len(vi)} videos em videos/"
          f"  + {len(reais) - len(im) - len(vi)} metadados")
    for origem, destino in movs[:12]:
        marca = "(md)" if origem.startswith("__legenda__") else ""
        print(f"  {origem}  ->  {destino} {marca}")
    if len(movs) > 12:
        print(f"  ... +{len(movs) - 12} operacoes")
    if not aplicar:
        print("\nDRY-RUN. Rode com --aplicar para executar.")
        return

    faltando = 0
    with open(LOG, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["origem", "destino"])
        for origem, destino in movs:
            if origem.startswith("__legenda__"):
                continue
            src = os.path.join(BASE, origem)
            dst = os.path.join(BASE, destino)
            if not os.path.exists(src):
                faltando += 1
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            (shutil.copy2 if copiar else shutil.move)(src, dst)
            w.writerow([origem, destino])

    n_md = 0
    for destino in [d for o, d in movs if o.startswith("__legenda__")]:
        texto = legendas.get(destino)
        if texto is None:
            continue
        caminho = os.path.join(BASE, destino)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        if os.path.exists(caminho):
            continue
        with open(caminho, "w", encoding="utf-8") as fh:
            fh.write(texto)
        n_md += 1
    if not copiar:
        print(f"pastas antigas vazias removidas: {limpar_vazias()}")
    print(f"\nOK. {len(reais)} arquivos movidos, {n_md} legendas escritas."
          + (f" {faltando} origens ausentes." if faltando else "")
          + f" Log: {LOG}")


def recolher_json(aplicar: bool) -> None:
    """Depois de mover as mídias, os .json que ficaram para trás (carrossel tem
    um json por mídia e só o primeiro vira post.json) são arquivados pelo post_id."""
    import json
    pendentes = []
    for nome in os.listdir(BASE):
        if not nome.endswith(".json"):
            continue
        cam = os.path.join(BASE, nome)
        try:
            with open(cam, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        data = (d.get("post_date") or d.get("date") or "")[:10]
        pid = str(d.get("post_id") or "")
        if not data or not pid:
            continue
        pasta = os.path.join("_posts", data[:4],
                             f"{data}_{d.get('post_shortcode') or pid}", "metadados")
        pendentes.append((nome, os.path.join(pasta, nome.replace(".json", ""))))
    print(f"{len(pendentes)} json soltos na raiz")
    if not pendentes:
        return
    if not aplicar:
        print("DRY-RUN. Use --recolher-json --aplicar")
        return
    with open(LOG, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        usados = set()
        for nome, destino in pendentes:
            base, ext = os.path.splitext(destino)
            n, alvo = 1, f"{base}.json"
            while alvo in usados or os.path.exists(os.path.join(BASE, alvo)):
                n += 1
                alvo = f"{base}-{n}.json"
            usados.add(alvo)
            os.makedirs(os.path.dirname(os.path.join(BASE, alvo)), exist_ok=True)
            shutil.move(os.path.join(BASE, nome), os.path.join(BASE, alvo))
            w.writerow([nome, alvo])
    print(f"{len(pendentes)} json arquivados em metadados/")


def limpar_vazias() -> int:
    """Remove as subpastas antigas que ficaram sem nada depois da fusão."""
    protegidas = {"_posts", "_reciclagem", "_sem_metadata"}
    removidas = 0
    for raiz, dirs, arquivos in os.walk(BASE, topdown=False):
        if os.path.abspath(raiz) == os.path.abspath(BASE):
            continue
        rel = os.path.relpath(raiz, BASE)
        if rel.split(os.sep)[0] in protegidas:
            continue
        if not os.listdir(raiz):
            os.rmdir(raiz)
            removidas += 1
    return removidas


def relatorio_pastas(midias: list[dict]) -> None:
    """Mapa das subpastas manuais: quantas mídias e qual pilar predominante."""
    from collections import Counter
    grupos: dict[str, list[dict]] = {}
    for m in midias:
        if m["pasta"]:
            grupos.setdefault(m["pasta"], []).append(m)
    linhas = [("pasta", "midias", "posts", "pilar_predominante", "MB")]
    for pasta, itens in sorted(grupos.items(), key=lambda kv: -len(kv[1])):
        pilar = Counter(m["pilar"] for m in itens).most_common(1)[0][0]
        mb = sum(m["bytes"] for m in itens) / 1e6
        linhas.append((pasta, str(len(itens)),
                       str(len({m["post_id"] for m in itens})), pilar, f"{mb:.0f}"))
    with open(os.path.join(AQUI, "pastas_manuais.csv"), "w", newline="",
              encoding="utf-8") as fh:
        csv.writer(fh).writerows(linhas)
    print(f"  mapa em pastas_manuais.csv ({len(grupos)} pastas)")


def desfazer() -> None:
    if not os.path.exists(LOG):
        print("sem movimentos.csv para reverter")
        return
    n = 0
    with open(LOG, encoding="utf-8") as fh:
        for linha in csv.DictReader(fh):
            dst = os.path.join(BASE, linha["destino"])
            src = os.path.join(BASE, linha["origem"])
            if os.path.exists(dst):
                os.makedirs(os.path.dirname(src), exist_ok=True)
                shutil.move(dst, src)
                n += 1
    print(f"{n} arquivos revertidos")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--copiar", action="store_true")
    ap.add_argument("--desfazer", action="store_true")
    ap.add_argument("--fundir-pastas", action="store_true",
                    help="inclui as subpastas manuais na reorganização (desfaz a curadoria)")
    ap.add_argument("--recolher-json", action="store_true",
                    help="arquiva .json órfãos da raiz junto do post (metadados/)")
    a = ap.parse_args()
    if a.desfazer:
        desfazer()
        return
    if a.recolher_json:
        recolher_json(a.aplicar)
        return
    midias, orfaos, quebrados = bcnlib.coletar(BASE)
    if quebrados:
        print(f"aviso: {len(quebrados)} json sem midia (ignorados)")

    manuais = [m for m in midias if m["pasta"]]
    if manuais and not a.fundir_pastas:
        pastas = {m["pasta"] for m in manuais}
        print(f"preservadas: {len(manuais)} midias em {len(pastas)} subpastas que voce organizou")
        print("  (use --fundir-pastas para incluir essas tambem)")
        relatorio_pastas(midias)

    recorte = [m for m in midias if not m.get("organizado")]
    if not a.fundir_pastas:
        recorte = [m for m in recorte if not m["pasta"]]
    movs = plano(midias, orfaos, a.fundir_pastas)
    legendas = {}
    for p in bcnlib.agrupar_posts(recorte):
        data = p["data"][:10] or "0000-00-00"
        destino = os.path.join("_posts", data[:4],
                              f"{data}_{p['post_shortcode'] or p['post_id']}", "legenda.md")
        legendas[destino] = escrever_legenda(p)
    executar(movs, legendas, a.aplicar, a.copiar)


if __name__ == "__main__":
    main()
