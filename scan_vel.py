"""Busca la funcion de velocidad (y candidatos Timer/Hitbox) en 1.21.114."""
import re

import capstone

EXE = (r"C:\Program Files\WindowsApps\Microsoft.MinecraftUWP_1.21.11401.0_x64__"
       r"8wekyb3d8bbwe\Minecraft.Windows.exe")
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)


def find_all(data, pattern, max_hits=100):
    pat = [None if p == "?" else int(p, 16) for p in pattern.split()]
    rx = re.compile(b"".join(re.escape(bytes([b])) if b is not None else b"(?s:.)"
                             for b in pat), re.DOTALL)
    return [m.start() for m in rx.finditer(data)][:max_hits]


def disas_around(data, off, back=64, fwd=120):
    start = max(0, off - back)
    out = []
    for ins in md.disasm(data[start:off + fwd], start):
        tag = ">>>" if start <= off < ins.address + ins.size else "   "
        out.append(f"{ins.address:012x} {tag} {ins.mnemonic} {ins.op_str}")
    return "\n".join(out)


def main():
    with open(EXE, "rb") as f:
        data = f.read()

    # la funcion de velocidad escribe 3 dobles a [rax+18/1C/20] con mulss
    # intercalados: buscar la secuencia completa con wildcards
    pats = {
        "vel completa": "F2 0F 10 02 F3 0F 59 05 ? ? ? ? F2 0F 11 40 18 F2 0F 10 42 04",
        "vel sin rdx": "F3 0F 59 05 ? ? ? ? F2 0F 11 40 18",
        "movsd 18": "F2 0F 11 40 18",
        "movsd 18/1C": "F2 0F 11 40 18 F2 0F 11 40 1C",
    }
    for name, p in pats.items():
        hits = find_all(data, p, max_hits=30)
        print(f"[{name}] {p}: {len(hits)} -> {[hex(h) for h in hits[:12]]}")

    # contexto del primer movsd 18/1C
    hits = find_all(data, pats["movsd 18/1C"], max_hits=10)
    for h in hits[:2]:
        print(f"\n=== contexto movsd 18/1C @ 0x{h:x} ===")
        print(disas_around(data, h))


if __name__ == "__main__":
    main()
