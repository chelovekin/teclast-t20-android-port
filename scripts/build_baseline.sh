#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/out"
WORK="${RUNNER_TEMP:-$ROOT/.work}/t20-kernel-baseline"
LOG="$OUT/build.log"

BASE_REPO="https://github.com/dguidipc/gemini-android-kernel-3.18-android8.git"
BASE_COMMIT="1a0acd5b806d370097fa0ce46fef0680ba27e4b7"
DONOR_REPO="https://github.com/Goayandi/android_kernel_mt8176_common.git"
DONOR_COMMIT="3979f3de3ac2308dbf455117aa5eaf23f28edc55"
CAMERA_REPO="https://github.com/WisniaPL/LeEco-Le1S-Kernel.git"
CAMERA_COMMIT="e03ab790982ed578e565ea43e07079108e13eeea"
TOOLCHAIN_REPO="https://github.com/LineageOS/android_prebuilts_gcc_linux-x86_aarch64_aarch64-linux-android-4.9.git"
TOOLCHAIN_COMMIT="7280ce2399316a5dbd8872e0bfe69435d8719230"

rm -rf "$OUT" "$WORK"
mkdir -p "$OUT" "$WORK"
exec > >(tee "$LOG") 2>&1

finish() {
  rc=$?
  {
    echo "result=$([[ $rc -eq 0 ]] && echo PASS || echo FAIL)"
    echo "exit_code=$rc"
    echo "base_commit=$BASE_COMMIT"
    echo "donor_commit=$DONOR_COMMIT"
    echo "camera_donor_commit=$CAMERA_COMMIT"
    echo "toolchain_commit=$TOOLCHAIN_COMMIT"
  } > "$OUT/BUILD_STATUS.txt"
}
trap finish EXIT

clone_at() {
  local url="$1" sha="$2" dst="$3"
  git init -q "$dst"
  git -C "$dst" remote add origin "$url"
  git -C "$dst" fetch -q --depth=1 origin "$sha"
  git -C "$dst" checkout -q --detach FETCH_HEAD
  test "$(git -C "$dst" rev-parse HEAD)" = "$sha"
}

echo "== fetch pinned sources =="
clone_at "$BASE_REPO" "$BASE_COMMIT" "$WORK/base"
clone_at "$DONOR_REPO" "$DONOR_COMMIT" "$WORK/donor"
clone_at "$CAMERA_REPO" "$CAMERA_COMMIT" "$WORK/camera-donor"
clone_at "$TOOLCHAIN_REPO" "$TOOLCHAIN_COMMIT" "$WORK/toolchain"

KERNEL="$WORK/base/kernel-3.18"
KOUT="$WORK/kout"
TOOLCHAIN="$WORK/toolchain"
mkdir -p "$KOUT"

grep -q '^VERSION = 3$' "$KERNEL/Makefile"
grep -q '^PATCHLEVEL = 18$' "$KERNEL/Makefile"
grep -q '^SUBLEVEL = 79$' "$KERNEL/Makefile"

echo "== integrate T20-only missing drivers =="
python3 "$ROOT/scripts/prepare_source.py" \
  --kernel "$KERNEL" \
  --donor "$WORK/donor" \
  --camera-donor "$WORK/camera-donor"

# prepare_source.py uses re.sub() to splice the MT6797 probe into the donor
# platform driver. Python's replacement-string parser consumes the C "\\n"
# escape in that generated printk and turns it into a literal newline. Repair
# that one generated string deterministically before compilation. This stays
# local to the generated donor copy; no compiler flags or warning policy change.
python3 - "$KERNEL/drivers/misc/mediatek/lcm/lq101r1sx01a_wqxga_dsi_vdo/lcm_drv_lq101r1sx01a_wqxga_dsi_vdo.c" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
broken = 'printk("[KE/LCM] gpio request GPIO_LCD_PWR_EN = 0x%x fail with %d\n",'
fixed = r'printk("[KE/LCM] gpio request GPIO_LCD_PWR_EN = 0x%x fail with %d\n",'
if broken not in s:
    raise SystemExit("expected generated broken LQ101 printk literal not found")
s = s.replace(broken, fixed, 1)
p.write_text(s)
print("LQ101 generated printk literal repaired", flush=True)
PY

# The pinned MT8176 MSA300 donor stores Chinese comments in a legacy codepage.
# Normalize that source copy to UTF-8 before the Python ABI adapter reads it.
# This changes comments only; C tokens in the driver are ASCII.
python3 - "$KERNEL/drivers/misc/mediatek/sensors-1.0/accelerometer/msa300/msa_cust.c" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
raw = p.read_bytes()
try:
    text = raw.decode("utf-8")
except UnicodeDecodeError:
    try:
        text = raw.decode("gb18030")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
p.write_text(text, encoding="utf-8")
print("MSA300 donor source normalized to UTF-8", flush=True)
PY

python3 "$ROOT/scripts/fix_s5k3l9_pdaf.py" \
  "$KERNEL/drivers/misc/mediatek/imgsensor/src/mt6797/s5k3l9_mipi_raw/s5k3l9otp.c"

# The pinned BQ24296 donor uses the older upmu_* PMIC accessor ABI.  MT6797's
# own Android-8 charging drivers use pmic_{get,set}_register_value() with the
# MT6351 register enum.  Translate only the eight donor calls that failed to
# compile, using the exact register names from the native MT6797 charging code.
python3 - "$KERNEL/drivers/misc/mediatek/power/mt6797/charging_hw_bq24296.c" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
replacements = {
    'upmu_set_rg_bc11_bb_ctrl(1);':
        'pmic_set_register_value(MT6351_PMIC_RG_BC11_BB_CTRL, 1);',
    'upmu_set_rg_bc11_rst(1);':
        'pmic_set_register_value(MT6351_PMIC_RG_BC11_RST, 1);',
    'upmu_set_rg_vcdt_hv_vth(register_value);':
        'pmic_set_register_value(MT6351_PMIC_RG_VCDT_HV_VTH, register_value);',
    'upmu_get_rgs_vcdt_hv_det()':
        'pmic_get_register_value(MT6351_PMIC_RGS_VCDT_HV_DET)',
    'upmu_set_baton_tdet_en(1);':
        'pmic_set_register_value(MT6351_PMIC_BATON_TDET_EN, 1);',
    'upmu_set_rg_baton_en(1);':
        'pmic_set_register_value(MT6351_PMIC_RG_BATON_EN, 1);',
    'upmu_get_rgs_baton_undet()':
        'pmic_get_register_value(MT6351_PMIC_RGS_BATON_UNDET)',
    'upmu_get_rgs_chrdet()':
        'pmic_get_register_value(MT6351_PMIC_RGS_CHRDET)',
}
for old, new in replacements.items():
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one BQ24296 PMIC call {old!r}, found {count}")
    s = s.replace(old, new, 1)
p.write_text(s)
print("BQ24296 adapted to native MT6797 MT6351 PMIC register API", flush=True)
PY

# Resolve the two final-link dependencies exposed after every T20 driver
# compiled: RT5735's BATFET fallback and the LQ101 donor's MT8176 hall flag.
python3 "$ROOT/scripts/fix_final_link_compat.py" "$KERNEL"

echo "== host compatibility patches for old MTK build tools =="
python3 -m lib2to3 -w -n "$KERNEL/tools/dct" > "$OUT/dct_2to3.log" 2>&1
python3 - "$KERNEL/tools/dct" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
compat = (
    "def cmp(a, b):\n"
    "    return (a > b) - (a < b)\n\n"
)
for p in root.rglob('*.py'):
    s = p.read_text(errors='surrogateescape')
    if 'cmp(' in s and 'def cmp(' not in s:
        p.write_text(compat + s, errors='surrogateescape')

# Restore Python-2 library behavior expected by MTK's DCT entrypoint before
# it imports the rest of the generator modules.
p = root / 'DrvGen.py'
s = p.read_text(errors='surrogateescape')
py2_compat = (
    "import string as _py2_string\n"
    "if not hasattr(_py2_string, 'atoi'):\n"
    "    _py2_string.atoi = lambda s, base=10: int(s, base)\n"
    "if not hasattr(_py2_string, 'atol'):\n"
    "    _py2_string.atol = lambda s, base=10: int(s, base)\n"
    "if not hasattr(_py2_string, 'atof'):\n"
    "    _py2_string.atof = float\n"
    "import configparser as _py2_configparser\n"
    "_py2_ConfigParser = _py2_configparser.ConfigParser\n"
    "def _compat_ConfigParser(*args, **kwargs):\n"
    "    kwargs.setdefault('strict', False)\n"
    "    return _py2_ConfigParser(*args, **kwargs)\n"
    "_py2_configparser.ConfigParser = _compat_ConfigParser\n\n"
)
if '_compat_ConfigParser' not in s:
    p.write_text(py2_compat + s, errors='surrogateescape')

# 2to3 wraps dict views with list(). EintData itself also names local values
# 'list', so those generated built-in calls become UnboundLocalError. Remove
# the unnecessary wrapping and rename the local in get_modeName.
p = root / 'data' / 'EintData.py'
s = p.read_text(errors='surrogateescape')
s = s.replace('for (key, value) in list(map.items()):',
              'for (key, value) in map.items():')
s = s.replace('if key in list(EintData._mode_map.keys()):',
              'if key in EintData._mode_map:')
s = s.replace('list =  EintData._mode_map[key]',
              'mode_list = EintData._mode_map[key]')
s = s.replace('if mode_idx < len(list) and mode_idx >= 0:',
              'if mode_idx < len(mode_list) and mode_idx >= 0:')
s = s.replace('return list[mode_idx]', 'return mode_list[mode_idx]')
p.write_text(s, errors='surrogateescape')
PY

# Linux 3.18's shipped DTC lexer defines yylloc as a tentative common symbol.
# Modern host GCC defaults to -fno-common, so leave the definition to parser.
sed -i 's/^YYLTYPE yylloc;$/extern YYLTYPE yylloc;/' \
  "$KERNEL/scripts/dtc/dtc-lexer.l" \
  "$KERNEL/scripts/dtc/dtc-lexer.lex.c_shipped"

# multiple_dtbo.py was written for Python 2, where text-mode file writes could
# carry raw byte strings. Under Python 3 the DTB must be handled explicitly as
# bytes or it is decoded as UTF-8 and fails on the first binary byte.
python3 - "$KERNEL/scripts/multiple_dtbo.py" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
s = s.replace("with open(output_file, 'w') as fo:",
              "with open(output_file, 'wb') as fo:")
s = s.replace('fo.write("%s" % item)', 'fo.write(item)')
s = s.replace("with open(input_file, 'r') as fi:",
              "with open(input_file, 'rb') as fi:")
p.write_text(s)
PY

echo "== reconstruct exact Android 8.1 factory config =="
bash "$ROOT/scripts/reconstruct_stock_config.sh" "$WORK/stock.config"
cp "$WORK/stock.config" "$OUT/stock.config"
cp "$WORK/stock.config" "$KOUT/.config"

export ARCH=arm64
export SUBARCH=arm64
export CROSS_COMPILE="$TOOLCHAIN/bin/aarch64-linux-android-"
export KBUILD_BUILD_USER=t20-ci
export KBUILD_BUILD_HOST=github

"${CROSS_COMPILE}gcc" --version | head -n 1
readelf -h "$KERNEL/drivers/input/touchscreen/mediatek/GSlX680/gsl_point_id" | grep -q 'Machine:.*AArch64'

echo "== resolve Kconfig against patched source =="
make -C "$KERNEL" O="$KOUT" python=python3 olddefconfig
cp "$KOUT/.config" "$OUT/resolved.config"

required=(
  'CONFIG_ARCH_MT6797=y'
  'CONFIG_MTK_PLATFORM="mt6797"'
  'CONFIG_ARCH_MTK_PROJECT="k97v1_64_bsp"'
  'CONFIG_BUILD_ARM64_APPENDED_DTB_IMAGE=y'
  'CONFIG_BUILD_ARM64_APPENDED_DTB_IMAGE_NAMES="mt6797"'
  'CONFIG_TOUCHSCREEN_MTK_GSlX680=y'
  'CONFIG_MTK_MSA300=y'
  'CONFIG_MTK_LTR303=y'
  'CONFIG_MTK_FINGERPRINT_SUPPORT=y'
  'CONFIG_MTK_FINGERPRINT_SELECT="FPC1145"'
  'CONFIG_FPC_FINGERPRINT=y'
  'CONFIG_MTK_GPU_VERSION="mali midgard r20p0"'
  'CONFIG_CUSTOM_KERNEL_LCM="lq101r1sx01a_wqxga_dsi_vdo"'
  'CONFIG_REGULATOR_RT5735=y'
  'CONFIG_MTK_BQ24296_SUPPORT=y'
)
for line in "${required[@]}"; do
  grep -Fqx "$line" "$KOUT/.config" || {
    echo "ERROR: required stock setting lost: $line"
    exit 20
  }
done

python3 - "$OUT/stock.config" "$OUT/resolved.config" > "$OUT/config_delta.txt" <<'PY'
import sys

def load(p):
    d = {}
    for raw in open(p, errors='replace'):
        s = raw.rstrip('\n')
        if s.startswith('CONFIG_') and '=' in s:
            k = s.split('=', 1)[0]
            d[k] = s
        elif s.startswith('# CONFIG_') and s.endswith(' is not set'):
            k = s.split()[1]
            d[k] = s
    return d

a = load(sys.argv[1])
b = load(sys.argv[2])
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f'{k}: {a.get(k, "<missing>")} -> {b.get(k, "<missing>")}')
PY

echo "== build Linux 3.18.79 T20 baseline =="
JOBS="$(nproc)"
[[ "$JOBS" -gt 4 ]] && JOBS=4
make -C "$KERNEL" O="$KOUT" python=python3 -j"$JOBS" Image.gz-dtb

IMAGE="$KOUT/arch/arm64/boot/Image.gz-dtb"
test -s "$IMAGE"
cp "$IMAGE" "$OUT/Image.gz-dtb"
cp "$KOUT/arch/arm64/boot/Image.gz" "$OUT/Image.gz"
cp "$KOUT/arch/arm64/boot/dts/mt6797.dtb" "$OUT/mt6797.dtb"
sha256sum "$OUT/Image.gz-dtb" "$OUT/Image.gz" "$OUT/mt6797.dtb" > "$OUT/SHA256SUMS"

strings "$OUT/Image.gz-dtb" | grep -Fq 'lq101r1sx01a_wqxga_dsi_vdo'
strings "$OUT/Image.gz-dtb" | grep -Fq 'mali midgard r20p0'

echo "BASELINE BUILD PASS"