"""HEIC/HEIF: EXIF is read from the ISO box structure with the standard library only."""
import random
import struct
import unittest
from datetime import datetime, timezone
from unittest import mock

import photo_organizer as org
from tests.helpers import (Base, box, fullbox, heic_bytes, iinf_box, iloc_box, infe_box, jpeg_bytes, make_tiff,
                           png_bytes)

TAGS = {0x9003: "2019:07:04 15:30:12", 0x9004: "2019:07:04 15:30:13", 0x9011: "+02:00"}
TIFF = make_tiff({0x0132: "2019:07:05 08:00:00"}, TAGS)
EXPECTED = {"DateTime": "2019:07:05 08:00:00", "DateTimeOriginal": "2019:07:04 15:30:12",
            "DateTimeDigitized": "2019:07:04 15:30:13", "OffsetTimeOriginal": "+02:00"}


class HeicBase(Base):
    def read(self, data, name="IMG_0001.HEIC"):
        return org.read_exif_dates(self.put(name, data))

    def assert_dates(self, data, name="IMG_0001.HEIC"):
        tags, warning = self.read(data, name)
        self.assertEqual((tags, warning), (EXPECTED, ""))


class LayoutVariants(HeicBase):
    def test_typical_layout(self):
        self.assert_dates(heic_bytes(TIFF))

    def test_both_byte_orders_of_the_embedded_tiff(self):
        for endian in "<>":
            tiff = make_tiff({0x0132: "2019:07:05 08:00:00"}, TAGS, endian)
            self.assert_dates(heic_bytes(tiff))

    def test_image_data_before_the_metadata(self):
        self.assert_dates(heic_bytes(TIFF, mdat_first=True))

    def test_all_iloc_versions(self):
        for version in (0, 1, 2):
            with self.subTest(version=version):
                self.assert_dates(heic_bytes(TIFF, iloc_version=version))

    def test_field_sizes_of_iloc(self):
        for offset_size, length_size, base_size in ((4, 4, 0), (8, 8, 0), (8, 4, 4), (4, 8, 8), (4, 4, 4), (8, 8, 8)):
            with self.subTest(offset=offset_size, length=length_size, base=base_size):
                self.assert_dates(heic_bytes(TIFF, offset_size=offset_size, length_size=length_size,
                                             base_offset_size=base_size))

    def test_extent_index_field(self):
        self.assert_dates(heic_bytes(TIFF, iloc_version=1, index_size=4))
        self.assert_dates(heic_bytes(TIFF, iloc_version=2, index_size=8))

    def test_item_info_versions_and_wide_item_ids(self):
        self.assert_dates(heic_bytes(TIFF, infe_version=3, iloc_version=2, iinf_version=1))

    def test_exif_stored_in_the_idat_box(self):
        self.assert_dates(heic_bytes(TIFF, method=1))
        self.assert_dates(heic_bytes(TIFF, method=1, iloc_version=2, base_offset_size=4))

    def test_64_bit_box_sizes(self):
        self.assert_dates(heic_bytes(TIFF, large=True))
        self.assert_dates(heic_bytes(TIFF, large=True, mdat_first=True))

    def test_exif_item_without_the_exif_prefix(self):
        self.assert_dates(heic_bytes(TIFF, exif_prefix=False))

    def test_file_with_only_the_exif_item(self):
        self.assert_dates(heic_bytes(TIFF, extra_item=False))

    def test_first_exif_item_wins(self):
        other = make_tiff({}, {0x9003: "2001:01:01 01:01:01"})
        tags, _ = self.read(heic_bytes([TIFF, other]))
        self.assertEqual(tags["DateTimeOriginal"], "2019:07:04 15:30:12")

    def test_box_that_extends_to_the_end_of_the_file(self):
        data = bytearray(heic_bytes(TIFF))
        mdat_start = data.rindex(b"mdat") - 4
        data[mdat_start:mdat_start + 4] = b"\x00\x00\x00\x00"  # size 0 = until end of file
        self.assert_dates(bytes(data))

    def test_boxes_inside_meta_may_use_64_bit_sizes(self):
        payload = struct.pack(">I", 6) + b"Exif\x00\x00" + TIFF
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        meta = fullbox(b"meta", 0, iinf_box([infe_box(2, b"Exif")], large=True)
                       + iloc_box([(2, 1, 0, [(0, len(payload))])], large=True) + box(b"idat", payload, large=True))
        self.assert_dates(ftyp + meta)

    def test_image_data_box_of_size_zero_before_the_metadata_is_skipped_to_the_end(self):
        data = heic_bytes(TIFF, mdat_first=True, extra_item=False)
        mdat_start = data.index(b"mdat") - 4
        broken = bytearray(data)
        broken[mdat_start:mdat_start + 4] = b"\x00\x00\x00\x00"  # runs to the end of the file, swallowing meta
        tags, warning = self.read(bytes(broken))
        self.assertEqual((tags, warning), ({}, ""))  # no meta box was seen: a valid file without EXIF

    def test_meta_box_of_size_zero_runs_to_the_end_of_the_file(self):
        data = bytearray(heic_bytes(TIFF, mdat_first=True))
        meta_start = data.rindex(b"meta") - 4
        data[meta_start:meta_start + 4] = b"\x00\x00\x00\x00"
        self.assert_dates(bytes(data))

    def test_large_image_data_is_skipped_not_read(self):
        data = heic_bytes(TIFF) + b"\x00" * (3 * 1024 * 1024)  # trailing junk after mdat is ignored
        self.assert_dates(data)

    def test_extensions_do_not_matter_content_does(self):
        for name in ("a.heic", "b.HEIC", "c.heif", "d.jpg", "e.png"):
            with self.subTest(name):
                self.assert_dates(heic_bytes(TIFF), name)


class Brands(HeicBase):
    def test_all_heif_brands_are_accepted(self):
        for brand in sorted(org.HEIF_BRANDS):
            with self.subTest(brand=brand):
                self.assert_dates(heic_bytes(TIFF, brand=brand, compat=()))

    def test_brand_may_be_a_compatible_brand_only(self):
        self.assert_dates(heic_bytes(TIFF, brand=b"avif", compat=(b"avif", b"mif1", b"miaf")))

    def test_other_iso_files_are_refused_with_a_clear_warning(self):
        for brand in (b"isom", b"mp42", b"qt  ", b"M4A "):
            with self.subTest(brand=brand):
                tags, warning = self.read(heic_bytes(TIFF, brand=brand, compat=(b"isom",)))
                self.assertEqual(tags, {})
                self.assertIn("not a HEIC/HEIF file", warning)

    def test_missing_exif_is_not_a_warning(self):
        self.assertEqual(self.read(heic_bytes(None)), ({}, ""))

    def test_file_without_a_meta_box(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        self.assertEqual(self.read(ftyp + box(b"mdat", b"\x00" * 32)), ({}, ""))

    def test_meta_without_item_list(self):
        self.assertEqual(self.read(heic_bytes(TIFF, with_iinf=False)), ({}, ""))

    def test_other_item_types_are_not_mistaken_for_exif(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        meta = fullbox(b"meta", 0, iinf_box([infe_box(1, b"hvc1"), infe_box(2, b"mime"), infe_box(3, b"grid")])
                       + iloc_box([(1, 0, 0, [(0, 4)])]))
        self.assertEqual(self.read(ftyp + meta), ({}, ""))

    def test_old_item_info_versions_carry_no_type_and_are_ignored(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        old = fullbox(b"infe", 1, struct.pack(">HH", 1, 0) + b"name\x00" + b"image/x\x00")
        meta = fullbox(b"meta", 0, iinf_box([old]) + iloc_box([]))
        self.assertEqual(self.read(ftyp + meta), ({}, ""))


class Malformed(HeicBase):
    def warning(self, data):
        tags, warning = self.read(data)
        self.assertEqual(tags, {})
        return warning

    def test_every_prefix_of_a_valid_file_is_handled(self):
        data = heic_bytes(TIFF)
        for n in range(len(data) + 1):
            tags, warning = self.read(data[:n])
            self.assertIsInstance(tags, dict, f"prefix {n}")
            self.assertIsInstance(warning, str, f"prefix {n}")

    def test_every_prefix_of_the_other_layouts(self):
        for kw in ({"method": 1}, {"mdat_first": True}, {"iloc_version": 2, "base_offset_size": 4}, {"large": True}):
            data = heic_bytes(TIFF, **kw)
            for n in range(0, len(data) + 1, 3):
                tags, warning = self.read(data[:n])
                self.assertIsInstance(tags, dict, f"{kw} prefix {n}")

    def test_random_byte_corruption_never_raises(self):
        rng = random.Random(20261022)
        for variant in ({}, {"method": 1}, {"iloc_version": 2, "offset_size": 8, "length_size": 8, "base_offset_size": 8}):
            original = heic_bytes(TIFF, **variant)
            for i in range(250):
                data = bytearray(original)
                for _ in range(rng.randint(1, 6)):
                    data[rng.randrange(len(data))] = rng.randrange(256)
                tags, warning = org.read_exif_dates(self.put(f"f{i}.heic", bytes(data)))
                self.assertIsInstance(tags, dict)
                self.assertIsInstance(warning, str)

    def test_exif_extent_beyond_the_end_of_the_file(self):
        data = bytearray(heic_bytes(TIFF))
        data = data[:len(data) - 20]  # cut the last bytes of the Exif payload off
        self.assertIn("beyond the end", self.warning(bytes(data)))

    def test_exif_pointing_at_garbage(self):
        data = bytearray(heic_bytes(TIFF))
        index = data.rindex(b"Exif\x00\x00") + 6
        data[index:index + 2] = b"ZZ"  # no longer a TIFF byte-order mark
        self.assertIn("EXIF unreadable", self.warning(bytes(data)))

    def test_box_size_smaller_than_its_header(self):
        data = bytearray(heic_bytes(TIFF))
        meta_start = data.index(b"meta") - 4
        data[meta_start:meta_start + 4] = struct.pack(">I", 4)
        self.assertIn("corrupt HEIF box size", self.warning(bytes(data)))

    def test_box_size_beyond_the_file(self):
        data = bytearray(heic_bytes(TIFF))
        data[0:4] = struct.pack(">I", 0x7FFFFFFF)  # the ftyp box
        self.assertIn("corrupt HEIF box size", self.warning(bytes(data)))

    def test_unsupported_construction_method(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        meta = fullbox(b"meta", 0, iinf_box([infe_box(2, b"Exif")]) + iloc_box([(2, 2, 0, [(0, 10)])]))
        self.assertIn("construction method 2", self.warning(ftyp + meta))

    def test_idat_reference_without_an_idat_box(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        meta = fullbox(b"meta", 0, iinf_box([infe_box(2, b"Exif")]) + iloc_box([(2, 1, 0, [(0, 10)])]))
        self.assertIn("no idat box", self.warning(ftyp + meta))

    def test_exif_item_without_a_location(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        meta = fullbox(b"meta", 0, iinf_box([infe_box(2, b"Exif")]) + iloc_box([(7, 0, 0, [(0, 10)])]))
        self.assertIn("no location", self.warning(ftyp + meta))

    def test_exif_item_without_an_iloc_box(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        meta = fullbox(b"meta", 0, iinf_box([infe_box(2, b"Exif")]))
        self.assertIn("no iloc box", self.warning(ftyp + meta))

    def test_unusable_extent_sizes(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        for length in (0, org.MAX_EXIF_BYTES + 1):
            with self.subTest(length=length):
                meta = fullbox(b"meta", 0, iinf_box([infe_box(2, b"Exif")])
                               + iloc_box([(2, 0, 0, [(0, length)])], length_size=8))
                self.assertIn("unusable size", self.warning(ftyp + meta))

    def test_unsupported_iloc_version_and_field_sizes(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        info = iinf_box([infe_box(2, b"Exif")])
        bad_version = fullbox(b"meta", 0, info + fullbox(b"iloc", 5, b"\x44\x00\x00\x00"))
        self.assertIn("unsupported iloc version", self.warning(ftyp + bad_version))
        bad_size = fullbox(b"meta", 0, info + fullbox(b"iloc", 0, b"\x34\x00\x00\x00"))
        self.assertIn("unsupported iloc field size", self.warning(ftyp + bad_size))

    def test_iloc_claiming_a_huge_item_count(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        iloc = fullbox(b"iloc", 2, b"\x44\x00" + struct.pack(">I", 0xFFFFFFFF))
        meta = fullbox(b"meta", 0, iinf_box([infe_box(2, b"Exif")]) + iloc)
        self.assertIn("truncated HEIF box", self.warning(ftyp + meta))

    def test_meta_box_over_the_size_limit(self):
        with mock.patch.object(org, "MAX_META_BYTES", 16):
            self.assertIn("meta box too large", self.warning(heic_bytes(TIFF)))

    def test_truncated_box_payloads(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        cases = {
            "truncated meta box": box(b"meta", b"\x00\x00"),
            "truncated iinf box": fullbox(b"meta", 0, box(b"iinf", b"\x00\x00")),
            "truncated iloc box": fullbox(b"meta", 0, iinf_box([infe_box(2, b"Exif")]) + box(b"iloc", b"\x00" * 4)),
            "truncated infe box": fullbox(b"meta", 0, iinf_box([fullbox(b"infe", 2, b"\x00\x02")])),
        }
        for expected, meta in cases.items():
            with self.subTest(expected):
                self.assertIn(expected, self.warning(ftyp + meta))

    def test_box_header_cut_off_inside_a_64_bit_size(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        meta = fullbox(b"meta", 0, struct.pack(">I4s", 1, b"iinf") + b"\x00\x00\x00")
        self.assertIn("truncated HEIF box header", self.warning(ftyp + meta))

    def test_exif_item_too_short(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        meta = fullbox(b"meta", 0, iinf_box([infe_box(2, b"Exif")]) + iloc_box([(2, 1, 0, [(0, 2)])])
                       + box(b"idat", b"\x00\x00"))
        self.assertIn("Exif item too short", self.warning(ftyp + meta))

    def test_ftyp_box_without_any_brand(self):
        self.assertIn("not a HEIC/HEIF file", self.warning(b"\x00\x00\x00\x08ftyp"))

    def test_absurd_offsets_are_a_warning_not_a_crash(self):
        ftyp = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")
        for offset in (2 ** 63, 2 ** 64 - 1, 10 ** 12):
            with self.subTest(offset=offset):
                meta = fullbox(b"meta", 0, iinf_box([infe_box(2, b"Exif")])
                               + iloc_box([(2, 0, 0, [(offset, 10)])], offset_size=8))
                self.assertIn("beyond the end", self.warning(ftyp + meta))


class OtherFormatsStillWork(HeicBase):
    def test_jpeg_png_bmp_are_not_confused_with_heif(self):
        self.assertEqual(self.read(jpeg_bytes(), "a.jpg"), ({}, ""))
        self.assertEqual(self.read(png_bytes(), "a.png"), ({}, ""))
        self.assertEqual(self.read(b"BM" + b"\x00" * 60, "a.bmp"), ({}, ""))

    def test_random_data_with_ftyp_at_offset_four(self):
        tags, warning = self.read(b"\x00\x00\x00\x20ftyp" + b"xxxx" * 6)
        self.assertEqual(tags, {})
        self.assertIn("not a HEIC/HEIF file", warning)


class EndToEnd(HeicBase):
    def test_iphone_style_names_are_sorted_by_exif_date(self):
        self.put("IMG_1234.HEIC", heic_bytes(TIFF))
        self.put("IMG_1235.heic", heic_bytes(make_tiff({}, {0x9003: "2020:02:03 04:05:06"})))
        self.put("holiday.heif", heic_bytes(make_tiff({}, {0x9003: "2021:12:31 23:59:00"})))
        self.go()
        self.assertEqual(self.outfiles(), ["2019_07/IMG_1234.HEIC", "2020_02/IMG_1235.heic", "2021_12/holiday.heif"])
        self.assertEqual(self.row("IMG_1234.HEIC")["date_source"], org.SRC_ORIGINAL)

    def test_rename_timestamp_and_timezone_apply_to_heic(self):
        self.put("IMG_1234.HEIC", heic_bytes(make_tiff({}, {0x9003: "2019:07:31 23:30:00", 0x9011: "-05:00"})))
        self.go(rename_by_date="%Y%m%d_%H%M%S_{original}", timezone_mode="utc", change_timestamp="yes")
        self.assertEqual(self.outfiles(), ["2019_08/20190801_043000_IMG_1234.HEIC"])
        expected = datetime(2019, 8, 1, 4, 30, 0, tzinfo=timezone.utc).timestamp()
        dest = self.out / "2019_08" / "20190801_043000_IMG_1234.HEIC"
        self.assertEqual(int(dest.stat().st_mtime), int(expected))

    def test_heic_without_exif_uses_the_file_name_then_the_modification_time(self):
        self.put("IMG_20190704_153012.HEIC", heic_bytes(None))
        self.put("plain.heic", heic_bytes(None) + b"\x01", mtime=datetime(2021, 5, 6, 7).timestamp())
        self.go()
        self.assertEqual(self.outfiles(), ["2019_07/IMG_20190704_153012.HEIC", "2021_05/plain.heic"])
        self.assertEqual(self.row("plain.heic")["date_source"], org.SRC_MTIME)

    def test_damaged_heic_is_still_organised_with_a_note(self):
        self.put("IMG_20190704_153012.HEIC", heic_bytes(TIFF)[:60])
        self.go()
        row = self.row("IMG_20190704_153012.HEIC")
        self.assertEqual((row["status"], row["date_source"]), ("completed", org.SRC_FILENAME))
        self.assertIn("EXIF unreadable", row["details"])

    def test_identical_heic_copies_are_detected(self):
        data = heic_bytes(TIFF)
        self.put("a.heic", data)
        self.put("copy.heic", data)
        self.go()
        self.assertEqual(self.outfiles(), ["2019_07/a.heic"])
        self.assertEqual(self.row("copy.heic")["status"], "skipped_identical")

    def test_extensions_setting_can_exclude_heic(self):
        self.put("a.heic", heic_bytes(TIFF))
        self.put("b.jpg", jpeg_bytes())
        self.go(extensions=".jpg", use_filesystem_mtime="no")
        self.assertEqual(self.row("a.heic")["status"], "skipped_extension")
        self.assertTrue((self.root / "unknown_files.csv").exists())

    def test_copy_is_byte_identical(self):
        data = heic_bytes(TIFF) + b"\x07" * 5000
        self.put("a.heic", data)
        self.go()
        self.assertEqual((self.out / "2019_07" / "a.heic").read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
