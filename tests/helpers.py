"""Shared helpers: build real JPEG/PNG/BMP files byte by byte and a base TestCase."""
import contextlib
import csv
import io
import os
import struct
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import photo_organizer as org

__all__ = ["BMP", "NOW", "Base", "box", "exif_jpeg", "fullbox", "heic_bytes", "iloc_box", "infe_box", "iinf_box",
           "jpeg_bytes", "make_tiff", "png_bytes", "png_chunk"]

NOW = datetime(2026, 10, 21, 12, 0, 0)  # fixed "today" so date sanity checks are deterministic


def make_tiff(ifd0=None, exif=None, endian="<"):
    """Build a TIFF/EXIF block. ifd0/exif: {tag: ascii string}."""
    ifd0, exif = dict(ifd0 or {}), dict(exif or {})
    entries0 = sorted(ifd0.items())
    n0 = len(entries0) + (1 if exif else 0)
    ifd0_size = 2 + n0 * 12 + 4
    exif_size = 2 + len(exif) * 12 + 4
    data_start = 8 + ifd0_size + (exif_size if exif else 0)
    blobs, pos = b"", data_start

    def entry(tag, text):
        nonlocal blobs, pos
        raw = text.encode("ascii") + b"\x00"
        if len(raw) <= 4:
            value = raw.ljust(4, b"\x00")
        else:
            value = struct.pack(endian + "I", pos)
            blobs += raw
            pos += len(raw)
        return struct.pack(endian + "HHI", tag, 2, len(raw)) + value

    e0 = [entry(t, v) for t, v in entries0]
    ee = [entry(t, v) for t, v in sorted(exif.items())]
    if exif:
        e0.append(struct.pack(endian + "HHII", 0x8769, 4, 1, 8 + ifd0_size))
        e0.sort(key=lambda b: struct.unpack(endian + "H", b[:2])[0])
    out = (b"II" if endian == "<" else b"MM") + struct.pack(endian + "HI", 42, 8)
    out += struct.pack(endian + "H", len(e0)) + b"".join(e0) + struct.pack(endian + "I", 0)
    if exif:
        out += struct.pack(endian + "H", len(ee)) + b"".join(ee) + struct.pack(endian + "I", 0)
    return out + blobs


def jpeg_bytes(tiff=None, xmp_first=False):
    out = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    if xmp_first:
        xmp = b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta/>"
        out += b"\xff\xe1" + struct.pack(">H", len(xmp) + 2) + xmp
    if tiff is not None:
        payload = b"Exif\x00\x00" + tiff
        out += b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return out + b"\xff\xda\x00\x02" + b"\x00" * 8 + b"\xff\xd9"


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + b"\x00\x00\x00\x00"


def png_bytes(tiff=None, exif_after_idat=False):
    ihdr = png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = png_chunk(b"IDAT", b"\x00" * 20)
    exif = png_chunk(b"eXIf", tiff) if tiff is not None else b""
    body = (idat + exif) if exif_after_idat else (exif + idat)
    return org.PNG_SIGNATURE + ihdr + body + png_chunk(b"IEND", b"")


BMP = b"BM" + b"\x00" * 60


def exif_jpeg(original=None, digitized=None, modified=None, offset=None, endian="<", **kw):
    ex = {}
    if original: ex[0x9003] = original
    if digitized: ex[0x9004] = digitized
    if offset: ex[0x9011] = offset
    ifd0 = {0x0132: modified} if modified else {}
    return jpeg_bytes(make_tiff(ifd0, ex, endian), **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.inp = self.root / "in"
        self.out = self.root / "out"
        self.inp.mkdir()

    def put(self, rel, data, mtime=None):
        p = self.inp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def conf(self, **kw):
        sections = {
            "organization": ["output_folderstructure", "unknown_date_folder", "handle_movies", "movies_folder", "testrun", "copy_mode",
                             "change_timestamp", "set_creation_time", "verify", "rename_by_date", "cleanup_empty_folders"],
            "dates": ["use_filename_date", "use_exif_modify_date", "use_filesystem_mtime",
                      "timezone_mode", "min_year", "reject_future_dates"],
            "behavior": ["recursive", "duplicate_policy", "skip_hidden", "extensions", "report_skipped"],
        }
        values = {"testrun": "no", **kw}
        lines = ["[folders]", f"input_folder = {self.inp}", f"output_folder = {self.out}"]
        for section, keys in sections.items():
            lines.append(f"[{section}]")
            lines += [f"{k} = {values[k]}" for k in keys if k in values]
        unknown = set(values) - {k for ks in sections.values() for k in ks}
        self.assertFalse(unknown, f"test used unknown config keys {unknown}")
        lines += [f"report_csv = {self.root / 'report.csv'}", f"unknown_files_csv = {self.root / 'unknown_files.csv'}"]
        cfg = self.root / "config.ini"
        cfg.write_text("\n".join(lines), encoding="utf-8")
        c = org.read_config(cfg)
        c["now"] = NOW
        return c

    def go(self, **kw):
        c = self.conf(**kw)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = org.run(c)
        self.code, self.stdout, self.stderr = code, out.getvalue(), err.getvalue()
        return c

    def rows(self):
        with (self.root / "report.csv").open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def row(self, name):
        found = [r for r in self.rows() if Path(r["source"]).name == name]
        self.assertEqual(len(found), 1, f"{name}: {[r['source'] for r in self.rows()]}")
        return found[0]

    def outfiles(self):
        return sorted(str(p.relative_to(self.out)).replace(os.sep, "/")
                      for p in self.out.rglob("*") if p.is_file()) if self.out.exists() else []


# ---- HEIC / HEIF (ISO base media file format) --------------------------------
def box(kind, payload=b"", large=False):
    """An ISO box; large=True uses the 64-bit size form."""
    if large:
        return struct.pack(">I4sQ", 1, kind, 16 + len(payload)) + payload
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def fullbox(kind, version, payload=b"", flags=0, large=False):
    return box(kind, struct.pack(">I", (version << 24) | flags) + payload, large)


def infe_box(item_id, item_type, version=2):
    if version == 2:
        body = struct.pack(">HH4s", item_id, 0, item_type) + b"\x00"
    else:
        body = struct.pack(">IH4s", item_id, 0, item_type) + b"\x00"
    return fullbox(b"infe", version, body)


def iinf_box(entries, version=0, large=False):
    count = struct.pack(">H" if version == 0 else ">I", len(entries))
    return fullbox(b"iinf", version, count + b"".join(entries), large=large)


def iloc_box(items, version=1, offset_size=4, length_size=4, base_offset_size=0, index_size=0, large=False):
    """items: [(item_id, construction_method, base_offset, [(extent_offset, extent_length), ...])]."""
    def num(value, size):
        return value.to_bytes(size, "big") if size else b""

    body = bytes([(offset_size << 4) | length_size, (base_offset_size << 4) | (index_size if version else 0)])
    body += struct.pack(">H" if version < 2 else ">I", len(items))
    for item_id, method, base, extents in items:
        body += struct.pack(">H" if version < 2 else ">I", item_id)
        if version >= 1:
            body += struct.pack(">H", method)
        body += struct.pack(">H", 0) + num(base, base_offset_size) + struct.pack(">H", len(extents))
        for offset, length in extents:
            if version >= 1 and index_size:
                body += num(0, index_size)
            body += num(offset, offset_size) + num(length, length_size)
    return fullbox(b"iloc", version, body, large=large)


def heic_bytes(tiff=None, *, brand=b"heic", compat=(b"mif1", b"heic"), iloc_version=1, offset_size=4,
               length_size=4, base_offset_size=0, index_size=0, method=0, infe_version=2, iinf_version=0,
               mdat_first=False, extra_item=True, large=False, exif_prefix=True, with_iinf=True):
    """A structurally valid HEIC file (the 'image' is dummy data) carrying EXIF in an 'Exif' item.

    tiff: one TIFF block, a list of them (several Exif items), or None (no Exif item).
    method: 0 = Exif stored in mdat (file offsets), 1 = stored in an 'idat' box inside 'meta'.
    """
    tiffs = [] if tiff is None else (list(tiff) if isinstance(tiff, (list, tuple)) else [tiff])
    payloads = [struct.pack(">I", 6 if exif_prefix else 0) + (b"Exif\x00\x00" if exif_prefix else b"") + t
                for t in tiffs]
    image = b"\x00" * 64
    ftyp = box(b"ftyp", brand + struct.pack(">I", 0) + b"".join(compat))
    header = 16 if large else 8

    def meta_for(mdat_payload_start):
        entries, locations = [], []
        position = 0
        if extra_item:
            entries.append(infe_box(1, b"hvc1", infe_version))
            offset = mdat_payload_start if not base_offset_size else 0
            locations.append((1, 0, mdat_payload_start if base_offset_size else 0, [(offset, len(image))]))
        mdat_cursor = len(image)
        for number, payload in enumerate(payloads):
            item_id = 2 + number
            entries.append(infe_box(item_id, b"Exif", infe_version))
            if method == 0:
                relative = mdat_cursor
                mdat_cursor += len(payload)
                base = mdat_payload_start if base_offset_size else 0
                offset = relative if base_offset_size else mdat_payload_start + relative
                locations.append((item_id, 0, base, [(offset, len(payload))]))
            else:
                locations.append((item_id, 1, 0, [(position, len(payload))]))
                position += len(payload)
        children = b""
        if with_iinf:
            children += iinf_box(entries, iinf_version)
        children += iloc_box(locations, iloc_version, offset_size, length_size, base_offset_size, index_size)
        if method == 1:
            children += box(b"idat", b"".join(payloads))
        return fullbox(b"meta", 0, children, large=large)

    mdat_payload = image + (b"".join(payloads) if method == 0 else b"")
    mdat = box(b"mdat", mdat_payload, large)
    meta_length = len(meta_for(0))  # field sizes are fixed, so the length does not depend on the offsets
    if mdat_first:
        start = len(ftyp) + header
        return ftyp + mdat + meta_for(start)
    start = len(ftyp) + meta_length + header
    return ftyp + meta_for(start) + mdat

