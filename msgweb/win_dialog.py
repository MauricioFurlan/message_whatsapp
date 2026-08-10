"""
Controle da janela nativa "Abrir" do Windows via mensagens Win32 (ctypes).

Por que isso existe: no WhatsApp Web atual, o único jeito de anexar uma imagem
como FOTO (grande, inline) é clicar em "Fotos e vídeos" no menu de anexo — o que
faz o Chrome abrir a janela nativa de seleção de arquivos. O Selenium não
controla essa janela.

A solução é preencher o campo "Nome do arquivo" e acionar o botão "Abrir"
enviando mensagens diretamente para os controles da janela (WM_SETTEXT/BM_CLICK).
Diferente de simular teclado, isso NÃO depende de foco: o usuário pode estar
usando o computador normalmente enquanto o envio acontece.

Só funciona no Windows. Em outros sistemas, as funções retornam None/False.
"""

import ctypes
import sys
import time
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

# Classe das dialogs padrão do Windows (inclui a de seleção de arquivos)
DIALOG_CLASS = "#32770"

WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_COMMAND = 0x0111
BM_CLICK = 0x00F5
IDOK = 1
IDCANCEL = 2

# Rótulos do botão de confirmação em pt-BR e en (o & é o atalho sublinhado)
CONFIRM_LABELS = ("abrir", "open", "selecionar", "select", "salvar", "save")


if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
    user32.EnumChildWindows.argtypes = [wintypes.HWND, EnumWindowsProc, wintypes.LPARAM]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.SendMessageW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p
    ]
    user32.SendMessageW.restype = ctypes.c_long


def _class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_text(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _children(hwnd) -> list:
    """Filhos diretos de uma janela."""
    encontrados = []

    def callback(child, _lparam):
        encontrados.append(child)
        return True

    user32.EnumChildWindows(hwnd, EnumWindowsProc(callback), 0)
    return encontrados


def list_dialogs() -> set:
    """Handles das dialogs (#32770) visíveis no momento."""
    if not IS_WINDOWS:
        return set()

    encontradas = set()

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and _class_name(hwnd) == DIALOG_CLASS:
            encontradas.add(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return encontradas


def wait_for_new_dialog(antes: set, timeout: float = 15.0):
    """
    Espera uma dialog nova aparecer (comparando com o conjunto `antes`).
    Retorna o handle ou None.
    """
    if not IS_WINDOWS:
        return None

    fim = time.time() + timeout
    while time.time() < fim:
        novas = list_dialogs() - antes
        for hwnd in novas:
            # Confirma que é uma dialog de arquivo: tem campo de nome
            if find_filename_field(hwnd):
                return hwnd
        time.sleep(0.2)
    return None


def find_filename_field(dialog):
    """
    Encontra o campo "Nome do arquivo". Na dialog moderna ele é um Edit dentro
    de um ComboBox/ComboBoxEx32 — importante distinguir da caixa de pesquisa,
    que também é um Edit mas não fica dentro de um ComboBox.
    """
    if not IS_WINDOWS or not dialog:
        return None

    def procurar(hwnd, dentro_de_combo=False, profundidade=0):
        if profundidade > 6:
            return None
        for child in _children(hwnd):
            cls = _class_name(child)
            if cls == "Edit" and dentro_de_combo:
                return child
            achado = procurar(
                child,
                dentro_de_combo or cls.startswith("ComboBox"),
                profundidade + 1,
            )
            if achado:
                return achado
        return None

    return procurar(dialog)


def find_confirm_button(dialog):
    """Encontra o botão Abrir/Open da dialog."""
    if not IS_WINDOWS or not dialog:
        return None

    def procurar(hwnd, profundidade=0):
        if profundidade > 6:
            return None
        for child in _children(hwnd):
            if _class_name(child) == "Button":
                texto = _window_text(child).replace("&", "").strip().lower()
                if texto in CONFIRM_LABELS:
                    return child
            achado = procurar(child, profundidade + 1)
            if achado:
                return achado
        return None

    return procurar(dialog)


def set_text(hwnd, texto: str) -> bool:
    """Escreve texto em um controle (WM_SETTEXT) e confere se colou."""
    if not IS_WINDOWS or not hwnd:
        return False
    buf = ctypes.create_unicode_buffer(texto)
    user32.SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.cast(buf, ctypes.c_void_p))
    return get_text(hwnd) == texto


def get_text(hwnd) -> str:
    """Lê o texto de um controle (WM_GETTEXT)."""
    if not IS_WINDOWS or not hwnd:
        return ""
    tamanho = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, None) + 1
    buf = ctypes.create_unicode_buffer(tamanho)
    user32.SendMessageW(
        hwnd, WM_GETTEXT, tamanho, ctypes.cast(buf, ctypes.c_void_p)
    )
    return buf.value


def submit_dialog(dialog) -> bool:
    """Aciona o botão Abrir (ou manda IDOK como reserva)."""
    if not IS_WINDOWS or not dialog:
        return False

    botao = find_confirm_button(dialog)
    if botao:
        user32.SendMessageW(botao, BM_CLICK, 0, None)
        return True

    user32.SendMessageW(dialog, WM_COMMAND, IDOK, None)
    return True


def cancel_dialog(dialog) -> bool:
    """Fecha a dialog sem escolher arquivo."""
    if not IS_WINDOWS or not dialog:
        return False
    user32.SendMessageW(dialog, WM_COMMAND, IDCANCEL, None)
    return True


def is_open(dialog) -> bool:
    """A dialog ainda existe?"""
    if not IS_WINDOWS or not dialog:
        return False
    return bool(user32.IsWindow(dialog))


def wait_closed(dialog, timeout: float = 10.0) -> bool:
    """Espera a dialog fechar. Retorna True se fechou."""
    fim = time.time() + timeout
    while time.time() < fim:
        if not is_open(dialog):
            return True
        time.sleep(0.2)
    return False


def choose_file(dialog, caminho: str) -> bool:
    """
    Preenche o nome do arquivo e confirma. Retorna True se a dialog fechou,
    o que significa que o arquivo foi aceito.
    """
    campo = find_filename_field(dialog)
    if not campo:
        return False
    if not set_text(campo, caminho):
        return False
    time.sleep(0.2)
    if not submit_dialog(dialog):
        return False
    return wait_closed(dialog, timeout=10.0)
