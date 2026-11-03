#!/usr/bin/env python3
"""Sort photos into date folders. Pure Python standard library, Python >= 3.9.

Supported file types in this version: .jpg, .jpeg, .png, .bmp, .heic, .heif (no videos).

REQUIREMENTS: none. This version needs NO third-party packages and no external
programs (no ExifTool, no pip install). If a future version adds formats that
need an extra library (for example video or RAW support), that library and its "pip install"
line will be listed in README.md under "Requirements".

Examples:
    python photo_organizer.py --config config.ini
    python photo_organizer.py --config config.ini --dry-run

The program never overwrites existing files and starts no other programs.
"""
from __future__ import annotations

import argparse
import configparser
import csv
import hashlib
import os
import re
import shutil
import stat
import struct
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

__version__ = "1.1.0"
__created__ = "2026-11-03 10:43:20"  # UTC; when this version was made (written by tools/release.py)



def version_string() -> str:
    """'0.4.0 (created 2026-10-31 09:56:49 UTC)': the version and the moment it was made."""
    return f"{__version__} (created {__created__} UTC)"


SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".heic", ".heif")
MOVIE_EXTENSIONS = (".mp4", ".mov")  # only handled when handle_movies = yes
MOVIE_HINT = " Movies (.mp4, .mov) are switched on with handle_movies = yes, not through extensions."
STRUCTURES = {
    "YYYY": "%Y",
    "YYYY_MM": "%Y_%m",
    "YYYY/MM": "%Y/%m",
    "YYYY/YYYY-MM": "%Y/%Y-%m",
    "YYYY/MM/DD": "%Y/%m/%d",
}
TIMEZONE_MODES = ("wallclock", "local", "utc")
DUPLICATE_POLICIES = ("skip_identical", "rename")
FIELDS = ["source", "destination", "date_source", "date_recorded", "date_used", "action", "status", "details"]
UNKNOWN_FIELDS = ["path", "extension", "size_bytes"]

TEMP_PREFIX = ".photo-organizer-"
CHUNK = 1024 * 1024
MAX_EXIF_BYTES = 16 * 1024 * 1024
MAX_META_BYTES = 8 * 1024 * 1024  # a real HEIC 'meta' box is a few kilobytes
MAX_ILOC_WORK = 200_000  # items plus extents examined in one 'iloc' box
MAX_JPEG_SEGMENTS = 1024  # EXIF sits in the first few segments of a real JPEG
MAX_PNG_CHUNKS = 100_000
# ISO base media "ftyp" brands that identify HEIF/HEIC still images
HEIF_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"})
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
INVALID_NAME_CHARS = set('<>:"/\\|?*') | {chr(i) for i in range(32)}

SRC_ORIGINAL = "exif_datetime_original"
SRC_DIGITIZED = "exif_datetime_digitized"
SRC_FILENAME = "filename"
SRC_MODIFIED = "exif_datetime_modified"
SRC_MTIME = "filesystem_mtime"
SRC_UNKNOWN = "unknown"
CAPTURE_SOURCES = {SRC_ORIGINAL, SRC_DIGITIZED}  # may change timestamps

IS_WINDOWS = os.name == "nt"
WINDOWS_MAX_PATH = 259  # characters in a path, without the long-path setting
FILETIME_UNIX_EPOCH = 116444736000000000  # 100 ns ticks between 1601-01-01 and 1970-01-01

EXIF_DATE_RE = re.compile(
    r"^(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$"
)
OFFSET_RE = re.compile(r"^(?:(Z)|([+-])(\d{2}):?(\d{2}))$")
# 2019-07-04, 2019_07_04, 20190704 ... optionally followed by a time (HHMMSS with
# optional separators). Digits directly around the match are rejected so long
# numbers (e.g. millisecond timestamps) are not misread as dates.
FILENAME_DATE_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_.]?(\d{2})[-_.]?(\d{2})"
    r"(?:(?:[-_. T]|\sat\s)?(\d{2})[-_.:]?(\d{2})[-_.:]?(\d{2}))?(?!\d)"
)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
def yesno(value: str, name: str = "value") -> bool:
    normalized = value.strip().lower()
    if normalized in ("yes", "true", "1", "on"):
        return True
    if normalized in ("no", "false", "0", "off"):
        return False
    raise ValueError(f"{name}: expected yes or no, got {value!r}")


def path_from_config(value: str, base: Path) -> Path:
    candidate = Path(os.path.expandvars(os.path.expanduser(value)))
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def validate_rename_pattern(pattern: str) -> None:
    """Fail early if the rename pattern can never produce a valid file name."""
    if not pattern:
        return
    try:
        sample = datetime(2019, 7, 4, 15, 30, 12).strftime(pattern)
    except ValueError as exc:
        raise ValueError(f"rename_by_date: unsupported date directive in {pattern!r} ({exc})") from exc
    sample = sample.replace("{original}", "IMG_0001")
    if any(ch in INVALID_NAME_CHARS for ch in sample):
        raise ValueError(f"rename_by_date: {pattern!r} produces characters not allowed in file names")
    if not sample.strip(" ."):
        raise ValueError(f"rename_by_date: {pattern!r} produces an empty file name")


def read_config(file: Path) -> dict:
    parser = configparser.ConfigParser(interpolation=None)
    if not file.is_file() or not parser.read(file, encoding="utf-8"):
        raise ValueError(f"Config file not found: {file} (copy config.example.ini to config.ini and edit it)")
    get = parser.get
    base = file.resolve().parent

    def flag(section: str, key: str, fallback: str) -> bool:
        return yesno(get(section, key, fallback=fallback), f"[{section}] {key}")

    def whole_number(section: str, key: str, fallback: str) -> int:
        text = get(section, key, fallback=fallback)
        try:
            return int(text)
        except ValueError:
            raise ValueError(f"[{section}] {key}: expected a whole number, got {text!r}") from None

    extensions = set()
    for raw in get("behavior", "extensions", fallback=",".join(SUPPORTED_EXTENSIONS)).split(","):
        ext = raw.strip().lower()
        if ext:
            extensions.add(ext if ext.startswith(".") else "." + ext)
    unsupported = sorted(extensions - set(SUPPORTED_EXTENSIONS))
    if unsupported:
        raise ValueError(
            f"Unsupported extension(s) in config: {', '.join(unsupported)}. "
            f"This version supports only: {', '.join(SUPPORTED_EXTENSIONS)}."
            + (MOVIE_HINT if set(unsupported) & set(MOVIE_EXTENSIONS) else "")
        )
    if not extensions:
        raise ValueError("extensions must list at least one of: " + ", ".join(SUPPORTED_EXTENSIONS))

    # the reports go into one folder (relative to config.ini); report_csv and unknown_files_csv are names inside it
    reports_dir = path_from_config(get("behavior", "reports_folder", fallback="./reports"), base)

    c = {
        "input": path_from_config(get("folders", "input_folder"), base),
        "output": path_from_config(get("folders", "output_folder"), base),
        "structure": get("organization", "output_folderstructure", fallback="YYYY_MM").strip(),
        "dry_run": flag("organization", "testrun", "yes"),
        "copy": flag("organization", "copy_mode", "yes"),
        "change_timestamp": flag("organization", "change_timestamp", "no"),
        "set_creation_time": flag("organization", "set_creation_time", "no"),
        "verify": flag("organization", "verify", "yes"),
        "rename_pattern": get("organization", "rename_by_date", fallback="").strip(),
        "cleanup": flag("organization", "cleanup_empty_folders", "no"),
        "unknown_folder": get("organization", "unknown_date_folder", fallback="unknown_date").strip(),
        "handle_movies": flag("organization", "handle_movies", "no"),
        "movies_folder": get("organization", "movies_folder", fallback="movies").strip(),
        "use_filename_date": flag("dates", "use_filename_date", "yes"),
        "use_modify_date": flag("dates", "use_exif_modify_date", "no"),
        "use_mtime": flag("dates", "use_filesystem_mtime", "yes"),
        "tz_mode": get("dates", "timezone_mode", fallback="wallclock").strip().lower(),
        "min_year": whole_number("dates", "min_year", "1990"),
        "reject_future": flag("dates", "reject_future_dates", "yes"),
        "recursive": flag("behavior", "recursive", "yes"),
        "duplicates": get("behavior", "duplicate_policy", fallback="skip_identical").strip().lower(),
        "skip_hidden": flag("behavior", "skip_hidden", "yes"),
        "extensions": extensions,
        "reports_dir": reports_dir,
        "report": path_from_config(get("behavior", "report_csv", fallback="organizer_report.csv"), reports_dir),
        "report_skipped": flag("behavior", "report_skipped", "yes"),
        "unknown_csv": path_from_config(get("behavior", "unknown_files_csv", fallback="unknown_files.csv"), reports_dir),
    }

    if c["structure"] not in STRUCTURES:
        raise ValueError(f"output_folderstructure must be one of: {', '.join(STRUCTURES)}")
    if c["duplicates"] not in DUPLICATE_POLICIES:
        raise ValueError(f"duplicate_policy must be one of: {', '.join(DUPLICATE_POLICIES)}")
    if c["tz_mode"] not in TIMEZONE_MODES:
        raise ValueError(f"timezone_mode must be one of: {', '.join(TIMEZONE_MODES)}")
    if not 1900 <= c["min_year"] <= 2100:
        raise ValueError("min_year must be between 1900 and 2100")
    for option, key in (("unknown_date_folder", "unknown_folder"), ("movies_folder", "movies_folder")):
        name = c[key]
        if not name or name in (".", "..") or any(ch in INVALID_NAME_CHARS for ch in name):
            raise ValueError(f"{option} must be a simple folder name (no slashes)")
    if c["handle_movies"]:
        c["extensions"] = c["extensions"] | set(MOVIE_EXTENSIONS)  # movies are scanned, hashed and de-duplicated like photos
    validate_rename_pattern(c["rename_pattern"])
    if c["set_creation_time"] and not c["change_timestamp"]:
        raise ValueError("set_creation_time = yes requires change_timestamp = yes")
    if not c["copy"] and not c["verify"]:
        raise ValueError("verify must be yes when copy_mode is no (a move is never done unverified)")

    if not c["input"].is_dir():
        raise ValueError(f"Input folder does not exist: {c['input']}")
    for a, b in ((c["input"], c["output"]), (c["output"], c["input"])):
        if a == b or a.is_relative_to(b):
            raise ValueError("Input and output folders must be separate and not nested.")
    for key, option in (("report", "report_csv"), ("unknown_csv", "unknown_files_csv")):
        if c[key].is_relative_to(c["input"]):
            raise ValueError(f"{option} ({c[key]}) must not be inside the input folder, it would be scanned. "
                             "Check reports_folder: a relative folder is relative to config.ini.")
    if c["report"] == c["unknown_csv"]:
        raise ValueError("report_csv and unknown_files_csv must be different files.")
    return c


# --------------------------------------------------------------------------
# Reading EXIF dates (JPEG and PNG) with the standard library only
# --------------------------------------------------------------------------
class ExifError(Exception):
    """Malformed metadata. Never fatal: the file just falls through to the next date source."""


def _tiff_from_jpeg(f) -> bytes | None:
    f.seek(2)  # after SOI
    for _ in range(MAX_JPEG_SEGMENTS):
        prefix = f.read(1)
        if not prefix:
            return None
        if prefix != b"\xff":
            raise ExifError("corrupt JPEG marker structure")
        marker = f.read(1)
        while marker == b"\xff":  # fill bytes
            marker = f.read(1)
        if not marker:
            return None
        code = marker[0]
        if code == 0x01 or 0xD0 <= code <= 0xD8:  # standalone markers
            continue
        if code in (0xD9, 0xDA):  # EOI / start of scan: no more metadata
            return None
        raw_length = f.read(2)
        if len(raw_length) < 2:
            return None
        length = struct.unpack(">H", raw_length)[0]
        if length < 2:
            raise ExifError("corrupt JPEG segment length")
        if code == 0xE1:  # APP1 (Exif or XMP)
            data = f.read(length - 2)
            if len(data) < length - 2:
                raise ExifError("truncated APP1 segment")
            if data.startswith(b"Exif\x00\x00"):
                return data[6:]
        else:
            f.seek(length - 2, 1)
    raise ExifError("too many segments before the image data")


def _tiff_from_png(f) -> bytes | None:
    f.seek(8)
    for _ in range(MAX_PNG_CHUNKS):
        header = f.read(8)
        if len(header) < 8:
            return None
        length, chunk_type = struct.unpack(">I4s", header)
        if chunk_type == b"eXIf":
            if length > MAX_EXIF_BYTES:
                raise ExifError("eXIf chunk too large")
            data = f.read(length)
            if len(data) < length:
                raise ExifError("truncated eXIf chunk")
            return data[6:] if data.startswith(b"Exif\x00\x00") else data
        if chunk_type == b"IEND":
            return None
        f.seek(length + 4, 1)  # chunk data + CRC
    raise ExifError("too many chunks")


def _uint(data: bytes, pos: int, size: int) -> int:
    """Big-endian unsigned integer of `size` bytes; size 0 means the field is absent (value 0)."""
    if size == 0:
        return 0
    if pos < 0 or pos + size > len(data):
        raise ExifError("truncated HEIF box")
    return int.from_bytes(data[pos:pos + size], "big")


def _iter_boxes(data: bytes, start: int = 0):
    """Yield (box type, payload start, payload end) for the boxes in data[start:]."""
    pos, end = start, len(data)
    while pos + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, pos)
        header = 8
        if size == 1:  # 64-bit size follows
            if pos + 16 > end:
                raise ExifError("truncated HEIF box header")
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            header = 16
        elif size == 0:  # box extends to the end of its container
            size = end - pos
        if size < header or pos + size > end:
            raise ExifError(f"corrupt HEIF box size in {kind!r}")
        yield kind, pos + header, pos + size
        pos += size


def _heif_items(iinf: bytes) -> list:
    """(item id, item type) for every item described in an 'iinf' payload."""
    if len(iinf) < 6:
        raise ExifError("truncated iinf box")
    first_child = 4 + (2 if iinf[0] == 0 else 4)  # version/flags + entry count
    items = []
    for kind, start, end in _iter_boxes(iinf, first_child):
        infe = iinf[start:end]
        if kind != b"infe" or len(infe) < 4 or infe[0] < 2:
            continue  # infe versions 0 and 1 carry no item type
        id_size = 2 if infe[0] == 2 else 4
        if len(infe) < 4 + id_size + 2 + 4:
            raise ExifError("truncated infe box")
        item_id = _uint(infe, 4, id_size)
        items.append((item_id, bytes(infe[4 + id_size + 2:4 + id_size + 6])))
    return items


def _heif_locations(iloc: bytes) -> dict:
    """item id -> (construction method, base offset, [(extent offset, extent length)])."""
    if len(iloc) < 8:
        raise ExifError("truncated iloc box")
    version = iloc[0]
    if version > 2:
        raise ExifError(f"unsupported iloc version {version}")
    offset_size, length_size = iloc[4] >> 4, iloc[4] & 15
    base_size, index_size = iloc[5] >> 4, (iloc[5] & 15 if version else 0)
    if any(size not in (0, 4, 8) for size in (offset_size, length_size, base_size, index_size)):
        raise ExifError("unsupported iloc field size")
    id_size = 2 if version < 2 else 4
    extent_width = offset_size + length_size + (index_size if version >= 1 else 0)
    pos, work = 6, 0
    count = _uint(iloc, pos, id_size)
    pos += id_size
    locations: dict = {}
    for _ in range(count):
        item_id = _uint(iloc, pos, id_size)
        pos += id_size
        method = 0
        if version >= 1:
            method = _uint(iloc, pos, 2) & 0xF
            pos += 2
        pos += 2  # data reference index
        base = _uint(iloc, pos, base_size)
        pos += base_size
        extent_count = _uint(iloc, pos, 2)
        pos += 2
        if extent_count and extent_width == 0:
            raise ExifError("iloc extents without any fields")  # would loop without consuming data
        work += 1 + extent_count
        if work > MAX_ILOC_WORK:
            raise ExifError("iloc box too large")
        extents = []
        for _ in range(extent_count):
            pos += index_size if version >= 1 else 0
            offset = _uint(iloc, pos, offset_size)
            pos += offset_size
            length = _uint(iloc, pos, length_size)
            pos += length_size
            extents.append((offset, length))
        locations.setdefault(item_id, (method, base, extents))
    return locations


def _heif_item_bytes(f, location: tuple, idat: bytes | None, file_end: int) -> bytes:
    method, base, extents = location
    if method not in (0, 1):
        raise ExifError(f"unsupported iloc construction method {method}")
    chunks, total = [], 0
    for offset, length in extents:
        total += length
        if length == 0 or total > MAX_EXIF_BYTES:
            raise ExifError("Exif item has an unusable size")
        position = base + offset
        if method == 0:  # offset from the start of the file
            if position + length > file_end:
                raise ExifError("Exif item extends beyond the end of the file")
            f.seek(position)
            chunk = f.read(length)
        elif idat is None:  # method 1: offset into the 'idat' box
            raise ExifError("item stored in idat, but the file has no idat box")
        else:
            chunk = idat[position:position + length]
        if len(chunk) < length:
            raise ExifError("Exif item extends beyond the end of the file")
        chunks.append(chunk)
    return b"".join(chunks)


def _tiff_from_heif(f) -> bytes | None:
    """Return the TIFF-structured EXIF block of a HEIC/HEIF file, or None if it has none."""
    file_end = f.seek(0, 2)
    pos, brands, meta = 0, set(), None
    while pos + 8 <= file_end:
        f.seek(pos)
        header = f.read(16)
        size, kind = struct.unpack(">I4s", header[:8])
        header_size = 8
        if size == 1:
            if len(header) < 16:
                raise ExifError("truncated HEIF box header")
            size, header_size = struct.unpack(">Q", header[8:16])[0], 16
        elif size == 0:
            size = file_end - pos
        if size < header_size or pos + size > file_end:
            raise ExifError(f"corrupt HEIF box size in {kind!r}")
        if kind == b"ftyp":
            f.seek(pos + header_size)
            payload = f.read(min(size - header_size, 4096))
            brands = {payload[:4]} | {payload[i:i + 4] for i in range(8, len(payload) - 3, 4)}
            if not brands & HEIF_BRANDS:
                raise ExifError(f"not a HEIC/HEIF file (brand {payload[:4]!r})")
        elif kind == b"meta":
            if size > MAX_META_BYTES:
                raise ExifError("meta box too large")
            f.seek(pos + header_size)
            meta = f.read(size - header_size)
            break
        pos += size
    if meta is None:
        return None
    if len(meta) < 4:
        raise ExifError("truncated meta box")
    parts = {kind: meta[start:end] for kind, start, end in _iter_boxes(meta, 4)
             if kind in (b"iinf", b"iloc", b"idat")}
    if b"iinf" not in parts:
        return None
    exif_ids = [item_id for item_id, item_type in _heif_items(parts[b"iinf"]) if item_type == b"Exif"]
    if not exif_ids:
        return None
    if b"iloc" not in parts:
        raise ExifError("Exif item present but the file has no iloc box")
    location = _heif_locations(parts[b"iloc"]).get(exif_ids[0])
    if location is None:
        raise ExifError("Exif item has no location")
    item = _heif_item_bytes(f, location, parts.get(b"idat"), file_end)
    if len(item) < 4:
        raise ExifError("Exif item too short")
    skip = struct.unpack_from(">I", item, 0)[0]  # bytes between this field and the TIFF header
    tiff = item[4 + skip:]
    return tiff[6:] if tiff.startswith(b"Exif\x00\x00") else tiff


def _read_ifd(buf: bytes, e: str, offset: int) -> dict:
    if offset < 8 or offset + 2 > len(buf):
        raise ExifError("IFD offset outside EXIF data")
    (count,) = struct.unpack_from(e + "H", buf, offset)
    count = min(count, (len(buf) - offset - 2) // 12)
    entries: dict = {}
    for i in range(count):
        pos = offset + 2 + i * 12
        tag, typ, cnt = struct.unpack_from(e + "HHI", buf, pos)
        entries.setdefault(tag, (typ, cnt, pos + 8))  # (type, count, position of value field)
    return entries


def _ascii(buf: bytes, e: str, entry) -> str:
    if entry is None:
        return ""
    typ, cnt, value_pos = entry
    if typ != 2 or cnt == 0 or cnt > 256:
        return ""
    if cnt <= 4:
        raw = buf[value_pos:value_pos + cnt]
    else:
        (offset,) = struct.unpack_from(e + "I", buf, value_pos)
        if offset + cnt > len(buf):
            return ""
        raw = buf[offset:offset + cnt]
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


def parse_tiff_dates(buf: bytes) -> dict:
    """Extract date and offset tags from a TIFF-structured EXIF block."""
    try:
        if buf[:2] == b"II":
            e = "<"
        elif buf[:2] == b"MM":
            e = ">"
        else:
            raise ExifError("bad TIFF byte-order mark")
        if struct.unpack_from(e + "H", buf, 2)[0] != 42:
            raise ExifError("bad TIFF magic number")
        ifd0 = _read_ifd(buf, e, struct.unpack_from(e + "I", buf, 4)[0])
        tags: dict = {}
        value = _ascii(buf, e, ifd0.get(0x0132))
        if value:
            tags["DateTime"] = value  # IFD0 DateTime = last modification time
        pointer = ifd0.get(0x8769)  # Exif sub-IFD
        if pointer and pointer[0] == 4 and pointer[1] == 1:
            sub = _read_ifd(buf, e, struct.unpack_from(e + "I", buf, pointer[2])[0])
            for tag, name in ((0x9003, "DateTimeOriginal"), (0x9004, "DateTimeDigitized"),
                              (0x9010, "OffsetTime"), (0x9011, "OffsetTimeOriginal"),
                              (0x9012, "OffsetTimeDigitized")):
                value = _ascii(buf, e, sub.get(tag))
                if value:
                    tags[name] = value
        return tags
    except (struct.error, IndexError) as exc:
        raise ExifError(f"malformed TIFF structure ({exc})") from exc


def read_exif_dates(path: Path) -> tuple[dict, str]:
    """Return (tags, warning). Malformed metadata gives a warning, never an exception.

    The format is chosen from the file's first bytes, not its extension. BMP has no
    EXIF metadata, so it always returns no tags (and no warning). HEIC/HEIF files are
    read through their ISO box structure; the image data itself is never decoded.
    """
    with path.open("rb") as f:
        head = f.read(8)
        try:
            if head[:2] == b"\xff\xd8":
                tiff = _tiff_from_jpeg(f)
            elif head == PNG_SIGNATURE:
                tiff = _tiff_from_png(f)
            elif head[:2] == b"BM":
                return {}, ""
            elif head[4:8] == b"ftyp":
                tiff = _tiff_from_heif(f)
            else:
                return {}, "unrecognised file content for its extension; no EXIF read"
            return (parse_tiff_dates(tiff), "") if tiff else ({}, "")
        except ExifError as exc:
            return {}, f"EXIF unreadable: {exc}"


# --------------------------------------------------------------------------
# Choosing the date
# --------------------------------------------------------------------------
@dataclass
class DateChoice:
    dt: datetime | None  # wall-clock time as recorded (naive)
    offset: timedelta | None  # UTC offset, only when the EXIF data recorded one
    source: str
    has_time: bool = True
    notes: list = field(default_factory=list)


def parse_offset(text: str | None) -> timedelta | None:
    if not text:
        return None
    m = OFFSET_RE.match(text.strip())
    if not m:
        return None
    if m.group(1):
        return timedelta(0)
    hours, minutes = int(m.group(3)), int(m.group(4))
    if hours > 14 or minutes > 59:
        return None
    delta = timedelta(hours=hours, minutes=minutes)
    return -delta if m.group(2) == "-" else delta


def parse_exif_datetime(raw: str):
    """Return (naive datetime, offset or None), or None if unusable."""
    m = EXIF_DATE_RE.match(raw.strip().replace("\x00", ""))
    if not m:
        return None
    try:
        dt = datetime(*(int(m.group(i)) for i in range(1, 7)))
    except ValueError:
        return None
    return dt, parse_offset(m.group(7))


def date_from_filename(name: str):
    """Find a date (and optional time) in a file name. Returns (datetime, has_time) or None."""
    for m in FILENAME_DATE_RE.finditer(name):
        year, month, day = (int(m.group(i)) for i in (1, 2, 3))
        if m.group(4) is not None:
            try:
                return datetime(year, month, day, int(m.group(4)), int(m.group(5)), int(m.group(6))), True
            except ValueError:
                pass  # digits after the date are not a real time: use the date alone
        try:
            return datetime(year, month, day), False
        except ValueError:
            continue
    return None


def sanity_problem(dt: datetime, c: dict, now: datetime) -> str | None:
    if dt.year < c["min_year"]:
        return f"before year {c['min_year']}"
    if c["reject_future"] and dt > now + timedelta(days=1):
        return "in the future"
    return None


def _blank_exif(raw: str) -> bool:
    return not raw.strip(" :0\x00-T")


def _exif_candidate(exif, key, offset_key, source, c, now, notes):
    raw = exif.get(key)
    if raw is None:
        return None
    parsed = parse_exif_datetime(raw)
    if parsed is None:
        if not _blank_exif(raw):
            notes.append(f"{key} unparseable ({raw!r})")
        return None
    dt, offset = parsed
    if offset is None:
        offset = parse_offset(exif.get(offset_key))
    problem = sanity_problem(dt, c, now)
    if problem:
        notes.append(f"{key} {dt:%Y-%m-%d} rejected ({problem})")
        return None
    return DateChoice(dt, offset, source)


def choose_date(path: Path, exif: dict, c: dict, now: datetime) -> DateChoice:
    """Priority: EXIF original, EXIF digitized, filename, [EXIF modify], [file mtime], unknown."""
    notes: list = []
    for key, offset_key, source in (("DateTimeOriginal", "OffsetTimeOriginal", SRC_ORIGINAL),
                                    ("DateTimeDigitized", "OffsetTimeDigitized", SRC_DIGITIZED)):
        choice = _exif_candidate(exif, key, offset_key, source, c, now, notes)
        if choice:
            choice.notes = notes
            return choice
    if c["use_filename_date"]:
        found = date_from_filename(path.name)
        if found:
            dt, has_time = found
            problem = sanity_problem(dt, c, now)
            if problem:
                notes.append(f"filename date {dt:%Y-%m-%d} rejected ({problem})")
            else:
                return DateChoice(dt, None, SRC_FILENAME, has_time, notes)
    if c["use_modify_date"]:
        choice = _exif_candidate(exif, "DateTime", "OffsetTime", SRC_MODIFIED, c, now, notes)
        if choice:
            choice.notes = notes
            return choice
    if c["use_mtime"]:
        try:
            dt = datetime.fromtimestamp(path.stat().st_mtime)
        except (OverflowError, OSError, ValueError):
            notes.append("file modification time unusable")
        else:
            problem = sanity_problem(dt, c, now)
            if problem:
                notes.append(f"file modification time {dt:%Y-%m-%d} rejected ({problem})")
            else:
                return DateChoice(dt, None, SRC_MTIME, True, notes)
    return DateChoice(None, None, SRC_UNKNOWN, False, notes)


def to_basis(dt: datetime, offset: timedelta | None, mode: str) -> datetime:
    """The time used for folder and file names, according to timezone_mode."""
    if mode == "wallclock" or offset is None:
        return dt
    aware = dt.replace(tzinfo=timezone(offset))
    try:
        converted = aware.astimezone() if mode == "local" else aware.astimezone(timezone.utc)
    except (OverflowError, OSError, ValueError):
        return dt
    return converted.replace(tzinfo=None)


def epoch_of(dt: datetime, offset: timedelta | None) -> float:
    """Absolute time. Without a recorded offset the computer's local timezone is assumed."""
    if offset is not None:
        return dt.replace(tzinfo=timezone(offset)).timestamp()
    return dt.timestamp()


def format_recorded(dt: datetime, offset: timedelta | None) -> str:
    text = dt.strftime("%Y-%m-%d %H:%M:%S")
    if offset is None:
        return text
    total = int(offset.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    return f"{text}{sign}{abs(total) // 60:02d}:{abs(total) % 60:02d}"


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------
def is_hidden(name: str, st) -> bool:
    """Dot-prefixed everywhere; Windows hidden/system attribute; macOS UF_HIDDEN flag.

    Linux has no OS-level hidden flag, so there only dot-prefixed names count.
    """
    if name.startswith("."):
        return True
    if getattr(st, "st_file_attributes", 0) & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM):
        return True
    if getattr(st, "st_flags", 0) & stat.UF_HIDDEN:
        return True
    return False


def scan(c: dict):
    """Yield (path, status, detail). status None means: an image to process.

    Hidden or symlinked folders are reported once and not entered.
    """
    def walk(directory):
        try:
            with os.scandir(directory) as it:
                entries = sorted(it, key=lambda e: (e.name.casefold(), e.name))
        except OSError as exc:
            yield Path(directory), "error", f"cannot read folder: {exc}"
            return
        for entry in entries:
            path = Path(entry.path)
            is_junction = getattr(entry, "is_junction", None)
            if entry.is_symlink() or (is_junction is not None and is_junction()):
                yield path, "skipped_symlink", "symbolic link or junction"
                continue
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                yield path, "error", f"cannot stat: {exc}"
                continue
            is_dir = entry.is_dir(follow_symlinks=False)
            if c["skip_hidden"] and is_hidden(entry.name, st):
                yield path, "skipped_hidden", "hidden folder, contents not scanned" if is_dir else "hidden file"
                continue
            if is_dir:
                if c["recursive"]:
                    yield from walk(entry.path)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            if path.suffix.lower() not in c["extensions"]:
                yield path, "skipped_extension", f"unsupported type {path.suffix or '(no extension)'}"
                continue
            yield path, None, ""

    yield from walk(c["input"])


# --------------------------------------------------------------------------
# Hashing, duplicates, names
# --------------------------------------------------------------------------
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


class ContentIndex:
    """Finds identical file content anywhere in the output tree (any name, any folder).

    Candidates are first narrowed by file size; hashes are computed only when a
    same-size candidate exists and are cached for the rest of the run.
    """

    def __init__(self):
        self._by_size: dict = {}

    def add(self, size: int, read_path: Path, label: Path, digest: str | None = None) -> None:
        self._by_size.setdefault(size, []).append([read_path, label, digest])

    def find_identical(self, source: Path, size: int):
        """Return (label of identical file or None, source digest or None if not needed)."""
        candidates = self._by_size.get(size)
        if not candidates:
            return None, None
        digest = sha256(source)
        for entry in candidates:
            if entry[2] is None:
                try:
                    entry[2] = sha256(entry[0])
                except OSError:
                    entry[2] = ""  # unreadable: never matches
            if entry[2] == digest:
                return entry[1], digest
        return None, digest


def build_index(c: dict) -> ContentIndex:
    index = ContentIndex()
    root = c["output"]
    if not root.is_dir():
        return index
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.startswith(TEMP_PREFIX):
                continue
            path = Path(dirpath) / name
            if path.suffix.lower() not in c["extensions"]:
                continue
            try:
                st = path.lstat()
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                index.add(st.st_size, path, path)
    return index


def unique_destination(folder: Path, name: str, reserved: set, hints: dict | None = None) -> Path:
    """NAME.ext, then NAME_001.ext, NAME_002.ext ... never an existing or planned path.

    `hints` remembers the last counter used per name, so a thousand files called IMG_0001.jpg do not each
    re-test every number from 001 upwards.
    """
    def taken(p: Path) -> bool:
        return os.path.normcase(str(p)) in reserved or os.path.lexists(p)

    candidate = folder / name
    if not taken(candidate):
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    key = os.path.normcase(str(candidate))
    counter = hints.get(key, 0) if hints is not None else 0
    while True:
        counter += 1
        if counter > 99999:
            raise RuntimeError(f"too many name collisions for {name}")
        candidate = folder / f"{stem}_{counter:03d}{suffix}"
        if not taken(candidate):
            if hints is not None:
                hints[key] = counter
            return candidate


def target_name(src: Path, choice: DateChoice, basis: datetime | None, pattern: str):
    """Return (file name, note). Renaming happens only for real capture-time dates."""
    if not pattern:
        return src.name, ""
    eligible = choice.source in CAPTURE_SOURCES or (choice.source == SRC_FILENAME and choice.has_time)
    if basis is None or not eligible:
        return src.name, f"kept original name (date source '{choice.source}' is not a full capture time)"
    return basis.strftime(pattern).replace("{original}", src.stem) + src.suffix, ""


# --------------------------------------------------------------------------
# Windows "Date created" (standard library ctypes, Windows only)
# --------------------------------------------------------------------------
def to_filetime(epoch: float) -> int:
    """Unix epoch seconds -> Windows FILETIME (100 ns ticks since 1601-01-01)."""
    ticks = FILETIME_UNIX_EPOCH + int(round(epoch * 10_000_000))
    if ticks < 0:
        raise ValueError("date before 1601 cannot be stored as a Windows file time")
    return ticks


def _win_path(path: Path) -> str:
    text = os.fspath(path)
    if len(text) >= 240 and not text.startswith("\\\\?\\"):  # long path prefix
        text = "\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text
    return text


def set_creation_time(path: Path, epoch: float) -> None:
    """Set the 'Date created' of an existing file (Windows only).

    The modified and accessed times are not touched. Raises OSError on failure.
    """
    if not IS_WINDOWS:
        raise OSError("setting the creation time is only supported on Windows")
    import ctypes
    from ctypes import wintypes

    ticks = to_filetime(epoch)
    filetime = wintypes.FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.CreateFileW.restype = wintypes.HANDLE
    pft = ctypes.POINTER(wintypes.FILETIME)
    k32.SetFileTime.argtypes = [wintypes.HANDLE, pft, pft, pft]
    k32.SetFileTime.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL

    FILE_WRITE_ATTRIBUTES, SHARE_ALL, OPEN_EXISTING, ATTRIBUTE_NORMAL = 0x0100, 0x7, 3, 0x80
    invalid = ctypes.c_void_p(-1).value
    handle = k32.CreateFileW(_win_path(path), FILE_WRITE_ATTRIBUTES, SHARE_ALL, None,
                             OPEN_EXISTING, ATTRIBUTE_NORMAL, None)
    if handle is None or handle == invalid:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not k32.SetFileTime(handle, ctypes.byref(filetime), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k32.CloseHandle(handle)


# --------------------------------------------------------------------------
# Transfer
# --------------------------------------------------------------------------
def copy_hashing(source: Path, temp: Path) -> str:
    """Copy source to temp and return the SHA-256 of exactly the bytes copied."""
    h = hashlib.sha256()
    with source.open("rb") as i, temp.open("wb") as o:
        while chunk := i.read(CHUNK):
            h.update(chunk)
            o.write(chunk)
    shutil.copystat(source, temp)
    return h.hexdigest()


def _make_writable(path: Path) -> None:
    """Windows refuses to delete a read-only file, so the temporary copy must never be read-only."""
    os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) | stat.S_IWRITE)


def _delete(path: Path) -> None:
    """Delete a file, clearing the read-only attribute first when the system insists (Windows)."""
    try:
        path.unlink()
    except PermissionError:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        path.unlink()


def transfer(source: Path, dest: Path, should_copy: bool, verify: bool, epoch: float | None,
             known_digest: str | None = None, notes: list | None = None) -> str:
    """Copy (or safely move) source to dest without ever overwriting. Returns the source SHA-256.

    The copy is made under a temporary name, verified, and only then published under its final name in
    one atomic step. Problems that leave the copy intact (for example a read-only flag that cannot be
    restored) are appended to `notes`.
    """
    notes = [] if notes is None else notes
    dest.parent.mkdir(parents=True, exist_ok=True)
    source_mode = stat.S_IMODE(source.stat().st_mode)
    fd, name = tempfile.mkstemp(prefix=TEMP_PREFIX, suffix=".tmp", dir=dest.parent)
    os.close(fd)
    temp = Path(name)
    try:
        digest = copy_hashing(source, temp)
        _make_writable(temp)  # copystat gave it the source's (possibly read-only) mode
        if known_digest is not None and known_digest != digest:
            raise OSError("source changed while being processed; nothing published")
        if verify and sha256(temp) != digest:
            raise OSError("SHA-256 mismatch after copy; original retained")
        if epoch is not None:
            os.utime(temp, (temp.stat().st_atime, epoch))
        try:
            os.link(temp, dest)  # atomic, fails if dest exists
        except OSError:
            if os.path.lexists(dest):
                raise FileExistsError(f"destination appeared during run: {dest}")
            # No hard links here (FAT, exFAT, some network shares). The finished and verified temporary file lies in
            # the same folder, so renaming it is atomic too: a half-written file can never carry the final name.
            os.rename(temp, dest)
        temp.unlink(missing_ok=True)
        if not source_mode & stat.S_IWRITE:  # the source is read-only, so the copy should be too
            try:
                os.chmod(dest, source_mode)
            except OSError as exc:
                notes.append(f"read-only state not copied: {exc}")
        if not should_copy:
            if sha256(source) != digest:
                raise OSError("source changed during move; original retained, destination kept")
            _delete(source)
        return digest
    finally:
        temp.unlink(missing_ok=True)


def remove_empty_folders(parents: set, root: Path) -> list:
    """Remove folders that became empty after a move, walking upward; never the input root."""
    removed: list = []
    for start in sorted(parents, key=lambda p: len(p.parts), reverse=True):
        directory = start
        while directory != root and root in directory.parents:
            try:
                os.rmdir(directory)
            except OSError:
                break  # not empty (or not removable): stop
            removed.append(directory)
            directory = directory.parent
    return removed


# --------------------------------------------------------------------------
# One run
# --------------------------------------------------------------------------
@dataclass
class RunState:
    """Everything that is shared between the files of one run."""
    c: dict
    now: datetime
    index: ContentIndex | None = None
    reserved: set = field(default_factory=set)  # destinations already used or planned
    hints: dict = field(default_factory=dict)  # last NAME_### counter per name
    counts: dict = field(default_factory=dict)
    moved_parents: set = field(default_factory=set)  # input folders that lost a file

    def claim(self, dest: Path, size: int | None, read_path: Path, digest: str | None) -> None:
        """Remember that `dest` is taken (and, for duplicate detection, what it contains)."""
        self.reserved.add(os.path.normcase(str(dest)))
        if self.index is not None and size is not None:
            self.index.add(size, read_path, dest, digest)


def process_image(src: Path, state: RunState) -> dict:
    """Date, destination and transfer for one image. Never raises: a failure becomes an `error` row."""
    c = state.c
    row = dict.fromkeys(FIELDS, "")
    row.update(source=src, action="copy" if c["copy"] else "move", status="error")
    notes: list = []
    dest = choice = basis = size = None
    attempted = False
    try:
        is_movie = c["handle_movies"] and src.suffix.lower() in MOVIE_EXTENSIONS
        exif, warning = ({}, "") if is_movie else read_exif_dates(src)  # movies carry no EXIF: file name, then mtime
        choice = choose_date(src, exif, c, state.now)
        notes = ([warning] if warning else []) + choice.notes
        if choice.dt is None:
            folder = c["output"] / c["unknown_folder"]
            notes.append(f"no usable date; placed in '{c['unknown_folder']}'")
        else:
            basis = to_basis(choice.dt, choice.offset, c["tz_mode"])
            folder = c["output"] / Path(*basis.strftime(STRUCTURES[c["structure"]]).split("/"))
        if is_movie:
            folder = folder / c["movies_folder"]
        name, rename_note = target_name(src, choice, basis, c["rename_pattern"])
        if rename_note:
            notes.append(rename_note)

        size = src.stat().st_size
        digest = None
        identical = None
        if state.index is not None:
            identical, digest = state.index.find_identical(src, size)
        if identical is not None:
            dest = identical
            row["status"] = "skipped_identical"
            notes.append("identical content already exists; original left untouched")
        else:
            dest = unique_destination(folder, name, state.reserved, state.hints)
            if dest.name != name:
                notes.append(f"name already used; renamed to {dest.name}")
            epoch = None
            if c["change_timestamp"] and choice.source in CAPTURE_SOURCES:
                try:
                    epoch = epoch_of(choice.dt, choice.offset)
                except (OverflowError, OSError, ValueError):
                    notes.append("timestamp not set: date out of range for this OS")
            if c["dry_run"]:
                row["status"] = "planned"
                if epoch is not None:
                    notes.append("destination mtime would be set")
                    if c["set_creation_time"]:
                        notes.append("destination creation time would be set")
                state.claim(dest, size, src, digest)
            else:
                attempted = True
                digest = transfer(src, dest, c["copy"], c["verify"], epoch, digest, notes)
                row["status"] = "completed"
                state.claim(dest, size, dest, digest)
                if epoch is not None:
                    notes.append("destination mtime set")
                    if c["set_creation_time"]:
                        try:  # the file is already safely published: a failure here is only a note
                            set_creation_time(dest, epoch)
                            notes.append("destination creation time set")
                        except Exception as exc:
                            notes.append(f"creation time not set: {exc}")
                if not c["copy"]:
                    state.moved_parents.add(src.parent)
    except Exception as exc:  # one bad file must not stop the run
        row["status"] = "error"
        notes.append(f"{type(exc).__name__}: {exc}")
        if IS_WINDOWS and dest is not None and len(os.fspath(dest)) > WINDOWS_MAX_PATH:
            notes.append(f"the destination path is {len(os.fspath(dest))} characters; Windows allows {WINDOWS_MAX_PATH} "
                         "unless long paths are enabled (see the README, Platform notes)")
        if attempted and dest is not None and os.path.lexists(dest):
            # published, but something afterwards failed (for example deleting the original): the copy exists
            state.claim(dest, size, dest, None)
    row.update(destination=dest or "", date_source=choice.source if choice else "",
               date_recorded=format_recorded(choice.dt, choice.offset) if choice and choice.dt else "",
               date_used=basis.strftime("%Y-%m-%d %H:%M:%S") if basis else "",
               details="; ".join(n for n in notes if n))
    return row


def write_unknown_files(c: dict, unknown_files: list) -> None:
    c["unknown_csv"].parent.mkdir(parents=True, exist_ok=True)
    with c["unknown_csv"].open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(UNKNOWN_FIELDS)
        writer.writerows(unknown_files)


class Progress:
    """One-line counter on stderr (`1234/5678  21%`), redrawn in place.

    Shown only when stderr is a terminal, so redirected output, logs and tests stay clean. Redraws are
    throttled, and the line is erased before the summary prints.
    """

    def __init__(self, total: int, stream=None):
        self.total, self.done, self.last = total, 0, 0.0
        self.stream = stream if stream is not None else sys.stderr
        try:
            self.enabled = total > 0 and bool(self.stream.isatty())
        except (AttributeError, ValueError, OSError):
            self.enabled = False

    def step(self) -> None:
        self.done += 1
        now = time.monotonic()
        if self.enabled and (self.done == self.total or now - self.last >= 0.1):
            self.last = now
            self._write(f"\r{self.done}/{self.total}  {self.done * 100 // self.total}%")

    def finish(self) -> None:
        if self.enabled:
            self._write("\r" + " " * (len(str(self.total)) * 2 + 7) + "\r")  # erase the line

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
            self.stream.flush()
        except (OSError, ValueError):
            self.enabled = False  # a broken console must never stop a run


def say(text: str) -> None:
    """Print a phase message at once, so it is visible even when the output goes through a pipe.

    A console that fails (closed pipe, ...) must never stop a run, so errors are ignored here.
    """
    try:
        print(text, flush=True)
    except (OSError, ValueError):
        pass


def yn(value: bool) -> str:
    return "yes" if value else "no"


def run(c: dict) -> int:
    now = c.get("now") or datetime.now()
    if c["set_creation_time"] and not IS_WINDOWS:
        print("WARNING: set_creation_time is only supported on Windows; ignored on this system.", file=sys.stderr)
        c["set_creation_time"] = False
    c["report"].parent.mkdir(parents=True, exist_ok=True)
    action = "copy" if c["copy"] else "move"

    say(f"Starting program with options: testrun={yn(c['dry_run'])}, copy_mode={yn(c['copy'])}, "
        f"verify={yn(c['verify'])}, duplicate_policy={c['duplicates']}")
    say(f"Input folder:   {c['input']}")
    say(f"Output folder:  {c['output']}")
    say(f"Reports folder: {c['reports_dir']}")

    # Preliminary scan: the output folder (known content, for duplicates) and the input folder (a folder walk,
    # no file is read), so the total is known for the progress line.
    say("Starting preliminary scan ...")
    state = RunState(c, now, build_index(c) if c["duplicates"] == "skip_identical" else None)
    unknown_files: list = []
    removed_folders: list = []
    entries = list(scan(c))
    to_process = sum(1 for _, status, _ in entries if status is None)
    skipped = sum(1 for _, status, _ in entries if status is not None and status.startswith("skipped_"))
    unreadable = sum(1 for _, status, _ in entries if status == "error")
    say(f"Preliminary scan completed: {to_process} file(s) to process, {skipped} skipped"
        + (f", {unreadable} unreadable" if unreadable else ""))
    progress = Progress(to_process)

    say("Starting file handling" + (" (test run: no file is changed) ..." if c["dry_run"] else " ..."))
    try:
        with c["report"].open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()

            def emit(row: dict) -> None:
                if row.get("action") != "remove_empty_folder":  # the summary counts files, not folders
                    state.counts[row["status"]] = state.counts.get(row["status"], 0) + 1
                writer.writerow({key: str(row.get(key, "")) for key in FIELDS})
                f.flush()  # the report stays usable if the run is interrupted

            for src, skip_status, skip_detail in entries:
                if skip_status == "skipped_extension":
                    try:
                        size = src.stat().st_size
                    except OSError:
                        size = ""
                    unknown_files.append((src, src.suffix.lower(), size))
                if skip_status is None:
                    emit(process_image(src, state))
                    progress.step()
                elif skip_status == "error" or c["report_skipped"]:
                    emit({"source": src, "action": "scan" if skip_status == "error" else "skip",
                          "status": skip_status, "details": skip_detail})

            if c["cleanup"] and not c["copy"] and not c["dry_run"]:
                for directory in remove_empty_folders(state.moved_parents, c["input"]):
                    emit({"source": directory, "action": "remove_empty_folder", "status": "completed"})
                    removed_folders.append(directory)
    finally:
        progress.finish()
        if unknown_files:  # also after Ctrl-C: the list of what was found so far is still useful
            write_unknown_files(c, unknown_files)

    # Everything is on disk now; only then print, so a console problem can never cost a result.
    print(f"Mode: {'TEST ONLY' if c['dry_run'] else 'LIVE'} ({action}) | "
          + ", ".join(f"{k}={v}" for k, v in sorted(state.counts.items())))
    if removed_folders:
        print(f"Removed {len(removed_folders)} empty folder(s) from the input folder.")
    elif c["cleanup"] and c["dry_run"] and not c["copy"]:
        print("Empty-folder cleanup is not simulated in a test run.")
    print(f"CSV report: {c['report']}")
    if unknown_files:
        print(f"WARNING: {len(unknown_files)} file(s) with unsupported types were NOT processed. "
              f"They are listed in {c['unknown_csv']}", file=sys.stderr)
    say("Program end. See the reports for details.")
    return 1 if state.counts.get("error") else 0


def _safe_console() -> None:
    """Never let a character the console cannot show (a path with an accent, say) abort or fail a run."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass  # not a text file object that can be reconfigured (for example under a test runner)


def main() -> int:
    _safe_console()
    parser = argparse.ArgumentParser(description=f"Photo Organizer {version_string()}\n\n{__doc__}",
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"%(prog)s {version_string()}")
    parser.add_argument("--config", default="config.ini", help="Path to config.ini")
    parser.add_argument("--dry-run", action="store_true", help="Force test run, regardless of config")
    args = parser.parse_args()
    print(f"Photo Organizer {version_string()}")  # first line of every run, also when the configuration is wrong
    try:
        conf = read_config(Path(args.config))
        if args.dry_run:
            conf["dry_run"] = True
        return run(conf)
    except KeyboardInterrupt:
        print("Interrupted. Files already processed stay where they are, no file was left half-written, and the "
              "report so far is saved.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, configparser.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
