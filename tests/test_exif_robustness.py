"""The EXIF reader must survive any damaged or unusual file without raising."""
import random
import struct

import photo_organizer as org
from tests.helpers import Base, exif_jpeg, jpeg_bytes, make_tiff, png_bytes, png_chunk

FULL_TAGS = {0x9003: "2019:07:04 15:30:12", 0x9004: "2019:07:04 15:30:13", 0x9011: "+02:00"}


def tiff_with_bad_ascii_offset():
    """Exif IFD whose DateTimeOriginal points far outside the data."""
    header = b"II" + struct.pack("<HI", 42, 8)
    ifd0 = struct.pack("<H", 1) + struct.pack("<HHII", 0x8769, 4, 1, 8 + 2 + 12 + 4) + struct.pack("<I", 0)
    sub = struct.pack("<H", 1) + struct.pack("<HHII", 0x9003, 2, 20, 0xFFFFF) + struct.pack("<I", 0)
    return header + ifd0 + sub


class Truncation(Base):
    def read(self, data, name="x.jpg"):
        return org.read_exif_dates(self.put(name, data))

    def check_all_prefixes(self, data, name):
        for n in range(len(data) + 1):
            tags, warning = self.read(data[:n], name)
            self.assertIsInstance(tags, dict, f"prefix {n}")
            self.assertIsInstance(warning, str, f"prefix {n}")

    def test_every_prefix_of_a_jpeg(self):
        self.check_all_prefixes(exif_jpeg("2019:07:04 15:30:12", "2019:07:04 15:30:13", "2019:07:05 08:00:00", "+02:00"),
                                "x.jpg")

    def test_every_prefix_of_a_png(self):
        self.check_all_prefixes(png_bytes(make_tiff({}, FULL_TAGS), exif_after_idat=True), "x.png")

    def test_full_file_is_still_read_after_the_loop(self):
        tags, warning = self.read(exif_jpeg("2019:07:04 15:30:12"))
        self.assertEqual((tags["DateTimeOriginal"], warning), ("2019:07:04 15:30:12", ""))


class Corruption(Base):
    def test_random_byte_flips_in_a_jpeg(self):
        rng = random.Random(20260421)
        original = exif_jpeg("2019:07:04 15:30:12", "2019:07:04 15:30:13", "2019:07:05 08:00:00", "+02:00")
        for i in range(400):
            data = bytearray(original)
            for _ in range(rng.randint(1, 6)):
                data[rng.randrange(len(data))] = rng.randrange(256)
            tags, warning = org.read_exif_dates(self.put(f"f{i}.jpg", bytes(data)))
            self.assertIsInstance(tags, dict)
            self.assertIsInstance(warning, str)

    def test_random_byte_flips_in_a_tiff_block(self):
        rng = random.Random(7)
        original = make_tiff({0x0132: "2019:07:05 08:00:00"}, FULL_TAGS)
        for _ in range(600):
            data = bytearray(original)
            for _ in range(rng.randint(1, 5)):
                data[rng.randrange(len(data))] = rng.randrange(256)
            try:
                result = org.parse_tiff_dates(bytes(data))
            except org.ExifError:
                continue  # the only allowed failure
            self.assertIsInstance(result, dict)

    def test_pure_noise_as_tiff(self):
        rng = random.Random(99)
        for _ in range(400):
            buf = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 90)))
            for prefix in (b"", b"II*\x00\x08\x00\x00\x00", b"MM\x00*\x00\x00\x00\x08"):
                try:
                    org.parse_tiff_dates(prefix + buf)
                except org.ExifError:
                    pass


class OddButValidStructures(Base):
    def read(self, data, name="x.jpg"):
        return org.read_exif_dates(self.put(name, data))

    def test_fill_bytes_before_a_marker(self):
        tiff = make_tiff({}, {0x9003: "2019:07:04 15:30:12"})
        payload = b"Exif\x00\x00" + tiff
        data = b"\xff\xd8" + b"\xff\xff\xff" + b"\xe1" + struct.pack(">H", len(payload) + 2) + payload + b"\xff\xd9"
        self.assertEqual(self.read(data)[0]["DateTimeOriginal"], "2019:07:04 15:30:12")

    def test_standalone_markers_are_skipped(self):
        tiff = make_tiff({}, {0x9003: "2019:07:04 15:30:12"})
        payload = b"Exif\x00\x00" + tiff
        data = b"\xff\xd8" + b"\xff\x01" + b"\xff\xd0" + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
        self.assertEqual(self.read(data)[0]["DateTimeOriginal"], "2019:07:04 15:30:12")

    def test_exif_after_start_of_scan_is_not_metadata(self):
        tiff = make_tiff({}, {0x9003: "2019:07:04 15:30:12"})
        payload = b"Exif\x00\x00" + tiff
        data = b"\xff\xd8\xff\xda\x00\x02" + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
        self.assertEqual(self.read(data), ({}, ""))

    def test_first_exif_segment_wins(self):
        first = b"Exif\x00\x00" + make_tiff({}, {0x9003: "2019:07:04 15:30:12"})
        second = b"Exif\x00\x00" + make_tiff({}, {0x9003: "2001:01:01 01:01:01"})
        data = (b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(first) + 2) + first
                + b"\xff\xe1" + struct.pack(">H", len(second) + 2) + second)
        self.assertEqual(self.read(data)[0]["DateTimeOriginal"], "2019:07:04 15:30:12")

    def test_format_is_detected_by_content_not_extension(self):
        tiff = make_tiff({}, {0x9003: "2020:01:02 03:04:05"})
        self.assertEqual(self.read(png_bytes(tiff), "really_a_png.jpg")[0]["DateTimeOriginal"], "2020:01:02 03:04:05")
        self.assertEqual(self.read(exif_jpeg("2019:07:04 15:30:12"), "really_a_jpeg.png")[0]["DateTimeOriginal"],
                         "2019:07:04 15:30:12")

    def test_png_exif_with_exif_prefix(self):
        tiff = make_tiff({}, {0x9003: "2020:01:02 03:04:05"})
        data = b"".join([org.PNG_SIGNATURE, png_chunk(b"IHDR", b"\x00" * 13),
                          png_chunk(b"eXIf", b"Exif\x00\x00" + tiff), png_chunk(b"IEND", b"")])
        self.assertEqual(self.read(data, "x.png")[0]["DateTimeOriginal"], "2020:01:02 03:04:05")

    def test_png_chunk_claiming_to_be_huge(self):
        data = org.PNG_SIGNATURE + struct.pack(">I4s", 0x7FFFFFFF, b"IDAT") + b"\x00" * 10
        self.assertEqual(self.read(data, "x.png"), ({}, ""))

    def test_png_exif_chunk_over_the_size_limit(self):
        data = org.PNG_SIGNATURE + struct.pack(">I4s", 17 * 1024 * 1024, b"eXIf")
        tags, warning = self.read(data, "x.png")
        self.assertEqual(tags, {})
        self.assertIn("too large", warning)

    def test_ascii_value_pointing_outside_the_data_is_ignored(self):
        tags, warning = self.read(jpeg_bytes(tiff_with_bad_ascii_offset()))
        self.assertEqual((tags, warning), ({}, ""))

    def test_ifd_entry_count_larger_than_the_data(self):
        header = b"II" + struct.pack("<HI", 42, 8)
        data = header + struct.pack("<H", 0xFFFF) + b"\x00" * 6
        self.assertEqual(self.read(jpeg_bytes(data))[0], {})

    def test_ifd0_offset_outside_the_data(self):
        data = b"II" + struct.pack("<HI", 42, 0x7FFFFFF)
        tags, warning = self.read(jpeg_bytes(data))
        self.assertEqual(tags, {})
        self.assertIn("IFD offset outside", warning)

    def test_non_ascii_bytes_in_a_date_value(self):
        tiff = make_tiff({}, {0x9003: "2019:07:04 15:30:12"})
        broken = tiff.replace(b"2019:07:04 15:30:12", b"\xff\xfe19:07:04 15:30:12")
        tags, _ = self.read(jpeg_bytes(broken))
        self.assertIn("DateTimeOriginal", tags)
        self.assertIsNone(org.parse_exif_datetime(tags["DateTimeOriginal"]))

    def test_value_with_nul_padding_and_spaces(self):
        self.assertIsNotNone(org.parse_exif_datetime("  2019:07:04 15:30:12\x00\x00 "))
