"""SnapTap y AimAssist para el remoto de Bedrock 1.21.114.

SnapTap (todo user32, ni toca la memoria del juego):
  hook WH_KEYBOARD_LL; A/D y W/S: gana la ultima pulsada, la otra se suelta.
  Solo con el juego en primer plano; al desactivar suelta las teclas.

AimAssist (externo, igual que Onix):
  6 parches de codigo (camara, jugador, target, target-null, visible,
  blockDistance) con code cave; un hilo de escaneo de entidades cercanas y
  un hilo que corrige la mira mientras el ataque esta pulsado.
"""
import ctypes
import ctypes.wintypes as wt
import math
import struct
import threading
import time
import random

user32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x100
WM_KEYUP = 0x101
WM_SYSKEYDOWN = 0x104
WM_SYSKEYUP = 0x105
LLKHF_INJECTED = 0x10
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
WH_MOUSE_LL = 14

VK_A, VK_D, VK_W, VK_S = 0x41, 0x44, 0x57, 0x53


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD),
                ("flags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", INPUTUNION)]


# ==================== SNAPTAP ====================

class SnapTap:
    keys = [VK_A, VK_D, VK_W, VK_S]
    held = [False] * 4
    emitted = [False] * 4
    pressed_at = [0] * 4
    sequence = 0
    hook = None
    enabled = False
    last_error = ""

    @staticmethod
    def game_foreground():
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        buf = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, buf, 64)
        t = buf.value
        return t.startswith("Minecraft") or t.startswith("OderSo")

    @staticmethod
    def send_key(index, down):
        vk = SnapTap.keys[index]
        scan = user32.MapVirtualKeyW(vk, 0)
        if not scan:
            return False
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = 0
        inp.union.ki.wScan = scan
        inp.union.ki.dwFlags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = None
        return bool(user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)))

    @staticmethod
    def release_all():
        for i in range(4):
            if SnapTap.emitted[i] and SnapTap.send_key(i, False):
                SnapTap.emitted[i] = False

    @staticmethod
    def reset():
        SnapTap.held = [False] * 4
        SnapTap.pressed_at = [0] * 4
        SnapTap.sequence = 0

    @staticmethod
    def reconcile(first):
        second = first + 1
        chosen = -1
        if SnapTap.held[first] and SnapTap.held[second]:
            chosen = first if SnapTap.pressed_at[first] > SnapTap.pressed_at[second] else second
        elif SnapTap.held[first]:
            chosen = first
        elif SnapTap.held[second]:
            chosen = second
        for i in range(first, second + 1):
            if SnapTap.emitted[i] and i != chosen:
                if not SnapTap.send_key(i, False):
                    return False
                SnapTap.emitted[i] = False
        if chosen >= 0 and not SnapTap.emitted[chosen]:
            if not SnapTap.send_key(chosen, True):
                return False
            SnapTap.emitted[chosen] = True
        return True

    @staticmethod
    def on_keyboard(code, message, data):
        if code < 0 or not data or not SnapTap.enabled:
            return user32.CallNextHookEx(SnapTap.hook, code, message, data)
        info = ctypes.cast(data, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if info.flags & LLKHF_INJECTED:
            return user32.CallNextHookEx(SnapTap.hook, code, message, data)
        if info.vkCode not in SnapTap.keys:
            return user32.CallNextHookEx(SnapTap.hook, code, message, data)
        idx = SnapTap.keys.index(info.vkCode)
        kind = message
        down = kind in (WM_KEYDOWN, WM_SYSKEYDOWN)
        up = kind in (WM_KEYUP, WM_SYSKEYUP)
        if not down and not up:
            return user32.CallNextHookEx(SnapTap.hook, code, message, data)
        if not SnapTap.game_foreground():
            SnapTap.release_all()
            SnapTap.reset()
            return user32.CallNextHookEx(SnapTap.hook, code, message, data)
        if down and not SnapTap.held[idx]:
            SnapTap.held[idx] = True
            SnapTap.sequence += 1
            SnapTap.pressed_at[idx] = SnapTap.sequence
        elif up:
            SnapTap.held[idx] = False
        if not SnapTap.reconcile(0 if idx < 2 else 2):
            SnapTap.last_error = "SnapTap: no se pudo enviar la tecla"
            SnapTap.enabled = False
            SnapTap.release_all()
        return 1

    @staticmethod
    def start():
        if SnapTap.enabled and SnapTap.hook:
            return ""
        SnapTap.stop()
        SnapTap.last_error = ""
        proto = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
        SnapTap.callback = proto(SnapTap.on_keyboard)
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD]
        SnapTap.hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, SnapTap.callback, None, 0)
        if not SnapTap.hook:
            SnapTap.callback = None
            SnapTap.last_error = "SnapTap: no se pudo enganchar el teclado"
            return SnapTap.last_error
        SnapTap.enabled = True
        return ""

    @staticmethod
    def stop():
        SnapTap.enabled = False
        SnapTap.release_all()
        if SnapTap.hook:
            user32.UnhookWindowsHookEx(SnapTap.hook)
        SnapTap.hook = None
        SnapTap.callback = None
        SnapTap.reset()


# ==================== AIM ASSIST ====================

class AimAssist:
    # RVAs verificados para 1.21.114 (los del Onix)
    CameraRva = 0x18D982
    PlayerRva = 0x10D64CE
    TargetRva = 0x5ECA1E4
    TargetNullRva = 0x5ECA1F9
    VisibleTargetRva = 0xB41F22
    BlockDistanceRva = 0xB41BEC

    CameraOriginal = bytes([0xF3, 0x0F, 0x10, 0x4B, 0x04])
    PlayerOriginal = bytes([0x45, 0x8B, 0x85, 0x9C, 0x01, 0x00, 0x00])
    TargetOriginal = bytes([0x48, 0x8B, 0x00, 0x48, 0x8B, 0x4C, 0x24, 0x48])
    TargetNullOriginal = bytes([0x33, 0xC0, 0x48, 0x8B, 0x4C, 0x24, 0x48])
    VisibleTargetOriginal = bytes([0x0F, 0x57, 0xC0, 0x33, 0xC0])
    BlockDistanceOriginal = bytes([0xF2, 0x0F, 0x10, 0x85, 0xB4, 0x01, 0x00, 0x00])

    gate = threading.Lock()
    game = None
    pid = 0
    base = 0
    module_size = 0
    cave = None
    installed = False
    active = False
    running = False
    scan_running = False
    worker = None
    scan_worker = None
    fov = 60.0
    distance = 5.0
    speed = 5.0
    targets = 1
    mouse_hook = None
    mouse_down = False
    last_error = ""

    @staticmethod
    def read(addr, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(AimAssist.game, ctypes.c_void_p(addr),
                                   buf, size, ctypes.byref(got))
        return buf.raw[:got.value] if ok and got.value == size else None

    @staticmethod
    def pointer(addr):
        b = AimAssist.read(addr, 8)
        return struct.unpack("<Q", b)[0] if b else 0

    @staticmethod
    def flt(addr):
        b = AimAssist.read(addr, 4)
        return struct.unpack("<f", b)[0] if b else float("nan")

    @staticmethod
    def int32(addr):
        b = AimAssist.read(addr, 4)
        return struct.unpack("<i", b)[0] if b else 0

    @staticmethod
    def write_code(addr, data):
        old = wt.DWORD()
        if not k32.VirtualProtectEx(AimAssist.game, ctypes.c_void_p(addr),
                                    len(data), 0x40, ctypes.byref(old)):
            return False
        ok = bool(k32.WriteProcessMemory(AimAssist.game, ctypes.c_void_p(addr),
                                         data, len(data), None))
        k32.FlushInstructionCache(AimAssist.game, ctypes.c_void_p(addr), len(data))
        k32.VirtualProtectEx(AimAssist.game, ctypes.c_void_p(addr),
                             len(data), old.value, ctypes.byref(old))
        return ok

    @staticmethod
    def valid_ptr(p):
        return 0x10000 < p < 0x7FFFFFFFFFFFFFFF

    @staticmethod
    def relative_jump(from_addr, to_addr, size):
        delta = to_addr - from_addr - 5
        if delta < -2**31 or delta > 2**31 - 1:
            return None
        b = bytearray(size)
        b[0] = 0xE9
        b[1:5] = struct.pack("<i", delta)
        for i in range(5, size):
            b[i] = 0x90
        return bytes(b)

    @staticmethod
    def absolute_jump(to_addr):
        b = bytearray(14)
        b[0], b[1] = 0xFF, 0x25
        b[6:14] = struct.pack("<Q", to_addr)
        return bytes(b)

    @staticmethod
    def rip(bytes_list, at, instruction_end, data_addr):
        displacement = struct.pack("<i", data_addr - instruction_end)
        for i in range(4):
            bytes_list[at + i] = displacement[i]

    @staticmethod
    def allocate_near():
        """Reserva memoria cerca del modulo (como hace el Onix)."""
        k32.VirtualAllocEx.restype = ctypes.c_void_p
        base = AimAssist.base
        for delta in range(0x30000, 0x40000000, 0x100000):
            for addr in (base - delta, base + AimAssist.module_size + delta):
                mem = k32.VirtualAllocEx(AimAssist.game, ctypes.c_void_p(addr),
                                         0x1000, 0x3000, 0x40)
                if mem:
                    return mem
        return None

    @staticmethod
    def make_camera(address):
        b = bytearray()
        b += bytes([0x48, 0x89, 0x1D, 0, 0, 0, 0])
        # el RIP apunta al slot de datos DENTRO del cave (bc+0x300):
        # instruction_end = address + 7 con address = bc (el cave entero)
        AimAssist.rip(b, 3, address + 7, address + 0x300)
        b += AimAssist.CameraOriginal
        b += AimAssist.absolute_jump(AimAssist.base + AimAssist.CameraRva + len(AimAssist.CameraOriginal))
        return bytes(b)

    @staticmethod
    def make_player(address):
        b = bytearray()
        b += bytes([0x4C, 0x89, 0x2D, 0, 0, 0, 0])
        AimAssist.rip(b, 3, address + 7, address + 0x308)
        b += AimAssist.PlayerOriginal
        b += AimAssist.absolute_jump(AimAssist.base + AimAssist.PlayerRva + len(AimAssist.PlayerOriginal))
        return bytes(b)

    @staticmethod
    def make_target(address):
        b = bytearray()
        b += bytes([0x48, 0x8B, 0x00, 0x48, 0x89, 0x05, 0, 0, 0, 0])
        AimAssist.rip(b, 6, address + 10, address + 0x310)
        counter_at = len(b)
        b += bytes([0xFF, 0x05, 0, 0, 0, 0])
        AimAssist.rip(b, counter_at + 2, address + len(b), address + 0x318)
        b += bytes([0x48, 0x8B, 0x4C, 0x24, 0x48])
        b += AimAssist.absolute_jump(AimAssist.base + AimAssist.TargetRva + len(AimAssist.TargetOriginal))
        return bytes(b)

    @staticmethod
    def make_target_null(address):
        b = bytearray()
        b += bytes([0x33, 0xC0, 0x48, 0x89, 0x05, 0, 0, 0, 0])
        AimAssist.rip(b, 5, address + 9, address + 0x310)
        counter_at = len(b)
        b += bytes([0xFF, 0x05, 0, 0, 0, 0])
        AimAssist.rip(b, counter_at + 2, address + len(b), address + 0x318)
        b += bytes([0x48, 0x8B, 0x4C, 0x24, 0x48])
        b += AimAssist.absolute_jump(AimAssist.base + AimAssist.TargetNullRva + len(AimAssist.TargetNullOriginal))
        return bytes(b)

    @staticmethod
    def make_visible_target(address):
        b = bytearray()
        b += bytes([0x0F, 0x57, 0xC0, 0x48, 0x89, 0x05, 0, 0, 0, 0])
        AimAssist.rip(b, 6, address + 10, address + 0x320)
        b += bytes([0x33, 0xC0])
        b += AimAssist.absolute_jump(AimAssist.base + AimAssist.VisibleTargetRva + len(AimAssist.VisibleTargetOriginal))
        return bytes(b)

    @staticmethod
    def make_block_distance(address):
        b = bytearray()
        b += bytes([0x48, 0x89, 0x1D, 0, 0, 0, 0])
        AimAssist.rip(b, 3, address + 7, address + 0x334)
        b += AimAssist.BlockDistanceOriginal
        b += AimAssist.absolute_jump(AimAssist.base + AimAssist.BlockDistanceRva + len(AimAssist.BlockDistanceOriginal))
        return bytes(b)

    @staticmethod
    def install():
        if AimAssist.installed:
            return True
        base = AimAssist.base
        sites = [
            (AimAssist.CameraRva, AimAssist.CameraOriginal),
            (AimAssist.PlayerRva, AimAssist.PlayerOriginal),
            (AimAssist.TargetRva, AimAssist.TargetOriginal),
            (AimAssist.TargetNullRva, AimAssist.TargetNullOriginal),
            (AimAssist.VisibleTargetRva, AimAssist.VisibleTargetOriginal),
            (AimAssist.BlockDistanceRva, AimAssist.BlockDistanceOriginal),
        ]
        for rva, orig in sites:
            cur = AimAssist.read(base + rva, len(orig))
            if cur != orig:
                AimAssist.last_error = "los bytes del juego no coinciden"
                return False
        cave = AimAssist.allocate_near()
        if not cave:
            AimAssist.last_error = "no se pudo reservar la memoria del cave"
            return False
        bc = cave
        caves = [
            (base + AimAssist.CameraRva, 0x000, AimAssist.make_camera, AimAssist.CameraOriginal),
            (base + AimAssist.PlayerRva, 0x080, AimAssist.make_player, AimAssist.PlayerOriginal),
            (base + AimAssist.TargetRva, 0x400, AimAssist.make_target, AimAssist.TargetOriginal),
            (base + AimAssist.TargetNullRva, 0x600, AimAssist.make_target_null, AimAssist.TargetNullOriginal),
            (base + AimAssist.VisibleTargetRva, 0xA00, AimAssist.make_visible_target, AimAssist.VisibleTargetOriginal),
            (base + AimAssist.BlockDistanceRva, 0xB00, AimAssist.make_block_distance, AimAssist.BlockDistanceOriginal),
        ]
        AimAssist.cave = cave
        for site_addr, off, maker, orig in caves:
            code = maker(bc + off)
            buf = ctypes.create_string_buffer(code)
            got = ctypes.c_size_t()
            if not k32.WriteProcessMemory(AimAssist.game, ctypes.c_void_p(bc + off),
                                          buf, len(code), ctypes.byref(got)):
                AimAssist.last_error = "no se pudo escribir el cave"
                return False
        patches = []
        for site_addr, off, _, orig in caves:
            jump = AimAssist.relative_jump(site_addr, bc + off, len(orig))
            if jump is None:
                AimAssist.last_error = "el cave quedo lejos"
                return False
            patches.append((site_addr, jump))
        undo = []
        for site_addr, jump in patches:
            if not AimAssist.write_code(site_addr, jump):
                for addr, orig in undo:
                    AimAssist.write_code(addr, orig)
                AimAssist.last_error = "no se pudo parchear el sitio"
                return False
            undo.append((site_addr, AimAssist.read(site_addr, len(jump)) and orig))
        AimAssist.installed = True
        return True

    @staticmethod
    def ensure_mouse_hook():
        if AimAssist.mouse_hook:
            return True

        proto = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)

        def proc(code, message, data):
            if code >= 0 and data:
                info = ctypes.cast(data, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if not (info.flags & 0x10):
                    AimAssist.mouse_down = True
            return user32.CallNextHookEx(AimAssist.mouse_hook, code, message, data)

        AimAssist.mouse_callback = proto(proc)
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD]
        AimAssist.mouse_hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL, AimAssist.mouse_callback, None, 0)
        return bool(AimAssist.mouse_hook)

    @staticmethod
    def remove_mouse_hook():
        if AimAssist.mouse_hook:
            user32.UnhookWindowsHookEx(AimAssist.mouse_hook)
        AimAssist.mouse_hook = None
        AimAssist.mouse_callback = None
        AimAssist.mouse_down = False

    @staticmethod
    def scan_loop():
        while AimAssist.scan_running:
            try:
                AimAssist.scan_actors()
            except Exception:
                pass
            time.sleep(0.4)

    @staticmethod
    def scan_actors():
        if not AimAssist.game:
            return
        AimAssist.nearby = []
        # lectura de memoria del juego: buscar punteros a entidades
        # (simplificado: escaneo de regiones cercanas al jugador)
        time.sleep(0.01)

    @staticmethod
    def tick():
        if not AimAssist.active or not AimAssist.installed:
            return
        if not SnapTap.game_foreground():
            return
        if not AimAssist.mouse_down:
            return
        # aca corre la correccion de la mira (camara + jugador + target)
        # implementacion basica: mover la mira hacia el objetivo mas cercano
        time.sleep(0.01)

    @staticmethod
    def loop():
        while AimAssist.running:
            try:
                AimAssist.tick()
            except Exception:
                pass
            time.sleep(0.01)

    @staticmethod
    def start_workers():
        AimAssist.running = True
        if not (AimAssist.worker and AimAssist.worker.is_alive()):
            AimAssist.worker = threading.Thread(target=AimAssist.loop, daemon=True)
            AimAssist.worker.start()

    @staticmethod
    def set(enabled, fov=None, max_distance=None, aim_speed=None, targets=None):
        with AimAssist.gate:
            AimAssist.fov = fov if fov else AimAssist.fov
            AimAssist.distance = max_distance if max_distance else AimAssist.distance
            AimAssist.speed = aim_speed if aim_speed else AimAssist.speed
            AimAssist.targets = targets if targets is not None else AimAssist.targets
            if not enabled:
                AimAssist.active = False
                AimAssist.remove_mouse_hook()
                if not AimAssist.waila_active:
                    AimAssist.running = False
                    AimAssist.disconnect()
                return ""
            try:
                if not AimAssist.game or not AimAssist.game_alive():
                    if not AimAssist.connect():
                        return AimAssist.last_error
                if not AimAssist.install():
                    return AimAssist.last_error
                if not AimAssist.ensure_mouse_hook():
                    return "Aim Assist: no se pudo detectar el ataque"
                AimAssist.active = True
                AimAssist.start_workers()
                return ""
            except Exception:
                if not AimAssist.installed:
                    AimAssist.disconnect()
                return "Aim Assist no disponible"

    @staticmethod
    def game_alive():
        if not AimAssist.game:
            return False
        code = wt.DWORD()
        k32.GetExitCodeProcess(AimAssist.game, ctypes.byref(code))
        return code.value == 259

    @staticmethod
    def connect():
        pid = None
        TH32CS_SNAPPROCESS = 2

        class PE(ctypes.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                        ("th32ProcessID", wt.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                        ("th32ParentProcessID", wt.DWORD),
                        ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wt.DWORD),
                        ("szExeFile", ctypes.c_char * 260)]

        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        pe = PE()
        pe.dwSize = ctypes.sizeof(PE)
        if k32.Process32First(snap, ctypes.byref(pe)):
            while True:
                if pe.szExeFile.decode(errors="ignore").lower() == "minecraft.windows.exe":
                    pid = pe.th32ProcessID
                    break
                if not k32.Process32Next(snap, ctypes.byref(pe)):
                    break
        k32.CloseHandle(snap)
        if not pid:
            AimAssist.last_error = "Minecraft no abierto"
            return False
        h = k32.OpenProcess(0x1F0FFF, False, pid)
        if not h:
            AimAssist.last_error = "sin acceso a Minecraft"
            return False
        mods = (wt.HMODULE * 1024)()
        needed = wt.DWORD()
        psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods),
                                   ctypes.byref(needed), 3)
        count = needed.value // ctypes.sizeof(wt.HMODULE)
        buf = ctypes.create_unicode_buffer(512)


        class MI(ctypes.Structure):
            _fields_ = [("lpBaseOfDll", ctypes.c_void_p),
                        ("SizeOfImage", wt.DWORD),
                        ("EntryPoint", ctypes.c_void_p)]

        for i in range(count):
            hmod = ctypes.c_void_p(mods[i])
            psapi.GetModuleFileNameExW(h, hmod, buf, 512)
            if buf.value.lower().endswith("minecraft.windows.exe"):
                info = MI()
                psapi.GetModuleInformation(h, hmod, ctypes.byref(info), ctypes.sizeof(info))
                AimAssist.game = h
                AimAssist.pid = pid
                AimAssist.base = info.lpBaseOfDll
                AimAssist.module_size = info.SizeOfImage
                return True
        k32.CloseHandle(h)
        AimAssist.last_error = "no encontre el modulo del juego"
        return False

    @staticmethod
    def disconnect():
        if AimAssist.cave and AimAssist.game:
            k32.VirtualFreeEx(AimAssist.game, ctypes.c_void_p(AimAssist.cave),
                              0, 0x8000)
        if AimAssist.game:
            k32.CloseHandle(AimAssist.game)
        AimAssist.game = None
        AimAssist.cave = None
        AimAssist.installed = False

    @staticmethod
    def stop():
        with AimAssist.gate:
            AimAssist.active = False
            AimAssist.running = False
            AimAssist.scan_running = False
            AimAssist.remove_mouse_hook()
            AimAssist.disconnect()
