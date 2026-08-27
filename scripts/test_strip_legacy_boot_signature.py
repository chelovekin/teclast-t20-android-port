#!/usr/bin/env python3
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PAGE = 2048


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def der(tag: int, value: bytes) -> bytes:
    n = len(value)
    if n < 0x80:
        length = bytes([n])
    elif n <= 0xFF:
        length = b"\x81" + bytes([n])
    else:
        length = b"\x82" + n.to_bytes(2, "big")
    return bytes([tag]) + length + value


def der_int(value: int) -> bytes:
    if value == 0:
        raw = b"\0"
    else:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        if raw[0] & 0x80:
            raw = b"\0" + raw
    return der(0x02, raw)


def boot_image(trailer: bytes) -> tuple[bytes, int]:
    kernel = b"K" * 3000
    ramdisk = b"R" * 1700
    header = bytearray(PAGE)
    header[:8] = b"ANDROID!"
    struct.pack_into("<I", header, 8, len(kernel))
    struct.pack_into("<I", header, 16, len(ramdisk))
    struct.pack_into("<I", header, 24, 0)
    struct.pack_into("<I", header, 36, PAGE)
    image = bytearray(header)
    image += kernel
    image += b"\0" * (align_up(len(image), PAGE) - len(image))
    image += ramdisk
    image += b"\0" * (align_up(len(image), PAGE) - len(image))
    payload_end = len(image)
    image += trailer
    return bytes(image), payload_end


def boot_signature(payload_end: int) -> bytes:
    attrs = der(0x30, der(0x13, b"/boot") + der_int(payload_end))
    body = der_int(1) + der(0x30, b"") + der(0x30, b"") + attrs + der(0x04, b"sig")
    return der(0x30, body)


class StripLegacyBootSignatureTest(unittest.TestCase):
    def run_tool(self, stock: bytes):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "in.img"
            dst = root / "out.img"
            report = root / "report.json"
            src.write_bytes(stock)
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("strip_legacy_boot_signature.py")),
                    str(src),
                    str(dst),
                    "--report",
                    str(report),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return dst.read_bytes(), json.loads(report.read_text())

    def test_strips_matching_boot_signature(self):
        unsigned, end = boot_image(b"")
        sig = boot_signature(end)
        signed = unsigned + sig
        out, report = self.run_tool(signed)
        self.assertEqual(out, unsigned)
        self.assertTrue(report["signature_stripped"])
        self.assertEqual(report["legacy_boot_signature"]["target"], "/boot")
        self.assertEqual(report["legacy_boot_signature"]["signed_length"], end)

    def test_preserves_unknown_vendor_trailer(self):
        stock, _end = boot_image(b"T20-VENDOR-TRAILER")
        out, report = self.run_tool(stock)
        self.assertEqual(out, stock)
        self.assertFalse(report["signature_stripped"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
