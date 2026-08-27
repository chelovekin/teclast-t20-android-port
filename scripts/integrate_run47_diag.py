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
    kernel = Path(args.kernel)

    # 1) Mark the exact transition seen in the preserved run46 ram-console:
    # all nine MT6797 PCM firmware versions print, then control enters the
    # late VcoreFS initialization path.
    p = kernel / "drivers/misc/mediatek/base/power/spm_v2/mt_spm.c"
    s = p.read_text()
    old = """\tif (spm_fw_count == check_spm_fw_count) {\n\t\tvcorefs_late_init_dvfs();\n\t\tdyna_load_pcm_done = 1;\n\t}\n"""
    new = """\tpr_emerg(\"T20RUN47: PCM loop complete count=%d expected=%d\\n\",\n\t\t spm_fw_count, check_spm_fw_count);\n\tif (spm_fw_count == check_spm_fw_count) {\n\t\tpr_emerg(\"T20RUN47: before vcorefs_late_init_dvfs\\n\");\n\t\tvcorefs_late_init_dvfs();\n\t\tpr_emerg(\"T20RUN47: after vcorefs_late_init_dvfs\\n\");\n\t\tdyna_load_pcm_done = 1;\n\t\tpr_emerg(\"T20RUN47: dyna_load_pcm_done=1\\n\");\n\t}\n"""
    s = replace_once(s, old, new, "mt_spm late-init transition")
    p.write_text(s)

    # 2) Trace the MT6797 VcoreFS governor late-init path without changing its
    # decisions or return values.
    p = kernel / "drivers/misc/mediatek/base/power/mt6797/mt_vcorefs_governor.c"
    s = p.read_text()

    s = replace_once(
        s,
        """bool is_vcorefs_feature_enable(void)\n{\n\tstruct governor_profile *gvrctrl = &governor_ctrl;\n\n\tif (!dram_can_support_fh()) {\n""",
        """bool is_vcorefs_feature_enable(void)\n{\n\tstruct governor_profile *gvrctrl = &governor_ctrl;\n\n\tpr_emerg(\"T20RUN47: feature_check before dram_can_support_fh\\n\");\n\tif (!dram_can_support_fh()) {\n""",
        "feature check entry",
    )
    s = replace_once(
        s,
        """\t\tvcorefs_err(\"DISABLE DVFS DUE TO NOT SUPPORT DRAM FH\\n\");\n\t}\n\n\treturn gvrctrl->plat_feature_en;\n}\n""",
        """\t\tvcorefs_err(\"DISABLE DVFS DUE TO NOT SUPPORT DRAM FH\\n\");\n\t}\n\tpr_emerg(\"T20RUN47: feature_check after dram_can_support_fh enabled=%d\\n\",\n\t\t gvrctrl->plat_feature_en);\n\n\treturn gvrctrl->plat_feature_en;\n}\n""",
        "feature check exit",
    )

    old_func = """int vcorefs_late_init_dvfs(void)\n{\n\tstruct kicker_config krconf;\n\tstruct governor_profile *gvrctrl = &governor_ctrl;\n\tint flag;\n\n\tif (is_vcorefs_feature_enable()) {\n\n\t\tkicker_table[KIR_REESPI] = -1;\n\t\tkicker_table[KIR_TEESPI] = -1;\n\n\t\tflag = vcorefs_check_feature_enable();\n\t\tvcorefs_crit(\"[%s] vcore_dvs: %d, ddr_dfs: %d, freq_dfs: %d, pcm_flag: 0x%x\\n\", __func__,\n\t\t\t\t\t\tgvrctrl->vcore_dvs, gvrctrl->ddr_dfs, gvrctrl->freq_dfs, flag);\n\t\tspm_go_to_vcore_dvfs(flag, 0);\n\t}\n\n\tmutex_lock(&governor_mutex);\n\tgvrctrl->late_init_opp = set_init_opp_index();\n\n\tif (is_vcorefs_feature_enable()) {\n\t\tkrconf.kicker = KIR_LATE_INIT;\n\t\tkrconf.opp = gvrctrl->late_init_opp;\n\t\tkrconf.dvfs_opp = gvrctrl->late_init_opp;\n\n\t\tkick_dvfs_by_opp_index(&krconf);\n\t}\n\n\tvcorefs_curr_opp = gvrctrl->late_init_opp;\n\tvcorefs_prev_opp = gvrctrl->late_init_opp;\n\tgvrctrl->plat_init_done = 1;\n\tmutex_unlock(&governor_mutex);\n\n\tvcorefs_crit(\"[%s] plat_init_done: %d, plat_feature_en: %d, late_init_opp: %d(%d)(%d)\\n\", __func__,\n\t\t\t\tgvrctrl->plat_init_done, is_vcorefs_feature_enable(),\n\t\t\t\tgvrctrl->late_init_opp, vcorefs_curr_opp, vcorefs_prev_opp);\n\n\tvcorefs_drv_init(gvrctrl->plat_init_done, is_vcorefs_feature_enable(), gvrctrl->late_init_opp);\n\n\treturn 0;\n}\n"""
    new_func = """int vcorefs_late_init_dvfs(void)\n{\n\tstruct kicker_config krconf;\n\tstruct governor_profile *gvrctrl = &governor_ctrl;\n\tint flag;\n\n\tpr_emerg(\"T20RUN47: late_init enter\\n\");\n\tpr_emerg(\"T20RUN47: late_init before feature check A\\n\");\n\tif (is_vcorefs_feature_enable()) {\n\t\tpr_emerg(\"T20RUN47: late_init feature A enabled\\n\");\n\n\t\tkicker_table[KIR_REESPI] = -1;\n\t\tkicker_table[KIR_TEESPI] = -1;\n\t\tpr_emerg(\"T20RUN47: late_init SPI kickers reset\\n\");\n\n\t\tpr_emerg(\"T20RUN47: late_init before vcorefs_check_feature_enable\\n\");\n\t\tflag = vcorefs_check_feature_enable();\n\t\tpr_emerg(\"T20RUN47: late_init after vcorefs_check_feature_enable flag=0x%x\\n\", flag);\n\t\tvcorefs_crit(\"[%s] vcore_dvs: %d, ddr_dfs: %d, freq_dfs: %d, pcm_flag: 0x%x\\n\", __func__,\n\t\t\t\t\t\tgvrctrl->vcore_dvs, gvrctrl->ddr_dfs, gvrctrl->freq_dfs, flag);\n\t\tpr_emerg(\"T20RUN47: late_init before spm_go_to_vcore_dvfs\\n\");\n\t\tspm_go_to_vcore_dvfs(flag, 0);\n\t\tpr_emerg(\"T20RUN47: late_init after spm_go_to_vcore_dvfs\\n\");\n\t}\n\tpr_emerg(\"T20RUN47: late_init after feature branch A\\n\");\n\n\tpr_emerg(\"T20RUN47: late_init before governor mutex lock\\n\");\n\tmutex_lock(&governor_mutex);\n\tpr_emerg(\"T20RUN47: late_init after governor mutex lock\\n\");\n\tpr_emerg(\"T20RUN47: late_init before set_init_opp_index\\n\");\n\tgvrctrl->late_init_opp = set_init_opp_index();\n\tpr_emerg(\"T20RUN47: late_init after set_init_opp_index opp=%d\\n\", gvrctrl->late_init_opp);\n\n\tpr_emerg(\"T20RUN47: late_init before feature check B\\n\");\n\tif (is_vcorefs_feature_enable()) {\n\t\tpr_emerg(\"T20RUN47: late_init feature B enabled\\n\");\n\t\tkrconf.kicker = KIR_LATE_INIT;\n\t\tkrconf.opp = gvrctrl->late_init_opp;\n\t\tkrconf.dvfs_opp = gvrctrl->late_init_opp;\n\n\t\tpr_emerg(\"T20RUN47: late_init before kick_dvfs_by_opp_index\\n\");\n\t\tkick_dvfs_by_opp_index(&krconf);\n\t\tpr_emerg(\"T20RUN47: late_init after kick_dvfs_by_opp_index\\n\");\n\t}\n\tpr_emerg(\"T20RUN47: late_init after feature branch B\\n\");\n\n\tvcorefs_curr_opp = gvrctrl->late_init_opp;\n\tvcorefs_prev_opp = gvrctrl->late_init_opp;\n\tgvrctrl->plat_init_done = 1;\n\tpr_emerg(\"T20RUN47: late_init before governor mutex unlock\\n\");\n\tmutex_unlock(&governor_mutex);\n\tpr_emerg(\"T20RUN47: late_init after governor mutex unlock\\n\");\n\n\tvcorefs_crit(\"[%s] plat_init_done: %d, plat_feature_en: %d, late_init_opp: %d(%d)(%d)\\n\", __func__,\n\t\t\t\tgvrctrl->plat_init_done, is_vcorefs_feature_enable(),\n\t\t\t\tgvrctrl->late_init_opp, vcorefs_curr_opp, vcorefs_prev_opp);\n\n\tpr_emerg(\"T20RUN47: late_init before vcorefs_drv_init\\n\");\n\tvcorefs_drv_init(gvrctrl->plat_init_done, is_vcorefs_feature_enable(), gvrctrl->late_init_opp);\n\tpr_emerg(\"T20RUN47: late_init after vcorefs_drv_init\\n\");\n\n\tpr_emerg(\"T20RUN47: late_init leave\\n\");\n\treturn 0;\n}\n"""
    s = replace_once(s, old_func, new_func, "vcorefs_late_init_dvfs")
    p.write_text(s)

    # 3) If the hang is inside the SPM scenario transition, bracket every
    # register-programming stage. The markers are deliberately KERN_EMERG so
    # MTK ram-console/pstore captures the last completed stage before watchdog.
    p = kernel / "drivers/misc/mediatek/base/power/spm_v2/mt_spm_vcorefs_mt6797.c"
    s = p.read_text()
    old_func = """static void __go_to_vcore_dvfs(u32 spm_flags, u8 spm_data)\n{\n\tunsigned long flags;\n\tstruct pcm_desc *pcmdesc;\n\tstruct pwr_ctrl *pwrctrl;\n\n#if DYNAMIC_LOAD\n\tu32 vcorefs_idx = spm_get_pcm_vcorefs_index();\n\n\tif (dyna_load_pcm[vcorefs_idx].ready) {\n\t\tpcmdesc = &(dyna_load_pcm[vcorefs_idx].desc);\n\t\tpwrctrl = __spm_vcore_dvfs.pwrctrl;\n\t} else {\n\t\tspm_vcorefs_err(\"[%s] dyna load F/W fail\\n\", __func__);\n\t\tBUG();\n\t}\n#else\n\tpcmdesc = __spm_vcore_dvfs.pcmdesc;\n\tpwrctrl = __spm_vcore_dvfs.pwrctrl;\n#endif\n\n\tif (!is_vcorefs_fw(DYNAMIC_LOAD))\n\t\tspm_vcorefs_spi_check();\n\n\tset_pwrctrl_pcm_flags(pwrctrl, spm_flags);\n\n\tmt_spm_pmic_wrap_set_phase(PMIC_WRAP_PHASE_NORMAL);\n\n\tspin_lock_irqsave(&__spm_lock, flags);\n\n\t_spm_vcorefs_init_reg();\n\n\t__spm_clean_after_wakeup();\n\n\t__spm_reset_and_init_pcm(pcmdesc);\n\n\t__spm_kick_im_to_fetch(pcmdesc);\n\n\t__spm_init_pcm_register();\n\n\t__spm_init_event_vector(pcmdesc);\n\n\t__spm_set_power_control(pwrctrl);\n\n\t__spm_set_wakeup_event(pwrctrl);\n\n\t__spm_kick_pcm_to_run(pwrctrl);\n\n\tspin_unlock_irqrestore(&__spm_lock, flags);\n\n#if SPM_AEE_RR_REC\n\taee_rr_rec_spm_common_scenario_val(SPM_COMMON_SCENARIO_SODI);\n#endif\n}\n"""
    new_func = """static void __go_to_vcore_dvfs(u32 spm_flags, u8 spm_data)\n{\n\tunsigned long flags;\n\tstruct pcm_desc *pcmdesc;\n\tstruct pwr_ctrl *pwrctrl;\n\n\tpr_emerg(\"T20RUN47: __go_to_vcore_dvfs enter flags=0x%x\\n\", spm_flags);\n#if DYNAMIC_LOAD\n\tpr_emerg(\"T20RUN47: SPM before spm_get_pcm_vcorefs_index\\n\");\n\tu32 vcorefs_idx = spm_get_pcm_vcorefs_index();\n\tpr_emerg(\"T20RUN47: SPM after spm_get_pcm_vcorefs_index idx=%u ready=%d\\n\",\n\t\t vcorefs_idx, dyna_load_pcm[vcorefs_idx].ready);\n\n\tif (dyna_load_pcm[vcorefs_idx].ready) {\n\t\tpcmdesc = &(dyna_load_pcm[vcorefs_idx].desc);\n\t\tpwrctrl = __spm_vcore_dvfs.pwrctrl;\n\t\tpr_emerg(\"T20RUN47: SPM dynamic firmware selected version=%s\\n\", pcmdesc->version);\n\t} else {\n\t\tspm_vcorefs_err(\"[%s] dyna load F/W fail\\n\", __func__);\n\t\tBUG();\n\t}\n#else\n\tpcmdesc = __spm_vcore_dvfs.pcmdesc;\n\tpwrctrl = __spm_vcore_dvfs.pwrctrl;\n#endif\n\n\tpr_emerg(\"T20RUN47: SPM before is_vcorefs_fw\\n\");\n\tif (!is_vcorefs_fw(DYNAMIC_LOAD)) {\n\t\tpr_emerg(\"T20RUN47: SPM before spm_vcorefs_spi_check\\n\");\n\t\tspm_vcorefs_spi_check();\n\t\tpr_emerg(\"T20RUN47: SPM after spm_vcorefs_spi_check\\n\");\n\t}\n\tpr_emerg(\"T20RUN47: SPM after is_vcorefs_fw branch\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before set_pwrctrl_pcm_flags\\n\");\n\tset_pwrctrl_pcm_flags(pwrctrl, spm_flags);\n\tpr_emerg(\"T20RUN47: SPM after set_pwrctrl_pcm_flags\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before mt_spm_pmic_wrap_set_phase\\n\");\n\tmt_spm_pmic_wrap_set_phase(PMIC_WRAP_PHASE_NORMAL);\n\tpr_emerg(\"T20RUN47: SPM after mt_spm_pmic_wrap_set_phase\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before __spm_lock\\n\");\n\tspin_lock_irqsave(&__spm_lock, flags);\n\tpr_emerg(\"T20RUN47: SPM after __spm_lock\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before _spm_vcorefs_init_reg\\n\");\n\t_spm_vcorefs_init_reg();\n\tpr_emerg(\"T20RUN47: SPM after _spm_vcorefs_init_reg\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before __spm_clean_after_wakeup\\n\");\n\t__spm_clean_after_wakeup();\n\tpr_emerg(\"T20RUN47: SPM after __spm_clean_after_wakeup\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before __spm_reset_and_init_pcm\\n\");\n\t__spm_reset_and_init_pcm(pcmdesc);\n\tpr_emerg(\"T20RUN47: SPM after __spm_reset_and_init_pcm\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before __spm_kick_im_to_fetch\\n\");\n\t__spm_kick_im_to_fetch(pcmdesc);\n\tpr_emerg(\"T20RUN47: SPM after __spm_kick_im_to_fetch\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before __spm_init_pcm_register\\n\");\n\t__spm_init_pcm_register();\n\tpr_emerg(\"T20RUN47: SPM after __spm_init_pcm_register\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before __spm_init_event_vector\\n\");\n\t__spm_init_event_vector(pcmdesc);\n\tpr_emerg(\"T20RUN47: SPM after __spm_init_event_vector\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before __spm_set_power_control\\n\");\n\t__spm_set_power_control(pwrctrl);\n\tpr_emerg(\"T20RUN47: SPM after __spm_set_power_control\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before __spm_set_wakeup_event\\n\");\n\t__spm_set_wakeup_event(pwrctrl);\n\tpr_emerg(\"T20RUN47: SPM after __spm_set_wakeup_event\\n\");\n\n\tpr_emerg(\"T20RUN47: SPM before __spm_kick_pcm_to_run\\n\");\n\t__spm_kick_pcm_to_run(pwrctrl);\n\tpr_emerg(\"T20RUN47: SPM after __spm_kick_pcm_to_run\\n\");\n\n\tspin_unlock_irqrestore(&__spm_lock, flags);\n\tpr_emerg(\"T20RUN47: SPM after __spm_unlock\\n\");\n\n#if SPM_AEE_RR_REC\n\taee_rr_rec_spm_common_scenario_val(SPM_COMMON_SCENARIO_SODI);\n#endif\n\tpr_emerg(\"T20RUN47: __go_to_vcore_dvfs leave\\n\");\n}\n"""
    s = replace_once(s, old_func, new_func, "__go_to_vcore_dvfs")
    p.write_text(s)

    print("run47 diagnostics integrated")


if __name__ == "__main__":
    main()
