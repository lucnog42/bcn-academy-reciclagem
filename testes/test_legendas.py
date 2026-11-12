"""Regras da legenda: `python3 -m unittest discover -s testes`.

Só stdlib — não precisa do .venv-asr."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "src"))  # src/

import os
import sys
import unittest
from transcricao import legendas  # noqa: E402
from projetos import modelo as MF  # noqa: E402


class Cartelas(unittest.TestCase):
    def test_entra_no_comeco_da_fala(self):
        c = legendas.cartelas([(1.00, 1.30, "olá"), (1.32, 1.60, "pessoal")])
        self.assertEqual(c[0][0], 1.00)

    def test_sai_logo_depois_da_fala(self):
        c = legendas.cartelas([(1.0, 1.4, "fim"), (5.0, 5.4, "outra")])
        self.assertAlmostEqual(c[0][1], 1.4 + legendas.SAIDA, places=3)

    def test_quebra_na_pausa(self):
        c = legendas.cartelas([(0, .3, "a"), (.31, .6, "b"), (1.2, 1.5, "c")])
        self.assertEqual([t for _, _, t in c], ["a b", "c"])

    def test_no_maximo_quatro_palavras(self):
        ps = [(i * .3, i * .3 + .28, f"p{i}") for i in range(9)]
        self.assertTrue(all(len(t.split()) <= 4 for _, _, t in legendas.cartelas(ps)))

    def test_minimo_nao_invade_a_proxima(self):
        c = legendas.cartelas([(1.0, 1.1, "é"), (1.3, 1.7, "isso")], pausa=0.1)
        self.assertLessEqual(c[0][1], c[1][0])
        self.assertEqual(c[1][0], 1.3)

    def test_fala_seguida_encosta(self):
        c = legendas.cartelas([(0, .3, "a"), (.31, .6, "b"), (.61, .9, "c"), (.91, 1.2, "d"),
                               (1.25, 1.5, "e")])
        self.assertEqual(c[0][1], c[1][0])

    def test_quadro_inteiro(self):
        for a, b, _ in legendas.cartelas([(1.013, 1.4, "x"), (3.017, 3.5, "y")], fps=30):
            self.assertAlmostEqual(a * 30, round(a * 30), places=2)
            self.assertAlmostEqual(b * 30, round(b * 30), places=2)


class Corte(unittest.TestCase):
    def test_palavra_cortada_sai(self):
        m = legendas.mapear_palavras([(0.5, 0.8, "a"), (1.5, 1.8, "b")], [(0.4, 1.0)])
        self.assertEqual([t for *_, t in m], ["a"])

    def test_tempo_vai_para_a_timeline_cortada(self):
        m = legendas.mapear_palavras([(3.0, 3.4, "c")], [(0.4, 1.2), (2.9, 4.0)])
        self.assertAlmostEqual(m[0][0], 0.8 + 0.1, places=3)


class Gerador(unittest.TestCase):
    def test_ordenar_nao_empurra_em_cascata(self):
        t = MF.ticks
        cues = [(t(1.0 + 0.32 * i), t(0.5), "x") for i in range(6)]
        inicios = [MF.seg(i) for i, _, _ in MF.ordenar_cartelas(cues)]
        self.assertEqual([round(x, 2) for x in inicios], [round(1.0 + 0.32 * i, 2) for i in range(6)])

    def test_ordenar_sem_sobreposicao(self):
        t = MF.ticks
        out = MF.ordenar_cartelas([(t(1), t(1), "a"), (t(1.5), t(1), "b")])
        self.assertLessEqual(out[0][0] + out[0][1], out[1][0])

    def test_srt_novo_passa_direto(self):
        out = MF.cartelas([(1.25, 1.9, "três palavras aqui")])
        self.assertEqual(out[0][0], MF.ticks(1.25))
        self.assertEqual(out[0][1], MF.ticks(0.65))


if __name__ == "__main__":
    unittest.main()
