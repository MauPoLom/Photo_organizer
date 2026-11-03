"""The transfer step: hashing, verification, atomic publish, move safety, cleanup of temp files."""
import hashlib
import os
import shutil
from unittest import mock

import photo_organizer as org
from tests.helpers import Base, exif_jpeg


class TransferBase(Base):
    def setUp(self):
        super().setUp()
        self.out.mkdir()
        self.dest = self.out / "sub" / "a.jpg"

    def leftovers(self):
        return [p.name for p in self.dest.parent.iterdir() if p.name.startswith(org.TEMP_PREFIX)] \
            if self.dest.parent.exists() else []


class CopyHashing(TransferBase):
    def test_returns_sha256_of_the_copied_bytes_and_keeps_mtime(self):
        src = self.put("a.jpg", b"hello" * 1000, mtime=1_500_000_000)
        temp = self.out / "t.tmp"
        digest = org.copy_hashing(src, temp)
        self.assertEqual(digest, hashlib.sha256(b"hello" * 1000).hexdigest())
        self.assertEqual(temp.read_bytes(), b"hello" * 1000)
        self.assertEqual(int(temp.stat().st_mtime), 1_500_000_000)

    def test_files_larger_than_one_chunk(self):
        data = os.urandom(org.CHUNK * 2 + 123)
        src = self.put("big.jpg", data)
        temp = self.out / "t.tmp"
        self.assertEqual(org.copy_hashing(src, temp), hashlib.sha256(data).hexdigest())
        self.assertEqual(temp.read_bytes(), data)

    def test_empty_file(self):
        src = self.put("empty.jpg", b"")
        self.assertEqual(org.copy_hashing(src, self.out / "t.tmp"), hashlib.sha256(b"").hexdigest())


class Copy(TransferBase):
    def test_copy_keeps_the_source_and_creates_parent_folders(self):
        src = self.put("a.jpg", b"payload")
        digest = org.transfer(src, self.dest, True, True, None)
        self.assertEqual(digest, hashlib.sha256(b"payload").hexdigest())
        self.assertEqual(self.dest.read_bytes(), b"payload")
        self.assertTrue(src.exists())
        self.assertEqual(self.leftovers(), [])

    def test_modification_time_is_preserved_without_epoch(self):
        src = self.put("a.jpg", b"x", mtime=1_500_000_000)
        org.transfer(src, self.dest, True, True, None)
        self.assertEqual(int(self.dest.stat().st_mtime), 1_500_000_000)

    def test_epoch_sets_the_destination_mtime_only(self):
        src = self.put("a.jpg", b"x", mtime=1_500_000_000)
        org.transfer(src, self.dest, True, True, 1_562_247_012)
        self.assertEqual(int(self.dest.stat().st_mtime), 1_562_247_012)
        self.assertEqual(int(src.stat().st_mtime), 1_500_000_000)

    def test_verify_off_skips_the_second_read(self):
        src = self.put("a.jpg", b"x")
        with mock.patch.object(org, "sha256") as sha:
            org.transfer(src, self.dest, True, False, None)
        sha.assert_not_called()
        self.assertTrue(self.dest.exists())

    def test_verify_on_reads_the_copy_once(self):
        src = self.put("a.jpg", b"x")
        with mock.patch.object(org, "sha256", side_effect=org.sha256) as sha:
            org.transfer(src, self.dest, True, True, None)
        self.assertEqual(sha.call_count, 1)


class NeverOverwrites(TransferBase):
    def test_existing_destination_is_kept(self):
        src = self.put("a.jpg", b"new")
        self.dest.parent.mkdir()
        self.dest.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            org.transfer(src, self.dest, True, True, None)
        self.assertEqual(self.dest.read_bytes(), b"existing")
        self.assertEqual(self.leftovers(), [])

    def test_destination_that_appears_during_the_copy(self):
        src = self.put("a.jpg", b"mine")

        def racer(source, target):
            with open(target, "wb") as f:  # somebody else publishes first
                f.write(b"theirs")
            raise FileExistsError(target)

        with mock.patch.object(org.os, "link", side_effect=racer):
            with self.assertRaises(FileExistsError):
                org.transfer(src, self.dest, True, True, None)
        self.assertEqual(self.dest.read_bytes(), b"theirs")
        self.assertEqual(self.leftovers(), [])


class FilesystemsWithoutHardLinks(TransferBase):
    """FAT, exFAT and some network shares: the finished temporary file is renamed into place."""

    def no_links(self):
        return mock.patch.object(org.os, "link", side_effect=OSError("hard links not supported"))

    def test_falls_back_to_a_rename(self):
        src = self.put("a.jpg", b"payload", mtime=1_500_000_000)
        with self.no_links():
            digest = org.transfer(src, self.dest, True, True, None)
        self.assertEqual(self.dest.read_bytes(), b"payload")
        self.assertEqual(digest, hashlib.sha256(b"payload").hexdigest())
        self.assertEqual(int(self.dest.stat().st_mtime), 1_500_000_000)
        self.assertEqual(self.leftovers(), [])
        self.assertTrue(src.exists())

    def test_the_final_name_never_holds_a_partial_file(self):
        src = self.put("a.jpg", b"x" * 100_000)
        real_rename = os.rename
        seen = {}

        def watching(old, new):
            seen["dest_existed"] = os.path.lexists(new)
            seen["size_of_temp"] = os.path.getsize(old)
            return real_rename(old, new)

        with self.no_links(), mock.patch.object(org.os, "rename", watching):
            org.transfer(src, self.dest, True, True, None)
        self.assertEqual(seen, {"dest_existed": False, "size_of_temp": 100_000})

    def test_a_full_disk_while_copying_leaves_nothing_under_the_final_name(self):
        src = self.put("a.jpg", b"x" * 100_000)

        def disk_full(source, temp):
            temp.write_bytes(b"x" * 40_000)  # half of the data lands on disk ...
            raise OSError(28, "No space left on device")  # ... then the disk is full

        with self.no_links(), mock.patch.object(org, "copy_hashing", disk_full):
            with self.assertRaises(OSError):
                org.transfer(src, self.dest, True, True, None)
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.leftovers(), [])

    def test_a_full_disk_while_publishing_leaves_nothing_under_the_final_name(self):
        """0.3.0 copied the verified file a second time, straight to the final name, and left half of it behind."""
        src = self.put("a.jpg", b"x" * 100_000)

        def disk_full(fsrc, fdst, length=0):
            fdst.write(fsrc.read(40_000))
            fdst.flush()
            raise OSError(28, "No space left on device")

        with self.no_links(), mock.patch.object(shutil, "copyfileobj", disk_full):
            try:
                org.transfer(src, self.dest, True, True, None)
            except OSError:
                pass
        if self.dest.exists():  # either nothing was published, or what carries the final name is complete
            self.assertEqual(self.dest.stat().st_size, 100_000, "a truncated file carries the final name")
        self.assertEqual(self.leftovers(), [])

    def test_ctrl_c_just_before_publishing_leaves_nothing_under_the_final_name(self):
        src = self.put("a.jpg", b"payload")
        with self.no_links(), mock.patch.object(org.os, "rename", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                org.transfer(src, self.dest, True, True, None)
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.leftovers(), [])
        self.assertTrue(src.exists())

    def test_a_file_that_appears_in_the_meantime_is_not_replaced(self):
        src = self.put("a.jpg", b"mine")

        def racer(source, target):
            with open(target, "wb") as f:
                f.write(b"theirs")
            raise OSError("hard links not supported")

        with mock.patch.object(org.os, "link", side_effect=racer):
            with self.assertRaises(FileExistsError):
                org.transfer(src, self.dest, True, True, None)
        self.assertEqual(self.dest.read_bytes(), b"theirs")
        self.assertEqual(self.leftovers(), [])

    def test_move_without_hard_links(self):
        src = self.put("a.jpg", b"payload")
        with self.no_links():
            org.transfer(src, self.dest, False, True, None)
        self.assertFalse(src.exists())
        self.assertEqual(self.dest.read_bytes(), b"payload")
        self.assertEqual(self.leftovers(), [])

    def test_whole_run_on_a_drive_without_hard_links(self):
        for i in range(4):  # four different photos with the same name in the same month
            self.put(f"d{i}/IMG_0001.jpg", exif_jpeg(f"2019:07:0{i + 1} 15:30:12"))
        with self.no_links():
            self.go()
        self.assertEqual(self.code, 0)
        self.assertEqual(self.outfiles(), ["2019_07/IMG_0001.jpg", "2019_07/IMG_0001_001.jpg",
                                           "2019_07/IMG_0001_002.jpg", "2019_07/IMG_0001_003.jpg"])
        self.assertEqual(sorted(p.name for p in self.out.rglob(org.TEMP_PREFIX + "*")), [])


class Verification(TransferBase):
    def test_copy_mismatch_publishes_nothing(self):
        src = self.put("a.jpg", b"payload")
        with mock.patch.object(org, "sha256", return_value="f" * 64):
            with self.assertRaisesRegex(OSError, "mismatch"):
                org.transfer(src, self.dest, True, True, None)
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.leftovers(), [])
        self.assertTrue(src.exists())

    def test_source_that_changed_since_it_was_hashed(self):
        src = self.put("a.jpg", b"content")
        with self.assertRaisesRegex(OSError, "changed"):
            org.transfer(src, self.dest, False, True, None, known_digest="0" * 64)
        self.assertTrue(src.exists())
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.leftovers(), [])


class Move(TransferBase):
    def test_source_is_removed_only_after_publish(self):
        src = self.put("a.jpg", b"payload")
        org.transfer(src, self.dest, False, True, None)
        self.assertFalse(src.exists())
        self.assertEqual(self.dest.read_bytes(), b"payload")

    def test_existing_destination_keeps_the_source(self):
        src = self.put("a.jpg", b"payload")
        self.dest.parent.mkdir()
        self.dest.write_bytes(b"other")
        with self.assertRaises(FileExistsError):
            org.transfer(src, self.dest, False, True, None)
        self.assertTrue(src.exists())

    def test_source_modified_during_the_move_is_never_deleted(self):
        src = self.put("a.jpg", b"payload")
        real = org.sha256
        calls = {"n": 0}

        def second_call_differs(path):
            calls["n"] += 1
            return real(path) if calls["n"] == 1 else "0" * 64  # 2nd call re-hashes the source

        with mock.patch.object(org, "sha256", side_effect=second_call_differs):
            with self.assertRaisesRegex(OSError, "changed during move"):
                org.transfer(src, self.dest, False, True, None)
        self.assertTrue(src.exists())
        self.assertTrue(self.dest.exists())  # the verified copy is kept, nothing is lost
        self.assertEqual(self.leftovers(), [])

    def test_move_rereads_the_source_once_more_than_a_copy(self):
        src = self.put("a.jpg", b"x")
        with mock.patch.object(org, "sha256", side_effect=org.sha256) as sha:
            org.transfer(src, self.dest, False, True, None)
        self.assertEqual(sha.call_count, 2)  # verify the temp file, re-check the source
