"""Cross-check the stand-alone EXIF reader against files written by Pillow.

Pillow is NOT needed to run the program. These tests exist only to prove that files produced by an
independent writer are read correctly; they are skipped when Pillow is not installed.
"""
import os
import unittest
from pathlib import Path

import photo_organizer as org
from tests.helpers import Base

try:
    from PIL import Image
except ImportError:  # pragma: no cover - depends on the environment
    Image = None

TAGS = {
    "DateTime": "2019:07:05 08:00:00",
    "DateTimeOriginal": "2019:07:04 15:30:12",
    "DateTimeDigitized": "2019:07:04 15:30:13",
    "OffsetTime": "+01:00",
    "OffsetTimeOriginal": "+02:00",
    "OffsetTimeDigitized": "-05:30",
}


@unittest.skipIf(Image is None, "Pillow is not installed (optional, test-only)")
class PillowInterop(Base):
    def exif(self, with_other_tags=False):
        exif = Image.Exif()
        exif[0x0132] = TAGS["DateTime"]
        if with_other_tags:
            exif[0x010F] = "ACME"  # Make
            exif[0x0110] = "Camera 9000"  # Model
            exif[0x0112] = 6  # Orientation
        sub = exif.get_ifd(0x8769)
        sub[0x9003] = TAGS["DateTimeOriginal"]
        sub[0x9004] = TAGS["DateTimeDigitized"]
        sub[0x9010] = TAGS["OffsetTime"]
        sub[0x9011] = TAGS["OffsetTimeOriginal"]
        sub[0x9012] = TAGS["OffsetTimeDigitized"]
        return exif

    def image(self, name, fmt, exif=None, size=(64, 48)):
        path = self.inp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        kwargs = {"exif": exif} if exif is not None else {}
        Image.new("RGB", size, (200, 30, 30)).save(path, fmt, **kwargs)
        return path

    def test_jpeg_tags(self):
        tags, warning = org.read_exif_dates(self.image("a.jpg", "JPEG", self.exif()))
        self.assertEqual((tags, warning), (TAGS, ""))

    def test_png_tags(self):
        tags, warning = org.read_exif_dates(self.image("a.png", "PNG", self.exif()))
        self.assertEqual((tags, warning), (TAGS, ""))

    def test_other_tags_do_not_confuse_the_reader(self):
        tags, _ = org.read_exif_dates(self.image("a.jpg", "JPEG", self.exif(with_other_tags=True)))
        self.assertEqual(tags, TAGS)

    def test_large_image_with_exif(self):
        tags, _ = org.read_exif_dates(self.image("big.jpg", "JPEG", self.exif(), size=(1500, 1000)))
        self.assertEqual(tags["DateTimeOriginal"], TAGS["DateTimeOriginal"])

    def test_images_without_exif(self):
        self.assertEqual(org.read_exif_dates(self.image("plain.jpg", "JPEG")), ({}, ""))
        self.assertEqual(org.read_exif_dates(self.image("plain.png", "PNG")), ({}, ""))

    def test_bmp_has_no_metadata(self):
        self.assertEqual(org.read_exif_dates(self.image("a.bmp", "BMP")), ({}, ""))

    def test_a_jpeg_exif_survives_pillow_resaving_with_the_same_exif(self):
        first = self.image("a.jpg", "JPEG", self.exif())
        second = self.inp / "b.jpg"
        with Image.open(first) as im:
            im.save(second, "JPEG", exif=im.getexif())
        tags, _ = org.read_exif_dates(second)
        self.assertEqual(tags["DateTimeOriginal"], TAGS["DateTimeOriginal"])

    def test_whole_run_on_pillow_files(self):
        self.image("a.jpg", "JPEG", self.exif())
        self.image("b.png", "PNG", self.exif())
        bmp = self.image("c.bmp", "BMP")
        os.utime(bmp, (1_620_000_000, 1_620_000_000))  # 2021-05-03: a fixed date for the fallback
        self.image("Screenshot_20210315-091500.png", "PNG")
        self.go(rename_by_date="%Y%m%d_%H%M%S_{original}", change_timestamp="yes")
        self.assertEqual(self.outfiles(), ["2019_07/20190704_153012_a.jpg", "2019_07/20190704_153012_b.png",
                                           "2021_03/20210315_091500_Screenshot_20210315-091500.png",
                                           "2021_05/c.bmp"])
        self.assertEqual(self.row("a.jpg")["date_source"], org.SRC_ORIGINAL)
        self.assertEqual(self.row("c.bmp")["date_source"], org.SRC_MTIME)

    def test_avif_written_by_libavif_is_read_by_the_heif_reader(self):
        """AVIF shares HEIC's box structure (ftyp, meta, iinf, iloc, Exif item) and has an independent writer."""
        try:
            path = self.image("a.avif", "AVIF", self.exif())
        except (KeyError, ValueError, OSError):  # this Pillow build has no AVIF encoder
            self.skipTest("Pillow cannot write AVIF here")
        tags, warning = org.read_exif_dates(path)
        self.assertEqual((tags, warning), (TAGS, ""))
        big, _ = org.read_exif_dates(self.image("big.avif", "AVIF", self.exif(), size=(1200, 900)))
        self.assertEqual(big, TAGS)

    def test_sanitised_android_fixture_is_valid_exif_for_pillow(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "IMG20260715143429.jpg"
        with Image.open(fixture) as im:
            exif = im.getexif()
            sub = exif.get_ifd(0x8769)
            self.assertEqual(exif.get(0x0132), "2026:07:15 14:34:29")
            self.assertEqual(sub.get(0x9003), "2026:07:15 14:34:29")
            self.assertEqual(sub.get(0x9011), "+02:00")
            self.assertEqual(sorted(exif.keys()), [0x0132, 0x8769])  # only the date and the pointer to the Exif sub-IFD
            self.assertFalse(exif.get_ifd(0x8825))  # no GPS

    def test_organized_files_are_still_valid_images(self):
        self.image("a.jpg", "JPEG", self.exif())
        self.image("b.png", "PNG", self.exif())
        self.go()
        for path in self.out.rglob("*"):
            if path.is_file():
                with self.subTest(path.name), Image.open(path) as im:
                    im.verify()


if __name__ == "__main__":
    unittest.main()
