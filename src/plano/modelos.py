#!/usr/bin/env python3
"""Modelos de prompt: estilos prontos que você escolhe antes de gerar (config/padroes/modelos-prompt.toml,
mais os da marca). Cada modelo vale para alguns tipos de momento e vira, com os dados do momento,
o briefing do motion ou o prompt do vídeo.

    python3 modelos.py listar [motion|video] [--tipo destaque]
    python3 modelos.py aplicar <pasta> <id> <modelo>
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import json

from nucleo import config  # noqa: E402
from plano import momentos  # noqa: E402

POSICOES = {"alto": "no alto", "meio": "no meio", "baixo": "acima da legenda", "esquerda": "à esquerda",
            "direita": "à direita"}


def listar(alvo: str = "", tipo: str = "") -> list[dict]:
    out = []
    for m in config.carregar().get("modelos_prompt") or []:
        if alvo and m.get("alvo") != alvo:
            continue
        if tipo and m.get("tipos") and tipo not in m["tipos"]:
            continue
        out.append({"id": m["id"], "alvo": m.get("alvo", "motion"), "nome": m.get("nome", m["id"]),
                    "descricao": m.get("descricao", ""), "tipos": list(m.get("tipos") or [])})
    return out


def _modelo(mid: str) -> dict:
    m = next((x for x in config.carregar().get("modelos_prompt") or [] if x.get("id") == mid), None)
    if m is None:
        raise ValueError(f"modelo desconhecido: {mid}")
    return m


def preencher(molde: str, s: dict) -> str:
    """O molde com os dados do momento. Marca que não tem valor some sem deixar buraco."""
    cfg = config.carregar()
    m = cfg["marca"]
    dur = max(0.5, float(s.get("fim", 0)) - float(s.get("ini", 0)) - 0.6)
    valores = {
        "texto": (s.get("texto") or "").strip(),
        "apoio": (s.get("apoio") or "").strip(),
        "duracao": f"{dur:.1f} s",
        "posicao": POSICOES.get(s.get("posicao") or "alto", s.get("posicao") or "no alto"),
        "cores": m.get("cores_texto") or ", ".join((cfg.get("cores") or {}).values()) or "as da marca",
        "estilo": (cfg.get("estilo") or {}).get("linha") or "natural, realistic",
        "fala": (s.get("fala") or "").strip(),
    }
    out = molde
    for k, v in valores.items():
        out = out.replace("{" + k + "}", v)
    return " ".join(out.split()).replace(" .", ".").strip()


def aplicar(pasta: str, sid: str, mid: str) -> dict:
    """Escreve o briefing (motion) ou o prompt (vídeo) do momento a partir do modelo e guarda a escolha."""
    mod = _modelo(mid)
    s = next((x for x in momentos.ler_sugestoes(pasta).get("itens", []) if x["id"] == sid), None)
    if s is None:
        raise ValueError("momento não encontrado")
    texto = preencher(mod.get("molde", ""), s)
    alvo = mod.get("alvo", "motion")
    campos = {"briefing": texto, "modelo_motion": mid} if alvo == "motion" else {"prompt_video": texto, "modelo_video": mid}
    momentos.marcar(pasta, sid, campos)
    return {"alvo": alvo, "modelo": mid, "texto": texto}


def guia(mid: str) -> str:
    """Para a IA: o que o modelo escolhido pede (ela escreve no estilo dele)."""
    if not mid:
        return ""
    try:
        m = _modelo(mid)
    except ValueError:
        return ""
    return f"Estilo escolhido pelo usuário: \"{m.get('nome')}\" — {m.get('descricao', '')}. Molde de referência: {m.get('molde', '')}"


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    li = sub.add_parser("listar")
    li.add_argument("alvo", nargs="?", default="")
    li.add_argument("--tipo", default="")
    ap_ = sub.add_parser("aplicar")
    ap_.add_argument("pasta")
    ap_.add_argument("id")
    ap_.add_argument("modelo")
    a = ap.parse_args()
    if a.cmd == "listar":
        for m in listar(a.alvo, a.tipo):
            print(f"{m['alvo']:<7} {m['id']:<16} {m['nome']:<22} {', '.join(m['tipos'])}")
    else:
        print(json.dumps(aplicar(a.pasta, a.id, a.modelo), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
