# Final preflight — T20/T2E1 2019-03-12, kernel run #46

This note records the final static preflight against the exact factory binaries supplied for `T20(T2E1)-Android8.1.0_V1.00_20190312_zh-CN_gapps`.

## Exact LK verified-boot path

Factory `lk.img` SHA-256:

`e9f49cea7039c8b3a4707dadbb0cb655a8083cb2380b1a24eece47c565adcf8f`

The LK payload is linked at `0x46000000` after the 0x200-byte MediaTek image header.

The verified-boot state selector at `0x46002b44` uses state 0 as ORANGE. The command-line selector at `0x46002c8c` maps state 0 to `androidboot.verifiedbootstate=orange`.

The verification path starting at `0x46002ce8` initializes the state to 0 (ORANGE), obtains the device lock bit through the helper at `0x4601dcd0`, and at `0x46002d08` executes `CBNZ r0, 0x46002d1a`. Therefore verification is entered only when the returned lock bit is non-zero. When the bit is zero, LK keeps ORANGE and skips boot-signature verification.

The captured running Android state reports `ro.boot.flash.locked=0`, matching the unlocked branch.

## Exact fastboot boot registration

Factory LK registers the `boot` fastboot command at `0x46027fdc..0x46027fe8` through `fastboot_register` (`0x460278fc`) with arguments `r2=1`, `r3=1`. The registration object stores those flags at offsets `+0x0c` and `+0x10`, with the handler at `+0x14`. The dispatcher checks the corresponding security/lock restrictions before calling the handler. The supplied device state is unlocked.

The `boot` handler at `0x46028870` validates the Android boot header, total image size, page size, kernel/ramdisk ranges, DRAM placement, LK overlap and download-buffer overlap before handing off to the normal boot path.

## Run #46 parity result

Kernel baseline run #46 completed successfully with gates for:

- Goodix REE fingerprint
- LN4913 hall sensor
- factory BQ24296 `mediatek,sw_charger` binding
- factory `pin_ctrl` and external-amplifier GPIO path
- MT6797 SPI reserved-memory hook
- absence of FPC from the final linked kernel

The final hardware-compatible audit compared factory base-DTB + factory ODM overlay against the March stock kernel and run #46. Of 404 factory `compatible` strings, 215 are confirmed to be supported by the March stock kernel. Missing from run #46: **0**.

## Final boot-image invariants

The final code-only boot candidate uses:

- run #46 `Image.gz`
- byte-identical factory base DTB
- byte-identical factory ramdisk
- factory boot header/cmdline, changing only `kernel_size` and canonical boot ID
- no stale 1320-byte legacy AVB1 signature trailer
- unchanged factory `odmdtbo` on the device

Final `boot.img` SHA-256:

`ced28ab312a0d4c9d3d934806f58a36bd0e270a0d090e3f67f4c7ac5903d3203`

The image is 8,513,536 bytes against the 16,777,216-byte factory boot partition.

## Conclusion

No static boot-chain, layout, verified-boot, DT binding, or known T20 vendor-driver blocker remains for the run #46 code-only candidate. Physical execution on the MT6797 device is the remaining validation step.
