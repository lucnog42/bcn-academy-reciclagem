#!/usr/bin/env python3
"""Cortar silêncio de um item (post ou pasta de cortes), nas duas pontas:

  * projeto: refaz o .fcproj do item com só a fala de cada vídeo, já com J/L entre
    as falas (o anterior fica em dados/marcas/<marca>/historico/projetos_antigos/)
  * arquivo: grava <vídeo>_sem_silencio.mp4 com o FFmpeg na pasta `saidas/` do item
    (fora da lista de posts e cortes, para não aparecer como vídeo novo)

Onde há fala vem das palavras do Whisper (`.words.json`, bordas já medidas na voz):
ruído de fundo, vento ou torcida não contam como fala. Sem transcrição, o nível do
ruído é estimado (`--detector auto`) ou fixo (`--detector nivel -t -40`).

    python3 aplicar.py <vídeo> [<vídeo> ...] --onde "projeto e arquivo" --corte _Cortes/Pais [opções do silencecut]
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "src"))  # src/

import argparse
import json
import os
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(AQUI)), "src")
from nucleo import caminhos  # noqa: E402
BASE = caminhos.acervo()
def abs_(p: str) -> str:
    return p if os.path.isabs(p) else os.path.join(BASE, p)


def pasta_de_saidas(video: str) -> str:
    """`<post>/saidas/` (o vídeo do post está em `<post>/videos/`) ou `<pasta do corte>/saidas/`."""
    pai = os.path.dirname(video)
    raiz = os.path.dirname(pai) if os.path.basename(pai) == "videos" else pai
    d = os.path.join(raiz, "saidas")
    os.makedirs(d, exist_ok=True)
    return d


def regioes_da_fala(video: str, silencio: float) -> list[list[float]] | None:
    """Onde há fala, pelas palavras: palavras com pausa menor que `silencio` viram uma região."""
    from transcricao import legendar
    w = legendar.caminho_saida(video, ".words.json")
    if not os.path.exists(w):
        return None
    from transcricao import legendas
    regs: list[list[float]] = []
    for a, b, _ in sorted(legendas.ler_words_json(w)):
        if regs and a - regs[-1][1] < silencio:
            regs[-1][1] = max(regs[-1][1], b)
        else:
            regs.append([a, b])
    return regs or None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--onde", default="projeto e arquivo")
    ap.add_argument("--detector", default="fala", choices=["fala", "auto", "nivel"])
    ap.add_argument("-s", "--min-silence", type=float, default=0.5)
    ap.add_argument("--post")
    ap.add_argument("--corte")
    a, resto = ap.parse_known_args()
    projeto = "projeto" in a.onde
    arquivo = "arquivo" in a.onde
    erros = 0
    for v in a.videos:
        v = abs_(v)
        cmd = [sys.executable, os.path.join(AQUI, "silencecut.py"), v, "-s", f"{a.min_silence}", *resto]
        tmp = None
        if a.detector == "fala":
            regs = regioes_da_fala(v, a.min_silence)
            if regs:
                tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
                json.dump(regs, tmp)
                tmp.close()
                cmd += ["--regioes", tmp.name]
            else:
                print(f"  {os.path.basename(v)}: sem transcrição — usando o nível de ruído estimado", flush=True)
                cmd += ["--auto-threshold"]
        elif a.detector == "auto":
            cmd += ["--auto-threshold"]
        if arquivo:
            saida = os.path.join(pasta_de_saidas(v), os.path.splitext(os.path.basename(v))[0] + "_sem_silencio.mp4")
            cmd += ["--render", saida]
        print(f"▶ {os.path.basename(v)}: medindo a fala" + (" e renderizando" if arquivo else ""), flush=True)
        r = subprocess.run(cmd)
        if tmp:
            os.unlink(tmp.name)
        erros += r.returncode != 0
    if erros:
        sys.exit(1)
    if projeto:
        if not (a.post or a.corte):
            print("sem post/corte: projeto não atualizado", flush=True)
            return
        print("▶ montando o projeto do FilmCraft só com a fala (e os J/L)", flush=True)
        g = [sys.executable, os.path.join(SRC, "projetos", "gerar.py"), "--aplicar", "--forcar", "--usar-cortes"]
        g += ["--tipo", "corte", "--corte", a.corte] if a.corte else ["--tipo", "video", "--post", a.post]
        sys.exit(subprocess.run(g).returncode)


if __name__ == "__main__":
    main()
