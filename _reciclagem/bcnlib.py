#!/usr/bin/env python3
"""Núcleo compartilhado: leitura dos .json do 4K Stogram e classificação por pilar.

O scraper grava um .json ao lado de cada mídia, com sufixo duplicado
("foto.webp.json"). O nome do arquivo de mídia é a chave; o json traz o resto
(legenda, data, curtidas, tipo, local, tags, coautores).
"""
from __future__ import annotations

import csv
import json
import os
import re
import statistics
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTS_MIDIA = {".jpg", ".jpeg", ".webp", ".png", ".mp4", ".mov", ".m4v", ".webm"}
TRANSCRICOES = os.path.join(BASE, "transcricoes")
PESO_FALA = 0.8      # fala transcrita: conteúdo rico, mas com erro de ASR

# ---------------------------------------------------------------- pilares
# Rótulo vem da LEGENDA, não da ordem de uma lista. Cada pilar tem termos com
# peso (3 = específico do tema, 2 = contextual, 1 = fraco/ambíguo); o texto é
# lido em três zonas com multiplicadores diferentes:
#   1ª linha (gancho)  x2.0   — é onde o post diz do que trata
#   corpo              x1.0
#   hashtags           x1.2   — hashtag é rótulo declarado pelo autor
# Vence o pilar com maior evidência; a margem sobre o 2º vira `confianca`.
TERMOS: dict[str, dict[str, float]] = {
    "DEPOIMENTO": {
        "depoimento": 3, "nos contou": 3, "conta como foi": 3, "minha história": 3,
        "meu relato": 3, "mudou minha vida": 3, "realizou o sonho": 3,
        "sonho realizado": 3, "valeu cada segundo": 3, "melhor decisão": 3,
        "relato": 2, "testemunho": 2, "aprendi muito": 2, "valeu a pena": 2,
        "me eligió": 3, "sorte do mundo": 2.5,
        "recomendo": 2, "experiência que marcou": 2, "gratidão": 2,
        "agradecemos": 1.5, "obrigado": 0.5, "obrigada": 0.5, "agradeço": 0.5,
    },
    "MIC": {
        "micfootball": 3, "#micfootball": 3, "copa mic": 3, "wearemic": 3,
        "copa iber": 3, "mic 2022": 3, "mic 2023": 3, "mic 2024": 3, "mic 2025": 3,
        "torneio mic": 3, "mic football": 3, "mic cup": 3, "mic": 2, "lloret": 1.5,
    },
    "INTERCAMBIO": {
        "intercâmbio": 3, "intercambio": 3, "programa de intercâmbio": 3,
        "bolsa de estudos": 3, "bolsa integral": 3, "morar na espanha": 3,
        "estudar na espanha": 3, "residência": 3, "dni": 3, "visto de estudante": 3,
        "programa bcn": 3, "desafio barcelona": 3,
        "espanha": 2, "españa": 2, "marcet": 2, "temporada": 2, "acadêmica": 1.5,
        "academica": 1.5, "escola": 1.5, "programa": 1, "barcelona": 1,
        "fora do país": 1.5, "experiência internacional": 2, "sueño": 2,
        "fútbol internacional": 2, "instalaciones": 1.5,
    },
    "ATLETA": {
        "nosso atleta": 3, "novo clube": 3, "assinou com": 3, "contratado pelo": 3,
        "se apresentou ao": 3, "reforço do": 3, "rumo à espanha": 3,
        "rumo a espanha": 3, "rumo à europa": 3,
        "atleta": 2, "transferência": 2, "carreira": 1.5, "profissional": 1.5,
        "clube": 1, "jogador": 1, "cirurgia": 2, "recuperação": 2, "lesão": 2, "primeiros passos": 1.5,
    },
    "JOGO": {
        "gol de": 3, "golaço": 3, "placar": 3, "vitória por": 3, "campeão": 3,
        "título": 3, "classificado para": 3, "semifinal": 2.5, "quartas de final": 2.5,
        "adversário": 2, "enfrenta": 2, "gol": 2, "gols": 2, "jogo": 2, "partida": 2,
        "torneio": 2, "campeonato": 2, "estreia": 2, "sub-14": 1, "sub14": 1,
        "sub-16": 1, "sub16": 1, "sub-18": 1, "sub18": 1, "copa": 1.5,
        "equipe": 1, "time": 1, "resultado": 1.5, "ao vivo": 2, "transmitir": 1.5,
        "equipo": 1.5, "partido": 2, "entrenamiento": 1,
    },
    "AVALIACAO": {
        "avaliação": 3, "avaliações": 3, "peneira": 3, "seletiva": 3, "tryout": 3,
        "processo seletivo": 3, "inscrições abertas": 3, "aprovado na avaliação": 3,
        "aprovado": 2, "selecionado": 2, "candidato": 2, "inscrição": 2,
        "teste": 1.5, "vaga": 1, "inscreva": 1,
    },
    "BASTIDOR": {
        "bastidores": 3, "nos bastidores": 3, "primeiro dia": 2.5, "rotina de treino": 3,
        "visita ao estádio": 3, "tour pelo": 3,
        "treino": 2, "aeroporto": 2, "chegada": 2, "passeio": 2, "viagem": 2,
        "estádio": 2, "estadio": 2, "camp nou": 2, "tibidabo": 2, "cidade": 1,
        "camp day": 3, "tour": 2.5, "entrenamiento": 2, "conhecer de perto": 2,
        "churrasco": 2, "parrillada": 2, "instalações": 1.5,
        "dia a dia": 1.5, "conheça": 1, "alojamento": 1.5, "hotel": 1.5, "dia de treino": 2,
    },
    "DIVULGACAO": {
        "sorteio": 3, "sortearemos": 3, "convite": 3, "promoção": 3, "seja parceiro": 3,
        "garanta sua vaga": 3, "link na bio": 3, "vagas limitadas": 2.5,
        "comente": 2, "marque": 2, "compartilhe": 2, "chama no": 2, "whatsapp": 2,
        "direct": 2, "dm": 2, "inscreva-se": 2, "desconto": 2, "parceria": 2,
        "venha jogar": 1.5, "corre": 1, "últimas vagas": 1.5,
    },
}
PILAR_FALLBACK = "OUTROS"
SEM_LEGENDA = "SEM_LEGENDA"   # ausência de texto ≠ tema desconhecido


def pista_da_pasta(pasta: str) -> str:
    alvo = (pasta or "").lower()
    return next((pilar for chave, pilar in PISTA_PASTA if chave in alvo), "")
# último recurso, só quando a legenda não deu evidência suficiente
LOCAL_PILAR = {"marcet": "INTERCAMBIO", "camp nou": "BASTIDOR",
               "lloret": "MIC", "guineueta": "JOGO"}
EVIDENCIA_MINIMA = 2.5   # abaixo disso a legenda não sustenta rótulo
# Nome da pasta que o usuário organizou à mão é curadoria humana: só entra quando
# a legenda não decidiu (OUTROS/SEM_LEGENDA), nunca por cima do texto.
# Lista ORDENADA, do mais específico ao mais genérico: vence o primeiro que casar.
# "treino fernando marcet" é treino (BASTIDOR), não o programa Marcet.
PISTA_PASTA: tuple[tuple[str, str], ...] = (
    ("treino", "BASTIDOR"), ("passeio", "BASTIDOR"), ("aeroporto", "BASTIDOR"),
    ("assistindo", "BASTIDOR"), ("destaques", "BASTIDOR"), ("material", "BASTIDOR"),
    ("depoimento", "DEPOIMENTO"), ("salve", "DEPOIMENTO"),
    ("avaliacao", "AVALIACAO"), ("avaliação", "AVALIACAO"), ("cenafe", "AVALIACAO"),
    ("mic", "MIC"), ("iber", "MIC"), ("copa", "MIC"),
    ("marcet", "INTERCAMBIO"), ("intercambio", "INTERCAMBIO"),
    ("passaporte", "INTERCAMBIO"), ("champions", "INTERCAMBIO"),
    ("jogo", "JOGO"), ("juvenil", "JOGO"), ("guineueta", "JOGO"), ("goleiro", "JOGO"),
    ("classificados", "JOGO"), ("fcf", "JOGO"), ("bravos", "JOGO"), ("barca", "JOGO"),
    ("promocao", "DIVULGACAO"), ("sorteio", "DIVULGACAO"), ("parceiro", "DIVULGACAO"),
    ("convite", "DIVULGACAO"), ("nike", "DIVULGACAO"),
    ("atleta", "ATLETA"),
)

# âncoras que tornam o post reaproveitável independente da data
EVERGREEN = ["oportunidade", "intercâmbio", "intercambio", "sonho", "espanha",
             "barcelona", "atleta", "vaga", "bolsa", "futebol de base",
             "futebolbase", "venha jogar", "garanta", "inscri"]


# chaves curtas precisam de fronteira de palavra: "mic" casaria dentro de
# "acadêmica"/"academico" e jogaria metade do acervo no pilar errado.
_RE_CHAVE: dict[str, re.Pattern] = {}


def _casar(texto: str, chave: str) -> bool:
    """Casa a chave como palavra/frase inteira. Sem isso, "direct" casaria em
    "eliminación directa", "marque" em "marcaram" e "mic" em "acadêmica"."""
    pad = _RE_CHAVE.get(chave)
    if pad is None:
        alvo = chave.lstrip("#")
        pad = re.compile(r"(?<!\w)" + re.escape(alvo) + r"(?!\w)")
        _RE_CHAVE[chave] = pad
    return bool(pad.search(texto))


def _zonas(legenda: str, transcricao: str = "") -> tuple[str, str, str, str]:
    """Separa gancho (1ª linha), corpo e hashtags. O gancho entra duas vezes
    no cálculo porque repete a intenção do post, não o rodapé do perfil."""
    linhas = [l.strip() for l in (legenda or "").splitlines() if l.strip()]
    gancho = linhas[0].lower() if linhas else ""
    corpo = " ".join(linhas[1:]).lower()
    tags = " ".join(re.findall(r"#\w+", (legenda or "").lower()))
    corpo = re.sub(r"#\w+", " ", corpo)
    return gancho, corpo, tags, (transcricao or "").lower()


def _rotular_base(legenda: str, local: str = "", transcricao: str = "") -> dict:
    """Rótulo principal + evidências. Retorna dict com pilar, score, confianca,
    secundarios e os termos que sustentaram a decisão."""
    gancho, corpo, tags, fala = _zonas(legenda, transcricao)
    escores: dict[str, float] = {}
    provas: dict[str, list[str]] = {}
    for pilar, termos in TERMOS.items():
        achados: list[tuple[float, str]] = []
        for termo, peso in termos.items():
            contrib = 0.0
            if _casar(gancho, termo):
                contrib += peso * 2.0
                achados.append((contrib, f"{termo}*2"))
            if termo in corpo and _casar(corpo, termo):
                contrib += peso
                achados.append((contrib, termo))
            if not termo.startswith("#") and termo in tags and _casar(tags, termo):
                contrib += peso * 1.2
                achados.append((contrib, f"#{termo}"))
            if fala and termo in fala and _casar(fala, termo):
                contrib += peso * PESO_FALA
                achados.append((contrib, f"fala:{termo}"))
        if not achados:
            continue
        # retorno decrescente: um termo forte vale mais que cinco fracos somados.
        # Sem isso, "treino" perdia para a soma de "obrigado"+"gratidão"+"experiência".
        achados.sort(key=lambda a: a[0], reverse=True)
        total = sum(c * (0.6 ** i) for i, (c, _) in enumerate(achados))
        escores[pilar] = round(total, 2)
        provas[pilar] = [nome for _, nome in achados[:5]]

    if not escores:
        l = (local or "").lower()
        vazio = not (legenda or "").strip()
        pilar = next((pl for ch, pl in LOCAL_PILAR.items() if ch in l),
                     SEM_LEGENDA if vazio else PILAR_FALLBACK)
        return {"pilar": pilar, "score": 0.0, "confianca": 0.0,
                "secundarios": "",
                "evidencias": "local" if pilar not in (PILAR_FALLBACK, SEM_LEGENDA) else ""}

    ranking = sorted(escores.items(), key=lambda kv: kv[1], reverse=True)
    pilar, score = ranking[0]
    if score < EVIDENCIA_MINIMA:      # legenda fraca ("SUB14 BCN X VIC")
        l = (local or "").lower()
        por_local = next((pl for ch, pl in LOCAL_PILAR.items() if ch in l), None)
        if por_local:
            return {"pilar": por_local, "score": score, "confianca": 0.0,
                    "secundarios": pilar, "evidencias": "local"}
        return {"pilar": PILAR_FALLBACK, "score": score, "confianca": 0.0,
                "secundarios": pilar, "evidencias": ",".join(provas[pilar])}
    segundo = ranking[1][1] if len(ranking) > 1 else 0.0
    confianca = round(score / (score + segundo), 2) if score else 0.0
    secundarios = " ".join(p for p, s in ranking[1:] if s >= 0.4 * score)
    return {"pilar": pilar, "score": score, "confianca": confianca,
            "secundarios": secundarios, "evidencias": ",".join(provas[pilar])}


FALA_MINIMA = 4.0    # fala sozinha precisa de evidência clara: letra de música
                     # transcrita pelo Whisper casava termos por acidente


def _pontuar_fala(transcricao: str) -> tuple[str, float, str]:
    """Pilar sugerido só pela fala transcrita. Retorna (pilar, score, evidências)."""
    fala = (transcricao or "").lower()
    if not fala:
        return "", 0.0, ""
    escores, provas = {}, {}
    for pilar, termos in TERMOS.items():
        achados = [(peso * PESO_FALA, f"fala:{termo}")
                   for termo, peso in termos.items()
                   if termo in fala and _casar(fala, termo)]
        if not achados:
            continue
        achados.sort(key=lambda a: a[0], reverse=True)
        escores[pilar] = round(sum(c * (0.6 ** i) for i, (c, _) in enumerate(achados)), 2)
        provas[pilar] = [n for _, n in achados[:4]]
    if not escores:
        return "", 0.0, ""
    pilar = max(escores, key=escores.get)
    return pilar, escores[pilar], ",".join(provas[pilar])


def rotular(legenda: str, local: str = "", pasta: str = "", transcricao: str = "") -> dict:
    """Rótulo pela legenda; depois pela fala transcrita; pasta só como último recurso."""
    r = _rotular_base(legenda, local)
    if r["pilar"] in (PILAR_FALLBACK, SEM_LEGENDA):
        pilar_fala, score_fala, ev_fala = _pontuar_fala(transcricao)
        if pilar_fala and score_fala >= FALA_MINIMA:
            return {"pilar": pilar_fala, "score": score_fala,
                    "confianca": round(min(0.9, score_fala / (FALA_MINIMA * 2)), 2),
                    "secundarios": "", "evidencias": ev_fala,
                    "resgatado_por": "fala"}
        pista = pista_da_pasta(pasta)
        if pista:
            r = {**r, "pilar": pista, "confianca": 0.35,
                 "evidencias": f"pasta:{pasta}", "resgatado_por": "pasta"}
        return r
    # fala que confirma o rótulo da legenda vale confiança extra e fica na trilha
    pilar_fala, score_fala, ev_fala = _pontuar_fala(transcricao)
    if pilar_fala and score_fala >= FALA_MINIMA:
        if pilar_fala == r["pilar"]:
            r = {**r, "confianca": min(0.95, round(r["confianca"] + 0.15, 2)),
                 "evidencias": ", ".join(x for x in (r["evidencias"], ev_fala) if x),
                 "resgatado_por": "fala+legenda"}
        elif r["confianca"] < 0.45:
            # legenda ambígua + fala clara: quem manda é o que a pessoa diz
            r = {**r, "pilar": pilar_fala, "confianca": round(min(0.8, score_fala / 8), 2),
                 "evidencias": ev_fala, "resgatado_por": "fala (legenda ambigua)",
                 "secundarios": (r["pilar"] + " " + r["secundarios"]).strip()}
        elif r["confianca"] < 0.6:
            r = {**r, "secundarios": (r["secundarios"] + " " + pilar_fala).strip()}
    return r


def classificar(texto: str, local: str = "", pasta: str = "") -> str:
    return rotular(texto, local, pasta)["pilar"]


def classificar_prioridade(texto: str, local: str = "") -> str:
    """Método antigo (primeiro pilar da lista que casar). Mantido só para
    comparar quanto o rótulo por legenda mudou o resultado."""
    t = (texto or "").lower()
    for pilar, termos in TERMOS.items():
        if any(_casar(t, k) for k in termos):
            return pilar
    l = (local or "").lower()
    for chave, pilar in LOCAL_PILAR.items():
        if chave in l:
            return pilar
    return PILAR_FALLBACK


def formato(w, h) -> str:
    try:
        w, h = int(w), int(h)
    except (TypeError, ValueError):
        return "?"
    if not w or not h:
        return "?"
    r = w / h
    if abs(r - 1) < 0.03:
        return "1:1"
    if abs(r - 0.8) < 0.03:
        return "4:5"
    if abs(r - 9 / 16) < 0.04:
        return "9:16"
    if abs(r - 16 / 9) < 0.04:
        return "16:9"
    return f"{w}x{h}"


def hashtags(texto: str) -> str:
    return " ".join("#" + h.lower() for h in sorted({h.lower() for h in re.findall(r"#(\w+)", texto or "")}))


def primeiro_gancho(texto: str, limite: int = 110) -> str:
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if len(linha) > 3:
            return linha[:limite]
    return ""


def ler_json(caminho: str) -> dict | None:
    try:
        with open(caminho, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


_TRANS_CACHE: dict[str, str] | None = None


def carregar_transcricoes(base: str = BASE) -> dict[str, str]:
    """Mapa caminho_relativo_do_video -> transcrição.

    A pasta `transcricoes/` espelha a estrutura do acervo com .txt e .srt
    (`transcricoes/_posts/<ano>/<post>/videos/01.txt`).
    """
    global _TRANS_CACHE
    if _TRANS_CACHE is not None:
        return _TRANS_CACHE
    _TRANS_CACHE = {}
    raiz = os.path.join(base, "transcricoes")
    if not os.path.isdir(raiz):
        return _TRANS_CACHE
    for dir_atual, _dirs, arquivos in os.walk(raiz):
        for nome in arquivos:
            if not nome.endswith(".txt"):
                continue
            cam = os.path.join(dir_atual, nome)
            rel = os.path.relpath(cam, raiz)
            video = os.path.splitext(rel)[0] + ".mp4"
            try:
                with open(cam, encoding="utf-8") as fh:
                    texto = " ".join(fh.read().split())
            except Exception:
                continue
            if len(texto) >= 20:
                _TRANS_CACHE[video] = texto
    return _TRANS_CACHE


def _resumo_fala(texto: str, limite: int = 400) -> str:
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    return corte[:corte.rfind(" ")] + " [...]"


_HIST_CACHE: dict[str, str] | None = None


def _historico_pastas() -> dict[str, str]:
    """destino -> pasta de origem, lido de movimentos.csv (log das organizações)."""
    global _HIST_CACHE
    if _HIST_CACHE is not None:
        return _HIST_CACHE
    _HIST_CACHE = {}
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "movimentos.csv")
    if not os.path.exists(caminho):
        return _HIST_CACHE
    try:
        with open(caminho, encoding="utf-8") as fh:
            for linha in csv.DictReader(fh):
                origem, destino = linha.get("origem", ""), linha.get("destino", "")
                pasta = os.path.dirname(origem)
                if pasta and destino:
                    _HIST_CACHE[destino] = pasta
    except Exception:
        pass
    return _HIST_CACHE


def _entrada(d: dict, arquivo_rel: str, pasta_rel: str, num: int, total: int,
             organizado: bool, caminho: str) -> dict:
    """Monta o registro de uma mídia a partir do json do scraper."""
    try:
        tamanho = os.path.getsize(caminho)
    except OSError:
        tamanho = 0
    return {
        "arquivo": arquivo_rel,
        "pasta": pasta_rel,
        "organizado": organizado,
        "ext": (d.get("extension") or os.path.splitext(arquivo_rel)[1].lstrip(".")).lower(),
        "bytes": tamanho,
        "post_id": str(d.get("post_id") or ""),
        "post_shortcode": d.get("post_shortcode") or "",
        "media_shortcode": d.get("shortcode") or "",
        "url": d.get("post_url") or "",
        "tipo": d.get("type") or "",
        "num": num,
        "total_midias": total,
        "data": (d.get("post_date") or d.get("date") or "")[:19],
        "curtidas": int(d.get("likes") or 0),
        "local": d.get("location_name") or "",
        "local_slug": d.get("location_slug") or "",
        "dono": d.get("username") or "",
        "audio": d.get("audio_title") or "",
        "w": d.get("width") or 0,
        "h": d.get("height") or 0,
        "legenda": d.get("description") or "",
        "tags": " ".join(t.get("username", "") for t in (d.get("tagged_users") or [])
                         if isinstance(t, dict)),
        "coautores": " ".join(c.get("username", "") for c in (d.get("coauthors") or [])
                              if isinstance(c, dict)),
        "fixado": bool(d.get("pinned")),
    }


def coletar(base: str = BASE, ignorar: tuple[str, ...] = ("_reciclagem", "transcricoes")):
    """Varre a árvore e devolve (midias, orfaos, quebrados).

    Entende as duas estruturas:
      * organizada — pasta de post com `post.json` + `imagens/` e `videos/`
        (um json serve todas as mídias do carrossel);
      * crua — `<midia>.<ext>.json` ao lado da mídia, na raiz ou em subpasta.
    """
    midias, quebrados, vistos = [], [], set()
    for raiz, dirs, arquivos in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ignorar]
        if "post.json" in arquivos and os.path.basename(raiz) != "_reciclagem":
            d = ler_json(os.path.join(raiz, "post.json"))
            if d is None:
                quebrados.append({"json": os.path.relpath(raiz, base), "motivo": "post.json ilegivel"})
            else:
                lista = []
                for sub in ("imagens", "videos"):
                    dir_sub = os.path.join(raiz, sub)
                    if not os.path.isdir(dir_sub):
                        continue
                    lista += [(os.path.join(sub, n), n)
                              for n in sorted(os.listdir(dir_sub))
                              if os.path.splitext(n)[1].lower() in EXTS_MIDIA]
                for i, (rel, _nome) in enumerate(lista, 1):
                    caminho = os.path.join(raiz, rel)
                    vistos.add(os.path.abspath(caminho))
                    midias.append(_entrada(d, os.path.relpath(caminho, base), "", i,
                                           len(lista), True, caminho))
            dirs[:] = []          # pasta de post já resolvida: não descer de novo
            continue
        for nome in arquivos:
            if not nome.endswith(".json"):
                continue
            cam_json = os.path.join(raiz, nome)
            cam_midia = cam_json[:-5]
            d = ler_json(cam_json)
            if d is None:
                quebrados.append({"json": os.path.relpath(cam_json, base), "motivo": "json ilegivel"})
                continue
            if not os.path.exists(cam_midia):
                quebrados.append({"json": os.path.relpath(cam_json, base), "motivo": "midia ausente"})
                continue
            vistos.add(os.path.abspath(cam_midia))
            pasta_rel = os.path.relpath(raiz, base) if raiz != base else ""
            midias.append(_entrada(d, os.path.relpath(cam_midia, base), pasta_rel,
                                   int(d.get("num") or 1), int(d.get("count") or 1),
                                   False, cam_midia))

    orfaos = []
    for raiz, dirs, arquivos in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ignorar]
        for nome in arquivos:
            if os.path.splitext(nome)[1].lower() not in EXTS_MIDIA:
                continue
            cam = os.path.join(raiz, nome)
            if os.path.abspath(cam) not in vistos:
                orfaos.append(os.path.relpath(cam, base))

    historico = _historico_pastas()
    falas = carregar_transcricoes(base)
    for m in midias:
        # pasta que a mídia tinha antes da fusão: curadoria humana que não se
        # perde, mesmo com a pasta já desmontada
        anterior = historico.get(m["arquivo"], "")
        m["transcricao"] = falas.get(os.path.splitext(m["arquivo"])[0] + ".mp4", "")
        m["fala"] = _resumo_fala(m["transcricao"])
        r = rotular(m["legenda"], m["local"], m["pasta"] or anterior, m["transcricao"])
        m["pilar"] = r["pilar"]
        m["confianca"] = r["confianca"]
        m["pilar_secundario"] = r["secundarios"]
        m["evidencias"] = r["evidencias"]
        m["resgatado_por"] = r.get("resgatado_por", "")
        m["formato"] = formato(m["w"], m["h"])
        m["ano"] = m["data"][:4]
        m["hashtags"] = hashtags(m["legenda"])
        m["gancho"] = primeiro_gancho(m["legenda"])
    return midias, orfaos, quebrados


ESTADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estados.json")


def carregar_estados() -> dict[str, dict]:
    """{"<pasta do post>": {"nao_interessante": bool, "repostado": bool, "quando": iso}}"""
    if not os.path.exists(ESTADOS):
        return {}
    try:
        with open(ESTADOS, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def salvar_estados(dados: dict[str, dict]) -> None:
    tmp = ESTADOS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, ESTADOS)


CORTES = os.path.join(BASE, "_Cortes")

# tema da pasta -> pilar (o corte não tem legenda de post; o tema é o rótulo)
TEMA_PILAR = {
    "depoimento": "DEPOIMENTO", "entrevista": "DEPOIMENTO",
    "futebol": "JOGO", "jogo": "JOGO", "gol": "JOGO", "treino": "BASTIDOR",
    "hotel": "BASTIDOR", "passeio": "BASTIDOR", "costa rica": "BASTIDOR",
}


def _duracao_srt(caminho: str) -> float:
    """Último fim de cue do .srt — aproxima a duração do corte sem decodificar."""
    try:
        with open(caminho, encoding="utf-8", errors="replace") as fh:
            marcas = re.findall(r"-->\s*(\d\d):(\d\d):(\d\d)[,.](\d{3})", fh.read())
    except OSError:
        return 0.0
    if not marcas:
        return 0.0
    h, m, s, ms = marcas[-1]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def coletar_cortes(base: str = BASE) -> list[dict]:
    """Cortes: `_Cortes/<tema>/[subpasta/]<corte>.mp4` com `.srt` e `.txt` ao lado."""
    raiz = os.path.join(base, "_Cortes")
    cortes = []
    if not os.path.isdir(raiz):
        return cortes
    for dir_atual, _dirs, arquivos in os.walk(raiz):
        for nome in sorted(arquivos):
            if not nome.lower().endswith(".mp4"):
                continue
            cam = os.path.join(dir_atual, nome)
            base_cam = os.path.splitext(cam)[0]
            tema_rel = os.path.relpath(dir_atual, raiz)
            tema = tema_rel.split(os.sep)[0]
            txt = base_cam + ".txt"
            fala = ""
            if os.path.exists(txt):
                try:
                    fala = " ".join(open(txt, encoding="utf-8", errors="replace").read().split())
                except OSError:
                    fala = ""
            pilar = next((p for chave, p in TEMA_PILAR.items() if chave in tema.lower()), "")
            if not pilar:
                # corte de entrevista: tema é o nome da pessoa, o rótulo vem da fala
                pilar = rotular(fala)["pilar"]
                if pilar in (PILAR_FALLBACK, SEM_LEGENDA):
                    pilar = "DEPOIMENTO"
            partes = tema_rel.split(os.sep)
            cortes.append({
                "arquivo": os.path.relpath(cam, base).replace(os.sep, "/"),
                "tema": tema + (f" {'/'.join(partes[1:])}" if len(partes) > 1 else ""),
                "pilar": pilar,
                "segundos": round(_duracao_srt(base_cam + ".srt"), 1),
                "fala": fala,
                "gancho": primeiro_gancho(fala, 110),
                "bytes": os.path.getsize(cam),
                "tem_srt": os.path.exists(base_cam + ".srt"),
            })
    cortes.sort(key=lambda c: (c["tema"], c["arquivo"]))
    return cortes


def _pasta_de(m: dict) -> str:
    """Pasta do post: a manual, ou a pasta que contém imagens/ e videos/."""
    if m["pasta"]:
        return m["pasta"]
    partes = m["arquivo"].split(os.sep)
    if "imagens" in partes or "videos" in partes:
        return os.sep.join(partes[:-2])
    return ""


def agrupar_posts(midias: list[dict]) -> list[dict]:
    """Agrupa mídias de carrossel/foto múltipla em um registro por post."""
    grupos: dict[str, list[dict]] = {}
    for m in midias:
        grupos.setdefault(m["post_id"] or m["arquivo"], []).append(m)
    posts = []
    for pid, itens in grupos.items():
        itens.sort(key=lambda m: m["num"])
        p = dict(itens[0])
        p["n_midias"] = len(itens)
        p["midias"] = [m["arquivo"] for m in itens]
        p["formatos"] = " ".join(sorted({m["formato"] for m in itens}))
        p["exts"] = " ".join(sorted({m["ext"] for m in itens}))
        p["bytes"] = sum(m["bytes"] for m in itens)
        p["pilares"] = " ".join(sorted({m["pilar"] for m in itens}))
        p["pastas"] = " | ".join(sorted({_pasta_de(m) for m in itens} - {""}))
        # pilar do post: se a mídia de capa não decidiu, aproveita a que decidiu
        if p["pilar"] in (PILAR_FALLBACK, SEM_LEGENDA):
            candidatos = [m for m in itens if m["pilar"] not in (PILAR_FALLBACK, SEM_LEGENDA)]
            if candidatos:
                melhor = max(candidatos, key=lambda m: m["confianca"])
                p["pilar"] = melhor["pilar"]
                p["confianca"] = melhor["confianca"]
                p["evidencias"] = melhor["evidencias"]
        p["falas"] = [m["fala"] for m in itens if m.get("fala")]
        p["fala"] = max(p["falas"], key=len) if p["falas"] else ""
        p["tem_fala"] = bool(p["falas"])
        p["tem_video"] = any(m["ext"] == "mp4" for m in itens)
        p["tem_imagem"] = any(m["ext"] in ("jpg", "jpeg", "webp", "png") for m in itens)
        posts.append(p)
    posts.sort(key=lambda p: p["data"])
    return posts


# pesos do score de reciclagem (usados por plano.py e pelo painel)
PESOS = {"alcance": 35, "evergreen": 20, "material": 20, "maturidade": 25,
         "penal_recente": -25, "penal_repetido": -20}
FAIXAS_MATURIDADE = ((1095, 25), (730, 20), (365, 14), (180, 7), (0, 0))


def pontuar(posts: list[dict], hoje=None) -> list[dict]:
    """Score de reciclagem 0-100 + os componentes que o explicam."""
    import datetime as _dt
    hoje = hoje or _dt.date.today()
    if not posts:
        return []
    ordenado = sorted(p["curtidas"] for p in posts)
    total, mediana = len(ordenado), max(statistics.median(ordenado), 1)
    for p in posts:
        pct = (ordenado.index(p["curtidas"]) + 0.5) / total
        idade = (hoje - _dt.date.fromisoformat(p["data"][:10])).days if p["data"] else 999
        alcance = PESOS["alcance"] * pct
        ever = PESOS["evergreen"] * min(1.0, sum((p["legenda"] or "").lower().count(k)
                                                 for k in EVERGREEN) / 3)
        material = min(PESOS["material"], 4 * p["n_midias"] + (8 if p["tem_video"] else 0))
        maturidade = next(v for limite, v in FAIXAS_MATURIDADE if idade >= limite)
        penal = PESOS["penal_recente"] if idade < 150 else 0
        if p.get("repetido", 1) > 1 and not p.get("melhor_do_grupo", True):
            penal += PESOS["penal_repetido"]
        p["score"] = round(alcance + ever + material + maturidade + penal, 1)
        p["idade_dias"] = idade
        p["percentil"] = round(pct * 100)
        p["vs_mediana"] = round(p["curtidas"] / mediana, 2)
        p["score_partes"] = {"alcance": round(alcance, 1), "evergreen": round(ever, 1),
                             "material": material, "maturidade": maturidade,
                             "penal": penal}
    return sorted(posts, key=lambda p: p["score"], reverse=True)


def marcar_repetidos(posts: list[dict]) -> list[dict]:
    """Marca posts que repetem a legenda de outro post. O perfil já reciclou esse
    material internamente — reaproveitar de novo é republicar pela terceira vez.
    Guarda também qual do grupo teve melhor desempenho, que é o que vale usar."""
    grupos: dict[str, list[dict]] = {}
    for p in posts:
        chave = re.sub(r"\s+", " ", (p["legenda"] or "").strip().lower())
        p["repetido"] = 1
        p["melhor_do_grupo"] = True
        if chave:
            grupos.setdefault(chave, []).append(p)
    for itens in grupos.values():
        if len(itens) < 2:
            continue
        melhor = max(itens, key=lambda p: p["curtidas"])
        for p in itens:
            p["repetido"] = len(itens)
            p["melhor_do_grupo"] = p is melhor
    return posts


def resumo(midias, orfaos, quebrados) -> str:
    posts = agrupar_posts(midias)
    c = Counter(m["pilar"] for m in midias)
    anos = Counter(m["ano"] for m in midias)
    gb = sum(m["bytes"] for m in midias) / 1e9
    linhas = [
        f"midias indexadas : {len(midias)}",
        f"posts unicos     : {len(posts)}",
        f"orfaos (sem json): {len(orfaos)}",
        f"quebrados        : {len(quebrados)}",
        f"tamanho total    : {gb:.1f} GB",
        f"periodo          : {min(anos)} .. {max(anos)}",
        "",
        "por pilar:",
    ]
    linhas += [f"  {k:<12} {v:>5}" for k, v in c.most_common()]
    linhas += ["", "por ano:"] + [f"  {k} {v:>5}" for k, v in sorted(anos.items())]
    return "\n".join(linhas)


if __name__ == "__main__":
    print(resumo(*coletar()))
