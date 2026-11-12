#!/usr/bin/env python3
"""Mexe num `.fcproj` já gerado, no lugar, sem refazer o projeto inteiro.

Usado pelos plugins para que a mudança apareça direto no FilmCraft:

  * ganho(proj, video, db)            -> volume do áudio do vídeo (normalizar)
  * legendas(proj, palavras, trechos) -> troca só a faixa de legenda (legendar)

Antes de gravar, a versão atual vai para `dados/marcas/<marca>/historico/projetos_antigos/` (espelhando o
acervo, com data e hora no nome), e o projeto novo é conferido com
`filmcraft-cli --project <p> inspect`; se o app recusar, a cópia volta.

    python3 fcproj.py ganho <proj.fcproj> <video> <db>
    python3 fcproj.py legendas <proj.fcproj> <video>
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import datetime as dt
import json
import os
import shutil
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
from nucleo import caminhos  # noqa: E402
BASE = caminhos.acervo()
from transcricao import legendas  # noqa: E402

ANTIGOS = caminhos.dados("historico", "projetos_antigos")
FILMCRAFT = "filmcraft-cli"


def _abs(p: str) -> str:
    return p if os.path.isabs(p) else os.path.join(BASE, p)


def carregar(caminho: str) -> dict:
    with open(_abs(caminho), encoding="utf-8") as fh:
        return json.load(fh)


def sequencia(proj: dict) -> dict:
    for item in proj["project"]["items"].values():
        if isinstance(item.get("kind"), dict) and "Sequence" in item["kind"]:
            return item["kind"]["Sequence"]
    raise RuntimeError("projeto sem sequência")


def caminho_do_item(proj: dict, item_id) -> str:
    it = proj["project"]["items"].get(str(item_id)) or {}
    media = (it.get("kind") or {}).get("Media") or {}
    return ((media.get("media") or {}).get("File") or {}).get("path", "")


def clipes_de(proj: dict, video: str, faixa: str = "audio_tracks") -> list[dict]:
    """Clipes (de áudio, por padrão) cuja mídia é `video`."""
    alvo = os.path.realpath(_abs(video))
    k = sequencia(proj)
    out = []
    for trilha in k.get(faixa, []):
        for cl in trilha.get("items", []):
            p = caminho_do_item(proj, cl.get("item"))
            if p and os.path.realpath(_abs(p)) == alvo:
                out.append(cl)
    return out


def guardar_copia(caminho: str) -> str:
    abs_ = _abs(caminho)
    rel = os.path.relpath(abs_, BASE)
    if rel.startswith(".."):              # fora do acervo: guarda só pelo nome
        rel = os.path.basename(abs_)
    raiz, ext = os.path.splitext(rel)
    destino = os.path.join(ANTIGOS, f"{raiz}.{dt.datetime.now():%Y%m%d-%H%M%S}{ext}")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.copy2(abs_, destino)
    return destino


def validar(caminho: str) -> str | None:
    """None se o FilmCraft abre; senão, a mensagem dele. Sem o CLI, não valida."""
    if not shutil.which(FILMCRAFT):
        return None
    r = subprocess.run([FILMCRAFT, "--project", _abs(caminho), "inspect"],
                       capture_output=True, text=True, timeout=120)
    return None if r.returncode == 0 else (r.stderr or r.stdout).strip()[:300]


def salvar(proj: dict, caminho: str) -> str:
    """Grava com cópia de segurança e confere no FilmCraft. Devolve o caminho da cópia."""
    copia = guardar_copia(caminho)
    abs_ = _abs(caminho)
    tmp = abs_ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(proj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, abs_)
    erro = validar(caminho)
    if erro:
        shutil.copy2(copia, abs_)
        raise RuntimeError(f"o FilmCraft recusou a mudança, projeto restaurado: {erro}")
    return copia


def ganho(caminho: str, video: str, db: float) -> int:
    """Põe `db` de ganho nos clipes de áudio do vídeo. Devolve quantos mudou."""
    proj = carregar(caminho)
    clipes = clipes_de(proj, video)
    for cl in clipes:
        cl["gain_db"] = round(float(db), 2)
    if clipes:
        salvar(proj, caminho)
    return len(clipes)


def lado_do_projeto(caminho: str):
    """O `<proj>.trechos.json`: {"videos": [{video, trechos, duracao}]} (novo) ou a
    lista de trechos de um vídeo só (antigo). None se o projeto não tem."""
    lado = os.path.splitext(_abs(caminho))[0] + ".trechos.json"
    if not os.path.exists(lado):
        return None
    with open(lado, encoding="utf-8") as fh:
        return json.load(fh)


def trechos_do_projeto(caminho: str) -> list[tuple] | None:
    """Trechos de fala do 1º vídeo, quando o projeto foi gerado com corte de silêncio."""
    d = lado_do_projeto(caminho)
    if isinstance(d, dict):
        vs = d.get("videos") or []
        t = vs[0].get("trechos") if vs else None
        return [tuple(x) for x in t] if t else None
    return [tuple(t) for t in d] if d else None


def palavras_do_video(video: str):
    from transcricao import legendar
    w = legendar.caminho_saida(_abs(video), ".words.json")
    return legendas.ler_words_json(w) if os.path.exists(w) else []


def legendas_do_projeto(caminho: str, palavras=None, fps: float | None = None) -> int:
    """Refaz só a faixa de legenda. Com vários vídeos (ou o lado novo), junta as
    palavras de cada um no lugar dele na timeline; senão usa `palavras` do vídeo único."""
    from projetos import modelo as MF
    proj = carregar(caminho)
    k = sequencia(proj)
    d = lado_do_projeto(caminho)
    if isinstance(d, dict) and d.get("videos"):
        lista = []
        for v in d["videos"]:
            dur = v.get("duracao")
            if dur is None:
                dur = MF.seg(MF.probe(_abs(v["video"]))["duration"])
            lista.append({"palavras": palavras_do_video(v["video"]), "trechos": v.get("trechos"),
                          "duracao": dur})
        cues = MF.ordenar_cartelas([(MF.ticks(a), MF.ticks(b - a), t) for a, b, t in
                                    legendas.cartelas(MF.palavras_na_timeline(lista), fps=fps)])
    else:
        cues = MF.ordenar_cartelas(MF.cartelas_de_palavras(palavras or [], trechos_do_projeto(caminho), fps))
    faixas = k.get("caption_tracks") or []
    if not faixas:
        return 0
    faixas[0]["captions"] = [{"id": 100 + i, "start": a, "duration": d_, "text": t,
                              "speaker": None, "cue_id": None, "settings": ""}
                             for i, (a, d_, t) in enumerate(cues)]
    salvar(proj, caminho)
    return len(cues)


def main() -> None:
    if len(sys.argv) >= 5 and sys.argv[1] == "ganho":
        n = ganho(sys.argv[2], sys.argv[3], float(sys.argv[4]))
        print(f"projeto: ganho {float(sys.argv[4]):+.1f} dB em {n} clipe(s) de {os.path.basename(sys.argv[2])}")
    elif len(sys.argv) >= 4 and sys.argv[1] == "legendas":
        n = legendas_do_projeto(sys.argv[2], palavras_do_video(sys.argv[3]))
        print(f"projeto: {n} cartelas novas em {os.path.basename(sys.argv[2])}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
