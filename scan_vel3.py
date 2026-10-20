"""Busca patrones con multiplicador (mulss rip-relativo) seguido de stores,
y los 5 candidatos de Timer con su contexto."""
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


def disas_around(data, off, back=48, fwd=110):
    start = max(0, off - back)
    out = []
    for ins in md.disasm(data[start:off + fwd], start):
        tag = ">>>" if start <= off < ins.address + ins.size else "   "
        out.append(f"{ins.address:012x} {tag} {ins.mnemonic} {ins.op_str}")
    return "\n".join(out)


def main():
    with open(EXE, "rb") as f:
        data = f.read()

    pats = {
        "timer exacto": "F3 0F 59 0D ? ? ? ? F3 0F 58 4B 10",
        "vel: mul->store rax": "F3 0F 59 05 ? ? ? ? F3 0F 11 40 18",
        "vel: mul->store rax (F2)": "F3 0F 59 05 ? ? ? ? F2 0F 11 40 18",
        "vel: read rdx + mul": "F3 0F 10 02 F3 0F 59 05",
        "vel: read rdx + mul (F2)": "F2 0F 10 02 F3 0F 59 05",
    }
    for name, p in pats.items():
        hits = find_all(data, p, max_hits=60)
        print(f"[{name}]: {len(hits)} -> {[hex(h) for h in hits[:8]]}")

    # timer: los 5 candidatos con contexto
    print("\n=== TIMER: contexto de cada match ===")
    for h in find_all(data, "F3 0F 58 4B 10", max_hits=10):
        print(f"\n--- @ 0x{h:x} ---")
        print(disas_around(data, h, back=24, fwd=40))


if __name__ == "__main__":
    main()
