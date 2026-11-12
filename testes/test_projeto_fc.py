"""Edição no lugar de um .fcproj (ganho e legenda), com cópia de segurança."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "src"))  # src/

import json
import os
import sys
import tempfile
import unittest
from projetos import modelo as MF  # noqa: E402
from projetos import fcproj  # noqa: E402


def projeto_minimo(video: str) -> dict:
    return {"project": {"name": "t", "items": {
        "8": {"name": "v", "kind": {"Media": {"media": {"File": {"path": video}}}}},
        "9": {"name": "outro", "kind": {"Media": {"media": {"File": {"path": "/x/musica.mp3"}}}}},
        "50": {"name": "seq", "kind": {"Sequence": {
            "settings": {"width": 1080, "height": 1920},
            "video_tracks": [{"id": 1, "items": [{"id": 1, "item": 8, "start": 0, "duration": MF.ticks(10)}]}],
            "audio_tracks": [{"id": 4, "items": [{"id": 2, "item": 8, "start": 0, "duration": MF.ticks(10), "gain_db": 0.0}]},
                             {"id": 7, "items": [{"id": 3, "item": 9, "start": 0, "duration": MF.ticks(10), "gain_db": -18.0}]}],
            "caption_tracks": [{"id": 44, "captions": [{"id": 100, "start": 0, "duration": MF.ticks(1), "text": "velha"}]}],
        }}},
    }}}


class ProjetoFC(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.video = os.path.join(self.tmp, "v.mp4")
        open(self.video, "w").close()
        self.proj = os.path.join(self.tmp, "p.fcproj")
        with open(self.proj, "w") as fh:
            json.dump(projeto_minimo(self.video), fh)
        self.antigos = fcproj.ANTIGOS
        fcproj.ANTIGOS = os.path.join(self.tmp, "antigos")
        self.cli = fcproj.FILMCRAFT
        fcproj.FILMCRAFT = "nao-existe-filmcraft-cli"

    def tearDown(self):
        fcproj.ANTIGOS = self.antigos
        fcproj.FILMCRAFT = self.cli

    def test_ganho_so_no_audio_do_video(self):
        self.assertEqual(fcproj.ganho(self.proj, self.video, -6.25), 1)
        p = fcproj.carregar(self.proj)
        k = fcproj.sequencia(p)
        self.assertEqual(k["audio_tracks"][0]["items"][0]["gain_db"], -6.25)
        self.assertEqual(k["audio_tracks"][1]["items"][0]["gain_db"], -18.0, "a música não muda")

    def test_copia_de_seguranca(self):
        fcproj.ganho(self.proj, self.video, -3)
        copias = [f for _, _, fs in os.walk(fcproj.ANTIGOS) for f in fs]
        self.assertEqual(len(copias), 1)

    def test_legenda_trocada_e_resto_igual(self):
        n = fcproj.legendas_do_projeto(self.proj, [(1.0, 1.3, "olá"), (1.35, 1.8, "pessoal")])
        self.assertEqual(n, 1)
        k = fcproj.sequencia(fcproj.carregar(self.proj))
        self.assertEqual(k["caption_tracks"][0]["captions"][0]["text"], "olá pessoal")
        self.assertEqual(k["caption_tracks"][0]["captions"][0]["start"], MF.ticks(1.0))
        self.assertEqual(len(k["video_tracks"][0]["items"]), 1)

    def test_legenda_respeita_trechos_do_corte(self):
        with open(os.path.splitext(self.proj)[0] + ".trechos.json", "w") as fh:
            json.dump([[0.5, 1.0], [3.0, 4.0]], fh)
        fcproj.legendas_do_projeto(self.proj, [(3.2, 3.6, "depois")])
        k = fcproj.sequencia(fcproj.carregar(self.proj))
        self.assertAlmostEqual(MF.seg(k["caption_tracks"][0]["captions"][0]["start"]), 0.7, places=3)


if __name__ == "__main__":
    unittest.main()
