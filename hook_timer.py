"""Prototype en Python del hook de Timer sobre Bedrock 1.21.114 (externo).

Prueba el mecanismo completo de Nitr0 sin compilar nada:
  attach -> base -> shellcode remoto (mul + add original + jmp back) -> patch
Empieza con multiplicador NEUTRO (20.0) para no romper nada; a los 60s pone
40.0 (deberia verse 2x speed). Log a archivo. A los 180s restaura todo.
"""
import ctypes
import ctypes.wintypes as wt
import os
import struct
import sys
import time

EXE = (r"C:\Program Files\WindowsApps\Microsoft.MinecraftUWP_1.21.11401.0_x64__"
       r"8wekyb3d8bbwe\Minecraft.Windows.exe")
LOG = r"C:\Users\jp\Documents\bedrock\hook_log.txt"
PATTERN = b"\xf3\x0f\x58\x4b\x10"          # addss xmm1,[rbx+10] (sitio del hook)
GAME = "Minecraft.Windows.exe"

out = open(LOG, "w", encoding="utf-8")


def log(m):
    out.write(m + "\n")
    out.flush()


k32 = ctypes.windll.kernel32
k32.VirtualAllocEx.restype = ctypes.c_void_p
psapi = ctypes.windll.psapi
adv = ctypes.windll.advapi32

PROCESS_ALL = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_RWX = 0x40


def enable_debug():
    tok = wt.HANDLE()
    adv.OpenProcessToken(ctypes.windll.kernel32.GetCurrentProcess(), 0x28, ctypes.byref(tok))
    tp = (ctypes.c_char * 32)()
    adv.LookupPrivilegeValueW(None, "SeDebugPrivilege",
                              ctypes.cast(tp, ctypes.POINTER(ctypes.c_ulonglong)))
    # estructura TOKEN_PRIVILEGES minima: count=1, luid, attr=2
    struct.pack_into("<I", tp, 0, 1)
    luid = struct.unpack_from("<Q", tp, 4)[0]
    struct.pack_into("<IQQ", tp, 0, 1, luid, 2)
    adv.AdjustTokenPrivileges(tok, False, tp, 0, None, None)


def find_pid(name):
    TH32CS_SNAPPROCESS = 2
    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                    ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_char * 260)]
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    pe = PE(); pe.dwSize = ctypes.sizeof(PE)
    pid = None
    if k32.Process32First(snap, ctypes.byref(pe)):
        while True:
            if pe.szExeFile.decode(errors="ignore").lower() == name.lower():
                pid = pe.th32ProcessID
                break
            if not k32.Process32Next(snap, ctypes.byref(pe)):
                break
    k32.CloseHandle(snap)
    return pid


def module_base(handle):
    LIST_MODULES_ALL = 3
    mods = (wt.HMODULE * 1024)()
    needed = wt.DWORD()
    if not psapi.EnumProcessModulesEx(handle, mods, ctypes.sizeof(mods), ctypes.byref(needed), LIST_MODULES_ALL):
        return None, None
    count = needed.value // ctypes.sizeof(wt.HMODULE)
    name_buf = ctypes.create_unicode_buffer(512)
    for i in range(count):
        hmod = ctypes.c_void_p(mods[i])
        psapi.GetModuleFileNameExW(handle, hmod, name_buf, 512)
        if name_buf.value.lower().endswith(GAME.lower()):
            class MODULEINFO(ctypes.Structure):
                _fields_ = [("lpBaseOfDll", ctypes.c_void_p), ("SizeOfImage", wt.DWORD), ("EntryPoint", ctypes.c_void_p)]
            info = MODULEINFO()
            psapi.GetModuleInformation(handle, hmod, ctypes.byref(info), ctypes.sizeof(info))
            return info.lpBaseOfDll, info.SizeOfImage
    return None, None


def rpm(handle, addr, size):
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
        raise OSError(f"RPM fallo @ {addr:#x}")
    return buf.raw[:got.value]


def wpm(handle, addr, data):
    old = wt.DWORD()
    k32.VirtualProtectEx(handle, ctypes.c_void_p(addr), len(data), PAGE_RWX, ctypes.byref(old))
    if not k32.WriteProcessMemory(handle, ctypes.c_void_p(addr), data, len(data), None):
        raise OSError(f"WPM fallo @ {addr:#x}")
    k32.VirtualProtectEx(handle, ctypes.c_void_p(addr), len(data), old, ctypes.byref(old))


def file_off_to_rva(file_off):
    with open(EXE, "rb") as f:
        pe_e_lfanew = struct.unpack("<I", f.read(4)[0:0] or b"") if False else None
        f.seek(0x3C)
        e_lfanew = struct.unpack("<I", f.read(4))[0]
        f.seek(e_lfanew + 6)
        nsec = struct.unpack("<H", f.read(2))[0]
        f.seek(e_lfanew + 20)                    # SizeOfOptionalHeader en +20
        opt_size = struct.unpack("<H", f.read(2))[0]
        sec0 = e_lfanew + 24 + opt_size
        for i in range(nsec):
            f.seek(sec0 + i * 40)
            hdr = f.read(40)
            name = hdr[:8].rstrip(b"\x00").decode("latin1")
            vsize, vaddr, rawsize, rawptr = struct.unpack("<IIII", hdr[8:24])
            if rawptr <= file_off < rawptr + rawsize:
                return vaddr + (file_off - rawptr)
    raise RuntimeError("seccion no encontrada")


def main():
    enable_debug()
    pid = find_pid(GAME)
    log(f"pid={pid}")
    if not pid:
        log("juego no encontrado"); return
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        log(f"OpenProcess fallo err={k32.GetLastError()}"); return
    base, size = module_base(h)
    log(f"base={base:#x} size={size:#x}")

    # --- localizar el addss objetivo (file offset conocido -> RVA) ---
    FILE_OFF = 0x4EDD425
    rva = file_off_to_rva(FILE_OFF)
    target = base + rva
    got = rpm(h, target, 5)
    log(f"addss @ {target:#x} bytes={got.hex(' ')}")
    if got != PATTERN:
        log("los bytes no coinciden con el patron esperado"); return

    # --- memoria remota para shellcode + data (busca sitio libre cerca) ---
    hookmem = datamem = None
    delta = 0x30000
    while delta < 0x40000000:
        if hookmem is None:
            hookmem = k32.VirtualAllocEx(h, ctypes.c_void_p(base - delta), 512,
                                         MEM_COMMIT | MEM_RESERVE, PAGE_RWX)
            if hookmem:
                log(f"hookmem={hookmem:#x} (delta={delta:#x})")
        elif datamem is None:
            datamem = k32.VirtualAllocEx(h, ctypes.c_void_p(base - delta), 512,
                                         MEM_COMMIT | MEM_RESERVE, PAGE_RWX)
            if datamem:
                log(f"datamem={datamem:#x} (delta={delta:#x})")
        if hookmem and datamem:
            break
        delta += 0x100000
    if not hookmem or not datamem:
        log("alloc fallo en todo el rango"); return
    log(f"hookmem={hookmem:#x} datamem={datamem:#x}")

    # data: [0] = multiplicador (float). NEUTRO = 1.0 (inserta un mul que
    # el juego no tenia: 20.0 = 20x speed = crashea)
    wpm(h, datamem, struct.pack("<f", 1.0))      # neutro real

    # shellcode: mulss xmm1,[datamem] ; addss xmm1,[rbx+10] ; jmp back
    sc = bytearray()
    sc += b"\xf3\x0f\x59\x0d" + struct.pack("<i", datamem - (hookmem + len(sc) + 8))
    sc += b"\xf3\x0f\x58\x4b\x10"
    rel = target - (hookmem + len(sc) + 5)
    sc += b"\xe9" + struct.pack("<i", rel)
    wpm(h, hookmem, bytes(sc))

    # patch: jmp del addss al shellcode
    orig = rpm(h, target, 5)
    jmp = b"\xe9" + struct.pack("<i", hookmem - (target + 5))
    wpm(h, target, jmp)
    log("hook aplicado (multiplicador neutro 1.0) -- el juego deberia ir NORMAL")

    t0 = time.time()
    stage = 0
    while time.time() - t0 < 240:
        time.sleep(2)
        if not find_pid(GAME):
            log(f"EL JUEGO CRASHEO a los {time.time()-t0:.0f}s (stage={stage})")
            return
        if stage == 0 and time.time() - t0 > 60:
            wpm(h, datamem, struct.pack("<f", 2.0))
            log("multiplicador 2.0 -> 2x speed (mirar el juego)")
            stage = 1
        if stage == 1 and time.time() - t0 > 120:
            wpm(h, datamem, struct.pack("<f", 1.0))
            log("de vuelta a 1.0 (normal)")
            stage = 2
        if stage == 2 and time.time() - t0 > 180:
            break

    # restore
    wpm(h, target, orig)
    k32.VirtualFreeEx(h, ctypes.c_void_p(hookmem), 0, MEM_RELEASE)
    k32.VirtualFreeEx(h, ctypes.c_void_p(datamem), 0, MEM_RELEASE)
    log("restaurado y liberado -- FIN")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log("CRASH: " + traceback.format_exc())
    out.close()
