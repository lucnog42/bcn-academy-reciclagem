#!/usr/bin/env python3
"""Modelo FilmCraft — constrói um .fcproj a partir do projeto base do usuário.

O base da marca (`montagem.modelo_fcproj` em config/marcas/<marca>/identidade.toml, um projeto
real do FilmCraft feito à mão) define:

    V1  vídeo do post → transição motion_camera (1 s) → vídeo de _endings → dip_to_black
    V2  Shape (abertura, 0–6 s)
    V3  Lower Third – Slab (título + subtítulo, 0–6 s)
    V4  logo da marca (entra em 6 s)
    A4  áudio do vídeo (+ DeEsser quando há legenda) e do ending
    A5  SFX: whoosh na abertura e no fim do título, notification, riser
    A6  riser de alta energia antes do ending
    C1  legendas — no máximo 4 palavras por cartela (novo)

Tudo é reescrito no JSON preservando ids e efeitos do base; as únicas coisas
calculadas são tempos, caminhos, mídia (info vinda do `filmcraft-cli probe`) e
os textos.
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import copy
import json
import os
import re
import subprocess
import sys
from transcricao import legendas  # noqa: E402

TICKS = 254_016_000_000          # ticks por segundo
FIM_TITULO = 6.0                 # abertura sem fala legendada
FIM_TITULO_COM_FALA = 4.0        # com legenda ativa a abertura encurta
MAX_PALAVRAS = 4                 # legenda: no máximo 4 palavras por vez
TITULO_IDX, SUBTITULO_IDX = 5, 6  # posição dos dois graphic_text no Lower Third
MUSICA_DB = -18.0
SFX_ANTES_ENDING = 2.2


def ticks(seg: float) -> int:
    return int(round(seg * TICKS))


def seg(t: int) -> float:
    return t / TICKS


def probe(caminho: str) -> dict:
    r = subprocess.run(["filmcraft-cli", "probe", caminho], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"probe falhou em {caminho}: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout)


# ------------------------------------------------------------------ mídia
def item_midia(item: dict, caminho: str, info: dict) -> dict:
    """Reescreve um item do bin para apontar para outro arquivo."""
    novo = copy.deepcopy(item)
    novo["name"] = os.path.basename(caminho)
    media = novo["kind"]["Media"]
    media["media"] = {"File": {"path": caminho}}
    media["info"] = {k: info.get(k) for k in
                     ("name", "kind", "duration", "video", "audio_streams",
                      "container", "start_timecode", "file_size")}
    media["identity"] = None          # deixa o app refingerprintar
    return novo


def clipe(caminho: str, item_id: int, inicio: int, duracao: int) -> dict:
    """Clipe de mídia com os efeitos padrão que o FilmCraft cria ao inserir."""
    return {
        "id": item_id + 1000, "item": item_id, "name": os.path.basename(caminho),
        "label": "Iris", "start": inicio, "duration": duracao, "source_in": 0,
        "speed": 1.0, "reverse": False, "enabled": True, "link": None, "group": None,
        "effects": [], "markers": [], "gain_db": 0.0, "frame_hold": None,
        "scale_to_frame": False, "graphic": None,
    }


# --------------------------------------------------------------- legendas
def ler_srt(caminho: str) -> list[tuple[float, float, str]]:
    """[(início, fim, texto)] de um .srt."""
    if not os.path.exists(caminho):
        return []
    bruto = open(caminho, encoding="utf-8", errors="replace").read()
    cues = []
    for bloco in re.split(r"\n\s*\n", bruto.strip()):
        linhas = [l for l in bloco.splitlines() if l.strip()]
        if len(linhas) < 2:
            continue
        marca = next((l for l in linhas if "-->" in l), None)
        if not marca:
            continue
        ini, fim = [x.strip() for x in marca.split("-->")[:2]]
        def s(hms: str) -> float:
            h, m, resto = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + float(resto.replace(",", "."))
        texto = " ".join(l.strip() for l in linhas[linhas.index(marca) + 1:])
        if texto:
            cues.append((s(ini), s(fim), texto))
    return cues


def cartelas(cues: list[tuple[float, float, str]],
             maximo: int = MAX_PALAVRAS) -> list[tuple[int, int, str]]:
    """Cues de um .srt -> cartelas em ticks. O .srt novo (legendar.py) já vem
    com ≤ 4 palavras presas à fala, então passa direto. Só um .srt antigo, com
    cue longo, ainda é dividido por proporção (sem tempo por palavra não há
    nada melhor) — e sem esticar nada."""
    saida = []
    for ini, fim, texto in cues:
        palavras = texto.split()
        if not palavras or fim <= ini:
            continue
        if len(palavras) <= maximo:
            saida.append((ticks(ini), ticks(fim - ini), texto))
            continue
        total, dur = len(palavras), fim - ini
        for i in range(0, total, maximo):
            trecho = palavras[i:i + maximo]
            comeco = ini + (i / total) * dur
            saida.append((ticks(comeco), ticks(len(trecho) / total * dur), " ".join(trecho)))
    return saida


def cartelas_de_palavras(palavras: list[tuple[float, float, str]],
                         trechos: list[tuple[float, float]] | None = None,
                         fps: float | None = None) -> list[tuple[int, int, str]]:
    """Cartelas direto do `.words.json`: as palavras vão primeiro para a
    timeline cortada (cada uma no seu trecho) e só depois são agrupadas — assim
    um corte de silêncio nunca deixa a legenda atravessada sobre outra fala."""
    no_corte = legendas.mapear_palavras(palavras, trechos)
    return [(ticks(a), ticks(b - a), t) for a, b, t in legendas.cartelas(no_corte, fps=fps)]


def caber(params: dict, texto: str, limite: int = 20) -> None:
    """Escreve o texto e encolhe o corpo se ele passar da largura do quadro —
    o Lower Third não quebra linha, então o título longo cortava na borda."""
    params["text"]["value"]["Text"] = texto
    atual = (params.get("size", {}).get("value", {}).get("Float") or 62.0)
    if len(texto) > limite:
        fator = max(0.55, limite / len(texto))
        params["size"]["value"]["Float"] = round(atual * fator, 1)


def ordenar_cartelas(cues: list[tuple[int, int, str]],
                     folga: int = TICKS // 100) -> list[tuple[int, int, str]]:
    """Cartelas não podem se sobrepor: o FilmCraft recusa editar o projeto inteiro
    quando duas legendas se cruzam. Quando encostam, quem cede é o FIM da
    anterior — a entrada de cada cartela é o tempo da fala e não se move.
    (Antes a seguinte era empurrada para frente e o atraso se acumulava.)"""
    saida: list[list] = []
    for ini, dur, txt in sorted(cues):
        if dur <= 0:
            continue
        if saida:
            ant = saida[-1]
            if ant[0] + ant[1] > ini - folga:
                ant[1] = max(folga, ini - folga - ant[0])
        saida.append([ini, dur, txt])
    return [(i, d, t) for i, d, t in saida]


def estilo_legenda() -> dict:
    # 40 pt garante 4 palavras em UMA linha no quadro 1080×1920 (medido no render);
    # base a 16% da borda para não ficar sob a interface do Instagram.
    # `background: true` sozinho não desenha nada no render: quem liga a caixa é
    # o `background_size`. Sem ele a legenda sai branca lisa e some em fundo claro.
    return {"font": "Inter", "size": 40.0, "color": [255, 255, 255, 255],
            "background": True, "background_color": [0, 0, 0, 170],
            "background_size": 12.0,
            "align": "Center", "anchor": "Bottom", "margin": 0.16,
            "line_spacing": 1.15, "outline": 2.0, "outline_color": [0, 0, 0, 255],
            "font_style": "Bold"}


def subir_titulo(vt: dict, delta: float) -> None:
    """Sobe o lower third (e só ele) quando há legenda: a abertura passa a
    conviver com o texto falado em vez de cobrir a primeira cartela.

    O lower third do modelo é animado: quem manda no render são os keyframes de
    `momentos.position`, não o valor estático. Mexer só no valor estático não move
    um pixel — a posição tem de ser subtraída em cada keyframe também.
    """
    if 3 not in vt:
        return
    for efeito in vt[3]["items"][0].get("effects", []):
        if efeito["effect"] != "motion":
            continue
        pos = efeito["params"]["position"]
        pos["value"]["Vec2"]["y"] = round(pos["value"]["Vec2"]["y"] - delta, 1)
        for kf in pos.get("keyframes") or []:
            v = kf.get("value", {}).get("Vec2")
            if v:
                v["y"] = round(v["y"] - delta, 1)


def ajustar_titulo_para_legenda(vt: dict, altura_quadro: int) -> float:
    """Quanto o título precisa subir para não encostar na legenda.

    Medido no render de 1080×1920: o lower third termina em y=1553 e a caixa da
    legenda começa em 1553 — zero de folga. Subir 0.035 da altura (~67 px) deixa
    respiro sem jogar o título para o meio do quadro.
    """
    delta = round(altura_quadro * 0.035, 1)
    subir_titulo(vt, delta)
    return delta


def sem_sobreposicao(trilha: dict, folga: int = 0) -> None:
    """Empurra clipes para a direita até não encavalarem. Um projeto com itens
    sobrepostos na mesma faixa é inválido — o FilmCraft recusa qualquer edição."""
    itens = sorted(trilha.get("items", []), key=lambda c: c.get("start", 0))
    fim = 0
    for cl in itens:
        alvo = max(cl.get("start", 0), fim + folga)
        cl["start"] = alvo
        fim = alvo + cl.get("duration", 0)
    trilha["items"] = itens


def preencher_quadro(cl: dict, largura_fonte: int, altura_fonte: int,
                     canvas_w: int, canvas_h: int) -> None:
    """Escala o clipe para cobrir o quadro inteiro (cover), sem ampliar além do
    necessário e sem deixar tarja: é o "ocupar toda a cena, nem mais nem menos"."""
    if not largura_fonte or not altura_fonte:
        return
    escala = max(canvas_w / largura_fonte, canvas_h / altura_fonte) * 100
    for efeito in cl.get("effects", []):
        if efeito["effect"] != "motion":
            continue
        p = efeito["params"]
        p["anchor"]["value"]["Vec2"] = {"x": largura_fonte / 2, "y": altura_fonte / 2}
        p["position"]["value"]["Vec2"] = {"x": canvas_w / 2, "y": canvas_h / 2}
        p["scale"]["value"]["Float"] = round(escala, 2)
        p["uniform_scale"]["value"]["Bool"] = True


def deesser() -> dict:
    return {"effect": "deesser", "enabled": True, "params": {
        "frequency": {"value": {"Float": 6000.0}},
        "reduction": {"value": {"Float": 8.0}},
        "threshold": {"value": {"Float": -12.0}}}}


# --------------------------------------------------- remoção de silêncios
def detectar_silencias(video: str, ruido_db: float = -32.0,
                       minimo: float = 0.55) -> list[tuple[float, float]]:
    """[(início, fim)] dos trechos mudos, medidos no áudio com ffmpeg."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-vn",
         "-af", f"silencedetect=noise={ruido_db}dB:d={minimo}", "-f", "null", "-"],
        capture_output=True, text=True)
    bruto = r.stderr or ""
    inicios = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", bruto)]
    fins = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", bruto)]
    return [(ini, fins[i] if i < len(fins) else ini + minimo)
            for i, ini in enumerate(inicios)]


def trechos_com_fala(video: str, duracao: float | None = None, srt: str | None = None,
                     ruido_db: float = -30.0, minimo: float = 0.45,
                     folga: float = 0.18, pre: float = 0.25, pos: float = 0.35,
                     juntar: float = 0.60, minimo_trecho: float = 0.30,
                     fps: float = 24.0) -> list[tuple[float, float]]:
    """Trechos que ficam no corte.

    Duas medidas, porque uma sozinha mente neste material:
      * o .srt diz onde há fala — é o que pega o vazio longo (20 s de treino
        sem ninguém falar continua com barulho de bola acima de -30 dB);
      * o ffmpeg diz onde há silêncio de verdade — é o que pega a pausa curta
        dentro de um cue só (o Whisper cola 30 s de fala num cue único).
    O corte é a fala do srt menos os silêncios medidos, com `folga` de respiro
    em cada borda: cortar no osso come a primeira e a última sílaba.
    """
    if duracao is None:
        duracao = seg(probe(video)["duration"])
    quadro = 1.0 / fps

    base: list[tuple[float, float]] = []
    for ini, fim, _ in ler_srt(srt) if srt else []:
        a, b = max(0.0, ini - pre), min(duracao, fim + pos)
        if base and a - base[-1][1] < juntar:
            base[-1] = (base[-1][0], max(base[-1][1], b))
        else:
            base.append((a, b))
    if not base:
        base = [(0.0, duracao)]

    silencios = detectar_silencias(video, ruido_db, minimo)
    blocos: list[tuple[float, float]] = []
    for a, b in base:
        cursor = a
        for si, sf in silencios:
            if sf <= a or si >= b:
                continue
            corte_ini, corte_fim = max(a, si + folga), min(b, sf - folga)
            if corte_fim - corte_ini < minimo_trecho or corte_ini <= cursor:
                continue
            if corte_ini - cursor >= minimo_trecho:
                blocos.append((cursor, corte_ini))
            cursor = corte_fim
        if b - cursor >= minimo_trecho:
            blocos.append((cursor, b))

    # alinhamento no quadro: corte em tempo que não é frame inteiro serrilha
    saida: list[tuple[float, float]] = []
    for a, b in blocos:
        a = round(a / quadro) * quadro
        b = round(b / quadro) * quadro
        a = max(0.0, min(a, duracao))
        b = max(a + quadro, min(b, duracao))
        if saida and a <= saida[-1][1]:
            a = saida[-1][1] + quadro
        if b - a >= minimo_trecho:
            saida.append((round(a, 4), round(b, 4)))
    return saida


def mapear_tempo(t: float, trechos: list[tuple[float, float]]) -> float:
    """Tempo de origem → tempo na timeline cortada. Quem cai num silêncio
    removido encosta no começo do trecho seguinte (legenda colada na fala)."""
    acumulado = 0.0
    for a, b in trechos:
        if t < a:
            return acumulado
        if t <= b:
            return acumulado + (t - a)
        acumulado += b - a
    return acumulado


def _proximo_id(usados: set[int]) -> int:
    n = max(usados) + 1
    usados.add(n)
    return n


def _usados(projeto: dict) -> set[int]:
    itens = projeto["project"]["items"]
    k = _seq(projeto)
    usados = {int(i) for i in itens if str(i).isdigit()}
    usados.add(int(projeto["project"].get("next_id") or 0) - 1)
    for trilha in k["video_tracks"] + k["audio_tracks"]:
        usados.add(int(trilha["id"]))
        for cl in trilha["items"]:
            usados.add(int(cl["id"]))
    for cap in k.get("caption_tracks") or []:
        usados.add(int(cap["id"]))
        for c in cap["captions"]:
            usados.add(int(c["id"]))
    return usados


def _seq(projeto: dict) -> dict:
    for v in projeto["project"]["items"].values():
        if isinstance(v.get("kind"), dict) and "Sequence" in v["kind"]:
            return v["kind"]["Sequence"]
    raise RuntimeError("projeto sem sequência")


def pecas_de(item_id: int, trechos) -> list[dict]:
    """Trechos de um vídeo -> peças da timeline. Um trecho é (a, b) — áudio e imagem
    juntos — ou (a, b, va, vb): o áudio é a..b e a IMAGEM é va..vb (J/L-cut: a imagem
    entra depois ou antes do som, sem mudar a duração total)."""
    out = []
    for t in trechos:
        a, b = float(t[0]), float(t[1])
        va, vb = (float(t[2]), float(t[3])) if len(t) >= 4 else (a, b)
        if b - a > 0 and vb - va > 0:
            out.append({"item": item_id, "a": a, "b": b, "va": va, "vb": vb})
    return out


def montar_principal(projeto: dict, pecas: list[dict], antigo: int | None = None) -> int:
    """Troca o clipe principal (V1 + A1) por uma sequência de peças, encostadas, cada
    uma com `source_in` na origem e o vídeo e o áudio vinculados. Com J/L, a imagem
    da peça começa/termina deslocada do som dela. Devolve a duração nova, em ticks.

    Tudo que era relativo ao fim do vídeo (riser, ending, transições, música) anda
    junto; abertura, logo e SFX de abertura ficam onde estão.
    """
    itens = projeto["project"]["items"]
    k = _seq(projeto)
    vt = {t["id"]: t for t in k["video_tracks"]}
    at = {t["id"]: t for t in k["audio_tracks"]}
    v1, a1 = vt[1], at[4]
    cl_v, cl_a = v1["items"][0], a1["items"][0]
    resto_v, resto_a = v1["items"][1:], a1["items"][1:]
    antigo = cl_v["duration"] if antigo is None else antigo
    usados = _usados(projeto)

    def novo_id() -> int:
        n = max(usados) + 1
        usados.add(n)
        return n

    novos_v, novos_a, cum = [], [], 0
    for p in pecas:
        dur = ticks(p["b"]) - ticks(p["a"])
        if dur <= 0:
            continue
        nome = itens[str(p["item"])]["name"]
        vid = novo_id()
        cv = copy.deepcopy(cl_v)
        cv.update(id=vid, item=p["item"], name=nome, link=vid,
                  start=cum + ticks(p["va"]) - ticks(p["a"]),
                  duration=ticks(p["vb"]) - ticks(p["va"]), source_in=ticks(p["va"]))
        ca = copy.deepcopy(cl_a)
        ca.update(id=novo_id(), item=p["item"], name=nome, link=vid,
                  start=cum, duration=dur, source_in=ticks(p["a"]))
        novos_v.append(cv)
        novos_a.append(ca)
        cum += dur
    if not novos_v:
        return antigo
    # a 1ª imagem nunca começa antes de 0 nem a última passa do fim do som
    novos_v[0]["duration"] -= max(0, -novos_v[0]["start"])
    novos_v[0]["start"] = max(0, novos_v[0]["start"])
    fim_v = novos_v[-1]["start"] + novos_v[-1]["duration"]
    if fim_v > cum:
        novos_v[-1]["duration"] -= fim_v - cum

    v1["items"] = novos_v + resto_v
    a1["items"] = novos_a + resto_a
    delta = cum - antigo

    for cl in resto_v + resto_a:
        cl["start"] += delta
    for trans in v1.get("transitions") or []:
        if trans.get("from") == cl_v["id"]:
            trans["from"] = novos_v[-1]["id"]
            trans["start"] = cum - trans["duration"] // 2
        else:
            trans["start"] += delta
    for tid, trilha in at.items():
        if tid == 4:
            continue
        for cl in trilha["items"]:
            if "riser" in cl.get("name", "").lower():
                cl["start"] = max(0, cl["start"] + delta)
    for trilha in k["audio_tracks"]:
        if trilha.get("name") == "Música" and trilha["items"]:
            trilha["items"][0]["duration"] = max(0, cum + sum(cl["duration"] for cl in resto_a))
    projeto["project"]["next_id"] = max(usados) + 1
    return cum


def cortar_silencio(projeto: dict, trechos, remapear_legendas: bool = True) -> int:
    """Corta o silêncio do vídeo único do projeto (compatível com o uso antigo)."""
    k = _seq(projeto)
    v1 = {t["id"]: t for t in k["video_tracks"]}[1]
    cum = montar_principal(projeto, pecas_de(v1["items"][0]["item"], trechos))
    if remapear_legendas:
        so_audio = [(t[0], t[1]) for t in trechos]
        for cap in k.get("caption_tracks") or []:
            novas = []
            for c in cap["captions"]:
                ini = mapear_tempo(seg(c["start"]), so_audio)
                fim = mapear_tempo(seg(c["start"] + c["duration"]), so_audio)
                if fim - ini >= 0.1:
                    novas.append((ticks(ini), ticks(fim - ini), c))
            arrumadas = ordenar_cartelas([(i, d, id(c)) for i, d, c in novas])
            por_id = {id(c): c for _, _, c in novas}
            cap["captions"] = []
            for i, d, chave in arrumadas:
                c = por_id[chave]
                c["start"], c["duration"] = i, d
                cap["captions"].append(c)
    return cum


def palavras_na_timeline(videos: list[dict]) -> list[tuple[float, float, str]]:
    """Palavras de vários vídeos, cada um no seu lugar da timeline: o vídeo k começa
    onde o anterior terminou (já sem os silêncios cortados)."""
    saida, off = [], 0.0
    for v in videos:
        trechos = [(t[0], t[1]) for t in v["trechos"]] if v.get("trechos") else None
        for a, b, t in legendas.mapear_palavras(v.get("palavras") or [], trechos):
            saida.append((round(a + off, 3), round(b + off, 3), t))
        off += sum(t[1] - t[0] for t in trechos) if trechos else v["duracao"]
    return saida


# ------------------------------------------------------------ construção
def construir(template: dict, dados: dict) -> dict:
    """Devolve o projeto pronto. `template` é o JSON do base já carregado."""
    proj = copy.deepcopy(template)
    itens = proj["project"]["items"]

    # --- mídia principal: um ou mais vídeos (uma pasta de cortes vira uma timeline só)
    videos = dados.get("videos") or [{"video": dados["video"], "trechos": dados.get("trechos")}]
    modelo_item = itens["8"]
    pecas: list[dict] = []
    for n, v in enumerate(videos):
        info = probe(v["video"])
        if n == 0:
            iid = 8
        else:
            # ids altos: as faixas (44...) e as cartelas (100 + n) usam a faixa baixa
            iid = max(5000, max(int(i) for i in itens if str(i).isdigit()) + 1)
        novo = item_midia(modelo_item, v["video"], info)
        novo["id"] = iid
        if "created" in novo:
            novo["created"] = iid
        itens[str(iid)] = novo
        if n and {"Item": iid} not in proj["project"]["root"]["children"]:
            proj["project"]["root"]["children"].append({"Item": iid})
        dur = seg(info["duration"])
        v["duracao"] = dur
        pecas += pecas_de(iid, v.get("trechos") or [(0.0, dur)])
    dur_v_t = sum(ticks(p["b"]) - ticks(p["a"]) for p in pecas)
    dur_v = seg(dur_v_t)

    if dados.get("ending"):
        info_e = probe(dados["ending"])
        itens["26"] = item_midia(itens["26"], dados["ending"], info_e)
        dur_e_t = itens["26"]["kind"]["Media"]["info"]["duration"]
    else:
        dur_e_t = 0
    dur_total = (dur_v_t + dur_e_t) / TICKS

    seqs = [v for v in itens.values()
            if isinstance(v.get("kind"), dict) and "Sequence" in v["kind"]]
    if not seqs:
        raise RuntimeError("template sem sequência")
    k = seqs[0]["kind"]["Sequence"]
    vt = {t["id"]: t for t in k["video_tracks"]}
    at = {t["id"]: t for t in k["audio_tracks"]}

    # --- V1: vídeo + encerramento + transições
    v1 = vt[1]
    v1["items"][0]["duration"] = dur_v_t
    if dur_e_t:
        v1["items"][1]["start"] = dur_v_t
        v1["items"][1]["duration"] = dur_e_t
    else:
        v1["items"] = v1["items"][:1]
    for trans in v1.get("transitions", []):
        if trans.get("from") == v1["items"][0]["id"] and trans.get("to"):
            trans["start"] = dur_v_t - trans["duration"] // 2      # CenterAtCut
        else:
            trans["start"] = dur_v_t + dur_e_t - trans["duration"]  # EndAtCut

    # --- enquadramento: cobre o quadro inteiro, sem ampliar sobrando nem faltando
    canvas_w = int(k["settings"].get("width") or 1080)
    canvas_h = int(k["settings"].get("height") or 1920)
    for cl in v1["items"]:
        info = itens[str(cl["item"])]["kind"]["Media"]["info"].get("video") or {}
        preencher_quadro(cl, int(info.get("width") or 0), int(info.get("height") or 0),
                         canvas_w, canvas_h)

    # --- V2/V3: abertura (título + subtítulo)
    alvo_abertura = FIM_TITULO_COM_FALA if dados.get("legendas") else FIM_TITULO
    abertura_t = ticks(min(alvo_abertura, max(2.0, dur_v - 1)))
    for tid in (2, 3):
        if tid in vt:
            vt[tid]["items"][0]["duration"] = abertura_t
    if 3 in vt:
        efeitos = vt[3]["items"][0]["effects"]
        textos = [(i, e) for i, e in enumerate(efeitos) if e["effect"] == "graphic_text"]
        if len(textos) >= 2:
            caber(textos[0][1]["params"], dados.get("titulo", ""), limite=20)
            caber(textos[1][1]["params"], dados.get("subtitulo", ""), limite=30)

    # --- V4: logo, logo depois do título
    if 24 in vt and dados.get("logo"):
        logo = vt[24]["items"][0]
        logo["start"] = abertura_t
        logo["duration"] = ticks(max(1.0, min(seg(dur_v_t) - FIM_TITULO, seg(logo["duration"]))))
        itens[str(logo["item"])] = item_midia(itens[str(logo["item"])],
                                              dados["logo"], probe(dados["logo"]))
    elif 24 in vt:
        vt[24]["items"] = []

    # --- vínculo A/V: o clipe de vídeo e o de áudio precisam do mesmo grupo,
    # senão o volume do vídeo não aparece para edição (o áudio fica solto na A1)
    for cl in v1["items"][:1]:
        cl["link"] = cl["id"] if cl["id"] else None

    # --- A4: áudio do vídeo (+ DeEsser quando há legenda) e do ending
    a1 = at[4]
    a1["items"][0]["duration"] = dur_v_t
    if dur_e_t and len(a1["items"]) > 1:
        a1["items"][1]["start"] = dur_v_t
        a1["items"][1]["duration"] = dur_e_t
    elif len(a1["items"]) > 1:
        a1["items"] = a1["items"][:1]
    if a1["items"]:
        a1["items"][0]["link"] = v1["items"][0]["id"]      # vídeo ↔ seu áudio
    # DeEsser: pedido do usuário — entra na faixa da MÚSICA quando há legenda
    # ativa, não no áudio do vídeo

    # --- SFX: realinha ao novo vídeo
    if 5 in at:
        for cl in at[5]["items"]:
            nome = cl.get("name", "").lower()
            if "riser" in nome:
                cl["start"] = max(0, dur_v_t - ticks(0.2))
            elif "whoosh" in nome:
                cl["start"] = 0 if cl["start"] < ticks(FIM_TITULO / 2) else abertura_t - ticks(0.4)
            elif "notification" in nome:
                cl["start"] = abertura_t + ticks(0.2)
    if 6 in at and at[6]["items"]:
        at[6]["items"][0]["start"] = max(0, dur_v_t - ticks(SFX_ANTES_ENDING))
    for tid in (5, 6):
        if tid in at:
            sem_sobreposicao(at[tid], folga=ticks(0.05))

    # --- legenda x abertura
    if dados.get("legendas"):
        ajustar_titulo_para_legenda(vt, int(k["settings"].get("height") or 1920))

    # --- legendas
    # legenda nunca é descartada: se o vídeo tem fala, o título sobe para dar lugar
    cues = ordenar_cartelas(list(dados.get("legendas") or []))
    k["caption_tracks"] = []
    if cues:
        k["caption_tracks"].append({
            "id": 44, "name": "Legendas", "format": "Subtitle", "language": "pt",
            "style": estilo_legenda(), "enabled": True, "locked": False,
            "sync_lock": True, "vtt_blocks": [],
            "captions": [{"id": 100 + i, "start": ini, "duration": dur,
                          "text": txt, "speaker": None, "cue_id": None, "settings": ""}
                         for i, (ini, dur, txt) in enumerate(cues)],
        })

    # --- música (Pixabay), numa faixa própria, cortada no tamanho da sequência
    if dados.get("musica") and os.path.exists(dados["musica"]):
        info_m = probe(dados["musica"])
        novo_id = max(int(i) for i in itens if str(i).isdigit()) + 1
        itens[str(novo_id)] = {
            "id": novo_id, "name": os.path.basename(dados["musica"]), "label": "Green",
            "kind": {"Media": {"media": {"File": {"path": dados["musica"]}},
                               "info": {kk: info_m.get(kk) for kk in
                                        ("name", "kind", "duration", "video",
                                         "audio_streams", "container",
                                         "start_timecode", "file_size")},
                               "interpret": {"frame_rate": None, "par": None,
                                             "ignore_alpha": False, "invert_alpha": False},
                               "mark_in": None, "mark_out": None, "markers": [],
                               "offline": False, "proxy": None, "identity": None}},
            "metadata": {}, "created": novo_id}
        modelo = copy.deepcopy(at[5])
        modelo["id"] = novo_id + 1
        modelo["name"] = "Música"
        modelo["items"] = [{
            "id": novo_id + 2, "item": novo_id,
            "name": os.path.basename(dados["musica"]), "label": "Green",
            "start": 0, "duration": ticks(dur_total), "source_in": 0, "speed": 1.0,
            "reverse": False, "enabled": True, "link": None, "group": None,
            "effects": [{"effect": "volume", "enabled": True,
                         "params": {"level": {"value": {"Float": MUSICA_DB}}}}]
                        + ([deesser()] if dados.get("legendas") else []),
            "markers": [], "gain_db": 0.0, "frame_hold": None, "scale_to_frame": False,
        }]
        k["audio_tracks"].append(modelo)

    # --- os vídeos (inteiros ou só com a fala, com J/L) no lugar do clipe do modelo
    if len(pecas) > 1 or len(videos) > 1 or any(v.get("trechos") for v in videos):
        if len(videos) == 1 and videos[0].get("trechos") and not dados.get("legendas_na_timeline"):
            cortar_silencio(proj, videos[0]["trechos"], remapear_legendas=True)
        else:
            montar_principal(proj, pecas, antigo=dur_v_t)
        for cl in vt[1]["items"]:
            info = (itens[str(cl["item"])]["kind"]["Media"]["info"].get("video") or {})
            preencher_quadro(cl, int(info.get("width") or 0), int(info.get("height") or 0),
                             canvas_w, canvas_h)

    # sync lock do base bloqueia qualquer edição que empurre clipes de outra faixa
    # ("this edit would break sync: V2 is sync-locked and has a clip in the way")
    for trilha in (k["video_tracks"] + k["audio_tracks"] + k.get("caption_tracks", [])):
        trilha["sync_lock"] = False
        trilha["locked"] = False

    proj["project"]["name"] = dados["nome"]
    proj["project"]["root"]["name"] = dados["nome"]
    for v in itens.values():
        if isinstance(v.get("kind"), dict) and "Sequence" in v["kind"]:
            v["name"] = dados["nome"]
    proj["generator"] = "video-automation-ng3"
    return proj


def srt_do_post(pasta_post: str, base_acervo: str) -> str:
    """Caminho do .srt que espelha o vídeo do post."""
    rel = os.path.relpath(os.path.join(pasta_post, "videos", "01.mp4"), base_acervo)
    return os.path.join(base_acervo, "transcricoes", os.path.splitext(rel)[0] + ".srt")


def escrever(projeto: dict, caminho: str) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(projeto, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)
