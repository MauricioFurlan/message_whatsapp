"""
Launcher do WhatsApp Automação.

Ponto de entrada do .exe:
- Inicia o servidor FastAPI (hypercorn)
- Abre o navegador padrão em localhost:8000
- Exibe janela de console mínima com status
"""

import os
import sys
import signal
import threading
import time
import webbrowser
import asyncio

# Garante que o diretório de trabalho é onde o .exe está
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))


def open_browser():
    """Abre o navegador após aguardar o servidor iniciar."""
    time.sleep(2)
    webbrowser.open("http://localhost:8000")


def main():
    print("=" * 50)
    print("  WhatsApp Automação")
    print("=" * 50)
    print()
    print("  Servidor iniciando...")
    print("  Acesse: http://localhost:8000")
    print()
    print("  Para fechar: feche esta janela ou Ctrl+C")
    print("=" * 50)
    print()

    # Abre o navegador em thread separada
    threading.Thread(target=open_browser, daemon=True).start()

    from app import app, state
    from hypercorn.config import Config
    from hypercorn.asyncio import serve

    config = Config()
    # Escuta APENAS em localhost. Com 0.0.0.0 qualquer máquina da mesma rede
    # acessaria a interface sem autenticação (lista de contatos, download da
    # planilha, log e disparo de envios). O navegador local não precisa disso.
    config.bind = ["127.0.0.1:8000"]
    config.loglevel = "WARNING"

    def force_exit(sig, frame):
        """Força encerramento."""
        print("\nEncerrando...")
        if state.sender and state.sender._driver:
            try:
                state.sender._driver.quit()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, force_exit)
    signal.signal(signal.SIGTERM, force_exit)

    try:
        asyncio.run(serve(app, config))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\nERRO: {e}")
        print("\nPressione Enter para fechar...")
        input()


if __name__ == "__main__":
    main()
