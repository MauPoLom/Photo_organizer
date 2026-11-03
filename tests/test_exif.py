"""EXIF reading from JPEG and PNG."""



import photo_organizer as org

from tests.helpers import BMP, Base, exif_jpeg, jpeg_bytes, make_tiff, png_bytes


class ExifReading(Base):
    def read(self, data, name="x.jpg"):
        return org.read_exif_dates(self.put(name, data))

    def test_little_and_big_endian_jpeg(self):
        for endian in "<>":
            tags, warn = self.read(exif_jpeg("2019:07:04 15:30:12", "2019:07:04 15:30:13", "2019:07:05 08:00:00",
                                            "+02:00", endian))
            self.assertEqual(warn, "")
            self.assertEqual(tags["DateTimeOriginal"], "2019:07:04 15:30:12")
            self.assertEqual(tags["DateTimeDigitized"], "2019:07:04 15:30:13")
            self.assertEqual(tags["DateTime"], "2019:07:05 08:00:00")
            self.assertEqual(tags["OffsetTimeOriginal"], "+02:00")

    def test_xmp_app1_before_exif_is_skipped(self):
        tags, _ = self.read(exif_jpeg("2019:07:04 15:30:12", xmp_first=True))
        self.assertEqual(tags["DateTimeOriginal"], "2019:07:04 15:30:12")

    def test_png_exif_before_and_after_idat(self):
        tiff = make_tiff({}, {0x9003: "2020:01:02 03:04:05"})
        for after in (False, True):
            tags, warn = self.read(png_bytes(tiff, after), "x.png")
            self.assertEqual((tags["DateTimeOriginal"], warn), ("2020:01:02 03:04:05", ""))

    def test_no_exif_bmp_and_wrong_content(self):
        self.assertEqual(self.read(jpeg_bytes()), ({}, ""))
        self.assertEqual(self.read(png_bytes(), "x.png"), ({}, ""))
        self.assertEqual(self.read(BMP, "x.bmp"), ({}, ""))
        self.assertIn("unrecognised", self.read(b"not an image")[1])
        self.assertIn("unrecognised", self.read(b"")[1])

    def test_corrupt_exif_gives_warning_not_exception(self):
        good = exif_jpeg("2019:07:04 15:30:12")
        self.assertIn("EXIF unreadable", self.read(good[:40])[1])
        self.assertIn("EXIF unreadable", self.read(jpeg_bytes(b"II*\x00\xff\xff\xff\x7f"))[1])
        self.assertIn("EXIF unreadable", self.read(jpeg_bytes(b"XX" + b"\x00" * 10))[1])
