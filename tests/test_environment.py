"""The environment report: OS and Python version in every test log, and run_tests.py."""
import os
import platform
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import photo_organizer as org
from tools import environment as env

REPO = Path(__file__).resolve().parent.parent


def fake_winreg(values):
    """A stand-in for the Windows registry module: values maps (key, name) to a value; anything else is missing."""
    class Handle:
        def __init__(self, key):
            self.key = key

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    module = types.ModuleType("winreg")
    module.HKEY_LOCAL_MACHINE = "HKLM"
    module.OpenKey = lambda root, key: Handle(key)

    def query(handle, name):
        if (handle.key, name) not in values:
            raise FileNotFoundError(name)
        return values[(handle.key, name)], 4

    module.QueryValueEx = query
    return module


VERSION_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
FILESYSTEM_KEY = r"SYSTEM\CurrentControlSet\Control\FileSystem"


class Describe(unittest.TestCase):
    def test_the_report_names_the_operating_system_and_python(self):
        items = dict(env.describe())
        self.assertIn(platform.python_version(), items["Python"])
        self.assertIn(platform.python_implementation(), items["Python"])
        self.assertTrue(items["Operating system"])
        self.assertNotIn("unknown (", items["Operating system"])
        self.assertIn(org.__version__, items["Program"])

    def test_every_expected_line_is_present_and_a_single_line(self):
        items = env.describe()
        labels = [label for label, _ in items]
        for expected in ("Run started", "Program", "Operating system", "Python", "Python executable", "Time zone",
                         "Encodings", "Temporary folder", "Its file system", "Long paths (Windows)", "Hard links",
                         "Symlinks", "Pillow (optional)"):
            with self.subTest(expected):
                self.assertIn(expected, labels)
        for label, value in items:
            with self.subTest(label):
                self.assertTrue(value)
                self.assertNotIn("\n", value)

    def test_header_has_one_line_per_item_in_aligned_columns(self):
        items = env.describe()
        lines = env.format_header(items).splitlines()
        self.assertEqual(len(lines), len(items) + 2)
        self.assertTrue(all(" : " in line for line in lines[1:-1]))
        self.assertEqual(len({line.index(" : ") for line in lines[1:-1]}), 1)

    def test_one_line_summary(self):
        line = env.one_line()
        self.assertNotIn("\n", line)
        self.assertTrue(line.startswith("Tested on: "))
        self.assertIn(f"Python {platform.python_version()}", line)
        self.assertIn(f"photo_organizer {org.__version__}", line)

    def test_time_zone_format(self):
        self.assertRegex(env.time_zone(), r"^.+ \(UTC[+-]\d\d:\d\d\)$")

    def test_a_failing_probe_never_breaks_the_report(self):
        with mock.patch.object(env, "os_description", side_effect=RuntimeError("boom")), \
                mock.patch.object(env.tempfile, "gettempdir", side_effect=OSError("no temp folder")):
            items = dict(env.describe())
        self.assertIn("unknown (RuntimeError: boom)", items["Operating system"])
        self.assertIn("unknown (OSError: no temp folder)", items["Temporary folder"])
        self.assertIn(platform.python_version(), items["Python"])  # the rest is still reported


class OperatingSystems(unittest.TestCase):
    def test_windows_names(self):
        self.assertEqual(env.windows_name(10, 0, 19045), "Windows 10")
        self.assertEqual(env.windows_name(10, 0, 21999), "Windows 10")
        self.assertEqual(env.windows_name(10, 0, 22000), "Windows 11")
        self.assertEqual(env.windows_name(10, 0, 26100), "Windows 11")
        self.assertEqual(env.windows_name(6, 3, 9600), "Windows 6.3")

    def windows(self, build=26100, registry=None, edition="Professional", machine="AMD64"):
        info = SimpleNamespace(major=10, minor=0, build=build, platform_version=(10, 0, build))
        edition_patch = mock.patch.object(platform, "win32_edition", return_value=edition) if edition else \
            mock.patch.object(platform, "win32_edition", side_effect=OSError("no edition"))
        return (mock.patch.object(sys, "platform", "win32"), mock.patch.object(sys, "getwindowsversion", create=True,
                                                                              return_value=info),
                edition_patch, mock.patch.object(platform, "machine", return_value=machine),
                mock.patch.dict(sys.modules, {"winreg": fake_winreg(registry or {})}))

    def describe_windows(self, **kwargs):
        patches = self.windows(**kwargs)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return env.os_description()

    def test_windows_11_with_version_revision_and_edition(self):
        text = self.describe_windows(registry={(VERSION_KEY, "DisplayVersion"): "24H2", (VERSION_KEY, "UBR"): 2605})
        self.assertEqual(text, "Windows 11 24H2 (build 26100.2605, Professional, AMD64)")

    def test_windows_10_without_registry_details(self):
        text = self.describe_windows(build=19045, edition=None)
        self.assertEqual(text, "Windows 10 (build 19045, AMD64)")

    def test_an_unreadable_registry_does_not_matter(self):
        broken = fake_winreg({})
        broken.OpenKey = mock.Mock(side_effect=PermissionError("denied"))
        patches = self.windows()[:4] + (mock.patch.dict(sys.modules, {"winreg": broken}),)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.assertEqual(env.os_description(), "Windows 11 (build 26100, Professional, AMD64)")

    def test_long_paths_switch(self):
        cases = {1: "on", 0: "off (paths over 259 characters fail)"}
        for value, expected in cases.items():
            with self.subTest(value), mock.patch.object(sys, "platform", "win32"), \
                    mock.patch.dict(sys.modules, {"winreg": fake_winreg({(FILESYSTEM_KEY, "LongPathsEnabled"): value})}):
                self.assertEqual(env.long_paths(), expected)

    def test_long_paths_setting_that_does_not_exist_counts_as_off(self):
        with mock.patch.object(sys, "platform", "win32"), mock.patch.dict(sys.modules, {"winreg": fake_winreg({})}):
            self.assertEqual(env.long_paths(), "off (setting not present; paths over 259 characters fail)")

    def test_long_paths_is_not_applicable_elsewhere(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertIn("not applicable", env.long_paths())

    def test_macos(self):
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(platform, "mac_ver", return_value=("15.1", ("", "", ""), "arm64")), \
                mock.patch.object(platform, "machine", return_value="arm64"):
            self.assertEqual(env.os_description(), "macOS 15.1 (arm64)")

    def test_linux_uses_the_pretty_name_from_os_release(self):
        text = 'NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\nVERSION_ID="24.04"\n'
        with mock.patch.object(sys, "platform", "linux"), mock.patch("builtins.open", mock.mock_open(read_data=text)), \
                mock.patch.object(platform, "release", return_value="6.8.0-45"), \
                mock.patch.object(platform, "machine", return_value="x86_64"):
            self.assertEqual(env.os_description(), "Ubuntu 24.04.1 LTS (kernel 6.8.0-45, x86_64)")

    def test_linux_without_os_release(self):
        with mock.patch.object(sys, "platform", "linux"), mock.patch("builtins.open", side_effect=FileNotFoundError), \
                mock.patch.object(platform, "release", return_value="5.4"), \
                mock.patch.object(platform, "machine", return_value="aarch64"):
            self.assertEqual(env.os_description(), "Linux (kernel 5.4, aarch64)")

    def test_other_systems_use_the_platform_string(self):
        with mock.patch.object(sys, "platform", "freebsd14"), mock.patch.object(platform, "platform", return_value="FreeBSD-14"), \
                mock.patch.object(platform, "machine", return_value="amd64"):
            self.assertEqual(env.os_description(), "FreeBSD-14 (amd64)")

    def test_a_failing_lookup_gives_a_note_not_an_exception(self):
        with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(platform, "mac_ver", side_effect=OSError("x")):
            self.assertIn("details unavailable", env.os_description())

    def test_parse_os_release(self):
        parsed = env.parse_os_release('# comment\nNAME="Debian GNU/Linux"\nID=debian\nPRETTY_NAME=\'Debian 12\'\n\nbroken line\n')
        self.assertEqual(parsed, {"NAME": "Debian GNU/Linux", "ID": "debian", "PRETTY_NAME": "Debian 12"})

    def test_file_system_type_from_the_mount_table(self):
        mounts = textwrap.dedent("""\
            overlay / overlay rw 0 0
            /dev/sda1 /mnt/data ext4 rw 0 0
            /dev/sdb1 /mnt/data/usb exfat rw 0 0
            /dev/sdc1 /mnt/photos\\040backup ntfs3 rw 0 0
            """)
        self.assertEqual(env.fs_type_from_mounts(mounts, "/tmp/x"), "overlay")
        self.assertEqual(env.fs_type_from_mounts(mounts, "/mnt/data/a"), "ext4")
        self.assertEqual(env.fs_type_from_mounts(mounts, "/mnt/data/usb/photos"), "exfat")
        self.assertEqual(env.fs_type_from_mounts(mounts, "/mnt/data/usb"), "exfat")
        self.assertEqual(env.fs_type_from_mounts(mounts, "/mnt/photos backup/x"), "ntfs3")
        self.assertEqual(env.fs_type_from_mounts(mounts, "/mnt/database"), "overlay")  # not a path inside /mnt/data
        self.assertIsNone(env.fs_type_from_mounts("", "/x"))


class Probes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = self._tmp.name

    def test_hard_links(self):
        self.assertTrue(env.probe_hard_links(self.folder).startswith(("yes", "no")))

    def test_hard_links_unsupported(self):
        with mock.patch.object(env.os, "link", side_effect=OSError(1, "Operation not permitted")):
            text = env.probe_hard_links(self.folder)
        self.assertTrue(text.startswith("no ("))
        self.assertIn("rename fallback", text)

    def test_symlinks_allowed(self):
        with mock.patch.object(env.os, "symlink"):
            self.assertEqual(env.probe_symlinks(self.folder), "allowed")

    def test_symlinks_not_permitted_on_windows_mentions_developer_mode(self):
        with mock.patch.object(env.os, "symlink", side_effect=OSError(1314, "A required privilege is not held")), \
                mock.patch.object(sys, "platform", "win32"):
            text = env.probe_symlinks(self.folder)
        self.assertIn("not permitted", text)
        self.assertIn("Developer Mode", text)
        self.assertIn("skipped", text)

    def test_symlinks_not_permitted_elsewhere_has_no_windows_hint(self):
        with mock.patch.object(env.os, "symlink", side_effect=OSError(1, "no")), mock.patch.object(sys, "platform", "linux"):
            self.assertNotIn("Developer Mode", env.probe_symlinks(self.folder))

    def test_describe_removes_the_folder_it_probes_in(self):
        created = []
        real = tempfile.TemporaryDirectory

        class Tracking(real):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self.name)

        with mock.patch.object(env.tempfile, "TemporaryDirectory", Tracking):
            env.describe()
        self.assertEqual(len(created), 1)
        self.assertFalse(os.path.exists(created[0]), "the probe folder with its hard link and symlink was left behind")

    def test_pillow_missing(self):
        with mock.patch.dict(sys.modules, {"PIL": None}):
            text = env.pillow_status()
        self.assertIn("not installed", text)
        self.assertIn("skipped", text)

    def test_pillow_present(self):
        fake = types.ModuleType("PIL")
        fake.__version__ = "11.2.1"
        fake.features = SimpleNamespace(check=lambda name: name == "avif")
        with mock.patch.dict(sys.modules, {"PIL": fake, "PIL.features": fake.features}):
            self.assertEqual(env.pillow_status(), "11.2.1 (AVIF writing: yes)")

    def test_pillow_without_the_feature_check(self):
        fake = types.ModuleType("PIL")
        fake.__version__ = "8.0"
        fake.features = SimpleNamespace(check=mock.Mock(side_effect=ValueError("unknown feature")))
        with mock.patch.dict(sys.modules, {"PIL": fake, "PIL.features": fake.features}):
            self.assertIn("8.0", env.pillow_status())

    def test_encodings_line(self):
        text = env.encodings()
        self.assertIn("file names", text)
        self.assertIn("UTF-8 mode", text)


class TheTestLog(unittest.TestCase):
    """What a person sees when they run the tests."""

    def run_unittest(self, extra_env=None):
        child_env = {k: v for k, v in os.environ.items() if k != "PHOTO_ORGANIZER_ENV_REPORTED"}
        child_env.update(extra_env or {})
        return subprocess.run([sys.executable, "-m", "unittest", "tests.test_release.Version.test_changelog_has_an_unreleased_section"],
                              cwd=REPO, capture_output=True, text=True, encoding="utf-8", env=child_env, timeout=120)

    def test_plain_unittest_prints_the_environment_once_and_a_recap_at_the_end(self):
        result = self.run_unittest()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("Test environment"), 1)
        self.assertIn(platform.python_version(), result.stderr)
        self.assertTrue(result.stderr.rstrip().splitlines()[-1].startswith("Tested on: "))

    def test_the_header_is_skipped_when_it_was_already_printed(self):
        result = self.run_unittest({"PHOTO_ORGANIZER_ENV_REPORTED": "1"})
        self.assertNotIn("Test environment", result.stderr)
        self.assertNotIn("Tested on:", result.stderr)


class RunTestsScript(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.report = self.folder / "report.txt"

    def write_tests(self, body):
        (self.folder / "test_demo.py").write_text(textwrap.dedent(body), encoding="utf-8")

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(REPO / "run_tests.py"), "--start-dir", str(self.folder),
                               "--report", str(self.report), *args], capture_output=True, text=True,
                              encoding="utf-8", timeout=120)

    def test_a_passing_run(self):
        self.write_tests("""
            import unittest
            class Demo(unittest.TestCase):
                def test_one(self): pass
                def test_two(self): pass
        """)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.report.read_text(encoding="utf-8")
        self.assertIn("Test environment", report)
        self.assertIn(platform.python_version(), report)
        self.assertIn("Result   : OK", report)
        self.assertIn("2 run, 2 passed, 0 failed, 0 errors, 0 skipped", report)
        self.assertIn("test_one (test_demo.Demo.test_one) ... ok", report)  # verbose by default
        self.assertTrue(report.rstrip().splitlines()[-2].startswith("Tested on: "))
        self.assertIn("Report written to", report)
        self.assertEqual(result.stderr.strip().splitlines()[0], report.splitlines()[0])  # console shows the same

    def test_failures_skips_and_errors_are_summarised(self):
        self.write_tests("""
            import unittest
            class Demo(unittest.TestCase):
                def test_ok(self): pass
                def test_fails(self): self.assertEqual(1, 2)
                def test_breaks(self): raise RuntimeError("boom")
                @unittest.skip("needs a symlink")
                def test_skipped_a(self): pass
                @unittest.skip("needs a symlink")
                def test_skipped_b(self): pass
                @unittest.skip("Pillow is not installed")
                def test_skipped_c(self): pass
        """)
        result = self.run_script("--brief")
        self.assertEqual(result.returncode, 1)
        report = self.report.read_text(encoding="utf-8")
        self.assertIn("Result   : FAILED", report)
        self.assertIn("6 run, 1 passed, 1 failed, 1 errors, 3 skipped", report)
        self.assertIn("  2 x needs a symlink", report)
        self.assertIn("  1 x Pillow is not installed", report)
        self.assertIn("test_demo.Demo.test_fails", report.split("Failed   :")[1])
        self.assertIn("test_demo.Demo.test_breaks", report.split("Errors   :")[1])
        self.assertIn("Traceback", report)  # the full details are in the report too
        self.assertNotIn("test_ok (test_demo", report)  # --brief: dots, not one line per test

    def test_no_tests_found_is_a_failure_not_a_green_result(self):
        result = self.run_script("--brief")  # an empty folder, as after a mistyped --pattern
        self.assertEqual(result.returncode, 5)
        report = self.report.read_text(encoding="utf-8")
        self.assertIn("Result   : NO TESTS FOUND", report)
        self.assertIn("No tests were found in", report)
        self.assertIn("Test environment", report)

    @unittest.skipUnless(sys.version_info >= (3, 12), "unittest reports durations from Python 3.12")
    def test_durations_are_listed_on_request(self):
        self.write_tests("""
            import time, unittest
            class Demo(unittest.TestCase):
                def test_slowish(self): time.sleep(0.05)
        """)
        self.run_script("--brief", "--durations", "3")
        self.assertIn("Slowest test durations", self.report.read_text(encoding="utf-8"))

    def test_the_default_report_is_called_test_report(self):
        text = (REPO / "run_tests.py").read_text(encoding="utf-8")
        self.assertIn('"test-report.txt"', text)

    def test_unicode_in_test_names_survives_in_the_report(self):
        self.write_tests("""
            import unittest
            class Demo(unittest.TestCase):
                @unittest.skip("geen rechten voor symlinks (\\u00e9\\u2600)")
                def test_a(self): pass
        """)
        self.run_script("--brief")
        self.assertIn("geen rechten voor symlinks (\u00e9\u2600)", self.report.read_text(encoding="utf-8"))


class ToolsReportTheirEnvironment(unittest.TestCase):
    def test_inspect_tool_starts_with_the_environment_line(self):
        sample = REPO / "tests" / "fixtures" / "IMG_9347.HEIC"
        result = subprocess.run([sys.executable, str(REPO / "tools" / "inspect_exif.py"), str(sample)],
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertTrue(result.stdout.startswith("Tested on: "))
        self.assertIn(f"Python {platform.python_version()}", result.stdout.splitlines()[0])

    def test_windows_check_starts_with_the_environment_line(self):
        result = subprocess.run([sys.executable, str(REPO / "tools" / "check_windows_creation_time.py")],
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertTrue(result.stdout.startswith("Tested on: "))

    def test_the_tools_help_does_not_need_the_environment(self):
        result = subprocess.run([sys.executable, str(REPO / "tools" / "inspect_exif.py"), "--help"],
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Tested on:", result.stdout)


class Documentation(unittest.TestCase):
    def test_readme_and_contributing_explain_the_report(self):
        for name in ("README.md", "CONTRIBUTING.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            with self.subTest(name):
                self.assertIn("run_tests.py", text)
        self.assertIn("test-report.txt", (REPO / "README.md").read_text(encoding="utf-8"))

    def test_the_report_file_is_ignored_by_git_and_packaged_script_is_listed(self):
        self.assertIn("test-report.txt", (REPO / ".gitignore").read_text(encoding="utf-8").splitlines())
        self.assertIn("run_tests.py", (REPO / "MANIFEST.in").read_text(encoding="utf-8"))

    def test_every_environment_line_is_described_in_the_readme(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for label, _ in env.describe():
            with self.subTest(label):
                self.assertIn(label, readme)


if __name__ == "__main__":
    unittest.main()
