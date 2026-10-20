"""Escanea el binario de Minecraft Bedrock 1.21.114 y verifica las firmas
que el proyecto Nitr0 necesita (Velocity / Timer / Hitbox / FakeLag / Reach)."""
import mmap
import re
import struct
import sys

import capstone

EXE = (r"C:\Program Files\WindowsApps\Microsoft.MinecraftUWP_1.21.11401.0_x64__"
       r"8wekyb3d8bbwe\Minecraft.Windows.exe")

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)


def hex_pat(s: str) -> bytes:
    out, i = bytearray(), 0
    parts = s.split()
    for p in parts:
        if p == "?":
            out.append(0x00)
        else:
            out.append(int(p, 16))
    return bytes(out)


def masked_find(data: bytes, pattern: str, max_hits: int = 50):
    """Busca un patron con wildcards '?' (0x00 + no comparar)."""
    pat = []
    for p in pattern.split():
        if p == "?":
            pat.append(None)
        else:
            pat.append(int(p, 16))

    out, start = [], 0
    n = len(pat)
    while len(out) < max_hits:
        # primer byte fijo conocido para acelerar el regex
        first = next((i, pat[i]) for i in range(n) if pat[i] is not None)
        fixed_first = bytes([pat[i] if pat[i] is not None else 0 for i in range(n)])
        regex = bytearray()
        for b in pat:
            regex.append(b if b is not None else 0)
        regex_mask = bytearray()
        for b in pat:
            regex_mask.append(0xFF if b is not None else 0x00)
        # regex binario: byte AND mask == fixed
        rx = re.compile(
            b"".join(
                re.escape(bytes([f])) if m == 0xFF
                else b"(?s:.)" if False else b"(?s:.)"
                for f, m in []
            )
        )
        break
    return out


def find_with_mask(data: bytes, pattern: str, max_hits: int = 50):
    pat = []
    for p in pattern.split():
        pat.append(None if p == "?" else int(p, 16))
    n = len(pat)
    out = []
    # construir regex: para cada posicion, byte fijo o cualquier byte
    rx = b""
    for b in pat:
        rx += re.escape(bytes([b])) if b is not None else b"(?s:.)"
    rx = re.compile(rx, re.DOTALL)
    for m in rx.finditer(data):
        out.append(m.start())
        if len(out) >= max_hits:
            break
    return out


def disas(data: bytes, off: int, before: int = 48, after: int = 96, count: int = 14):
    start = max(0, off - before)
    chunk = data[start:off + after]
    lines = []
    for ins in md.disasm(chunk, start):
        mark = " >>>" if (start <= off < ins.address + ins.size) and not (
            ins.address > off) else (">>" if ins.address <= off < ins.address + ins.size else "   ")
        lines.append(f"{ins.address:012x} {mark} {ins.mnemonic} {ins.op_str}")
        if len(lines) >= count * 2:
            break
    return "\n".join(lines)


def main():
    with open(EXE, "rb") as f:
        data = f.read()
    print(f"binario: {len(data)/1048576:.1f} MB")

    # ---- VELOCITY (patron conocido del fix embebido) ----
    vel = "F3 0F 10 40 ? 48 8B 5C 24 ? 48 83 C4"
    hits = find_with_mask(data, vel)
    print(f"\n[Velocity] patron {vel}")
    print(f"  matches: {len(hits)} -> offsets: {[hex(h) for h in hits]}")

    # ---- TIMER: addss xmm1,[rbx+10] ----
    timer = "F3 0F 58 4B 10"
    hits_t = find_with_mask(data, timer, max_hits=200)
    print(f"\n[Timer] patron {timer}: {len(hits_t)} matches")

    # ---- HITBOX: movss [rax+18],xmm0 ----
    hb = "F3 0F 11 40 18"
    hits_h = find_with_mask(data, hb, max_hits=500)
    print(f"[Hitbox] patron {hb}: {len(hits_h)} matches")

    # ---- HITBOX doble: width + height consecutivos ----
    hb2 = "F3 0F 11 40 18 F3 0F 11 40 1C"
    hits_h2 = find_with_mask(data, hb2, max_hits=50)
    print(f"[Hitbox x2] patron {hb2}: {len(hits_h2)} -> {[hex(h) for h in hits_h2]}")

    # ---- FAKELAG (hardcodeado en el source) ----
    fl = "48 83 EC ? 48 0F BE ? ? 48 83 C0 ? 74 27"
    hits_f = find_with_mask(data, fl)
    print(f"[FakeLag] patron {fl}: {len(hits_f)} -> {[hex(h) for h in hits_f]}")

    # ---- contexto del primer match de velocity ----
    if hits:
        off = hits[0]
        print(f"\n=== VELOCITY @ file 0x{off:x} (primer match) ===")
        print(disas(data, off))

    if hits_h2:
        off = hits_h2[0]
        print(f"\n=== HITBOX x2 @ file 0x{off:x} ===")
        print(disas(data, off))


if __name__ == "__main__":
    main()
