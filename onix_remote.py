"""Onix Remote Cheat — Minecraft Bedrock 1.21.114 controlado desde el celu.

Como funciona:
  - El cheat corre EN LA PC del usuario (un script Python que lee/escribe la
    memoria del juego desde afuera; sin DLL, sin inyeccion, sin exe aparte).
  - Abre un servidor web local con token por sesion.
  - Desde el celu (mismo WiFi) abris la URL y tenes los modulos:
    Reach, Velocity XZ/Y, Air y el estado del juego en vivo.

Multiusuario: cada sesion tiene su token; quien comparte la tool le pasa el
archivo a otro y ese otro corre el suyo (el script busca SU juego y sirve SU
panel). Sin licencias ni claves: token por arranque.

Uso:  py onix_remote.py            (detecta el juego, sirve el panel)
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import random
import re
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

GAME_EXE = "Minecraft.Windows.exe"
PORT_RANGE = (21000, 44000)
STATE_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "SSTool", "remote.json")
LOG_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "SSTool", "remote.log")

# ==== memoria ====
k32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi

PROCESS_ALL = 0x1F0FFF
MEM_COMMIT = 0x1000
PAGE_RWX = 0x40


def find_pid(name=GAME_EXE):
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


class Game:
    handle = None
    pid = 0
    base = 0
    size = 0

    @classmethod
    def attach(cls):
        pid = find_pid()
        if not pid:
            return False
        h = k32.OpenProcess(PROCESS_ALL, False, pid)
        if not h:
            return False
        mods = (wt.HMODULE * 1024)()
        needed = wt.DWORD()
        if not psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods),
                                          ctypes.byref(needed), 3):
            k32.CloseHandle(h)
            return False
        count = needed.value // ctypes.sizeof(wt.HMODULE)
        buf = ctypes.create_unicode_buffer(512)

        class MI(ctypes.Structure):
            _fields_ = [("lpBaseOfDll", ctypes.c_void_p),
                        ("SizeOfImage", wt.DWORD),
                        ("EntryPoint", ctypes.c_void_p)]

        for i in range(count):
            hmod = ctypes.c_void_p(mods[i])
            psapi.GetModuleFileNameExW(h, hmod, buf, 512)
            if buf.value.lower().endswith(GAME_EXE.lower()):
                info = MI()
                psapi.GetModuleInformation(h, hmod, ctypes.byref(info),
                                           ctypes.sizeof(info))
                cls.handle = h
                cls.pid = pid
                cls.base = info.lpBaseOfDll
                cls.size = info.SizeOfImage
                return True
        k32.CloseHandle(h)
        return False

    @classmethod
    def alive(cls):
        if not cls.handle:
            return False
        code = wt.DWORD()
        k32.GetExitCodeProcess(cls.handle, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE

    @classmethod
    def read_bytes(cls, rva, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(cls.handle, ctypes.c_void_p(cls.base + rva),
                                     buf, size, ctypes.byref(got)):
            return None
        return buf.raw[:got.value]

    @classmethod
    def write_bytes(cls, rva, data):
        old = wt.DWORD()
        addr = cls.base + rva
        if not k32.VirtualProtectEx(cls.handle, ctypes.c_void_p(addr), len(data),
                                    PAGE_RWX, ctypes.byref(old)):
            return False
        ok = bool(k32.WriteProcessMemory(cls.handle, ctypes.c_void_p(addr),
                                         data, len(data), None))
        k32.VirtualProtectEx(cls.handle, ctypes.c_void_p(addr), len(data),
                             old.value, ctypes.byref(old))
        return ok

    @classmethod
    def read_float(cls, rva):
        buf = ctypes.create_string_buffer(4)
        got = ctypes.c_size_t()
        addr = cls.base + rva
        if not k32.ReadProcessMemory(cls.handle, ctypes.c_void_p(addr),
                                     buf, 4, ctypes.byref(got)):
            return None
        return struct.unpack("<f", buf.raw[:4])[0]

    @classmethod
    def write_float(cls, rva, value):
        old = wt.DWORD()
        addr = cls.base + rva
        if not k32.VirtualProtectEx(cls.handle, ctypes.c_void_p(addr), 4,
                                    PAGE_RWX, ctypes.byref(old)):
            return False
        data = struct.pack("<f", value)
        ok = bool(k32.WriteProcessMemory(cls.handle, ctypes.c_void_p(addr),
                                         data, 4, None))
        k32.VirtualProtectEx(cls.handle, ctypes.c_void_p(addr), 4,
                             old.value, ctypes.byref(old))
        return ok


# ==== modulos (valores verificados para 1.21.114) ====
# - float_sites: un solo float en memoria que se lee/escribe directo.
# - code_sites: instrucciones del juego que contienen un float constante
#   (bits) que se reescribe multiplicado (asi hace el AirAcceleration de
#   Onix: 4 sites walk/sprint, con verificacion de bytes originales).
MODULES = {
    "reach": {"rva": 145749080, "min": 3.0, "max": 7.0, "default": 3.0},
    "velxz": {"rva": 0x2637850, "min": 0.0, "max": 1.0, "default": 1.0},
}

AIR_WALK_BITS = 0x3CA3D70A          # float 0.02 (aceleracion al caminar)
AIR_SPRINT_BITS = 0x3CD4FDF3        # float 0.026 (aceleracion al esprintar)
AIR_SITES = [0x28C5684, 0x28C5691, 0x28CCEAB, 0x28CCEC9]
AIR_DEFAULTS = [AIR_WALK_BITS, AIR_SPRINT_BITS, AIR_WALK_BITS, AIR_SPRINT_BITS]
AIR_MULT_MAX = 3.0

MODULES["air"] = {"min": 1.0, "max": AIR_MULT_MAX, "default": 1.0,
                  "code": True}

# parches NOP de codigo verificado en 1.21.114 (del Onix):
# - ItemDelay: el call indirecto del cooldown de ataque -> NOPs (ataque sin espera)
ITEM_DELAY_RVA = 0xACC36C
ITEM_DELAY_ORIG = bytes([0xFF, 0x15, 0x16, 0x64, 0x78, 0x07])
# - NoCamReset: stores de la posicion de camara al respawn -> NOPs
NOCAM_RVA = 0x18D9D7
NOCAM_ORIG = bytes([0xF3, 0x0F, 0x11, 0x07, 0xF3, 0x0F, 0x11, 0x4F, 0x04])
NOP_PATCHES = {
    "itemdelay": (ITEM_DELAY_RVA, ITEM_DELAY_ORIG),
    "nocam": (NOCAM_RVA, NOCAM_ORIG),
}
for _n in NOP_PATCHES:
    MODULES[_n] = {"min": 0, "max": 1, "default": 0, "nop": True}

state = {"on": {}, "value": {}}
stateLock = threading.Lock()


def read_int(rva):
    buf = ctypes.create_string_buffer(4)
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(Game.handle, ctypes.c_void_p(Game.base + rva),
                                 buf, 4, ctypes.byref(got)):
        return None
    return struct.unpack("<I", buf.raw[:4])[0]


def write_int(rva, bits):
    old = wt.DWORD()
    addr = Game.base + rva
    if not k32.VirtualProtectEx(Game.handle, ctypes.c_void_p(addr), 4,
                                PAGE_RWX, ctypes.byref(old)):
        return False
    data = struct.pack("<I", bits)
    ok = bool(k32.WriteProcessMemory(Game.handle, ctypes.c_void_p(addr), data, 4, None))
    k32.VirtualProtectEx(Game.handle, ctypes.c_void_p(addr), 4, old.value, ctypes.byref(old))
    return ok


def float_bits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


written_air = {}          # site -> bits escritos por nosotros


def air_read_mult():
    b = read_int(AIR_SITES[0])
    if b is None:
        return None
    return struct.unpack("<f", struct.pack("<I", b))[0] / 0.02


def air_apply(mult):
    walk = float_bits(0.02 * mult)
    sprint = float_bits(0.026 * mult)
    desired = [walk, sprint, walk, sprint]
    for i, site in enumerate(AIR_SITES):
        cur = read_int(site)
        if cur is None:
            return False
        expected = written_air.get(i, AIR_DEFAULTS[i])
        if cur != expected and cur != desired[i]:
            # el juego restauro el valor por su cuenta: re-aplicar (write prawnclean)
            pass
    for i, site in enumerate(AIR_SITES):
        if not write_int(site, desired[i]):
            return False
    for i in range(4):
        written_air[i] = desired[i]
    return True


def air_restore():
    for i, site in enumerate(AIR_SITES):
        cur = read_int(site)
        if cur is not None and cur != AIR_DEFAULTS[i]:
            write_int(site, AIR_DEFAULTS[i])
    written_air.clear()


written_nop = {}          # name -> bytes que pisamos (para restaurar)


def nop_apply(name, on):
    rva, orig = NOP_PATCHES[name]
    cur = Game.read_bytes(rva, len(orig))
    if cur is None:
        return False
    if on:
        if cur == orig:
            nops = b"\x90" * len(orig)
            if Game.write_bytes(rva, nops):
                written_nop[name] = orig
                return True
            return False
        if cur == b"\x90" * len(orig):
            return True            # ya estaba puesto
        return False
    if cur == b"\x90" * len(orig):
        if Game.write_bytes(rva, orig):
            written_nop.pop(name, None)
            return True
        return False
    return True                    # ya estaba original


def module_status():
    with stateLock:
        out = {}
        for name, mod in MODULES.items():
            on = state["on"].get(name, False)
            val = state["value"].get(name, mod["default"])
            if mod.get("code"):
                cur = air_read_mult()
            elif mod.get("nop"):
                cur = 1.0 if state["on"].get(name) else 0.0
            else:
                cur = Game.read_float(mod["rva"])
            out[name] = {"on": on, "v": round(val, 3),
                         "mem": round(cur, 3) if cur is not None else None}
        return out


def module_apply(name, on, value):
    with stateLock:
        mod = MODULES.get(name)
        if not mod:
            return "modulo desconocido"
        if not Game.alive():
            return "el juego no esta corriendo"
        if mod.get("nop"):
            if nop_apply(name, bool(on)):
                state["on"][name] = bool(on)
                return ""
            return "la memoria del juego no coincide"
        v = max(mod["min"], min(mod["max"], value))
        if mod.get("code"):
            if on:
                if air_apply(v):
                    state["on"][name] = True
                    state["value"][name] = v
                    return ""
                return "la memoria del juego cambio; restaurado"
            air_restore()
            state["on"][name] = False
            if state["value"].get(name, 0) >= mod["min"]:
                state["value"][name] = state["value"].get(name, mod["default"])
            return ""
        if on and not state["on"].get(name):
            # primer apply: escribir y recordar
            if Game.write_float(mod["rva"], v):
                state["on"][name] = True
                state["value"][name] = v
                return ""
            return "no se pudo escribir la memoria"
        if on and state["on"].get(name):
            if Game.write_float(mod["rva"], v):
                state["value"][name] = v
                return ""
            return "no se pudo escribir la memoria"
        if not on:
            if Game.write_float(mod["rva"], mod["default"]):
                state["on"][name] = False
                # recordar el ultimo valor: al re-prender, vuelve al que habia
                # puesto el usuario (no resetear al default del modulo)
                if state["value"].get(name, 0) >= mod["min"]:
                    state["value"][name] = state["value"].get(name, mod["default"])
                return ""
            return "no se pudo restaurar"
    return ""


def module_watch():
    """Si el juego muere, apagar; si el AIR esta ON, re-aplicar cada 50ms."""
    while True:
        time.sleep(0.05)
        with stateLock:
            if not Game.handle or not Game.alive():
                if Game.handle:
                    state["on"] = {k: False for k in state["on"]}
                    Game.handle = None
                continue
            if state["on"].get("air") and written_air:
                air_apply(state["value"].get("air", 1.0))


def panic_clean():
    """SS: apagar todo, restaurar valores, matar el script y el servidor."""
    with stateLock:
        air_restore()
        for name in list(NOP_PATCHES):
            try:
                nop_apply(name, False)
            except Exception:
                pass
        for name, mod in MODULES.items():
            if mod.get("code") or mod.get("nop"):
                continue
            if state["on"].get(name):
                try:
                    Game.write_float(mod["rva"], mod["default"])
                except Exception:
                    pass
        state["on"] = {}
        state["value"] = {}
    if Game.handle:
        k32.CloseHandle(Game.handle)
        Game.handle = None
    try:
        os.remove(STATE_FILE)
    except Exception:
        pass
    print("[panic] limpio: modulos apagados, memoria restaurada, cerrando")
    threading.Timer(0.6, lambda: os._exit(0)).start()


# ==== servidor web ====
PANEL = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>Onix remoto</title><style>
body{background:#12100d;color:#e8dcc8;font-family:system-ui;margin:0;padding:16px}
h1{font-size:20px;margin:4px 0 14px} .st{font-size:12px;opacity:.7;margin-bottom:14px}
.card{background:#1d1912;border:1px solid #3a2e1c;border-radius:12px;padding:14px;margin-bottom:12px}
.row{display:flex;align-items:center;justify-content:space-between}
.n{font-weight:700;font-size:16px}
.v{font-size:12px;opacity:.75}
button{border:1px solid #f0b040;background:#241e14;color:#f0b040;border-radius:10px;
padding:10px 18px;font-weight:700;font-size:14px;width:100%;margin-top:10px}
button.on{background:#f0b040;color:#12100d}
input[type=range]{width:100%;margin-top:10px}
</style></head><body>
<h1>ONIX <span style='font-size:11px;opacity:.6'>remoto</span></h1>
<div class=st id=st>conectando...</div>
<div class=card>
 <div class=row><span class=n>EMERGENCIA</span></div>
 <button style='background:#5c1d0e;border-color:#e06030;color:#ffb080'
  onclick="fetch('/api/panic?k='+K).then(function(){document.getElementById('st').textContent='limpiado - todo cerrado';})">
  PANIC: LIMPIAR TODO (SS)</button>
 <div class=v>Apaga todos los modulos, restaura la memoria y cierra el script.</div>
</div>
<div id=cards></div>
<script>
var K='KKEY';
var M=[
 {id:'reach',n:'REACH',min:3,max:7,step:0.1},
 {id:'velxz',n:'VELOCITY XZ',min:0,max:1,step:0.05},
 {id:'air',n:'AIR',min:1,max:3,step:0.1},
 {id:'itemdelay',n:'ITEM DELAY',min:0,max:1,step:1},
 {id:'nocam',n:'NO CAM RESET',min:0,max:1,step:1}
];
var vals={}, els={}, built=false;
function card(m,on,v,mem){
 var d=document.createElement('div');d.className='card';
 var row=document.createElement('div');row.className='row';
 var nm=document.createElement('span');nm.className='n';nm.textContent=m.n;
 var st=document.createElement('span');st.className='v';
 st.textContent='mem: '+(mem===null?'?':mem);
 row.appendChild(nm);row.appendChild(st);d.appendChild(row);
 var rng=document.createElement('input');rng.type='range';
 rng.min=m.min;rng.max=m.max;rng.step=m.step;rng.value=v;
 var val=document.createElement('span');val.className='v';
 val.textContent='valor: '+v;
 rng.oninput=function(){vals[m.id]=(+rng.value);val.textContent='valor: '+(+rng.value).toFixed(2)};
 d.appendChild(rng);d.appendChild(val);
 var b=document.createElement('button');b.textContent=on?'ON':'OFF';
 if(on)b.className='on';
 b.onclick=function(){send(m.id,on?0:1,vals[m.id])};
 d.appendChild(b);
 els[m.id]={btn:b,mem:st,val:val,rng:rng};
 return d;
}
function upd(s){
 for(var i=0;i<M.length;i++){
  var id=M[i].id,e=els[id];if(!e||!s[id])continue;
  var on=s[id].on;
  e.btn.textContent=on?'ON':'OFF';
  if(on)e.btn.className='on';else e.btn.className='';
  e.mem.textContent='mem: '+(s[id].mem===null?'?':s[id].mem);
  e.val.textContent='valor: '+(+vals[id]).toFixed(2);
 }
}
function render(s){
 var root=document.getElementById('cards');root.innerHTML='';els={};
 for(var i=0;i<M.length;i++){
  var id=M[i].id;
  if(vals[id]===undefined)vals[id]=s[id]?s[id].v:M[i].min;
  root.appendChild(card(M[i],s[id]&&s[id].on,vals[id],s[id]?s[id].mem:null));
 }
 built=true;
}
function send(id,on,v){
 fetch('/api/set?k='+K+'&m='+id+'&on='+on+'&v='+v)
  .then(function(r){return r.json()}).then(function(s){
   if(s.state){ if(s.state[id])vals[id]=s.state[id].v; upd(s.state); }
  });
}
function refresh(){
 fetch('/api/status?k='+K).then(function(r){return r.json()})
 .then(function(s){
  if(s.ok===false){document.getElementById('st').textContent='sin juego';return;}
  document.getElementById('st').textContent='conectado al juego (pid '+s.pid+')';
  if(!built)render(s.state);else upd(s.state);
 }).catch(function(){document.getElementById('st').textContent='sin conexion con la PC';});
}
refresh();setInterval(refresh,2000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {self.client_address[0]} "
                        + (fmt % args) + "\n")
        except Exception:
            pass

    def _send(self, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        key = (q.get("k") or [""])[0]
        if key != TOKEN:
            self._send("{}")
            return
        if u.path in ("/", "/panel"):
            self._send(PANEL.replace("KKEY", TOKEN),
                       "text/html; charset=utf-8")
        elif u.path == "/api/status":
            alive = Game.alive()
            self._send(json.dumps({
                "ok": True, "pid": Game.pid if alive else 0,
                "state": module_status() if alive else {},
            }))
        elif u.path == "/api/panic":
            self._send('{"ok":true,"panic":true}')
            threading.Thread(target=panic_clean, daemon=True).start()
        elif u.path == "/api/set":
            m = (q.get("m") or [""])[0]
            on = (q.get("on") or ["0"])[0] == "1"
            try:
                v = float(unquote((q.get("v") or ["0"])[0]))
            except ValueError:
                v = 0.0
            err = module_apply(m, on, v)
            self._send(json.dumps({
                "ok": err == "", "error": err,
                "state": module_status() if Game.alive() else {},
            }))
        else:
            self._send("{}")


TOKEN = "".join(random.choice("0123456789abcdef") for _ in range(10))


def lan_ip():
    s = socket = None
    import socket as _s
    s = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 53))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    if not Game.attach():
        print("[!] No encontre Minecraft 1.21.114 abierto. Abre el juego y vuelve a correr esto.")
        sys.exit(1)
    port = random.randint(*PORT_RANGE)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    url = f"http://{lan_ip()}:{port}/?k={TOKEN}"
    threading.Thread(target=module_watch, daemon=True).start()
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({"url": url}, f)
    except Exception:
        pass
    print("=" * 48)
    print("  ONIX REMOTO — Minecraft Bedrock 1.21.114")
    print(f"  PID del juego: {Game.pid}")
    print(f"  Desde el celu abre:")
    print(f"  {url}")
    print("=" * 48)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
