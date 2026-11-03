"""Describe the machine a test or tool runs on: operating system, Python, and what the file system allows.

Used by the test suite (`tests/__init__.py`, `run_tests.py`) and by the helper scripts in `tools/`, so a pasted log
always says where it came from. Standard library only. Nothing here may ever raise: a value that cannot be found is
reported as "unknown (reason)" instead.
"""
from __future__ import annotations

import datetime
import locale
import os
import platform
import signal
import struct
import sys
import tempfile
import time

UNKNOWN = "unknown"


def _unknown(exc) -> str:
    return f"{UNKNOWN} ({type(exc).__name__}: {exc})"


def _safe(function, *args):
    """Run an information probe; a failing probe becomes text instead of an exception."""
    try:
        return function(*args)
    except Exception as exc:  # noqa: BLE001 - a report must never break a test run
        return _unknown(exc)


# --------------------------------------------------------------------------------------------------------
# Operating system
# --------------------------------------------------------------------------------------------------------
def windows_name(major: int, minor: int, build: int) -> str:
    """Windows 11 reports version 10.0 like Windows 10; the build number tells them apart (11 starts at 22000)."""
    if major == 10 and build >= 22000:
        return "Windows 11"
    if major == 10:
        return "Windows 10"
    return f"Windows {major}.{minor}"


def parse_os_release(text: str) -> dict:
    """The KEY=value lines of /etc/os-release as a dictionary (quotes removed)."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _registry_value(root: str, key: str, name: str):
    """Read one registry value (Windows only). Returns None when it does not exist."""
    import winreg  # imported here: it only exists on Windows
    try:
        with winreg.OpenKey(getattr(winreg, root), key) as handle:
            return winreg.QueryValueEx(handle, name)[0]
    except FileNotFoundError:
        return None


def _registry_or_none(key: str, name: str):
    try:
        return _registry_value("HKEY_LOCAL_MACHINE", key, name)
    except Exception:  # noqa: BLE001 - optional detail: leave it out when it cannot be read
        return None


def _windows_description() -> str:
    info = sys.getwindowsversion()
    version = getattr(info, "platform_version", None) or (info.major, info.minor, info.build)
    major, minor, build = version[0], version[1], version[2]
    parts = [windows_name(major, minor, build)]
    display = _registry_or_none(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "DisplayVersion")  # e.g. 24H2
    revision = _registry_or_none(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "UBR")  # e.g. 2605
    detail = f"build {build}" + (f".{revision}" if isinstance(revision, int) else "")
    if isinstance(display, str) and display:
        parts.append(display)
    parts.append(f"({detail}")
    try:
        edition = platform.win32_edition()
        if edition:
            parts[-1] += f", {edition}"
    except Exception:  # noqa: BLE001
        pass
    parts[-1] += f", {platform.machine()})"
    return " ".join(parts)


def _linux_description() -> str:
    pretty = None
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path, encoding="utf-8") as handle:
                pretty = parse_os_release(handle.read()).get("PRETTY_NAME")
            if pretty:
                break
        except OSError:
            continue
    return f"{pretty or 'Linux'} (kernel {platform.release()}, {platform.machine()})"


def os_description() -> str:
    """One line such as 'Windows 11 24H2 (build 26100.2605, Pro, AMD64)' or 'macOS 15.1 (arm64)'."""
    try:
        if sys.platform == "win32":
            return _windows_description()
        if sys.platform == "darwin":
            return f"macOS {platform.mac_ver()[0] or UNKNOWN} ({platform.machine()})"
        if sys.platform.startswith("linux"):
            return _linux_description()
        return f"{platform.platform()} ({platform.machine()})"
    except Exception as exc:  # noqa: BLE001
        return f"{_safe(platform.platform)} - details unavailable: {_unknown(exc)}"


# --------------------------------------------------------------------------------------------------------
# Python
# --------------------------------------------------------------------------------------------------------
def python_description() -> str:
    bits = struct.calcsize("P") * 8
    return f"{platform.python_version()} {platform.python_implementation()}, {bits}-bit ({platform.python_compiler()})"


def python_location() -> str:
    in_venv = getattr(sys, "base_prefix", sys.prefix) != sys.prefix or hasattr(sys, "real_prefix")
    return f"{sys.executable} (virtual environment: {'yes' if in_venv else 'no'})"


def encodings() -> str:
    stream = sys.stderr
    return (f"file names {sys.getfilesystemencoding()}, locale {locale.getpreferredencoding(False)}, "
            f"console {getattr(stream, 'encoding', None) or UNKNOWN}, UTF-8 mode {'on' if sys.flags.utf8_mode else 'off'}")


def time_zone() -> str:
    now = datetime.datetime.now().astimezone()
    return f"{time.tzname[0]} (UTC{now.strftime('%z')[:3]}:{now.strftime('%z')[3:]})"


# --------------------------------------------------------------------------------------------------------
# What this machine allows (these explain skipped tests and some failures)
# --------------------------------------------------------------------------------------------------------
def fs_type_from_mounts(mounts_text: str, path: str) -> str | None:
    """File system type of `path` from the text of /proc/mounts (the longest matching mount point wins)."""
    best, best_type = "", None
    for line in mounts_text.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        mount_point = fields[1].replace("\\040", " ")
        if (path == mount_point or path.startswith(mount_point.rstrip("/") + "/")) and len(mount_point) >= len(best):
            best, best_type = mount_point, fields[2]
    return best_type


def _windows_volume_type(path: str) -> str:
    import ctypes
    drive, _ = os.path.splitdrive(os.path.abspath(path))
    root = (drive + "\\") if drive else None
    if not root:
        return UNKNOWN
    name = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), None, 0, None, None, None, name, 261)
    return name.value if ok else UNKNOWN


def file_system_type(path: str) -> str:
    if sys.platform == "win32":
        return _windows_volume_type(path)
    if sys.platform.startswith("linux"):
        with open("/proc/mounts", encoding="utf-8") as handle:
            return fs_type_from_mounts(handle.read(), os.path.realpath(path)) or UNKNOWN
    return UNKNOWN


def long_paths() -> str:
    """Windows only: are paths longer than 259 characters allowed? (The registry switch `LongPathsEnabled`.)"""
    if sys.platform != "win32":
        return "not applicable (not Windows)"
    value = _registry_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\FileSystem", "LongPathsEnabled")
    if value is None:
        return "off (setting not present; paths over 259 characters fail)"
    return "on" if value == 1 else "off (paths over 259 characters fail)"


def probe_hard_links(folder: str) -> str:
    source = os.path.join(folder, "probe-source")
    with open(source, "wb") as handle:
        handle.write(b"x")
    try:
        os.link(source, os.path.join(folder, "probe-link"))
        return "yes (the program publishes copies atomically)"
    except OSError as exc:
        return f"no ({exc.__class__.__name__}: {exc}); the rename fallback is used"


def probe_symlinks(folder: str) -> str:
    source = os.path.join(folder, "probe-target")
    with open(source, "wb") as handle:
        handle.write(b"x")
    try:
        os.symlink(source, os.path.join(folder, "probe-symlink"))
        return "allowed"
    except (OSError, NotImplementedError) as exc:
        hint = "; on Windows enable Developer Mode or run as administrator" if sys.platform == "win32" else ""
        return f"not permitted ({exc.__class__.__name__}){hint}; the symlink tests are skipped"


def pillow_status() -> str:
    try:
        import PIL
        from PIL import features
    except ImportError:
        return "not installed; the Pillow cross-check tests are skipped (optional: pip install pillow)"
    try:
        avif = "yes" if features.check("avif") else "no"
    except Exception:  # noqa: BLE001
        avif = UNKNOWN
    return f"{PIL.__version__} (AVIF writing: {avif})"


def program_version() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository root
    if root not in sys.path:
        sys.path.insert(0, root)
    import photo_organizer
    return f"photo_organizer {photo_organizer.version_string()}"


def describe() -> list:
    """(label, value) pairs describing this machine. Never raises."""
    items = [
        ("Run started", _safe(lambda: datetime.datetime.now().astimezone().isoformat(timespec="seconds"))),
        ("Program", _safe(program_version)),
        ("Operating system", _safe(os_description)),
        ("Python", _safe(python_description)),
        ("Python executable", _safe(python_location)),
        ("CPU cores", str(os.cpu_count() or UNKNOWN)),
        ("Time zone", _safe(time_zone)),
        ("Encodings", _safe(encodings)),
    ]
    try:
        folder_root = tempfile.gettempdir()
        items.append(("Temporary folder", f"{folder_root} ({len(folder_root)} characters)"))
        items.append(("Its file system", _safe(file_system_type, folder_root)))
        items.append(("Long paths (Windows)", _safe(long_paths)))
        with tempfile.TemporaryDirectory() as probe_folder:
            items.append(("Hard links", _safe(probe_hard_links, probe_folder)))
            items.append(("Symlinks", _safe(probe_symlinks, probe_folder)))
    except Exception as exc:  # noqa: BLE001
        items.append(("Temporary folder", _unknown(exc)))
    items.append(("POSIX tzset / SIGALRM", f"{'yes' if hasattr(time, 'tzset') else 'no'} / "
                                           f"{'yes' if hasattr(signal, 'SIGALRM') else 'no'}"))
    items.append(("Pillow (optional)", _safe(pillow_status)))
    return [(label, " ".join(str(value).split())) for label, value in items]  # one line per value


def format_header(items: list | None = None) -> str:
    items = describe() if items is None else items
    width = max(len(label) for label, _ in items)
    lines = ["=" * 24 + " Test environment " + "=" * 24]
    lines += [f"{label.ljust(width)} : {value}" for label, value in items]
    lines.append("=" * 66)
    return "\n".join(lines)


def one_line(items: list | None = None) -> str:
    """The sentence to paste next to a result: 'Tested on: Windows 11 ..., Python 3.13.1 ..., photo_organizer 0.3.2'."""
    values = dict(describe() if items is None else items)
    python = values.get("Python", UNKNOWN).split(" (")[0]
    return f"Tested on: {values.get('Operating system', UNKNOWN)} | Python {python} | {values.get('Program', UNKNOWN)}"


if __name__ == "__main__":
    print(format_header())
