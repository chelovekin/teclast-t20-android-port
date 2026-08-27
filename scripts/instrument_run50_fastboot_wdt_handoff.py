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

    # MTK LK fastboot keeps the hardware watchdog enabled. Its cmd_boot path
    # cancels LK's 5-second periodic kicker, performs one final mtk_wdt_restart(),
    # then jumps to Linux. Our fastboot-booted kernel spends ~8.5 s loading the
    # nine MT6797 PCM firmware blobs, so keep the inherited hardware watchdog
    # alive until the normal kernel watchdog/kicker has had time to take over.
    include_pat = r'(#ifdef CONFIG_MTK_WD_KICKER\n#include <mach/wd_api\.h>\n#endif)'
    include_repl = (
        r'\1\n\n'
        r'#if defined(CONFIG_ARCH_MT6797) && defined(CONFIG_MTK_WD_KICKER)\n'
        r'extern void mtk_wdt_restart(enum wd_restart_type type);\n'
        r'#define T20_RUN50_WDT_KICK(tag, idx) do { \\\n'
        r'\tmtk_wdt_restart(WD_TYPE_NOLOCK); \\\n'
        r'\taee_sram_printk("T20RUN50 " tag " i=%d\\n", (idx)); \\\n'
        r'} while (0)\n'
        r'#else\n'
        r'#define T20_RUN50_WDT_KICK(tag, idx) do { } while (0)\n'
        r'#endif'
    )
    s = replace_once(s, include_pat, include_repl, "wdt helper insertion")

    # Kick immediately after entering the loader, before any long firmware I/O.
    entry_pat = (
        r'(?P<indent>^[ \t]*)if \(dyna_load_pcm_done\)\n'
        r'(?P=indent)[ \t]+return err;\n'
    )
    entry_repl = (
        r'\g<indent>if (dyna_load_pcm_done)\n'
        r'\g<indent>\treturn err;\n\n'
        r'\g<indent>T20_RUN50_WDT_KICK("A loader_enter", -1);\n'
    )
    s = replace_once(s, entry_pat, entry_repl, "loader entry")

    # Refresh the inherited LK watchdog before each request_firmware() attempt.
    req_pat = (
        r'(?P<indent>^[ \t]*)do \{\n'
        r'(?P=indent)[ \t]+j\+\+;\n'
        r'(?P=indent)[ \t]+pr_debug\("try to request_firmware\(\) %s - %d\\n", dyna_load_pcm_path\[i\], j\);'
    )
    req_repl = (
        r'\g<indent>do {\n'
        r'\g<indent>\tT20_RUN50_WDT_KICK("B before_request", i);\n'
        r'\g<indent>\tj++;\n'
        r'\g<indent>\tpr_debug("try to request_firmware() %s - %d\\n", dyna_load_pcm_path[i], j);'
    )
    s = replace_once(s, req_pat, req_repl, "request_firmware loop")

    # The old persistent trace always ended on firmware #8. Kick immediately
    # before that existing spm_crit2() and record a persistent marker after it.
    log_pat = (
        r'(?P<indent>^[ \t]*)spm_crit2\(" spm fw version\(%d\) = %s\\n", i, \(char \*\)pdesc->version\);\n\n'
        r'(?P=indent)dyna_load_pcm\[i\]\.ready = 1;\n'
        r'(?P=indent)spm_fw_count\+\+;'
    )
    log_repl = (
        r'\g<indent>T20_RUN50_WDT_KICK("C before_fw_log", i);\n'
        r'\g<indent>spm_crit2(" spm fw version(%d) = %s\\n", i, (char *)pdesc->version);\n'
        r'\g<indent>T20_RUN50_WDT_KICK("D after_fw_log", i);\n\n'
        r'\g<indent>dyna_load_pcm[i].ready = 1;\n'
        r'\g<indent>spm_fw_count++;\n'
        r'\g<indent>T20_RUN50_WDT_KICK("E counted", i);'
    )
    s = replace_once(s, log_pat, log_repl, "firmware log/count block")

    # Keep the normal VcoreFS path. Only bracket it with watchdog refreshes and
    # persistent markers so run50 remains functionally equivalent to the source
    # except for surviving the fastboot watchdog handoff window.
    late_pat = (
        r'(?P<indent>^[ \t]*)if \(spm_fw_count == check_spm_fw_count\) \{\n'
        r'(?P=indent)[ \t]+vcorefs_late_init_dvfs\(\);\n'
        r'(?P=indent)[ \t]+dyna_load_pcm_done = 1;\n'
        r'(?P=indent)\}'
    )
    late_repl = (
        r'\g<indent>T20_RUN50_WDT_KICK("F loop_done", spm_fw_count);\n'
        r'\g<indent>if (spm_fw_count == check_spm_fw_count) {\n'
        r'\g<indent>\tT20_RUN50_WDT_KICK("G before_vcorefs", spm_fw_count);\n'
        r'\g<indent>\tvcorefs_late_init_dvfs();\n'
        r'\g<indent>\tT20_RUN50_WDT_KICK("H after_vcorefs", spm_fw_count);\n'
        r'\g<indent>\tdyna_load_pcm_done = 1;\n'
        r'\g<indent>\tT20_RUN50_WDT_KICK("I done", spm_fw_count);\n'
        r'\g<indent>}'
    )
    s = replace_once(s, late_pat, late_repl, "normal late VcoreFS block")

    p.write_text(s)
    print("run50 MT6797 fastboot watchdog handoff kicks + AEE markers injected; normal VcoreFS retained", flush=True)


if __name__ == "__main__":
    main()
