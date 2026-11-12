#!/usr/bin/env python3
"""Servidor local do painel — opcional, só para os botões que escrevem no disco.

    python3 _reciclagem/servidor.py            # http://127.0.0.1:8765
    python3 _reciclagem/servidor.py --porta 9000

Sem ele o painel.html continua funcionando (marcações no navegador, seleção
exportada à mão). Com ele, o painel grava direto em:

    _reciclagem/estados.json     marcações (não interessante / já repostado)
    _posts/…/<post>.fcproj|.pcraft   projetos, via gerar_projetos.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bcnlib  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = bcnlib.BASE
PAINEL = os.path.join(BASE, "painel.html")
TRAVA = threading.Lock()


def gerar(posts: list[str], linked: bool = True, cortes: bool = False) -> dict:
    """Roda o gerador para os posts escolhidos e devolve o log."""
    if not posts:
        return {"ok": False, "saida": "nenhum post selecionado"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump({"posts": posts}, fh, ensure_ascii=False)
        caminho = fh.name
    try:
        if cortes:
            cmd = [sys.executable, os.path.join(AQUI, "gerar_projetos.py"),
                   "--tipo", "corte", "--aplicar"]
            for c in posts:
                cmd += ["--corte", c]
        else:
            cmd = [sys.executable, os.path.join(AQUI, "gerar_projetos.py"),
                   "--selecao", caminho, "--aplicar"]
        if linked:
            cmd.append("--linked")     # .pcraft leve: aponta para imagens/, não embute
        r = subprocess.run(cmd,
                           capture_output=True, text=True, cwd=BASE, timeout=1800)
    except subprocess.TimeoutExpired:
        return {"ok": False, "saida": "tempo esgotado (30 min)"}
    finally:
        os.unlink(caminho)
    feitos = []
    for post in posts:
        pasta = None
        for ano in os.listdir(os.path.join(BASE, "_posts")):
            cam = os.path.join(BASE, "_posts", ano, post)
            if os.path.isdir(cam):
                pasta = cam
                break
        if pasta and (os.path.exists(os.path.join(pasta, f"{post}.fcproj"))
                      or os.path.exists(os.path.join(pasta, f"{post}.pcraft"))):
            feitos.append(post)
    return {"ok": r.returncode == 0, "saida": (r.stdout or r.stderr)[-1500:],
            "gerados": feitos}


class Handler(BaseHTTPRequestHandler):
    server_version = "bcn-painel/1"

    def _json(self, dados: dict, codigo: int = 200) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _html(self) -> None:
        if not os.path.exists(PAINEL):
            self._json({"ok": False, "saida": "rode painel.py primeiro"}, 404)
            return
        with open(PAINEL, "rb") as fh:
            corpo = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    TIPOS = {".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".png": "image/png", ".mp4": "video/mp4", ".mov": "video/quicktime"}

    def _arquivo(self, rel: str) -> None:
        from urllib.parse import unquote
        alvo = os.path.realpath(os.path.join(BASE, unquote(rel)))
        if not alvo.startswith(os.path.realpath(BASE)) or not os.path.isfile(alvo):
            self._json({"ok": False, "saida": "não encontrado"}, 404)
            return
        ext = os.path.splitext(alvo)[1].lower()
        with open(alvo, "rb") as fh:
            corpo = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", self.TIPOS.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self) -> None:                                   # noqa: N802
        if self.path in ("/", "/index.html", "/painel.html"):
            self._html()
        elif self.path.startswith("/_posts/"):
            self._arquivo(self.path.lstrip("/").split("?")[0])
        elif self.path.startswith("/api/estado"):
            self._json({"ok": True, "servidor": True,
                        "estados": bcnlib.carregar_estados()})
        else:
            self._json({"ok": False, "saida": "rota desconhecida"}, 404)

    def do_POST(self) -> None:                                  # noqa: N802
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
            corpo = json.loads(self.rfile.read(tamanho) or b"{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "saida": "json inválido"}, 400)
            return

        if self.path == "/api/marcar":
            post = str(corpo.get("post") or "")
            if not post:
                self._json({"ok": False, "saida": "post vazio"}, 400)
                return
            with TRAVA:
                estados = bcnlib.carregar_estados()
                atual = estados.setdefault(post, {})
                for campo in ("nao_interessante", "repostado"):
                    if campo in corpo:
                        atual[campo] = bool(corpo[campo])
                if not any(atual.get(c) for c in ("nao_interessante", "repostado")):
                    estados.pop(post, None)
                import datetime as dt
                atual["quando"] = dt.datetime.now().isoformat(timespec="seconds")
                bcnlib.salvar_estados(estados)
            self._json({"ok": True, "estados": estados})

        elif self.path == "/api/gerar":
            resultado = gerar([str(p) for p in (corpo.get("posts") or [])],
                              linked=bool(corpo.get("linked", True)),
                              cortes=bool(corpo.get("cortes", False)))
            self._json(resultado)

        elif self.path == "/api/regerar-painel":
            r = subprocess.run([sys.executable, os.path.join(AQUI, "painel.py")],
                               capture_output=True, text=True, cwd=BASE)
            self._json({"ok": r.returncode == 0, "saida": r.stdout + r.stderr})

        else:
            self._json({"ok": False, "saida": "rota desconhecida"}, 404)

    def log_message(self, formato: str, *args) -> None:
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("  %s\n" % (formato % args))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=8765)
    a = ap.parse_args()
    if not os.path.exists(PAINEL):
        print("painel.html não existe — rodando painel.py")
        subprocess.run([sys.executable, os.path.join(AQUI, "painel.py")], cwd=BASE)
    servidor = ThreadingHTTPServer(("127.0.0.1", a.porta), Handler)
    print(f"painel em http://127.0.0.1:{a.porta}  (Ctrl+C para parar)")
    print(f"estados: {bcnlib.ESTADOS}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\ntchau")


if __name__ == "__main__":
    main()
