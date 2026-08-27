#!/usr/bin/env python3
import gzip
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compose_kernel_with_stock_dtb.py"


def align_up(v, a):
    return (v + a - 1) // a * a


def arm64_image(size=4096, image_size=0x200000):
    b = bytearray(size)
    struct.pack_into("<I", b, 0, 0x14000010)
    struct.pack_into("<Q", b, 8, 0x80000)
    struct.pack_into("<Q", b, 16, image_size)
    b[0x38:0x3c] = b"ARMd"
    return bytes(b)


def tiny_fdt():
    # A structurally bounded FDT header is sufficient here: the composer only
    # proves that the exact final DTB blob is preserved, not DT semantics.
    total = 40
    return struct.pack(">10I", 0xD00DFEED, total, 40, 40, 40, 17, 16, 0, 0, 0)


def mkboot(kernel, ramdisk=b"factory-ramdisk"):
    page = 2048
    h = bytearray(page)
    h[:8] = b"ANDROID!"
    struct.pack_into("<I", h, 8, len(kernel))
    struct.pack_into("<I", h, 12, 0x40080000)
    struct.pack_into("<I", h, 16, len(ramdisk))
    struct.pack_into("<I", h, 20, 0x45000000)
    struct.pack_into("<I", h, 24, 0)
    struct.pack_into("<I", h, 28, 0x40F00000)
    struct.pack_into("<I", h, 32, 0x44000000)
    struct.pack_into("<I", h, 36, page)
    out = h + kernel
    out += b"\0" * (align_up(len(out), page) - len(out))
    out += ramdisk
    return bytes(out)


def main():
    stock_gz = gzip.compress(arm64_image(), mtime=0)
    stock_dtb = tiny_fdt()
    stock_boot = mkboot(stock_gz + stock_dtb)
    new_gz = gzip.compress(arm64_image(size=8192, image_size=0x201000), mtime=0)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "stock.img").write_bytes(stock_boot)
        (td / "new.gz").write_bytes(new_gz)
        subprocess.run([
            sys.executable, str(SCRIPT), str(td / "stock.img"), str(td / "new.gz"),
            str(td / "kernel"), "--stock-dtb-out", str(td / "factory.dtb"),
            "--report", str(td / "report.json")
        ], check=True, stdout=subprocess.DEVNULL)
        assert (td / "kernel").read_bytes() == new_gz + stock_dtb
        assert (td / "factory.dtb").read_bytes() == stock_dtb
        report = json.loads((td / "report.json").read_text())
        assert report["stock_dtb_sha256"] == hashlib.sha256(stock_dtb).hexdigest()
        assert report["new_arm64_image"]["text_offset"] == "0x80000"

        # Reject a stock kernel without a final FDT.
        (td / "bad.img").write_bytes(mkboot(stock_gz))
        bad = subprocess.run([
            sys.executable, str(SCRIPT), str(td / "bad.img"), str(td / "new.gz"), str(td / "bad-out")
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert bad.returncode != 0

    print("compose_kernel_with_stock_dtb: PASS")


if __name__ == "__main__":
    main()
