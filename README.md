# Teclast T20 (T2E1) Android port

Bring-up workspace for the Teclast T20 / T2E1 (MediaTek MT6797X), starting from the factory Android 8.1 Linux 3.18.79 kernel baseline.

## Current state

- Exact factory kernel configuration recovered from the T20 Android 8.1 `boot.img`.
- Linux 3.18.79 baseline builds to completion with the factory compiler reported by the stock kernel: Linaro GCC 6.3.1 20170109.
- T20-specific LQ101 panel, S5K3L9 camera/PDAF path, GSLX680 touch, MSA300 accelerometer, LTR303 ALS/PS and BQ24296 charging support are integrated into the MT6797 source baseline.
- CI produces `Image.gz-dtb`, `Image.gz`, `mt6797.dtb` and `odmdtbo.img` and validates the final `vmlinux`.
- `scripts/compose_kernel_with_stock_dtb.py` builds the first-test kernel payload as the new `Image.gz` plus the byte-identical base DTB extracted from the exact factory boot image. This keeps the factory base-DTB/ODM-overlay interface unchanged during the first kernel-code test.
- `scripts/repack_stock_boot.py` places that composite kernel into the exact stock boot image while preserving its Android boot header geometry and stock ramdisk and recomputing the canonical legacy boot ID when applicable.
- The exact 2019-03-12 stock `boot.img` carries a legacy Android Verified Boot 1.0 DER trailer. `scripts/strip_legacy_boot_signature.py` removes that now-invalid trailer from the unlocked/orange kernel-test image after repacking.
- Exact stock-image hashes are recorded in `stock/T20-T2E1-20190312.sha256`.
- The stock boot chain is documented in `docs/stock-boot-chain-20190312.md`.
- The exact factory LK fastboot command registration, lock gate and `cmd_boot` preflight path are documented from binary disassembly in `docs/lk-fastboot-static-proof-20190312.md`.

## First boot-image test

`.github/workflows/boot-repack.yml` is a manual, authenticated repack job. It downloads the latest successful factory-kernel artifact and accepts an exact stock `boot.img` over HTTPS only when its caller-supplied SHA-256 matches. A matching scatter file can also be supplied so the repacker refuses an image larger than the `boot` partition.

The resulting artifact contains the repacked `boot.img`, the extracted `factory-base.dtb`, SHA-256 sums, baseline provenance and composition/repack/signature reports. CI does not flash the tablet.

The first test changes only executable kernel code: use the rebuilt `Image.gz`, exact factory base DTB, exact factory ramdisk and the factory `odmdtbo` already on the device. Keep `odmdtbo`, `lk`, preloader, TEE and SCP partitions unchanged.

Static disassembly of the exact 2019-03-12 `lk.img` proves that the fastboot `boot` command is registered with the security and lock gates enabled, and that the captured device state is unlocked/orange. Therefore the non-destructive first execution path is `fastboot boot boot.img` while `getvar:unlocked` reports `yes`; this path does not write the boot partition.
