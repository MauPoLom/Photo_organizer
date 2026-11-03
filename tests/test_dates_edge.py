"""Edge cases: date formats, limits of the sanity checks, offsets, file-name dates."""
import unittest
from datetime import datetime, timedelta, timezone

import photo_organizer as org
from tests.helpers import NOW, Base

LIMITS = {"min_year": 1990, "reject_future": True}


class ParseExifDatetime(unittest.TestCase):
    def test_accepted_formats(self):
        d = datetime(2019, 7, 4, 15, 30, 12)
        cases = {
            "2019:07:04 15:30:12": (d, None),
            "2019-07-04 15:30:12": (d, None),
            "2019:07:04T15:30:12": (d, None),
            "2019:07:04 15:30:12.45": (d, None),
            "2019:07:04 15:30:12Z": (d, timedelta(0)),
            "2019:07:04 15:30:12 +0200": (d, timedelta(hours=2)),
            "2019:07:04 15:30:12+02:00": (d, timedelta(hours=2)),
            "2019:07:04 15:30:12-05:30": (d, -timedelta(hours=5, minutes=30)),
        }
        for raw, expected in cases.items():
            self.assertEqual(org.parse_exif_datetime(raw), expected, raw)

    def test_rejected_values(self):
        for raw in ("", "2019:02:30 10:00:00", "2019:07:04 24:00:00", "2019:07:04", "15:30:12",
                    "2019:07:04 15:30", "20190704153012", "0000:00:00 00:00:00", "2019:07:04 15:30:12 +25:00x"):
            self.assertIsNone(org.parse_exif_datetime(raw), raw)

    def test_invalid_offset_is_dropped_but_date_kept(self):
        parsed = org.parse_exif_datetime("2019:07:04 15:30:12+99:99")
        self.assertEqual(parsed, (datetime(2019, 7, 4, 15, 30, 12), None))


class SanityLimits(unittest.TestCase):
    def problem(self, dt):
        return org.sanity_problem(dt, LIMITS, NOW)

    def test_lower_limit_is_the_first_instant_of_min_year(self):
        self.assertIsNone(self.problem(datetime(1990, 1, 1)))
        self.assertIn("before year 1990", self.problem(datetime(1989, 12, 31, 23, 59, 59)))

    def test_upper_limit_is_now_plus_one_day(self):
        self.assertIsNone(self.problem(NOW))
        self.assertIsNone(self.problem(NOW + timedelta(days=1)))
        self.assertEqual(self.problem(NOW + timedelta(days=1, seconds=1)), "in the future")

    def test_future_check_can_be_disabled(self):
        self.assertIsNone(org.sanity_problem(datetime(2099, 1, 1), {"min_year": 1990, "reject_future": False}, NOW))

    def test_min_year_is_configurable(self):
        self.assertIsNone(org.sanity_problem(datetime(1950, 6, 1), {"min_year": 1900, "reject_future": True}, NOW))


class Offsets(unittest.TestCase):
    def test_format_recorded(self):
        dt = datetime(2019, 7, 4, 15, 30, 12)
        self.assertEqual(org.format_recorded(dt, None), "2019-07-04 15:30:12")
        self.assertEqual(org.format_recorded(dt, timedelta(hours=2)), "2019-07-04 15:30:12+02:00")
        self.assertEqual(org.format_recorded(dt, -timedelta(hours=5, minutes=30)), "2019-07-04 15:30:12-05:30")
        self.assertEqual(org.format_recorded(dt, timedelta(0)), "2019-07-04 15:30:12+00:00")

    def test_utc_conversion_rolls_the_date_backwards_and_forwards(self):
        self.assertEqual(org.to_basis(datetime(2019, 7, 5, 0, 30), timedelta(hours=2), "utc"),
                         datetime(2019, 7, 4, 22, 30))
        self.assertEqual(org.to_basis(datetime(2019, 12, 31, 23, 30), timedelta(hours=-5), "utc"),
                         datetime(2020, 1, 1, 4, 30))

    def test_unknown_offset_is_never_converted(self):
        dt = datetime(2019, 7, 4, 23, 59)
        for mode in org.TIMEZONE_MODES:
            self.assertEqual(org.to_basis(dt, None, mode), dt)

    def test_epoch_with_negative_and_zero_offset(self):
        dt = datetime(2019, 7, 4, 15, 30, 12)
        self.assertEqual(org.epoch_of(dt, timedelta(0)), datetime(2019, 7, 4, 15, 30, 12, tzinfo=timezone.utc).timestamp())
        self.assertEqual(org.epoch_of(dt, -timedelta(hours=5)),
                         datetime(2019, 7, 4, 20, 30, 12, tzinfo=timezone.utc).timestamp())

    def test_parse_offset_variants(self):
        cases = {"+02:00": timedelta(hours=2), "-0530": -timedelta(hours=5, minutes=30), "+14:00": timedelta(hours=14),
                 "z": None, " +02:00 ": timedelta(hours=2), "+2:00": None, "+02:60": None, "+15:00": None, None: None}
        for raw, expected in cases.items():
            self.assertEqual(org.parse_offset(raw), expected, raw)


class FilenameDates(unittest.TestCase):
    def test_leap_days(self):
        self.assertEqual(org.date_from_filename("IMG_20200229.jpg"), (datetime(2020, 2, 29), False))
        self.assertIsNone(org.date_from_filename("IMG_20190229.jpg"))

    def test_first_valid_date_wins(self):
        self.assertEqual(org.date_from_filename("20190230_20190304.jpg"), (datetime(2019, 3, 4), False))
        self.assertEqual(org.date_from_filename("IMG_20190704_vs_20200101.jpg"), (datetime(2019, 7, 4), False))

    def test_garbage_time_falls_back_to_the_date(self):
        self.assertEqual(org.date_from_filename("20190704_256012.jpg"), (datetime(2019, 7, 4), False))
        self.assertEqual(org.date_from_filename("20190704_240000.jpg"), (datetime(2019, 7, 4), False))

    def test_separators(self):
        expected = (datetime(2019, 7, 4, 15, 30, 12), True)
        for name in ("2019-07-04_15-30-12.jpg", "2019.07.04 15.30.12.jpg", "2019_07_04-15_30_12.jpg",
                     "2019-07-04T15:30:12.jpg", "20190704T153012.jpg", "IMG_2019-07-04_15-30-12.jpg"):
            self.assertEqual(org.date_from_filename(name), expected, name)

    def test_surrounding_digits_prevent_a_match(self):
        for name in ("120190704.jpg", "201907041.jpg", "IMG_0020190704.jpg", "1562254212345.jpg"):
            self.assertIsNone(org.date_from_filename(name), name)

    def test_years_outside_1900_2099_are_not_dates(self):
        self.assertIsNone(org.date_from_filename("18990704.jpg"))
        self.assertIsNone(org.date_from_filename("21000704.jpg"))

    def test_only_the_file_name_is_used_not_the_folder(self):
        self.assertIsNone(org.date_from_filename("holiday.jpg"))


class ChooseDateEdge(Base):
    def choose(self, exif=None, name="IMG.jpg", **kw):
        conf = dict(min_year=1990, reject_future=True, use_filename_date=True, use_modify_date=False, use_mtime=True)
        conf.update(kw)
        path = self.put(name, b"x", datetime(2022, 3, 3, 10).timestamp())
        return org.choose_date(path, exif or {}, conf, NOW)

    def test_digitized_is_used_when_original_is_rejected(self):
        c = self.choose({"DateTimeOriginal": "2099:01:01 00:00:00", "DateTimeDigitized": "2018:05:05 05:05:05"})
        self.assertEqual(c.source, org.SRC_DIGITIZED)
        self.assertTrue(any("DateTimeOriginal" in n and "rejected" in n for n in c.notes))

    def test_filename_date_can_be_switched_off(self):
        self.assertEqual(self.choose({}, "20190704_153012.jpg", use_filename_date=False).source, org.SRC_MTIME)

    def test_modify_date_uses_its_own_offset_tag(self):
        c = self.choose({"DateTime": "2021:05:05 05:05:05", "OffsetTime": "-03:00"}, use_modify_date=True)
        self.assertEqual((c.source, c.offset), (org.SRC_MODIFIED, -timedelta(hours=3)))

    def test_original_does_not_borrow_the_wrong_offset_tag(self):
        c = self.choose({"DateTimeOriginal": "2019:07:04 15:30:12", "OffsetTime": "+09:00"})
        self.assertIsNone(c.offset)

    def test_blank_values_are_silent_but_garbage_is_reported(self):
        quiet = self.choose({"DateTimeOriginal": "    :  :     :  :  "})
        self.assertEqual(quiet.notes, [])
        noisy = self.choose({"DateTimeOriginal": "last tuesday"})
        self.assertTrue(any("unparseable" in n for n in noisy.notes))

    def test_unknown_when_nothing_is_usable(self):
        c = self.choose({}, "photo.jpg", use_mtime=False)
        self.assertEqual((c.dt, c.source, c.has_time), (None, org.SRC_UNKNOWN, False))

    def test_filename_without_time_has_no_time_flag(self):
        c = self.choose({}, "IMG-20190704-WA0001.jpg")
        self.assertEqual((c.source, c.has_time, c.dt), (org.SRC_FILENAME, False, datetime(2019, 7, 4)))


if __name__ == "__main__":
    unittest.main()
