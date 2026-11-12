#!/usr/bin/env python3
"""Confere se a legenda está colada na fala: mede cada cartela do .srt contra
a voz medida no áudio do vídeo.

    python3 src/verificacao/conferir_legendas.py --arquivo _Cortes/Fernando/x.mp4
    python3 src/verificacao/conferir_legendas.py --raiz _Cortes --limite 20
    python3 src/verificacao/conferir_legendas.py --arquivo x.mp4 --detalhe

Para cada vídeo mostra: quanto a legenda entra antes/depois da voz (mediana e
p90) e quanto fica na tela depois que a fala acaba. As piores cartelas saem
com --detalhe. Roda no .venv-asr (precisa de numpy e do Silero do faster-whisper).
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
from nucleo import caminhos  # noqa: E402
BASE = caminhos.acervo()
from transcricao import legendas  # noqa: E402
from transcricao import legendar  # noqa: E402


def conferir_video(video: str, detalhe: bool = False) -> dict | None:
    srt = legendar.caminho_saida(video, ".srt")
    cues = legendas.ler_srt(srt)
    if not cues:
        return None
    v = voz.analisar(video)
    r = voz.conferir(cues, v)
    nome = os.path.relpath(video, BASE)
    print(f"{nome[-58:]:58s} {r['cartelas']:3d} cartelas · entrada p90 {r['entrada_p90']:.2f}s "
          f"máx {r['entrada_max']:.2f}s · sobra p90 {r['sobra_p90']:+.2f}s máx {r['sobra_max']:+.2f}s"
          f" · fora {r['fora_tolerancia']} (erro real {r['erros_reais']})"
          + (f" · {r['sem_voz']} sem voz" if r["sem_voz"] else ""))
    if detalhe:
        for l in r["piores"][:10]:
            e = "—" if l["entrada"] is None else f"{l['entrada']:+.2f}s"
            so = "—" if l["sobra"] is None else f"{l['sobra']:+.2f}s"
            print(f"    {l['ini']:7.2f}–{l['fim']:7.2f}  entrada {e}  sobra {so}  "
                  f"[{l['categoria']}]  {l['texto']}")
    return r


def garantir_venv() -> None:
    """numpy + Silero vivem no .venv-asr: reexecuta lá se preciso."""
    try:
        import numpy  # noqa: F401
        import faster_whisper  # noqa: F401
        return
    except ImportError:
        pass
    alvo = caminhos.raiz(".venv-asr", "bin", "python")
    if os.path.exists(alvo) and os.path.realpath(sys.executable) != os.path.realpath(alvo):
        os.execv(alvo, [alvo, os.path.abspath(__file__)] + sys.argv[1:])
    sys.exit("precisa do .venv-asr (numpy + faster-whisper)")


def main() -> None:
    garantir_venv()
    global voz
    from transcricao import voz
    ap = argparse.ArgumentParser()
    ap.add_argument("--raiz", action="append", default=[])
    ap.add_argument("--arquivo", action="append", default=[])
    ap.add_argument("--desde", type=int)
    ap.add_argument("--limite", type=int)
    ap.add_argument("--detalhe", action="store_true")
    a = ap.parse_args()
    videos = []
    for r in a.raiz:
        videos += legendar.listar(r if os.path.isabs(r) else os.path.join(BASE, r), a.desde)
    videos += [v if os.path.isabs(v) else os.path.join(BASE, v) for v in a.arquivo]
    videos = [v for v in sorted(set(videos))
              if os.path.exists(legendar.caminho_saida(v, ".srt"))]
    if a.limite:
        videos = videos[:a.limite]
    if not videos:
        sys.exit("nenhum vídeo com .srt (--raiz _Cortes | --arquivo <vídeo>)")
    todos = []
    for v in videos:
        r = conferir_video(v, a.detalhe)
        if r:
            todos.append(r)
    if len(todos) > 1:
        fora = sum(r["fora_tolerancia"] for r in todos)
        reais = sum(r["erros_reais"] for r in todos)
        total = sum(r["cartelas"] for r in todos)
        print(f"\n{len(todos)} vídeos · {total} cartelas · {fora} fora da tolerância "
              f"({100 * fora / max(total, 1):.1f}%) · erro real de sincronia: {reais} "
              f"({100 * reais / max(total, 1):.1f}%)")
        cats: dict[str, int] = {}
        for r in todos:
            for c, n in r["categorias"].items():
                cats[c] = cats.get(c, 0) + n
        for c, n in sorted(cats.items(), key=lambda x: -x[1]):
            marca = "erro" if c in voz.REAIS else "    "
            print(f"  {marca} {n:6d}  {voz.CATEGORIAS[c]}")


if __name__ == "__main__":
    main()
