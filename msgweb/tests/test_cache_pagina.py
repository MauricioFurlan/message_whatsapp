"""A página principal não pode ficar no cache do navegador.

Com o servidor desligado, o navegador servia `/` do próprio cache: a tela
abria inteira, todas as chamadas falhavam e o usuário terminava olhando o
formulário de ativação de licença, achando que tinha perdido a licença.

Com `Cache-Control: no-store`, abrir a página sem o programa rodando dá o erro
de conexão do navegador — que é a verdade. O aviso de "programa não está
rodando" (lado do frontend, `tests/test_servidor_offline.js`) cobre o caso em
que o servidor cai ou ainda está subindo com a página já aberta.
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCachePagina(unittest.TestCase):
    def test_index_nao_pode_ser_cacheada(self):
        import app

        resposta = asyncio.run(app.serve_frontend())
        cache = resposta.headers.get("cache-control", "")
        self.assertIn("no-store", cache, "GET / precisa proibir o cache do navegador")


if __name__ == "__main__":
    unittest.main()
