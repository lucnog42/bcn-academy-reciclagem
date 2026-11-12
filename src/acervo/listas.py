#!/usr/bin/env python3
"""As listas que o painel mostra: posts (com pilar, score e mídias) e pastas de cortes."""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import datetime as dt
import os

from acervo import colecao  # noqa: E402

BASE = colecao.BASE
TAMANHOS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350),
            "16:9": (1920, 1080)}
EXTS_VIDEO = ("mp4", "mov", "m4v")


def montar_dados(limite_fala: int = 260, limite_legenda: int = 400) -> list[dict]:
    midias, _, _ = colecao.coletar(BASE)
    org = [m for m in midias if m.get("organizado")]
    posts = colecao.marcar_repetidos(colecao.agrupar_posts(org))
    colecao.pontuar(posts, dt.date.today())
    por_post = {p["post_id"]: p for p in posts}
    itens_por_post: dict[str, list[dict]] = {}
    for m in org:
        itens_por_post.setdefault(m["post_id"], []).append(m)

    dados = []
    for pid, p in por_post.items():
        itens = sorted(itens_por_post[pid],
                       key=lambda m: (0 if "imagens" in m["arquivo"] else 1, m["num"]))
        pasta = os.sep.join(itens[0]["arquivo"].split(os.sep)[:-2])
        nome = os.path.basename(pasta)
        videos = [m for m in itens if m["ext"] in EXTS_VIDEO]
        imagens = [m for m in itens if m["ext"] not in EXTS_VIDEO]
        fmt = itens[0]["formato"] if itens[0]["formato"] in TAMANHOS else ""
        larg, alt = TAMANHOS.get(fmt, (1080, 1080))
        alvo = os.path.join(BASE, pasta, f"{nome}.{'fcproj' if videos else 'pcraft'}")
        capa = (imagens or videos)[0]
        dados.append({
            "id": pid,
            "pasta": pasta.replace(os.sep, "/"),
            "nome": nome,
            "data": p["data"][:10],
            "ano": p["data"][:4],
            "pilar": p["pilar"],
            "conf": p["confianca"],
            "curtidas": p["curtidas"],
            "score": p["score"],
            "partes": p["score_partes"],
            "percentil": p["percentil"],
            "idade": p["idade_dias"],
            "repetido": p.get("repetido", 1),
            "tipo": "fcproj" if videos else "pcraft",
            "seq": f"{larg}×{alt}",
            "n_video": len(videos),
            "n_img": len(imagens),
            "midias": [m["arquivo"].replace(os.sep, "/") for m in imagens + videos],
            "thumb": (imagens[0]["arquivo"].replace(os.sep, "/") if imagens else ""),
            "url": p["url"],
            "w": int(capa.get("w") or 0), "h": int(capa.get("h") or 0),
            "gancho": (p["legenda"] or "").strip()[:limite_legenda],
            "fala": (p["fala"] or "")[:limite_fala],
            "projeto": os.path.exists(alvo),
            "arquivo_projeto": os.path.relpath(alvo, BASE).replace(os.sep, "/") if os.path.exists(alvo) else "",
            "peso": round(len(imagens) * 3.2 + len(videos) * 0.01, 1),
            "mb": round(sum(m["bytes"] for m in itens) / 1e6, 1),
        })
    dados.sort(key=lambda d: d["data"], reverse=True)
    return dados


def _proporcao(caminho_abs: str) -> tuple[int, int]:
    """Largura e altura como o vídeo aparece (com a rotação do celular aplicada)."""
    try:
        from acervo import midia
        i = midia.info(caminho_abs)
        return int(i["largura"]), int(i["altura"])
    except Exception:
        return 0, 0


def montar_cortes(limite_fala: int = 320) -> list[dict]:
    """Cortes de `_Cortes/`: um card por PASTA (os vídeos dela formam um projeto só)."""
    cortes = []
    for g in colecao.agrupar_cortes(colecao.coletar_cortes(BASE)):
        pasta_abs = os.path.join(BASE, g["pasta"])
        alvo = os.path.join(pasta_abs, f"{g['nome']}.fcproj")
        w, h = _proporcao(os.path.join(BASE, g["videos"][0]))
        cortes.append({
            "arquivo": g["pasta"],
            "nome_arq": g["pasta"].split("/", 1)[-1],
            "videos": g["videos"],
            "tema": g["tema"],
            "tema_raiz": g["tema"].split("/")[0].strip(),
            "pilar": g["pilar"],
            "seg": g["segundos"],
            "mb": round(g["bytes"] / 1e6, 1),
            "fala": (g["fala"] or "")[:limite_fala],
            "gancho": g["gancho"],
            "w": w, "h": h,
            "projeto": os.path.exists(alvo),
            "arquivo_projeto": os.path.relpath(alvo, BASE).replace(os.sep, "/") if os.path.exists(alvo) else "",
            "nome_projeto": g["nome"],
        })
    return cortes
