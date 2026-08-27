#!/usr/bin/env python3
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


def u32le(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def gunzip_exact(data: bytes) -> bytes:
    dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = dec.decompress(data) + dec.flush()
    if not dec.eof or dec.unused_data:
        raise ValueError("gzip stream is incomplete or has trailing bytes")
    return raw


def arm64_header(raw: bytes) -> dict:
    if len(raw) < 64 or raw[0x38:0x3c] != ARM64_MAGIC:
        raise ValueError("decompressed payload is not an ARM64 Linux Image")
    return {
        "code0": f"0x{struct.unpack_from('<I', raw, 0)[0]:08x}",
        "text_offset": f"0x{struct.unpack_from('<Q', raw, 8)[0]:x}",
        "image_size": f"0x{struct.unpack_from('<Q', raw, 16)[0]:x}",
        "flags": f"0x{struct.unpack_from('<Q', raw, 24)[0]:x}",
        "decompressed_bytes": len(raw),
    }


def stock_kernel_from_boot(boot: bytes) -> bytes:
    if len(boot) < 48 or boot[:8] != ANDROID_MAGIC:
        raise ValueError("stock image is not a legacy Android boot image")
    page_size = u32le(boot, 36)
    kernel_size = u32le(boot, 8)
    if page_size < 512 or page_size & (page_size - 1):
        raise ValueError(f"invalid boot page size {page_size}")
    end = page_size + kernel_size
    if end > len(boot):
        raise ValueError("stock kernel extends past boot image")
    return boot[page_size:end]


def split_stock_kernel(kernel: bytes) -> tuple[bytes, bytes, int]:
    exact = []
    pos = 0
    while True:
        pos = kernel.find(FDT_MAGIC, pos)
        if pos < 0:
            break
        if pos + 8 <= len(kernel):
            total = struct.unpack_from(">I", kernel, pos + 4)[0]
            if total >= 40 and pos + total == len(kernel):
                exact.append((pos, total))
        pos += 1
    if len(exact) != 1:
        raise ValueError(f"expected exactly one final factory DTB, found {len(exact)}")
    off, total = exact[0]
    gzip_part = kernel[:off]
    dtb = kernel[off:off + total]
    gunzip_exact(gzip_part)
    return gzip_part, dtb, off


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build a first-boot kernel payload from a new Image.gz plus the exact DTB appended to stock boot.img."
    )
    ap.add_argument("stock_boot", type=Path)
    ap.add_argument("new_image_gz", type=Path)
    ap.add_argument("output_kernel", type=Path)
    ap.add_argument("--stock-dtb-out", type=Path)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    stock_boot = args.stock_boot.read_bytes()
    new_gz = args.new_image_gz.read_bytes()
    stock_kernel = stock_kernel_from_boot(stock_boot)
    stock_gz, stock_dtb, stock_dtb_off = split_stock_kernel(stock_kernel)

    stock_raw = gunzip_exact(stock_gz)
    new_raw = gunzip_exact(new_gz)
    stock_hdr = arm64_header(stock_raw)
    new_hdr = arm64_header(new_raw)
    if stock_hdr["text_offset"] != new_hdr["text_offset"]:
        raise ValueError(
            f"ARM64 text_offset changed: stock={stock_hdr['text_offset']} new={new_hdr['text_offset']}"
        )

    composite = new_gz + stock_dtb
    args.output_kernel.parent.mkdir(parents=True, exist_ok=True)
    args.output_kernel.write_bytes(composite)
    if args.stock_dtb_out:
        args.stock_dtb_out.parent.mkdir(parents=True, exist_ok=True)
        args.stock_dtb_out.write_bytes(stock_dtb)

    report = {
        "stock_boot_sha256": sha256(stock_boot),
        "stock_kernel_sha256": sha256(stock_kernel),
        "stock_image_gz_sha256": sha256(stock_gz),
        "stock_dtb_sha256": sha256(stock_dtb),
        "stock_dtb_offset_in_kernel": stock_dtb_off,
        "stock_dtb_size": len(stock_dtb),
        "new_image_gz_sha256": sha256(new_gz),
        "composite_kernel_sha256": sha256(composite),
        "stock_arm64_image": stock_hdr,
        "new_arm64_image": new_hdr,
        "invariant": "composite kernel is new Image.gz followed by byte-identical factory base DTB",
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
    except (OSError, ValueError, zlib.error) as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        raise SystemExit(2)
