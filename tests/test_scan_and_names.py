"""Scanning, hidden-file detection, duplicate index, destination names, empty-folder cleanup."""
import os
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import photo_organizer as org
from tests.helpers import BMP, Base, exif_jpeg, jpeg_bytes, png_bytes


class IsHidden(unittest.TestCase):
    def test_dot_names(self):
        self.assertTrue(org.is_hidden(".DS_Store", SimpleNamespace()))
        self.assertTrue(org.is_hidden("._IMG_0001.jpg", SimpleNamespace()))  # macOS AppleDouble
        self.assertFalse(org.is_hidden("IMG.jpg", SimpleNamespace()))

    def test_windows_attributes(self):
        self.assertTrue(org.is_hidden("x.jpg", SimpleNamespace(st_file_attributes=0x2)))  # hidden
        self.assertTrue(org.is_hidden("x.jpg", SimpleNamespace(st_file_attributes=0x4)))  # system
        self.assertTrue(org.is_hidden("x.jpg", SimpleNamespace(st_file_attributes=0x2 | 0x20)))
        self.assertFalse(org.is_hidden("x.jpg", SimpleNamespace(st_file_attributes=0x20)))  # archive only
        self.assertFalse(org.is_hidden("x.jpg", SimpleNamespace(st_file_attributes=0)))

    def test_macos_flag(self):
        self.assertTrue(org.is_hidden("x.jpg", SimpleNamespace(st_flags=0x8000)))
        self.assertTrue(org.is_hidden("x.jpg", SimpleNamespace(st_flags=0x8000 | 0x1)))
        self.assertFalse(org.is_hidden("x.jpg", SimpleNamespace(st_flags=0x1)))
        self.assertFalse(org.is_hidden("x.jpg", SimpleNamespace(st_flags=0)))


class Scan(Base):
    def scan(self, **kw):
        conf = {"input": self.inp, "skip_hidden": True, "recursive": True,
                "extensions": {".jpg", ".jpeg", ".png", ".bmp"}}
        conf.update(kw)
        return [(p.relative_to(self.inp).as_posix(), status) for p, status, _ in org.scan(conf)]

    def test_deterministic_order_case_insensitive_with_folders_inline(self):
        for name in ("b.jpg", "A.jpg", "c.png"):
            self.put(name, b"x")
        self.put("bb/x.jpg", b"x")
        self.assertEqual([n for n, _ in self.scan()], ["A.jpg", "b.jpg", "bb/x.jpg", "c.png"])

    def test_extensions_are_case_insensitive(self):
        for name in ("a.JPG", "b.JPEG", "c.Png", "d.BMP"):
            self.put(name, b"x")
        self.assertEqual({s for _, s in self.scan()}, {None})

    def test_hidden_folder_is_reported_once_and_not_entered(self):
        self.put(".cache/deep/x.jpg", b"x")
        self.put("visible/y.jpg", b"x")
        self.assertEqual(self.scan(), [(".cache", "skipped_hidden"), ("visible/y.jpg", None)])

    def test_hidden_folder_is_entered_when_skip_hidden_is_off(self):
        self.put(".cache/x.jpg", b"x")
        self.assertEqual(self.scan(skip_hidden=False), [(".cache/x.jpg", None)])

    def test_non_recursive_ignores_sub_folders_silently(self):
        self.put("a.jpg", b"x")
        self.put("sub/b.jpg", b"x")
        self.assertEqual(self.scan(recursive=False), [("a.jpg", None)])

    def test_unsupported_and_extensionless_files(self):
        self.put("clip.mp4", b"x")
        self.put("README", b"x")
        self.put("img.avif", b"x")
        self.assertEqual(self.scan(), [("clip.mp4", "skipped_extension"), ("img.avif", "skipped_extension"),
                                       ("README", "skipped_extension")])

    def test_extension_set_limits_what_is_processed(self):
        self.put("a.jpg", b"x")
        self.put("b.png", b"x")
        self.assertEqual(self.scan(extensions={".png"}), [("a.jpg", "skipped_extension"), ("b.png", None)])

    def test_unreadable_folder_is_an_error_row_not_a_crash(self):
        self.put("locked/x.jpg", b"x")
        self.put("ok.jpg", b"x")
        real = os.scandir

        def fake(path):
            if Path(path).name == "locked":
                raise PermissionError("denied")
            return real(path)

        with mock.patch.object(org.os, "scandir", fake):
            result = self.scan()
        self.assertEqual(result, [("locked", "error"), ("ok.jpg", None)])

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlinks")
    def test_symlinked_folder_is_not_followed(self):
        self.put("real/x.jpg", b"x")
        try:
            os.symlink(self.inp / "real", self.inp / "alias", target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation not permitted")
        self.assertEqual(self.scan(), [("alias", "skipped_symlink"), ("real/x.jpg", None)])


class UniqueDestination(Base):
    def test_free_name_is_used_as_is(self):
        self.assertEqual(org.unique_destination(self.out, "a.jpg", set()), self.out / "a.jpg")

    def test_counter_sequence_and_padding(self):
        self.out.mkdir()
        (self.out / "a.jpg").write_bytes(b"x")
        reserved = set()
        names = []
        for _ in range(3):
            dest = org.unique_destination(self.out, "a.jpg", reserved)
            names.append(dest.name)
            reserved.add(os.path.normcase(str(dest)))
        self.assertEqual(names, ["a_001.jpg", "a_002.jpg", "a_003.jpg"])

    def test_counter_grows_past_three_digits(self):
        reserved = {os.path.normcase(str(self.out / "a.jpg"))}
        reserved |= {os.path.normcase(str(self.out / f"a_{n:03d}.jpg")) for n in range(1, 1000)}
        self.assertEqual(org.unique_destination(self.out, "a.jpg", reserved).name, "a_1000.jpg")

    def test_names_with_several_dots_keep_the_extension(self):
        reserved = {os.path.normcase(str(self.out / "trip.day1.jpg"))}
        self.assertEqual(org.unique_destination(self.out, "trip.day1.jpg", reserved).name, "trip.day1_001.jpg")

    def test_reserved_names_count_even_if_not_on_disk(self):
        reserved = {os.path.normcase(str(self.out / "a.jpg"))}
        self.assertEqual(org.unique_destination(self.out, "a.jpg", reserved).name, "a_001.jpg")

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlinks")
    def test_broken_symlink_blocks_the_name(self):
        self.out.mkdir()
        try:
            os.symlink(self.root / "missing", self.out / "a.jpg")
        except OSError:
            self.skipTest("symlink creation not permitted")
        self.assertEqual(org.unique_destination(self.out, "a.jpg", set()).name, "a_001.jpg")


class ContentIndexTests(Base):
    def test_different_sizes_never_hash_anything(self):
        a = self.put("a.jpg", b"1234")
        index = org.ContentIndex()
        index.add(5, self.root / "other", self.out / "other.jpg")
        with mock.patch.object(org, "sha256") as sha:
            self.assertEqual(index.find_identical(a, 4), (None, None))
        sha.assert_not_called()

    def test_identical_content_is_found_and_labelled(self):
        a = self.put("a.jpg", b"same!")
        b = self.put("b.jpg", b"same!")
        index = org.ContentIndex()
        index.add(5, b, self.out / "b.jpg")
        label, digest = index.find_identical(a, 5)
        self.assertEqual(label, self.out / "b.jpg")
        self.assertEqual(digest, org.sha256(a))

    def test_same_size_different_content_returns_the_source_digest_for_reuse(self):
        a = self.put("a.jpg", b"aaaaa")
        b = self.put("b.jpg", b"bbbbb")
        index = org.ContentIndex()
        index.add(5, b, self.out / "b.jpg")
        label, digest = index.find_identical(a, 5)
        self.assertIsNone(label)
        self.assertEqual(digest, org.sha256(a))

    def test_candidate_hashes_are_cached(self):
        a = self.put("a.jpg", b"aaaaa")
        c = self.put("c.jpg", b"ccccc")
        b = self.put("b.jpg", b"bbbbb")
        index = org.ContentIndex()
        index.add(5, b, self.out / "b.jpg")
        real = org.sha256
        with mock.patch.object(org, "sha256", side_effect=real) as sha:
            index.find_identical(a, 5)
            index.find_identical(c, 5)
        hashed = [call.args[0] for call in sha.call_args_list]
        self.assertEqual(hashed.count(b), 1)

    def test_unreadable_candidate_never_matches(self):
        a = self.put("a.jpg", b"aaaaa")
        index = org.ContentIndex()
        index.add(5, self.root / "vanished.jpg", self.out / "vanished.jpg")
        self.assertEqual(index.find_identical(a, 5)[0], None)

    def test_build_index_filters_files(self):
        self.out.mkdir()
        (self.out / "2019_07").mkdir()
        (self.out / "2019_07" / "a.jpg").write_bytes(b"1")
        (self.out / "2019_07" / "notes.txt").write_bytes(b"2")
        (self.out / "2019_07" / (org.TEMP_PREFIX + "abc.tmp")).write_bytes(b"3")
        (self.out / "2019_07" / (org.TEMP_PREFIX + "abc.jpg")).write_bytes(b"4")
        (self.out / "b.PNG").write_bytes(b"5")
        conf = {"output": self.out, "extensions": {".jpg", ".png"}}
        index = org.build_index(conf)
        labels = sorted(entry[1].name for entries in index._by_size.values() for entry in entries)
        self.assertEqual(labels, ["a.jpg", "b.PNG"])

    def test_build_index_of_missing_output_is_empty(self):
        self.assertEqual(org.build_index({"output": self.out, "extensions": {".jpg"}})._by_size, {})


class RemoveEmptyFolders(Base):
    def test_removes_the_emptied_chain_but_stops_at_a_folder_with_other_content(self):
        deep = self.inp / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (self.inp / "a" / "keep.txt").write_bytes(b"x")
        removed = org.remove_empty_folders({deep}, self.inp)
        self.assertEqual(removed, [deep, deep.parent])
        self.assertTrue((self.inp / "a").is_dir())
        self.assertFalse((self.inp / "a" / "b").exists())

    def test_never_removes_the_root(self):
        sub = self.inp / "only"
        sub.mkdir()
        removed = org.remove_empty_folders({sub, self.inp}, self.inp)
        self.assertEqual(removed, [sub])
        self.assertTrue(self.inp.is_dir())

    def test_non_empty_start_is_left_alone(self):
        sub = self.inp / "sub"
        sub.mkdir()
        (sub / "x.jpg").write_bytes(b"x")
        self.assertEqual(org.remove_empty_folders({sub}, self.inp), [])
        self.assertTrue((sub / "x.jpg").exists())

    def test_folders_outside_the_root_are_never_touched(self):
        outside = self.root / "elsewhere"
        outside.mkdir()
        self.assertEqual(org.remove_empty_folders({outside}, self.inp), [])
        self.assertTrue(outside.is_dir())

    def test_shared_parent_is_handled_once(self):
        a, b = self.inp / "trip" / "d1", self.inp / "trip" / "d2"
        a.mkdir(parents=True)
        b.mkdir()
        removed = org.remove_empty_folders({a, b}, self.inp)
        self.assertEqual(sorted(p.name for p in removed), ["d1", "d2", "trip"])
        self.assertTrue(self.inp.is_dir())


class TargetName(unittest.TestCase):
    def choice(self, source, has_time=True):
        return org.DateChoice(datetime(2019, 7, 4, 15, 30, 12), None, source, has_time)

    def run_target(self, name, source, pattern, has_time=True, basis=datetime(2019, 7, 4, 15, 30, 12)):
        return org.target_name(Path(name), self.choice(source, has_time), basis, pattern)

    def test_no_pattern_keeps_the_name(self):
        self.assertEqual(self.run_target("IMG_1.JPG", org.SRC_ORIGINAL, ""), ("IMG_1.JPG", ""))

    def test_capture_sources_are_renamed_and_the_suffix_case_is_kept(self):
        for source in (org.SRC_ORIGINAL, org.SRC_DIGITIZED):
            name, note = self.run_target("IMG_1.JPG", source, "%Y%m%d_%H%M%S")
            self.assertEqual((name, note), ("20190704_153012.JPG", ""))

    def test_original_placeholder(self):
        self.assertEqual(self.run_target("IMG_1.jpg", org.SRC_ORIGINAL, "%Y-%m-%d_{original}")[0],
                         "2019-07-04_IMG_1.jpg")

    def test_filename_source_needs_a_time(self):
        self.assertEqual(self.run_target("x.jpg", org.SRC_FILENAME, "%H%M", has_time=True)[0], "1530.jpg")
        name, note = self.run_target("x.jpg", org.SRC_FILENAME, "%H%M", has_time=False)
        self.assertEqual(name, "x.jpg")
        self.assertIn("kept original name", note)

    def test_fallback_sources_never_rename(self):
        for source in (org.SRC_MODIFIED, org.SRC_MTIME, org.SRC_UNKNOWN):
            name, note = self.run_target("x.jpg", source, "%Y", basis=None if source == org.SRC_UNKNOWN else datetime(2019, 1, 1))
            self.assertEqual(name, "x.jpg", source)
            self.assertIn("kept original name", note)


class ScanThroughRun(Base):
    """A few full runs that depend on what scan() reports."""

    def test_only_supported_formats_in_a_mixed_folder(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("b.png", png_bytes())
        self.put("c.bmp", BMP)
        self.put("d.jpeg", jpeg_bytes())
        for unsupported in ("e.gif", "f.tif", "g.avif", "h.mp4", "i.cr3", "j.webp"):
            self.put(unsupported, b"x")
        self.go()
        self.assertEqual(sum(1 for r in self.rows() if r["status"] == "completed"), 4)
        self.assertEqual(sum(1 for r in self.rows() if r["status"] == "skipped_extension"), 6)


if __name__ == "__main__":
    unittest.main()
