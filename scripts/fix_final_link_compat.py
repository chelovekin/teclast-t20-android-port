#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: fix_final_link_compat.py <kernel-root>")

root = Path(sys.argv[1])

# RT5735's MT6797 fallback calls battery_disable_batfet().  In the public
# MT6797 tree that helper is supplied by bq25890.c and simply disables the
# charger's BATFET.  The T20 factory config selects BQ24296 instead, whose
# driver exposes the equivalent bq24296_set_batfet_disable().  Supply the same
# platform helper from the actually selected charger rather than pulling in a
# second, wrong charger driver just to satisfy the link.
bq = root / "drivers/misc/mediatek/power/mt6797/bq24296.c"
s = bq.read_text()

# The pinned MT8167 donor matches the BQ24296 register/I2C ABI but uses the
# generic TI OF spelling.  The exact T20 2019-03-12 ODM overlay instead enables
# sw_charger@6b with compatible="mediatek,sw_charger"; the factory kernel also
# carries that exact compatible and not "ti,bq24296".  Bind to the stock node
# so a code-only boot using the unmodified factory DTBO talks to address 0x6b.
old_compat = '{ .compatible = "ti,bq24296" }'
new_compat = '{ .compatible = "mediatek,sw_charger" }'
if old_compat in s:
    if s.count(old_compat) != 1:
        raise RuntimeError("unexpected BQ24296 donor OF compatible count")
    s = s.replace(old_compat, new_compat, 1)
elif new_compat not in s:
    raise RuntimeError("BQ24296 OF compatible not found")
if 'ti,bq24296' in s:
    raise RuntimeError("stale non-stock BQ24296 OF compatible remains")
if 'bq24296_i2c_id[]' not in s or '"bq24296", 0' not in s:
    raise RuntimeError("BQ24296 I2C id table no longer matches expected donor ABI")

if "void battery_disable_batfet(void)" not in s:
    anchor = "void bq24296_set_batfet_disable(unsigned int val)"
    pos = s.find(anchor)
    if pos < 0:
        raise RuntimeError("BQ24296 BATFET setter not found")

    # Insert the wrapper after the complete setter function.  Find its opening
    # brace and match braces so the edit is independent of whitespace/style.
    brace = s.find("{", pos)
    if brace < 0:
        raise RuntimeError("BQ24296 BATFET setter opening brace not found")
    depth = 0
    end = None
    for i in range(brace, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise RuntimeError("BQ24296 BATFET setter closing brace not found")

    wrapper = (
        "\n\n/* MT6797 RT5735 fallback: equivalent of the native BQ25890 helper. */\n"
        "void battery_disable_batfet(void)\n"
        "{\n"
        "\tbq24296_set_batfet_disable(1);\n"
        "\tpr_notice(\"battery_disable_batfet: BQ24296 BATFET disabled\\n\");\n"
        "}\n"
    )
    s = s[:end] + wrapper + s[end:]
else:
    if "bq24296_set_batfet_disable(1);" not in s:
        raise RuntimeError("existing battery_disable_batfet is not the expected BQ24296 wrapper")
bq.write_text(s)
print("BQ24296 now matches T20 sw_charger DT binding and provides battery_disable_batfet", flush=True)

# The LQ101 donor exported its suspend flag through an MT8176 hall-sensor
# driver.  That hall driver is not part of the T20 factory configuration; the
# LCM itself is the only selected consumer/producer in this build.  Keep the
# state inside the LCM instead of importing an unrelated MT8176 hall stack.
lcm = root / "drivers/misc/mediatek/lcm/lq101r1sx01a_wqxga_dsi_vdo/lq101r1sx01a_wqxga_dsi_vdo.c"
s = lcm.read_text()
old = "extern unsigned int g_is_suspend;"
new = "static unsigned int g_is_suspend;"
if old in s:
    if s.count(old) != 1:
        raise RuntimeError("unexpected LQ101 g_is_suspend declaration count")
    s = s.replace(old, new, 1)
elif new not in s:
    raise RuntimeError("LQ101 g_is_suspend declaration not found")
lcm.write_text(s)
print("LQ101 suspend state localized; MT8176 hall dependency removed", flush=True)
