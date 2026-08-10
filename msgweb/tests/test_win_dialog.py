"""
Teste de integração do win_dialog: abre uma janela nativa "Abrir" de verdade
(via PowerShell/OpenFileDialog) e verifica se conseguimos preencher o nome do
arquivo e confirmar sem usar teclado nem roubar o foco.

Executa com:
    python tests/test_win_dialog.py
"""

import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import win_dialog  # noqa: E402

PS_SCRIPT = """
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = 'Abrir'
$d.Filter = 'Todos|*.*'
if ($d.ShowDialog() -eq 'OK') {{
    Set-Content -LiteralPath '{saida}' -Value $d.FileName -Encoding UTF8
}} else {{
    Set-Content -LiteralPath '{saida}' -Value 'CANCELADO' -Encoding UTF8
}}
"""


def main():
    if not win_dialog.IS_WINDOWS:
        print("PULADO  win_dialog só se aplica ao Windows")
        return 0

    log_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "resultado_win_dialog.txt"
    )
    log_file = open(log_path, "w", encoding="utf-8")

    def log(msg):
        print(msg, flush=True)
        log_file.write(msg + "\n")
        log_file.flush()

    tmp = tempfile.mkdtemp(prefix="win_dialog_")
    alvo = os.path.join(tmp, "arquivo de teste com acento çãé.txt")
    with open(alvo, "w", encoding="utf-8") as fh:
        fh.write("conteudo")

    saida = os.path.join(tmp, "escolhido.txt")
    ps_path = os.path.join(tmp, "abrir.ps1")
    with open(ps_path, "w", encoding="utf-8") as fh:
        fh.write(PS_SCRIPT.format(saida=saida.replace("'", "''")))

    antes = win_dialog.list_dialogs()
    proc = subprocess.Popen(
        ["powershell", "-STA", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", ps_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    falhas = []
    try:
        dialog = win_dialog.wait_for_new_dialog(antes, timeout=25.0)
        if not dialog:
            log("FALHOU  não encontrou a janela 'Abrir'")
            return 1
        log(f"PASSOU  janela 'Abrir' encontrada (hwnd={dialog})")

        campo = win_dialog.find_filename_field(dialog)
        if not campo:
            log("FALHOU  não encontrou o campo 'Nome do arquivo'")
            falhas.append("campo")
        else:
            log(f"PASSOU  campo 'Nome do arquivo' encontrado (hwnd={campo})")

        botao = win_dialog.find_confirm_button(dialog)
        if not botao:
            log("AVISO   botão 'Abrir' não encontrado — usará IDOK como reserva")
        else:
            rotulo = win_dialog._window_text(botao).encode("ascii", "replace").decode()
            log(f"PASSOU  botão de confirmação encontrado: '{rotulo}'")

        ok = win_dialog.choose_file(dialog, alvo)
        if not ok:
            log("FALHOU  choose_file não fechou a janela")
            falhas.append("choose_file")
        else:
            log("PASSOU  janela preenchida e confirmada (sem teclado, sem foco)")

        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            log("AVISO   o processo da dialog não encerrou em 15s")

        if not os.path.exists(saida):
            log("FALHOU  a dialog não gravou o arquivo escolhido")
            falhas.append("saida")
        else:
            with open(saida, encoding="utf-8-sig") as fh:
                escolhido = fh.read().strip()
            if escolhido == alvo:
                log("PASSOU  arquivo selecionado corretamente (caminho confere)")
            else:
                log(f"FALHOU  esperado != obtido:\n  {alvo!r}\n  {escolhido!r}")
                falhas.append("caminho")
    finally:
        if proc.poll() is None:
            for d in win_dialog.list_dialogs() - antes:
                win_dialog.cancel_dialog(d)
            time.sleep(1)
            if proc.poll() is None:
                proc.kill()

    if falhas:
        log(f"RESULTADO: FALHOU ({', '.join(falhas)})")
        log_file.close()
        return 1
    log("RESULTADO: OK — dá para controlar a janela nativa sem teclado")
    log_file.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
