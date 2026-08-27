# Teclast T20 (T2E1) Android port

Bring-up workspace for the Teclast T20 / T2E1 (MediaTek MT6797X), starting from the factory Android 8.1 Linux 3.18.79 kernel baseline.

## Current state

- Exact factory kernel configuration recovered from the T20 Android 8.1 `boot.img`.
- Linux 3.18.79 baseline builds to completion with the factory compiler reported by the stock kernel: Linaro GCC 6.3.1 20170109.
- T20-specific LQ101 panel, S5K3L9 camera/PDAF path, GSLX680 touch, MSA300 accelerometer, LTR303 ALS/PS and BQ24296 charging support are integrated into the MT6797 source baseline.
- CI produces `Image.gz-dtb`, `Image.gz`, `mt6797.dtb` and `odmdtbo.img` and validates the final `vmlinux`.
- `scripts/repack_stock_boot.py` replaces only the kernel payload in the exact stock boot image while preserving its Android boot header geometry and stock ramdisk.
- The exact 2019-03-12 stock `boot.img` carries a legacy Android Verified Boot 1.0 DER trailer. `scripts/strip_legacy_boot_signature.py` removes that now-invalid trailer from an unlocked/orange kernel-test image after repacking.
- Exact stock-image hashes are recorded in `stock/T20-T2E1-20190312.sha256`.
- The stock boot chain and first-test constraints are documented in `docs/stock-boot-chain-20190312.md`.

## First boot-image test

`.github/workflows/boot-repack.yml` is a manual, authenticated repack job. It downloads the latest successful factory-kernel artifact and accepts an exact stock `boot.img` over HTTPS only when its caller-supplied SHA-256 matches. A matching scatter file can also be supplied so the repacker refuses an image larger than the `boot` partition.

The resulting artifact contains only the repacked `boot.img`, SHA-256 sums, baseline provenance and repack/signature reports. CI does not flash the tablet.

For the first device test, keep the factory `odmdtbo`, `lk`, preloader, TEE and SCP unchanged. Change only `boot.img`. The preferred first attempt is a temporary fastboot boot on the already-unlocked device; write the `boot` partition only if the device LK does not support temporary boot or after the test image has successfully reached Android.
