"""Clientes (marcas): listar e criar um novo a partir do molde config/marcas/exemplo/."""
from __future__ import annotations

import json
import os
import re
import shutil
import tomllib

from nucleo import caminhos


def _ler(p: str) -> str:
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _escrever(p: str, s: str) -> None:
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(s)


def listar() -> list[dict]:
    out = []
    for slug in caminhos.marcas():
        try:
            with open(caminhos.raiz("config", "marcas", slug, "marca.toml"), "rb") as fh:
                nome = (tomllib.load(fh).get("marca") or {}).get("nome") or slug
        except (OSError, tomllib.TOMLDecodeError):
            nome = slug
        out.append({"slug": slug, "nome": nome, "molde": slug == "exemplo"})
    return out


def _slug(nome: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def criar(nome: str, raiz_acervo: str = "", slug: str = "") -> dict:
    """Copia o molde, troca nome e slug, e aponta o acervo (vazio = uma pasta nova em dados/)."""
    nome = nome.strip()
    if not nome:
        raise ValueError("dê um nome ao cliente")
    slug = _slug(slug or nome)
    if not slug or slug in caminhos.marcas():
        raise ValueError(f"já existe um cliente \"{slug}\"")
    if raiz_acervo.strip():
        raiz_acervo = os.path.abspath(os.path.expanduser(raiz_acervo.strip()))
        if not os.path.isdir(raiz_acervo):
            raise ValueError(f"pasta não encontrada: {raiz_acervo}")
    else:
        raiz_acervo = caminhos.raiz("dados", "marcas", slug, "acervo")
        os.makedirs(raiz_acervo, exist_ok=True)
    destino = caminhos.raiz("config", "marcas", slug)
    shutil.copytree(caminhos.raiz("config", "marcas", "exemplo"), destino)
    p = os.path.join(destino, "marca.toml")
    s = _ler(p)
    s = re.sub(r'(?m)^slug = ".*"$', f'slug = "{slug}"', s)
    s = re.sub(r'(?m)^nome = ".*"$', f"nome = {json.dumps(nome, ensure_ascii=False)}", s)
    s = re.sub(r'(?m)^instagram = ".*"$', 'instagram = ""', s)
    s = re.sub(r'(?m)^descricao = ".*"$', f'descricao = {json.dumps(nome + " (descreva aqui o que a marca faz)", ensure_ascii=False)}', s)
    s = s.replace("# Molde para um cliente novo: copie esta pasta para config/marcas/<slug>/ e troque os textos.\n", "")
    _escrever(p, s)
    p = os.path.join(destino, "acervo.toml")
    s = _ler(p)
    s = re.sub(r'(?m)^raiz = ".*"$', f"raiz = {json.dumps(raiz_acervo, ensure_ascii=False)}", s, count=1)
    s = s.replace("[marcas.exemplo.", f"[marcas.{slug}.")
    _escrever(p, s)
    return {"slug": slug, "nome": nome, "acervo": raiz_acervo}
