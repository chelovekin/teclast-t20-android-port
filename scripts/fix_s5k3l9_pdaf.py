#!/usr/bin/env python3
import re
import sys
from pathlib import Path


if len(sys.argv) != 2:
    raise SystemExit("usage: fix_s5k3l9_pdaf.py <s5k3l9otp.c>")

p = Path(sys.argv[1])
s = p.read_text()
call = "S5K3L9_Read_PDAF_Otp(ui4_length, pinputdata);"

if call not in s:
    pattern = re.compile(
        r"^(?P<line_indent>[ \t]*)else[ \t]+if[ \t]*\([ \t]*ui4_length[ \t]*==[ \t]*"
        r"S5K3L9_LSC_OTP_SIZE[ \t]*\)[ \t]*\r?\n"
        r"(?P<brace_indent>[ \t]*)\{",
        re.MULTILINE,
    )

    def repl(m: re.Match) -> str:
        li = m.group("line_indent")
        bi = m.group("brace_indent")
        return (
            f"{li}else if(ui4_length == S5K3L9_PDAF_OTP_SIZE)\n"
            f"{bi}{{\n"
            f"{bi}\t{call}\n"
            f"{bi}}}\n"
            f"{li}else if(ui4_length == S5K3L9_LSC_OTP_SIZE)\n"
            f"{bi}{{"
        )

    s, count = pattern.subn(repl, s, count=1)
    if count != 1:
        raise RuntimeError("could not locate S5K3L9 LSC branch for PDAF integration")

if s.count(call) != 1:
    raise RuntimeError(f"unexpected S5K3L9 PDAF call count: {s.count(call)}")

p.write_text(s)
print("S5K3L9 PDAF OTP read path wired into CAM_CAL dispatcher", flush=True)
