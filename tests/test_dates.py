"""Date selection, sanity checks, time zones and file-name dates."""

import os
import time
import unittest
from datetime import datetime, timedelta, timezone

import photo_organizer as org

from tests.helpers import NOW, Base


class ChooseDate(Base):
    def choose(self, exif=None, name="IMG.jpg", mtime=None, **kw):
        defaults = dict(min_year=1990, reject_future=True, use_filename_date=True, use_modify_date=False,
                        use_mtime=True)
        defaults.update(kw)
        p = self.put(name, b"x", datetime(2022, 3, 3, 10).timestamp() if mtime is None else mtime)
        return org.choose_date(p, exif or {}, defaults, NOW)

    def test_priority_order(self):
        ex = {"DateTimeOriginal": "2019:07:04 15:30:12", "DateTimeDigitized": "2018:01:01 00:00:00",
              "DateTime": "2021:01:01 00:00:00"}
        self.assertEqual(self.choose(ex, "20100101_101010.jpg").source, org.SRC_ORIGINAL)
        del ex["DateTimeOriginal"]
        self.assertEqual(self.choose(ex, "20100101_101010.jpg").source, org.SRC_DIGITIZED)
        del ex["DateTimeDigitized"]
        self.assertEqual(self.choose(ex, "20100101_101010.jpg").source, org.SRC_FILENAME)
        self.assertEqual(self.choose(ex, "IMG.jpg").source, org.SRC_MTIME)
        self.assertEqual(self.choose(ex, "IMG.jpg", use_modify_date=True).source, org.SRC_MODIFIED)
        self.assertEqual(self.choose(ex, "IMG.jpg", use_mtime=False).source, org.SRC_UNKNOWN)

    def test_modify_date_ignored_by_default(self):
        c = self.choose({"DateTime": "2021:05:05 05:05:05"})
        self.assertEqual(c.source, org.SRC_MTIME)

    def test_sanity_rejections_fall_through_and_explain(self):
        for bad in ("2099:01:01 00:00:00", "1904:01:01 00:00:00", "1970:01:01 00:00:00"):
            c = self.choose({"DateTimeOriginal": bad})
            self.assertEqual(c.source, org.SRC_MTIME, bad)
            self.assertTrue(any("rejected" in n for n in c.notes), bad)
        self.assertEqual(self.choose({"DateTimeOriginal": "2026:10:22 11:00:00"}).source, org.SRC_ORIGINAL)
        self.assertEqual(self.choose({"DateTimeOriginal": "2026:10:23 13:00:00"}).source, org.SRC_MTIME)
        self.assertEqual(self.choose({"DateTimeOriginal": "2099:01:01 00:00:00"}, reject_future=False).source,
                         org.SRC_ORIGINAL)
        self.assertEqual(self.choose({"DateTimeOriginal": "1985:01:01 00:00:00"}, min_year=1980).source,
                         org.SRC_ORIGINAL)

    def test_blank_and_garbage_values(self):
        for raw in ("    :  :     :  :  ", "0000:00:00 00:00:00", "2019:13:45 25:61:61", "yesterday"):
            self.assertEqual(self.choose({"DateTimeOriginal": raw}).source, org.SRC_MTIME, raw)

    def test_mtime_is_sanity_checked_too(self):
        c = self.choose(None, "IMG.jpg", mtime=0)
        self.assertEqual(c.source, org.SRC_UNKNOWN)
        self.assertTrue(any("modification time" in n for n in c.notes))

    def test_timezone_offset_read_from_tags_and_string(self):
        c = self.choose({"DateTimeOriginal": "2019:07:04 15:30:12", "OffsetTimeOriginal": "+02:00"})
        self.assertEqual(c.offset, timedelta(hours=2))
        c = self.choose({"DateTimeOriginal": "2019:07:04 15:30:12-05:30"})
        self.assertEqual(c.offset, -timedelta(hours=5, minutes=30))
        c = self.choose({"DateTimeOriginal": "2019:07:04 15:30:12", "OffsetTimeOriginal": "nonsense"})
        self.assertIsNone(c.offset)

    def test_parse_offset(self):
        self.assertEqual(org.parse_offset("Z"), timedelta(0))
        self.assertEqual(org.parse_offset("+0530"), timedelta(hours=5, minutes=30))
        self.assertIsNone(org.parse_offset("+25:00"))
        self.assertIsNone(org.parse_offset(""))

    def test_epoch_uses_recorded_offset(self):
        dt = datetime(2019, 7, 4, 15, 30, 12)
        expected = datetime(2019, 7, 4, 13, 30, 12, tzinfo=timezone.utc).timestamp()
        self.assertEqual(org.epoch_of(dt, timedelta(hours=2)), expected)

    def test_timezone_modes(self):
        dt, off = datetime(2019, 7, 4, 23, 30, 0), timedelta(hours=-5)
        self.assertEqual(org.to_basis(dt, off, "wallclock"), dt)
        self.assertEqual(org.to_basis(dt, off, "utc"), datetime(2019, 7, 5, 4, 30, 0))
        self.assertEqual(org.to_basis(dt, None, "utc"), dt)  # no offset known: used as-is

    @unittest.skipUnless(hasattr(time, "tzset"), "needs POSIX tzset")
    def test_timezone_local_mode(self):
        old = os.environ.get("TZ")
        self.addCleanup(lambda: (os.environ.__setitem__("TZ", old) if old else os.environ.pop("TZ", None),
                                 time.tzset()))
        os.environ["TZ"] = "Europe/Brussels"  # UTC+2 in July
        time.tzset()
        got = org.to_basis(datetime(2019, 7, 4, 23, 30, 0), timedelta(hours=-5), "local")
        self.assertEqual(got, datetime(2019, 7, 5, 6, 30, 0))

    def test_filename_patterns(self):
        cases = {
            "IMG_20190704_153012.jpg": (datetime(2019, 7, 4, 15, 30, 12), True),
            "PXL_20190704_153012345.jpg": (datetime(2019, 7, 4), False),
            "20190704153012.jpg": (datetime(2019, 7, 4, 15, 30, 12), True),
            "IMG-20190704-WA0001.jpg": (datetime(2019, 7, 4), False),
            "Screenshot_20190704-153012.png": (datetime(2019, 7, 4, 15, 30, 12), True),
            "Screenshot 2019-07-04 at 15.30.12.png": (datetime(2019, 7, 4, 15, 30, 12), True),
            "Screenshot from 2019-07-04 15-30-12.png": (datetime(2019, 7, 4, 15, 30, 12), True),
            "WhatsApp Image 2019-07-04 at 15.30.12.jpeg": (datetime(2019, 7, 4, 15, 30, 12), True),
            "signal-2019-07-04-15-30-12.jpg": (datetime(2019, 7, 4, 15, 30, 12), True),
            "2019_07_04.jpg": (datetime(2019, 7, 4), False),
        }
        for name, expected in cases.items():
            self.assertEqual(org.date_from_filename(name), expected, name)

    def test_filename_non_dates(self):
        for name in ("IMG_0001.jpg", "FB_IMG_1562254212345.jpg", "20191345.jpg", "holiday.jpg",
                     "12019070412345.jpg", "IMG_20190230.jpg"):
            self.assertIsNone(org.date_from_filename(name), name)

    def test_filename_date_sanity(self):
        c = self.choose(None, "IMG_20990101.jpg")
        self.assertEqual(c.source, org.SRC_MTIME)
        self.assertTrue(any("filename date" in n for n in c.notes))
