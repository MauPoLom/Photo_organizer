"""Configuration loading: defaults, parsing, path handling and validation errors."""
import configparser
import os
import textwrap
from unittest import mock

import photo_organizer as org
from tests.helpers import Base


class ConfigBase(Base):
    def write(self, text, name="config.ini", folder=None):
        folder = folder or self.root
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        return path

    def minimal(self, extra=""):
        return self.write(f"[folders]\ninput_folder = {self.inp}\noutput_folder = {self.out}\n{extra}")


class Defaults(ConfigBase):
    def test_only_the_folders_are_required(self):
        c = org.read_config(self.minimal())
        self.assertEqual(c["structure"], "YYYY_MM")
        self.assertEqual(c["unknown_folder"], "unknown_date")
        self.assertTrue(c["dry_run"])  # safe by default
        self.assertTrue(c["copy"])
        self.assertTrue(c["verify"])
        self.assertFalse(c["change_timestamp"])
        self.assertFalse(c["set_creation_time"])
        self.assertEqual(c["rename_pattern"], "")
        self.assertFalse(c["cleanup"])
        self.assertTrue(c["use_filename_date"])
        self.assertFalse(c["use_modify_date"])
        self.assertTrue(c["use_mtime"])
        self.assertEqual((c["tz_mode"], c["min_year"], c["reject_future"]), ("wallclock", 1990, True))
        self.assertTrue(c["recursive"])
        self.assertEqual(c["duplicates"], "skip_identical")
        self.assertTrue(c["skip_hidden"])
        self.assertEqual(c["extensions"], {".jpg", ".jpeg", ".png", ".bmp", ".heic", ".heif"})
        self.assertTrue(c["report_skipped"])
        self.assertEqual(c["report"].name, "organizer_report.csv")
        self.assertEqual(c["unknown_csv"].name, "unknown_files.csv")


class ExplicitValues(ConfigBase):
    def test_every_option_can_be_set(self):
        path = self.write(f"""
            [folders]
            input_folder = {self.inp}
            output_folder = {self.out}
            [organization]
            output_folderstructure = YYYY/MM/DD
            unknown_date_folder = no_date
            testrun = no
            copy_mode = no
            change_timestamp = yes
            set_creation_time = yes
            verify = yes
            rename_by_date = %Y%m%d_{{original}}
            cleanup_empty_folders = yes
            [dates]
            use_filename_date = no
            use_exif_modify_date = yes
            use_filesystem_mtime = no
            timezone_mode = UTC
            min_year = 1950
            reject_future_dates = no
            [behavior]
            recursive = no
            duplicate_policy = RENAME
            skip_hidden = no
            extensions = .JPG, png
            report_csv = {self.root / 'r.csv'}
            report_skipped = no
            unknown_files_csv = {self.root / 'u.csv'}
        """)
        c = org.read_config(path)
        self.assertEqual((c["structure"], c["unknown_folder"]), ("YYYY/MM/DD", "no_date"))
        self.assertEqual((c["dry_run"], c["copy"], c["change_timestamp"], c["set_creation_time"], c["verify"]),
                         (False, False, True, True, True))
        self.assertEqual((c["rename_pattern"], c["cleanup"]), ("%Y%m%d_{original}", True))
        self.assertEqual((c["use_filename_date"], c["use_modify_date"], c["use_mtime"]), (False, True, False))
        self.assertEqual((c["tz_mode"], c["min_year"], c["reject_future"]), ("utc", 1950, False))
        self.assertEqual((c["recursive"], c["duplicates"], c["skip_hidden"]), (False, "rename", False))
        self.assertEqual(c["extensions"], {".jpg", ".png"})
        self.assertEqual((c["report"].name, c["report_skipped"], c["unknown_csv"].name), ("r.csv", False, "u.csv"))

    def test_all_folder_structures_are_accepted(self):
        for structure in org.STRUCTURES:
            with self.subTest(structure):
                c = org.read_config(self.minimal(f"[organization]\noutput_folderstructure = {structure}\n"))
                self.assertEqual(c["structure"], structure)

    def test_yes_no_spellings(self):
        for text, value in (("yes", True), ("YES", True), ("true", True), ("1", True), ("on", True),
                            ("no", False), ("No", False), ("false", False), ("0", False), ("off", False)):
            with self.subTest(text):
                c = org.read_config(self.minimal(f"[organization]\ntestrun = {text}\n"))
                self.assertEqual(c["dry_run"], value)

    def test_min_year_bounds(self):
        for year in (1900, 2100):
            self.assertEqual(org.read_config(self.minimal(f"[dates]\nmin_year = {year}\n"))["min_year"], year)
        for year in ("1899", "2101", "abc", ""):
            with self.subTest(year), self.assertRaises(ValueError):
                org.read_config(self.minimal(f"[dates]\nmin_year = {year}\n"))

    def test_rename_patterns(self):
        for ok in ("%Y%m%d", "{original}", "%Y-%m-%d_%H%M%S_{original}", "photo_%Y", "%%"):
            with self.subTest(ok):
                self.assertEqual(org.read_config(self.minimal(f"[organization]\nrename_by_date = {ok}\n"))["rename_pattern"], ok)
        for bad in ("bad:name", "%Y/%m", "a*b", "a?b", "a|b", "..", "{original}/x", 'a"b', "a\\b"):
            with self.subTest(bad), self.assertRaises(ValueError):
                org.read_config(self.minimal(f"[organization]\nrename_by_date = {bad}\n"))

    def test_unknown_folder_names(self):
        for bad in ("", ".", "..", "a/b", "a\\b", "a:b"):
            with self.subTest(bad), self.assertRaises(ValueError):
                org.read_config(self.minimal(f"[organization]\nunknown_date_folder = {bad}\n"))


class Extensions(ConfigBase):
    def ext(self, text):
        return org.read_config(self.minimal(f"[behavior]\nextensions = {text}\n"))["extensions"]

    def test_dots_case_and_spaces_are_normalised(self):
        self.assertEqual(self.ext("JPG, .Png ,bmp, HEIC"), {".jpg", ".png", ".bmp", ".heic"})

    def test_unsupported_types_are_refused_with_a_helpful_message(self):
        for text in (".avif", ".jpg,.mp4", ".gif", ".tif", ".cr3", ".webp", ".avi"):
            with self.subTest(text), self.assertRaisesRegex(ValueError, "supports only"):
                self.ext(text)

    def test_empty_list_is_refused(self):
        for text in ("", " , ,"):
            with self.subTest(text), self.assertRaises(ValueError):
                self.ext(text)


class Paths(ConfigBase):
    def test_relative_paths_resolve_against_the_config_file_not_the_working_directory(self):
        project = self.root / "project"
        (project / "in").mkdir(parents=True)
        cfg = self.write("[folders]\ninput_folder = ./in\noutput_folder = ../sorted\n", folder=project)
        old = os.getcwd()
        os.chdir(self.root)
        try:
            c = org.read_config(cfg)
        finally:
            os.chdir(old)
        self.assertEqual(c["input"], (project / "in").resolve())
        self.assertEqual(c["output"], (self.root / "sorted").resolve())
        self.assertEqual(c["report"], (project / "reports" / "organizer_report.csv").resolve())

    def test_environment_variables_and_home_are_expanded(self):
        with mock.patch.dict(os.environ, {"PO_TEST_ROOT": str(self.root)}):
            cfg = self.write("[folders]\ninput_folder = ${PO_TEST_ROOT}/in\noutput_folder = ${PO_TEST_ROOT}/out\n")
            c = org.read_config(cfg)
        self.assertEqual(c["input"], self.inp.resolve())

    def test_missing_config_file_has_a_hint(self):
        with self.assertRaisesRegex(ValueError, r"Config file not found.*config\.example\.ini"):
            org.read_config(self.root / "nope.ini")

    def test_config_file_that_is_a_folder(self):
        with self.assertRaises(ValueError):
            org.read_config(self.root)

    def test_missing_input_folder(self):
        cfg = self.write(f"[folders]\ninput_folder = {self.root / 'missing'}\noutput_folder = {self.out}\n")
        with self.assertRaisesRegex(ValueError, "Input folder does not exist"):
            org.read_config(cfg)

    def test_missing_required_section_or_key_is_a_configparser_error(self):
        with self.assertRaises(configparser.Error):
            org.read_config(self.write("[organization]\ntestrun = yes\n"))
        with self.assertRaises(configparser.Error):
            org.read_config(self.write(f"[folders]\ninput_folder = {self.inp}\n"))

    def test_input_and_output_must_be_separate(self):
        nested_out = self.inp / "sorted"
        parent_out = self.root
        same = self.inp
        for out in (nested_out, parent_out, same):
            with self.subTest(out=out), self.assertRaisesRegex(ValueError, "separate"):
                org.read_config(self.write(f"[folders]\ninput_folder = {self.inp}\noutput_folder = {out}\n"))

    def test_reports_must_not_be_inside_the_input_folder(self):
        for key in ("report_csv", "unknown_files_csv"):
            with self.subTest(key), self.assertRaisesRegex(ValueError, "inside the input"):
                org.read_config(self.minimal(f"[behavior]\n{key} = {self.inp / 'x.csv'}\n"))

    def test_the_two_reports_must_differ(self):
        same = self.root / "same.csv"
        with self.assertRaisesRegex(ValueError, "different"):
            org.read_config(self.minimal(f"[behavior]\nreport_csv = {same}\nunknown_files_csv = {same}\n"))

    def test_reports_may_live_in_the_output_folder(self):
        c = org.read_config(self.minimal(f"[behavior]\nreport_csv = {self.out / 'report.csv'}\n"))
        self.assertEqual(c["report"].parent, self.out.resolve())


class InvalidValues(ConfigBase):
    def test_unknown_choices_are_refused(self):
        bad = [("organization", "output_folderstructure", "DD/MM/YYYY"), ("organization", "output_folderstructure", "yyyy"),
               ("behavior", "duplicate_policy", "error"), ("behavior", "duplicate_policy", "overwrite"),
               ("dates", "timezone_mode", "mars"), ("organization", "testrun", "maybe"),
               ("organization", "copy_mode", "2")]
        for section, key, value in bad:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                org.read_config(self.minimal(f"[{section}]\n{key} = {value}\n"))

    def test_inline_comments_are_not_supported_and_fail_loudly(self):
        # a ';' after a value becomes part of the value; the error makes that visible
        with self.assertRaises(ValueError):
            org.read_config(self.minimal("[organization]\ntestrun = yes ; just testing\n"))

    def test_move_requires_verification(self):
        with self.assertRaisesRegex(ValueError, "verify"):
            org.read_config(self.minimal("[organization]\ncopy_mode = no\nverify = no\n"))
        org.read_config(self.minimal("[organization]\ncopy_mode = yes\nverify = no\n"))

    def test_creation_time_requires_the_timestamp_option(self):
        with self.assertRaisesRegex(ValueError, "change_timestamp"):
            org.read_config(self.minimal("[organization]\nset_creation_time = yes\n"))

    def test_percent_signs_in_values_are_not_interpolated(self):
        c = org.read_config(self.minimal("[organization]\nrename_by_date = %Y%m%d\n"))
        self.assertEqual(c["rename_pattern"], "%Y%m%d")

    def test_non_utf8_config_is_a_clear_error_not_a_traceback(self):
        path = self.root / "bad.ini"
        path.write_bytes(b"[folders]\ninput_folder = \xff\xfe\n")
        with self.assertRaises((ValueError, UnicodeDecodeError)):
            org.read_config(path)
