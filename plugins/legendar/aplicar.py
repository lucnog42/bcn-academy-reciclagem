#!/usr/bin/env python3
"""Legendar um vídeo e, se houver projeto, trocar a legenda dentro do .fcproj.

    python3 aplicar.py <vídeo> --modo refinar|transcrever [--projeto <arquivo.fcproj>]

Só a faixa de legenda do projeto muda (o resto, inclusive o que foi editado à mão no
FilmCraft, fica); a versão anterior vai para dados/marcas/<marca>/historico/projetos_antigos/.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "src"))  # src/

import argparse
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(AQUI)), "src")
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--modo", default="refinar")
    ap.add_argument("--projeto")
    a = ap.parse_args()
    cmd = [sys.executable, os.path.join(SRC, "transcricao", "legendar.py"), "--arquivo", a.video, "--aplicar",
           "--so-srt" if a.modo == "refinar" else "--forcar"]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(r.returncode)
    if a.projeto:
        # projeto_fc usa o python que tiver; o words.json já foi gravado
        r = subprocess.run([sys.executable, os.path.join(SRC, "projetos", "fcproj.py"), "legendas", a.projeto, a.video])
        sys.exit(r.returncode)


if __name__ == "__main__":
    main()
