#!/usr/bin/env python3
import argparse
import re
import shutil
from pathlib import Path


def copy_dir(src: Path, dst: Path) -> None:
    if not src.is_dir():
        raise RuntimeError(f"required donor directory missing: {src}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def append_once(path: Path, marker: str, text: str) -> None:
    data = path.read_text()
    if marker not in data:
        if not data.endswith("\n"):
            data += "\n"
        data += text
        path.write_text(data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--donor", required=True)
    ap.add_argument("--camera-donor", required=True)
    args = ap.parse_args()

    k = Path(args.kernel).resolve()
    d = Path(args.donor).resolve()
    cam = Path(args.camera_donor).resolve()

    # T20 Android 8.1 stock config requests these components, but the public
    # MT6797 Android-8 tree is missing them. Import pinned MTK implementations
    # and adapt only what is required to build them in this source framework.
    copy_dir(
        d / "drivers/input/touchscreen/mediatek/GSlX680",
        k / "drivers/input/touchscreen/mediatek/GSlX680",
    )
    copy_dir(
        d / "drivers/misc/mediatek/lcm/lq101r1sx01a_wqxga_dsi_vdo",
        k / "drivers/misc/mediatek/lcm/lq101r1sx01a_wqxga_dsi_vdo",
    )
    copy_dir(
        d / "drivers/misc/mediatek/accelerometer/msa300",
        k / "drivers/misc/mediatek/sensors-1.0/accelerometer/msa300",
    )
    copy_dir(
        d / "drivers/misc/mediatek/alsps/LTR303",
        k / "drivers/misc/mediatek/sensors-1.0/alsps/LTR303",
    )

    # Adapt the MT8176/MT6397 LQ101 donor to the MT6797/MT6351 ABI.  The donor
    # toggles the old MT6397 VGP4 LDO with upmu_set_rg_vgp4_*(), but MT6797's
    # PMIC API has no VGP4 at all (its generic programmable LDO is VGP3).  The
    # factory T20 8.1 DTBO marks VGP3 default-on and the factory kernel's LQ101
    # platform-driver strings show only gpio_lcm_pwr_en, not an LCM1V8/VGP4
    # regulator consumer.  Keep the panel GPIO sequencing and remove only the
    # three stale MT6397 VGP4 calls rather than inventing a different rail.
    lq_dir = k / "drivers/misc/mediatek/lcm/lq101r1sx01a_wqxga_dsi_vdo"
    lq_main = lq_dir / "lq101r1sx01a_wqxga_dsi_vdo.c"
    lq_text = lq_main.read_text()
    lq_text, vgp4_count = re.subn(
        r'^[ \t]*upmu_set_rg_vgp4_(?:sw_en|vosel)\s*\([^;]+\);[ \t]*\r?\n?',
        '',
        lq_text,
        flags=re.MULTILINE,
    )
    if vgp4_count != 3:
        raise RuntimeError(
            f"expected exactly 3 active MT6397 VGP4 calls in LQ101 donor, found {vgp4_count}"
        )
    if re.search(r'^[ \t]*upmu_set_rg_vgp4_', lq_text, flags=re.MULTILINE):
        raise RuntimeError("active MT6397 VGP4 call remains in LQ101 donor")
    lq_main.write_text(lq_text)

    # The donor's companion platform driver is also MT8173-specific.  The
    # actual T20 8.1 kernel contains the compatible string mediatek,mt6797-lcm
    # and only requests gpio_lcm_pwr_en.  Mirror that observed stock shape:
    # do not request donor-only reset/LED GPIO properties or the absent LCM1V8
    # regulator.  This keeps probe tied to the real MT6797 lcm node.
    lq_plat = lq_dir / "lcm_drv_lq101r1sx01a_wqxga_dsi_vdo.c"
    plat_text = lq_plat.read_text()
    old_compatible = 'compatible = "mediatek,mt8173-lcm"'
    if old_compatible not in plat_text:
        raise RuntimeError("expected MT8173 LQ101 compatible string not found")
    plat_text = plat_text.replace(
        old_compatible,
        'compatible = "mediatek,mt6797-lcm"',
        1,
    )
    request_re = re.compile(
        r'static int lcm_request_gpio_control\(struct device \*dev\)\s*\{.*?\n\}\n\nstatic int lcm_probe',
        re.DOTALL,
    )
    request_replacement = '''static int lcm_request_gpio_control(struct device *dev)\n{\n\tint ret;\n\n\tGPIO_LCD_PWR_EN = of_get_named_gpio(dev->of_node, "gpio_lcm_pwr_en", 0);\n\tret = gpio_request(GPIO_LCD_PWR_EN, "GPIO_LCD_PWR_EN");\n\tif (ret)\n\t\tprintk("[KE/LCM] gpio request GPIO_LCD_PWR_EN = 0x%x fail with %d\\n",\n\t\t       GPIO_LCD_PWR_EN, ret);\n\n\treturn ret;\n}\n\nstatic int lcm_probe'''
    plat_text, request_count = request_re.subn(request_replacement, plat_text, count=1)
    if request_count != 1:
        raise RuntimeError("could not replace donor LQ101 GPIO/regulator probe")
    if 'regulator_get(dev, "LCM1V8")' in plat_text:
        raise RuntimeError("donor LCM1V8 regulator consumer remains")
    if 'of_get_named_gpio(dev->of_node, "gpio_led"' in plat_text:
        raise RuntimeError("donor LQ101 LED GPIO request remains")
    if 'of_get_named_gpio(dev->of_node, "gpio_lcm_rst_en"' in plat_text:
        raise RuntimeError("donor LQ101 reset GPIO request remains")
    lq_plat.write_text(plat_text)
    print(
        f"LQ101 MT6797 adaptation: removed {vgp4_count} MT6397 VGP4 call(s), "
        "matched factory mt6797-lcm probe",
        flush=True,
    )

    # The MT6797 Android-8 base has the generic LCM registry but does not know
    # the factory T20 panel imported above. CONFIG_CUSTOM_KERNEL_LCM is turned
    # into the LQ101R1SX01A_WQXGA_DSI_VDO preprocessor define by the existing
    # MTK LCM Makefile, so register exactly the donor's exported driver symbol.
    lcm_h = k / "drivers/misc/mediatek/lcm/mt65xx_lcm_list.h"
    lcm_h_text = lcm_h.read_text()
    lcm_decl = "extern LCM_DRIVER lq101r1sx01a_wqxga_dsi_vdo_lcm_drv;"
    if lcm_decl not in lcm_h_text:
        marker = "\n#ifdef BUILD_LK\n"
        if marker not in lcm_h_text:
            raise RuntimeError("could not locate LCM header insertion point")
        lcm_h.write_text(lcm_h_text.replace(marker, "\n" + lcm_decl + "\n" + marker, 1))

    lcm_c = k / "drivers/misc/mediatek/lcm/mt65xx_lcm_list.c"
    lcm_c_text = lcm_c.read_text()
    lcm_guard = "#if defined(LQ101R1SX01A_WQXGA_DSI_VDO)"
    if lcm_guard not in lcm_c_text:
        marker = "\n};\n\nunsigned char lcm_name_list"
        if marker not in lcm_c_text:
            raise RuntimeError("could not locate LCM driver-list insertion point")
        block = (
            "\n#if defined(LQ101R1SX01A_WQXGA_DSI_VDO)\n"
            "\t&lq101r1sx01a_wqxga_dsi_vdo_lcm_drv,\n"
            "#endif\n"
        )
        lcm_c.write_text(lcm_c_text.replace(
            marker,
            block + "\n};\n\nunsigned char lcm_name_list",
            1,
        ))
    print("T20 factory LQ101 LCM registered in MT6797 driver list", flush=True)

    # The exact stock config also names s5k3l9_mipi_raw, but that directory is
    # absent from the public MT6797 Android-8 tree. The closest public MTK
    # implementation found is pinned separately and imported as a compatibility
    # donor. It is intentionally kept isolated so provenance is explicit.
    cam_dst = k / "drivers/misc/mediatek/imgsensor/src/mt6797/s5k3l9_mipi_raw"
    copy_dir(
        cam / "drivers/misc/mediatek/imgsensor/src/mt6795/s5k3l9_mipi_raw",
        cam_dst,
    )
    # Its old tree included a global Makefile.custom that the Android-8 MT6797
    # source does not contain. Only the two local objects are needed here.
    (cam_dst / "Makefile").write_text(
        "obj-y += s5k3l9otp.o\n"
        "obj-y += s5k3l9mipiraw_Sensor.o\n"
    )

    # The older camera donor also assumes MTK_I2C_EXTENSION. MT6797's stock
    # configuration does not enable it, so struct i2c_client has no `timing`
    # member. The bus timing is owned by the MT6797 controller; remove only the
    # donor-only assignment. linux/xlog.h is likewise absent and unused because
    # this driver already routes LOG_INF through pr_debug().
    sensor_c = cam_dst / "s5k3l9mipiraw_Sensor.c"
    sensor_text = sensor_c.read_text()
    sensor_text = re.sub(r'^#include <linux/xlog\.h>\s*\r?\n', '', sensor_text, flags=re.MULTILINE)
    sensor_c.write_text(sensor_text)

    otp_c = cam_dst / "s5k3l9otp.c"
    otp_text = otp_c.read_text()
    otp_text, camera_timing_count = re.subn(
        r'^[ \t]*g_pstI2Cclient->timing\s*=\s*[^;]+;[ \t]*\r?\n?',
        '',
        otp_text,
        flags=re.MULTILINE,
    )
    if camera_timing_count == 0:
        raise RuntimeError("expected S5K3L9 donor i2c_client timing assignment not found")
    if re.search(r'\bg_pstI2Cclient->timing\b', otp_text):
        raise RuntimeError("unsupported S5K3L9 i2c_client timing assignment remains")

    # Pull the donor's old CAM_CAL helper onto the Android-8 MT6797 camera ABI.
    # The factory config is arm64+compat, so keep the compat ioctl rather than
    # deleting it. These edits are mechanical API migrations; OTP offsets and
    # calibration payload handling are left intact.
    otp_text = otp_text.replace(
        '#include <linux/i2c.h>\n',
        '#include <linux/module.h>\n#include <linux/i2c.h>\n#include "kd_camera_typedef.h"\n',
        1,
    )
    otp_text = re.sub(r'^[ \t]*kal_uint16 get_byte\s*=\s*0;[ \t]*\r?\n', '', otp_text, flags=re.MULTILINE)
    otp_text = re.sub(
        r'^[ \t]*g_pstI2Cclient->addr\s*=\s*g_pstI2Cclient->addr\s*&\s*\(I2C_MASK_FLAG\);[ \t]*\r?\n',
        '',
        otp_text,
        flags=re.MULTILINE,
    )
    otp_text = otp_text.replace(
        'g_s5k3l9_otp_struct.module_id;\n',
        'return g_s5k3l9_otp_struct.module_id;\n',
        1,
    )
    otp_text = otp_text.replace(
        'static kal_uint8 S5K3L9_Read_AWBAF_Otp(kal_uint8 address,unsigned char *iBuffer,unsigned int buffersize)\n{\n\tu8 readbuff, i;',
        'static kal_uint8 S5K3L9_Read_AWBAF_Otp(kal_uint8 address,unsigned char *iBuffer,unsigned int buffersize)\n{\n\tu8 i;',
        1,
    )
    otp_text = otp_text.replace(
        'static kal_bool S5K3L9_Read_PDAF_Otp(u16 Outdatalen,unsigned char * pOutputdata)\n{\n\tu8 readbuff, i;',
        'static kal_bool S5K3L9_Read_PDAF_Otp(u16 Outdatalen,unsigned char * pOutputdata)\n{\n\tunsigned int i;',
        1,
    )
    otp_text = otp_text.replace(
        '    else if(ui4_length == S5K3L9_LSC_OTP_SIZE)\n    {',
        '    else if(ui4_length == S5K3L9_PDAF_OTP_SIZE)\n    {\n        S5K3L9_Read_PDAF_Otp(ui4_length, pinputdata);\n    }\n    else if(ui4_length == S5K3L9_LSC_OTP_SIZE)\n    {',
        1,
    )
    otp_text = otp_text.replace(
        'bool read_3l9_pdaf_data( kal_uint16 addr, BYTE* data, kal_uint32 size)',
        'bool read_3l9_pdaf_data(kal_uint16 addr, unsigned char *data, kal_uint32 size)',
        1,
    )
    otp_text = re.sub(
        r'(int get_3l9_dvt_id\(void\)\s*\{\s*)int i\s*=\s*0;\s*',
        r'\1',
        otp_text,
        count=1,
    )
    otp_text = otp_text.replace(
        '    compat_uptr_t p;\n    compat_uint_t i;\n    int err;\n\n    err = get_user(i, &data->u4Offset);',
        '    compat_uptr_t p;\n    compat_uint_t i;\n    void __user *up;\n    int err;\n\n    err = get_user(i, &data->u4Offset);',
        1,
    )
    otp_text = otp_text.replace(
        '    err |= get_user(p, &data->pu1Params);\n    err |= put_user(p, &data32->pu1Params);',
        '    err |= get_user(up, &data->pu1Params);\n    p = ptr_to_compat(up);\n    err |= put_user(p, &data32->pu1Params);',
        1,
    )
    otp_text = otp_text.replace(
        '    case COMPAT_CAM_CALIOC_G_READ:\n    {\n        CAM_CALDB("[CAMERA SENSOR] COMPAT_CAM_CALIOC_G_READ\\n");\n        COMPAT_stCAM_CAL_INFO_STRUCT __user *data32;\n        stCAM_CAL_INFO_STRUCT __user *data;\n        int err;\n',
        '    case COMPAT_CAM_CALIOC_G_READ:\n    {\n        COMPAT_stCAM_CAL_INFO_STRUCT __user *data32;\n        stCAM_CAL_INFO_STRUCT __user *data;\n        int err;\n\n        CAM_CALDB("[CAMERA SENSOR] COMPAT_CAM_CALIOC_G_READ\\n");\n',
        1,
    )
    otp_c.write_text(otp_text)

    # The MT6795 donor used the removed legacy mach/mt_boot.h include. The
    # Android-8 MT6797 tree exposes the same boot_mode_t/get_boot_mode ABI from
    # mt-plat/mt_boot_common.h, including FACTORY_BOOT used by this driver.
    otp_h = cam_dst / "s5k3l9otp.h"
    otp_h_text = otp_h.read_text()
    legacy_boot_include = '#include "mach/mt_boot.h"'
    if legacy_boot_include not in otp_h_text:
        raise RuntimeError("expected S5K3L9 legacy boot header include not found")
    otp_h.write_text(otp_h_text.replace(
        legacy_boot_include,
        '#include <mt-plat/mt_boot_common.h>',
        1,
    ))
    print(f"S5K3L9 MT6797 I2C adaptation: removed {camera_timing_count} timing assignment(s)", flush=True)

    # The donor GSLX680 comes from an MTK tree with CONFIG_MTK_I2C_EXTENSION,
    # where struct i2c_msg has a vendor-only `timing` member. MT6797 uses the
    # arbitration I2C path and does not enable that extension. Remove every
    # xfer_msg[].timing assignment, including copies inside disabled legacy
    # code, while leaving the actual i2c_transfer() calls untouched.
    gsl = k / "drivers/input/touchscreen/mediatek/GSlX680/mtk_gslX680.c"
    gsl_text = gsl.read_text()
    gsl_text, count = re.subn(
        r"^[ \t]*xfer_msg\[\d+\]\.timing\s*=\s*[^;]+;[ \t]*\r?\n?",
        "",
        gsl_text,
        flags=re.MULTILINE,
    )
    if count == 0:
        raise RuntimeError("expected GSLX680 donor i2c_msg timing assignments not found")
    if re.search(r"\bxfer_msg\[\d+\]\.timing\b", gsl_text):
        raise RuntimeError("unsupported GSLX680 i2c_msg timing assignment remains")
    gsl.write_text(gsl_text)
    print(f"GSLX680 MT6797 I2C adaptation: removed {count} timing assignment(s)", flush=True)

    # The donor GSL Makefile contains project-specific ARM paths and debug
    # warnings. Keep only architecture-neutral rules, including its required
    # prebuilt AArch64 gsl_point_id object.
    (k / "drivers/input/touchscreen/mediatek/GSlX680/Makefile").write_text(
        "ccflags-y += -I$(srctree)/drivers/input/touchscreen/mediatek/GSlX680/\n"
        "ccflags-y += -I$(srctree)/drivers/input/touchscreen/mediatek/\n"
        "obj-y += mtk_gslX680.o\n"
        "obj-y += gsl_point_id.o\n"
        "$(obj)/gsl_point_id.o: $(srctree)/$(obj)/gsl_point_id\n"
        "\tcp $(srctree)/$(obj)/gsl_point_id $(obj)/gsl_point_id.o\n"
    )

    # Adapt old MTK sensor-driver include paths to the Android-8 sensors-1.0
    # framework used by the selected MT6797 source tree.
    (k / "drivers/misc/mediatek/sensors-1.0/accelerometer/msa300/Makefile").write_text(
        "ccflags-y += -I$(srctree)/drivers/misc/mediatek/sensors-1.0/accelerometer/inc\n"
        "ccflags-y += -I$(srctree)/drivers/misc/mediatek/sensors-1.0/hwmon/include\n"
        "ccflags-y += -I$(srctree)/drivers/misc/mediatek/sensors-1.0/include\n"
        "obj-y := msa_core.o msa_cust.o\n"
    )
    (k / "drivers/misc/mediatek/sensors-1.0/alsps/LTR303/Makefile").write_text(
        "ccflags-y += -I$(srctree)/drivers/misc/mediatek/sensors-1.0/alsps/inc\n"
        "ccflags-y += -I$(srctree)/drivers/misc/mediatek/sensors-1.0/hwmon/include\n"
        "ccflags-y += -I$(srctree)/drivers/misc/mediatek/include/mt-plat/\n"
        "ccflags-y += -I$(srctree)/drivers/misc/mediatek/include/mt-plat/$(MTK_PLATFORM)/include/\n"
        "ccflags-y += -I$(srctree)/drivers/misc/mediatek/include/mt-plat/$(MTK_PLATFORM)/include/mach/\n"
        "obj-y := ltr303.o\n"
    )

    append_once(
        k / "drivers/input/touchscreen/mediatek/Makefile",
        "CONFIG_TOUCHSCREEN_MTK_GSlX680",
        "\nobj-$(CONFIG_TOUCHSCREEN_MTK_GSlX680) += GSlX680/\n",
    )
    append_once(
        k / "drivers/input/touchscreen/mediatek/Kconfig",
        "config TOUCHSCREEN_MTK_GSlX680",
        "\nconfig TOUCHSCREEN_MTK_GSlX680\n"
        "\tbool \"GSLX680 touchscreen\"\n"
        "\tdepends on TOUCHSCREEN_MTK\n"
        "\tdefault n\n",
    )

    append_once(
        k / "drivers/misc/mediatek/sensors-1.0/accelerometer/Kconfig",
        'source "drivers/misc/mediatek/sensors-1.0/accelerometer/msa300/Kconfig"',
        '\nsource "drivers/misc/mediatek/sensors-1.0/accelerometer/msa300/Kconfig"\n',
    )
    append_once(
        k / "drivers/misc/mediatek/sensors-1.0/accelerometer/Makefile",
        "CONFIG_MTK_MSA300",
        "\nobj-$(CONFIG_MTK_MSA300) += msa300/\n",
    )
    append_once(
        k / "drivers/misc/mediatek/sensors-1.0/alsps/Kconfig",
        'source "drivers/misc/mediatek/sensors-1.0/alsps/LTR303/Kconfig"',
        '\nsource "drivers/misc/mediatek/sensors-1.0/alsps/LTR303/Kconfig"\n',
    )
    append_once(
        k / "drivers/misc/mediatek/sensors-1.0/alsps/Makefile",
        "CONFIG_MTK_LTR303",
        "\nobj-$(CONFIG_MTK_LTR303) += LTR303/\n",
    )

    print("T20 source integration prepared")


if __name__ == "__main__":
    main()
