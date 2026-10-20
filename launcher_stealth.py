"""Onix Remote — launcher sigiloso.

Corre el cheat remoto sin consola y con nombre de proceso inofensivo:
  - la ventana cmd se oculta al instante
  - si el exe es python.exe/pythonw.exe, se lanza una copia con nombre
    de updater (msedgewu.exe) desde una carpeta de sistema conocida
  - el puerto solo vive mientras el cheat corre; el PANIC lo cierra

Uso:  pythonw launcher_stealth.py       (doble clic, sin ventana)
"""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile

PY = sys.executable
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "onix_remote.py")
HIDE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "EdgeUpdate")
STAMP_EXE = os.path.join(HIDE_DIR, "msedgewu.exe")


def console_hide():
    h = ctypes.windll.kernel32.GetConsoleWindow()
    if h:
        ctypes.windll.user32.ShowWindow(h, 0)


def runner():
    """Un exe con nombre inofensivo que corra el script (copia de pythonw)."""
    try:
        os.makedirs(HIDE_DIR, exist_ok=True)
        pythonw = PY.replace("python.exe", "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = PY
        if not os.path.exists(STAMP_EXE) or \
                os.path.getsize(STAMP_EXE) != os.path.getsize(pythonw):
            shutil.copy2(pythonw, STAMP_EXE)
        return STAMP_EXE
    except Exception:
        return None


def main():
    console_hide()
    runner_exe = runner()
    if runner_exe and os.path.exists(SRC):
        # corre el cheat con el exe disfrazado (sin consola, nombre inofensivo)
        DETACHED = 0x00000008
        subprocess.Popen([runner_exe, SRC], close_fds=True,
                         creationflags=DETACHED)
        return
    # fallback: el propio interprete (sigue funcionando, menos sigilo)
    subprocess.Popen([PY, SRC])


if __name__ == "__main__":
    main()
