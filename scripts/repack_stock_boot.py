#!/usr/bin/env python3
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ANDROID_MAGIC = b"ANDROID!"
MTK_MAGIC = 0x58881688
MTK_HEADER_SIZE = 512
BOOT_ID_OFFSET = 576
BOOT_ID_SIZE = 32
AVB_FOOTER_SIZE = 64
AVB_FOOTER_MAGIC = b"AVBf"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def parse_u32le(buf: bytes, off: int) -> int:
    if off + 4 > len(buf):
        raise ValueError(f"short boot header at offset {off}")
    return struct.unpack_from("<I", buf, off)[0]


def mkbootimg_v0_id(kernel: bytes, ramdisk: bytes, second: bytes) -> bytes:
    """Return the 32-byte Android 8.1 mkbootimg id field."""
    h = hashlib.sha1()
    for blob in (kernel, ramdisk, second):
        h.update(blob)
        h.update(struct.pack("<I", len(blob)))
    return h.digest() + b"\0" * (BOOT_ID_SIZE - h.digest_size)


def decode_cstring(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def parse_boot_image(data: bytes) -> dict:
    if len(data) < 48 or data[:8] != ANDROID_MAGIC:
        raise ValueError("not a legacy Android boot image (ANDROID! magic missing)")

    if len(data) >= AVB_FOOTER_SIZE and data[-AVB_FOOTER_SIZE:-AVB_FOOTER_SIZE + 4] == AVB_FOOTER_MAGIC:
        raise ValueError("AVB footer detected; refusing to preserve an invalidated boot signature")

    kernel_size = parse_u32le(data, 8)
    kernel_addr = parse_u32le(data, 12)
    ramdisk_size = parse_u32le(data, 16)
    ramdisk_addr = parse_u32le(data, 20)
    second_size = parse_u32le(data, 24)
    second_addr = parse_u32le(data, 28)
    tags_addr = parse_u32le(data, 32)
    page_size = parse_u32le(data, 36)
    unused = parse_u32le(data, 40)
    os_version = parse_u32le(data, 44)

    if page_size < 512 or page_size > 65536 or page_size & (page_size - 1):
        raise ValueError(f"implausible page_size={page_size}")
    if len(data) < page_size:
        raise ValueError("boot image shorter than one header page")

    kernel_off = page_size
    kernel_end = kernel_off + kernel_size
    ramdisk_off = align_up(kernel_end, page_size)
    ramdisk_end = ramdisk_off + ramdisk_size
    second_off = align_up(ramdisk_end, page_size)
    second_end = second_off + second_size

    if kernel_end > len(data):
        raise ValueError("kernel extends beyond boot image")
    if ramdisk_end > len(data):
        raise ValueError("ramdisk extends beyond boot image")
    if second_end > len(data):
        raise ValueError("second stage extends beyond boot image")

    header_page = data[:page_size]
    kernel = data[kernel_off:kernel_end]
    ramdisk = data[ramdisk_off:ramdisk_end]
    second = data[second_off:second_end]

    stored_id = None
    canonical_id = None
    id_mode = "unavailable"
    if page_size >= BOOT_ID_OFFSET + BOOT_ID_SIZE:
        stored_id = header_page[BOOT_ID_OFFSET:BOOT_ID_OFFSET + BOOT_ID_SIZE]
        canonical_id = mkbootimg_v0_id(kernel, ramdisk, second)
        if stored_id == canonical_id:
            id_mode = "canonical_sha1"
        elif stored_id == b"\0" * BOOT_ID_SIZE:
            id_mode = "zero"
        else:
            id_mode = "vendor_or_unknown"

    board = decode_cstring(header_page[48:64]) if page_size >= 64 else ""
    cmdline = decode_cstring(header_page[64:min(576, page_size)]) if page_size > 64 else ""
    if page_size > 608 and b"\0" not in header_page[64:min(576, page_size)]:
        extra = decode_cstring(header_page[608:min(1632, page_size)])
        cmdline += extra

    return {
        "kernel_size": kernel_size,
        "kernel_addr": kernel_addr,
        "ramdisk_size": ramdisk_size,
        "ramdisk_addr": ramdisk_addr,
        "second_size": second_size,
        "second_addr": second_addr,
        "tags_addr": tags_addr,
        "page_size": page_size,
        "unused": unused,
        "os_version": os_version,
        "kernel_off": kernel_off,
        "kernel_end": kernel_end,
        "ramdisk_off": ramdisk_off,
        "ramdisk_end": ramdisk_end,
        "second_off": second_off,
        "second_end": second_end,
        "kernel": kernel,
        "ramdisk": ramdisk,
        "second": second,
        "header_page": header_page,
        "tail": data[ramdisk_off:],
        "board": board,
        "cmdline": cmdline,
        "stored_id": stored_id,
        "canonical_id": canonical_id,
        "id_mode": id_mode,
    }


def wrap_kernel_like_stock(stock_kernel: bytes, new_kernel: bytes) -> tuple[bytes, dict]:
    info = {"mtk_wrapper_preserved": False, "mtk_name": None}
    if len(stock_kernel) >= MTK_HEADER_SIZE:
        magic = struct.unpack_from("<I", stock_kernel, 0)[0]
        if magic == MTK_MAGIC:
            header = bytearray(stock_kernel[:MTK_HEADER_SIZE])
            struct.pack_into("<I", header, 4, len(new_kernel))
            raw_name = bytes(header[8:40]).split(b"\0", 1)[0]
            info["mtk_wrapper_preserved"] = True
            info["mtk_name"] = raw_name.decode("ascii", errors="replace")
            return bytes(header) + new_kernel, info
    return new_kernel, info


def scatter_partition_size(path: Path, partition_name: str) -> int | None:
    current = None
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("partition_name:"):
            current = line.split(":", 1)[1].strip()
        elif current == partition_name and line.startswith("partition_size:"):
            return int(line.split(":", 1)[1].strip(), 0)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Replace only the kernel payload in an Android 8.1-era legacy boot.img "
            "while preserving stock boot parameters, ramdisk, second stage and trailing data."
        )
    )
    ap.add_argument("stock_boot", type=Path)
    ap.add_argument("new_kernel", type=Path, help="raw Image.gz-dtb produced by the T20 kernel build")
    ap.add_argument("output_boot", type=Path)
    ap.add_argument("--scatter", type=Path, help="optional MTK scatter file used to enforce boot partition size")
    ap.add_argument("--partition-name", default="boot")
    ap.add_argument("--report", type=Path, help="optional JSON report path")
    args = ap.parse_args()

    stock = args.stock_boot.read_bytes()
    new_raw = args.new_kernel.read_bytes()
    if not new_raw:
        raise SystemExit("new kernel is empty")

    meta = parse_boot_image(stock)
    replacement, wrap_info = wrap_kernel_like_stock(meta["kernel"], new_raw)

    header = bytearray(meta["header_page"])
    struct.pack_into("<I", header, 8, len(replacement))

    boot_id_recomputed = False
    if meta["id_mode"] == "canonical_sha1":
        new_id = mkbootimg_v0_id(replacement, meta["ramdisk"], meta["second"])
        header[BOOT_ID_OFFSET:BOOT_ID_OFFSET + BOOT_ID_SIZE] = new_id
        boot_id_recomputed = True

    out = bytearray(header)
    out += replacement
    out += b"\0" * (align_up(len(out), meta["page_size"]) - len(out))
    new_ramdisk_off = len(out)
    out += meta["tail"]

    partition_size = None
    if args.scatter:
        partition_size = scatter_partition_size(args.scatter, args.partition_name)
        if partition_size is None:
            raise SystemExit(f"partition {args.partition_name!r} not found in {args.scatter}")
        if len(out) > partition_size:
            raise SystemExit(
                f"repacked boot image is too large: {len(out)} > partition size {partition_size}"
            )

    if bytes(out[new_ramdisk_off:]) != meta["tail"]:
        raise SystemExit("internal error: non-kernel boot payload changed")

    args.output_boot.parent.mkdir(parents=True, exist_ok=True)
    args.output_boot.write_bytes(out)

    output_id = None
    if meta["stored_id"] is not None:
        output_id = bytes(header[BOOT_ID_OFFSET:BOOT_ID_OFFSET + BOOT_ID_SIZE])

    report = {
        "stock_boot": str(args.stock_boot),
        "new_kernel": str(args.new_kernel),
        "output_boot": str(args.output_boot),
        "board": meta["board"],
        "cmdline": meta["cmdline"],
        "page_size": meta["page_size"],
        "kernel_addr": meta["kernel_addr"],
        "ramdisk_addr": meta["ramdisk_addr"],
        "second_addr": meta["second_addr"],
        "tags_addr": meta["tags_addr"],
        "os_version_raw": meta["os_version"],
        "legacy_unused_raw": meta["unused"],
        "stock_kernel_size": meta["kernel_size"],
        "raw_new_kernel_size": len(new_raw),
        "packed_new_kernel_size": len(replacement),
        "ramdisk_size": meta["ramdisk_size"],
        "second_size": meta["second_size"],
        "stock_ramdisk_offset": meta["ramdisk_off"],
        "new_ramdisk_offset": new_ramdisk_off,
        "stock_boot_size": len(stock),
        "output_boot_size": len(out),
        "boot_partition_size": partition_size,
        "boot_id_mode": meta["id_mode"],
        "boot_id_recomputed": boot_id_recomputed,
        "stock_boot_id_hex": meta["stored_id"].hex() if meta["stored_id"] is not None else None,
        "output_boot_id_hex": output_id.hex() if output_id is not None else None,
        "stock_boot_sha256": sha256(stock),
        "raw_new_kernel_sha256": sha256(new_raw),
        "output_boot_sha256": sha256(out),
        "preserved_tail_sha256": sha256(meta["tail"]),
        **wrap_info,
    }

    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
