#!/usr/bin/env python3
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PAGE = 2048
ANDROID_MAGIC = b"ANDROID!"
MTK_MAGIC = 0x58881688
MTK_HEADER_SIZE = 512
BOOT_ID_OFFSET = 576
BOOT_ID_SIZE = 32


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def mkbootimg_id(kernel: bytes, ramdisk: bytes, second: bytes) -> bytes:
    h = hashlib.sha1()
    for blob in (kernel, ramdisk, second):
        h.update(blob)
        h.update(struct.pack("<I", len(blob)))
    return h.digest() + b"\0" * (BOOT_ID_SIZE - h.digest_size)


def make_stock_boot() -> tuple[bytes, bytes, bytes, bytes]:
    raw_stock_kernel = b"stock-kernel" * 173
    mtk = bytearray(MTK_HEADER_SIZE)
    struct.pack_into("<I", mtk, 0, MTK_MAGIC)
    struct.pack_into("<I", mtk, 4, len(raw_stock_kernel))
    mtk[8:14] = b"KERNEL"
    stock_kernel = bytes(mtk) + raw_stock_kernel

    ramdisk = b"RAMDISK" + bytes(range(256)) * 9
    second = b"SECOND-STAGE" * 37
    trailer = b"T20-STOCK-TRAILER" * 11

    header = bytearray(PAGE)
    header[:8] = ANDROID_MAGIC
    struct.pack_into("<I", header, 8, len(stock_kernel))
    struct.pack_into("<I", header, 12, 0x40080000)
    struct.pack_into("<I", header, 16, len(ramdisk))
    struct.pack_into("<I", header, 20, 0x44000000)
    struct.pack_into("<I", header, 24, len(second))
    struct.pack_into("<I", header, 28, 0x40F00000)
    struct.pack_into("<I", header, 32, 0x4E000000)
    struct.pack_into("<I", header, 36, PAGE)
    struct.pack_into("<I", header, 40, 0)
    struct.pack_into("<I", header, 44, 0)
    name = b"T20-stock\0"
    cmdline = b"console=tty0 androidboot.test=1\0"
    header[48:48 + len(name)] = name
    header[64:64 + len(cmdline)] = cmdline
    header[BOOT_ID_OFFSET:BOOT_ID_OFFSET + BOOT_ID_SIZE] = mkbootimg_id(
        stock_kernel, ramdisk, second
    )
    assert len(header) == PAGE

    image = bytearray(header)
    image += stock_kernel
    image += b"\0" * (align_up(len(image), PAGE) - len(image))
    image += ramdisk
    image += b"\0" * (align_up(len(image), PAGE) - len(image))
    image += second
    image += trailer
    return bytes(image), stock_kernel, ramdisk, second


class RepackStockBootTest(unittest.TestCase):
    def test_cli_preserves_payload_and_updates_canonical_id(self) -> None:
        stock, stock_kernel, ramdisk, second = make_stock_boot()
        new_kernel = b"new-Image.gz-dtb" * 409

        stock_kernel_size = struct.unpack_from("<I", stock, 8)[0]
        old_ramdisk_off = align_up(PAGE + stock_kernel_size, PAGE)
        old_tail = stock[old_ramdisk_off:]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stock_path = root / "boot-stock.img"
            kernel_path = root / "Image.gz-dtb"
            output_path = root / "boot.img"
            report_path = root / "report.json"
            scatter_path = root / "MT6797_Android_scatter.txt"

            stock_path.write_bytes(stock)
            kernel_path.write_bytes(new_kernel)
            scatter_path.write_text(
                "- partition_index: SYS8\n"
                "  partition_name: boot\n"
                "  file_name: boot.img\n"
                "  is_download: true\n"
                "  type: NORMAL_ROM\n"
                "  linear_start_addr: 0x0000000001d80000\n"
                "  physical_start_addr: 0x0000000001d80000\n"
                "  partition_size: 0x0000000002000000\n"
            )

            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("repack_stock_boot.py")),
                    str(stock_path),
                    str(kernel_path),
                    str(output_path),
                    "--scatter",
                    str(scatter_path),
                    "--report",
                    str(report_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            out = output_path.read_bytes()
            report = json.loads(report_path.read_text())

        packed_size = struct.unpack_from("<I", out, 8)[0]
        self.assertEqual(packed_size, MTK_HEADER_SIZE + len(new_kernel))
        new_ramdisk_off = align_up(PAGE + packed_size, PAGE)
        self.assertEqual(out[new_ramdisk_off:], old_tail)

        packed_kernel = out[PAGE:PAGE + packed_size]
        self.assertEqual(struct.unpack_from("<I", packed_kernel, 0)[0], MTK_MAGIC)
        self.assertEqual(struct.unpack_from("<I", packed_kernel, 4)[0], len(new_kernel))
        self.assertEqual(packed_kernel[8:MTK_HEADER_SIZE], stock_kernel[8:MTK_HEADER_SIZE])
        self.assertEqual(packed_kernel[MTK_HEADER_SIZE:], new_kernel)

        expected_header = bytearray(stock[:PAGE])
        struct.pack_into("<I", expected_header, 8, packed_size)
        expected_id = mkbootimg_id(packed_kernel, ramdisk, second)
        expected_header[BOOT_ID_OFFSET:BOOT_ID_OFFSET + BOOT_ID_SIZE] = expected_id
        self.assertEqual(out[:PAGE], bytes(expected_header))

        self.assertTrue(report["mtk_wrapper_preserved"])
        self.assertEqual(report["mtk_name"], "KERNEL")
        self.assertEqual(report["boot_id_mode"], "canonical_sha1")
        self.assertTrue(report["boot_id_recomputed"])
        self.assertEqual(report["output_boot_id_hex"], expected_id.hex())
        self.assertEqual(report["preserved_tail_sha256"], hashlib.sha256(old_tail).hexdigest())
        self.assertEqual(report["boot_partition_size"], 0x02000000)

    def test_cli_rejects_partition_overflow(self) -> None:
        stock, _stock_kernel, _ramdisk, _second = make_stock_boot()
        new_kernel = b"X" * 9000

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stock_path = root / "boot-stock.img"
            kernel_path = root / "Image.gz-dtb"
            output_path = root / "boot.img"
            scatter_path = root / "scatter.txt"
            stock_path.write_bytes(stock)
            kernel_path.write_bytes(new_kernel)
            scatter_path.write_text(
                "partition_name: boot\n"
                "partition_size: 0x00001000\n"
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("repack_stock_boot.py")),
                    str(stock_path),
                    str(kernel_path),
                    str(output_path),
                    "--scatter",
                    str(scatter_path),
                ],
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("too large", proc.stderr + proc.stdout)

    def test_cli_rejects_avb_footer(self) -> None:
        stock, _stock_kernel, _ramdisk, _second = make_stock_boot()
        footer = bytearray(64)
        footer[:4] = b"AVBf"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stock_path = root / "boot-stock.img"
            kernel_path = root / "Image.gz-dtb"
            output_path = root / "boot.img"
            stock_path.write_bytes(stock + footer)
            kernel_path.write_bytes(b"kernel")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("repack_stock_boot.py")),
                    str(stock_path),
                    str(kernel_path),
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("AVB footer detected", proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
