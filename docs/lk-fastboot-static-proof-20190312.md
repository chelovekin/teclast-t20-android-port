# T20 T2E1 2019-03-12 LK: static fastboot boot proof

This note records facts recovered from the exact factory `lk.img` with SHA-256
`e9f49cea7039c8b3a4707dadbb0cb655a8083cb2380b1a24eece47c565adcf8f`.
It is intentionally based on the device binary rather than on a similar public LK tree.

## Image layout

The file begins with the MediaTek image wrapper (`0x58881688`) and a 0x200-byte
header. Early ARM code copies the LK body into its linked address range at
`0x46000000`. File offsets below refer to offsets in the exact `lk.img`.

## Fastboot command record

The function at file offset `0x27afc` allocates 0x18 bytes per command and stores:

- `+0x04`: command prefix pointer
- `+0x08`: prefix length
- `+0x0c`: security-enabled flag
- `+0x10`: forbidden-while-locked flag
- `+0x14`: handler pointer

The command loop begins at file offset `0x27d60`. For a matched command it reads
those two flags. When the lock gate is set, it calls the same routine used to
publish the fastboot `unlocked` variable; the handler is entered only when that
routine reports the device unlocked. The failure path contains the exact string
`not allowed in locked state` at file offset `0x54868`.

## `boot` is registered

The registration sequence at file offsets `0x281dc..0x281e8` resolves its prefix
to the exact string `boot` at file offset `0x54aa4` and passes:

- security-enabled flag: `1`
- forbidden-while-locked flag: `1`

The handler is loaded through the LK GOT. The GOT entry resolves to Thumb address
`0x46028871`, corresponding to the function beginning at file offset `0x28a70`.
That function is therefore the handler registered for the `boot` command.

## Exact `cmd_boot` preflight checks

The handler at file offset `0x28a70` copies the 0x260-byte legacy Android boot
header and rejects the image before jumping if any of the following is true:

- boot page size is zero;
- the aligned kernel/ramdisk payload is larger than the downloaded image;
- kernel and ramdisk ranges overlap;
- kernel load address is outside DRAM;
- kernel range overlaps LK;
- kernel range overlaps the fastboot download image;
- ramdisk load address is outside DRAM;
- ramdisk range overlaps LK;
- ramdisk range overlaps the fastboot download image.

The exact failure strings in this binary include `incomplete bootimage`,
`invalid kernel & ramdisk address: images overlap`,
`invalid kernel address: overlap with lk`,
`invalid kernel address: overlap with the download image`, and the corresponding
ramdisk failures.

## Factory state captured from the device

The stock runtime fingerprint captured for this device reports:

- `ro.boot.flash.locked=0`
- `ro.boot.verifiedbootstate=orange`

Thus the captured device state satisfies the lock gate used by the registered
`boot` command. If lock state is changed later, `fastboot getvar unlocked` is the
direct readback of the same LK state variable and must read `yes` before using the
command.

## First code-only boot image invariants

For the first kernel execution test the image must not use the rebuilt base DTB.
The factory `odmdtbo` contains many overlay fragments/fixups and is tied to the
factory base tree. The first image therefore uses:

1. the newly built `Image.gz` only;
2. the exact base DTB extracted from the end of the 2019-03-12 factory boot kernel;
3. the exact factory ramdisk;
4. the factory `odmdtbo` already present on the device.

For run #36 the decompressed ARM64 kernel has `text_offset=0x80000` and
`image_size=0x13a9000`. With the factory `kernel_addr=0x40080000`, its declared
load range ends at `0x41429000`. The factory ramdisk starts at `0x45000000`,
leaving 62,746,624 bytes between the two declared ranges. Both ranges are below
LK at `0x46000000` and therefore satisfy the address/overlap checks above.

This proves the fastboot command registration and all bootloader-level structural
preconditions that can be established before executing the new kernel. Runtime
kernel behavior is then a test of the built kernel itself, not an unknown LK,
header, DTB, DTBO, or fastboot path.
