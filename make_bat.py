r"""make_bat.py — genera la version de un solo archivo (dist\SSTOOL.bat).

El motor (core.ps1) viaja en base64 en variables CORE0..CORE9 (cada una
corta, sin expansiones %VAR% que rompan el limite de linea de cmd). El menu
ejecuta el motor en memoria (Invoke-Expression leyendo el entorno) y el
servidor remoto se volca una vez a %LOCALAPPDATA%\SSTool\core.ps1 para correr
como archivo normal.
Uso:  py make_bat.py
"""
import base64
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC_BAT = HERE / "sstool.bat"
SRC_PS1 = HERE / "core.ps1"
OUT = HERE / "dist" / "SSTOOL.bat"

ANCHOR = "rem @@CORE@@"
DUMP = "rem @@DUMP@@"
CHUNK = 3400
MAX_CHUNKS = 10

CONCAT = (
    "$c=$env:CORE0;"
    + "".join(f"if($env:CORE{i}){{$c+=$env:CORE{i}}};"
              for i in range(1, MAX_CHUNKS))
)
RUNNER_BODY = CONCAT + "$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($c));Invoke-Expression $s"
RUNNER = f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{RUNNER_BODY}"'
DUMP_LINE = (
    'powershell -NoProfile -ExecutionPolicy Bypass -Command "'
    + CONCAT
    + "[IO.File]::WriteAllText('%COREDIR%\\core.ps1',"
      "[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($c)))\""
)


def main():
    raw = SRC_PS1.read_text(encoding="utf-8")
    b64 = base64.b64encode(raw.encode("utf-8")).decode("ascii")

    if len(b64) > CHUNK * MAX_CHUNKS:
        raise SystemExit(f"el motor no cabe: {len(b64)} > {CHUNK * MAX_CHUNKS}")

    lines = []
    for i in range(0, len(b64), CHUNK):
        lines.append(f'set "CORE{i // CHUNK}={b64[i:i + CHUNK]}"')
    inject = "\r\n".join(lines)

    out = SRC_BAT.read_text(encoding="utf-8")
    out = out.replace(DUMP, DUMP_LINE)
    out = out.replace(
        'start "" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core.ps1" serve %RTOK% %RPORT%',
        f'start "" /min {RUNNER}')
    out = out.replace(ANCHOR, inject)
    out = out.replace(
        'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core.ps1"',
        RUNNER)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out, encoding="utf-8", newline="\r\n")
    print(f"[+] {OUT}  ({OUT.stat().st_size} B)")
    print(f"    motor: {len(raw)} chars -> b64 {len(b64)} en {len(lines)} variables")


if __name__ == "__main__":
    main()
