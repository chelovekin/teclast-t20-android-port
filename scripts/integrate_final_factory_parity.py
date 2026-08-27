#!/usr/bin/env python3
import argparse
from pathlib import Path


PIN_CTRL_SOURCE = r'''// Functional reconstruction from the exact T20 2019-03-12 ARM64 Image and factory DT.
// This is not claimed to be the vendor's original source text.
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/of_gpio.h>
#include <linux/gpio.h>
#include <linux/device.h>

static int gpio_spk_en;
static struct platform_driver pin_ctrl_driver;

void gpio_spk_en_set(unsigned int value)
{
	gpio_direction_output(gpio_spk_en, value);
	gpio_set_value(gpio_spk_en, value);
}

static ssize_t pin_ctrl_show(struct device_driver *driver, char *buf)
{
	return sprintf(buf, "%d", 0);
}

static ssize_t pin_ctrl_store(struct device_driver *driver,
			      const char *buf, size_t count)
{
	if (buf[0] == '1')
		pr_notice("gezi_pinctrl .................................................\n");
	return count;
}

static DRIVER_ATTR(pin_ctrl, 0644, pin_ctrl_show, pin_ctrl_store);

static int pin_ctrl_probe(struct platform_device *pdev)
{
	int ret;

	pr_notice("gezi pin_ctrl_probe start............\n");
	gpio_spk_en = of_get_named_gpio(pdev->dev.of_node, "gpio_spk_en", 0);
	pr_notice("gezi pin_ctrl_probe start....gpio_spk_en = %d........\n", gpio_spk_en);
	ret = gpio_request(gpio_spk_en, "gpio_spk_en");
	pr_notice("gezi [FAN] gpio request gpio_spk_en = 0x%x fail with %d\n",
		  gpio_spk_en, ret);
	driver_create_file(&pin_ctrl_driver.driver, &driver_attr_pin_ctrl);
	pr_notice("gezi %s------------------ok!\n", __func__);
	return 0;
}

static int pin_ctrl_remove(struct platform_device *pdev)
{
	return 0;
}

static int pin_ctrl_suspend(struct platform_device *pdev, pm_message_t state)
{
	pr_notice("gezi pin_ctrl_suspend....\n");
	return 0;
}

static int pin_ctrl_resume(struct platform_device *pdev)
{
	pr_notice("gezi pin_ctrl_resume....\n");
	return 0;
}

#ifdef CONFIG_OF
static const struct of_device_id pin_ctrl_of_match[] = {
	{ .compatible = "mediatek,pin_ctrl" },
	{},
};
MODULE_DEVICE_TABLE(of, pin_ctrl_of_match);
#endif

static struct platform_driver pin_ctrl_driver = {
	.probe = pin_ctrl_probe,
	.remove = pin_ctrl_remove,
	.suspend = pin_ctrl_suspend,
	.resume = pin_ctrl_resume,
	.driver = {
		.name = "pin_ctrl",
		.of_match_table = of_match_ptr(pin_ctrl_of_match),
	},
};

static int __init pin_ctrl_init(void)
{
	int ret = platform_driver_register(&pin_ctrl_driver);
	if (ret)
		pr_notice("[pin_ctrl_init]platform_driver_register error:(%d)\n", ret);
	else
		pr_notice("[pin_ctrl_init]platform_driver_register done!\n");
	return ret;
}

static void __exit pin_ctrl_exit(void)
{
	platform_driver_unregister(&pin_ctrl_driver);
}

module_init(pin_ctrl_init);
module_exit(pin_ctrl_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Teclast T20 factory speaker-enable GPIO reconstruction");
'''


STOCK_EXTAMP = r'''int AudDrv_GPIO_EXTAMP_Select(int bEnable, int mode)
{
	int i;

	pr_warn("gezi AudDrv_GPIO_EXTAMP_Select bEnable = %d,mode = %d\n",
		bEnable, mode);
	if (bEnable) {
		for (i = 0; i < mode; i++) {
			udelay(2);
			gpio_spk_en_set(0);
			udelay(2);
			gpio_spk_en_set(1);
		}
	} else {
		gpio_spk_en_set(0);
	}
	return 0;
}
'''


def replace_function(text: str, signature: str, replacement: str) -> str:
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"function signature not found: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"opening brace not found: {signature}")
    depth = 0
    end = None
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise RuntimeError(f"closing brace not found: {signature}")
    return text[:start] + replacement.rstrip() + text[end:]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True, type=Path)
    args = ap.parse_args()
    k = args.kernel.resolve()

    # Exact factory DT contains a 0x16000 no-map reservation with this compatible.
    # Public MT6797 spi-dev.c already contains the same RESERVEDMEM_OF_DECLARE but
    # compiles it out behind its factory/4G-test switch. The March Image contains
    # reserve_memory_spi_fn and the compatible, so enable that existing block.
    spi = k / "drivers/spi/mediatek/mt6797/spi-dev.c"
    s = spi.read_text()
    old = "#define USE_SPI1_4GB_TEST (0)"
    new = "#define USE_SPI1_4GB_TEST (1)"
    if s.count(old) != 1:
        raise RuntimeError(f"expected one MT6797 SPI reserved-memory gate, found {s.count(old)}")
    spi.write_text(s.replace(old, new, 1))

    # Reconstruct the vendor-only pin_ctrl platform driver from the exact stock
    # machine code and DT ABI: compatible mediatek,pin_ctrl; gpio_spk_en property;
    # probe requests the GPIO; gpio_spk_en_set() performs direction_output then
    # gpio_set_value; suspend/resume only log; driver sysfs attribute is 0644.
    leaf = k / "drivers/misc/mediatek/pin_ctrl"
    leaf.mkdir(parents=True, exist_ok=True)
    (leaf / "pin_ctrl.c").write_text(PIN_CTRL_SOURCE)
    (leaf / "Makefile").write_text("obj-y += pin_ctrl.o\n")
    m = k / "drivers/misc/mediatek/Makefile"
    ms = m.read_text()
    if "obj-y += pin_ctrl/" not in ms:
        if not ms.endswith("\n"):
            ms += "\n"
        ms += "\n# T20 2019-03-12 vendor speaker-enable platform driver\nobj-y += pin_ctrl/\n"
        m.write_text(ms)

    # Stock AudDrv_GPIO_EXTAMP_Select has three direct calls to gpio_spk_en_set:
    # enable pulses low/high `mode` times with 2-us delays, disable drives low.
    aud = k / "sound/soc/mediatek/mt6797/AudDrv_Gpio.c"
    a = aud.read_text()
    if "extern void gpio_spk_en_set(unsigned int value);" not in a:
        anchor = '#include "AudDrv_Gpio.h"\n'
        if a.count(anchor) != 1:
            raise RuntimeError("AudDrv_Gpio.h include anchor not unique")
        a = a.replace(anchor, anchor + "extern void gpio_spk_en_set(unsigned int value);\n", 1)
    a = replace_function(a, "int AudDrv_GPIO_EXTAMP_Select(int bEnable, int mode)", STOCK_EXTAMP)
    aud.write_text(a)

    # Deterministic integration assertions.
    checks = {
        spi: ("#define USE_SPI1_4GB_TEST (1)", "mediatek,spi-reserve-memory", "reserve_memory_spi_fn"),
        leaf / "pin_ctrl.c": ("mediatek,pin_ctrl", "gpio_spk_en", "gpio_spk_en_set", "DRIVER_ATTR(pin_ctrl, 0644"),
        aud: ("gezi AudDrv_GPIO_EXTAMP_Select", "gpio_spk_en_set(0)", "gpio_spk_en_set(1)"),
    }
    for path, tokens in checks.items():
        data = path.read_text()
        for token in tokens:
            if token not in data:
                raise RuntimeError(f"final factory-parity marker missing in {path}: {token}")

    print("T20 final factory parity integrated: pin_ctrl/audio EXTAMP + SPI reserved-memory", flush=True)


if __name__ == "__main__":
    main()
