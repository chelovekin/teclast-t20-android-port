#!/usr/bin/env python3
import argparse
import json
import struct
import sys
from pathlib import Path

ANDROID_MAGIC = b"ANDROID!"


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def u32le(data: bytes, off: int) -> int:
    if off + 4 > len(data):
        raise ValueError("short Android boot header")
    return struct.unpack_from("<I", data, off)[0]


def der_tlv(data: bytes, off: int) -> tuple[int, bytes, int]:
    if off >= len(data):
        raise ValueError("short DER object")
    tag = data[off]
    off += 1
    if off >= len(data):
        raise ValueError("short DER length")
    first = data[off]
    off += 1
    if first < 0x80:
        length = first
    else:
        count = first & 0x7F
        if count == 0 or count > 4 or off + count > len(data):
            raise ValueError("unsupported DER length")
        length = int.from_bytes(data[off:off + count], "big")
        off += count
    end = off + length
    if end > len(data):
        raise ValueError("DER object extends beyond input")
    return tag, data[off:end], end


def der_children(sequence: bytes) -> list[tuple[int, bytes]]:
    out = []
    off = 0
    while off < len(sequence):
        tag, value, end = der_tlv(sequence, off)
        out.append((tag, value))
        off = end
    if off != len(sequence):
        raise ValueError("malformed DER sequence")
    return out


def parse_boot_signature(trailer: bytes) -> dict | None:
    if not trailer:
        return None
    try:
        tag, body, end = der_tlv(trailer, 0)
        if tag != 0x30 or end != len(trailer):
            return None
        top = der_children(body)
        if len(top) != 5:
            return None
        if top[0][0] != 0x02 or int.from_bytes(top[0][1], "big") != 1:
            return None
        if top[3][0] != 0x30 or top[4][0] != 0x04:
            return None
        attrs = der_children(top[3][1])
        if len(attrs) != 2 or attrs[0][0] != 0x13 or attrs[1][0] != 0x02:
            return None
        target = attrs[0][1].decode("ascii", errors="strict")
        length = int.from_bytes(attrs[1][1], "big")
        return {"target": target, "signed_length": length, "signature_size": len(trailer)}
    except (ValueError, UnicodeDecodeError):
        return None


def payload_end(data: bytes) -> tuple[int, int]:
    if len(data) < 48 or data[:8] != ANDROID_MAGIC:
        raise ValueError("not a legacy Android boot image")
    kernel_size = u32le(data, 8)
    ramdisk_size = u32le(data, 16)
    second_size = u32le(data, 24)
    page_size = u32le(data, 36)
    if page_size < 512 or page_size > 65536 or page_size & (page_size - 1):
        raise ValueError(f"implausible page_size={page_size}")
    kernel_end = page_size + kernel_size
    ramdisk_off = align_up(kernel_end, page_size)
    ramdisk_end = ramdisk_off + ramdisk_size
    second_off = align_up(ramdisk_end, page_size)
    second_end = second_off + second_size
    end = align_up(second_end, page_size)
    if end > len(data):
        raise ValueError("boot payload extends beyond image")
    return end, page_size


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Strip a stale Android Verified Boot 1.0 DER BootSignature after a boot.img payload change."
    )
    ap.add_argument("input_boot", type=Path)
    ap.add_argument("output_boot", type=Path)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    data = args.input_boot.read_bytes()
    end, page_size = payload_end(data)
    trailer = data[end:]
    sig = parse_boot_signature(trailer)

    stripped = False
    reason = "no legacy BootSignature detected"
    out = data
    if sig is not None:
        if sig["target"] != "/boot":
            reason = f"DER BootSignature targets {sig['target']!r}; preserved"
        elif sig["signed_length"] != end:
            reason = (
                f"DER /boot signature length {sig['signed_length']} does not match "
                f"payload end {end}; preserved as unknown vendor trailer"
            )
        else:
            out = data[:end]
            stripped = True
            reason = "stale Android Verified Boot 1.0 /boot signature removed"

    args.output_boot.parent.mkdir(parents=True, exist_ok=True)
    args.output_boot.write_bytes(out)
    report = {
        "input_size": len(data),
        "output_size": len(out),
        "page_size": page_size,
        "payload_end": end,
        "trailer_size": len(trailer),
        "legacy_boot_signature": sig,
        "signature_stripped": stripped,
        "reason": reason,
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
