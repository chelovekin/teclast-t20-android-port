#!/usr/bin/env python3
from pathlib import Path
import argparse
import re


def replace_once(text: str, pattern: str, repl: str, label: str) -> str:
    out, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    args = ap.parse_args()

    p = Path(args.kernel) / "drivers/misc/mediatek/base/power/spm_v2/mt_spm.c"
    s = p.read_text()

    # The previous run47 markers lived in vcorefs_late_init_dvfs(), but the
    # persistent AEE SRAM log never reached them. Put the markers directly in
    # the MT6797 dynamic PCM loader, immediately after the last known-good
    # persistent message. Use aee_sram_printk() directly so the marker itself
    # cannot get stuck in the normal printk path.
    count_pat = (
        r'(?P<indent>^[ \t]*)dyna_load_pcm\[i\]\.ready = 1;\n'
        r'(?P=indent)spm_fw_count\+\+;'
    )
    count_repl = (
        r'\g<indent>aee_sram_printk("T20RUN49 A after_fw_log i=%d\\n", i);\n'
        r'\g<indent>dyna_load_pcm[i].ready = 1;\n'
        r'\g<indent>aee_sram_printk("T20RUN49 B ready_set i=%d\\n", i);\n'
        r'\g<indent>spm_fw_count++;\n'
        r'\g<indent>aee_sram_printk("T20RUN49 C count=%d i=%d\\n", spm_fw_count, i);'
    )
    s = replace_once(s, count_pat, count_repl, "PCM ready/count block")

    # Bring-up workaround: the crash is after firmware #8 and before the first
    # run47 marker in vcorefs_late_init_dvfs(). For run49, deliberately do not
    # enter the late VcoreFS/DVFS transition. Mark the exact branch in AEE SRAM
    # and declare the PCM firmware load complete. This is a diagnostic/bring-up
    # kernel, not the final power-management implementation.
    late_pat = (
        r'(?P<indent>^[ \t]*)if \(spm_fw_count == check_spm_fw_count\) \{\n'
        r'(?P=indent)[ \t]+vcorefs_late_init_dvfs\(\);\n'
        r'(?P=indent)[ \t]+dyna_load_pcm_done = 1;\n'
        r'(?P=indent)\}'
    )
    late_repl = (
        r'\g<indent>aee_sram_printk("T20RUN49 D loop_done count=%d check=%d\\n", '
        r'spm_fw_count, check_spm_fw_count);\n'
        r'\g<indent>if (spm_fw_count == check_spm_fw_count) {\n'
        r'\g<indent>\taee_sram_printk("T20RUN49 E count_match bypass_vcorefs_late_init\\n");\n'
        r'\g<indent>\tdyna_load_pcm_done = 1;\n'
        r'\g<indent>\taee_sram_printk("T20RUN49 F dyna_load_pcm_done=1\\n");\n'
        r'\g<indent>}'
    )
    s = replace_once(s, late_pat, late_repl, "late VcoreFS block")

    p.write_text(s)
    print("run49 persistent SPM markers A..F injected; late VcoreFS transition bypassed", flush=True)


if __name__ == "__main__":
    main()
