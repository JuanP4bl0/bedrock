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
MODULES = {
    "reach": {"rva": 145749080, "min": 3.0, "max": 7.0, "default": 3.0},
    "velxz": {"rva": 0x2637850, "min": 0.0, "max": 1.0, "default": 1.0},
    "air": {"rva": 0x28C5684, "min": 0.0, "max": 4.0, "default": 1.0},
}

state = {"on": {}, "value": {}}
stateLock = threading.Lock()


def module_status():
    with stateLock:
        out = {}
        for name, mod in MODULES.items():
            on = state["on"].get(name, False)
            val = state["value"].get(name, mod["default"])
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
        v = max(mod["min"], min(mod["max"], value))
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
                state["value"][name] = mod["default"]
                return ""
            return "no se pudo restaurar"
    return ""


def module_watch():
    """Si el juego muere, marcar todo apagado."""
    while True:
        time.sleep(2)
        if Game.handle and not Game.alive():
            with stateLock:
                state["on"] = {k: False for k in state["on"]}
                Game.handle = None


def panic_clean():
    """SS: apagar todo, restaurar valores, matar el script y el servidor."""
    with stateLock:
        for name, mod in MODULES.items():
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
  onclick="fetch('?k='+K+'&api=panic').then(function(){document.getElementById('st').textContent='limpiado - todo cerrado';})">
  PANIC: LIMPIAR TODO (SS)</button>
 <div class=v>Apaga todos los modulos, restaura la memoria y cierra el script.</div>
</div>
<div id=cards></div>
<script>
var M=[
 {id:'reach',n:'REACH',min:3,max:7,step:0.1},
 {id:'velxz',n:'VELOCITY XZ',min:0,max:1,step:0.05},
 {id:'air',n:'AIR',min:0,max:4,step:0.1}
];
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
 rng.oninput=function(){val.textContent='valor: '+(+rng.value).toFixed(2)};
 d.appendChild(rng);d.appendChild(val);
 var b=document.createElement('button');b.textContent=on?'ON':'OFF';
 if(on)b.className='on';
 b.onclick=function(){send(m.id,on?0:1,+rng.value)};
 d.appendChild(b);
 return d;
}
function render(s){
 var root=document.getElementById('cards');root.innerHTML='';
 for(var i=0;i<M.length;i++){
  var id=M[i][0]||M[i].id;
  root.appendChild(card(M[i],s[id]&&s[id].on,s[id]?s[id].v:M[i].default||0,s[id]?s[id].mem:null));
 }
}
function send(id,on,v){
 fetch('?k='+K+'&api=set&m='+id+'&on='+on+'&v='+v)
  .then(function(r){return r.json()}).then(function(s){ if(s.state) render(s.state); });
}
function refresh(){
 fetch('?k='+K+'&api=status').then(function(r){return r.json()})
 .then(function(s){
  if(s.ok===false){document.getElementById('st').textContent='sin juego';return;}
  document.getElementById('st').textContent='conectado al juego (pid '+s.pid+')';
  render(s.state);
 }).catch(function(){document.getElementById('st').textContent='sin conexion con la PC';});
}
refresh();setInterval(refresh,2000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
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
