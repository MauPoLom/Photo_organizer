"""The test suite.

Importing this package prints the test environment once (operating system, Python version, what the file system
allows), and repeats the one-line summary when the process ends, so any pasted log says where it was produced.
`python run_tests.py` does the same and also writes the whole log to `test-report.txt`.
"""
import atexit
import os
import sys

from tools import environment

if not os.environ.get("PHOTO_ORGANIZER_ENV_REPORTED"):
    os.environ["PHOTO_ORGANIZER_ENV_REPORTED"] = "1"  # once per process tree, also when run_tests.py printed it already
    print(environment.format_header(), file=sys.stderr, flush=True)
    atexit.register(lambda: print("\n" + environment.one_line(), file=sys.stderr, flush=True))
