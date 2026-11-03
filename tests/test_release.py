"""Release hygiene: version, changelog, documentation, example config and packaging must agree."""
import ast
import configparser
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import photo_organizer as org

REPO = Path(__file__).resolve().parent.parent
PATH_KEYS = {"input", "output", "report", "unknown_csv"}


def read(relative):
    return (REPO / relative).read_text(encoding="utf-8")


def config_keys_in_source():
    """(section, key) pairs that read_config() really looks up, observed while it loads the example file."""
    seen = set()
    real_get = configparser.ConfigParser.get

    def spy(self, section, option, *args, **kwargs):
        seen.add((section, option))
        return real_get(self, section, option, *args, **kwargs)

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / "photos_input").mkdir()
        (folder / "config.ini").write_text(read("config.example.ini"), encoding="utf-8")
        with mock.patch.object(configparser.ConfigParser, "get", spy):
            org.read_config(folder / "config.ini")
    return seen


class Version(unittest.TestCase):
    def test_version_looks_like_a_pep440_semver(self):
        self.assertRegex(org.__version__, r"^\d+\.\d+\.\d+((a|b|rc)\d+)?$")

    def test_changelog_has_an_unreleased_section(self):
        self.assertIn("## [Unreleased]", read("CHANGELOG.md"))

    def test_changelog_documents_the_current_version_with_a_date(self):
        self.assertRegex(read("CHANGELOG.md"), r"(?m)^## \[" + re.escape(org.__version__) + r"\] - \d{4}-\d{2}-\d{2}$")

    def test_newest_changelog_entry_is_the_current_version(self):
        versions = re.findall(r"(?m)^## \[(\d+\.\d+\.\d+[^\]]*)\]", read("CHANGELOG.md"))
        self.assertEqual(versions[0], org.__version__)
        numeric = [tuple(int(x) for x in re.match(r"(\d+)\.(\d+)\.(\d+)", v).groups()) for v in versions]
        self.assertEqual(numeric, sorted(numeric, reverse=True), "changelog entries must be newest first")

    def test_pyproject_reads_the_version_from_the_module(self):
        text = read("pyproject.toml")
        self.assertIn('dynamic = ["version"]', text)
        self.assertIn('attr = "photo_organizer.__version__"', text)
        self.assertNotRegex(text, r'(?m)^version\s*=\s*"')

    def test_console_script_points_at_a_real_callable(self):
        self.assertIn('photo-organizer = "photo_organizer:main"', read("pyproject.toml"))
        self.assertTrue(callable(org.main))


class PythonSupport(unittest.TestCase):
    def ci_versions(self):
        match = re.search(r'python-version:\s*\[([^\]]+)\]', read(".github/workflows/ci.yml"))
        return re.findall(r'"(3\.\d+)"', match.group(1))

    def test_minimum_version_is_consistent_everywhere(self):
        self.assertIn('requires-python = ">=3.9"', read("pyproject.toml"))
        self.assertIn("Python 3.9 or newer", read("README.md"))
        self.assertEqual(self.ci_versions()[0], "3.9")

    def test_classifiers_match_the_ci_matrix(self):
        classifiers = set(re.findall(r'"Programming Language :: Python :: (3\.\d+)"', read("pyproject.toml")))
        self.assertEqual(classifiers, set(self.ci_versions()))

    def test_all_source_files_parse_as_python_3_9(self):
        files = [REPO / "photo_organizer.py", *sorted((REPO / "tests").glob("*.py")), *sorted((REPO / "tools").glob("*.py"))]
        for path in files:
            with self.subTest(path.name):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))

    @unittest.skipUnless(hasattr(sys, "stdlib_module_names"), "needs Python 3.10+")
    def test_the_program_imports_only_the_standard_library(self):
        tree = ast.parse(read("photo_organizer.py"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
        self.assertEqual(sorted(m for m in modules if m not in sys.stdlib_module_names), [])

    def test_union_annotations_always_come_with_the_future_import(self):
        # 'str | None' evaluated at definition time raises TypeError on Python 3.9
        files = [REPO / "photo_organizer.py", REPO / "run_tests.py", *sorted((REPO / "tests").glob("*.py")),
                 *sorted((REPO / "tools").glob("*.py"))]
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            has_future = any(isinstance(node, ast.ImportFrom) and node.module == "__future__"
                             and any(alias.name == "annotations" for alias in node.names) for node in tree.body)
            annotations = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = node.args.args + node.args.kwonlyargs + node.args.posonlyargs
                    annotations += [a.annotation for a in args if a.annotation] + ([node.returns] if node.returns else [])
                elif isinstance(node, ast.AnnAssign):
                    annotations.append(node.annotation)
            uses_union = any(isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr)
                             for annotation in annotations for sub in ast.walk(annotation))
            with self.subTest(path.name):
                self.assertTrue(has_future or not uses_union, f"{path.name} uses 'X | Y' annotations without the future import")

    def test_pyproject_declares_no_dependencies(self):
        self.assertIn("dependencies = []", read("pyproject.toml"))


class ExampleConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name).resolve()
        (self.dir / "photos_input").mkdir()
        (self.dir / "config.ini").write_text(read("config.example.ini"), encoding="utf-8")

    def test_the_example_loads_and_is_a_safe_test_run(self):
        conf = org.read_config(self.dir / "config.ini")
        self.assertTrue(conf["dry_run"])
        self.assertTrue(conf["copy"])
        self.assertEqual(conf["input"], self.dir / "photos_input")

    def test_the_example_lists_exactly_the_keys_the_program_reads(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(self.dir / "config.ini", encoding="utf-8")
        in_example = {(section, key) for section in parser.sections() for key in parser[section]}
        self.assertEqual(in_example, config_keys_in_source())

    def test_the_example_shows_the_real_defaults(self):
        (self.dir / "minimal.ini").write_text(
            f"[folders]\ninput_folder = {self.dir / 'photos_input'}\noutput_folder = {self.dir / 'out'}\n", encoding="utf-8")
        defaults = org.read_config(self.dir / "minimal.ini")
        example = org.read_config(self.dir / "config.ini")
        for key in defaults:
            if key not in PATH_KEYS:
                with self.subTest(key):
                    self.assertEqual(example[key], defaults[key])

    def test_every_option_is_documented_in_the_readme(self):
        readme = read("README.md")
        for _section, key in sorted(config_keys_in_source()):
            with self.subTest(key):
                self.assertIn(f"`{key}`", readme)

    def test_every_option_in_the_example_has_a_comment(self):
        lines = read("config.example.ini").splitlines()
        for index, line in enumerate(lines):
            if re.match(r"^\w+\s*=", line):
                previous = lines[index - 1].strip() if index else ""
                with self.subTest(line.split("=")[0].strip()):
                    self.assertTrue(previous.startswith(";"), f"no comment directly above: {line}")


class ReportContract(unittest.TestCase):
    def test_columns_are_documented(self):
        readme = read("README.md")
        for column in org.FIELDS:
            with self.subTest(column):
                self.assertIn(f"| `{column}` |", readme)

    def test_statuses_are_documented(self):
        source = read("photo_organizer.py")
        statuses = set(re.findall(r'"(skipped_\w+)"', source)) | {"planned", "completed", "error"}
        readme = read("README.md")
        for status in sorted(statuses):
            with self.subTest(status):
                self.assertIn(f"| `{status}` |", readme)

    def test_date_sources_are_documented(self):
        readme = read("README.md")
        for value in (org.SRC_ORIGINAL, org.SRC_DIGITIZED, org.SRC_FILENAME, org.SRC_MODIFIED, org.SRC_MTIME, org.SRC_UNKNOWN):
            with self.subTest(value):
                self.assertIn(f"`{value}`", readme)

    def test_folder_layouts_are_documented(self):
        readme = read("README.md")
        for layout in org.STRUCTURES:
            with self.subTest(layout):
                self.assertIn(f"`{layout}`", readme)

    def test_supported_extensions_are_documented(self):
        readme = read("README.md")
        for ext in org.SUPPORTED_EXTENSIONS:
            with self.subTest(ext):
                self.assertIn(f"`{ext}`", readme)


class Documentation(unittest.TestCase):
    def test_exit_codes_are_documented(self):
        readme = read("README.md")
        for code in ("0", "1", "2", "130"):
            with self.subTest(code):
                self.assertIn(f"| `{code}` |", readme)

    def test_every_fixture_device_is_listed_in_the_readme(self):
        readme = read("README.md")
        for needle in ("iPhone", "Samsung Galaxy A57", "libavif", "Qualcomm"):
            with self.subTest(needle):
                self.assertIn(needle, readme)

    def test_the_readme_example_error_matches_the_real_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "in").mkdir()
            (folder / "c.ini").write_text(f"[folders]\ninput_folder = {folder / 'in'}\noutput_folder = {folder / 'out'}\n"
                                          "[organization]\ntestrun = yes ; comment\n", encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                org.read_config(folder / "c.ini")
        self.assertIn(str(caught.exception), read("README.md"))


class RepositoryFiles(unittest.TestCase):
    def test_expected_files_exist(self):
        for name in ("README.md", "LICENSE", "CHANGELOG.md", "CONTRIBUTING.md", "pyproject.toml", "config.example.ini",
                     ".gitignore", ".github/workflows/ci.yml", ".github/pull_request_template.md",
                     ".github/ISSUE_TEMPLATE/bug_report.md", ".github/ISSUE_TEMPLATE/feature_request.md"):
            with self.subTest(name):
                self.assertTrue((REPO / name).is_file())

    def test_personal_files_are_ignored_by_git(self):
        ignored = read(".gitignore").splitlines()
        for pattern in ("config.ini", "organizer_report.csv", "unknown_files.csv", "__pycache__/"):
            with self.subTest(pattern):
                self.assertIn(pattern, ignored)

    def test_license_is_mit(self):
        self.assertTrue(read("LICENSE").startswith("MIT License"))
        self.assertIn('license = "MIT"', read("pyproject.toml"))

    def test_ci_runs_on_all_three_platforms_and_the_windows_check(self):
        ci = read(".github/workflows/ci.yml")
        for token in ("ubuntu-latest", "windows-latest", "macos-latest", "check_windows_creation_time.py",
                      "unittest discover"):
            with self.subTest(token):
                self.assertIn(token, ci)

    def test_no_placeholder_leaks_into_code(self):
        for path in [REPO / "photo_organizer.py", *sorted((REPO / "tests").glob("*.py"))]:
            with self.subTest(path.name):
                self.assertNotIn("YOUR_" + "USER", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
