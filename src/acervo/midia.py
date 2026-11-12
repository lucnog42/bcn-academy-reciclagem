#!/usr/bin/env python3
"""Miniaturas, tiras de quadros e informações de mídia, com cache em disco.

O app nativo não decodifica vídeo no Linux (o `Player` do Rune não tem
backend Linux), então tudo que é imagem de vídeo sai daqui, via FFmpeg:

  * miniatura(arq)  -> .jpg pequeno para a grade (imagem ou quadro do vídeo)
  * tira(video, n)  -> uma imagem com n quadros lado a lado, para o scrub
                       ao passar o mouse e para a linha do tempo do preview
  * info(arq)       -> duração, tamanho, fps, se tem áudio

O cache fica em `dados/marcas/<marca>/cache/` (fora do git) e a chave inclui a data
de modificação do arquivo, então um vídeo trocado gera miniatura nova.
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import hashlib
import json
import os
import subprocess
import threading

from nucleo import config

_TRAVAS: dict[str, threading.Lock] = {}
_TRAVA_GERAL = threading.Lock()
EXTS_VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")


def _trava(chave: str) -> threading.Lock:
    with _TRAVA_GERAL:
        return _TRAVAS.setdefault(chave, threading.Lock())


def cache_dir(sub: str) -> str:
    d = os.path.join(config.carregar()["app"]["cache"], sub)
    os.makedirs(d, exist_ok=True)
    return d


def _chave(arq: str, *extra) -> str:
    st = os.stat(arq)
    bruto = f"{os.path.abspath(arq)}|{st.st_mtime_ns}|{st.st_size}|" + "|".join(map(str, extra))
    return hashlib.sha1(bruto.encode()).hexdigest()[:20]


def eh_video(arq: str) -> bool:
    return os.path.splitext(arq)[1].lower() in EXTS_VIDEO


def info(arq: str) -> dict:
    alvo = os.path.join(cache_dir("info"), _chave(arq, "v2") + ".json")
    if os.path.exists(alvo):
        with open(alvo, encoding="utf-8") as fh:
            return json.load(fh)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", arq],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe falhou: {r.stderr.strip()[:200]}")
    d = json.loads(r.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = any(s.get("codec_type") == "audio" for s in d.get("streams", []))
    fps = 0.0
    if v:
        n, _, q = (v.get("avg_frame_rate") or "0/1").partition("/")
        fps = float(n) / float(q or 1) if float(q or 1) else 0.0
    # vídeo de celular: gravado deitado com uma marca de rotação; o FFmpeg e o
    # FilmCraft mostram em pé, então largura e altura trocam
    rot = 0
    if v:
        for sd in v.get("side_data_list") or []:
            if "rotation" in sd:
                rot = int(float(sd["rotation"]))
        rot = rot or int(float((v.get("tags") or {}).get("rotate", 0) or 0))
    w, h = (int(v.get("width", 0)), int(v.get("height", 0))) if v else (0, 0)
    if abs(rot) % 180 == 90:
        w, h = h, w
    out = {"duracao": float(d.get("format", {}).get("duration") or 0),
           "largura": w, "altura": h, "rotacao": rot,
           "fps": round(fps, 3), "audio": a, "video": bool(v) and eh_video(arq)}
    tmp = alvo + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    os.replace(tmp, alvo)
    return out


def _ffmpeg(args: list[str]) -> None:
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-300:])


def miniatura(arq: str, px: int | None = None, t: float | None = None) -> str:
    """Caminho de um .jpg com no máximo `px` no lado maior."""
    px = px or int(config.carregar()["app"]["miniatura_px"])
    chave = _chave(arq, "mini", px, t)
    alvo = os.path.join(cache_dir("mini"), chave + ".jpg")
    with _trava(chave):
        if os.path.exists(alvo):
            return alvo
        escala = f"scale='if(gt(iw,ih),{px},-2)':'if(gt(iw,ih),-2,{px})'"
        tmp = alvo + ".tmp.jpg"
        if eh_video(arq):
            dur = info(arq)["duracao"]
            quando = t if t is not None else min(1.0, dur * 0.1)
            _ffmpeg(["-ss", f"{quando:.3f}", "-i", arq, "-frames:v", "1", "-vf", escala,
                     "-q:v", "4", tmp])
        else:
            _ffmpeg(["-i", arq, "-frames:v", "1", "-vf", escala, "-q:v", "3", tmp])
        os.replace(tmp, alvo)
        return alvo


def tira(video: str, n: int = 12, px: int = 240) -> dict:
    """n quadros igualmente espaçados numa imagem só (n × 1). Devolve o
    caminho e a geometria para o app recortar cada quadro."""
    chave = _chave(video, "tira", n, px)
    alvo = os.path.join(cache_dir("tira"), chave + ".jpg")
    i = info(video)
    altura = round(px * i["altura"] / i["largura"] / 2) * 2 if i["largura"] else px
    res = {"arquivo": alvo, "n": n, "largura": px, "altura": altura, "duracao": i["duracao"],
           "tempos": [round(i["duracao"] * (k + 0.5) / n, 3) for k in range(n)]}
    with _trava(chave):
        if os.path.exists(alvo):
            return res
        taxa = n / max(i["duracao"], 0.1)
        tmp = alvo + ".tmp.jpg"
        # só quadros-chave: não decodifica o vídeo inteiro (de ~5 s para ~0,3 s num 1080p);
        # o tpad repete o último quadro-chave para a tira não terminar com casas vazias
        _ffmpeg(["-skip_frame", "nokey", "-i", video, "-vf", f"tpad=stop_mode=clone:stop_duration={i['duracao']:.2f},fps={taxa:.6f},scale={px}:{altura},tile={n}x1",
                 "-frames:v", "1", "-q:v", "4", tmp])
        os.replace(tmp, alvo)
        return res


def quadros(video: str, n: int = 16, px: int = 720) -> list[str]:
    """Os mesmos n quadros da tira, em tamanho de preview, numa passada só do FFmpeg que
    lê só os quadros-chave (o quadro fica no quadro-chave mais próximo do tempo; para a
    imagem exata, `exportar_quadro`). Devolve os caminhos, em ordem."""
    chave = _chave(video, "quadros", n, px)
    pasta = os.path.join(cache_dir("quadros"), chave)
    alvos = [os.path.join(pasta, f"{k + 1:02d}.jpg") for k in range(n)]
    with _trava(chave):
        if all(os.path.exists(a) for a in alvos):
            return alvos
        os.makedirs(pasta, exist_ok=True)
        i = info(video)
        taxa = n / max(i["duracao"], 0.1)
        escala = f"scale='if(gt(iw,ih),{px},-2)':'if(gt(iw,ih),-2,{px})'"
        _ffmpeg(["-skip_frame", "nokey", "-i", video, "-vf", f"tpad=stop_mode=clone:stop_duration={i['duracao']:.2f},fps={taxa:.6f},{escala}", "-frames:v", str(n), "-q:v", "4",
                 os.path.join(pasta, "%02d.jpg")])
        # se o vídeo rendeu um quadro a menos no fim, repete o último
        for k, a in enumerate(alvos):
            if not os.path.exists(a) and k:
                import shutil
                shutil.copy2(alvos[k - 1], a)
        return alvos


def exportar_quadro(video: str, t: float, destino_dir: str | None = None) -> str:
    """Quadro em resolução cheia (PNG) no instante t, numa pasta `quadros/` do post
    (ou ao lado do corte). Nunca sobrescreve: acrescenta -2, -3..."""
    base = os.path.splitext(os.path.basename(video))[0]
    if destino_dir is None:
        pai = os.path.dirname(video)
        destino_dir = os.path.join(os.path.dirname(pai) if os.path.basename(pai) == "videos" else pai, "quadros")
    os.makedirs(destino_dir, exist_ok=True)
    m, s = divmod(max(t, 0.0), 60)
    nome = f"{base}_{int(m):02d}m{s:04.1f}s".replace(".", ",")
    alvo = os.path.join(destino_dir, nome + ".png")
    k = 2
    while os.path.exists(alvo):
        alvo = os.path.join(destino_dir, f"{nome}-{k}.png")
        k += 1
    _ffmpeg(["-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", alvo])
    return alvo
