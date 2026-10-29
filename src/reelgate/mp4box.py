"""ISO/IEC 14496-12 MP4 top-level box scanner for moov/mdat faststart verification."""

from __future__ import annotations

from pathlib import Path
import struct


def scan_mp4_boxes(path: str | Path) -> list[tuple[str, int, int]]:
    """Return top-level ISO BMFF boxes as (fourcc, byte_offset, byte_size) tuples."""
    file_path = Path(path)
    total_size = file_path.stat().st_size
    boxes: list[tuple[str, int, int]] = []
    offset = 0

    with file_path.open("rb") as handle:
        while offset + 8 <= total_size:
            handle.seek(offset)
            header = handle.read(8)
            if len(header) < 8:
                break
            box_size, raw_type = struct.unpack(">I4s", header)
            box_type = raw_type.decode("latin-1", errors="replace")

            if box_size == 1:
                ext = handle.read(8)
                if len(ext) < 8:
                    break
                box_size = struct.unpack(">Q", ext)[0]
            elif box_size == 0:
                box_size = total_size - offset

            if box_size < 8 or offset + box_size > total_size:
                break

            boxes.append((box_type, offset, box_size))
            offset += box_size

    return boxes


def has_faststart_moov(path: str | Path) -> bool:
    """Return True when the MP4 file contains a moov box positioned before the first mdat box."""
    boxes = scan_mp4_boxes(path)
    moov_offset: int | None = None
    mdat_offset: int | None = None

    for box_type, offset, _ in boxes:
        if box_type == "moov" and moov_offset is None:
            moov_offset = offset
        elif box_type == "mdat" and mdat_offset is None:
            mdat_offset = offset

    if moov_offset is None or mdat_offset is None:
        return False
    return moov_offset < mdat_offset
