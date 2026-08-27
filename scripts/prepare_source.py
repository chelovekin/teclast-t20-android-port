#!/usr/bin/env python3
import argparse
import shutil
from pathlib import Path


def copy_dir(src: Path, dst: Path) -> None:
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
    args = ap.parse_args()

    k = Path(args.kernel).resolve()
    d = Path(args.donor).resolve()

    # T20 Android 8.1 stock config requests these components, but the public
    # MT6797 Android-8 tree is missing them. Import the closest pinned MTK 3.18
    # implementations and integrate them into the Android-8 sensor framework.
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

    # The donor GSLX680 comes from an MTK tree with CONFIG_MTK_I2C_EXTENSION,
    # where struct i2c_msg has a vendor-only `timing` member. MT6797 uses the
    # arbitration I2C path and does not enable that extension, so the per-msg
    # timing assignment cannot exist here. The transfer itself is standard
    # i2c_transfer() and remains unchanged.
    gsl = k / "drivers/input/touchscreen/mediatek/GSlX680/mtk_gslX680.c"
    gsl_text = gsl.read_text()
    timing_line = "\txfer_msg[0].timing = 400;\n"
    if timing_line not in gsl_text:
        raise RuntimeError("expected GSLX680 donor timing assignment not found")
    gsl.write_text(gsl_text.replace(timing_line, "", 1))

    # The donor GSL Makefile contains project-specific ARM paths and debug
    # warnings. Keep only the architecture-neutral rules, including its
    # required prebuilt AArch64 gsl_point_id object.
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
