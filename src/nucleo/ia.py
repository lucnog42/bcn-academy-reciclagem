#!/usr/bin/env python3
"""Uma conversa com a IA escolhida no painel: Claude (API própria) ou qualquer API no formato
da OpenAI (DeepSeek, OpenRouter, Ollama local, ...).

O conteúdo entra sempre no formato do Claude (blocos `text` e `image` com base64); para os
outros provedores ele é convertido (`image_url` com data URI). Se o modelo escolhido não
aceita imagem, a mesma pergunta é refeita só com o texto, e a resposta avisa.

    from nucleo import ia
    texto = ia.conversar([{"type": "text", "text": "oi"}], sistema="...")
    ia.testar()   # {"valida": True/False, "erro": "..."}
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import json
import urllib.error
import urllib.request

from nucleo import config

TIMEOUT = 240


class SemChave(RuntimeError):
    pass


def _post(url: str, corpo: dict, cabecalhos: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(corpo).encode(),
                                 headers={"content-type": "application/json", **cabecalhos})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code} {e.read().decode(errors='replace')[:400]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"sem conexão com {url}: {e.reason}")


def _cabecalhos(p: dict, chave: str | None) -> dict:
    if p["tipo"] == "anthropic":
        return {"x-api-key": chave or "", "anthropic-version": "2023-06-01"}
    h = {"Authorization": f"Bearer {chave}"} if chave else {}
    if p["id"] == "openrouter":
        h["X-Title"] = "video-automation-ng3"
    return h


def _para_openai(conteudo: list, com_imagens: bool = True) -> list:
    out = []
    for b in conteudo:
        if b.get("type") == "text":
            out.append({"type": "text", "text": b["text"]})
        elif b.get("type") == "image" and com_imagens:
            src = b["source"]
            out.append({"type": "image_url",
                        "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
    return out


def _parece_sem_visao(erro: str) -> bool:
    e = erro.lower()
    return any(x in e for x in ("image", "vision", "multimodal", "image_url", "unsupported content"))


def conversar(conteudo: list, sistema: str = "", max_tokens: int = 3000) -> str:
    """Manda a mensagem ao provedor escolhido e devolve o texto da resposta."""
    p = config.ia()
    chave = config.chave(p["id"])
    if p["chave"] and not chave:
        raise SemChave(f"sem chave da API para {p['nome']}: abra o botão da IA no topo do painel")
    if not p["modelo"]:
        raise ValueError(f"escolha o modelo de {p['nome']} no botão da IA no topo do painel")
    if p["tipo"] == "anthropic":
        corpo = {"model": p["modelo"], "max_tokens": max_tokens,
                 "messages": [{"role": "user", "content": conteudo}]}
        if sistema:
            corpo["system"] = sistema
        resp = _post(f"{p['base_url']}/messages", corpo, _cabecalhos(p, chave))
        return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")

    def pedir(com_imagens: bool) -> dict:
        msgs = ([{"role": "system", "content": sistema}] if sistema else []) + \
               [{"role": "user", "content": _para_openai(conteudo, com_imagens)}]
        return _post(f"{p['base_url']}/chat/completions",
                     {"model": p["modelo"], "max_tokens": max_tokens, "messages": msgs},
                     _cabecalhos(p, chave))

    tem_imagem = any(b.get("type") == "image" for b in conteudo)
    try:
        resp = pedir(True)
    except RuntimeError as e:
        if not (tem_imagem and _parece_sem_visao(str(e))):
            raise
        print(f"  ({p['modelo']} não aceita imagens: pergunta refeita só com o texto)", flush=True)
        resp = pedir(False)
    msg = (resp.get("choices") or [{}])[0].get("message") or {}
    texto = msg.get("content") or ""
    if isinstance(texto, list):
        texto = "".join(x.get("text", "") for x in texto if isinstance(x, dict))
    return texto


def info() -> dict:
    """O que o painel mostra (nunca a chave inteira)."""
    p = config.ia()
    c = config.chave(p["id"]) or ""
    from nucleo import caminhos
    return {"provedor": p["id"], "nome": p["nome"], "modelo": p["modelo"], "base_url": p["base_url"],
            "escopo_ia": p.get("escopo", "geral"), "marca": caminhos.marca(),
            "origem_video": config.origem_chave("video"),
            "precisa_chave": p["chave"], "claude": bool(c) or not p["chave"],
            "origem": config.origem_chave(p["id"]), "fim": c[-4:] if c else "",
            "chave_video": bool(config.chave("video")),
            "fim_video": (config.chave("video") or "")[-4:],
            "provedores": [{"id": k, "nome": v["nome"], "base_url": v["base_url"], "modelo": v["modelo"],
                            "chave": v["chave"], "tem_chave": bool(config.chave(k)),
                            "origem": config.origem_chave(k)}
                           for k, v in config.PROVEDORES.items()]}


def testar() -> dict:
    """Uma consulta sem custo (a lista de modelos) para ver se endereço e chave valem."""
    p = config.ia()
    chave = config.chave(p["id"])
    out = info()
    if p["chave"] and not chave:
        return {**out, "valida": False, "erro": "sem chave"}
    url = f"{p['base_url']}/models" + ("?limit=1" if p["tipo"] == "anthropic" else "")
    req = urllib.request.Request(url, headers=_cabecalhos(p, chave))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            dados = json.load(r)
    except urllib.error.HTTPError as e:
        motivo = {401: "chave recusada (401): confira se copiou inteira",
                  403: "sem permissão (403)", 404: "endereço errado (404)"}.get(e.code, f"erro {e.code}")
        return {**out, "valida": False, "erro": motivo}
    except Exception as e:
        return {**out, "valida": False, "erro": f"sem conexão com {p['base_url']}: {e}"}
    ids = [m.get("id", "") for m in (dados.get("data") or []) if isinstance(m, dict)]
    if p["tipo"] == "openai" and ids and p["modelo"] and p["modelo"] not in ids:
        return {**out, "valida": True, "erro": f"o modelo {p['modelo']} não aparece na lista; "
                                               f"alguns: {', '.join(ids[:6])}"}
    return {**out, "valida": True, "erro": "", "modelos": ids[:40]}
