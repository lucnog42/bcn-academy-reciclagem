#!/usr/bin/env python3
"""
silencecut — corte automático de silêncio para o FilmCraft.

Analisa o áudio de um vídeo (ou de um arquivo só de áudio), encontra os
trechos de silêncio conforme o nível (dB) e o tempo mínimo configurados e gera:

  * <nome>.silencecut.otio   timeline OpenTimelineIO para importar no FilmCraft
  * <nome>.cuts.json         lista de cortes (para conferir ou usar em scripts)
  * <nome>.razor.jsonl       comandos `timeline.razor` para o filmcraft-cli
                             (modo "manter": corta no lugar, sem mover nada)
  * opcional: --render       arquivo final renderizado com FFmpeg

Modos:
  join  -> junta os cortes (remove o silêncio e encosta os trechos, ripple)
  keep  -> mantém tudo no mesmo lugar; os silêncios viram clipes
           desativados, gaps ou clipes normais (--silence)

J-cut / L-cut automático (--jl): desloca o ponto de corte do VÍDEO em
relação ao do áudio em cada emenda, sem mexer na fala:
  J-cut -> o áudio do próximo trecho entra antes da imagem
  L-cut -> a imagem do próximo trecho entra antes, o áudio anterior continua
  auto  -> escolhe por emenda, comparando a energia do fim do trecho que sai
           com a do começo do trecho que entra

Requer: Python 3.8+ e ffmpeg/ffprobe no PATH. Sem dependências Python.
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "src"))  # src/

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

VERSION = "1.0.0"
HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

DEFAULTS = {
    "threshold_db": -40.0,      # abaixo disso é silêncio (dBFS, RMS em janelas de 10 ms)
    "auto_threshold": False,    # estima o limiar pelo ruído de fundo
    "auto_offset_db": 10.0,     # limiar = ruído de fundo + offset (no modo auto)
    "min_silence": 0.5,         # silêncio precisa durar pelo menos isso (s) para ser cortado
    "min_clip": 0.20,           # trechos com som mais curtos que isso viram silêncio (cliques, estalos)
    "pad_before": 0.10,         # margem antes da fala (s)
    "pad_after": 0.15,          # margem depois da fala (s)
    "mode": "join",             # join | keep
    "silence": "disable",       # (modo keep) disable | gap | keep
    "jl": "off",                # off | j | l | auto | alternate
    "jl_amount": 0.30,          # deslocamento do J/L (s)
    "jl_window": 0.30,          # janela de energia usada pelo modo auto (s)
    "jl_min_clip": 0.80,        # não aplica J/L em trechos mais curtos que isso (s)
    "audio_stream": 0,          # índice da trilha de áudio usada na análise
    "timeline_offset": 0.0,     # (razor) onde o clipe começa na timeline do FilmCraft (s)
}

PRESET_DIR = HERE / "presets"


def load_preset(name: str) -> dict:
    p = Path(name)
    if not p.suffix:
        p = PRESET_DIR / f"{name}.json"
    if not p.exists():
        avail = ", ".join(sorted(x.stem for x in PRESET_DIR.glob("*.json")))
        sys.exit(f"Preset não encontrado: {name}. Disponíveis: {avail}")
    data = json.loads(p.read_text(encoding="utf-8"))
    unknown = set(data) - set(DEFAULTS) - {"description"}
    if unknown:
        sys.exit(f"Chaves desconhecidas no preset {p}: {', '.join(sorted(unknown))}")
    return {k: v for k, v in data.items() if k in DEFAULTS}


# ---------------------------------------------------------------------------
# FFmpeg helpers
# ---------------------------------------------------------------------------

def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        sys.exit(f"'{tool}' não encontrado no PATH. Instale o FFmpeg (ex.: sudo pacman -S ffmpeg).")
    return path


@dataclass
class MediaInfo:
    path: Path
    duration: float
    has_video: bool
    fps: float
    fps_num: int
    fps_den: int
    has_audio: bool
    sample_rate: int
    width: int = 0
    height: int = 0


def probe(path: Path, audio_stream: int) -> MediaInfo:
    out = subprocess.run(
        [need("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"ffprobe falhou em {path}:\n{out.stderr}")
    info = json.loads(out.stdout)
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    auds = [s for s in streams if s.get("codec_type") == "audio"]
    if not auds:
        sys.exit(f"{path.name}: sem trilha de áudio, não há o que analisar.")
    if audio_stream >= len(auds):
        sys.exit(f"{path.name}: só tem {len(auds)} trilha(s) de áudio (pedido índice {audio_stream}).")
    a = auds[audio_stream]
    dur = float(info.get("format", {}).get("duration") or a.get("duration") or 0)
    num, den = 30, 1
    if v:
        rate = v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1"
        if rate in ("0/0", "0/1"):
            rate = v.get("r_frame_rate", "30/1")
        n, d = (int(x) for x in rate.split("/"))
        if n > 0 and d > 0:
            num, den = n, d
    return MediaInfo(
        path=path, duration=dur, has_video=v is not None,
        fps=num / den, fps_num=num, fps_den=den, has_audio=True,
        sample_rate=int(a.get("sample_rate") or 48000),
        width=int(v.get("width", 0)) if v else 0,
        height=int(v.get("height", 0)) if v else 0,
    )


def ffmpeg_major() -> int:
    out = subprocess.run([need("ffmpeg"), "-version"], capture_output=True, text=True).stdout
    m = re.search(r"ffmpeg version n?(\d+)", out)
    return int(m.group(1)) if m else 6


WIN = 0.01  # janela de análise (10 ms)


def envelope(path: Path, audio_stream: int) -> List[float]:
    """RMS em dBFS a cada 10 ms (mono, 16 kHz). Uma passada do FFmpeg, sem numpy."""
    with tempfile.TemporaryDirectory() as td:
        meta = Path(td) / "env.txt"
        # escapa o caminho para dentro do filtergraph
        fpath = str(meta).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        af = (
            "aformat=channel_layouts=mono,aresample=16000,"
            "asetnsamples=n=160:p=0,"
            "astats=metadata=1:reset=1:measure_overall=RMS_level:measure_perchannel=none,"
            f"ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file='{fpath}'"
        )
        r = subprocess.run(
            [need("ffmpeg"), "-nostdin", "-hide_banner", "-nostats", "-loglevel", "error",
             "-i", str(path), "-map", f"0:a:{audio_stream}", "-af", af, "-f", "null", "-"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            sys.exit(f"FFmpeg falhou ao analisar {path.name}:\n{r.stderr}")
        vals = []
        for line in meta.read_text().splitlines():
            if line.startswith("lavfi.astats.Overall.RMS_level="):
                s = line.split("=", 1)[1].strip()
                try:
                    x = float(s)
                except ValueError:
                    x = -120.0
                if math.isinf(x) or math.isnan(x):
                    x = -120.0
                vals.append(max(x, -120.0))
    return vals


def percentile(vals: List[float], p: float) -> float:
    s = sorted(vals)
    if not s:
        return -120.0
    k = (len(s) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)


# ---------------------------------------------------------------------------
# Detecção
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    """Trecho com fala, em segundos de origem (já com margens e quantizado)."""
    start: float
    end: float
    v_start: float = 0.0   # início do vídeo (após J/L)
    v_end: float = 0.0     # fim do vídeo (após J/L)
    jl_out: str = ""       # tipo de emenda na saída deste trecho: "J", "L" ou ""
    jl_shift: float = 0.0  # deslocamento aplicado nessa emenda (s)

    @property
    def dur(self) -> float:
        return self.end - self.start


def detect(env: List[float], cfg: dict, duration: float) -> tuple[list[tuple[float, float]], float]:
    """Retorna regiões com som (sem margem) e o limiar usado."""
    thr = cfg["threshold_db"]
    if cfg["auto_threshold"]:
        floor = percentile(env, 0.10)
        loud = percentile(env, 0.95)
        thr = floor + cfg["auto_offset_db"]
        if loud - 6 > floor:          # nunca acima do nível da fala
            thr = min(thr, loud - 6)
    loud_flags = [x > thr for x in env]

    # regiões com som
    regions = []
    i, n = 0, len(loud_flags)
    while i < n:
        if loud_flags[i]:
            j = i
            while j < n and loud_flags[j]:
                j += 1
            regions.append([i * WIN, min(j * WIN, duration)])
            i = j
        else:
            i += 1

    # preenche silêncios curtos (não cortáveis)
    merged: list[list[float]] = []
    for r in regions:
        if merged and r[0] - merged[-1][1] < cfg["min_silence"]:
            merged[-1][1] = r[1]
        else:
            merged.append(r)

    # descarta "blips" curtos (estalos, respiração forte isolada)
    merged = [r for r in merged if r[1] - r[0] >= cfg["min_clip"]]
    return [(a, b) for a, b in merged], thr


def build_segments(regions, cfg, info: MediaInfo) -> List[Segment]:
    fps = info.fps if info.has_video else 1000.0

    def q(t: float) -> float:
        return round(t * fps) / fps

    segs: List[Segment] = []
    for a, b in regions:
        s = max(0.0, a - cfg["pad_before"])
        e = min(info.duration, b + cfg["pad_after"])
        s, e = q(s), q(e)
        if e > info.duration:
            e = math.floor(info.duration * fps) / fps
        if segs and s <= segs[-1].end + 0.5 / fps:
            segs[-1].end = max(segs[-1].end, e)
        elif e - s >= 1.0 / fps:
            segs.append(Segment(s, e))
    for sg in segs:
        sg.v_start, sg.v_end = sg.start, sg.end
    return segs


def mean_db(env: List[float], t0: float, t1: float) -> float:
    i0, i1 = max(0, int(t0 / WIN)), min(len(env), int(math.ceil(t1 / WIN)))
    if i1 <= i0:
        return -120.0
    # média em potência, não em dB
    p = sum(10 ** (x / 10) for x in env[i0:i1]) / (i1 - i0)
    return 10 * math.log10(p) if p > 0 else -120.0


def apply_jl(segs: List[Segment], regions, env, cfg, info: MediaInfo) -> None:
    """Desloca os pontos de corte do vídeo em cada emenda. O áudio não muda."""
    mode = cfg["jl"]
    if mode == "off" or not info.has_video or len(segs) < 2:
        return
    fps = info.fps
    frame = 1.0 / fps
    toggle = True
    for i in range(len(segs) - 1):
        a, b = segs[i], segs[i + 1]
        gap = b.start - a.end
        if gap < frame or a.dur < cfg["jl_min_clip"] or b.dur < cfg["jl_min_clip"]:
            continue
        # quanto dá para deslocar sem repetir imagem e sem engolir o trecho
        d = min(cfg["jl_amount"], gap, 0.4 * (a.v_end - a.v_start), 0.4 * (b.v_end - b.v_start))
        d = math.floor(d * fps + 1e-6) / fps
        if d < frame:
            continue
        if mode == "j":
            kind = "J"
        elif mode == "l":
            kind = "L"
        elif mode == "alternate":
            kind = "J" if toggle else "L"
            toggle = not toggle
        else:  # auto
            w = cfg["jl_window"]
            tail = mean_db(env, a.end - cfg["pad_after"] - w, a.end - cfg["pad_after"])
            head = mean_db(env, b.start + cfg["pad_before"], b.start + cfg["pad_before"] + w)
            # começo do próximo mais forte -> deixa ouvir antes de ver (J)
            # fim do atual mais forte -> deixa a fala "respirar" sobre a próxima imagem (L)
            kind = "J" if head >= tail else "L"
        if kind == "J":
            # imagem do trecho atual estica para dentro do silêncio,
            # imagem do próximo começa d depois (áudio dele já está tocando)
            a.v_end += d
            b.v_start += d
        else:
            # imagem do próximo entra d antes, áudio do atual continua
            a.v_end -= d
            b.v_start -= d
        a.v_end, b.v_start = round(a.v_end * fps) / fps, round(b.v_start * fps) / fps
        a.jl_out, a.jl_shift = kind, d


# ---------------------------------------------------------------------------
# Timeline (modelo intermediário)
# ---------------------------------------------------------------------------

@dataclass
class Item:
    kind: str            # "clip" | "gap"
    src_in: float = 0.0
    src_out: float = 0.0
    enabled: bool = True
    name: str = ""

    @property
    def dur(self) -> float:
        return self.src_out - self.src_in


def build_tracks(segs: List[Segment], cfg, info: MediaInfo) -> dict:
    tracks = {"video": [], "audio": []}
    D = info.duration
    fps = info.fps if info.has_video else 1000.0
    D = math.floor(D * fps + 1e-6) / fps

    if cfg["mode"] == "join":
        for k, s in enumerate(segs, 1):
            tracks["audio"].append(Item("clip", s.start, s.end, True, f"Fala {k}"))
            if info.has_video:
                tracks["video"].append(Item("clip", s.v_start, s.v_end, True, f"Fala {k}"))
    else:  # keep
        sil = cfg["silence"]

        def silence_item(t0, t1, name):
            if t1 - t0 <= 1e-9:
                return None
            if sil == "gap":
                return Item("gap", t0, t1, True, name)
            return Item("clip", t0, t1, sil == "keep", name)

        for track, key_s, key_e in (("audio", "start", "end"), ("video", "v_start", "v_end")):
            if track == "video" and not info.has_video:
                continue
            t = 0.0
            for k, s in enumerate(segs, 1):
                st, en = getattr(s, key_s), getattr(s, key_e)
                it = silence_item(t, st, f"Silêncio {k}")
                if it:
                    tracks[track].append(it)
                tracks[track].append(Item("clip", st, en, True, f"Fala {k}"))
                t = en
            it = silence_item(t, D, "Silêncio final")
            if it:
                tracks[track].append(it)
    return tracks


# ---------------------------------------------------------------------------
# Saídas
# ---------------------------------------------------------------------------

def _rt(seconds: float, rate: float) -> dict:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": round(seconds * rate, 6)}


def _tr(start: float, dur: float, rate: float) -> dict:
    return {"OTIO_SCHEMA": "TimeRange.1", "start_time": _rt(start, rate), "duration": _rt(dur, rate)}


def write_otio(tracks: dict, info: MediaInfo, cfg, out: Path) -> None:
    rate = info.fps if info.has_video else 1000.0
    url = info.path.resolve().as_uri()
    avail = _tr(0.0, math.floor(info.duration * rate + 1e-6) / rate, rate)

    def ref():
        return {
            "OTIO_SCHEMA": "ExternalReference.1", "name": info.path.name,
            "target_url": url, "available_range": avail,
            "available_image_bounds": None, "metadata": {},
        }

    def item_json(it: Item) -> dict:
        if it.kind == "gap":
            return {"OTIO_SCHEMA": "Gap.1", "name": it.name, "source_range": _tr(0, it.dur, rate),
                    "effects": [], "markers": [], "enabled": True, "metadata": {}}
        return {
            "OTIO_SCHEMA": "Clip.2", "name": it.name,
            "source_range": _tr(it.src_in, it.dur, rate),
            "media_references": {"DEFAULT_MEDIA": ref()},
            "active_media_reference_key": "DEFAULT_MEDIA",
            "effects": [], "markers": [], "enabled": it.enabled,
            "metadata": {"silencecut": {"src_in_s": it.src_in, "src_out_s": it.src_out}},
        }

    children = []
    for key, kind, nm in (("video", "Video", "V1"), ("audio", "Audio", "A1")):
        if tracks[key]:
            children.append({
                "OTIO_SCHEMA": "Track.1", "name": nm, "kind": kind,
                "children": [item_json(i) for i in tracks[key]],
                "source_range": None, "effects": [], "markers": [], "enabled": True, "metadata": {},
            })
    tl = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": f"{info.path.stem} — silencecut ({cfg['mode']})",
        "global_start_time": None,
        "metadata": {"silencecut": {"version": VERSION, "settings": cfg}},
        "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": children,
                   "source_range": None, "effects": [], "markers": [], "enabled": True, "metadata": {}},
    }
    out.write_text(json.dumps(tl, indent=2, ensure_ascii=False), encoding="utf-8")


def write_razor(segs: List[Segment], info: MediaInfo, cfg, out: Path) -> int:
    """Comandos timeline.razor nos limites (modo manter no lugar)."""
    off = cfg["timeline_offset"]
    times = set()
    for s in segs:
        for t in (s.start, s.end):
            if 0 < t < info.duration:
                times.add(round(t + off, 6))
    lines = [json.dumps({"id": "timeline.razor", "params": {"seconds": t}}) for t in sorted(times)]
    out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


def write_cuts(segs, regions, thr, info: MediaInfo, cfg, out: Path) -> None:
    data = {
        "source": str(info.path.resolve()),
        "duration": info.duration,
        "fps": info.fps if info.has_video else None,
        "threshold_db_used": None if thr != thr else round(thr, 2),
        "settings": cfg,
        "speech_segments": [asdict(s) for s in segs],
        "kept_seconds": round(sum(s.dur for s in segs), 3),
        "removed_seconds": round(info.duration - sum(s.dur for s in segs), 3),
    }
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _between(ranges, eps: float) -> str:
    return "+".join(f"between(t\\,{a + eps:.6f}\\,{b - eps:.6f})" for a, b in ranges) or "0"


def render(segs: List[Segment], tracks: dict, info: MediaInfo, cfg, out: Path, extra: dict) -> None:
    ff = need("ffmpeg")
    audio_only_out = out.suffix.lower() in (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus")
    use_video = info.has_video and not audio_only_out
    sr = info.sample_rate
    parts = []

    if cfg["mode"] == "join":
        frame = 1.0 / info.fps if info.has_video else 0.001
        a_ranges = [(i.src_in, i.src_out) for i in tracks["audio"]]
        # áudio: quebra em blocos de 1 ms para o aselect ser preciso
        parts.append(
            f"[0:a:{cfg['audio_stream']}]asetnsamples=n={max(1, sr // 1000)}:p=0,"
            f"aselect='{_between(a_ranges, 0.0)}',asetpts=N/SR/TB[aout]"
        )
        if use_video:
            v_ranges = [(i.src_in, i.src_out) for i in tracks["video"]]
            # meio frame de tolerância para pegar exatamente os frames do intervalo [in, out)
            sel = "+".join(
                f"between(t\\,{a - frame / 2:.6f}\\,{b - frame / 2:.6f})" for a, b in v_ranges
            )
            parts.append(f"[0:v:0]select='{sel}',setpts=N/FRAME_RATE/TB[vout]")
    else:
        sil = cfg["silence"]
        if sil == "keep":
            parts.append(f"[0:a:{cfg['audio_stream']}]anull[aout]")
        else:
            mute = [(i.src_in, i.src_out) for i in tracks["audio"] if i.kind == "gap" or not i.enabled]
            parts.append(
                f"[0:a:{cfg['audio_stream']}]volume=volume=0:enable='{_between(mute, 0.0)}'[aout]"
            )
        if use_video:
            parts.append("[0:v:0]null[vout]")

    graph = ";\n".join(parts)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write(graph)
        script = fh.name
    try:
        fc_flag = ["-/filter_complex", script] if ffmpeg_major() >= 7 else ["-filter_complex_script", script]
        cmd = [ff, "-nostdin", "-hide_banner", "-y", "-i", str(info.path), *fc_flag]
        if use_video:
            cmd += ["-map", "[vout]"]
        cmd += ["-map", "[aout]"]
        if use_video:
            cmd += ["-c:v", extra.get("vcodec") or "libx264"]
            if (extra.get("vcodec") or "libx264") in ("libx264", "libx265"):
                cmd += ["-crf", str(extra.get("crf", 18)), "-preset", "medium", "-pix_fmt", "yuv420p"]
            cmd += ["-fps_mode", "cfr", "-r", f"{info.fps_num}/{info.fps_den}"]
        if extra.get("acodec"):
            cmd += ["-c:a", extra["acodec"]]
        elif out.suffix.lower() in (".mp4", ".mov", ".m4a", ".mkv"):
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-ar", str(sr), str(out)]
        print(f"  renderizando -> {out.name} ...", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"FFmpeg falhou ao renderizar:\n{r.stderr[-3000:]}")
    finally:
        os.unlink(script)


# ---------------------------------------------------------------------------
# Integração com o filmcraft-cli
# ---------------------------------------------------------------------------

def filmcraft_apply(project: Path, otio: Path, razor: Path, cfg, cli: str) -> None:
    exe = shutil.which(cli) or cli
    if not Path(exe).exists() and not shutil.which(exe):
        sys.exit(f"filmcraft-cli não encontrado ({cli}). Use --filmcraft-cli /caminho/filmcraft-cli.")
    if cfg["mode"] == "keep" and cfg["jl"] == "off" and cfg["silence"] == "keep":
        # só lâminas na sequência ativa do projeto
        cmd = [exe, "--project", str(project), "--save", "run", "-"]
        with open(razor, "rb") as fh:
            r = subprocess.run(cmd, stdin=fh, capture_output=True, text=True)
        what = "cortes (razor) aplicados na sequência ativa"
    else:
        cmd = [exe, "--project", str(project), "--save", "import", str(otio.resolve())]
        r = subprocess.run(cmd, capture_output=True, text=True)
        what = "timeline OTIO importada como nova sequência"
    if r.returncode != 0:
        sys.exit(f"filmcraft-cli falhou ({' '.join(cmd)}):\n{r.stdout}\n{r.stderr}")
    print(f"  FilmCraft: {what} em {project.name}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def fmt(t: float) -> str:
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    return f"{h:d}:{m:02d}:{s:06.3f}" if h else f"{m:d}:{s:06.3f}"


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="silencecut",
        description="Corta áudio/vídeo por silêncio e gera timeline para o FilmCraft (OTIO), "
                    "comandos razor para o filmcraft-cli e/ou um render pronto.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exemplos:\n"
               "  silencecut.py entrevista.mp4\n"
               "  silencecut.py entrevista.mp4 --preset podcast --jl auto --render final.mp4\n"
               "  silencecut.py aula.mp4 --mode keep --silence disable\n"
               "  silencecut.py *.mp4 -t -35 --min-silence 0.4 --pad 0.12\n"
               "  silencecut.py locucao.wav --render locucao_cortada.wav\n",
    )
    p.add_argument("inputs", nargs="+", type=Path, help="arquivos de vídeo ou áudio")
    p.add_argument("--preset", help="nome em presets/ ou caminho de um .json")
    g = p.add_argument_group("detecção")
    g.add_argument("-t", "--threshold-db", type=float, help="nível de silêncio em dBFS (padrão -40)")
    g.add_argument("--auto-threshold", action="store_true", default=None,
                   help="estima o limiar pelo ruído de fundo")
    g.add_argument("--auto-offset-db", type=float, help="dB acima do ruído de fundo (padrão 10)")
    g.add_argument("-s", "--min-silence", type=float, help="tempo mínimo de silêncio para cortar, s (0.5)")
    g.add_argument("--min-clip", type=float, help="descarta sons isolados mais curtos que isso, s (0.2)")
    g.add_argument("--pad", type=float, help="margem antes e depois da fala, s")
    g.add_argument("--pad-before", type=float, help="margem antes da fala, s (0.10)")
    g.add_argument("--pad-after", type=float, help="margem depois da fala, s (0.15)")
    g.add_argument("--audio-stream", type=int, help="trilha de áudio usada na análise (0)")
    g.add_argument("--regioes", type=Path,
                   help="JSON [[início, fim], ...] com onde há fala (ex.: das palavras do "
                        "Whisper); substitui a detecção por nível")
    e = p.add_argument_group("edição")
    e.add_argument("-m", "--mode", choices=["join", "keep"],
                   help="join = junta os cortes; keep = mantém no mesmo lugar")
    e.add_argument("--silence", choices=["disable", "gap", "keep"],
                   help="(keep) silêncio vira clipe desativado, gap, ou clipe normal")
    e.add_argument("--jl", choices=["off", "j", "l", "auto", "alternate"], help="J/L-cut automático")
    e.add_argument("--jl-amount", type=float, help="deslocamento do J/L, s (0.30)")
    e.add_argument("--jl-min-clip", type=float, help="trecho mínimo para receber J/L, s (0.8)")
    o = p.add_argument_group("saída")
    o.add_argument("-o", "--out-dir", type=Path, help="pasta de saída (padrão: ao lado do arquivo)")
    o.add_argument("--render", type=Path,
                   help="renderiza com FFmpeg (.mp4/.mov/.mkv ou .wav/.mp3/.m4a/.flac); "
                        "com vários arquivos, use uma pasta")
    o.add_argument("--crf", type=int, default=18, help="qualidade x264 no render (18)")
    o.add_argument("--vcodec", help="codec de vídeo do render (libx264)")
    o.add_argument("--acodec", help="codec de áudio do render")
    o.add_argument("--timeline-offset", type=float,
                   help="(razor) início do clipe na timeline do FilmCraft, s")
    o.add_argument("--dry-run", action="store_true", help="só mostra o resumo, não grava nada")
    f = p.add_argument_group("FilmCraft")
    f.add_argument("--filmcraft-project", type=Path,
                   help="aplica direto num projeto .fcproj via filmcraft-cli")
    f.add_argument("--filmcraft-cli", default="filmcraft-cli", help="caminho do filmcraft-cli")
    p.add_argument("--version", action="version", version=f"silencecut {VERSION}")
    return p.parse_args(argv)


def resolve_cfg(a) -> dict:
    cfg = dict(DEFAULTS)
    if a.preset:
        cfg.update(load_preset(a.preset))
    m = {
        "threshold_db": a.threshold_db, "auto_threshold": a.auto_threshold,
        "auto_offset_db": a.auto_offset_db, "min_silence": a.min_silence, "min_clip": a.min_clip,
        "pad_before": a.pad_before if a.pad_before is not None else a.pad,
        "pad_after": a.pad_after if a.pad_after is not None else a.pad,
        "audio_stream": a.audio_stream, "mode": a.mode, "silence": a.silence, "jl": a.jl,
        "jl_amount": a.jl_amount, "jl_min_clip": a.jl_min_clip, "timeline_offset": a.timeline_offset,
    }
    cfg.update({k: v for k, v in m.items() if v is not None})
    for k in ("min_silence", "min_clip", "pad_before", "pad_after", "jl_amount"):
        if cfg[k] < 0:
            sys.exit(f"{k} não pode ser negativo")
    return cfg


def process(path: Path, cfg: dict, a) -> None:
    if not path.exists():
        print(f"! não encontrado: {path}", file=sys.stderr)
        return
    info = probe(path, cfg["audio_stream"])
    print(f"\n▶ {path.name}  ({fmt(info.duration)}"
          + (f", {info.fps:.3f} fps" if info.has_video else ", só áudio") + ")")
    env = envelope(path, cfg["audio_stream"])
    if getattr(a, "regioes", None):
        regs = json.loads(Path(a.regioes).read_text(encoding="utf-8"))
        regions = [(max(0.0, float(x)), min(info.duration, float(y))) for x, y in regs if y > x]
        thr = float("nan")
    else:
        regions, thr = detect(env, cfg, info.duration)
    segs = build_segments(regions, cfg, info)
    if not segs:
        print(f"  nenhum trecho acima de {thr:.1f} dB — tudo é silêncio? Ajuste -t ou use --auto-threshold.")
        return
    if cfg["jl"] != "off" and not info.has_video:
        print("  (J/L ignorado: arquivo só de áudio)")
    apply_jl(segs, regions, env, cfg, info)
    tracks = build_tracks(segs, cfg, info)

    kept = sum(s.dur for s in segs)
    nj = sum(1 for s in segs if s.jl_out == "J")
    nl = sum(1 for s in segs if s.jl_out == "L")
    print(("  detecção pela fala" if thr != thr else f"  limiar {thr:.1f} dB") + f" | {len(segs)} trechos de fala | "
          f"mantém {fmt(kept)} | remove {fmt(info.duration - kept)} "
          f"({100 * (1 - kept / info.duration):.0f}%)"
          + (f" | J-cuts {nj}, L-cuts {nl}" if nj + nl else ""))
    if a.dry_run:
        for k, s in enumerate(segs[:40], 1):
            print(f"   {k:3d}  {fmt(s.start)} → {fmt(s.end)}" + (f"  [{s.jl_out} {s.jl_shift:.2f}s]" if s.jl_out else ""))
        if len(segs) > 40:
            print(f"   ... +{len(segs) - 40}")
        return

    out_dir = a.out_dir or path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / path.stem
    otio = base.with_name(base.name + ".silencecut.otio")
    cuts = base.with_name(base.name + ".cuts.json")
    razor = base.with_name(base.name + ".razor.jsonl")
    write_otio(tracks, info, cfg, otio)
    write_cuts(segs, regions, thr, info, cfg, cuts)
    n = write_razor(segs, info, cfg, razor)
    print(f"  OTIO  -> {otio}")
    print(f"  cortes-> {cuts}")
    print(f"  razor -> {razor} ({n} cortes)")

    if a.render:
        r = a.render
        if len(a.inputs) > 1 or r.is_dir() or not r.suffix:
            r.mkdir(parents=True, exist_ok=True)
            ext = path.suffix if info.has_video else ".wav"
            r = r / f"{path.stem}_cortado{ext}"
        render(segs, tracks, info, cfg, r,
               {"crf": a.crf, "vcodec": a.vcodec, "acodec": a.acodec})
        print(f"  render-> {r}")

    if a.filmcraft_project:
        filmcraft_apply(a.filmcraft_project, otio, razor, cfg, a.filmcraft_cli)


def main(argv=None):
    a = parse_args(argv)
    need("ffmpeg"), need("ffprobe")
    cfg = resolve_cfg(a)
    print(f"silencecut {VERSION} | modo {cfg['mode']}"
          + (f" ({cfg['silence']})" if cfg["mode"] == "keep" else "")
          + f" | J/L {cfg['jl']} | "
          + ("limiar auto" if cfg["auto_threshold"] else f"limiar {cfg['threshold_db']} dB")
          + f" | silêncio ≥ {cfg['min_silence']}s | margem {cfg['pad_before']}/{cfg['pad_after']}s")
    for path in a.inputs:
        process(path, cfg, a)


if __name__ == "__main__":
    main()
