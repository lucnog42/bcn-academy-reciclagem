"""Ponte do app: `python3 -m unittest discover -s testes`."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "src"))  # src/

import json
import os
import sys
import tempfile
import unittest
from painel import api  # noqa: E402
from acervo import colecao  # noqa: E402
from nucleo import config  # noqa: E402


class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.estados_orig = colecao.ESTADOS
        colecao.ESTADOS = os.path.join(self.tmp, "estados.json")

    def tearDown(self):
        colecao.ESTADOS = self.estados_orig

    def chamar(self, metodo, dados=None):
        return api.atender({"id": 1, "metodo": metodo, "dados": dados or {}})

    def test_ping(self):
        r = self.chamar("ping")
        self.assertTrue(r["ok"])
        self.assertEqual(r["resultado"]["base"], colecao.BASE)

    def test_metodo_desconhecido(self):
        self.assertFalse(self.chamar("apagar_tudo")["ok"])

    def test_marcar_e_desmarcar(self):
        r = self.chamar("marcar", {"post": "p1", "repostado": True})
        self.assertTrue(r["resultado"]["p1"]["repostado"])
        r = self.chamar("marcar", {"post": "p1", "repostado": False})
        self.assertNotIn("p1", r["resultado"])
        with open(colecao.ESTADOS, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {})

    def test_processo_fora_da_lista(self):
        r = self.chamar("processo", {"cmd": ["rm", "-rf", "/tmp/x"]})
        self.assertFalse(r["ok"])

    def test_python_so_scripts_do_projeto(self):
        r = self.chamar("processo", {"cmd": ["python3", "/etc/passwd"]})
        self.assertFalse(r["ok"])

    def test_caminho_fora_do_acervo(self):
        r = self.chamar("info", {"arquivo": "../../etc/passwd"})
        self.assertFalse(r["ok"])

    def test_config_sem_segredos(self):
        cfg = self.chamar("config")["resultado"]
        self.assertNotIn("segredos", cfg)
        self.assertTrue(os.path.isabs(cfg["montagem"]["endings"]))


if __name__ == "__main__":
    unittest.main()
