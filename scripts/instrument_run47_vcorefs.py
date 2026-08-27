#!/usr/bin/env python3
from pathlib import Path
import argparse


def function_span(text: str, signature: str):
    start = text.find(signature)
    if start < 0:
        raise SystemExit(f"function not found: {signature}")
    brace = text.find("{", start + len(signature))
    if brace < 0:
        raise SystemExit(f"opening brace not found: {signature}")
    depth = 0
    for pos in range(brace, len(text)):
        ch = text[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return start, pos + 1
    raise SystemExit(f"closing brace not found: {signature}")


def replace_one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_function(text: str, signature: str, patcher):
    start, end = function_span(text, signature)
    chunk = text[start:end]
    chunk = patcher(chunk)
    return text[:start] + chunk + text[end:]


def patch_feature(chunk: str) -> str:
    chunk = replace_one(
        chunk,
        "\tstruct governor_profile *gvrctrl = &governor_ctrl;\n",
        "\tstruct governor_profile *gvrctrl = &governor_ctrl;\n"
        "\tint dram_fh_ok;\n\n"
        "\tpr_emerg(\"T20RUN47 A enter is_vcorefs_feature_enable\\n\");\n"
        "\tpr_emerg(\"T20RUN47 B before dram_can_support_fh\\n\");\n",
        "feature prologue",
    )
    chunk = replace_one(
        chunk,
        "\tif (!dram_can_support_fh()) {",
        "\tdram_fh_ok = dram_can_support_fh();\n"
        "\tpr_emerg(\"T20RUN47 C after dram_can_support_fh=%d\\n\", dram_fh_ok);\n"
        "\tif (!dram_fh_ok) {",
        "dram_can_support_fh",
    )
    chunk = replace_one(
        chunk,
        "\treturn gvrctrl->plat_feature_en;",
        "\tpr_emerg(\"T20RUN47 D leave is_vcorefs_feature_enable=%d\\n\", gvrctrl->plat_feature_en);\n\n"
        "\treturn gvrctrl->plat_feature_en;",
        "feature return",
    )
    return chunk


def patch_late(chunk: str) -> str:
    chunk = replace_one(
        chunk,
        "\tint flag;\n",
        "\tint flag;\n"
        "\tint feature_en;\n\n"
        "\tpr_emerg(\"T20RUN47 E enter vcorefs_late_init_dvfs\\n\");\n",
        "late prologue",
    )

    first = "\tif (is_vcorefs_feature_enable()) {"
    if chunk.count(first) != 2:
        raise SystemExit(f"late feature checks: expected two matches, found {chunk.count(first)}")
    chunk = chunk.replace(
        first,
        "\tfeature_en = is_vcorefs_feature_enable();\n"
        "\tpr_emerg(\"T20RUN47 F feature1=%d\\n\", feature_en);\n"
        "\tif (feature_en) {",
        1,
    )
    chunk = replace_one(
        chunk,
        "\t\tflag = vcorefs_check_feature_enable();",
        "\t\tpr_emerg(\"T20RUN47 G before vcorefs_check_feature_enable\\n\");\n"
        "\t\tflag = vcorefs_check_feature_enable();\n"
        "\t\tpr_emerg(\"T20RUN47 H after vcorefs_check_feature_enable flag=0x%x\\n\", flag);",
        "feature flag",
    )
    chunk = replace_one(
        chunk,
        "\t\tspm_go_to_vcore_dvfs(flag, 0);",
        "\t\tpr_emerg(\"T20RUN47 I before spm_go_to_vcore_dvfs\\n\");\n"
        "\t\tspm_go_to_vcore_dvfs(flag, 0);\n"
        "\t\tpr_emerg(\"T20RUN47 J after spm_go_to_vcore_dvfs\\n\");",
        "spm_go_to_vcore_dvfs",
    )
    chunk = replace_one(
        chunk,
        "\tmutex_lock(&governor_mutex);",
        "\tpr_emerg(\"T20RUN47 K before governor mutex\\n\");\n"
        "\tmutex_lock(&governor_mutex);",
        "governor mutex lock",
    )
    chunk = replace_one(
        chunk,
        "\tgvrctrl->late_init_opp = set_init_opp_index();",
        "\tpr_emerg(\"T20RUN47 L before set_init_opp_index\\n\");\n"
        "\tgvrctrl->late_init_opp = set_init_opp_index();\n"
        "\tpr_emerg(\"T20RUN47 M after set_init_opp_index=%d\\n\", gvrctrl->late_init_opp);",
        "set_init_opp_index",
    )
    chunk = replace_one(
        chunk,
        first,
        "\tfeature_en = is_vcorefs_feature_enable();\n"
        "\tpr_emerg(\"T20RUN47 N feature2=%d\\n\", feature_en);\n"
        "\tif (feature_en) {",
        "second feature check",
    )
    chunk = replace_one(
        chunk,
        "\t\tkick_dvfs_by_opp_index(&krconf);",
        "\t\tpr_emerg(\"T20RUN47 O before kick_dvfs_by_opp_index\\n\");\n"
        "\t\tkick_dvfs_by_opp_index(&krconf);\n"
        "\t\tpr_emerg(\"T20RUN47 P after kick_dvfs_by_opp_index\\n\");",
        "kick_dvfs_by_opp_index",
    )
    chunk = replace_one(
        chunk,
        "\tmutex_unlock(&governor_mutex);",
        "\tmutex_unlock(&governor_mutex);\n"
        "\tpr_emerg(\"T20RUN47 Q after governor mutex\\n\");",
        "governor mutex unlock",
    )
    chunk = replace_one(
        chunk,
        "\tvcorefs_drv_init(gvrctrl->plat_init_done, is_vcorefs_feature_enable(), gvrctrl->late_init_opp);",
        "\tpr_emerg(\"T20RUN47 R before vcorefs_drv_init\\n\");\n"
        "\tvcorefs_drv_init(gvrctrl->plat_init_done, is_vcorefs_feature_enable(), gvrctrl->late_init_opp);\n"
        "\tpr_emerg(\"T20RUN47 S after vcorefs_drv_init\\n\");",
        "vcorefs_drv_init",
    )
    return chunk


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    args = ap.parse_args()

    p = Path(args.kernel) / "drivers/misc/mediatek/base/power/mt6797/mt_vcorefs_governor.c"
    s = p.read_text()
    s = patch_function(s, "bool is_vcorefs_feature_enable(void)", patch_feature)
    s = patch_function(s, "int vcorefs_late_init_dvfs(void)", patch_late)

    for marker in "ABCDEFGHIJKLMNOPQRS":
        token = f"T20RUN47 {marker} "
        if token not in s:
            raise SystemExit(f"missing marker after patch: {token}")

    p.write_text(s)
    print("run47 VcoreFS markers A..S injected", flush=True)


if __name__ == "__main__":
    main()
