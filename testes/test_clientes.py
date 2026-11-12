"""Clientes separados: criar cliente, chaves e IA por cliente (com a geral de reserva) e pastas
importadas sem cópia. Roda numa cópia temporária de config/ (NG3_RAIZ)."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "src"))

import os
import shutil
import tempfile
import unittest

from nucleo import caminhos, config  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Clientes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copytree(os.path.join(RAIZ, "config"), os.path.join(self.tmp, "config"),
                        ignore=shutil.ignore_patterns("local.toml"))
        self.env = {k: os.environ.get(k) for k in ("NG3_RAIZ", "NG3_MARCA", "ANTHROPIC_API_KEY", "NG3_ACERVO")}
        os.environ["NG3_RAIZ"] = self.tmp
        os.environ["NG3_MARCA"] = "exemplo"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.acervo = os.path.join(self.tmp, "acervo")
        os.makedirs(self.acervo)
        os.environ["NG3_ACERVO"] = self.acervo
        config._CACHE = None

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config._CACHE = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chave_do_cliente_e_geral_de_reserva(self):
        geral = "sk-ant-geral-" + "a" * 20
        cliente = "sk-ant-cliente-" + "b" * 20
        config.salvar_chave(geral, "claude", "geral")
        self.assertEqual(config.chave("claude"), geral)
        self.assertEqual(config.origem_chave("claude"), "geral")
        config.salvar_chave(cliente, "claude")                    # padrão: só o cliente ativo
        self.assertEqual(config.chave("claude"), cliente)
        self.assertEqual(config.origem_chave("claude"), "cliente")
        os.environ["NG3_MARCA"] = "bcn"                           # outro cliente não vê a chave
        self.assertEqual(config.chave("claude"), geral)
        os.environ["NG3_MARCA"] = "exemplo"
        config.salvar_chave("", "claude")                         # tirar a do cliente volta à geral
        self.assertEqual(config.chave("claude"), geral)

    def test_ia_por_cliente(self):
        config.salvar_ia("deepseek", "", "", "geral")
        self.assertEqual(config.ia()["id"], "deepseek")
        config.salvar_ia("openrouter", "x/modelo", "")
        self.assertEqual((config.ia()["id"], config.ia()["escopo"]), ("openrouter", "marca"))
        os.environ["NG3_MARCA"] = "bcn"
        self.assertEqual(config.ia()["id"], "deepseek")
        os.environ["NG3_MARCA"] = "exemplo"
        config.usar_ia_geral()
        self.assertEqual((config.ia()["id"], config.ia()["escopo"]), ("deepseek", "geral"))

    def test_criar_cliente(self):
        from nucleo import marcas
        m = marcas.criar("Padaria São João")
        self.assertEqual(m["slug"], "padaria-sao-joao")
        self.assertIn("padaria-sao-joao", caminhos.marcas())
        os.environ["NG3_MARCA"] = "padaria-sao-joao"
        os.environ.pop("NG3_ACERVO")
        config._CACHE = None
        cfg = config.carregar()
        self.assertEqual(cfg["marca"]["nome"], "Padaria São João")
        self.assertTrue(os.path.isdir(cfg["acervo"]["raiz"]))
        with self.assertRaises(ValueError):
            marcas.criar("Padaria São João")

    def test_importar_pasta_sem_copiar(self):
        from acervo import fontes
        origem = os.path.join(self.tmp, "HD", "Depoimentos 2024")
        os.makedirs(os.path.join(origem, "sub"))
        for n in ("a.mp4", "sub/b.MOV", "c.jpg", ".oculto.mp4"):
            open(os.path.join(origem, n), "wb").close()
        f = fontes.adicionar(origem, "falas", "Depoimentos 2024")
        self.assertEqual(f["id"], "depoimentos-2024")
        self.assertEqual([t for _, t in fontes.arquivos(f)], ["video", "video"])        # falas: só vídeos
        self.assertIn("depoimentos-2024", [x["id"] for x in fontes.listar()])
        with self.assertRaises(ValueError):
            fontes.adicionar(os.path.join(origem, "sub"), "broll")                         # já está dentro de outra
        fontes.ativar("depoimentos-2024", False)
        self.assertFalse(next(x for x in fontes.listar() if x["id"] == "depoimentos-2024")["ativo"])
        fontes.remover("depoimentos-2024")
        self.assertTrue(os.path.exists(os.path.join(origem, "a.mp4")))                    # nada apagado na origem
        with self.assertRaises(ValueError):
            fontes.remover("posts")                                                         # as da config não saem

    def test_referencias_ficam_fora_do_material(self):
        from acervo import fontes
        from achar import indice
        ref = os.path.join(self.tmp, "Refs")
        os.makedirs(ref)
        open(os.path.join(ref, "estilo.mp4"), "wb").close()
        fontes.adicionar(ref, "referencias", "Refs")
        self.assertNotIn("refs", [f["id"] for f in indice.fontes()])

    def test_transcricao_de_pasta_importada_vai_para_dados(self):
        from transcricao import legendar
        legendar.BASE = self.acervo
        alvo = legendar.caminho_saida("/mnt/HD/Depoimentos/a.mp4", ".words.json")
        self.assertTrue(alvo.startswith(os.path.join(self.tmp, "dados", "marcas", "exemplo", "transcricoes", "externos")))
        self.assertTrue(alvo.endswith("mnt/HD/Depoimentos/a.words.json"))


if __name__ == "__main__":
    unittest.main()
