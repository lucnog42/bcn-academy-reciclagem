#!/usr/bin/env python3
"""Vídeo gerado por IA (OpenRouter) para um momento do item: um b-roll que entra por cima do
vídeo no tempo do momento, com o som original continuando por baixo.

Usa a chave própria do vídeo (`[segredos] video_openrouter_api_key`), separada da IA das sugestões. O pedido é assíncrono: o job é
enviado, consultado a cada 10 s e, pronto, baixado para `_motion/prontos/<id>.mp4` — de onde o
plugin Inserir motion o coloca no projeto, como os motions do Claude.

    python3 video_ia.py modelos
    python3 video_ia.py gerar <pasta> <id> --modelo google/veo-3.1 --prompt "..." [--duracao 5]
        [--resolucao 720p] [--formato 9:16] [--refs primeiro_quadro|referencias|nenhuma] [--audio]
    python3 video_ia.py continuar <pasta> <id>      # retoma um job que ficou no meio

Endpoints (docs do OpenRouter): POST /api/v1/videos, GET /api/v1/videos/{id},
GET /api/v1/videos/{id}/content, GET /api/v1/videos/models.
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import base64
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
from nucleo import config  # noqa: E402
from plano import momentos  # noqa: E402

API = os.environ.get("NG3_OPENROUTER_API", "https://openrouter.ai/api/v1")   # trocado só em teste
ESPERA = float(os.environ.get("NG3_VIDEO_ESPERA", 10))   # s entre consultas
LIMITE = 20 * 60     # desiste de esperar depois de 20 min (o job continua no OpenRouter)


def _chave() -> str:
    c = config.chave("video")
    if not c:
        raise RuntimeError("sem a chave do vídeo: no botão da IA (topo do painel), em "
                           "\"Vídeo com IA (OpenRouter)\", cole a chave e salve")
    return c


def _req(metodo: str, url: str, corpo: dict | None = None, binario: bool = False):
    h = {"Authorization": f"Bearer {_chave()}", "X-Title": "video-automation-ng3"}
    dados = None
    if corpo is not None:
        h["content-type"] = "application/json"
        dados = json.dumps(corpo).encode()
    req = urllib.request.Request(url, data=dados, headers=h, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=300 if binario else 60) as r:
            return r.read() if binario else json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenRouter {e.code}: {e.read().decode(errors='replace')[:500]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"sem conexão com o OpenRouter: {e.reason}")


# ------------------------------------------------------------------ modelos
def modelos() -> list[dict]:
    """Os modelos de vídeo, com o que cada um aceita e o preço, em cache por 6 h."""
    cache = os.path.join(config.carregar()["app"]["cache"], "video_modelos.json")
    try:
        if time.time() - os.path.getmtime(cache) < 6 * 3600:
            with open(cache, encoding="utf-8") as fh:
                return json.load(fh)
    except OSError:
        pass
    dados = _req("GET", f"{API}/videos/models").get("data") or []
    out = [{"id": m["id"], "nome": m.get("name") or m["id"],
            "duracoes": m.get("supported_durations") or [],
            "resolucoes": m.get("supported_resolutions") or [],
            "formatos": m.get("supported_aspect_ratios") or [],
            "quadros": m.get("supported_frame_images") or [],
            "audio": bool(m.get("generate_audio")),
            "precos": m.get("pricing_skus") or {}} for m in dados]
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out


# ------------------------------------------------------------------ prompt e imagens
def prompt_inicial(pasta: str, s: dict) -> str:
    """Um ponto de partida para o prompt: o que o momento diz + o contexto do item."""
    ctx = momentos.ler_contexto(pasta).get("texto", "").strip()
    from nucleo import config
    partes = [f"B-roll para um vídeo da marca ({config.descricao_marca()}), no momento em que a fala diz: "
              f"\"{s.get('texto', '').strip()}\"."]
    if s.get("apoio"):
        partes.append(s["apoio"].strip() + ".")
    if ctx:
        partes.append(f"Contexto: {ctx}")
    partes.append("Cena realista e cinematográfica, câmera em movimento suave, luz natural, "
                  "sem texto, sem logos, sem legendas na imagem.")
    estilo = config.carregar()["estilo"].get("linha")
    if estilo:
        partes.append(f"Estilo: {estilo}")
    return " ".join(partes)


def _data_uri(caminho_rel: str, px: int = 1280) -> str:
    from acervo import midia
    jpg = midia.miniatura(momentos._abs(caminho_rel), px)
    with open(jpg, "rb") as fh:
        return "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode()


def _salvar_job(pasta: str, sid: str, info: dict) -> dict:
    def mudar(s: dict) -> None:
        s["video_ia"] = {**(s.get("video_ia") or {}), **info}
    return momentos._mudar_momento(pasta, sid, mudar)


# ------------------------------------------------------------------ gerar
def gerar(pasta: str, sid: str, modelo: str, prompt: str, duracao: int | None = None,
          resolucao: str | None = None, formato: str = "9:16", refs: str = "primeiro_quadro",
          audio: bool = False) -> str:
    s = next((x for x in momentos.ler_sugestoes(pasta).get("itens", []) if x["id"] == sid), None)
    if s is None:
        raise ValueError("momento não encontrado")
    corpo: dict = {"model": modelo, "prompt": prompt.strip() or prompt_inicial(pasta, s),
                   "aspect_ratio": formato, "generate_audio": bool(audio)}
    if duracao:
        corpo["duration"] = int(duracao)
    if resolucao:
        corpo["resolution"] = resolucao
    imagens = [r for r in (s.get("referencias") or []) if os.path.exists(momentos._abs(r))]
    if refs == "primeiro_quadro" and imagens:
        corpo["frame_images"] = [{"type": "image_url", "image_url": {"url": _data_uri(imagens[0])},
                                  "frame_type": "first_frame"}]
    elif refs == "referencias" and imagens:
        corpo["input_references"] = [{"type": "image_url", "image_url": {"url": _data_uri(r)}}
                                     for r in imagens[:4]]
    print(f"▶ enviando a {modelo}: {formato}, {duracao or 'duração do modelo'} s, "
          f"{resolucao or 'resolução do modelo'}, imagens: "
          f"{len(corpo.get('frame_images') or corpo.get('input_references') or [])}", flush=True)
    r = _req("POST", f"{API}/videos", corpo)
    job = r.get("id")
    if not job:
        raise RuntimeError(f"resposta sem id: {json.dumps(r)[:300]}")
    _salvar_job(pasta, sid, {"job": job, "modelo": modelo, "prompt": corpo["prompt"], "status": "pending",
                             "enviado_em": dt.datetime.now().isoformat(timespec="seconds"), "erro": ""})
    print(f"  job {job}", flush=True)
    return esperar(pasta, sid, job)


def esperar(pasta: str, sid: str, job: str) -> str:
    inicio, ultimo = time.time(), ""
    while True:
        r = _req("GET", f"{API}/videos/{job}")
        st = r.get("status", "")
        if st != ultimo:
            print(f"  {dt.datetime.now():%H:%M:%S} {st}", flush=True)
            _salvar_job(pasta, sid, {"status": st})
            ultimo = st
        if st == "completed":
            break
        if st in ("failed", "cancelled", "expired"):
            erro = json.dumps(r.get("error") or st, ensure_ascii=False)[:300]
            _salvar_job(pasta, sid, {"erro": erro})
            raise RuntimeError(f"o OpenRouter não gerou o vídeo: {erro}")
        if time.time() - inicio > LIMITE:
            raise RuntimeError(f"ainda não ficou pronto em {LIMITE // 60} min; "
                               f"rode 'continuar' depois (job {job})")
        time.sleep(ESPERA)
    os.makedirs(momentos.PRONTOS, exist_ok=True)
    alvo = os.path.join(momentos.PRONTOS, f"{sid}.mp4")
    if os.path.exists(alvo):                     # gerou de novo: o anterior fica guardado
        os.replace(alvo, os.path.join(momentos.PRONTOS, f"{sid}.{dt.datetime.now():%Y%m%d-%H%M%S}.mp4.antigo"))
    dados = _req("GET", f"{API}/videos/{job}/content?index=0", binario=True)
    with open(alvo, "wb") as fh:
        fh.write(dados)
    custo = (r.get("usage") or {}).get("cost")

    def pronto(s: dict) -> None:
        s["status"] = "pronto"
        s["video_ia"] = {**(s.get("video_ia") or {}), "status": "completed", "custo": custo,
                         "arquivo": momentos._rel(alvo)}
    momentos._mudar_momento(pasta, sid, pronto)
    # o vídeo gerado não precisa do Claude: sai da fila dos filmes Motion
    momentos._gravar(momentos.FILA, [p for p in momentos.ler_fila() if p["id"] != sid])
    print(f"pronto: {momentos._rel(alvo)}" + (f" · custo US$ {custo}" if custo is not None else ""), flush=True)
    return alvo


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("modelos")
    g = sub.add_parser("gerar")
    g.add_argument("pasta")
    g.add_argument("id")
    g.add_argument("--modelo", required=True)
    g.add_argument("--prompt", default="")
    g.add_argument("--duracao", type=int)
    g.add_argument("--resolucao")
    g.add_argument("--formato", default="9:16")
    g.add_argument("--refs", default="primeiro_quadro", choices=["primeiro_quadro", "referencias", "nenhuma"])
    g.add_argument("--audio", action="store_true")
    c = sub.add_parser("continuar")
    c.add_argument("pasta")
    c.add_argument("id")
    a = ap.parse_args()
    try:
        if a.cmd == "modelos":
            for m in modelos():
                print(f"{m['id']:<40} {m['duracoes']} {m['resolucoes']} {m['formatos']} {m['precos']}")
        elif a.cmd == "gerar":
            gerar(a.pasta, a.id, a.modelo, a.prompt, a.duracao, a.resolucao, a.formato, a.refs, a.audio)
        else:
            s = next(x for x in momentos.ler_sugestoes(a.pasta)["itens"] if x["id"] == a.id)
            esperar(a.pasta, a.id, s["video_ia"]["job"])
    except RuntimeError as e:
        print(f"erro: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
