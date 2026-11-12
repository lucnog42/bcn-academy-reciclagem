#!/usr/bin/env python3
"""Normaliza o volume de um vídeo/áudio para redes sociais (loudnorm em duas passadas).

    python3 normalizar.py <arquivo> [--lufs -14] [--pico -1.5] [--saida <arquivo>]

Grava `<nome>_norm<ext>` na pasta `saidas/` do post ou do corte (nunca sobrescreve o
original, e fica fora da lista de vídeos). A imagem é copiada
sem recodificar; o áudio sai em AAC 192k (ou no formato do arquivo, se for só áudio).
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "src"))  # src/

import argparse
import json
import os
import re
import subprocess
import sys


def medir(arq: str, lufs: float, pico: float) -> dict:
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", arq, "-vn",
                        "-af", f"loudnorm=I={lufs}:TP={pico}:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        sys.exit(f"não consegui medir {arq}:\n{r.stderr[-800:]}")
    return json.loads(m.group(0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("arquivo")
    ap.add_argument("--lufs", type=float, default=-14.0)
    ap.add_argument("--pico", type=float, default=-1.5)
    ap.add_argument("--saida")
    ap.add_argument("--projeto", help=".fcproj: põe o ganho no clipe de áudio do vídeo, no próprio projeto")
    ap.add_argument("--sem-arquivo", action="store_true", help="não grava o _norm, só ajusta o projeto")
    a = ap.parse_args()
    base, ext = os.path.splitext(a.arquivo)
    if not a.saida:
        pai = os.path.dirname(os.path.abspath(a.arquivo))
        raiz = os.path.dirname(pai) if os.path.basename(pai) == "videos" else pai
        os.makedirs(os.path.join(raiz, "saidas"), exist_ok=True)
    saida = a.saida or os.path.join(raiz, "saidas", os.path.basename(base) + f"_norm{ext}")
    if os.path.abspath(saida) == os.path.abspath(a.arquivo):
        sys.exit("a saída não pode ser o próprio arquivo")
    m = medir(a.arquivo, a.lufs, a.pico)
    print(f"medido: {m['input_i']} LUFS, pico {m['input_tp']} dBTP, LRA {m['input_lra']}", flush=True)
    if a.projeto:
        # no projeto é só um ganho: leva o loudness ao alvo sem passar do pico
        ganho = min(a.lufs - float(m["input_i"]), a.pico - float(m["input_tp"]))
        from projetos import fcproj
        n = fcproj.ganho(a.projeto, a.arquivo, ganho)
        limite = " (limitado pelo pico)" if ganho < a.lufs - float(m["input_i"]) - 0.05 else ""
        print(f"projeto: ganho {ganho:+.1f} dB{limite} em {n} clipe(s) de {os.path.basename(a.projeto)}", flush=True)
    if a.sem_arquivo:
        return
    filtro = (f"loudnorm=I={a.lufs}:TP={a.pico}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    so_audio = ext.lower() in (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus")
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", a.arquivo, "-af", filtro, "-ar", "48000"]
    if not so_audio:
        cmd += ["-map", "0:v:0?", "-map", "0:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    cmd.append(saida)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg falhou:\n{r.stderr[-800:]}")
    depois = medir(saida, a.lufs, a.pico)
    print(f"pronto: {saida} → {depois['input_i']} LUFS, pico {depois['input_tp']} dBTP", flush=True)


if __name__ == "__main__":
    main()
