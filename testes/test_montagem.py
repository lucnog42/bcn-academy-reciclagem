"""Vários vídeos numa timeline, J/L de verdade no projeto e o que não é corte novo."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "src"))  # src/

import os
import sys
import tempfile
import unittest
from acervo import colecao  # noqa: E402
from projetos import modelo as MF  # noqa: E402

T = MF.ticks


def projeto() -> dict:
    return {"project": {"name": "t", "next_id": 50, "root": {"children": []}, "items": {
        "8": {"name": "a.mp4", "kind": {"Media": {}}},
        "9": {"name": "b.mp4", "kind": {"Media": {}}},
        "26": {"name": "ending.mp4", "kind": {"Media": {}}},
        "50": {"name": "seq", "kind": {"Sequence": {
            "settings": {"width": 1080, "height": 1920},
            "video_tracks": [{"id": 1, "items": [
                {"id": 10, "item": 8, "start": 0, "duration": T(20), "source_in": 0, "link": 10},
                {"id": 28, "item": 26, "start": T(20), "duration": T(3), "source_in": 0, "link": 27}],
                "transitions": []}],
            "audio_tracks": [{"id": 4, "items": [
                {"id": 11, "item": 8, "start": 0, "duration": T(20), "source_in": 0, "link": 10},
                {"id": 29, "item": 26, "start": T(20), "duration": T(3), "source_in": 0, "link": 27}]}],
            "caption_tracks": [],
        }}},
    }}}


def sem_sobrepor(clipes):
    fim = 0
    for c in sorted(clipes, key=lambda c: c["start"]):
        assert c["start"] >= fim, c
        fim = c["start"] + c["duration"]


class Montagem(unittest.TestCase):
    def test_j_cut_imagem_passa_do_som(self):
        p = projeto()
        # 1º trecho: imagem vai 0,3 s além do som (J); 2º: imagem entra 0,3 s depois
        pecas = MF.pecas_de(8, [(0, 5, 0, 5.3), (7, 12, 7.3, 12)])
        cum = MF.montar_principal(p, pecas)
        k = MF._seq(p)
        v, a = k["video_tracks"][0]["items"], k["audio_tracks"][0]["items"]
        self.assertEqual(cum, T(10))
        self.assertEqual(v[0]["duration"], T(5.3))
        self.assertEqual(v[1]["start"], T(5.3))          # imagem do 2º entra depois do som dele
        self.assertEqual(a[1]["start"], T(5))
        self.assertEqual(v[1]["source_in"], T(7.3))
        self.assertEqual(v[0]["link"], a[0]["link"])
        sem_sobrepor(v)
        sem_sobrepor(a)
        self.assertEqual(v[-1]["start"], T(10))          # ending anda junto

    def test_dois_videos_em_sequencia(self):
        p = projeto()
        pecas = MF.pecas_de(8, [(0, 4)]) + MF.pecas_de(9, [(1, 3)])
        MF.montar_principal(p, pecas)
        a = MF._seq(p)["audio_tracks"][0]["items"]
        self.assertEqual([c["item"] for c in a], [8, 9, 26])
        self.assertEqual(a[1]["start"], T(4))
        self.assertEqual(a[1]["source_in"], T(1))
        self.assertGreater(p["project"]["next_id"], max(c["id"] for c in a))

    def test_palavras_de_dois_videos(self):
        ws = MF.palavras_na_timeline([
            {"palavras": [(0.5, 1.0, "oi")], "trechos": None, "duracao": 3.0},
            {"palavras": [(2.0, 2.5, "tchau")], "trechos": [(1.5, 3.0)], "duracao": 9.0},
        ])
        self.assertEqual(ws, [(0.5, 1.0, "oi"), (3.5, 4.0, "tchau")])

    def test_derivados_nao_sao_cortes(self):
        d = tempfile.mkdtemp()
        for n in ("x.mp4", "x_norm.mp4", "x_sem_silencio.mp4", "x_sem_silencio_norm.mp4",
                  "Pasta_x.mp4", "Pasta_x.fcproj"):
            open(os.path.join(d, n), "w").close()
        livres = [n for n in sorted(os.listdir(d)) if n.endswith(".mp4")
                  and not colecao.eh_derivado(os.path.join(d, n))]
        self.assertEqual(livres, ["x.mp4"])

    def test_pasta_vira_um_item(self):
        cs = [{"arquivo": f"_Cortes/Pais/{n}.mp4", "tema": "Pais", "pilar": "DEPOIMENTO",
               "segundos": 10.0, "fala": n, "gancho": "", "bytes": 1, "tem_srt": True}
              for n in ("b", "a")] + [
              {"arquivo": "_Cortes/depoimentos hotel/27/c.mp4", "tema": "depoimentos hotel 27",
               "pilar": "DEPOIMENTO", "segundos": 5.0, "fala": "", "gancho": "", "bytes": 1, "tem_srt": False}]
        g = {x["pasta"]: x for x in colecao.agrupar_cortes(cs)}
        self.assertEqual(g["_Cortes/Pais"]["videos"], ["_Cortes/Pais/a.mp4", "_Cortes/Pais/b.mp4"])
        self.assertEqual(g["_Cortes/Pais"]["segundos"], 20.0)
        self.assertEqual(g["_Cortes/depoimentos hotel/27"]["nome"], "depoimentos-hotel_27")

    def test_motion_anda_com_o_corte_de_silencio(self):
        import json
        from plano import momentos
        d = tempfile.mkdtemp()
        proj = os.path.join(d, "p.fcproj")
        a, b = os.path.join(d, "a.mp4"), os.path.join(d, "b.mp4")
        with open(os.path.splitext(proj)[0] + ".trechos.json", "w") as fh:
            json.dump({"videos": [{"video": a, "trechos": [[0, 4], [6, 10]], "duracao": 12},
                                  {"video": b, "trechos": None, "duracao": 5}]}, fh)
        self.assertEqual(momentos.tempo_na_timeline(proj, a, 7.0), 5.0)     # 4 s do 1º trecho + 1 s
        self.assertEqual(momentos.tempo_na_timeline(proj, b, 2.0), 10.0)    # depois dos 8 s do vídeo a
        self.assertIsNone(momentos.tempo_na_timeline(proj, os.path.join(d, "c.mp4"), 1.0))

    def test_linha_do_tempo_do_projeto(self):
        import json
        from projetos import linha_tempo
        d = tempfile.mkdtemp()
        a, b, e = (os.path.join(d, n) for n in ("a.mp4", "b.mp4", "end.mp4"))
        midia = lambda p: {"kind": {"Media": {"media": {"File": {"path": p}}}}}
        T = MF.ticks
        proj = {"project": {"name": "t", "items": {"8": midia(a), "9": midia(b), "26": midia(e), "50": {"kind": {"Sequence": {
            "settings": {}, "video_tracks": [
                {"id": 1, "items": [{"id": 1, "item": 8, "start": 0, "duration": T(4.3), "source_in": 0},
                                    {"id": 2, "item": 9, "start": T(4.3), "duration": T(5.7), "source_in": T(1.3)},
                                    {"id": 3, "item": 26, "start": T(10), "duration": T(3), "source_in": 0}]},
                {"id": 3, "name": "Video 3", "items": [{"id": 4, "item": 8, "start": 0, "duration": T(4), "effects": [
                    {"effect": "graphic_text", "params": {"text": {"value": {"Text": "Fernando"}}}}]}]}],
            "audio_tracks": [{"id": 4, "items": [{"id": 5, "item": 8, "start": 0, "duration": T(4), "source_in": 0},
                                                 {"id": 6, "item": 9, "start": T(4), "duration": T(6), "source_in": T(1)},
                                                 {"id": 7, "item": 26, "start": T(10), "duration": T(3), "source_in": 0}]}],
            "caption_tracks": [{"id": 44, "captions": [{"id": 100, "start": T(5), "duration": T(1), "text": "oi"}]}]}}}}}}
        caminho = os.path.join(d, "p.fcproj")
        with open(caminho, "w") as fh:
            json.dump(proj, fh)
        l = linha_tempo.ler(caminho)
        rel = lambda p: os.path.relpath(os.path.realpath(p), os.path.realpath(linha_tempo.fcproj.BASE))
        self.assertEqual(len(l["pecas"]), 2)                    # o ending não é fala
        self.assertAlmostEqual(l["ending"]["t0"], 10.0)
        self.assertEqual(linha_tempo.para_fonte(l, 6.0), (rel(b), 3.0))   # pela faixa de áudio
        self.assertAlmostEqual(linha_tempo.para_timeline(l, rel(b), 3.0), 6.0)
        n = linha_tempo.na_tela(l, 3.0, 6.0)
        self.assertEqual([c["textos"] for c in n["camadas"]], [["Fernando"]])
        self.assertEqual(n["legendas"], ["oi"])
        self.assertEqual(n["cortes"], [4.0])


if __name__ == "__main__":
    unittest.main()
