"""Roteiros a partir do banco de falas (IA simulada) e o primeiro corte ao aprovar. Precisa do
acervo de teste (NG3_ACERVO) e do filmcraft-cli (ou do stub); sem eles, pula."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "src"))

import json
import os
import shutil
import tempfile
import unittest

from nucleo import ia  # noqa: E402
from plano import falas, momentos, roteiros  # noqa: E402

TEM_ACERVO = os.path.isdir(os.path.join(momentos.BASE, "_Cortes")) and shutil.which("filmcraft-cli")


class Frases(unittest.TestCase):
    def test_frases_por_pausa_e_ponto(self):
        ws = [(0.0, 0.3, "Eu"), (0.35, 0.6, "fui"), (0.65, 1.4, "embora."), (1.5, 1.8, "Depois"), (1.85, 2.9, "voltei"),
              (4.0, 4.3, "E"), (4.35, 5.6, "ganhei")]
        fs = falas.frases_de(ws)
        self.assertEqual([f[2] for f in fs], ["Eu fui embora.", "Depois voltei", "E ganhei"])

    def test_frase_curta_cola_na_seguinte(self):
        fs = falas.frases_de([(0.0, 0.4, "Sim."), (0.6, 2.4, "foi incrível")])
        self.assertEqual(len(fs), 1)


@unittest.skipUnless(TEM_ACERVO, "sem acervo de teste ou sem filmcraft-cli")
class Roteiros(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = (roteiros.pasta, momentos.DIR_MOTION, momentos.FILA, ia.conversar)
        roteiros.pasta = lambda: self.tmp
        momentos.DIR_MOTION = os.path.join(self.tmp, "motion")
        momentos.FILA = os.path.join(self.tmp, "motion", "fila.json")
        falas.garantir()
        self.pool = falas.amostra(10, semente=1)
        self.assertGreaterEqual(len(self.pool), 3)
        a, b, c = self.pool[:3]

        def conversar(conteudo, sistema, maximo=1500):
            return json.dumps({"titulo": "Teste de roteiro", "resumo": "r", "partes": [
                {"parte": "gancho", "tipo": "fala", "id": a["id"], "funcao": "so-a-pessoa", "mostrar": ""},
                {"parte": "ponte", "tipo": "nova", "texto": "Foi aí que tudo mudou para ele", "quem": "locução",
                 "funcao": "clima", "mostrar": "treino Marcet"},
                {"parte": "prova", "tipo": "fala", "id": b["id"], "funcao": "provar", "mostrar": "treino Marcet camp"},
                {"parte": "repetida", "tipo": "fala", "id": a["id"], "funcao": "provar", "mostrar": "x"},
                {"parte": "inventada", "tipo": "fala", "id": "naoexiste", "funcao": "provar", "mostrar": "x"},
                {"parte": "convite", "tipo": "fala", "id": c["id"], "funcao": "inventada", "mostrar": "x"}]})
        ia.conversar = conversar

    def tearDown(self):
        roteiros.pasta, momentos.DIR_MOTION, momentos.FILA, ia.conversar = self.orig
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(os.path.join(momentos.BASE, "_Roteiros"), ignore_errors=True)

    def test_escrever_valida_e_acha_cobertura(self):
        r = roteiros.escrever("intercâmbio", "depoimento", 30)
        ps = r["partes"]
        self.assertEqual([p["tipo"] for p in ps], ["fala", "nova", "fala", "fala"])   # repetida e inventada saem
        self.assertEqual(ps[3]["funcao"], "so-a-pessoa")                               # função inválida vira "só a pessoa"
        self.assertEqual(ps[0]["cobertura"], [])
        self.assertTrue(ps[2]["cobertura"] and ps[2]["escolhida"])
        self.assertEqual(ps[0]["texto"], self.pool[0]["texto"])                        # fala gravada não muda
        self.assertEqual(roteiros.listar()[0]["novas"], 1)

    def test_editar_e_excluir(self):
        r = roteiros.escrever("intercâmbio")
        r = roteiros.editar(r["id"], "mover", 0, 1)
        self.assertEqual(r["partes"][0]["tipo"], "nova")
        r = roteiros.editar(r["id"], "texto", 0, "Uma fala nova bem mais longa que a anterior para testar")
        self.assertGreater(r["partes"][0]["dur"], 3)
        with self.assertRaises(ValueError):
            roteiros.editar(r["id"], "texto", 1, "não pode")
        roteiros.excluir(r["id"])
        self.assertEqual(roteiros.listar(), [])

    def test_aprovar_monta_o_primeiro_corte(self):
        r = roteiros.escrever("intercâmbio")
        r = roteiros.aprovar(r["id"])
        self.assertEqual(r["status"], "aprovado")
        proj = momentos._abs(r["projeto"])
        self.assertTrue(os.path.exists(proj))
        with open(os.path.splitext(proj)[0] + ".trechos.json", encoding="utf-8") as fh:
            self.assertEqual(len(json.load(fh)["videos"]), len(r["partes"]))
        ms = momentos.ler_sugestoes(r["pasta"])["itens"]
        self.assertEqual(len(ms), len(r["partes"]))
        aprovados = [m for m in ms if m.get("formato") == "acervo"]
        self.assertTrue(aprovados and all(m["broll"]["sequencia"] for m in aprovados))
        self.assertGreaterEqual(r["broll"], 1)
        self.assertNotIn(r["id"], [p["id"] for p in momentos.ler_fila()])
        self.assertTrue(os.path.exists(roteiros.exportar_md(r["id"])))


if __name__ == "__main__":
    unittest.main()
