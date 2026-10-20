"""Encuentra la funcion de velocidad en 1.21.114: secuencia de 3 stores
(X/Y/Z) con multiplicador rip-relativo cerca, orden variable."""
import re

import capstone

EXE = (r"C:\Program Files\WindowsApps\Microsoft.MinecraftUWP_1.21.11401.0_x64__"
       r"8wekyb3d8bbwe\Minecraft.Windows.exe")
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)


def find_all(data, pattern, max_hits=200):
    pat = [None if p == "?" else int(p, 16) for p in pattern.split()]
    rx = re.compile(b"".join(re.escape(bytes([b])) if b is not None else b"(?s:.)"
                             for b in pat), re.DOTALL)
    return [m.start() for m in rx.finditer(data)][:max_hits]


def disas_around(data, off, back=80, fwd=160):
    start = max(0, off - back)
    out = []
    for ins in md.disasm(data[start:off + fwd], start):
        tag = ">>>" if start <= off < ins.address + ins.size else "   "
        out.append(f"{ins.address:012x} {tag} {ins.mnemonic} {ins.op_str}")
    return "\n".join(out)


def main():
    with open(EXE, "rb") as f:
        data = f.read()

    # semillas: un store a +18/+1C/+20 con prefijo F2 o F3
    seeds = find_all(data, "0F 11 40 18", max_hits=400)
    seeds += find_all(data, "0F 11 40 1C", max_hits=400)
    seeds += find_all(data, "0F 11 40 20", max_hits=400)

    scored = []
    for s in set(seeds):
        window = data[s - 48:s + 64]
        score = 0
        # stores de componentes vecinos
        for comp in (b"\x0f\x11\x40\x1c", b"\x0f\x11\x40\x20", b"\x0f\x11\x40\x18"):
            score += window.count(comp) * 3
        # multiplicador rip-relativo (mulss xmm, [rip+x])
        score += window.count(b"\xf3\x0f\x59\x05") * 5
        score += window.count(b"\xf2\x0f\x59\x05") * 5
        # lecturas desde rdx (parametro)
        score += window.count(b"\x0f\x10\x42") * 2
        if score >= 12:
            scored.append((score, s))
    scored.sort(reverse=True)
    print(f"candidatos con score: {len(scored)}")
    for score, off in scored[:6]:
        print(f"\n===== score {score} @ file 0x{off:x} =====")
        print(disas_around(data, off))


if __name__ == "__main__":
    main()
