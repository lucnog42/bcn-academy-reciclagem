#!/usr/bin/env python3
"""Configuração: padrões do produto (config/padroes/), a marca ativa (config/marcas/<marca>/)
e config/local.toml desta máquina (fora do git: chaves de API, caminhos locais).

    from nucleo import config
    cfg = config.carregar()
    cfg["montagem"]["endings"]       # caminho absoluto
    config.chave("claude")           # variável de ambiente ou config/local.toml
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # src/

import copy
import os
import re
import tomllib

from nucleo import caminhos

_CACHE: dict | None = None


def _mesclar(base: dict, por_cima: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in por_cima.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _mesclar(out[k], v)
        else:
            out[k] = v
    return out


def _ler(caminho: str) -> dict:
    if not os.path.exists(caminho):
        return {}
    with open(caminho, "rb") as fh:
        return tomllib.load(fh)


def local_toml() -> str:
    return caminhos.raiz("config", "local.toml")


def carregar(recarregar: bool = False) -> dict:
    """Tudo mesclado: padrões do produto < marca ativa < config/local.toml (desta máquina).

    Seções de compatibilidade que o código usa: `acervo` (raiz, posts, cortes, transcricoes,
    projetos, saidas — absolutos), `montagem` (logo, aberturas, endings, ending_padrao, musicas,
    modelo_fcproj, motion — absolutos), `legenda`, `claude`, `app` (cache absoluto), `marca`,
    `pilares`, `termos`, `vocabulario`, `estilo`, `fontes`.
    """
    global _CACHE
    if _CACHE is not None and not recarregar:
        return _CACHE
    m = caminhos.marca()
    cfg: dict = {}
    for nome in sorted(os.listdir(caminhos.raiz("config", "padroes"))):
        if nome.endswith(".toml"):
            d = _ler(caminhos.raiz("config", "padroes", nome))
            cfg = _mesclar(cfg, d if nome == "geral.toml" else {os.path.splitext(nome)[0]: d})
    pasta_marca = caminhos.raiz("config", "marcas", m)
    if not os.path.isdir(pasta_marca):
        raise RuntimeError(f"marca '{m}' não existe em config/marcas/")
    marca = {}
    for nome in sorted(os.listdir(pasta_marca)):
        if nome.endswith(".toml"):
            marca[os.path.splitext(nome)[0]] = _ler(os.path.join(pasta_marca, nome))
    local = _ler(local_toml())
    por_cima = (local.get("marcas") or {}).get(m) or {}
    for k, v in por_cima.items():
        marca[k] = _mesclar(marca.get(k) or {}, v)
    # achata no formato que o código usa
    ac = marca.get("acervo") or {}
    pub = dict(ac.get("publicado") or {})
    # NG3_ACERVO (ou --acervo no app) troca a pasta do acervo sem mexer na config
    raiz_ac = os.path.expanduser(os.environ.get("NG3_ACERVO") or pub.get("raiz") or "")
    pub["raiz"] = raiz_ac
    for k in ("posts", "cortes", "transcricoes"):
        if pub.get(k):
            pub[k] = caminhos.resolver(pub[k], raiz_ac)
    cfg["acervo"] = pub
    cfg["fontes"] = ac.get("fontes") or []
    mont = _mesclar(cfg.get("montagem") or {}, (marca.get("identidade") or {}).get("montagem") or {})
    for k in ("logo", "aberturas", "endings", "ending_padrao", "musicas", "modelo_fcproj"):
        if mont.get(k):
            mont[k] = caminhos.resolver(mont[k], raiz_ac)
    mont["motion"] = caminhos.dados("motion")
    cfg["montagem"] = mont
    cfg["cores"] = (marca.get("identidade") or {}).get("cores") or {}
    cfg["marca"] = (marca.get("marca") or {}).get("marca") or {"slug": m, "nome": m}
    pil = marca.get("pilares") or {}
    cfg["pilares"] = pil.get("pilares") or {}
    for k in ("termos", "local_pilar", "tema_pilar"):
        cfg[k] = pil.get(k) or {}
    cfg["pista_pasta"] = [tuple(x) for x in (pil.get("pasta") or {}).get("pistas") or []]
    cfg["corte_padrao"] = (pil.get("cortes") or {}).get("padrao") or ""
    cfg["vocabulario"] = marca.get("vocabulario") or {}
    cfg["estilo"] = (marca.get("estilo") or {}).get("estilo") or {}
    cfg["regras"] = marca.get("regras") or {}
    for k in ("legenda", "claude", "app"):
        if local.get(k):
            cfg[k] = _mesclar(cfg.get(k) or {}, local[k])
    cfg.setdefault("app", {})["cache"] = caminhos.dados("cache")
    # modelos de prompt: os do produto, e os da marca por cima (mesmo id substitui)
    mods = {x["id"]: x for x in (cfg.pop("modelos-prompt", {}) or {}).get("modelos") or [] if x.get("id")}
    for x in (marca.get("modelos-prompt") or {}).get("modelos") or []:
        if x.get("id"):
            mods[x["id"]] = x
    cfg["modelos_prompt"] = list(mods.values())
    _CACHE = cfg
    return cfg


def descricao_marca() -> str:
    """O parágrafo fixo que a IA recebe sobre a marca (nome, o que faz, público, formato)."""
    m = carregar()["marca"]
    partes = [m.get("descricao") or m.get("nome", "")]
    if m.get("publico"):
        partes.append(f"Público: {m['publico']}.")
    if m.get("formato_padrao"):
        partes.append(f"Formato: {m['formato_padrao']}.")
    return " ".join(p for p in partes if p)


# provedores de IA: o app fala com o Claude (API própria) ou com qualquer API no formato
# da OpenAI (DeepSeek, OpenRouter, Ollama local, ...). A chave de cada um fica separada.
PROVEDORES = {
    "claude": {"nome": "Claude", "tipo": "anthropic", "base_url": "https://api.anthropic.com/v1",
               "modelo": "", "env": "ANTHROPIC_API_KEY", "segredo": "anthropic_api_key", "chave": True},
    "deepseek": {"nome": "DeepSeek", "tipo": "openai", "base_url": "https://api.deepseek.com",
                 "modelo": "deepseek-flash", "env": "DEEPSEEK_API_KEY", "segredo": "deepseek_api_key", "chave": True},
    "openrouter": {"nome": "OpenRouter", "tipo": "openai", "base_url": "https://openrouter.ai/api/v1",
                   "modelo": "", "env": "OPENROUTER_API_KEY", "segredo": "openrouter_api_key", "chave": True},
    "ollama": {"nome": "Ollama (local)", "tipo": "openai", "base_url": "http://localhost:11434/v1",
               "modelo": "", "env": "", "segredo": "", "chave": False},
    "outro": {"nome": "Outra (formato OpenAI)", "tipo": "openai", "base_url": "",
              "modelo": "", "env": "", "segredo": "outro_api_key", "chave": True},
}


# chaves de outras funções, separadas das da IA das sugestões (cada coisa com a sua chave)
CHAVES_EXTRA = {
    "video": {"nome": "Vídeo com IA (OpenRouter)", "env": "NG3_VIDEO_API_KEY",
              "segredo": "video_openrouter_api_key", "chave": True},
}


def _def_chave(pid: str | None) -> dict:
    if pid in CHAVES_EXTRA:
        return CHAVES_EXTRA[pid]
    return PROVEDORES.get(pid or ia()["id"]) or PROVEDORES["claude"]


def _local() -> dict:
    return _ler(local_toml())


def ia() -> dict:
    """O provedor escolhido, já com base_url e modelo resolvidos (sem a chave)."""
    escolha = _local().get("ia") or {}
    pid = escolha.get("provedor") or "claude"
    if pid not in PROVEDORES:
        pid = "claude"
    p = dict(PROVEDORES[pid])
    p["id"] = pid
    if escolha.get("provedor") == pid:
        p["base_url"] = escolha.get("base_url") or p["base_url"]
        p["modelo"] = escolha.get("modelo") or p["modelo"]
    if pid == "claude" and not p["modelo"]:
        p["modelo"] = carregar()["claude"]["modelo"]
    p["base_url"] = p["base_url"].rstrip("/")
    return p


def chave(pid: str | None = None) -> str | None:
    """A chave do provedor: variável de ambiente ou `[segredos]` do config.local.toml.
    Nunca é devolvida pela API do app."""
    p = _def_chave(pid)
    if p["env"] and os.environ.get(p["env"]):
        return os.environ[p["env"]]
    if not p["segredo"]:
        return None
    return (_local().get("segredos") or {}).get(p["segredo"])


def chave_claude() -> str | None:
    return chave("claude")


def origem_chave(pid: str | None = None) -> str:
    """De onde vem a chave: "ambiente", "arquivo" ou "" (nenhuma)."""
    p = _def_chave(pid)
    if p["env"] and os.environ.get(p["env"]):
        return "ambiente"
    return "arquivo" if p["segredo"] and (_local().get("segredos") or {}).get(p["segredo"]) else ""


def _editar_local(secao: str, valores: dict[str, str | None]) -> None:
    """Muda só as linhas `chave = "..."` pedidas dentro de `[secao]` do config.local.toml
    (None tira a linha). O resto do arquivo fica como está; legível só pelo usuário."""
    import re
    caminho = local_toml()
    texto = open(caminho, encoding="utf-8").read() if os.path.exists(caminho) else ""
    linhas = texto.splitlines()
    # limites da seção
    ini = next((k for k, l in enumerate(linhas) if l.strip() == f"[{secao}]"), None)
    if ini is None:
        if linhas and linhas[-1].strip():
            linhas.append("")
        linhas.append(f"[{secao}]")
        ini = len(linhas) - 1
    fim = next((k for k in range(ini + 1, len(linhas)) if linhas[k].strip().startswith("[")), len(linhas))
    for nome, valor in valores.items():
        pad = re.compile(rf"\s*{re.escape(nome)}\s*=")
        corpo = [l for l in linhas[ini + 1:fim] if not pad.match(l)]
        if valor is not None:
            v = str(valor).replace("\\", "\\\\").replace('"', '\\"')
            corpo.insert(0, f'{nome} = "{v}"')
        linhas[ini + 1:fim] = corpo
        fim = ini + 1 + len(corpo)
    tmp = caminho + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas).rstrip() + "\n")
    os.replace(tmp, caminho)
    os.chmod(caminho, 0o600)
    global _CACHE
    _CACHE = None


def salvar_chave(valor: str | None, pid: str | None = None) -> None:
    """Grava (ou tira, com vazio) a chave do provedor em `[segredos]`."""
    import re
    p = _def_chave(pid)
    if not p["segredo"]:
        return
    valor = (valor or "").strip()
    if valor and not re.fullmatch(r"[A-Za-z0-9_\-.:]{16,400}", valor):
        raise ValueError("isso não parece uma chave de API")
    _editar_local("segredos", {p["segredo"]: valor or None})


def salvar_ia(pid: str, modelo: str = "", base_url: str = "") -> dict:
    """Escolhe o provedor (e o modelo / endereço) em `[ia]` do config.local.toml."""
    if pid not in PROVEDORES:
        raise ValueError(f"provedor desconhecido: {pid}")
    if base_url and not re.match(r"^https?://", base_url.strip()):
        raise ValueError("o endereço precisa começar com http:// ou https://")
    _editar_local("ia", {"provedor": pid, "modelo": modelo.strip() or None,
                         "base_url": base_url.strip() or None})
    return ia()


def primeiro_existente(*caminhos: str | None) -> str | None:
    return next((c for c in caminhos if c and os.path.exists(c)), None)
