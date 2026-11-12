#!/usr/bin/env python3
"""Onde há voz de verdade no áudio, medido em passos de 10 ms.

O Whisper acerta as palavras mas erra as bordas: o tempo por palavra sai da
atenção do modelo, não do som. Na prática a 1ª palavra depois de uma pausa
costuma "começar" 0,1–0,4 s antes da voz e a última antes de uma pausa
"termina" até 1 s depois. É isso que faz a legenda aparecer antes da fala e
ficar na tela depois que a pessoa já parou.

Aqui as bordas são medidas no áudio:

  * Silero VAD (o mesmo modelo ONNX que já vem dentro do faster-whisper, sem
    download e sem torch) diz se cada janela de 32 ms tem voz — separa fala de
    torcida, bola e música melhor que volume;
  * o RMS em janelas de 10 ms acha a borda fina dentro dessa janela.

`refinar()` move só o que o som desmente: começo de palavra caído no silêncio
anda até a voz, fim caído no silêncio volta até a voz. Palavras no meio de uma
frase contínua ficam como o Whisper deu (não há borda audível entre elas).

Precisa de numpy; o VAD precisa de onnxruntime + faster-whisper (ambos já
estão no `.venv-asr`). Sem eles cai para só energia.
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import math
import subprocess
from dataclasses import dataclass

import numpy as np

SR = 16000
PASSO = 0.010            # resolução da análise
VAD_JANELA = 512         # amostras por janela do Silero a 16 kHz (32 ms)


@dataclass
class Voz:
    """Resultado da análise de um arquivo."""
    regioes: list[tuple[float, float]]   # trechos com voz (s)
    rms: np.ndarray                      # dBFS por passo de 10 ms
    prob: np.ndarray | None              # prob. de voz por passo de 10 ms
    piso_db: float                       # ruído de fundo estimado
    metodo: str                          # "vad+energia" | "energia"
    duracao: float


# ---------------------------------------------------------------- áudio
def carregar_audio(caminho: str, sr: int = SR) -> np.ndarray:
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", caminho,
         "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg não decodificou {caminho}: {r.stderr.decode()[-300:]}")
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def rms_db(audio: np.ndarray, sr: int = SR, passo: float = PASSO) -> np.ndarray:
    n = int(sr * passo)
    k = len(audio) // n
    if k == 0:
        return np.full(1, -120.0)
    q = audio[: k * n].reshape(k, n).astype(np.float64)
    r = np.sqrt((q * q).mean(axis=1))
    return np.maximum(20 * np.log10(r + 1e-9), -120.0)


_VAD = None


def _modelo_vad():
    global _VAD
    if _VAD is None:
        from faster_whisper.vad import get_vad_model   # ONNX embutido, sem download
        _VAD = get_vad_model()
    return _VAD


def prob_voz(audio: np.ndarray, sr: int = SR, passo: float = PASSO) -> np.ndarray | None:
    """Probabilidade de voz (0–1) reamostrada para passos de 10 ms."""
    try:
        modelo = _modelo_vad()
    except Exception:
        return None
    pad = (-len(audio)) % VAD_JANELA
    x = np.pad(audio, (0, pad)).astype(np.float32)
    try:
        p = np.asarray(modelo(x)).reshape(-1)
    except Exception:
        return None
    janela = VAD_JANELA / sr
    n = int(math.ceil(len(audio) / sr / passo))
    idx = np.minimum((np.arange(n) * passo / janela).astype(int), len(p) - 1)
    return p[idx]


# -------------------------------------------------------------- regiões
def _corridas(flags: np.ndarray) -> list[tuple[int, int]]:
    """[(i, j)) de cada sequência de True."""
    if not len(flags):
        return []
    d = np.diff(np.concatenate([[0], flags.astype(np.int8), [0]]))
    ini = np.flatnonzero(d == 1)
    fim = np.flatnonzero(d == -1)
    return list(zip(ini.tolist(), fim.tolist()))


def analisar(caminho_ou_audio, *, entra: float = 0.5, sai: float = 0.35,
             juntar: float = 0.10, minimo: float = 0.08,
             usar_vad: bool = True) -> Voz:
    """Mede as regiões de voz de um arquivo (ou de um array 16 kHz)."""
    audio = (carregar_audio(caminho_ou_audio) if isinstance(caminho_ou_audio, str)
             else np.asarray(caminho_ou_audio, dtype=np.float32))
    rms = rms_db(audio)
    n = len(rms)
    piso = float(np.percentile(rms, 10)) if n else -120.0
    prob = prob_voz(audio) if usar_vad else None
    if prob is not None:
        prob = prob[:n]
        if len(prob) < n:
            prob = np.pad(prob, (0, n - len(prob)), constant_values=0.0)

    # 1) núcleo: onde é voz com certeza
    if prob is not None:
        # histerese: entra acima de `entra`, só sai abaixo de `sai`
        voz = np.zeros(n, dtype=bool)
        dentro = False
        for i in range(n):
            if dentro:
                dentro = prob[i] >= sai
            else:
                dentro = prob[i] >= entra
            voz[i] = dentro
        # a voz ainda precisa ter energia acima do ruído (o VAD às vezes
        # fica "ligado" uns 100 ms depois da palavra)
        voz &= rms >= piso + 6.0
        metodo = "vad+energia"
    else:
        alto = float(np.percentile(rms, 95)) if n else -120.0
        limiar = max(piso + 10.0, min(piso + 0.35 * (alto - piso), alto - 6.0))
        voz = rms >= limiar
        metodo = "energia"

    corr = _corridas(voz)

    # 2) borda fina pela energia: a partir do núcleo, estende enquanto o som
    #    está acima de (pico do trecho − 30 dB) e acima do ruído; no máximo 80 ms
    regioes: list[list[float]] = []
    folga = int(0.08 / PASSO)
    for i, j in corr:
        pico = float(rms[i:j].max())
        lim = max(piso + 6.0, pico - 30.0)
        a = i
        while a > 0 and i - a < folga and rms[a - 1] >= lim:
            a -= 1
        b = j
        while b < n and b - j < folga and rms[b] >= lim:
            b += 1
        # e encolhe se o núcleo começou em quadro fraco
        while a < b - 1 and rms[a] < lim:
            a += 1
        while b > a + 1 and rms[b - 1] < lim:
            b -= 1
        ta, tb = a * PASSO, b * PASSO
        if regioes and ta - regioes[-1][1] < juntar:
            regioes[-1][1] = max(regioes[-1][1], tb)
        else:
            regioes.append([ta, tb])
    regioes = [r for r in regioes if r[1] - r[0] >= minimo]
    return Voz([(round(a, 3), round(b, 3)) for a, b in regioes], rms, prob, piso,
               metodo, len(audio) / SR)


# ------------------------------------------------------------ refinamento
def _regioes_em(regioes, a: float, b: float) -> list[tuple[float, float]]:
    return [r for r in regioes if r[1] > a and r[0] < b]


def refinar(palavras: list[tuple[float, float, str]], voz: Voz,
            max_desloc: float = 0.60, busca: float = 0.25, pausa_real: float = 0.20
            ) -> tuple[list[tuple[float, float, str]], dict]:
    """Ajusta começo/fim de cada palavra às bordas reais da voz.

    Regras (só mexe no que o som contradiz):
      * começo no silêncio  -> anda até o início da voz dentro da palavra;
      * fim no silêncio     -> volta até o fim da voz dentro da palavra;
      * 1ª palavra após pausa começando depois da voz (Whisper atrasado)
        -> recua até o início da voz, se não invadir a palavra anterior;
      * última antes da pausa terminando antes da voz acabar
        -> avança até o fim da voz, se não invadir a próxima;
      * palavra sem voz nenhuma por perto fica como estava (e é contada).
    """
    regs = voz.regioes
    saida: list[tuple[float, float, str]] = []
    stats = {"inicio_movido": 0, "fim_movido": 0, "sem_voz": 0,
             "desloc_inicio": [], "desloc_fim": []}
    for i, (a, b, t) in enumerate(palavras):
        a0, b0 = a, b
        ant = saida[-1][1] if saida else -1e9
        prox = palavras[i + 1][0] if i + 1 < len(palavras) else 1e9
        dentro = _regioes_em(regs, a - busca, b + busca)
        sobre = _regioes_em(regs, a, b)
        if not sobre:
            # palavra inteira caiu no silêncio: puxa para a voz mais próxima
            # que ainda não é de outra palavra (Whisper deslocado em bloco)
            perto = [r for r in dentro if r[1] > ant + 0.02]
            if perto:
                r = min(perto, key=lambda r: min(abs(r[0] - b), abs(r[1] - a)))
                dur = b - a
                if r[0] >= b:          # Whisper adiantado: a voz começa depois
                    a = r[0]
                    b = min(r[1], a + dur, prox if prox > a + 0.05 else a + dur)
                else:                  # Whisper atrasado: a voz acabou antes
                    b = r[1]
                    a = max(r[0], b - dur, ant)
            else:
                stats["sem_voz"] += 1
                saida.append((a, b, t))
                continue
        else:
            # uma palavra não atravessa uma pausa real: se ela cobre duas falas
            # separadas por silêncio (o Whisper "comeu" a pausa), fica só com a
            # primeira — a próxima palavra é que começa na fala seguinte
            grupos = [[sobre[0]]]
            for r in sobre[1:]:
                if r[0] - grupos[-1][-1][1] >= pausa_real:
                    grupos.append([r])
                else:
                    grupos[-1].append(r)

            def cobre(g):
                return sum(min(b, r[1]) - max(a, r[0]) for r in g)
            grupo = max(grupos, key=cobre)      # a fala onde está a maior parte
            r0, rn = grupo[0], grupo[-1]
            # começo
            if a < r0[0]:
                a = r0[0]
            elif r0[0] < a and r0[0] > ant + 0.02 and a - r0[0] <= max_desloc:
                a = r0[0]
            # fim
            if b > rn[1]:
                b = rn[1]
            elif rn[1] > b and rn[1] < prox - 0.02 and rn[1] - b <= max_desloc:
                b = rn[1]
        a = max(a, ant)
        if b - a < 0.05:
            b = a + 0.05
        if abs(a - a0) > 0.005:
            stats["inicio_movido"] += 1
            stats["desloc_inicio"].append(round(a - a0, 3))
        if abs(b - b0) > 0.005:
            stats["fim_movido"] += 1
            stats["desloc_fim"].append(round(b - b0, 3))
        saida.append((round(a, 3), round(b, 3), t))
    return saida, stats


def conferir(cartelas_: list[tuple[float, float, str]], voz: Voz,
             tolerancia: float = 0.12, sobra_ok: float = 0.25) -> dict:
    """Mede o que quem assiste percebe, cartela por cartela:

    entrada < 0  a legenda apareceu em silêncio, antes da voz (quanto antes);
    entrada > 0  a pessoa começou a falar e a tela ficou sem legenda (atraso);
    sobra   > 0  a legenda ficou na tela em silêncio, depois da voz;
    sobra   < 0  a legenda sumiu com a pessoa ainda falando.

    Borda que cai no meio de uma fala coberta por outra cartela não é erro.
    """
    regs = voz.regioes
    cs = sorted(cartelas_)

    def regiao_em(t):
        return next((r for r in regs if r[0] <= t < r[1]), None)

    linhas = []
    for i, (a, b, t) in enumerate(cs):
        ant_fim = cs[i - 1][1] if i else -1e9
        prox_ini = cs[i + 1][0] if i + 1 < len(cs) else 1e9
        r = regiao_em(a)
        if r is None:                       # entrou no silêncio
            prox = next((x[0] for x in regs if x[0] >= a), None)
            entrada = round(a - prox, 3) if prox is not None and prox < b else None
        elif ant_fim < r[0] - 0.02:          # tela vazia quando a voz começou
            entrada = round(a - r[0], 3)
        else:
            entrada = 0.0
        r = regiao_em(b - 1e-3)
        if r is None:                       # saiu no silêncio
            fim_voz = max((x[1] for x in regs if x[1] <= b), default=None)
            sobra = round(b - fim_voz, 3) if fim_voz is not None and fim_voz > a else None
        elif prox_ini > r[1] + 0.02:         # sumiu antes de a voz acabar
            sobra = round(b - r[1], 3)
        else:
            sobra = 0.0
        linhas.append({"ini": a, "fim": b, "texto": t, "entrada": entrada, "sobra": sobra})

    en = [abs(l["entrada"]) for l in linhas if l["entrada"] is not None]
    so = [l["sobra"] for l in linhas if l["sobra"] is not None]
    fora = []
    for l in linhas:
        le, ls = l["entrada"], l["sobra"]
        cat = None
        if le is not None and le < -tolerancia:
            cat = "entra_antes"
        elif le is not None and le > tolerancia:
            cat = "voz_sem_texto_antes" if le > 0.6 else "entra_atrasada"
        elif ls is not None and ls > sobra_ok:
            cat = "duracao_minima" if l["fim"] - l["ini"] <= 0.42 else "fica_depois"
        elif ls is not None and ls < -tolerancia:
            cat = "voz_sem_texto_depois" if ls < -0.6 else "sai_cedo"
        if cat:
            l["categoria"] = cat
            fora.append(l)
    sem_voz = sum(1 for l in linhas if l["entrada"] is None and l["sobra"] is None)
    categorias: dict[str, int] = {}
    for l in fora:
        categorias[l["categoria"]] = categorias.get(l["categoria"], 0) + 1

    def pct(xs, p):
        return round(float(np.percentile(xs, p)), 3) if xs else 0.0
    return {"cartelas": len(linhas),
            "entrada_p90": pct(en, 90), "entrada_max": round(max(en), 3) if en else 0.0,
            "sobra_p90": pct(so, 90), "sobra_max": round(max(so), 3) if so else 0.0,
            "fora_tolerancia": len(fora), "sem_voz": sem_voz, "categorias": categorias,
            "erros_reais": sum(n for c, n in categorias.items() if c in REAIS),
            "linhas": linhas, "piores": sorted(fora, key=lambda l: -max(
                abs(l["entrada"] or 0), abs(l["sobra"] or 0)))}


# o que é erro de sincronia de verdade; o resto é voz sem texto (música,
# torcida, outra pessoa) ou a duração mínima de leitura, que é proposital
REAIS = ("entra_antes", "entra_atrasada", "fica_depois", "sai_cedo")
CATEGORIAS = {
    "entra_antes": "legenda aparece antes da voz",
    "entra_atrasada": "legenda atrasada (até 0,6 s)",
    "fica_depois": "legenda fica em silêncio depois da voz",
    "sai_cedo": "legenda some com a voz ainda soando (até 0,6 s)",
    "voz_sem_texto_antes": "som de voz sem palavra transcrita antes (música, torcida, outra pessoa)",
    "voz_sem_texto_depois": "som de voz sem palavra transcrita depois (música, torcida, outra pessoa)",
    "duracao_minima": "palavra curta mantida 0,4 s na tela para dar tempo de ler",
}


def _regiao_mais_proxima(regioes, cartela):
    a, b, _ = cartela
    meio = (a + b) / 2
    return min(regioes, key=lambda r: 0 if r[0] <= meio <= r[1] else min(abs(meio - r[0]), abs(meio - r[1])))
