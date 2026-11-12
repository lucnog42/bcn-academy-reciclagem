#!/usr/bin/env python3
"""Cartelas de legenda a partir das palavras com tempo — uma regra só.

Antes havia duas: o `legendar.py` montava o .srt por palavra e o
`modelo_filmcraft.py` lia esse .srt e redividia cada cue **por proporção**,
depois forçava 0,5 s mínimos e empurrava a cartela seguinte para frente quando
encostava na anterior. Cada cartela empurrada empurrava a próxima, e a
legenda ia descolando da fala ao longo do vídeo.

Agora as duas pontas usam `cartelas()` daqui, e o gerador monta as cartelas
direto do `.words.json` (já mapeado para a timeline cortada), sem redividir.

Regras:
  * no máximo 4 palavras, quebra numa pausa real (> 0,25 s) ou aos 2,6 s;
  * entra no começo da 1ª palavra (sem antecipar) e sai 0,08 s depois da última;
  * duas cartelas com menos de 0,15 s entre si encostam (a legenda não pisca);
  * duração mínima só cresce até a próxima fala — nunca empurra ninguém;
  * tudo alinhado ao quadro do vídeo quando o fps é informado.

Só stdlib.
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import json
import math
import os
import re

MAX_PALAVRAS = 4
PAUSA = 0.25          # pausa que quebra a cartela
DUR_MAX = 2.6         # cartela não passa disso
DUR_MIN = 0.40        # abaixo disso não dá para ler 1 palavra
ENTRADA = 0.0         # antecipação da entrada (0 = no começo da fala)
SAIDA = 0.08          # quanto fica depois da última palavra
ENCOSTAR = 0.15       # buraco menor que isso entre cartelas é fechado

Palavra = tuple[float, float, str]


def fim_util(ini: float, fim: float, texto: str) -> float:
    """Teto para o fim de uma palavra quando não há medida de voz: o Whisper às
    vezes estica uma palavra isolada por segundos. ~0,09 s por letra + 0,25."""
    return min(fim, ini + min(1.6, max(0.30, 0.09 * len(texto) + 0.25)))


def cartelas(palavras: list[Palavra], *, maximo: int = MAX_PALAVRAS,
             pausa: float = PAUSA, dur_max: float = DUR_MAX, dur_min: float = DUR_MIN,
             entrada: float = ENTRADA, saida: float = SAIDA, encostar: float = ENCOSTAR,
             fps: float | None = None) -> list[Palavra]:
    """[(ini, fim, texto)] — agrupa palavras em cartelas presas à fala."""
    palavras = sorted((p for p in palavras if p[2].strip()), key=lambda p: p[0])
    grupos: list[list[Palavra]] = []
    atual: list[Palavra] = []
    for p in palavras:
        if atual:
            buraco = p[0] - atual[-1][1]
            longo = (p[1] - atual[0][0]) > dur_max
            if len(atual) >= maximo or buraco > pausa or longo:
                grupos.append(atual)
                atual = []
        atual.append(p)
    if atual:
        grupos.append(atual)

    base = [(max(0.0, g[0][0] - entrada), g[-1][1], " ".join(w[2].strip() for w in g))
            for g in grupos]
    out: list[Palavra] = []
    for i, (ini, fim_fala, txt) in enumerate(base):
        prox = base[i + 1][0] if i + 1 < len(base) else math.inf
        fim = fim_fala + saida
        if prox - fim < encostar:          # fala seguida: encosta, não pisca
            fim = prox
        if fim - ini < dur_min:            # curta demais: cresce só até a próxima
            fim = min(ini + dur_min, prox)
        fim = min(fim, prox)
        out.append((ini, fim, txt))

    if fps:
        q = 1.0 / fps
        alinhadas = []
        for ini, fim, txt in out:
            a = round(ini / q) * q
            b = max(a + q, round(fim / q) * q)
            if alinhadas and a < alinhadas[-1][1]:
                pa, pb, pt = alinhadas[-1]
                alinhadas[-1] = (pa, max(pa + q, a), pt)
            alinhadas.append((a, b, txt))
        return [(round(a, 6), round(b, 6), t) for a, b, t in alinhadas]
    return [(round(a, 3), round(b, 3), t) for a, b, t in out]


# ------------------------------------------------------------ tempo cortado
def mapear_palavras(palavras: list[Palavra], trechos: list[tuple[float, float]] | None
                    ) -> list[Palavra]:
    """Leva palavras do tempo do arquivo para a timeline com o silêncio removido.
    Palavra fora de todos os trechos sai (foi cortada); palavra que cruza um
    corte é recortada no trecho onde está a maior parte dela."""
    if not trechos:
        return list(palavras)
    saida: list[Palavra] = []
    offs = []
    acc = 0.0
    for a, b in trechos:
        offs.append(acc)
        acc += b - a
    for ini, fim, txt in palavras:
        melhor = None
        for (a, b), off in zip(trechos, offs):
            sob = min(fim, b) - max(ini, a)
            if sob > 0 and (melhor is None or sob > melhor[0]):
                melhor = (sob, off + max(ini, a) - a, off + min(fim, b) - a)
        if melhor and melhor[2] - melhor[1] >= 0.04:
            saida.append((round(melhor[1], 3), round(melhor[2], 3), txt))
    return saida


# --------------------------------------------------------------- arquivos
def ler_words_json(caminho: str) -> list[Palavra]:
    with open(caminho, encoding="utf-8") as fh:
        d = json.load(fh)
    return [(float(w["a"]), float(w["b"]), w["t"]) for w in d.get("palavras", [])]


def _ts(t: float) -> str:
    t = max(0.0, t)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def escrever_srt(cartelas_: list[Palavra], caminho: str) -> None:
    blocos = [f"{i}\n{_ts(a)} --> {_ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(cartelas_, 1)]
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(blocos))
    os.replace(tmp, caminho)


def ler_srt(caminho: str) -> list[Palavra]:
    if not caminho or not os.path.exists(caminho):
        return []
    bruto = open(caminho, encoding="utf-8", errors="replace").read()
    cues = []
    for bloco in re.split(r"\n\s*\n", bruto.strip()):
        linhas = [l for l in bloco.splitlines() if l.strip()]
        marca = next((l for l in linhas if "-->" in l), None)
        if not marca:
            continue

        def s(hms: str) -> float:
            h, m, resto = hms.strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(resto.replace(",", "."))
        ini, fim = marca.split("-->")[:2]
        texto = " ".join(l.strip() for l in linhas[linhas.index(marca) + 1:])
        if texto:
            cues.append((s(ini), s(fim.split()[0]), texto))
    return cues


def words_ao_lado(srt: str) -> str | None:
    """`.words.json` irmão de um `.srt` (mesma raiz), se existir."""
    if not srt:
        return None
    alvo = os.path.splitext(srt)[0] + ".words.json"
    return alvo if os.path.exists(alvo) else None
