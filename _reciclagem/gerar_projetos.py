#!/usr/bin/env python3
"""Passo 6 — gera um projeto FilmCraft/PhotoCraft por postagem do acervo.

    _posts/<ano>/<post>/<post>.fcproj    (tem vídeo)
    _posts/<ano>/<post>/<post>.pcraft    (só imagem)

Os projetos são criados pelos próprios apps via CLI headless, então o schema é o
deles — não um JSON escrito à mão que envelhece.

    python3 _reciclagem/gerar_projetos.py --limite 5          # simula 5
    python3 _reciclagem/gerar_projetos.py --limite 5 --aplicar
    python3 _reciclagem/gerar_projetos.py --aplicar --workers 4
    python3 _reciclagem/gerar_projetos.py --pilar MIC --desde 2024 --aplicar
    python3 _reciclagem/gerar_projetos.py --tipo imagem --limite 20 --aplicar
    python3 _reciclagem/gerar_projetos.py --verificar 5       # reabre e confere

Fila em `projetos.csv`, retomável: o que já existe é pulado (use --forcar).
Modelo completo em MODELO_PROJETOS.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import subprocess
import sys
import zlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bcnlib  # noqa: E402
import modelo_filmcraft as MF  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = bcnlib.BASE
FILA = os.path.join(AQUI, "projetos.csv")
COLS = ["post", "tipo", "projeto", "status", "segundos", "erro"]

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELO = os.path.join(AQUI, "modelo_base.fcproj")
ENDINGS = os.path.join(BASE, "_endings")
FILMCRAFT = "filmcraft-cli"
PHOTOCRAFT = "photocraft-cli"
TICKS_POR_S = 254_016_000_000

# formato de publicação → tamanho de sequência
TAMANHOS = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "16:9": (1920, 1080),
}


def pasta_do_post(p: dict) -> str:
    partes = p["midias"][0].split(os.sep)
    if "imagens" in partes or "videos" in partes:
        return os.sep.join(partes[:-2])
    return os.path.dirname(p["midias"][0])


def tamanho_sequencia(p: dict) -> tuple[int, int]:
    for fmt in p["formatos"].split():
        if fmt in TAMANHOS:
            return TAMANHOS[fmt]
    lados = [(m["w"], m["h"]) for m in p.get("_midias_raw", []) if m.get("w")]
    if lados:
        w, h = max(lados, key=lambda wh: wh[0] * wh[1])
        if w > h:
            return (1920, 1080)
        if h / max(w, 1) > 1.5:
            return (1080, 1920)
    return (1080, 1080)


def rodar(cmd: list[str], timeout: int = 180) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout de {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)


def musicas_disponiveis(pista: str | None) -> list[str]:
    """Faixas do Pixabay: um arquivo só, ou todas as de `_audio/musicas/`."""
    if not pista:
        for cand in ("_audio/musicas", "_audio/musica", "_musicas"):
            d = os.path.join(BASE, cand)
            if os.path.isdir(d):
                pista = d
                break
    if not pista:
        return []
    pista = os.path.expanduser(pista)
    if os.path.isdir(pista):
        return [os.path.join(pista, a) for a in sorted(os.listdir(pista))
                if os.path.splitext(a)[1].lower() in (".mp3", ".wav", ".m4a", ".aac", ".ogg")]
    return [pista] if os.path.exists(pista) else []


def achar_musica(pista: str | None, semente: str = "") -> str | None:
    """Escolhe a trilha: determinística por post (mesmo post sempre com a mesma
    faixa, mas o acervo não fica repetindo uma só)."""
    lista = musicas_disponiveis(pista)
    if not lista:
        return None
    if len(lista) == 1 or not semente:
        return lista[0]
    return lista[zlib.crc32(semente.encode()) % len(lista)]


def nome_do_corte(c: dict) -> str:
    """`_Cortes/Fernando/20260404_205347_corte.mp4` → `Fernando_20260404_205347`."""
    tema = c["tema"].split("/")[0].strip().replace(" ", "-")
    base_arq = os.path.splitext(os.path.basename(c["arquivo"]))[0]
    return f"{tema}_{base_arq}"


def gerar_com_modelo(nome: str, pasta: str, videos: list[str], dados_extra: dict,
                     musica: str | None, ending: str | None,
                     srt: str | None = None,
                     trechos: list[tuple[float, float]] | None = None) -> tuple[bool, str]:
    """Constrói o .fcproj a partir do projeto base do usuário (título, legenda,
    deesser, ending e SFX já no lugar)."""
    if not os.path.exists(MODELO):
        return False, f"modelo base ausente: {MODELO}"
    if not videos:
        return False, "sem vídeo"
    video = videos[0]
    if srt is None:
        pasta_post = os.path.dirname(video)
        srt = MF.srt_do_post(os.path.dirname(pasta_post), BASE)
    leg = MF.cartelas(MF.ler_srt(srt))
    dados = {"nome": nome, "video": video, "ending": ending,
             "logo": dados_extra.get("logo"), "titulo": dados_extra["titulo"],
             "subtitulo": dados_extra["subtitulo"], "legendas": leg,
             "musica": musica, "trechos": trechos}
    with open(MODELO, encoding="utf-8") as fh:
        template = json.load(fh)
    projeto = MF.construir(template, dados)
    alvo = os.path.join(pasta, f"{nome}.fcproj")
    MF.escrever(projeto, alvo)
    # o app valida ao abrir; se o arquivo tiver sobreposição, ele fica sem edição
    r = subprocess.run([FILMCRAFT, "--project", alvo, "inspect"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        os.unlink(alvo)
        return False, f"projeto inválido: {(r.stderr or r.stdout).strip()[:220]}"
    return True, ""


def gerar_filmcraft(nome: str, pasta: str, videos: list[str], imagens: list[str],
                    url: str, tamanho: tuple[int, int]) -> tuple[bool, str]:
    saida = os.path.join(pasta, f"{nome}.fcproj")
    largura, altura = tamanho
    plano = os.path.join(f"/tmp/bcn_fc_{os.getpid()}_{abs(hash(nome)) % 10**8}.jsonl")
    passos = [
        {"id": "file.newProject", "params": {"name": nome}},
        {"id": "file.newSequence", "params": {"name": nome, "width": largura,
                                             "height": altura, "fps": 30}},
        {"id": "edit.pasteMedia", "params": {"paths": videos + imagens, "place": True}},
    ]
    if url:
        passos.append({"id": "markers.add", "params": {
            "target": "program", "time": 0, "name": "Instagram",
            "comment": url, "color": "blue"}})
    with open(plano, "w", encoding="utf-8") as fh:
        for p in passos:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    codigo, out, err = rodar([FILMCRAFT, "--save-as", saida, "run", plano])
    os.unlink(plano)
    ok = codigo == 0 and os.path.exists(saida) and os.path.getsize(saida) > 0
    if not ok:
        falha = err.strip() or "".join(l for l in out.splitlines() if '"ok":false' in l)
        return False, falha[:300]
    return True, ""


def gerar_photocraft(nome: str, pasta: str, imagens: list[str],
                     tamanho: tuple[int, int], linked: bool) -> tuple[bool, str]:
    """Um documento, um artboard por imagem do carrossel (01..NN), lado a lado."""
    saida = os.path.join(pasta, f"{nome}.pcraft")
    if not imagens:
        return False, "sem imagem"
    largura, altura = tamanho
    folga = 100                      # separação entre boards na mesa
    passo = largura + folga
    novo = {"width": largura, "height": altura, "mode": "rgb", "depth": 8,
            "background": "transparent", "name": nome}
    cmd = [PHOTOCRAFT, "run", "--new", json.dumps(novo, ensure_ascii=False)]
    comando = "file.placeLinked" if linked else "file.placeEmbedded"
    # boards de trás para frente: o mais novo fica no topo, então a exportação
    # (que percorre a pilha de cima para baixo) sai na ordem do carrossel, 01 → NN
    for i in range(len(imagens) - 1, -1, -1):
        img = imagens[i]
        x = i * passo
        cmd += ["--cmd", "layer.new.artboard", "--params", json.dumps({
            "name": f"{i + 1:02d}", "x": x, "y": 0,
            "width": largura, "height": altura, "background": "transparent"})]
        cmd += ["--cmd", comando, "--params", json.dumps({
            "path": img, "fit": True, "center": [x + largura // 2, altura // 2]})]
    # sobra a camada vazia que o documento novo traz
    cmd += ["--cmd", "file.scripts.deleteAllEmptyLayers", "--params", "{}"]
    cmd += ["--out", saida]
    codigo, out, err = rodar(cmd, timeout=300)
    ok = codigo == 0 and os.path.exists(saida) and os.path.getsize(saida) > 0
    return (ok, "" if ok else (err.strip() or out.strip())[:300])


def carregar_selecao(caminho: str) -> set[str]:
    """Aceita o JSON do painel ({"posts": [pasta…]}) ou um nome de pasta por linha."""
    caminho = os.path.expanduser(caminho)
    with open(caminho, encoding="utf-8") as fh:
        texto = fh.read()
    try:
        dados = json.loads(texto)
        itens = dados.get("posts", dados) if isinstance(dados, dict) else dados
        return {os.path.basename(str(p).rstrip("/")) for p in itens}
    except json.JSONDecodeError:
        return {os.path.basename(l.split("\t")[0].strip().rstrip("/"))
                for l in texto.splitlines() if l.strip()}


def carregar_fila() -> dict[str, dict]:
    if not os.path.exists(FILA):
        return {}
    with open(FILA, encoding="utf-8") as fh:
        return {r["post"]: r for r in csv.DictReader(fh)}


def gravar_fila(fila: dict[str, dict]) -> None:
    with open(FILA, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(sorted(fila.values(), key=lambda r: r["post"]))


def titulo_e_subtitulo(p: dict) -> tuple[str, str]:
    """Título curto (cabe no Lower Third) e subtítulo com data e pilar."""
    gancho = (p.get("gancho") or "").strip()
    palavras, titulo = [], ""
    for palavra in gancho.split():
        if len(titulo) + len(palavra) + 1 > 20 or len(palavras) >= 4:
            break
        palavras.append(palavra)
        titulo = " ".join(palavras)
    if not titulo:
        titulo = p["pilar"].title()
    data = p["data"][:10]
    ano, mes, dia = data.split("-") if data else ("", "", "")
    return titulo, f"{dia}/{mes}/{ano} · {p['pilar']}"


# nome de pasta vem sem acento no acervo; o título vai para a tela, então devolve
# o acento das palavras que aparecem com frequência nos temas
ACENTOS = {
    "campeao": "Campeão", "otavio": "Otávio", "joao": "João", "lucio": "Lúcio",
    "vinicius": "Vinícius", "goncalves": "Gonçalves", "antonio": "Antônio",
    "nicolas": "Nicolás", "lucas": "Lucas", "pais": "Pais", "copa": "Copa",
}


def _com_acento(palavra: str) -> str:
    return ACENTOS.get(palavra.lower(), palavra)


def titulo_do_tema(tema: str) -> str:
    """`Futebol Campeao` → `Futebol Campeão`, `Costa RIca` → `Costa Rica`."""
    partes = []
    for p in tema.split("/")[0].split():
        partes.append(p if p.isupper() and len(p) <= 4 else _com_acento(p.title()))
    return " ".join(partes)


def tarefa_corte(c: dict, forcar: bool, opcoes: dict, nome: str) -> dict:
    """Projeto a partir de um corte cru de `_Cortes` (vídeo + srt ao lado)."""
    pasta_abs = os.path.join(BASE, os.path.dirname(c["arquivo"]))
    video = os.path.join(BASE, c["arquivo"])
    alvo = os.path.join(pasta_abs, f"{nome}.fcproj")
    if os.path.exists(alvo) and not forcar:
        return {"post": nome, "tipo": "fcproj", "projeto": os.path.relpath(alvo, BASE),
                "status": "existente", "segundos": "0", "erro": ""}
    # título: nome da pessoa/tema; subtítulo: pilar + data do nome do arquivo
    data = ""
    m = __import__("re").match(r"(\d{4})(\d{2})(\d{2})_", os.path.basename(c["arquivo"]))
    if m:
        data = f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    titulo = titulo_do_tema(c["tema"])
    subtitulo = " · ".join(x for x in (c["pilar"].title(), data) if x)
    inicio = time.time()
    # silêncios medidos no áudio, não deduzidos do .srt: entre duas cartelas de
    # fala pode haver 30 s de silêncio que o Whisper colou num cue só
    trechos = None
    if opcoes.get("sem_silencio"):
        trechos = MF.trechos_com_fala(
            video, srt=os.path.splitext(video)[0] + ".srt",
            ruido_db=float(opcoes["sem_silencio"]))
    ok, erro = gerar_com_modelo(nome, pasta_abs, [video],
                                {"titulo": titulo, "subtitulo": subtitulo,
                                 "logo": opcoes.get("logo")},
                                achar_musica(opcoes.get("musica"), nome),
                                opcoes.get("ending"),
                                srt=os.path.splitext(video)[0] + ".srt",
                                trechos=trechos)
    if ok and trechos:
        print(f"  {nome}: {len(trechos)} trechos · "
              f"{sum(b - a for a, b in trechos):.1f}s de fala no corte")
    return {"post": nome, "tipo": "fcproj",
            "projeto": os.path.relpath(alvo, BASE) if ok else "",
            "status": "ok" if ok else "erro", "segundos": f"{time.time() - inicio:.1f}",
            "erro": erro}


def tarefa(p: dict, tipos: str, linked: bool, forcar: bool,
           opcoes: dict | None = None) -> dict:
    pasta_rel = pasta_do_post(p)
    pasta_abs = os.path.join(BASE, pasta_rel)
    nome = os.path.basename(pasta_rel)
    videos = [m["arquivo"] for m in p["_midias_raw"] if m["ext"] in ("mp4", "mov", "m4v")]
    imagens = [m["arquivo"] for m in p["_midias_raw"]
               if m["ext"] in ("webp", "jpg", "jpeg", "png")]
    videos = [os.path.join(BASE, v) for v in videos]
    imagens = [os.path.join(BASE, i) for i in imagens]
    tipo = "fcproj" if videos else "pcraft"
    if tipos == "video" and tipo != "fcproj":
        return {"post": nome, "tipo": "", "projeto": "", "status": "ignorado",
                "segundos": "0", "erro": ""}
    if tipos == "imagem" and tipo != "pcraft":
        return {"post": nome, "tipo": "", "projeto": "", "status": "ignorado",
                "segundos": "0", "erro": ""}
    alvo = os.path.join(pasta_abs, f"{nome}.{tipo}")
    if os.path.exists(alvo) and not forcar:
        return {"post": nome, "tipo": tipo, "projeto": os.path.relpath(alvo, BASE),
                "status": "existente", "segundos": "0", "erro": ""}

    inicio = time.time()
    opcoes = opcoes or {}
    if tipo == "fcproj":
        titulo, subtitulo = titulo_e_subtitulo(p)
        dados = {"titulo": titulo, "subtitulo": subtitulo,
                 "logo": opcoes.get("logo")}
        if os.path.exists(opcoes.get("modelo") or MODELO):
            ok, erro = gerar_com_modelo(nome, pasta_abs, videos, dados,
                                        achar_musica(opcoes.get("musica"), nome),
                                        opcoes.get("ending"))
        else:
            ok, erro = gerar_filmcraft(nome, pasta_abs, videos, imagens, p["url"],
                                       tamanho_sequencia(p))
    else:
        ok, erro = gerar_photocraft(nome, pasta_abs, imagens,
                                    tamanho_sequencia(p), linked)
    dur = time.time() - inicio
    return {"post": nome, "tipo": tipo,
            "projeto": os.path.relpath(alvo, BASE) if ok else "",
            "status": "ok" if ok else "erro", "segundos": f"{dur:.1f}", "erro": erro}


def verificar(n: int, fila: dict[str, dict]) -> None:
    prontos = [r for r in fila.values() if r["status"] == "ok"]
    amostra = random.sample(prontos, min(n, len(prontos)))
    falhas = 0
    for r in amostra:
        cam = os.path.join(BASE, r["projeto"])
        if r["tipo"] == "fcproj":
            codigo, out, err = rodar([FILMCRAFT, "--project", cam, "inspect"], timeout=120)
            ok = codigo == 0 and '"activeSequence"' in out
        else:
            codigo, out, err = rodar([PHOTOCRAFT, "info", cam], timeout=120)
            ok = codigo == 0 and out.strip().startswith("{")
        print(f"  {'ok  ' if ok else 'FALHA'} {os.path.basename(cam)}")
        if not ok:
            falhas += 1
            print(f"        {err.strip()[:160]}")
    print(f"{len(amostra) - falhas}/{len(amostra)} projetos abrem")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--limite", type=int)
    ap.add_argument("--pilar")
    ap.add_argument("--desde", type=int)
    ap.add_argument("--tipo", choices=["video", "imagem", "todos", "corte"], default="todos",
                    help="corte: gera projetos a partir de _Cortes/")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--linked", action="store_true",
                    help="PhotoCraft: placeLinked (projeto leve, depende do arquivo)")
    ap.add_argument("--verificar", type=int, default=0)
    ap.add_argument("--selecao", help="JSON exportado pelo painel.html (ou lista de pastas)")
    ap.add_argument("--modelo", default=MODELO, help=".fcproj base (novo modelo)")
    ap.add_argument("--ending", default=os.path.join(ENDINGS, "enceramento1.mp4"))
    ap.add_argument("--musica", help="arquivo ou pasta com a trilha do Pixabay")
    ap.add_argument("--logo", default="/run/media/doykoy/SDD/Projetos BCN/Imagens/bcn.png")
    ap.add_argument("--sem-silencio", nargs="?", const=-30.0, type=float, default=None,
                    help="remove os silêncios medidos no áudio (limiar em dB, padrão -30)")
    ap.add_argument("--corte", action="append", default=[],
                    help="um corte de _Cortes pelo nome do arquivo (repita)")
    ap.add_argument("--post", action="append", default=[],
                    help="um post pelo nome da pasta (repita para varios)")
    a = ap.parse_args()

    midias, _, _ = bcnlib.coletar(BASE)
    posts = bcnlib.agrupar_posts([m for m in midias if m.get("organizado")])
    for p in posts:
        p["_midias_raw"] = [m for m in midias
                            if m.get("organizado") and m["post_id"] == p["post_id"]]
    if a.selecao:
        escolhidos = carregar_selecao(a.selecao)
        posts = [p for p in posts if os.path.basename(pasta_do_post(p)) in escolhidos]
    if a.post:
        querem = set(a.post)
        posts = [p for p in posts if os.path.basename(pasta_do_post(p)) in querem]
    if a.pilar:
        posts = [p for p in posts if p["pilar"] == a.pilar.upper()]
    if a.desde:
        posts = [p for p in posts if int(p["data"][:4]) >= a.desde]
    if a.tipo == "video":
        posts = [p for p in posts if any(m["ext"] in ("mp4", "mov", "m4v")
                                         for m in p["_midias_raw"])]
    elif a.tipo == "imagem":
        posts = [p for p in posts if not any(m["ext"] in ("mp4", "mov", "m4v")
                                             for m in p["_midias_raw"])]
    if a.limite:
        posts = posts[:a.limite]

    fila = carregar_fila()

    if a.tipo == "corte":
        cortes = bcnlib.coletar_cortes(BASE)
        if a.corte:
            querem = set(a.corte)
            cortes = [c for c in cortes
                      if os.path.basename(c["arquivo"]) in querem or c["arquivo"] in querem]
        if a.pilar:
            cortes = [c for c in cortes if c["pilar"] == a.pilar.upper()]
        if a.limite:
            cortes = cortes[:a.limite]
        opcoes = {"ending": a.ending if os.path.exists(a.ending) else None,
                  "musica": a.musica, "logo": a.logo if os.path.exists(a.logo) else None,
                  "sem_silencio": a.sem_silencio}
        print(f"{len(cortes)} cortes · workers={a.workers} · "
              f"{'APLICANDO' if a.aplicar else 'DRY-RUN'}")
        if not a.aplicar:
            for c in cortes[:10]:
                print(f"  fcproj  {c['segundos']:>6.1f}s  {c['pilar']:<11} {c['tema'][:40]}")
            if len(cortes) > 10:
                print(f"  ... +{len(cortes) - 10}")
            print("\nUse --aplicar.")
            return
        inicio = time.time()
        status: list[str] = []
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
            futuros = {pool.submit(tarefa_corte, c, a.forcar, opcoes,
                                   nome_do_corte(c)): c for c in cortes}
            for fut in as_completed(futuros):
                r = fut.result()
                fila[r["post"]] = r
                status.append(r["status"])
                if r["status"] == "erro":
                    print(f"  ERRO {r['post']}: {r['erro'][:120]}")
        gravar_fila(fila)
        from collections import Counter
        c_ = Counter(status)
        print(f"\ncortes: {c_.get('ok', 0)} criados · {c_.get('existente', 0)} já existiam"
              f" · {c_.get('erro', 0)} erros · {time.time() - inicio:.0f}s")
        return

    if a.verificar:
        verificar(a.verificar, fila)
        return

    print(f"{len(posts)} posts na fila · workers={a.workers} · "
          f"{'APLICANDO' if a.aplicar else 'DRY-RUN'}")
    if not a.aplicar:
        for p in posts[:12]:
            pasta = pasta_do_post(p)
            tem_video = any(m["ext"] in ("mp4", "mov", "m4v") for m in p["_midias_raw"])
            print(f"  {'fcproj' if tem_video else 'pcraft'}  {tamanho_sequencia(p)}  "
                  f"{os.path.basename(pasta)}")
        if len(posts) > 12:
            print(f"  ... +{len(posts) - 12}")
        print("\nUse --aplicar. Modelo em MODELO_PROJETOS.md")
        return

    inicio = time.time()
    feitos = 0
    desta_rodada: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        opcoes = {"modelo": a.modelo, "ending": a.ending if os.path.exists(a.ending) else None,
                  "musica": a.musica, "logo": a.logo if os.path.exists(a.logo) else None}
        futuros = {pool.submit(tarefa, p, a.tipo, a.linked, a.forcar, opcoes): p
                   for p in posts}
        for fut in as_completed(futuros):
            r = fut.result()
            anterior = fila.get(r["post"], {})
            if r["status"] == "existente" and anterior.get("status") == "ok":
                r["status"] = "ok"          # já criado numa rodada anterior
                r["segundos"] = anterior.get("segundos", "0")
            fila[r["post"]] = r
            desta_rodada.append(r["status"])
            feitos += 1
            if r["status"] == "erro":
                print(f"  ERRO {r['post']}: {r['erro'][:120]}")
            if feitos % 25 == 0:
                gravar_fila(fila)
                print(f"  {feitos}/{len(posts)} · {time.time() - inicio:.0f}s")
    gravar_fila(fila)

    from collections import Counter
    c = Counter(desta_rodada)
    print(f"\nesta rodada: {c.get('ok', 0)} criados · {c.get('existente', 0)} já existiam · "
          f"{c.get('erro', 0)} erros · {c.get('ignorado', 0)} fora do filtro · "
          f"{time.time() - inicio:.0f}s")
    prontos = sum(1 for r in fila.values() if r["status"] in ("ok", "existente")
                  and r.get("projeto"))
    print(f"na fila total: {prontos} projetos no disco")
    print(f"fila: {FILA}")


if __name__ == "__main__":
    main()
