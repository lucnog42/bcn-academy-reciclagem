"""Modelos de prompt (estilos prontos escolhidos antes de gerar): `python3 -m unittest discover -s testes`."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "src"))

import os
import shutil
import tempfile
import unittest

from plano import momentos, modelos  # noqa: E402


class Modelos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = (momentos.DIR_MOTION, momentos.FILA)
        momentos.DIR_MOTION = os.path.join(self.tmp, "motion")
        momentos.FILA = os.path.join(self.tmp, "motion", "fila.json")
        self.pasta = os.path.relpath(self.tmp, momentos.BASE) if self.tmp.startswith(momentos.BASE) else self.tmp
        self.s = momentos.novo_momento(self.pasta, "v.mp4", 2.0, 5.0, tipo="nome", texto="Ana Souza")

    def tearDown(self):
        momentos.DIR_MOTION, momentos.FILA = self.orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_listar_filtra_por_alvo_e_tipo(self):
        ids = {m["id"] for m in modelos.listar("motion", "nome")}
        self.assertIn("lower-third", ids)
        self.assertNotIn("contador", ids)
        self.assertTrue(all(m["alvo"] == "video" for m in modelos.listar("video")))

    def test_aplicar_preenche_e_guarda_a_escolha(self):
        r = modelos.aplicar(self.pasta, self.s["id"], "lower-third")
        self.assertIn("Ana Souza", r["texto"])
        self.assertNotIn("{", r["texto"])
        s = next(x for x in momentos.ler_sugestoes(self.pasta)["itens"] if x["id"] == self.s["id"])
        self.assertEqual(s["modelo_motion"], "lower-third")
        self.assertEqual(s["briefing"], r["texto"])

    def test_modelo_de_video_vai_para_o_prompt(self):
        r = modelos.aplicar(self.pasta, self.s["id"], "drone")
        s = next(x for x in momentos.ler_sugestoes(self.pasta)["itens"] if x["id"] == self.s["id"])
        self.assertEqual(s["prompt_video"], r["texto"])
        self.assertEqual(s["modelo_video"], "drone")

    def test_modelo_desconhecido(self):
        with self.assertRaises(ValueError):
            modelos.aplicar(self.pasta, self.s["id"], "nao-existe")


if __name__ == "__main__":
    unittest.main()
