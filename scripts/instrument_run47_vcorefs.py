#!/usr/bin/env python3
from pathlib import Path
import argparse


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    args = ap.parse_args()

    p = Path(args.kernel) / "drivers/misc/mediatek/base/power/mt6797/mt_vcorefs_governor.c"
    s = p.read_text()

    old = '''bool is_vcorefs_feature_enable(void)
{
\tstruct governor_profile *gvrctrl = &governor_ctrl;

\tif (!dram_can_support_fh()) {
\t\tgvrctrl->plat_feature_en = 0;
\t\tvcorefs_err("DISABLE DVFS DUE TO NOT SUPPORT DRAM FH\\n");
\t}

\treturn gvrctrl->plat_feature_en;
}
'''
    new = '''bool is_vcorefs_feature_enable(void)
{
\tstruct governor_profile *gvrctrl = &governor_ctrl;
\tint dram_fh_ok;

\tpr_emerg("T20RUN47 A enter is_vcorefs_feature_enable\\n");
\tpr_emerg("T20RUN47 B before dram_can_support_fh\\n");
\tdram_fh_ok = dram_can_support_fh();
\tpr_emerg("T20RUN47 C after dram_can_support_fh=%d\\n", dram_fh_ok);
\tif (!dram_fh_ok) {
\t\tgvrctrl->plat_feature_en = 0;
\t\tvcorefs_err("DISABLE DVFS DUE TO NOT SUPPORT DRAM FH\\n");
\t}
\tpr_emerg("T20RUN47 D leave is_vcorefs_feature_enable=%d\\n", gvrctrl->plat_feature_en);

\treturn gvrctrl->plat_feature_en;
}
'''
    s = replace_once(s, old, new, "is_vcorefs_feature_enable")

    old = '''int vcorefs_late_init_dvfs(void)
{
\tstruct kicker_config krconf;
\tstruct governor_profile *gvrctrl = &governor_ctrl;
\tint flag;

\tif (is_vcorefs_feature_enable()) {

\t\tkicker_table[KIR_REESPI] = -1;
\t\tkicker_table[KIR_TEESPI] = -1;

\t\tflag = vcorefs_check_feature_enable();
\t\tvcorefs_crit("[%s] vcore_dvs: %d, ddr_dfs: %d, freq_dfs: %d, pcm_flag: 0x%x\\n", __func__,
\t\t\t\t\t\tgvrctrl->vcore_dvs, gvrctrl->ddr_dfs, gvrctrl->freq_dfs, flag);
\t\tspm_go_to_vcore_dvfs(flag, 0);
\t}

\tmutex_lock(&governor_mutex);
\tgvrctrl->late_init_opp = set_init_opp_index();

\tif (is_vcorefs_feature_enable()) {
\t\tkrconf.kicker = KIR_LATE_INIT;
\t\tkrconf.opp = gvrctrl->late_init_opp;
\t\tkrconf.dvfs_opp = gvrctrl->late_init_opp;

\t\tkick_dvfs_by_opp_index(&krconf);
\t}

\tvcorefs_curr_opp = gvrctrl->late_init_opp;
\tvcorefs_prev_opp = gvrctrl->late_init_opp;
\tgvrctrl->plat_init_done = 1;
\tmutex_unlock(&governor_mutex);

\tvcorefs_crit("[%s] plat_init_done: %d, plat_feature_en: %d, late_init_opp: %d(%d)(%d)\\n", __func__,
\t\t\t\t\tgvrctrl->plat_init_done, is_vcorefs_feature_enable(),
\t\t\t\t\tgvrctrl->late_init_opp, vcorefs_curr_opp, vcorefs_prev_opp);

\tvcorefs_drv_init(gvrctrl->plat_init_done, is_vcorefs_feature_enable(), gvrctrl->late_init_opp);

\treturn 0;
}
'''
    new = '''int vcorefs_late_init_dvfs(void)
{
\tstruct kicker_config krconf;
\tstruct governor_profile *gvrctrl = &governor_ctrl;
\tint flag;
\tint feature_en;

\tpr_emerg("T20RUN47 E enter vcorefs_late_init_dvfs\\n");
\tfeature_en = is_vcorefs_feature_enable();
\tpr_emerg("T20RUN47 F feature1=%d\\n", feature_en);
\tif (feature_en) {

\t\tkicker_table[KIR_REESPI] = -1;
\t\tkicker_table[KIR_TEESPI] = -1;

\t\tpr_emerg("T20RUN47 G before vcorefs_check_feature_enable\\n");
\t\tflag = vcorefs_check_feature_enable();
\t\tpr_emerg("T20RUN47 H after vcorefs_check_feature_enable flag=0x%x\\n", flag);
\t\tvcorefs_crit("[%s] vcore_dvs: %d, ddr_dfs: %d, freq_dfs: %d, pcm_flag: 0x%x\\n", __func__,
\t\t\t\t\t\tgvrctrl->vcore_dvs, gvrctrl->ddr_dfs, gvrctrl->freq_dfs, flag);
\t\tpr_emerg("T20RUN47 I before spm_go_to_vcore_dvfs\\n");
\t\tspm_go_to_vcore_dvfs(flag, 0);
\t\tpr_emerg("T20RUN47 J after spm_go_to_vcore_dvfs\\n");
\t}

\tpr_emerg("T20RUN47 K before governor mutex\\n");
\tmutex_lock(&governor_mutex);
\tpr_emerg("T20RUN47 L before set_init_opp_index\\n");
\tgvrctrl->late_init_opp = set_init_opp_index();
\tpr_emerg("T20RUN47 M after set_init_opp_index=%d\\n", gvrctrl->late_init_opp);

\tfeature_en = is_vcorefs_feature_enable();
\tpr_emerg("T20RUN47 N feature2=%d\\n", feature_en);
\tif (feature_en) {
\t\tkrconf.kicker = KIR_LATE_INIT;
\t\tkrconf.opp = gvrctrl->late_init_opp;
\t\tkrconf.dvfs_opp = gvrctrl->late_init_opp;

\t\tpr_emerg("T20RUN47 O before kick_dvfs_by_opp_index\\n");
\t\tkick_dvfs_by_opp_index(&krconf);
\t\tpr_emerg("T20RUN47 P after kick_dvfs_by_opp_index\\n");
\t}

\tvcorefs_curr_opp = gvrctrl->late_init_opp;
\tvcorefs_prev_opp = gvrctrl->late_init_opp;
\tgvrctrl->plat_init_done = 1;
\tmutex_unlock(&governor_mutex);
\tpr_emerg("T20RUN47 Q after governor mutex\\n");

\tvcorefs_crit("[%s] plat_init_done: %d, plat_feature_en: %d, late_init_opp: %d(%d)(%d)\\n", __func__,
\t\t\t\t\tgvrctrl->plat_init_done, is_vcorefs_feature_enable(),
\t\t\t\t\tgvrctrl->late_init_opp, vcorefs_curr_opp, vcorefs_prev_opp);

\tpr_emerg("T20RUN47 R before vcorefs_drv_init\\n");
\tvcorefs_drv_init(gvrctrl->plat_init_done, is_vcorefs_feature_enable(), gvrctrl->late_init_opp);
\tpr_emerg("T20RUN47 S after vcorefs_drv_init\\n");

\treturn 0;
}
'''
    s = replace_once(s, old, new, "vcorefs_late_init_dvfs")

    p.write_text(s)
    print("run47 VcoreFS markers A..S injected", flush=True)


if __name__ == "__main__":
    main()
