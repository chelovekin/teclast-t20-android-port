#!/usr/bin/env python3
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

GOODIX_REPO = "https://github.com/Vgdn1942/android_kernel_mt6755_3.18.119.git"
GOODIX_COMMIT = "2b9237953a86a145cd801d85fdde92d656275ca8"
GOODIX_SRC = Path("drivers/input/fingerprint/gf3208")


def replace_exact(text: str, old: str, new: str, desc: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{desc}: expected one occurrence, found {count}")
    return text.replace(old, new, 1)


def clone_pinned(dst: Path) -> None:
    subprocess.run(["git", "init", "-q", str(dst)], check=True)
    subprocess.run(["git", "-C", str(dst), "remote", "add", "origin", GOODIX_REPO], check=True)
    subprocess.run(
        ["git", "-C", str(dst), "fetch", "-q", "--depth=1", "origin", GOODIX_COMMIT],
        check=True,
    )
    subprocess.run(["git", "-C", str(dst), "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
    got = subprocess.check_output(["git", "-C", str(dst), "rev-parse", "HEAD"], text=True).strip()
    if got != GOODIX_COMMIT:
        raise RuntimeError(f"Goodix donor pin mismatch: {got}")


def integrate_goodix(kernel: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="t20-goodix-") as td:
        donor = Path(td) / "donor"
        clone_pinned(donor)
        src = donor / GOODIX_SRC
        dst = kernel / "drivers/input/fingerprint/goodix_ree"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    # Preserve the donor generation whose ABI matches the March-2019 binary,
    # but bind it to the exact T20 SPI child and exact stock pinctrl state names.
    c = dst / "gf_common.c"
    s = c.read_text()

    # MT6797 donor carry-over: this header is absent from the Android-8 MT6797
    # tree and the only vcorefs calls in this Goodix source are commented out.
    # Removing the unused include changes no executable Goodix behavior.
    s = replace_exact(
        s,
        '#if defined(CONFIG_ARCH_MT6797)\n#include <mt_vcorefs_manager.h>\n#endif\n',
        '',
        "remove unused MT6755 vcorefs include",
    )

    s = replace_exact(
        s,
        '{ .compatible = "mediatek,goodix-fp", },',
        '{ .compatible = "goodix,fingerprint", },',
        "Goodix SPI compatible",
    )
    # The donor has one stale sensor-info lookup spelling not present in the
    # exact March Image. The T20 platform pinctrl node is mediatek,goodix-fp.
    s = replace_exact(
        s,
        'of_find_compatible_node(NULL, NULL, "goodix,goodix-fp")',
        'of_find_compatible_node(NULL, NULL, "mediatek,goodix-fp")',
        "Goodix platform-node compatible",
    )

    pin_names = {
        '"fp_state_eint_as_int"': '"fingerprint_irq"',
        '"fp_default"': '"default"',
        '"finger_power_low"': '"en_low"',
        '"finger_power_high"': '"en_high"',
        '"fp_state_rst_output1"': '"reset_high"',
        '"fp_state_rst_output0"': '"reset_low"',
    }
    for old, new in pin_names.items():
        if old not in s:
            raise RuntimeError(f"Goodix pinctrl state missing in donor: {old}")
        s = s.replace(old, new)

    # The exact factory binary carries this source path and these strings.
    required = [
        'mediatek,goodix-fp',
        'goodix_fp',
        'GF_IOC_TRANSFER_RAW_CMD',
        'Finger Print: Have not used Goodix, return',
        'GF_LINUX_VERSION "V1.01.04"',
    ]
    for token in required:
        if token not in s and token not in (dst / "gf_common.h").read_text():
            raise RuntimeError(f"Goodix donor ABI marker missing: {token}")
    if 'goodix,goodix-fp' in s:
        raise RuntimeError("stale non-stock Goodix compatible survived adaptation")
    c.write_text(s)

    # The recovered stock Kconfig says FPC1145, but the exact March kernel
    # binary has no fpc1020 implementation and does contain goodix_ree. Mirror
    # the produced factory binary without falsifying the archived stock config.
    top = kernel / "drivers/input/fingerprint/Makefile"
    m = top.read_text()
    m = replace_exact(
        m,
        'obj-$(CONFIG_FPC_FINGERPRINT) += fpc/',
        '# T20 factory binary override: FPC selected in config but not linked\n# obj-$(CONFIG_FPC_FINGERPRINT) += fpc/',
        "disable FPC binary mismatch",
    )
    if 'obj-y += goodix_ree/' not in m:
        m += '\n# T20 2019-03-12 factory binary parity\nobj-y += goodix_ree/\n'
    top.write_text(m)

    mk = dst / "Makefile"
    mk.write_text(
        'ccflags-y += -I$(srctree)/drivers/spi/mediatek/$(MTK_PLATFORM)\n'
        'ccflags-y += -I$(srctree)/drivers/misc/mediatek/include\n'
        'ccflags-y += -I$(srctree)/drivers/misc/mediatek/include/mt-plat\n'
        'ccflags-y += -I$(srctree)/drivers/misc/mediatek/include/mt-plat/$(MTK_PLATFORM)/include\n'
        'obj-y += gf_common.o gf_spi_access.o\n'
    )
    print(f"Goodix REE factory-parity donor integrated at {GOODIX_COMMIT}", flush=True)


HALL_SOURCE = r'''// Reconstructed from the exact T20 2019-03-12 kernel strings and DT ABI.
// This is not claimed to be the vendor's original source text.
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/of_irq.h>
#include <linux/gpio.h>
#include <linux/interrupt.h>
#include <linux/input.h>
#include <linux/pinctrl/consumer.h>
#include <linux/slab.h>

struct ln4913_data {
    struct device *dev;
    struct input_dev *input;
    struct pinctrl *pinctrl;
    struct pinctrl_state *irq_init;
    int gpio_irq;
    int irq;
    bool suspended;
};

static int ln4913_report(struct ln4913_data *d)
{
    int value = gpio_get_value(d->gpio_irq);
    dev_info(d->dev, "wisky_hall: g_is_suspend = %d, GPIO_HALL_INT_VALUE = %d\n",
             d->suspended ? 1 : 0, value);
    input_report_switch(d->input, SW_LID, !value);
    input_sync(d->input);
    return value;
}

static irqreturn_t ln4913_eint_func(int irq, void *cookie)
{
    struct ln4913_data *d = cookie;
    ln4913_report(d);
    return IRQ_HANDLED;
}

static int ln4913_pinctrl_init(struct platform_device *pdev, struct ln4913_data *d)
{
    d->pinctrl = devm_pinctrl_get(&pdev->dev);
    if (IS_ERR(d->pinctrl))
        return PTR_ERR(d->pinctrl);
    d->irq_init = pinctrl_lookup_state(d->pinctrl, "irq_init");
    if (IS_ERR(d->irq_init))
        return PTR_ERR(d->irq_init);
    return pinctrl_select_state(d->pinctrl, d->irq_init);
}

static int ln4913_gpio_init(struct platform_device *pdev, struct ln4913_data *d)
{
    u32 gpio;
    int ret = of_property_read_u32(pdev->dev.of_node, "gpio-irq", &gpio);
    if (ret)
        return ret;
    d->gpio_irq = (int)gpio;
    if (!gpio_is_valid(d->gpio_irq))
        return -EINVAL;
    ret = devm_gpio_request_one(&pdev->dev, d->gpio_irq, GPIOF_IN, "hall_eint");
    if (ret)
        return ret;
    return 0;
}

static int ln4913_setup_eint(struct platform_device *pdev, struct ln4913_data *d)
{
    struct device_node *eint;
    int ret;

    eint = of_find_compatible_node(NULL, NULL, "mediatek,irq_hall-eint");
    if (!eint) {
        dev_err(&pdev->dev, "%s : can not find hall eint compatible node\n", __func__);
        return -ENODEV;
    }
    d->irq = irq_of_parse_and_map(eint, 0);
    of_node_put(eint);
    if (d->irq <= 0) {
        dev_err(&pdev->dev, "[hall]EINT IRQ LINE NOT AVAILABLE\n");
        return -EINVAL;
    }

    ret = devm_request_threaded_irq(&pdev->dev, d->irq, NULL, ln4913_eint_func,
                                    IRQF_TRIGGER_RISING | IRQF_TRIGGER_FALLING | IRQF_ONESHOT,
                                    "hall_eint", d);
    if (ret)
        return ret;
    enable_irq_wake(d->irq);
    dev_info(&pdev->dev, "[hall]hall set EINT finished, hall_irq=%d\n", d->irq);
    return 0;
}

static int ln4913_probe(struct platform_device *pdev)
{
    struct ln4913_data *d;
    int ret;

    dev_info(&pdev->dev, "wisky_hall: enter\n");
    d = devm_kzalloc(&pdev->dev, sizeof(*d), GFP_KERNEL);
    if (!d)
        return -ENOMEM;
    d->dev = &pdev->dev;
    platform_set_drvdata(pdev, d);

    ret = ln4913_pinctrl_init(pdev, d);
    if (ret)
        return ret;
    ret = ln4913_gpio_init(pdev, d);
    if (ret)
        return ret;

    d->input = devm_input_allocate_device(&pdev->dev);
    if (!d->input)
        return -ENOMEM;
    d->input->name = "MechanicalHallEffectSwitch";
    d->input->phys = "ln4913/input0";
    input_set_capability(d->input, EV_SW, SW_LID);
    ret = input_register_device(d->input);
    if (ret) {
        dev_err(&pdev->dev, "hall sensor register input device failed (%d)\n", ret);
        return ret;
    }

    ret = ln4913_setup_eint(pdev, d);
    if (ret)
        return ret;
    dev_info(&pdev->dev, "[hall]hall_irq=%d\n", d->irq);
    ln4913_report(d);
    return 0;
}

static int ln4913_remove(struct platform_device *pdev)
{
    struct ln4913_data *d = platform_get_drvdata(pdev);
    if (d && d->irq > 0)
        disable_irq_wake(d->irq);
    return 0;
}

static int ln4913_suspend(struct platform_device *pdev, pm_message_t state)
{
    struct ln4913_data *d = platform_get_drvdata(pdev);
    if (d) {
        d->suspended = true;
        dev_info(&pdev->dev, "[ln4913] hall close\n");
    }
    return 0;
}

static int ln4913_resume(struct platform_device *pdev)
{
    struct ln4913_data *d = platform_get_drvdata(pdev);
    if (d) {
        d->suspended = false;
        dev_info(&pdev->dev, "[ln4913] hall open\n");
        ln4913_report(d);
    }
    return 0;
}

#ifdef CONFIG_OF
static const struct of_device_id hall_switch_of_match[] = {
    { .compatible = "mediatek,hall-gpio-int" },
    {},
};
MODULE_DEVICE_TABLE(of, hall_switch_of_match);
#endif

static struct platform_driver hall_driver = {
    .probe = ln4913_probe,
    .remove = ln4913_remove,
    .suspend = ln4913_suspend,
    .resume = ln4913_resume,
    .driver = {
        .name = "ln4913_Driver",
        .of_match_table = of_match_ptr(hall_switch_of_match),
    },
};

static int __init ln4913_mod_init(void)
{
    return platform_driver_register(&hall_driver);
}

static void __exit ln4913_mod_exit(void)
{
    platform_driver_unregister(&hall_driver);
}

module_init(ln4913_mod_init);
module_exit(ln4913_mod_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Teclast T20 LN4913 hall switch factory-ABI reconstruction");
'''


def integrate_hall(kernel: Path) -> None:
    sensors = kernel / "drivers/misc/mediatek/sensors-1.0"
    hall = sensors / "hall"
    leaf = hall / "ln4913"
    leaf.mkdir(parents=True, exist_ok=True)
    (leaf / "ln4913.c").write_text(HALL_SOURCE)
    (leaf / "Makefile").write_text("obj-y += ln4913.o\n")
    (hall / "Makefile").write_text("obj-y += ln4913/\n")

    top = sensors / "Makefile"
    s = top.read_text()
    line = 'obj-$(CONFIG_CUSTOM_KERNEL_HALL) += hall/'
    if line not in s:
        if not s.endswith("\n"):
            s += "\n"
        s += "# T20 vendor hall driver absent from the public MT6797 Android-8 tree\n" + line + "\n"
        top.write_text(s)

    print("LN4913 factory-DT ABI reconstruction integrated", flush=True)


def verify(kernel: Path) -> None:
    fp_mk = (kernel / "drivers/input/fingerprint/Makefile").read_text()
    if 'obj-y += goodix_ree/' not in fp_mk:
        raise RuntimeError("Goodix REE is not wired into the build")
    if '\nobj-$(CONFIG_FPC_FINGERPRINT) += fpc/' in "\n" + fp_mk:
        raise RuntimeError("FPC implementation still actively wired")

    goodix = (kernel / "drivers/input/fingerprint/goodix_ree/gf_common.c").read_text()
    for token in (
        'goodix,fingerprint', 'mediatek,goodix-fp', 'fingerprint_irq',
        'reset_high', 'reset_low', 'en_high', 'en_low',
        'Finger Print: Have not used Goodix, return',
    ):
        if token not in goodix:
            raise RuntimeError(f"integrated Goodix marker missing: {token}")
    if 'mt_vcorefs_manager.h' in goodix or 'goodix,goodix-fp' in goodix:
        raise RuntimeError("non-MT6797 Goodix donor residue survived adaptation")

    hall = (kernel / "drivers/misc/mediatek/sensors-1.0/hall/ln4913/ln4913.c").read_text()
    for token in ('mediatek,hall-gpio-int', 'mediatek,irq_hall-eint', 'ln4913_Driver', 'wisky_hall'):
        if token not in hall:
            raise RuntimeError(f"integrated hall marker missing: {token}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True, type=Path)
    args = ap.parse_args()
    kernel = args.kernel.resolve()
    integrate_goodix(kernel)
    integrate_hall(kernel)
    verify(kernel)
    print("T20 stock-kernel parity integration prepared", flush=True)


if __name__ == "__main__":
    main()
