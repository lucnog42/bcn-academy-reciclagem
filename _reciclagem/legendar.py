#!/usr/bin/env python3
"""Passo 7 — reescreve os .srt do acervo com tempo por palavra.

O .srt herdado do Whisper tem cue por trecho inteiro (até 30 s) e o projeto
dividia esse cue em blocos de 4 palavras por proporção — o que atrasa a legenda
em até 5 s. Aqui o SRT nasce **já legendável**: cada cartela tem no máximo 4
palavras e começa/termina no tempo real das palavras ditas.

    python3 _reciclagem/legendar.py --raiz _Cortes                  # simula
    python3 _reciclagem/legendar.py --raiz _Cortes --aplicar
    python3 _reciclagem/legendar.py --raiz _posts --aplicar --desde 2025
    python3 _reciclagem/legendar.py --arquivo <um.mp4> --aplicar

Grava, ao lado de cada vídeo (posts: espelhado em `transcricoes/`):
    <video>.srt         cartelas de até 4 palavras
    <video>.words.json  palavras com tempo (fonte para regerar)
    <video>.txt         transcrição corrida (rótulos/pilar usam esse texto)

O .srt antigo é movido para `_reciclagem/srt_antigo/` espelhando a origem.
Fila em `srt_fila.csv`, retomável: o que já tem .words.json é pulado.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(AQUI)
FILA = os.path.join(AQUI, "srt_fila.csv")
ANTIGOS = os.path.join(AQUI, "srt_antigo")
COLS = ["video", "status", "segundos", "audio_s", "erro"]

MAX_PALAVRAS = 4        # cabe em uma linha no quadro 1080×1920 a 40 pt
PAUSA = 0.30            # pausa que quebra a cartela
DUR_MAX = 2.6           # cartela não fica mais que isso na tela
DUR_MIN = 0.55
LEAD = 0.05             # entra um tico antes da palavra
TAIL = 0.12             # sai depois da última palavra


# ------------------------------------------------------------------ SRT
def fim_util(ini: float, fim: float, texto: str) -> float:
    """O Whisper às vezes estica o fim de uma palavra isolada ("participei" com
    7,8 s) e a cartela fica plantada na tela. Corta em ~0,11 s por letra."""
    return min(fim, ini + min(1.8, max(0.35, 0.11 * len(texto) + 0.30)))


def ler_palavras(segmentos) -> list[tuple[float, float, str]]:
    """Achata os segmentos do faster-whisper em palavras com tempo."""
    palavras = []
    for seg in segmentos:
        for w in (seg.words or []):
            texto = (w.word or "").strip()
            if texto:
                palavras.append((w.start, fim_util(w.start, w.end, texto), texto))
    return palavras


def cartelas(palavras: list[tuple[float, float, str]],
             maximo: int = MAX_PALAVRAS, pausa: float = PAUSA,
             dur_max: float = DUR_MAX, dur_min: float = DUR_MIN
             ) -> list[tuple[float, float, str]]:
    """Agrupa palavras em cartelas que quebram na pausa real, não por proporção."""
    grupos: list[list[tuple[float, float, str]]] = []
    atual: list[tuple[float, float, str]] = []
    for ini, fim, texto in palavras:
        if atual:
            buraco = ini - atual[-1][1]
            longo = (fim - atual[0][0]) > dur_max
            if len(atual) >= maximo or buraco > pausa or longo:
                grupos.append(atual)
                atual = []
        atual.append((ini, fim, texto))
    if atual:
        grupos.append(atual)

    saida: list[tuple[float, float, str]] = []
    for g in grupos:
        ini = max(0.0, g[0][0] - LEAD)
        fim = g[-1][1] + TAIL
        saida.append((ini, fim, " ".join(w[2] for w in g)))

    # entre cartelas: pausa curta a legenda continua na tela; pausa de verdade
    # deixa o quadro limpo. Nunca passa de dur_max + 0,4 na tela.
    for i in range(len(saida) - 1):
        ini, fim, txt = saida[i]
        prox = saida[i + 1][0]
        if prox - fim < 0.35:
            fim = prox - 0.02
        fim = min(fim, ini + dur_max + 0.4)
        if fim - ini < dur_min:
            fim = ini + dur_min
        saida[i] = (ini, min(fim, prox - 0.01), txt)
    if saida:
        ini, fim, txt = saida[-1]
        saida[-1] = (ini, max(fim, ini + dur_min), txt)
    return saida


def _ts(t: float) -> str:
    if t < 0:
        t = 0.0
    h, resto = divmod(t, 3600)
    m, s = divmod(resto, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def escrever_srt(cartelas_: list[tuple[float, float, str]], caminho: str) -> None:
    linhas = []
    for i, (ini, fim, txt) in enumerate(cartelas_, 1):
        linhas.append(f"{i}\n{_ts(ini)} --> {_ts(fim)}\n{txt}\n")
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas))
    os.replace(tmp, caminho)


# --------------------------------------------------------------- modelo
_MODELO = None


def libs_cuda() -> None:
    """cublas/cudnn do venv: o ctranslate2 é compilado contra CUDA 12 e o Arch já
    está no CUDA 13 (`libcublas.so.12 is not found`).

    Exportar LD_LIBRARY_PATH aqui não basta: o loader resolve a busca no início
    do processo, então mexer em `os.environ` depois não muda o dlopen do
    ctranslate2. O que funciona é carregar as .so por caminho absoluto com
    RTLD_GLOBAL antes do import — em seguida o `dlopen("libcublas.so.12")`
    encontra o símbolo já carregado.
    """
    import ctypes
    raiz = os.path.dirname(os.path.abspath(__file__))
    base = os.path.join(raiz, ".venv-asr/lib/python3.11/site-packages/nvidia")
    for pacote in ("cublas", "cudnn"):
        d = os.path.join(base, pacote, "lib")
        if not os.path.isdir(d):
            continue
        os.environ["LD_LIBRARY_PATH"] = d + ":" + os.environ.get("LD_LIBRARY_PATH", "")
        for so in sorted(os.listdir(d)):
            if ".so" not in so:
                continue
            try:
                ctypes.CDLL(os.path.join(d, so), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass            # libs auxiliares com deps ausentes: ignora


def modelo(nome: str = "medium", dispositivo: str = "auto"):
    """Carrega uma vez só: 1,5 GB de pesos não ficam recarregando por vídeo."""
    global _MODELO
    if _MODELO is not None:
        return _MODELO
    libs_cuda()
    from faster_whisper import WhisperModel
    if dispositivo == "auto":
        try:
            import ctranslate2
            dispositivo = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
        except Exception:
            dispositivo = "cpu"
    # float16 estoura os 4 GB da 3050 quando o desktop já ocupa ~1,8 GB
    tipo = "int8_float16" if dispositivo == "cuda" else "int8"
    try:
        _MODELO = WhisperModel(nome, device=dispositivo, compute_type=tipo,
                               cpu_threads=os.cpu_count() or 8)
        print(f"[modelo] {nome} em {dispositivo}/{tipo}", flush=True)
    except Exception as e:
        print(f"[modelo] {dispositivo} falhou ({str(e)[:80]}), caindo para CPU", flush=True)
        _MODELO = WhisperModel(nome, device="cpu", compute_type="int8",
                               cpu_threads=os.cpu_count() or 8)
    return _MODELO


def audio_do_video(video: str) -> str | None:
    """Extrai o áudio para wav 16 kHz mono (o decode do modelo é o gargalo)."""
    alvo = os.path.join("/tmp", f"bcn_asr_{abs(hash(video)) % 10**10}.wav")
    if os.path.exists(alvo):
        return alvo
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-i", video, "-vn", "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", alvo], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(alvo):
        return None
    return alvo


def transcrever(video: str, opcoes: dict) -> dict:
    wav = audio_do_video(video)
    if not wav:
        return {"erro": "sem áudio decodificável"}
    try:
        segs, info = modelo(opcoes["modelo"], opcoes["device"]).transcribe(
            wav, language="pt", beam_size=5, word_timestamps=True,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 300},
            condition_on_previous_text=False, temperature=[0.0, 0.2])
        segmentos = list(segs)          # gerador: tem de consumir aqui
    except Exception as e:
        return {"erro": f"asr: {str(e)[:180]}"}
    finally:
        if opcoes.get("limpar_wav"):
            try:
                os.unlink(wav)
            except OSError:
                pass
    palavras = ler_palavras(segmentos)
    if not palavras:
        return {"erro": "nenhuma palavra reconhecida"}
    return {"palavras": palavras, "duracao": info.duration,
            "texto": " ".join(s.text.strip() for s in segmentos)}


def caminho_saida(video: str, ext: str) -> str:
    """O .srt dos posts vive em `transcricoes/` espelhando o acervo (é de lá que
    `srt_do_post` e `bcnlib.carregar_transcricoes` leem); o dos cortes fica ao
    lado do vídeo."""
    rel = os.path.relpath(video, BASE)
    if rel.split(os.sep)[0] == "_posts":
        return os.path.join(BASE, "transcricoes", os.path.splitext(rel)[0] + ext)
    return os.path.splitext(video)[0] + ext


def gravar(video: str, res: dict, opcoes: dict) -> None:
    """SRT + words.json + txt, movendo o SRT antigo para o arquivo morto."""
    raiz_srt = os.path.splitext(caminho_saida(video, ".srt"))[0]
    os.makedirs(os.path.dirname(raiz_srt), exist_ok=True)
    srt = raiz_srt + ".srt"
    if os.path.exists(srt) and opcoes.get("backup", True):
        rel = os.path.relpath(srt, BASE)
        destino = os.path.join(ANTIGOS, rel)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        shutil.copy2(srt, destino)
    escrever_srt(cartelas(res["palavras"]), srt)
    with open(raiz_srt + ".words.json", "w", encoding="utf-8") as fh:
        json.dump({"video": video, "duracao": res["duracao"],
                   "palavras": [{"a": round(a, 3), "b": round(b, 3), "t": t}
                                for a, b, t in res["palavras"]]},
                  fh, ensure_ascii=False)
    with open(raiz_srt + ".txt", "w", encoding="utf-8") as fh:
        fh.write(res["texto"] + "\n")


# ------------------------------------------------------------------ fila
def carregar_fila() -> dict[str, dict]:
    if not os.path.exists(FILA):
        return {}
    with open(FILA, encoding="utf-8") as fh:
        return {r["video"]: r for r in csv.DictReader(fh)}


def gravar_fila(fila: dict[str, dict]) -> None:
    tmp = FILA + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(sorted(fila.values(), key=lambda r: r["video"]))
    os.replace(tmp, FILA)


def listar(raiz: str, desde: int | None) -> list[str]:
    videos = []
    for pasta, _, arquivos in os.walk(raiz):
        for a in arquivos:
            if a.lower().endswith((".mp4", ".mov", ".m4v")):
                videos.append(os.path.join(pasta, a))
    if desde:
        videos = [v for v in videos if str(desde) in v]
    return sorted(videos)


def regravar(video: str) -> dict | None:
    """Refaz só o .srt a partir do words.json — quando muda a regra da cartela
    não há motivo para passar 20 h de áudio pelo modelo outra vez."""
    alvo = caminho_saida(video, ".words.json")
    if not os.path.exists(alvo):
        return None
    with open(alvo, encoding="utf-8") as fh:
        d = json.load(fh)
    palavras = [(w["a"], fim_util(w["a"], w["b"], w["t"]), w["t"]) for w in d["palavras"]]
    if not palavras:
        return None
    escrever_srt(cartelas(palavras), caminho_saida(video, ".srt"))
    return {"video": os.path.relpath(video, BASE), "status": "ok", "segundos": "0",
            "audio_s": f"{d.get('duracao', 0):.1f}", "erro": ""}


def tarefa(video: str, opcoes: dict) -> dict:
    if opcoes.get("so_srt"):
        r = regravar(video)
        if r:
            return r
        return {"video": os.path.relpath(video, BASE), "status": "erro",
                "segundos": "0", "audio_s": "0", "erro": "sem words.json"}
    rel = os.path.relpath(video, BASE)
    alvo = caminho_saida(video, ".words.json")
    if os.path.exists(alvo) and not opcoes.get("forcar"):
        return {"video": rel, "status": "existente", "segundos": "0",
                "audio_s": "0", "erro": ""}
    inicio = time.time()
    res = transcrever(video, opcoes)
    if "erro" in res:
        return {"video": rel, "status": "erro", "segundos": f"{time.time() - inicio:.1f}",
                "audio_s": "0", "erro": res["erro"]}
    gravar(video, res, opcoes)
    dur = time.time() - inicio
    return {"video": rel, "status": "ok", "segundos": f"{dur:.1f}",
            "audio_s": f"{res['duracao']:.1f}", "erro": ""}


def garantir_venv() -> None:
    """O faster-whisper vive no venv com as libs CUDA 12; se alguém chamar com o
    python do sistema, re-executa no venv em vez de morrer em ImportError."""
    try:
        import faster_whisper  # noqa: F401
        return
    except ImportError:
        pass
    alvo = os.path.join(AQUI, ".venv-asr/bin/python")
    if os.path.exists(alvo) and os.path.realpath(sys.executable) != os.path.realpath(alvo):
        os.execv(alvo, [alvo, os.path.abspath(__file__)] + sys.argv[1:])
    sys.exit("faster-whisper ausente: crie o venv em _reciclagem/.venv-asr")


def limpar_sem_fala() -> None:
    """Vídeo sem fala não pode herdar SRT alucinado pelo Whisper ("Subtítulos por
    la comunidad de Amara.org", "¡Suscríbete!", "por favor" em loop): grava SRT
    vazio, e o projeto nasce sem faixa de legenda em vez de com legenda falsa."""
    fila = carregar_fila()
    zerados = vazios = 0
    for rel, r in fila.items():
        if r["status"] != "erro":
            continue
        video = os.path.join(BASE, rel)
        destino = caminho_saida(video, ".srt")
        r["status"] = "sem_fala"
        if not os.path.exists(destino):
            vazios += 1
            continue
        antigo = open(destino, encoding="utf-8", errors="replace").read().strip()
        if not antigo:
            vazios += 1
            continue
        backup = os.path.join(ANTIGOS, os.path.relpath(destino, BASE))
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.copy2(destino, backup)
        with open(destino, "w", encoding="utf-8"):
            pass
        zerados += 1
    gravar_fila(fila)
    print(f"{zerados} SRT com alucinação zerados · {vazios} já estavam vazios/ausentes")


def main() -> None:
    garantir_venv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--raiz", action="append", default=[], help="_Cortes, _posts…")
    ap.add_argument("--arquivo", action="append", default=[], help="um vídeo (repita)")
    ap.add_argument("--desde", type=int, help="só caminhos que contenham esse ano")
    ap.add_argument("--limite", type=int)
    ap.add_argument("--modelo", default="medium")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--workers", type=int, default=1, help="1 na GPU: 4 GB não cabem 2")
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--sem-backup", action="store_true")
    ap.add_argument("--limpar-sem-fala", action="store_true",
                    help="zera o SRT dos vídeos que ficaram sem fala (alucinação do ASR)")
    ap.add_argument("--so-srt", action="store_true",
                    help="regera o .srt a partir do words.json, sem rodar o modelo")
    a = ap.parse_args()

    if a.limpar_sem_fala:
        limpar_sem_fala()
        return

    videos: list[str] = []
    for r in a.raiz or []:
        raiz = r if os.path.isabs(r) else os.path.join(BASE, r)
        if not os.path.isdir(raiz):
            sys.exit(f"raiz inexistente: {raiz}")
        videos += listar(raiz, a.desde)
    for v in a.arquivo:
        videos.append(v if os.path.isabs(v) else os.path.join(BASE, v))
    videos = sorted(set(videos))
    if a.limite:
        videos = videos[:a.limite]
    if not videos:
        sys.exit("nada para transcrever (--raiz _Cortes | --arquivo <arquivo>)")

    fila = carregar_fila()
    def tem_srt(v: str) -> bool:
        return os.path.exists(os.path.splitext(v)[0] + ".srt")

    if a.so_srt:
        pendentes = [v for v in videos if os.path.exists(caminho_saida(v, ".words.json"))]
    else:
        pendentes = [v for v in videos
                     if a.forcar or not os.path.exists(caminho_saida(v, ".words.json"))]
    print(f"{len(videos)} vídeos · {len(pendentes)} a fazer · "
          f"modelo={a.modelo} device={a.device} workers={a.workers} · "
          f"{'APLICANDO' if a.aplicar else 'DRY-RUN'}")
    if not a.aplicar:
        for v in pendentes[:15]:
            print(f"  {os.path.relpath(v, BASE)}")
        if len(pendentes) > 15:
            print(f"  ... +{len(pendentes) - 15}")
        return

    opcoes = {"modelo": a.modelo, "device": a.device, "so_srt": a.so_srt,
              "backup": not a.sem_backup, "forcar": a.forcar, "limpar_wav": True}
    if a.so_srt:
        print("[--so-srt] refazendo só os .srt a partir do words.json", flush=True)
    else:
        modelo(a.modelo, a.device)          # carrega antes de contar o tempo
    inicio = time.time()
    feitos = audio_s = erros = 0
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        futuros = {pool.submit(tarefa, v, opcoes): v for v in pendentes}
        for fut in as_completed(futuros):
            r = fut.result()
            fila[r["video"]] = r
            feitos += 1
            if r["status"] == "erro":
                erros += 1
                print(f"  ERRO {r['video']}: {r['erro'][:120]}", flush=True)
            elif r["status"] == "ok":
                audio_s += float(r["audio_s"] or 0)
                decorrido = time.time() - inicio
                ritmo = audio_s / decorrido if decorrido else 0
                falta = sum(1 for f in futuros if not f.done())
                eta = (falta * (audio_s / max(feitos, 1)) / ritmo / 60) if ritmo else 0
                print(f"  [{feitos}/{len(pendentes)}] {r['audio_s']}s de áudio em "
                      f"{r['segundos']}s ({ritmo:.1f}x) · ETA {eta:.0f} min · "
                      f"{os.path.basename(r['video'])[:38]}", flush=True)
            if feitos % 10 == 0:
                gravar_fila(fila)
    gravar_fila(fila)
    total = time.time() - inicio
    print(f"\n{feitos - erros} ok · {erros} erros · {audio_s / 60:.1f} min de áudio "
          f"em {total / 60:.1f} min ({audio_s / max(total, 1):.1f}x) · fila: {FILA}")


if __name__ == "__main__":
    main()
