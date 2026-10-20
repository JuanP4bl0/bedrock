"""Limpia el hook viejo que quedo pegado en el juego: restaura los bytes
originales del addss y libera la memoria remota que quedo reservada."""
import ctypes
import ctypes.wintypes as wt
import struct

GAME = "Minecraft.Windows.exe"
BASE = 0x7FF6E2280000
TARGET = BASE + 0x4EDCA25
ORIG = b"\xf3\x0f\x58\x4b\x10"

k32 = ctypes.windll.kernel32
k32.VirtualAllocEx.restype = ctypes.c_void_p

h = k32.OpenProcess(0x1F0FFF, False, __import__("subprocess").check_output(
    ["tasklist", "/fi", f"imagename eq {GAME}", "/fo", "csv", "/nh"],
    text=True).split('"')[1].split('"')[0] if False else None) if False else None

# buscar pid
import ctypes.wintypes as w
TH32CS_SNAPPROCESS = 2


class PE(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD),
                ("th32ProcessID", w.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", w.DWORD), ("szExeFile", ctypes.c_char * 260)]


snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
pe = PE(); pe.dwSize = ctypes.sizeof(PE)
pid = None
if k32.Process32First(snap, ctypes.byref(pe)):
    while True:
        if pe.szExeFile.decode(errors="ignore").lower() == GAME.lower():
            pid = pe.th32ProcessID
            break
        if not k32.Process32Next(snap, ctypes.byref(pe)):
            break
k32.CloseHandle(snap)
print(f"pid={pid}")
h = k32.OpenProcess(0x1F0FFF, False, pid)
print(f"handle={'ok' if h else 'fallo'}")

buf = ctypes.create_string_buffer(5)
got = ctypes.c_size_t()
k32.ReadProcessMemory(h, ctypes.c_void_p(TARGET), buf, 5, ctypes.byref(got))
print(f"bytes actuales: {buf.raw.hex(' ')}")

if buf.raw != ORIG:
    old = wt.DWORD()
    k32.VirtualProtectEx(h, ctypes.c_void_p(TARGET), 5, 0x40, ctypes.byref(old))
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(TARGET), ORIG, 5, None)
    k32.VirtualProtectEx(h, ctypes.c_void_p(TARGET), 5, old, ctypes.byref(old))
    print(f"restaurado: {ok}")
else:
    print("ya estaba original")

# liberar la memoria remota del run viejo (hookmem deducido del jmp)
if buf.raw.startswith(b"\xe9"):
    rel = struct.unpack("<i", buf.raw[1:5])[0]
    hookmem = TARGET + 5 + rel
    datamem = hookmem - 0x100000
    print(f"hookmem viejo: {hookmem:#x}  datamem: {datamem:#x}")
    for addr in (hookmem, datamem):
        ok = k32.VirtualFreeEx(h, ctypes.c_void_p(addr), 0, 0x8000)
        print(f"liberado {addr:#x}: {ok}")

k32.ReadProcessMemory(h, ctypes.c_void_p(TARGET), buf, 5, ctypes.byref(got))
print(f"bytes finales: {buf.raw.hex(' ')}")
