r"""Show what Photo Organizer reads from a photo, and which date it would choose.

    python tools/inspect_exif.py IMG_0001.HEIC
    python tools/inspect_exif.py D:\photos\*.jpg

For every file it prints the detected container, the EXIF date tags, any warning, the date the program would
use with its default settings, and, for HEIC/HEIF, the item structure of the file (brands, items and where each
item is stored). Attach this output to a bug report when a photo is sorted into the wrong folder.
"""
import glob
import struct
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
import photo_organizer as org  # noqa: E402
from tools import environment  # noqa: E402

DEFAULTS = {"min_year": 1990, "reject_future": True, "use_filename_date": True,
            "use_modify_date": False, "use_mtime": True}


def container(path: Path) -> str:
    with path.open("rb") as f:
        head = f.read(12)
    if head[:2] == b"\xff\xd8":
        return "JPEG"
    if head[:8] == org.PNG_SIGNATURE:
        return "PNG"
    if head[:2] == b"BM":
        return "BMP"
    if head[4:8] == b"ftyp":
        return f"ISO base media file (ftyp brand {head[8:12]!r})"
    return "unrecognised"


def heif_structure(path: Path) -> list:
    """Human-readable lines describing the ftyp, items and item locations of a HEIC/HEIF file."""
    lines = []
    with path.open("rb") as f:
        data = f.read(8 * 1024 * 1024)  # the structure is at the start; image data further on is never needed
    file_size = path.stat().st_size
    pos = 0
    meta = None
    while pos + 8 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, pos)
        header = 8
        if size == 1 and pos + 16 <= len(data):
            size, header = struct.unpack_from(">Q", data, pos + 8)[0], 16
        elif size == 0:
            size = file_size - pos
        lines.append(f"  box {kind.decode('latin-1')!r:8} at {pos}, {size} bytes")
        if kind == b"ftyp":
            payload = data[pos + header:pos + size]
            brands = [payload[i:i + 4].decode("latin-1") for i in range(8, len(payload) - 3, 4)]
            lines.append(f"    major brand {payload[:4].decode('latin-1')!r}, compatible {brands}")
        if kind == b"meta":
            meta = data[pos + header:pos + size]
        if size < header:
            break
        pos += size
        if pos >= len(data):
            break  # the rest of the file is image data that was not read
    if meta is None:
        return lines + ["  (no meta box)"]
    parts = {kind: meta[start:end] for kind, start, end in org._iter_boxes(meta, 4)}
    lines.append("  meta children: " + ", ".join(sorted(k.decode("latin-1") for k in parts)))
    items = org._heif_items(parts[b"iinf"]) if b"iinf" in parts else []
    locations = org._heif_locations(parts[b"iloc"]) if b"iloc" in parts else {}
    if b"iloc" in parts:
        lines.append(f"  iloc version {parts[b'iloc'][0]}")
    for item_id, item_type in items:
        where = locations.get(item_id)
        lines.append(f"  item {item_id}: type {item_type.decode('latin-1')!r}, location {where}")
    return lines


def inspect(path: Path) -> bool:
    """Print the findings for one file. Returns False when the file cannot be read."""
    print(f"== {path}")
    try:
        kind = container(path)
        print(f"container : {kind}")
        tags, warning = org.read_exif_dates(path)
    except OSError as exc:
        print(f"cannot read: {exc}\n")
        return False
    if "ftyp" in kind:
        try:
            for line in heif_structure(path):
                print(line)
        except (org.ExifError, struct.error, KeyError) as exc:
            print(f"  (structure summary failed: {exc})")
    print("EXIF tags :", tags if tags else "none")
    if warning:
        print("warning   :", warning)
    choice = org.choose_date(path, tags, DEFAULTS, datetime.now())
    shown = org.format_recorded(choice.dt, choice.offset) if choice.dt else "no usable date"
    print(f"date used : {shown}   (source: {choice.source})")
    for note in choice.notes:
        print("note      :", note)
    print()
    return True


def main(argv) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    print(environment.one_line() + "\n")
    files = [Path(p) for pattern in argv for p in (glob.glob(pattern) or [pattern])]
    results = [inspect(path) for path in files]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
