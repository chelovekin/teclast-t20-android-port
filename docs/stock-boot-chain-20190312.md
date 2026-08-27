# Stock boot chain: T20(T2E1) Android 8.1 V1.00 2019-03-12

This note records facts extracted from the exact factory images for `T20(T2E1)-Android8.1.0_V1.00_20190312_zh-CN_gapps`. The stock binaries themselves are not stored in the repository; their SHA-256 values are recorded in `stock/T20-T2E1-20190312.sha256`.

## Partition layout

The matching MT6797 scatter identifies project `k97v1_64_bsp` on eMMC. Relevant partitions are:

- `lk` and `lk2`: 0x80000 bytes each.
- `boot`: 0x1000000 bytes (16 MiB), start 0x0b100000.
- `odmdtbo`: 0x1000000 bytes (16 MiB), start 0x0c900000.
- `tee1` and `tee2`: 0x500000 bytes each.
- `scp1` and `scp2`: 0x100000 bytes each.
- `recovery`: 0x1000000 bytes (16 MiB).

## boot.img and recovery.img

Both images use the legacy Android boot image format with:

- page size: 2048 bytes
- kernel address: `0x40080000`
- ramdisk address: `0x45000000`
- tags address: `0x44000000`
- second stage size: 0
- command line: `bootopt=64S3,32N2,64N2 buildvariant=user`
- raw OS-version field: `0x10040127`

The stock boot kernel size is 7,382,867 bytes. The recovery image contains exactly the same kernel payload:

`SHA-256 8bbaf015fa5f7552018c9a95bf4f5c2ae6bd3fcd9181fa53653d0248bcc5ed67`

Only the ramdisk differs. This independently confirms the boot header geometry used by the test-image repacker.

The aligned stock `boot.img` payload is followed by a 1,320-byte DER Android Verified Boot 1.0 signature. The aligned stock `recovery.img` payload is followed by a 1,324-byte DER signature. Both signatures embed the same Android test-style X.509 identity (`CN=Android`, organization `Android`) and use `sha1WithRSAEncryption`. A kernel replacement invalidates the `/boot` signature, so the repacker strips the stale legacy signature for the unlocked-device bring-up image rather than preserving invalid metadata.

## Runtime lock state

The captured factory runtime properties report:

- `ro.boot.flash.locked=0`
- `ro.boot.verifiedbootstate=orange`
- `ro.secure=1`
- `ro.debuggable=0`

This is the expected unlocked/orange bring-up state. It is not an engineering Android userspace build.

## lk.img

`lk.img` is MediaTek-wrapped:

- MTK magic: `0x58881688`
- wrapper size: 512 bytes
- payload name: `lk`
- payload size: 397,408 bytes
- total image size: 397,920 bytes

The exact LK binary contains fastboot command strings for `flash:`, `erase:`, `continue`, `reboot`, `reboot-bootloader`, `download:`, `oem unlock`, `oem lock`, `flashing unlock`, `flashing lock` and `flashing get_unlock_ability`.

It also contains the verified-boot state paths `orange`, `yellow`, `red`, and `green`, including `androidboot.verifiedbootstate=orange`, plus code-path strings for legacy verified-boot signature parsing and image authentication. LK explicitly loads overlay DTBO and reports failure with `load overlay dtbo failed !`.

The binary also contains the fastboot `boot` path. MediaTek LK source from the same command family registers `boot` for an unlocked secure device, so a temporary `fastboot boot boot.img` attempt is preferred before writing the `boot` partition. Device behaviour still has to be confirmed at runtime; if LK rejects the command, the fallback is to flash only `boot` while retaining the exact stock image for immediate restoration.

## preloader

The preloader is 190,400 bytes and identifies the same MTK security/download framework. Strings show Download Agent verification, image-authentication policy, SECRO/seccfg handling, lock-state policy and emergency download paths. These observations are a reason not to modify or replace the preloader during kernel bring-up.

## tee.img

`tee.img` is MediaTek-wrapped:

- MTK magic: `0x58881688`
- wrapper size: 512 bytes
- payload name: `atf`
- payload size: 97,792 bytes
- total image size: 98,304 bytes

The payload is ARM Trusted Firmware/BL31 and contains the EL3-to-kernel handoff path. It is not part of the first kernel test and must remain stock.

## scp.img

`scp.img` contains two MediaTek-wrapped payloads:

1. offset `0x0000`: `tinysys-loader-CM4_A`, payload size 1,024 bytes
2. offset `0x0600`: `tinysys-scp-CM4_A`, payload size 37,444 bytes

The SCP firmware includes FreeRTOS and MediaTek DVFS/SCP code. LK contains an explicit SCP verification path. SCP remains stock for initial kernel bring-up.

## First-test rule

For the first boot test change exactly one component: `boot.img`.

Keep stock `odmdtbo`, `lk`, `preloader`, `tee`, `scp`, `recovery`, modem firmware, `vendor` and `system` unchanged. The generated `odmdtbo.img` from the source build is intentionally not part of the first test because changing kernel and overlay data at the same time would make failures ambiguous.
