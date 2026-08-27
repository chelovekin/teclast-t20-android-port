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

    # MTK LK fastboot keeps the HW watchdog enabled. cmd_boot cancels LK's
    # periodic 5-second kicker, does one final restart, then jumps to Linux.
    # Keep that inherited watchdog alive while MT6797 loads its nine PCM blobs.
    include_pat = r'(#ifdef CONFIG_MTK_WD_KICKER\n#include <mach/wd_api\.h>\n#endif)'
    include_repl = r'''\1

#if defined(CONFIG_ARCH_MT6797) && defined(CONFIG_MTK_WD_KICKER)
extern void mtk_wdt_restart(enum wd_restart_type type);
static inline void t20_run50_wdt_kick(const char *tag, int idx)
{
	mtk_wdt_restart(WD_TYPE_NOLOCK);
	aee_sram_printk("T20RUN50 %s i=%d\n", tag, idx);
}
#else
static inline void t20_run50_wdt_kick(const char *tag, int idx)
{
}
#endif'''
    s = replace_once(s, include_pat, include_repl, "wdt helper insertion")

    # Kick immediately after entering the loader, before long firmware I/O.
    entry_pat = (
        r'(?P<indent>^[ \t]*)if \(dyna_load_pcm_done\)\n'
        r'(?P=indent)[ \t]+return err;\n'
    )
    entry_repl = (
        r'\g<indent>if (dyna_load_pcm_done)\n'
        r'\g<indent>\treturn err;\n\n'
        r'\g<indent>t20_run50_wdt_kick("A loader_enter", -1);\n'
    )
    s = replace_once(s, entry_pat, entry_repl, "loader entry")

    # Refresh before each request_firmware() attempt.
    req_pat = (
        r'(?P<indent>^[ \t]*)do \{\n'
        r'(?P=indent)[ \t]+j\+\+;\n'
        r'(?P=indent)[ \t]+pr_debug\("try to request_firmware\(\) %s - %d\\n", dyna_load_pcm_path\[i\], j\);'
    )
    req_repl = (
        r'\g<indent>do {\n'
        r'\g<indent>\tt20_run50_wdt_kick("B before_request", i);\n'
        r'\g<indent>\tj++;\n'
        r'\g<indent>\tpr_debug("try to request_firmware() %s - %d\\n", dyna_load_pcm_path[i], j);'
    )
    s = replace_once(s, req_pat, req_repl, "request_firmware loop")

    # The persistent trace used to end on fw #8. Kick directly around that
    # existing log and around the ready/count transition.
    log_pat = (
        r'(?P<indent>^[ \t]*)spm_crit2\(" spm fw version\(%d\) = %s\\n", i, \(char \*\)pdesc->version\);\n\n'
        r'(?P=indent)dyna_load_pcm\[i\]\.ready = 1;\n'
        r'(?P=indent)spm_fw_count\+\+;'
    )
    log_repl = (
        r'\g<indent>t20_run50_wdt_kick("C before_fw_log", i);\n'
        r'\g<indent>spm_crit2(" spm fw version(%d) = %s\\n", i, (char *)pdesc->version);\n'
        r'\g<indent>t20_run50_wdt_kick("D after_fw_log", i);\n\n'
        r'\g<indent>dyna_load_pcm[i].ready = 1;\n'
        r'\g<indent>spm_fw_count++;\n'
        r'\g<indent>t20_run50_wdt_kick("E counted", i);'
    )
    s = replace_once(s, log_pat, log_repl, "firmware log/count block")

    # Keep normal VcoreFS/DVFS. Only bracket it with watchdog refreshes.
    late_pat = (
        r'(?P<indent>^[ \t]*)if \(spm_fw_count == check_spm_fw_count\) \{\n'
        r'(?P=indent)[ \t]+vcorefs_late_init_dvfs\(\);\n'
        r'(?P=indent)[ \t]+dyna_load_pcm_done = 1;\n'
        r'(?P=indent)\}'
    )
    late_repl = (
        r'\g<indent>t20_run50_wdt_kick("F loop_done", spm_fw_count);\n'
        r'\g<indent>if (spm_fw_count == check_spm_fw_count) {\n'
        r'\g<indent>\tt20_run50_wdt_kick("G before_vcorefs", spm_fw_count);\n'
        r'\g<indent>\tvcorefs_late_init_dvfs();\n'
        r'\g<indent>\tt20_run50_wdt_kick("H after_vcorefs", spm_fw_count);\n'
        r'\g<indent>\tdyna_load_pcm_done = 1;\n'
        r'\g<indent>\tt20_run50_wdt_kick("I done", spm_fw_count);\n'
        r'\g<indent>}'
    )
    s = replace_once(s, late_pat, late_repl, "normal late VcoreFS block")

    p.write_text(s)
    print("run50 MT6797 fastboot watchdog handoff kicks + AEE markers injected; normal VcoreFS retained", flush=True)


if __name__ == "__main__":
    main()
