#!/usr/bin/env python3
"""A linha do tempo do projeto do FilmCraft, lida para o motion e o vídeo com IA.

As sugestões partem do PROJETO (o que vai para o ar: já cortado, com abertura, logo, legendas,
ending e os motions que já existem), não do vídeo cru. Daqui saem:

  * os trechos de fala na timeline e de onde cada um vem (vídeo + tempo no arquivo), pela faixa
    de áudio do vídeo (no J/L a imagem anda deslocada; a fala manda);
  * o que já ocupa a tela em cada instante: abertura (título), logo, motions, ending;
  * as legendas exatamente como estão no projeto, com o tempo da timeline.

    python3 linha_tempo.py <projeto.fcproj>      # mostra o resumo que a IA recebe
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
from projetos import fcproj  # noqa: E402

TICKS = 254_016_000_000
NOMES = {2: "abertura (forma)", 3: "abertura (título e subtítulo)", 24: "logo"}


def _s(t: int) -> float:
    return round(t / TICKS, 3)


def _textos(cl: dict) -> list[str]:
    out = []
    for e in cl.get("effects") or []:
        if e.get("effect") == "graphic_text":
            t = (((e.get("params") or {}).get("text") or {}).get("value") or {}).get("Text")
            if t:
                out.append(str(t))
    return out


def ler(projeto: str) -> dict:
    proj = fcproj.carregar(projeto)
    k = fcproj.sequencia(proj)
    base = os.path.realpath(fcproj.BASE)

    def rel(item_id) -> str:
        p = fcproj.caminho_do_item(proj, item_id)
        return os.path.relpath(os.path.realpath(p), base).replace(os.sep, "/") if p else ""

    vt = k.get("video_tracks") or []
    at = k.get("audio_tracks") or []
    principal = next((t for t in vt if t.get("id") == 1), vt[0] if vt else {"items": []})
    audio = next((t for t in at if t.get("id") == 4), at[0] if at else {"items": []})
    # o que é vídeo do item: o que está no V1 e não é o ending (o último clipe, de outra mídia)
    videos_v1 = [rel(c["item"]) for c in principal["items"]]
    ending = None
    if len(set(videos_v1)) > 1 and videos_v1[-1] not in videos_v1[:-1]:
        c = principal["items"][-1]
        ending = {"t0": _s(c["start"]), "t1": _s(c["start"] + c["duration"]), "nome": c.get("name", "")}
    meus = set(videos_v1[:-1] if ending else videos_v1)
    pecas = [{"t0": _s(c["start"]), "t1": _s(c["start"] + c["duration"]), "video": rel(c["item"]),
              "src0": _s(c.get("source_in", 0))}
             for c in sorted(audio["items"], key=lambda c: c["start"]) if rel(c["item"]) in meus]
    camadas = []
    for t in vt:
        if t is principal:
            continue
        for c in t.get("items") or []:
            camadas.append({"faixa": t.get("name") or f"V{t.get('id')}",
                            "o_que": "motion" if t.get("name") == "Motion" else NOMES.get(t.get("id"), t.get("name") or ""),
                            "t0": _s(c["start"]), "t1": _s(c["start"] + c["duration"]),
                            "nome": c.get("name", ""), "textos": _textos(c)})
    legendas = []
    for cap in k.get("caption_tracks") or []:
        for c in cap.get("captions") or []:
            legendas.append((_s(c["start"]), _s(c["start"] + c["duration"]), c.get("text", "")))
    fim_video = max((p["t1"] for p in pecas), default=0.0)
    return {"projeto": os.path.relpath(os.path.realpath(fcproj._abs(projeto)), base).replace(os.sep, "/"),
            "duracao": max([fim_video] + [c["t1"] for c in camadas] + ([ending["t1"]] if ending else [])),
            "fim_video": fim_video, "pecas": pecas, "camadas": sorted(camadas, key=lambda c: c["t0"]),
            "ending": ending, "legendas": sorted(legendas)}


def para_fonte(linha: dict, t: float) -> tuple[str, float] | None:
    """Tempo da timeline -> (vídeo, tempo no arquivo). Fora da fala: o trecho mais próximo."""
    if not linha["pecas"]:
        return None
    for p in linha["pecas"]:
        if p["t0"] <= t < p["t1"]:
            return p["video"], round(p["src0"] + (t - p["t0"]), 3)
    p = min(linha["pecas"], key=lambda p: min(abs(t - p["t0"]), abs(t - p["t1"])))
    t = min(max(t, p["t0"]), p["t1"] - 0.01)
    return p["video"], round(p["src0"] + (t - p["t0"]), 3)


def para_timeline(linha: dict, video: str, src: float) -> float | None:
    """(vídeo, tempo no arquivo) -> tempo da timeline; None se esse trecho foi cortado."""
    for p in linha["pecas"]:
        if p["video"] == video and p["src0"] <= src < p["src0"] + (p["t1"] - p["t0"]):
            return round(p["t0"] + (src - p["src0"]), 3)
    return None


def na_tela(linha: dict, t0: float, t1: float) -> dict:
    """O que já está na tela entre t0 e t1 (timeline): camadas, legendas e cortes perto."""
    camadas = [c for c in linha["camadas"] if c["t0"] < t1 and c["t1"] > t0]
    legendas = [x[2] for x in linha["legendas"] if x[0] < t1 and x[1] > t0]
    cortes = [p["t0"] for p in linha["pecas"][1:] if t0 - 1.0 <= p["t0"] <= t1 + 1.0]
    ending = linha["ending"] and linha["ending"]["t0"] < t1
    return {"camadas": camadas, "legendas": legendas, "cortes": cortes, "ending": bool(ending)}


def resumo(linha: dict) -> str:
    """O texto que a IA recebe: tempos da TIMELINE do projeto."""
    l = [f"Projeto: {linha['projeto']} — {linha['duracao']:.1f} s no total; o vídeo (fala) vai até "
         f"{linha['fim_video']:.1f} s" + (f", depois o encerramento ({linha['ending']['t0']:.1f}–{linha['ending']['t1']:.1f} s)."
                                         if linha["ending"] else ".")]
    cortes = [f"{p['t0']:.1f}" for p in linha["pecas"][1:]]
    l.append(f"Trechos de fala emendados: {len(linha['pecas'])}" +
             (f"; emendas (cortes) em {', '.join(cortes)} s." if cortes else "."))
    if linha["camadas"]:
        l.append("Já ocupam a tela (não sobreponha sem motivo):")
        for c in linha["camadas"]:
            txt = f" — \"{' / '.join(c['textos'])}\"" if c["textos"] else ""
            l.append(f"  {c['t0']:.1f}–{c['t1']:.1f} s  {c['o_que'] or c['faixa']}{txt}")
    l.append("Legendas do projeto (terço de baixo da tela), tempo da timeline:")
    for a, b, t in linha["legendas"]:
        l.append(f"  [{a:.1f}–{b:.1f}] {t}")
    return "\n".join(l)


if __name__ == "__main__":
    print(resumo(ler(sys.argv[1])))
