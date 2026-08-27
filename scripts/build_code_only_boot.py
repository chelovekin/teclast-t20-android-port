#!/usr/bin/env python3
"""Build and validate the T20 code-only boot candidate.

The new executable is Image.gz from a parity kernel build. The exact factory
base DTB, ramdisk, boot geometry and cmdline come from the supplied stock
2019-03-12 boot.img. The stale legacy AVB1 DER /boot signature is deliberately
omitted and the canonical legacy mkbootimg SHA-1 id is recomputed.
"""
import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

ANDROID_MAGIC = b"ANDROID!"
FDT_MAGIC = b"\xd0\x0d\xfe\xed"
ARM64_MAGIC = b"ARMd"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def align(value: int, size: int) -> int:
    return (value + size - 1) // size * size


def gunzip_exact(data: bytes) -> bytes:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = d.decompress(data) + d.flush()
    if not d.eof or d.unused_data:
        raise ValueError("Image.gz is not one exact gzip stream")
    return raw


def arm64_header(raw: bytes) -> dict:
    if len(raw) < 64 or raw[0x38:0x3c] != ARM64_MAGIC:
        raise ValueError("decompressed payload is not an ARM64 Linux Image")
    return {
        "text_offset": struct.unpack_from("<Q", raw, 8)[0],
        "image_size": struct.unpack_from("<Q", raw, 16)[0],
        "flags": struct.unpack_from("<Q", raw, 24)[0],
        "raw_bytes": len(raw),
    }


def boot_parts(data: bytes) -> dict:
    if len(data) < 608 or data[:8] != ANDROID_MAGIC:
        raise ValueError("not a legacy Android boot image")
    page = u32(data, 36)
    if page < 512 or page & (page - 1):
        raise ValueError(f"invalid page size: {page}")
    ks, rs, ss = u32(data, 8), u32(data, 16), u32(data, 24)
    ko = page
    ke = ko + ks
    ro = align(ke, page)
    re = ro + rs
    so = align(re, page)
    se = so + ss
    pe = align(se, page)
    if pe > len(data):
        raise ValueError("boot components extend past file")
    return {
        "page": page,
        "kernel_size": ks,
        "ramdisk_size": rs,
        "second_size": ss,
        "header": data[:page],
        "kernel": data[ko:ke],
        "ramdisk": data[ro:re],
        "second": data[so:se],
        "trailer": data[pe:],
    }


def split_stock_kernel(kernel: bytes) -> tuple[bytes, bytes]:
    hits = []
    pos = 0
    while True:
        pos = kernel.find(FDT_MAGIC, pos)
        if pos < 0:
            break
        if pos + 8 <= len(kernel):
            size = struct.unpack_from(">I", kernel, pos + 4)[0]
            if size >= 40 and pos + size == len(kernel):
                hits.append((pos, size))
        pos += 1
    if len(hits) != 1:
        raise ValueError(f"expected one final factory DTB, found {len(hits)}")
    off, size = hits[0]
    gz = kernel[:off]
    dtb = kernel[off:off + size]
    gunzip_exact(gz)
    return gz, dtb


def boot_id(kernel: bytes, ramdisk: bytes, second: bytes) -> bytes:
    h = hashlib.sha1()
    for blob in (kernel, ramdisk, second):
        h.update(blob)
        h.update(struct.pack("<I", len(blob)))
    return h.digest() + b"\0" * 12


def scatter_partition_size(path: Path, name: str = "boot") -> int:
    current = None
    for line in path.read_text(errors="replace").splitlines():
        text = line.strip()
        if text.startswith("partition_name:"):
            current = text.split(":", 1)[1].strip()
        elif current == name and text.startswith("partition_size:"):
            return int(text.split(":", 1)[1].strip(), 0)
    raise ValueError(f"partition not found in scatter: {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock-boot", required=True, type=Path)
    ap.add_argument("--scatter", required=True, type=Path)
    ap.add_argument("--image-gz", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--baseline-run", type=int)
    args = ap.parse_args()

    stock = args.stock_boot.read_bytes()
    new_gz = args.image_gz.read_bytes()
    old = boot_parts(stock)
    stock_gz, stock_dtb = split_stock_kernel(old["kernel"])
    stock_arm = arm64_header(gunzip_exact(stock_gz))
    new_arm = arm64_header(gunzip_exact(new_gz))
    if stock_arm["text_offset"] != new_arm["text_offset"]:
        raise ValueError("ARM64 text_offset changed")

    if old["header"][576:608] != boot_id(old["kernel"], old["ramdisk"], old["second"]):
        raise ValueError("factory boot does not use the expected canonical SHA-1 id")

    replacement = new_gz + stock_dtb
    header = bytearray(old["header"])
    struct.pack_into("<I", header, 8, len(replacement))
    header[576:608] = boot_id(replacement, old["ramdisk"], old["second"])

    output = bytearray(header)
    output += replacement
    output += b"\0" * (align(len(output), old["page"]) - len(output))
    output += old["ramdisk"]
    output += b"\0" * (align(len(output), old["page"]) - len(output))
    if old["second"]:
        output += old["second"]
        output += b"\0" * (align(len(output), old["page"]) - len(output))

    trailer = old["trailer"]
    der_ok = (len(trailer) >= 4 and trailer[:2] == b"0\x82" and
              int.from_bytes(trailer[2:4], "big") + 4 == len(trailer))
    if not der_ok:
        raise ValueError(f"unexpected factory trailer: {len(trailer)} bytes")

    partition_size = scatter_partition_size(args.scatter)
    if len(output) > partition_size:
        raise ValueError(f"boot image exceeds partition: {len(output)} > {partition_size}")

    # Independent round-trip invariants.
    new = boot_parts(bytes(output))
    if new["ramdisk"] != old["ramdisk"] or new["second"] != old["second"]:
        raise ValueError("factory ramdisk/second changed")
    ngz, ndtb = split_stock_kernel(new["kernel"])
    if ngz != new_gz or ndtb != stock_dtb:
        raise ValueError("code-only kernel composition mismatch")
    if new["trailer"]:
        raise ValueError("legacy signature/trailer survived")
    if new["header"][576:608] != boot_id(new["kernel"], new["ramdisk"], new["second"]):
        raise ValueError("output boot id mismatch")

    masked_stock = bytearray(old["header"])
    masked_new = bytearray(new["header"])
    masked_stock[8:12] = masked_new[8:12]
    masked_stock[576:608] = masked_new[576:608]
    if masked_stock != masked_new:
        raise ValueError("boot header changed outside kernel_size/id")

    kernel_addr = u32(stock, 12)
    ramdisk_addr = u32(stock, 20)
    image_end = kernel_addr + new_arm["image_size"]
    if image_end > ramdisk_addr:
        raise ValueError("decompressed Image overlaps ramdisk load range")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    report = {
        "result": "PASS",
        "baseline_run": args.baseline_run,
        "stock_boot_sha256": sha256(stock),
        "new_image_gz_sha256": sha256(new_gz),
        "factory_base_dtb_sha256": sha256(stock_dtb),
        "factory_ramdisk_sha256": sha256(old["ramdisk"]),
        "output_boot_sha256": sha256(output),
        "page_size": old["page"],
        "kernel_addr": f"0x{kernel_addr:x}",
        "ramdisk_addr": f"0x{ramdisk_addr:x}",
        "new_arm64_text_offset": f"0x{new_arm['text_offset']:x}",
        "new_arm64_image_size": f"0x{new_arm['image_size']:x}",
        "decompressed_image_end": f"0x{image_end:x}",
        "image_to_ramdisk_gap": ramdisk_addr - image_end,
        "output_size": len(output),
        "boot_partition_size": partition_size,
        "partition_free_bytes": partition_size - len(output),
        "removed_legacy_avb1_signature_bytes": len(trailer),
        "invariants": [
            "header identical except kernel_size and canonical boot id",
            "factory ramdisk byte-identical",
            "factory base DTB byte-identical",
            "new executable byte-identical to supplied Image.gz",
            "legacy AVB1 DER signature absent",
        ],
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, zlib.error) as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        raise SystemExit(2)
