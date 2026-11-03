r"""Windows-only check: can this computer/drive set "Date created"?

    python tools/check_windows_creation_time.py
    python tools/check_windows_creation_time.py D:\photos_sorted     (test a specific drive or share)

Creates a temporary file, sets its creation time, reads it back, and deletes it.
"""
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
import photo_organizer as org  # noqa: E402
from tools import environment  # noqa: E402


def main() -> int:
    print(environment.one_line())
    if os.name != "nt":
        print("This check only makes sense on Windows (set_creation_time is Windows-only).")
        return 2
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    target = datetime(2019, 7, 4, 13, 30, 12, tzinfo=timezone.utc).timestamp()
    mtime = 1_600_000_000
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        probe = Path(tmp) / "creation_time_check.jpg"
        probe.write_bytes(b"x")
        os.utime(probe, (mtime, mtime))
        try:
            org.set_creation_time(probe, target)
        except OSError as exc:
            print(f"FAIL: could not set the creation time: {exc}")
            return 1
        st = probe.stat()
        created = getattr(st, "st_birthtime", st.st_ctime)  # st_ctime = creation time on Windows < 3.12
        created_ok = abs(created - target) < 0.01
        mtime_ok = int(st.st_mtime) == mtime
        print(f"Wanted creation time : {datetime.fromtimestamp(target)}")
        print(f"Actual creation time : {datetime.fromtimestamp(created)}  -> {'OK' if created_ok else 'WRONG'}")
        print(f"Modified time intact : {'OK' if mtime_ok else 'WRONG'}")
        print("PASS" if created_ok and mtime_ok else "FAIL")
        return 0 if created_ok and mtime_ok else 1


if __name__ == "__main__":
    sys.exit(main())
