"""The Gold Volt desktop window. It holds no passwords, keys or business data."""
import ctypes
import sys
import urllib.error
import urllib.request

import webview

BASE_URL = "http://127.0.0.1:8765"
MUTEX_NAME = "GoldVoltWindowSingleInstance"
ERROR_ALREADY_EXISTS = 183

NOT_RUNNING = """<!doctype html><meta charset="utf-8"><title>Gold Volt</title>
<body style="font-family:Segoe UI,Tahoma,sans-serif;text-align:center;padding:4rem">
<p>Gold Volt service is not running.</p><p dir="rtl">خدمة Gold Volt لا تعمل.</p>
<button onclick="pywebview.api.retry()">Retry / إعادة المحاولة</button></body>"""


def service_is_up():
    try:
        with urllib.request.urlopen(f"{BASE_URL}/health/", timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


class Api:
    """The only native actions pages can ask for."""

    def __init__(self):
        self._window = None

    def retry(self):
        if service_is_up():
            self._window.load_url(BASE_URL)

    def save_text(self, filename, text):
        chosen = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=filename,
                                                file_types=("Text file (*.txt)",))
        if not chosen:
            return False
        path = chosen if isinstance(chosen, str) else chosen[0]
        if path.upper().startswith("C:") and not self._window.create_confirmation_dialog(
            "Gold Volt",
            "This location is on this computer, where other users could read it. Save here anyway?\n\n"
            "هذا المكان موجود على هذا الحاسوب ويمكن لمستخدمين آخرين قراءته. هل تحفظ هنا رغم ذلك؟",
        ):
            return False
        with open(path, "w", encoding="utf-8", newline="\r\n") as handle:
            handle.write(text)
        return True


def main():
    ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        sys.exit(0)
    api = Api()
    if service_is_up():
        api._window = webview.create_window("Gold Volt", BASE_URL, js_api=api, width=1280, height=820)
    else:
        api._window = webview.create_window("Gold Volt", html=NOT_RUNNING, js_api=api, width=640, height=360)
    webview.start(debug=False, private_mode=True, gui="edgechromium")


if __name__ == "__main__":
    main()
