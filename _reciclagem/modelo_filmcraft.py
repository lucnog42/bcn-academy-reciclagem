#!/usr/bin/env python3
"""Modelo FilmCraft — constrói um .fcproj a partir do projeto base do usuário.

O base (`_reciclagem/modelo_base.fcproj`, copiado do post
2025-07-24_MIC_copa-micfootball-2022-o-dia-que-a-bcn-sports-academy) define:

    V1  vídeo do post → transição motion_camera (1 s) → vídeo de _endings → dip_to_black
    V2  Shape (abertura, 0–6 s)
    V3  Lower Third – Slab (título + subtítulo, 0–6 s)
    V4  logo bcn.png (entra em 6 s)
    A4  áudio do vídeo (+ DeEsser quando há legenda) e do ending
    A5  SFX: whoosh na abertura e no fim do título, notification, riser
    A6  riser de alta energia antes do ending
    C1  legendas — no máximo 4 palavras por cartela (novo)

Tudo é reescrito no JSON preservando ids e efeitos do base; as únicas coisas
calculadas são tempos, caminhos, mídia (info vinda do `filmcraft-cli probe`) e
os textos.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess

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
    """Quebra cada cue em blocos de no máximo `maximo` palavras, dividindo o tempo
    proporcionalmente ao número de palavras — cabe no vídeo vertical, sem linha
    quebrada em três."""
    saida = []
    for ini, fim, texto in cues:
        palavras = texto.split()
        if not palavras:
            continue
        total = len(palavras)
        dur = max(fim - ini, 0.6)
        passo = dur / max(1, total / maximo)
        for i in range(0, total, maximo):
            trecho = palavras[i:i + maximo]
            começo = ini + (i / total) * dur
            fim_trecho = começo + len(trecho) / total * dur
            saida.append((ticks(começo), ticks(max(fim_trecho - começo, 0.5)),
                          " ".join(trecho)))
    return saida


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
    quando duas legendas se cruzam. Aqui cada uma começa depois do fim da anterior."""
    saida = []
    fim_anterior = -1
    for ini, dur, txt in sorted(cues):
        if ini <= fim_anterior:
            ini = fim_anterior + folga
        dur = max(dur, TICKS // 2)
        saida.append((ini, dur, txt))
        fim_anterior = ini + dur
    return saida


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
    `motion.position`, não o valor estático. Mexer só no valor estático não move
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


def cortar_silencio(projeto: dict, trechos: list[tuple[float, float]]) -> float:
    """Fatia o clipe principal nos `trechos` e remove o resto: cada trecho vira
    um clipe com `source_in` na origem, encostado no anterior (sem buraco).
    Devolve a duração nova do vídeo, em ticks.

    Tudo que era relativo ao fim do vídeo (riser, ending, transições) anda
    junto; abertura, logo e SFX de abertura ficam onde estão.
    """
    itens = projeto["project"]["items"]
    seqs = [v for v in itens.values()
            if isinstance(v.get("kind"), dict) and "Sequence" in v["kind"]]
    k = seqs[0]["kind"]["Sequence"]
    vt = {t["id"]: t for t in k["video_tracks"]}
    at = {t["id"]: t for t in k["audio_tracks"]}
    v1, a1 = vt[1], at[4]
    cl_v, cl_a = v1["items"][0], a1["items"][0]
    resto_v, resto_a = v1["items"][1:], a1["items"][1:]
    antigo = cl_v["duration"]

    usados = {int(i) for i in itens if str(i).isdigit()}
    for trilha in k["video_tracks"] + k["audio_tracks"]:
        usados.add(int(trilha["id"]))
        for cl in trilha["items"]:
            usados.add(int(cl["id"]))
    for cap in k.get("caption_tracks") or []:
        for c in cap["captions"]:
            usados.add(int(c["id"]))

    novos_v, novos_a, cum = [], [], 0
    for a, b in trechos:
        dur = ticks(b - a)
        if dur <= 0:
            continue
        vid = _proximo_id(usados)
        cv = copy.deepcopy(cl_v)
        cv.update(id=vid, start=cum, duration=dur, source_in=ticks(a), link=vid)
        ca = copy.deepcopy(cl_a)
        ca.update(id=_proximo_id(usados), start=cum, duration=dur,
                  source_in=ticks(a), link=vid)
        novos_v.append(cv)
        novos_a.append(ca)
        cum += dur
    if not novos_v:
        return antigo

    v1["items"] = novos_v + resto_v
    a1["items"] = novos_a + resto_a
    delta = cum - antigo

    # o que vinha depois do vídeo (ending) anda junto com o novo fim
    for cl in resto_v + resto_a:
        cl["start"] += delta

    # transições: a da entrada é CenterAtCut no último trecho, a do ending desloca
    for trans in v1.get("transitions") or []:
        if trans.get("from") == cl_v["id"]:
            trans["from"] = novos_v[-1]["id"]
            trans["start"] = cum - trans["duration"] // 2
        else:
            trans["start"] += delta

    # risers são ancorados no fim do vídeo; whoosh/notification ficam na abertura
    for tid, trilha in at.items():
        if tid == 4:
            continue
        for cl in trilha["items"]:
            if "riser" in cl.get("name", "").lower():
                cl["start"] = max(0, cl["start"] + delta)

    # trilha de música cobre a sequência inteira, ending incluído
    for trilha in k["audio_tracks"]:
        if trilha.get("name") == "Música" and trilha["items"]:
            trilha["items"][0]["duration"] = max(
                0, cum + sum(cl["duration"] for cl in resto_a))

    # legendas: remapeia para a timeline cortada e reordena sem sobreposição
    for cap in k.get("caption_tracks") or []:
        caps = cap["captions"]
        for c in caps:
            ini = mapear_tempo(seg(c["start"]), trechos)
            fim = mapear_tempo(seg(c["start"] + c["duration"]), trechos)
            c["start"] = ticks(ini)
            c["duration"] = ticks(max(fim - ini, 0.5))
        caps.sort(key=lambda c: c["start"])
        fim_anterior = -1
        for c in caps:
            if c["start"] <= fim_anterior:
                c["start"] = fim_anterior + TICKS // 100
            fim_anterior = c["start"] + c["duration"]
        cap["captions"] = caps

    return cum


# ------------------------------------------------------------ construção
def construir(template: dict, dados: dict) -> dict:
    """Devolve o projeto pronto. `template` é o JSON do base já carregado."""
    proj = copy.deepcopy(template)
    itens = proj["project"]["items"]

    # --- mídia principal e encerramento
    info_v = probe(dados["video"])
    itens["8"] = item_midia(itens["8"], dados["video"], info_v)
    dur_v = seg(itens["8"]["kind"]["Media"]["info"]["duration"])
    dur_v_t = itens["8"]["kind"]["Media"]["info"]["duration"]

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

    # --- silêncios: a timeline nasce já só com a fala
    if dados.get("trechos"):
        cortar_silencio(proj, dados["trechos"])

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
    proj["generator"] = "bcn_academy / modelo base 2025-07-24"
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
