r"""Make a release: bump the version, stamp its creation date and time (UTC) and close the changelog section.

    python tools/release.py check             show version and creation time and verify they agree everywhere
    python tools/release.py patch|minor|major release the next version (needs entries under [Unreleased])
    python tools/release.py set 1.0.0         release exactly this version
    --dry-run   show what would change, change nothing
    --time "YYYY-MM-DD HH:MM:SS"   use this UTC time instead of now
    --root DIR  the repository to work on (default: this one)

The version and the creation time live in photo_organizer.py (`__version__`, `__created__`) and nowhere else.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_RE = re.compile(r'^__version__ = "([^"]*)"', re.M)
CREATED_RE = re.compile(r'^__created__ = "([^"]*)"', re.M)
PLAIN_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def numbers(version: str) -> tuple:
    return tuple(int(part) for part in re.match(r"(\d+)\.(\d+)\.(\d+)", version).groups())


def bump(version: str, part: str) -> str:
    if not PLAIN_VERSION.match(version):
        raise ValueError(f"{version!r} is a pre-release; use `set` to choose the next version")
    major, minor, patch = numbers(version)
    return {"major": f"{major + 1}.0.0", "minor": f"{major}.{minor + 1}.0", "patch": f"{major}.{minor}.{patch + 1}"}[part]


def stamp_source(text: str, version: str, created: str) -> str:
    """Write the version and creation time into the source; adds the creation line if it does not exist yet."""
    if len(VERSION_RE.findall(text)) != 1:
        raise ValueError("expected exactly one __version__ line")
    nl = "\r\n" if "\r\n" in text else "\n"
    text = VERSION_RE.sub(f'__version__ = "{version}"', text, count=1)
    line = f'__created__ = "{created}"  # UTC; when this version was made (written by tools/release.py)'
    if CREATED_RE.search(text):
        return re.sub(r'^__created__ = "[^"]*".*$', lambda m: line, text, count=1, flags=re.M)
    return VERSION_RE.sub(lambda m: m.group(0) + nl + line, text, count=1)


def close_changelog(text: str, version: str, date: str) -> str:
    """Turn the entries under [Unreleased] into the section of `version` and leave an empty [Unreleased]."""
    start = re.search(r"^## \[Unreleased\][ \t]*\r?\n", text, re.M)
    if not start:
        raise ValueError("CHANGELOG.md has no '## [Unreleased]' heading")
    following = re.search(r"^## \[", text[start.end():], re.M)
    end = start.end() + (following.start() if following else len(text) - start.end())
    body = text[start.end():end]
    if not body.strip():
        raise ValueError("nothing under [Unreleased]: describe the changes in CHANGELOG.md first")
    nl = "\r\n" if "\r\n" in text else "\n"
    return text[:start.start()] + "## [Unreleased]" + nl + nl + f"## [{version}] - {date}" + nl + body + text[end:]


def state(root: Path) -> tuple:
    source = (root / "photo_organizer.py").read_text(encoding="utf-8")
    version, created = VERSION_RE.search(source), CREATED_RE.search(source)
    return source, (version.group(1) if version else None), (created.group(1) if created else None)


def problems(root: Path, now: datetime | None = None) -> list:
    """Everything that disagrees: an empty list means version, creation time and changelog are consistent."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    _, version, created = state(root)
    found = []
    if not version or not re.match(r"^\d+\.\d+\.\d+((a|b|rc)\d+)?$", version):
        found.append(f"__version__ is {version!r}, not a version number such as 1.2.3")
    try:
        moment = datetime.strptime(created or "", TIME_FORMAT)
        if moment > now + timedelta(days=1):
            found.append(f"__created__ ({created}) lies in the future")
    except ValueError:
        moment = None
        found.append(f"__created__ is {created!r}, not 'YYYY-MM-DD HH:MM:SS'")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    top = re.search(r"^## \[(\d+\.\d+\.\d+[^\]]*)\] - (\d{4}-\d{2}-\d{2})", changelog, re.M)
    if not top:
        found.append("CHANGELOG.md has no released version")
    else:
        if top.group(1) != version:
            found.append(f"the newest changelog entry is {top.group(1)}, the program says {version}")
        elif moment and top.group(2) != moment.strftime("%Y-%m-%d"):
            found.append(f"the changelog dates {version} as {top.group(2)}, the program was created {created}")
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["check", "patch", "minor", "major", "set"])
    parser.add_argument("version", nargs="?", help="the version for `set`")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--time", help='UTC time "YYYY-MM-DD HH:MM:SS" (default: now)')
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    root = Path(args.root)
    source, version, created = state(root)
    if args.action == "check":
        print(f"Version {version}, created {created} UTC")
        found = problems(root)
        print("OK: version, creation time and changelog agree" if not found else "\n".join(f"PROBLEM: {p}" for p in found))
        return 1 if found else 0
    try:
        if args.action == "set":
            new = args.version or ""
            if not re.match(r"^\d+\.\d+\.\d+((a|b|rc)\d+)?$", new):
                raise ValueError(f"{new!r} is not a version number such as 1.2.3")
        else:
            new = bump(version, args.action)
        if numbers(new) < numbers(version) or new == version:
            raise ValueError(f"{new} is not newer than {version}")
        moment = datetime.strptime(args.time, TIME_FORMAT) if args.time else \
            datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        changelog_path = root / "CHANGELOG.md"
        changelog = changelog_path.read_text(encoding="utf-8")
        top = re.search(r"^## \[(\d+\.\d+\.\d+[^\]]*)\]", changelog, re.M)
        if not top or top.group(1) != version:
            raise ValueError("the program and the newest changelog entry name different versions; run `check`")
        new_changelog = close_changelog(changelog, new, moment.strftime("%Y-%m-%d"))
        new_source = stamp_source(source, new, moment.strftime(TIME_FORMAT))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"{version} -> {new}, created {moment.strftime(TIME_FORMAT)} UTC" + ("  (dry run, nothing written)" if args.dry_run else ""))
    if not args.dry_run:
        (root / "photo_organizer.py").write_text(new_source, encoding="utf-8", newline="")
        changelog_path.write_text(new_changelog, encoding="utf-8", newline="")
        print(f"Next: run the tests, then\n  git commit -am \"Release {new}\"\n  git tag -a v{new} -m \"Version {new}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
