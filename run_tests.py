#!/usr/bin/env python3
"""Run the whole test suite and write a report that says where it ran.

    python run_tests.py                 verbose log, written to test-report.txt next to this file
    python run_tests.py --brief         dots instead of one line per test
    python run_tests.py --durations 10  also list the 10 slowest tests (Python 3.12 or newer)
    python run_tests.py --report FILE   write the report elsewhere

The report starts with the test environment (operating system and Python version, long paths, symlinks, hard links,
optional Pillow) and ends with a summary, including why tests were skipped. Send that file along with a bug report.
Exit code: 0 when every test passed, 1 when one failed, 5 when no test was found (as `python -m unittest` does).
"""
import argparse
import os
import sys
import time
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ["PHOTO_ORGANIZER_ENV_REPORTED"] = "1"  # this script prints the environment itself
from tools import environment  # noqa: E402


class Tee:
    """Write to several streams at once (the console and the report file)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def summary(result, seconds: float) -> str:
    """The closing section of the report: counts, skip reasons, the names of failed tests."""
    problems = len(result.failures) + len(result.errors)
    passed = result.testsRun - problems - len(result.skipped) - len(result.expectedFailures)
    lines = ["", "=" * 28 + " Summary " + "=" * 28,
             f"Result   : {'NO TESTS FOUND' if result.testsRun == 0 else 'OK' if result.wasSuccessful() else 'FAILED'}",
             f"Tests    : {result.testsRun} run, {passed} passed, {len(result.failures)} failed, "
             f"{len(result.errors)} errors, {len(result.skipped)} skipped, in {seconds:.1f} s"]
    if result.skipped:
        lines.append("Skipped  :")
        for reason, count in Counter(reason for _, reason in result.skipped).most_common():
            lines.append(f"  {count:3d} x {reason}")
    for title, items in (("Failed   :", result.failures), ("Errors   :", result.errors)):
        if items:
            lines.append(title)
            lines += [f"  {test.id()}" for test, _ in items]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--brief", action="store_true", help="dots instead of one line per test")
    parser.add_argument("--report", default=str(ROOT / "test-report.txt"), help="file for the report")
    parser.add_argument("--durations", type=int, default=0, metavar="N", help="list the N slowest tests (3.12+)")
    parser.add_argument("--start-dir", default=str(ROOT), help="where to look for tests (default: this repository)")
    parser.add_argument("--pattern", default="test*.py", help="file name pattern of test modules")
    args = parser.parse_args(argv)

    try:
        sys.stderr.reconfigure(errors="backslashreplace")  # a console that cannot show a character must not stop the run
    except (AttributeError, ValueError, OSError):
        pass
    start = Path(args.start_dir).resolve()
    with open(args.report, "w", encoding="utf-8", newline="") as report:
        out = Tee(sys.stderr, report)
        out.write(environment.format_header() + "\n\n")
        out.flush()
        suite = unittest.defaultTestLoader.discover(str(start), pattern=args.pattern, top_level_dir=str(start))
        options = {"stream": out, "verbosity": 1 if args.brief else 2}
        if args.durations and sys.version_info >= (3, 12):
            options["durations"] = args.durations
        started = time.time()
        result = unittest.TextTestRunner(**options).run(suite)
        out.write(summary(result, time.time() - started) + "\n")
        if result.testsRun == 0:
            out.write(f"No tests were found in {start} with the pattern {args.pattern!r}.\n")
        out.write("\n" + environment.one_line() + "\n")
        out.write(f"Report written to {args.report}\n")
        out.flush()
    if result.testsRun == 0:
        return 5
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
