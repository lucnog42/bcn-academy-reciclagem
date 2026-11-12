"""B-roll do acervo: índice, candidatos, sequência e montagem. Precisa de um acervo de teste com
posts e cortes (NG3_ACERVO); sem ele, pula. `python3 -m unittest discover -s testes`."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "src"))

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from achar import broll, indice  # noqa: E402
from plano import momentos  # noqa: E402

CORTE = "_Cortes/Fernando"


@unittest.skipUnless(os.path.isdir(os.path.join(momentos.BASE, CORTE)), "sem acervo de teste")
class Broll(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "broll.sqlite")
        cls.n = indice.indexar(db=cls.db)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.orig = (momentos.DIR_MOTION, momentos.FILA)
        momentos.DIR_MOTION = os.path.join(self.tmp, "motion")
        momentos.FILA = os.path.join(self.tmp, "motion", "fila.json")
        self.video = momentos.videos_da_pasta(CORTE)[0]
        self.s = momentos.novo_momento(CORTE, self.video, 3.0, 7.0, tipo="lugar", texto="treino em Marcet camp day")

    def tearDown(self):
        momentos.DIR_MOTION, momentos.FILA = self.orig

    def test_indice_tem_posts_e_cortes(self):
        self.assertGreater(self.n.get("posts", 0), 0)
        self.assertGreater(self.n.get("cortes", 0), 0)
        self.assertEqual(indice.consulta_fts(['a"b', "OR", "estádio"]), '"a b" OR "estádio"')

    def test_candidatos_variados_e_sem_o_proprio_trecho(self):
        r = broll.candidatos(CORTE, self.s["id"], 5, db=self.db)
        cs = r["candidatos"]
        self.assertTrue(3 <= len(cs) <= 5, cs)
        por_item = {}
        for c in cs:
            por_item[c["item"]] = por_item.get(c["item"], 0) + 1
            self.assertFalse(c["arquivo"] == self.video and c["ini"] < 8 and c["fim"] > 2)
        self.assertLessEqual(max(por_item.values()), 2)
        self.assertTrue(any("marcet" in c["texto"].lower() for c in cs))
        guardado = next(x for x in momentos.ler_sugestoes(CORTE)["itens"] if x["id"] == self.s["id"])
        self.assertEqual(len(guardado["broll"]["candidatos"]), len(cs))

    def test_sequencia_divide_o_tempo_e_monta_o_arquivo(self):
        cs = broll.candidatos(CORTE, self.s["id"], 5, db=self.db)["candidatos"]
        img = next(c for c in cs if c["tipo"] == "imagem")
        outro = momentos.videos_da_pasta(CORTE)[-1]
        s = broll.sequencia(CORTE, self.s["id"], [img, {"arquivo": outro, "tipo": "video", "ini": 1.0, "dur": 1.5}])
        seq = s["broll"]["sequencia"]
        self.assertEqual(s["formato"], "acervo")
        self.assertEqual([p["dur"] for p in seq], [2.5, 1.5])      # 4 s do momento, o resto vai para a foto
        momentos.marcar(CORTE, self.s["id"], {"status": "aprovado"})
        self.assertNotIn(self.s["id"], [p["id"] for p in momentos.ler_fila()])   # não vai para o Claude
        saida = broll.renderizar(self.video, broll.aprovados(CORTE))
        try:
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                        saida], capture_output=True, text=True).stdout)
            self.assertGreater(dur, 5)
        finally:
            os.remove(saida)

    def test_no_maximo_tres_pedacos(self):
        cs = broll.candidatos(CORTE, self.s["id"], 5, db=self.db)["candidatos"]
        s = broll.sequencia(CORTE, self.s["id"], cs)
        self.assertEqual(len(s["broll"]["sequencia"]), 3)
        s = broll.sequencia(CORTE, self.s["id"], [])
        self.assertNotEqual(s["formato"], "acervo")


if __name__ == "__main__":
    unittest.main()
