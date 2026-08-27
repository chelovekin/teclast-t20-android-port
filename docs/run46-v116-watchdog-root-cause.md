# run46 temporary-boot result on V1.16

## Observed device state

The device used for the first `fastboot boot` test was not on the March 2019 Android 8.1 factory stack. It was running the older V1.16 Android 7.1.1 stack:

- Android: 7.1.1
- kernel: Linux 3.18.41+ (`#11 Fri Aug 24 14:57:08 CST 2018`)
- verified boot: unlocked/orange

## run46 result

`fastboot boot boot.img` accepted the image and transferred control to run46. Persistent RAM-console output proves run46 reached MT6797 SPM/VcoreFS init at about 0.18 s. The next boot reported `wdt_by_pass_pwk`, so the temporary kernel stalled early and the hardware watchdog reset the tablet. The installed V1.16 boot image was then loaded normally.

The final persistent run46 lines were:

```
[VcoreFS] LPM: 0x1, HPM: 0x2, ULTRA: 0x4
[VcoreFS] dram_khz: 1600000, vcorefs_fw_mode: 0x1
[VcoreFS] SPM_SW_RSV_5: 0xff7fffff, dramc shuf addr: ..., val: 0x1
```

## Root cause

The test mixed two incompatible DT delivery schemes.

The V1.16 boot image contains a complete board DTB appended to its kernel. A property-by-property comparison between that embedded DTB and the live `/proc/device-tree` capture produced 2547 exact matches out of 2561 static properties (>99.4%). The small differences are runtime/bootloader data such as model suffix, bootargs, RAM ranges and SCP status. This establishes that the V1.16 boot chain passes the embedded full board DT directly.

The March 2019 Android 8.1 boot image is different: its appended DTB is only the factory base DTB and the board-specific changes are supplied by the separate `odmdtbo` partition. run46 deliberately preserved that March base DTB because it was built for the March 8.1 boot chain.

Therefore booting run46 under the installed V1.16 boot chain passed only the March base DTB without the required March ODM overlay. The temporary test did not reproduce the target Android 8.1 boot environment.

This is also why the failure must not be attributed to the SPM source line immediately following the last log message: AArch64 disassembly of that SPM/VcoreFS block is instruction-equivalent between the exact March factory kernel and run46, and V1.16 executes the same infracfg_ao `+0x230` RMW successfully.

## Required test environment

A run46 Android-8.1 candidate is valid only after the device has a coherent March-2019 Android-8.1 stack, including at minimum the matching LK, SCP, TEE, ODM DTBO, vendor and system partitions. A boot image alone cannot convert the installed Android 7.1.1 userspace to Android 8.1.

Do not use `Format All + Download`. Preserve NVRAM/protect/calibration partitions. Preloader is not required for the first migration attempt and should remain untouched unless a separately justified need is established.
