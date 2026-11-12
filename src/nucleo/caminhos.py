"""Onde fica cada coisa. É o único lugar que sabe de caminhos: o resto pergunta aqui.

    raiz()      a pasta do projeto (a que tem src/, config/, dados/)
    marca()     o slug da marca ativa: $NG3_MARCA ou config/marca-ativa
    acervo()    a raiz do acervo publicado da marca (config/marcas/<marca>/acervo.toml)
    dados(...)  dados/marcas/<marca>/... — estado de trabalho, fora do git
    assets(...) assets/... — arquivos de apoio do projeto
"""
from __future__ import annotations

import os

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def raiz(*partes: str) -> str:
    return os.path.join(os.environ.get("NG3_RAIZ") or _RAIZ, *partes)


def marca() -> str:
    m = os.environ.get("NG3_MARCA")
    if m:
        return m.strip()
    with open(raiz("config", "marca-ativa"), encoding="utf-8") as fh:
        return fh.read().strip()


def marcas() -> list[str]:
    d = raiz("config", "marcas")
    return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)))


def acervo() -> str:
    from nucleo import config
    return config.carregar()["acervo"]["raiz"]


def dados(*partes: str) -> str:
    d = raiz("dados", "marcas", marca(), *partes)
    os.makedirs(d if not os.path.splitext(d)[1] else os.path.dirname(d), exist_ok=True)
    return d


def assets(*partes: str) -> str:
    return raiz("assets", *partes)


def resolver(valor: str, base: str) -> str:
    """Caminho de config: absoluto/~ como está; `assets/...` no projeto; o resto relativo a `base`."""
    v = os.path.expanduser(valor)
    if os.path.isabs(v):
        return v
    if v.startswith("assets/"):
        return raiz(v)
    return os.path.join(base, v)
