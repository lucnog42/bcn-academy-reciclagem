"""O código não sabe qual é a marca: tudo de marca vem de config/marcas/<marca>/.

    python3 -m unittest discover -s testes
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# o que nunca pode aparecer no código genérico (só nos arquivos da própria marca)
PROIBIDO = re.compile(r"bcn|interc[aâ]mbio|doykoy|barcelona|micfootball|\"MIC\"", re.I)
PASTAS = ["src", "plugins", os.path.join("config", "padroes"), os.path.join("app", "src")]
EXTENSOES = (".py", ".rs", ".luau", ".toml")


class Agnosticidade(unittest.TestCase):
    def test_nada_de_marca_no_codigo(self):
        achados = []
        for pasta in PASTAS:
            for raiz, dirs, arqs in os.walk(os.path.join(RAIZ, pasta)):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "target", "presets")]
                for a in arqs:
                    if not a.endswith(EXTENSOES):
                        continue
                    caminho = os.path.join(raiz, a)
                    with open(caminho, encoding="utf-8") as fh:
                        for n, linha in enumerate(fh, 1):
                            if PROIBIDO.search(linha):
                                achados.append(f"{os.path.relpath(caminho, RAIZ)}:{n}: {linha.strip()[:100]}")
        self.assertEqual(achados, [], "marca no código genérico:\n" + "\n".join(achados))

    def test_toda_marca_tem_os_arquivos(self):
        base = os.path.join(RAIZ, "config", "marcas")
        for m in os.listdir(base):
            for f in ("marca.toml", "acervo.toml", "pilares.toml", "vocabulario.toml", "identidade.toml", "estilo.toml"):
                self.assertTrue(os.path.exists(os.path.join(base, m, f)), f"{m}/{f}")

    def test_marca_exemplo_funciona_ponta_a_ponta(self):
        """Um cliente novo (a marca-molde `exemplo`) com um acervo vazio: o motor sobe, o ping diz a
        marca e os pilares dela, e o estado vai para dados/marcas/exemplo/ (nunca para outra marca)."""
        acervo = tempfile.mkdtemp()
        os.makedirs(os.path.join(acervo, "_posts"))
        env = {**os.environ, "NG3_MARCA": "exemplo", "NG3_ACERVO": acervo}
        api = os.path.join(RAIZ, "src", "painel", "api.py")

        def chamar(metodo, dados=None):
            r = subprocess.run([sys.executable, api, "chamar", metodo, json.dumps(dados or {})],
                               env=env, capture_output=True, text=True, cwd=RAIZ, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)

        ping = chamar("ping")["resultado"]
        self.assertEqual(ping["marca"], "exemplo")
        self.assertEqual(ping["nome_marca"], "Marca Exemplo")
        self.assertEqual(ping["pilares"], ["DEPOIMENTO", "PRODUTO", "BASTIDOR"])
        self.assertEqual(os.path.realpath(ping["base"]), os.path.realpath(acervo))
        self.assertIn("bcn", ping["marcas"])
        self.assertEqual(chamar("posts")["resultado"], [])
        cfg = chamar("config")["resultado"]
        self.assertNotIn("segredos", cfg)
        self.assertIn(os.path.join("dados", "marcas", "exemplo"), cfg["montagem"]["motion"])

    def test_sistema_da_ia_usa_a_marca(self):
        env = {**os.environ, "NG3_MARCA": "exemplo"}
        codigo = ("import sys; sys.path.insert(0, 'src');"
                  "from plano import prompts; print(prompts.sistema('video'))")
        r = subprocess.run([sys.executable, "-c", codigo], env=env, capture_output=True, text=True, cwd=RAIZ)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Marca Exemplo", r.stdout)
        self.assertIn("warm documentary look", r.stdout)
        self.assertNotIn("{marca}", r.stdout)


if __name__ == "__main__":
    unittest.main()
