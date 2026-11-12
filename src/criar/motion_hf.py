#!/usr/bin/env python3
"""Motion com HyperFrames (HTML → vídeo): o gráfico de um momento vira uma composição HTML com
fundo transparente, renderizada em MOV ProRes 4444 (com alfa), que entra por cima do vídeo como
os outros motions (plugin Inserir motion / faixa Motion).

1. compor: a IA das sugestões escreve dados/marcas/<marca>/motion/hyperframes/<id>/index.html a
   partir do briefing do momento (ou do texto dele), seguindo o contrato do HyperFrames;
   `npx hyperframes lint` confere e, se reclamar, a IA corrige uma vez.
2. renderizar: `npx hyperframes render --format mov` → motion/prontos/<id>.mov.

Precisa de Node 22+ e do FFmpeg nesta máquina (o `npx` baixa o HyperFrames na primeira vez).
A composição fica na pasta para abrir e ajustar à mão (`npx hyperframes preview`).

    python3 src/criar/motion_hf.py gerar <pasta> <id>
    python3 src/criar/motion_hf.py compor <pasta> <id>
    python3 src/criar/motion_hf.py renderizar <pasta> <id>
    python3 src/criar/motion_hf.py biblioteca
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess

from nucleo import config  # noqa: E402
from plano import momentos  # noqa: E402

W, H, FPS = 1080, 1920, 30

CONTRATO = """Você escreve composições HyperFrames (HTML renderizado quadro a quadro em vídeo).
Devolva UM arquivo index.html completo, dentro de ```html ... ```, e nada mais.

Contrato (obrigatório):
- <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script> no <head>; nenhum outro recurso externo.
- html, body: margin 0, width {W}px, height {H}px, overflow hidden, background TRANSPARENTE (é um gráfico POR CIMA de um vídeo).
- Um #root com data-composition-id="main" data-start="0" data-duration="{D}" data-width="{W}" data-height="{H}", sem fundo.
- Todo elemento que aparece e some tem class="clip", id estável, data-start e data-duration em segundos e data-track-index;
  ele existe no intervalo [start, start+duration).
- Uma timeline GSAP pausada: const tl = gsap.timeline({{ paused: true }}); ... window.__timelines["main"] = tl; tl.seek(0);
  registrada no fim do script, depois de todos os tweens.
- Nada de Date.now(), Math.random() sem semente, setTimeout, fetch, repeat: -1. Tudo depende só do tempo da timeline.
- Não anime display/visibility/autoAlpha de um .clip (anime um filho, ou a opacidade); anime transform (x, y, scale),
  nunca left/top/width/height; sem CSS transform num elemento que o GSAP anima.
- Fontes: só as do sistema (sans-serif, "Inter" se houver) ou nenhuma família específica.
- Tudo dentro da área segura: 6% de margem; o terço de baixo é da legenda, não use (a não ser que o briefing peça).
- Entrada 0,3–0,5 s (power2.out / power4.out), saída 0,25–0,35 s (power2.in) terminando antes do fim; nada piscando mais de 3x/s.
- Texto exatamente como no briefing; não invente nome, número ou data."""


def pasta_hf(sid: str) -> str:
    d = os.path.join(momentos.DIR_MOTION, "hyperframes", sid)
    os.makedirs(d, exist_ok=True)
    return d


def _momento(pasta: str, sid: str) -> dict:
    s = next((x for x in momentos.ler_sugestoes(pasta).get("itens", []) if x["id"] == sid), None)
    if s is None:
        raise ValueError("momento não encontrado")
    return s


def _npx() -> str:
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError("o HyperFrames precisa do Node 22+ (npx): sudo pacman -S nodejs npm")
    return npx


def _html_de(texto: str) -> str:
    m = re.search(r"```(?:html)?\s*(.*?)```", texto, re.S)
    html = (m.group(1) if m else texto).strip()
    if "data-composition-id" not in html or "__timelines" not in html:
        raise RuntimeError("a IA não devolveu uma composição HyperFrames")
    return html


def _duracao(s: dict) -> float:
    return round(max(1.5, float(s["fim"]) - float(s["ini"])), 2)


def compor(pasta: str, sid: str) -> str:
    from nucleo import ia
    s = _momento(pasta, sid)
    cfg = config.carregar()
    d = _duracao(s)
    cores = cfg["marca"].get("cores_texto") or ", ".join((cfg.get("cores") or {}).values()) or "as da marca"
    briefing = (s.get("briefing") or "").strip() or (
        f"Gráfico do tipo {s.get('tipo')} com o texto \"{s.get('texto', '')}\""
        + (f" e, menor, \"{s['apoio']}\"" if s.get("apoio") else "") + f", na posição {s.get('posicao') or 'alto'}.")
    no_proj = momentos._no_projeto(pasta, s)
    pedido = (f"Briefing do motion:\n{briefing}\n\nDuração total: {d} s. Formato {W}x{H} (vertical).\n"
              f"Cores da marca: {cores}. Paleta (hex): {json.dumps(cfg.get('cores') or {})}.\n"
              + (f"Já na tela neste trecho do projeto: {no_proj['na_tela']}. Legenda na tela: \"{no_proj.get('legenda_na_tela', '')}\".\n"
                 if no_proj.get("na_tela") else "")
              + f"Marca: {config.descricao_marca()}")
    sistema = CONTRATO.replace("{W}", str(W)).replace("{H}", str(H)).replace("{D}", str(d)).replace("{{", "{").replace("}}", "}")
    html = _html_de(ia.conversar([{"type": "text", "text": pedido}], sistema, 6000))
    dirr = pasta_hf(sid)
    arq = os.path.join(dirr, "index.html")
    with open(arq, "w", encoding="utf-8") as fh:
        fh.write(html)
    erros = lint(dirr)
    if erros:
        print(f"  lint: {len(erros)} problema(s); pedindo a correção à IA", flush=True)
        conserto = (pedido + "\n\nA composição abaixo não passou no `hyperframes lint`. Corrija e devolva o arquivo inteiro.\n"
                    f"Erros:\n" + "\n".join(erros[:20]) + f"\n\n```html\n{html}\n```")
        html = _html_de(ia.conversar([{"type": "text", "text": conserto}], sistema, 6000))
        with open(arq, "w", encoding="utf-8") as fh:
            fh.write(html)
        erros = lint(dirr)
        if erros:
            print("  ainda com avisos do lint (renderizando mesmo assim):\n   " + "\n   ".join(erros[:8]), flush=True)

    def mudar(x: dict) -> None:
        x["motion_hf"] = {"composicao": arq, "composto_em": dt.datetime.now().isoformat(timespec="seconds"),
                          "ia": ia.info()["nome"]}
    momentos._mudar_momento(pasta, sid, mudar)
    return arq


def lint(dirr: str) -> list[str]:
    """Os erros do `hyperframes lint --json` (vazio = passou)."""
    r = subprocess.run([_npx(), "--yes", "hyperframes", "lint", "--json"], cwd=dirr, capture_output=True, text=True,
                       timeout=300)
    try:
        d = json.loads(r.stdout[r.stdout.find("{"):])
    except ValueError:
        return [] if r.returncode == 0 else [(r.stderr or r.stdout).strip()[:400]]
    itens = d.get("errors") or d.get("issues") or d.get("findings") or []
    out = []
    for x in itens:
        if isinstance(x, dict) and (x.get("severity") in (None, "error")):
            out.append(f"{x.get('code') or x.get('rule') or ''}: {x.get('message') or x}")
        elif isinstance(x, str):
            out.append(x)
    return out


def renderizar(pasta: str, sid: str) -> str:
    dirr = pasta_hf(sid)
    if not os.path.exists(os.path.join(dirr, "index.html")):
        raise RuntimeError("sem composição: rode compor primeiro")
    os.makedirs(momentos.PRONTOS, exist_ok=True)
    alvo = os.path.join(momentos.PRONTOS, f"{sid}.mov")
    if os.path.exists(alvo):
        os.replace(alvo, os.path.join(momentos.PRONTOS, f"{sid}.{dt.datetime.now():%Y%m%d-%H%M%S}.mov.antigo"))
    print(f"▶ renderizando com HyperFrames (MOV com transparência): {sid}", flush=True)
    r = subprocess.run([_npx(), "--yes", "hyperframes", "render", "--format", "mov", "--quality", "high",
                        "--fps", str(FPS), "--output", alvo], cwd=dirr, text=True)
    if r.returncode != 0 or not os.path.exists(alvo):
        raise RuntimeError("o HyperFrames não renderizou (veja as linhas acima; `npx hyperframes doctor` confere a máquina)")

    def pronto(x: dict) -> None:
        x["status"] = "pronto"
        x["formato"] = "motion"
        x.setdefault("motion_hf", {})["renderizado_em"] = dt.datetime.now().isoformat(timespec="seconds")
    momentos._mudar_momento(pasta, sid, pronto)
    momentos._gravar(momentos.FILA, [p for p in momentos.ler_fila() if p["id"] != sid])
    print(f"pronto: {alvo}", flush=True)
    return alvo


def gerar(pasta: str, sid: str) -> str:
    print(f"▶ escrevendo a composição do momento {sid}", flush=True)
    compor(pasta, sid)
    return renderizar(pasta, sid)


# ------------------------------------------------------------------ motions que já existem
def biblioteca() -> list[dict]:
    """Os motions prontos do cliente (de qualquer item), com o texto e o tipo do momento de origem."""
    info: dict[str, dict] = {}
    for arq in glob.glob(os.path.join(momentos.DIR_MOTION, "itens", "*", "sugestoes.json")):
        try:
            with open(arq, encoding="utf-8") as fh:
                for s in json.load(fh).get("itens") or []:
                    info[s["id"]] = {"texto": s.get("texto", ""), "tipo": s.get("tipo", ""), "briefing": s.get("briefing", ""),
                                     "item": os.path.basename(os.path.dirname(arq)), "dur": round(s["fim"] - s["ini"], 1)}
        except (OSError, ValueError, KeyError):
            continue
    out = []
    if os.path.isdir(momentos.PRONTOS):
        for n in os.listdir(momentos.PRONTOS):
            sid, ext = os.path.splitext(n)
            if ext.lower() not in (".mov", ".webm") or "." in sid:      # só motions (MP4 é vídeo gerado)
                continue
            arq = os.path.join(momentos.PRONTOS, n)
            out.append({"id": sid, "arquivo": arq, "quando": os.path.getmtime(arq), **(info.get(sid) or {})})
    return sorted(out, key=lambda x: -x["quando"])


def reusar(pasta: str, sid: str, origem: str) -> dict:
    """Usa um motion que já existe neste momento (um link para o mesmo arquivo, sem renderizar de novo)."""
    src = next((b["arquivo"] for b in biblioteca() if b["id"] == origem), None)
    if not src:
        raise ValueError("motion não encontrado na biblioteca")
    alvo = os.path.join(momentos.PRONTOS, sid + os.path.splitext(src)[1])
    if os.path.exists(alvo):
        os.replace(alvo, alvo + f".{dt.datetime.now():%Y%m%d-%H%M%S}.antigo")
    try:
        os.link(src, alvo)
    except OSError:
        shutil.copy2(src, alvo)

    def pronto(x: dict) -> None:
        x["status"] = "pronto"
        x["formato"] = "motion"
        x["reuso_de"] = origem
    return momentos._mudar_momento(pasta, sid, pronto)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("gerar", "compor", "renderizar"):
        p = sub.add_parser(c)
        p.add_argument("pasta")
        p.add_argument("id")
    sub.add_parser("biblioteca")
    a = ap.parse_args()
    try:
        if a.cmd == "gerar":
            gerar(a.pasta, a.id)
        elif a.cmd == "compor":
            print(compor(a.pasta, a.id))
        elif a.cmd == "renderizar":
            renderizar(a.pasta, a.id)
        else:
            for b in biblioteca():
                print(f"{b['id']:<14} {b.get('tipo', ''):<9} {b.get('texto', '')[:50]}")
    except RuntimeError as e:
        print(f"erro: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    import sys
    main()
