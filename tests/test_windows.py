"""Windows 'Date created' support (API calls simulated off Windows; real tests on Windows)."""

import contextlib
import os
import unittest
from datetime import datetime, timezone
from unittest import mock

import photo_organizer as org

from tests.helpers import Base, exif_jpeg, png_bytes


class CreationTime(Base):
    def test_to_filetime(self):
        self.assertEqual(org.to_filetime(0), 116444736000000000)
        self.assertEqual(org.to_filetime(1), 116444736010000000)
        self.assertEqual(org.to_filetime(-1), 116444735990000000)  # before 1970 is fine
        self.assertEqual(org.to_filetime(1562247012.5), 116444736000000000 + 15622470125000000)
        with self.assertRaises(ValueError):
            org.to_filetime(-12_000_000_000)  # before 1601

    def test_requires_change_timestamp(self):
        with self.assertRaises(ValueError):
            self.conf(set_creation_time="yes", change_timestamp="no")
        self.assertTrue(self.conf(set_creation_time="yes", change_timestamp="yes")["set_creation_time"])
        self.assertFalse(self.conf()["set_creation_time"])

    def test_ignored_with_warning_outside_windows(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        with mock.patch.object(org, "IS_WINDOWS", False), mock.patch.object(org, "set_creation_time") as fake:
            self.go(set_creation_time="yes", change_timestamp="yes")
        fake.assert_not_called()
        self.assertIn("only supported on Windows", self.stderr)
        self.assertEqual(self.row("a.jpg")["status"], "completed")

    def test_applied_to_capture_dates_only_with_offset(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12", offset="+02:00"))
        self.put("IMG_20180101_010101.png", png_bytes())
        with mock.patch.object(org, "IS_WINDOWS", True), mock.patch.object(org, "set_creation_time") as fake:
            self.go(set_creation_time="yes", change_timestamp="yes")
        self.assertEqual(fake.call_count, 1)
        dest, epoch = fake.call_args[0]
        self.assertEqual(dest, self.out / "2019_07" / "a.jpg")
        self.assertEqual(epoch, datetime(2019, 7, 4, 13, 30, 12, tzinfo=timezone.utc).timestamp())
        self.assertIn("creation time set", self.row("a.jpg")["details"])
        self.assertNotIn("creation", self.row("IMG_20180101_010101.png")["details"])

    def test_testrun_only_plans_it(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        with mock.patch.object(org, "IS_WINDOWS", True), mock.patch.object(org, "set_creation_time") as fake:
            self.go(testrun="yes", set_creation_time="yes", change_timestamp="yes")
        fake.assert_not_called()
        self.assertIn("creation time would be set", self.row("a.jpg")["details"])

    def test_failure_is_a_note_not_an_error(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        with mock.patch.object(org, "IS_WINDOWS", True), \
                mock.patch.object(org, "set_creation_time", side_effect=OSError("access denied")):
            self.go(set_creation_time="yes", change_timestamp="yes", copy_mode="no")
        r = self.row("a.jpg")
        self.assertEqual(r["status"], "completed")
        self.assertIn("creation time not set: access denied", r["details"])
        self.assertTrue((self.out / "2019_07" / "a.jpg").exists())
        self.assertFalse((self.inp / "a.jpg").exists())  # move still completed

    def _run_with_fake_kernel32(self, set_ok=True):
        import ctypes
        k32 = mock.MagicMock()
        k32.CreateFileW.return_value = 1234
        k32.SetFileTime.return_value = 1 if set_ok else 0
        target = self.put("a.jpg", b"x")
        patches = [mock.patch.object(org, "IS_WINDOWS", True),
                   mock.patch.object(ctypes, "WinDLL", create=True, return_value=k32),
                   mock.patch.object(ctypes, "get_last_error", create=True, return_value=5),
                   mock.patch.object(ctypes, "WinError", create=True,
                                     side_effect=lambda code: OSError(f"WinError {code}"))]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            try:
                org.set_creation_time(target, 1562247012.5)
                error = None
            except OSError as exc:
                error = exc
        return k32, target, error

    def test_win32_call_sequence(self):
        k32, target, error = self._run_with_fake_kernel32()
        self.assertIsNone(error)
        args = k32.CreateFileW.call_args[0]
        self.assertEqual(args, (str(target), 0x0100, 7, None, 3, 0x80, None))
        handle, creation, accessed, written = k32.SetFileTime.call_args[0]
        self.assertEqual((handle, accessed, written), (1234, None, None))  # only creation time is passed
        ft = creation._obj
        self.assertEqual((ft.dwHighDateTime << 32) | ft.dwLowDateTime, org.to_filetime(1562247012.5))
        k32.CloseHandle.assert_called_once_with(1234)

    def test_win32_failure_closes_handle(self):
        k32, _target, error = self._run_with_fake_kernel32(set_ok=False)
        self.assertEqual(str(error), "WinError 5")
        k32.CloseHandle.assert_called_once_with(1234)

    def test_win32_open_failure(self):
        import ctypes
        k32 = mock.MagicMock()
        k32.CreateFileW.return_value = ctypes.c_void_p(-1).value  # INVALID_HANDLE_VALUE
        with mock.patch.object(org, "IS_WINDOWS", True), \
                mock.patch.object(ctypes, "WinDLL", create=True, return_value=k32), \
                mock.patch.object(ctypes, "get_last_error", create=True, return_value=2), \
                mock.patch.object(ctypes, "WinError", create=True, side_effect=lambda c: OSError(f"WinError {c}")):
            with self.assertRaises(OSError):
                org.set_creation_time(self.put("a.jpg", b"x"), 0)
        k32.SetFileTime.assert_not_called()

    def test_not_windows_raises(self):
        with mock.patch.object(org, "IS_WINDOWS", False), self.assertRaises(OSError):
            org.set_creation_time(self.put("a.jpg", b"x"), 0)

    @unittest.skipUnless(os.name == "nt", "real Windows API; runs only on Windows")
    def test_real_windows_roundtrip(self):
        p = self.put("real.jpg", b"x", mtime=1_600_000_000)
        target = datetime(2019, 7, 4, 13, 30, 12, tzinfo=timezone.utc).timestamp()
        org.set_creation_time(p, target)
        st = p.stat()
        created = getattr(st, "st_birthtime", st.st_ctime)  # st_ctime is the creation time on Windows < 3.12
        self.assertAlmostEqual(created, target, delta=0.01)
        self.assertEqual(int(st.st_mtime), 1_600_000_000)  # modified time untouched

    @unittest.skipUnless(os.name == "nt", "real Windows API; runs only on Windows")
    def test_real_windows_end_to_end(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12", offset="+02:00"))
        self.go(set_creation_time="yes", change_timestamp="yes")
        st = (self.out / "2019_07" / "a.jpg").stat()
        target = datetime(2019, 7, 4, 13, 30, 12, tzinfo=timezone.utc).timestamp()
        self.assertAlmostEqual(getattr(st, "st_birthtime", st.st_ctime), target, delta=0.01)
        self.assertAlmostEqual(st.st_mtime, target, delta=0.01)
