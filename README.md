# Teclast T20 (T2E1) Android port

Bring-up workspace for the Teclast T20 / T2E1 (MediaTek MT6797X), starting from the factory Android 8.1 Linux 3.18.79 kernel baseline.

## Current state

- Exact factory kernel configuration recovered from the T20 Android 8.1 `boot.img`.
- Linux 3.18.79 baseline builds to completion with the factory compiler reported by the stock kernel: Linaro GCC 6.3.1 20170109.
- T20-specific LQ101 panel, S5K3L9 camera/PDAF path, GSLX680 touch, MSA300 accelerometer, LTR303 ALS/PS and BQ24296 charging support are integrated into the MT6797 source baseline.
- CI produces `Image.gz-dtb`, `Image.gz`, `mt6797.dtb` and `odmdtbo.img` and validates the final `vmlinux`.
- `scripts/repack_stock_boot.py` can replace only the kernel payload in the exact stock boot image while preserving the stock header page, ramdisk, second stage and trailing data. If the stock kernel carries the MediaTek 512-byte `mkimage` header, that wrapper is retained and its payload size is updated.

## First boot-image test

`.github/workflows/boot-repack.yml` is a manual, authenticated repack job. It downloads the latest successful factory-kernel artifact and accepts an exact stock `boot.img` over HTTPS only when its caller-supplied SHA-256 matches. A matching scatter file can also be supplied so the repacker refuses an image larger than the `boot` partition.

The resulting artifact contains the repacked `boot.img`, the built `odmdtbo.img`, SHA-256 sums and a JSON repack report. CI does not flash the tablet.
