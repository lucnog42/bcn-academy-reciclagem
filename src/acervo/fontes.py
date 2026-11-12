#!/usr/bin/env python3
"""Importar sem duplicar: pastas apontadas como fontes do cliente ativo.

Uma fonte é uma pasta em qualquer disco. Nada é copiado nem escrito nela: o índice, as
transcrições e as miniaturas ficam em dados/marcas/<marca>/. Cada fonte tem um tipo, que diz
para que ela serve:

  * falas  -> vídeos com gente falando: são transcritos e entram nos roteiros e no b-roll
  * broll  -> vídeos e fotos de cobertura (sem fala útil)
  * fotos  -> só imagens
  * referencias -> vídeos e imagens de OUTROS (estilo, ritmo, montagem): nunca entram no b-roll
              nem nos roteiros como material; servem de referência para a direção

As fontes do acervo.toml (posts, cortes) aparecem junto, mas só as importadas podem ser removidas.
Ficam em dados/marcas/<marca>/fontes.json (caminhos desta máquina; não vão para o git).

    python3 src/acervo/fontes.py
    python3 src/acervo/fontes.py adicionar "/mnt/HD/Depoimentos 2024" --tipo falas --nome "Depoimentos 2024"
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import json
import os
import re
import time

from nucleo import caminhos, config  # noqa: E402

TIPOS = {"falas": "vídeos com fala (transcritos; entram nos roteiros)",
         "broll": "vídeos e fotos de cobertura",
         "fotos": "só imagens",
         "referencias": "referências de estilo e montagem (nunca entram como material)"}
VIDEO = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts")
IMAGEM = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff")


def _ler() -> dict:
    try:
        with open(config.fontes_importadas_json(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _gravar(d: dict) -> None:
    arq = config.fontes_importadas_json()
    tmp = arq + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, arq)
    config._CACHE = None


def _indexadas() -> dict[str, dict]:
    from achar import indice
    if not os.path.exists(indice.caminho_db()):
        return {}
    con = indice.abrir()
    out = {i: {"n": n, "quando": q} for i, q, n in con.execute("select id, quando, n from fontes")}
    con.close()
    return out


def listar() -> list[dict]:
    idx = _indexadas()
    out = []
    for f in config.carregar(recarregar=True).get("fontes") or []:
        i = idx.get(f["id"]) or {}
        out.append({"id": f["id"], "nome": f.get("nome") or f["id"], "tipo": f.get("tipo") or "pasta",
                    "raiz": f.get("raiz") or "", "ativo": bool(f.get("ativo", True)), "origem": f.get("origem", "config"),
                    "existe": (not f.get("raiz")) or os.path.isdir(f["raiz"]),
                    "indexados": i.get("n", 0), "indexado_em": i.get("quando") or 0})
    return out


def _slug(nome: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "fonte"


def adicionar(raiz: str, tipo: str, nome: str = "") -> dict:
    raiz = os.path.abspath(os.path.expanduser(raiz.strip()))
    if not os.path.isdir(raiz):
        raise ValueError(f"pasta não encontrada: {raiz}")
    if tipo not in TIPOS:
        raise ValueError(f"tipo é {', '.join(TIPOS)}")
    for f in config.carregar(recarregar=True).get("fontes") or []:
        r = f.get("raiz")
        if r and (raiz == r or raiz.startswith(r.rstrip(os.sep) + os.sep)):
            raise ValueError(f"essa pasta já está na fonte \"{f.get('nome') or f['id']}\"")
        if r and r.startswith(raiz.rstrip(os.sep) + os.sep):
            raise ValueError(f"a fonte \"{f.get('nome') or f['id']}\" já está dentro dessa pasta: remova-a antes")
    acervo = config.carregar()["acervo"]["raiz"]
    if acervo and (raiz + os.sep).startswith(acervo.rstrip(os.sep) + os.sep):
        raise ValueError("essa pasta já faz parte do acervo publicado")
    d = _ler()
    nome = nome.strip() or os.path.basename(raiz)
    ids = {f["id"] for f in config.carregar().get("fontes") or []}
    base = _slug(nome)
    fid, n = base, 2
    while fid in ids:
        fid, n = f"{base}-{n}", n + 1
    f = {"id": fid, "nome": nome, "tipo": tipo, "raiz": raiz, "ativo": True,
         "adicionada_em": time.strftime("%Y-%m-%d %H:%M")}
    d.setdefault("fontes", []).append(f)
    _gravar(d)
    return f


def remover(fid: str) -> None:
    """Tira a fonte importada do sistema (a pasta e os arquivos dela ficam como estão)."""
    d = _ler()
    antes = len(d.get("fontes") or [])
    d["fontes"] = [f for f in d.get("fontes") or [] if f["id"] != fid]
    if len(d["fontes"]) == antes:
        raise ValueError("só as fontes importadas pelo painel podem ser removidas")
    (d.get("estado") or {}).pop(fid, None)
    _gravar(d)
    from achar import indice
    if os.path.exists(indice.caminho_db()):
        con = indice.abrir()
        con.execute("delete from midias where fonte = ?", (fid,))
        con.execute("delete from fontes where id = ?", (fid,))
        con.commit()
        con.close()


def ativar(fid: str, ativo: bool) -> None:
    if fid not in {f["id"] for f in config.carregar(recarregar=True).get("fontes") or []}:
        raise ValueError("fonte desconhecida")
    d = _ler()
    d.setdefault("estado", {}).setdefault(fid, {})["ativo"] = bool(ativo)
    _gravar(d)


def fonte(fid: str) -> dict:
    f = next((x for x in config.carregar(recarregar=True).get("fontes") or [] if x["id"] == fid), None)
    if f is None:
        raise ValueError("fonte desconhecida")
    return f


def arquivos(f: dict) -> list[tuple[str, str]]:
    """(caminho, "video"|"imagem") de uma fonte de pasta, respeitando o tipo e o `ignorar`."""
    raiz = f.get("raiz") or ""
    if not os.path.isdir(raiz):
        return []
    ignorar = [x.lower() for x in f.get("ignorar") or []]
    tipo = f.get("tipo") or "pasta"
    out = []
    for r, dirs, arqs in os.walk(raiz):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not any(i in d.lower() for i in ignorar))
        for a in sorted(arqs):
            ext = os.path.splitext(a)[1].lower()
            if a.startswith("."):
                continue
            if ext in VIDEO and tipo not in ("fotos",):
                out.append((os.path.join(r, a), "video"))
            elif ext in IMAGEM and tipo != "falas":
                out.append((os.path.join(r, a), "imagem"))
    return out


def contar(fid: str) -> dict:
    """Quantos vídeos e fotos a pasta tem e quantos vídeos já têm transcrição."""
    from transcricao import legendar
    f = fonte(fid)
    arqs = arquivos(f)
    videos = [a for a, t in arqs if t == "video"]
    transcritos = sum(1 for v in videos if os.path.exists(legendar.caminho_saida(v, ".words.json")))
    return {"id": fid, "videos": len(videos), "imagens": len(arqs) - len(videos), "transcritos": transcritos}


def comando_transcrever(fid: str) -> list[str]:
    """O comando (para a fila de tarefas do app) que transcreve os vídeos da fonte que faltam."""
    f = fonte(fid)
    if not os.path.isdir(f.get("raiz") or ""):
        raise ValueError("a pasta da fonte não está acessível (o disco está montado?)")
    return ["python3", "src/transcricao/legendar.py", "--raiz", f["raiz"], "--aplicar"]


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    a_ = sub.add_parser("adicionar")
    a_.add_argument("raiz")
    a_.add_argument("--tipo", required=True, choices=list(TIPOS))
    a_.add_argument("--nome", default="")
    r_ = sub.add_parser("remover")
    r_.add_argument("id")
    a = ap.parse_args()
    if a.cmd == "adicionar":
        print(json.dumps(adicionar(a.raiz, a.tipo, a.nome), ensure_ascii=False))
    elif a.cmd == "remover":
        remover(a.id)
    else:
        for f in listar():
            print(f"{'●' if f['ativo'] else '○'} {f['id']:<20} {f['tipo']:<7} {f['origem']:<9} {f['indexados']:>6}  {f['raiz']}")


if __name__ == "__main__":
    main()
