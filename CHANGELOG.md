# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-11-03

### Changed

- **First public release on GitHub.** The version number goes from 0.7.0 straight to 1.1.0. From here on the project
  follows Semantic Versioning without the 0.x exception: renamed or removed options, changed folder naming and changed
  CSV columns or statuses need a new major version. The package is marked "Production/Stable".
- The MIT license names the copyright holder (MauPoLom). The package metadata has an author and project links
  (homepage, issues, changelog), and the clone URLs and the CI badge in the README point to the repository.

## [0.7.0] - 2026-11-03

### Added

- **Phase messages.** After the version line a run now says where it is: `Starting program with options: testrun=...,
  copy_mode=..., verify=..., duplicate_policy=...`, the input, output and reports folders, `Starting preliminary scan ...`,
  `Preliminary scan completed: N file(s) to process, M skipped`, `Starting file handling ...` (with a note in a test run),
  and, after the existing `Mode:` and `CSV report:` lines, `Program end. See the reports for details.` Phase messages go
  through a function that ignores console errors, so a broken console cannot stop a run.
- **Progress line.** On a terminal a one-line counter (`1234/5678  21%`) shows how far file handling is. It is drawn on
  stderr, updated in place at most ten times a second, and erased before the summary. Nothing is printed when stderr is
  redirected, so logs and scripts are unchanged.

### Changed

- The input folder is listed completely before the first file is processed (names only, no file is read), so that the
  total is known. As a result an interrupt during this preliminary scan leaves an earlier report untouched instead of
  replacing it with an empty one.

### Fixed

- README: the CI matrix (macOS runs Python 3.10 to 3.13, not 3.9), the Live Photo `.mov` and `handle_movies` wording, a
  missing full stop in the movies FAQ, the duplicate-detection note (only files of a type listed in `extensions` are
  compared), the `report_csv` row (an absolute path is allowed), outdated version examples and the sample output.

## [0.6.0] - 2026-11-03

### Added

- `reports_folder`: both CSV reports now go into one folder, `reports` next to `config.ini` by default, created when needed
  (relative paths are relative to the folder of `config.ini`; an absolute path or `.` is allowed).

### Changed

- **Behaviour change:** `report_csv` and `unknown_files_csv` are now file names inside the reports folder, no longer paths
  next to `config.ini`. A configuration that still says `./organizer_report.csv` keeps working and now lands in
  `reports/`; an absolute path is used as written. To get the old location back, set `reports_folder = .`.
- The error for a report inside the input folder names the option (`report_csv`) and says what to check.

## [0.5.0] - 2026-11-02

### Added

- **Movies.** `handle_movies = yes` sorts `.mp4` and `.mov` files into a sub-folder of their date folder, for example
  `2019_07/movies`, `2019/07/movies` or `2019/07/04/movies`; `movies_folder` sets the name (default `movies`). Movies without
  a date go to `unknown_date/movies`. Dates come from the file name, then the modification time (movies have no EXIF; the
  creation time inside the file is not read). Default is `no`: movies stay unsupported and are listed in `unknown_files.csv`.
- Listing `.mp4` or `.mov` under `extensions` now explains that `handle_movies` is the switch.

## [0.4.0] - 2026-10-31

### Added

- **Version number with creation date and time, shown at every start.** The first line of every run is now
  `Photo Organizer 0.4.0 (created 2026-10-31 09:56:49 UTC)`, also when the configuration is wrong. `--version` and
  `--help` show the same text. Both values live in one place, `__version__` and `__created__` in `photo_organizer.py`.
- `tools/release.py`: `check` verifies that version, creation time and changelog agree; `patch`, `minor`, `major` or
  `set X.Y.Z` bump the version, stamp the current UTC time, and close the `[Unreleased]` section of the changelog
  (`--dry-run` shows the change first). It refuses an empty changelog section and a version that is not newer.
- 16 tests for the above; the test environment block and the tools' one-line summary include the creation time.

- Every test log now says where it was produced. Running the tests prints an environment block (operating system with
  Windows feature release, build and edition or macOS and Linux versions; Python version, implementation, bitness and
  executable; time zone; encodings; temporary folder and its file system; the Windows long-path switch; whether hard links
  and symlinks really work; Pillow) and ends with a one-line `Tested on: ...` recap. The lines that explain skipped
  tests are probed for real, not guessed.
- `run_tests.py`: runs the suite and writes `test-report.txt` (environment, full log, summary with skip reasons and
  the names of failed tests). Options `--brief`, `--durations N`, `--report FILE`.
- `tools/environment.py` (the shared, never-raising report code) and an environment line at the start of
  `tools/inspect_exif.py` and `tools/check_windows_creation_time.py`.
- 44 tests for the report, including simulated Windows, macOS and Linux branches, a broken registry, and
  `run_tests.py` on a demo suite with passes, failures, errors, skips and no tests at all (exit code 5, not a green
  result). Mutation checks (breaking the Windows 11 threshold, the header, the recap line, the no-tests exit code and the
  probe cleanup) are each caught by a test.
- A release test that fails when a source file uses a `X | None` annotation without
  `from __future__ import annotations` (it would crash on Python 3.9).

## [0.3.2] - 2026-10-25

First release checked on a real Windows machine. The full suite ran there for the first time: 399 tests passed, 16 were
skipped as designed (11 need Pillow, 3 need symlink rights, 2 are POSIX-only) and one failed. That failure was in the
test, not in the program. The tests that call the real Windows API for "Date created" and the tests for read-only files
passed on that machine.

A second run of this release on the same machine passed completely: 419 tests, 403 passed, 16 skipped as designed, none
failed.

### Fixed

- `test_very_long_but_valid_file_name` assumed a 204-character file name always works. On Windows the whole destination
  path may not exceed 259 characters unless long paths are enabled, and in a temporary folder it reached 264. The test now
  leaves room for the folders in front of the name, and it prints the path length and the report when it fails.

### Changed

- When a file fails and its destination path is longer than Windows allows, the `details` column now says so
  (`the destination path is 264 characters; Windows allows 259 unless long paths are enabled`) and the README explains
  how to enable long paths. Before, the row only showed the system's generic "path not found" message.

### Added

- Three tests for too-long paths: the explanatory note (with a mutation check: it fails without the note), no note for
  short paths or other systems, and one over-long file not stopping the others.
- README: a table of what was run on which operating system, and a FAQ entry on long paths.

## [0.3.1] - 2026-10-24

A review release. 0.3.0 was re-read critically, every suspected defect was confirmed with an experiment before it
was fixed, and each fix has a regression test that fails on the old code. No option and no report column changed.

### Fixed

- **A path the console cannot show made a successful run report failure.** With redirected output (or a legacy
  console) a non-ASCII path in a printed line raised an error: exit code 2 although the photos were copied, and
  `unknown_files.csv` was never written. All files are now written before anything is printed, and characters the
  console cannot show are escaped instead of raising.
- **Crafted files could keep the parsers busy for minutes.** A 32 KB HEIC whose `iloc` box declared extents without
  any fields made the reader loop for hours. The work is now bounded everywhere: such extents are refused, the `iloc`
  box is limited to 200,000 entries, a JPEG may have at most 1,024 segments before its image data, a PNG at most
  100,000 chunks, and the HEIC `meta` box limit went from 64 to 8 MiB (a real one is a few kilobytes).
- **Read-only source files broke copies on Windows.** The read-only attribute was copied onto the temporary file, which
  Windows then refuses to delete: a successful copy ended as an error and left a stray `.photo-organizer-*.tmp`; a move
  could not delete a read-only original. The temporary file is now never read-only, the copy gets the read-only state
  afterwards, and a move clears the attribute before deleting the verified original. (Reproduced here by simulating
  Windows' delete rule; confirm on real Windows with the test suite.)
- **Copies to FAT and exFAT drives (and some network shares) were not atomic.** Without hard links the program copied the
  verified file a second time straight to its final name, so a full disk, a crash or Ctrl-C in the middle left a truncated
  photo under that name (reproduced: 50,000 of 200,108 bytes). This affected 0.2.0 and 0.3.0. The finished, verified
  temporary file is now renamed into place, which is atomic and does not copy again.
- **A copy that was published but whose original could not be deleted was invisible to duplicate detection**, so the next
  identical file was copied a second time. It is now registered.
- **Ctrl-C produced a raw traceback and lost `unknown_files.csv`.** It now stops cleanly with exit code 130, keeps the
  report written so far, writes the list of unsupported files found so far, and leaves no temporary file.
- **Thousands of files with the same name took quadratic time** (3,000 colliding names: 31 seconds). The `NAME_001`
  search now continues where the previous one stopped.
- **Test run and live run could number collisions differently after a failed file.** They agree now.
- Error messages name the option: `[organization] testrun: expected yes or no, got 'maybe'` instead of
  `Expected yes or no, got 'maybe'`; a non-numeric `min_year` no longer shows Python's `invalid literal for int()`.
- The module docstring still claimed the program never uses `shell=True`; it starts no other programs at all.

### Added

- A fourth sanitised real-world fixture, a Samsung Galaxy A57 JPEG: little-endian Exif, a negative UTC offset, a
  restart-interval marker and a vendor trailer after the image. Its trailer held a network country code and a UTC
  time; both were removed. 32 tests cover the real-world fixtures and 31 more the defects above; for the defects, the
  tests that distinguish old from new behaviour were run against 0.3.0 and fail there.
- Test guards that fail if a fixture contains location, device or vendor strings.

### Changed

- Internal: `run()` was split into `process_image()`, `RunState`, `write_unknown_files()` and a small `run()`;
  `transfer()` takes an optional `notes` list and `unique_destination()` an optional `hints` dictionary.
- The release test now observes which options the program really reads instead of searching its source text.
- `tools/inspect_exif.py` reads only the first 8 MiB of a file.

## [0.3.0] - 2026-10-22

### Added

- **HEIC and HEIF support** (`.heic`, `.heif`, so iPhone photos). The EXIF block is read from the file's ISO box
  structure (`ftyp`, `meta`, `iinf`, `iloc`), still with the standard library only. The image data is never
  decoded. Supported: `iloc` versions 0 to 2, all field sizes, 64-bit box sizes, Exif stored in `mdat` or in an
  `idat` box, `infe` versions 2 and 3. All date, time zone, rename and timestamp options apply to HEIC.
- The file type is recognised by its `ftyp` brand; other ISO files (MP4, MOV) with a HEIC extension are
  refused with a clear note and fall back to the file name or modification time.
- `tools/inspect_exif.py`: shows what is read from a photo, the file structure of a HEIC, and which date
  would be used. Meant for checking real-world files and for bug reports.
- 55 HEIC tests (layout variants, brands, every truncation, random corruption, absurd offsets, end-to-end) and an
  optional cross-check against AVIF files written independently by libavif through Pillow.

### Changed

- The default for `extensions` is now `.jpg,.jpeg,.png,.bmp,.heic,.heif`. A configuration that lists
  `extensions` explicitly keeps working unchanged.

## [0.2.0] - 2026-10-21

First version with a public structure: a pure-Python rewrite of the original ExifTool-based prototype.
While the major version is 0, minor releases may contain breaking changes; they are marked **breaking** below.

### Added

- `--version` option; the version is defined once as `__version__` in `photo_organizer.py`.
- Folder layouts `YYYY`, `YYYY/YYYY-MM` and `YYYY/MM/DD` next to `YYYY_MM` and `YYYY/MM`.
- `unknown_date_folder`: files without a usable date go to their own folder (`use_filesystem_mtime = no`).
- `rename_by_date`: rename by capture date with a `strftime` pattern and `{original}`.
- `cleanup_empty_folders`: remove input folders emptied by a move (never the input folder itself).
- `report_skipped`: skipped files (type, symlink, hidden) get a CSV row and are counted.
- `unknown_files.csv` and an on-screen warning for files of unsupported types.
- Date from the file name (`IMG_20190704_153012`, `Screenshot 2019-07-04 at 15.30.12`, `IMG-20190704-WA0001` ...)
  with the options `use_filename_date`.
- Date sanity checks (`min_year`, `reject_future_dates`); rejected dates are explained in the report.
- Time zone support: `OffsetTime*` tags and `+02:00` suffixes are read; `timezone_mode` chooses `wallclock`,
  `local` or `utc` for folder names; `change_timestamp` now sets the exact moment.
- `use_exif_modify_date` to opt in to the EXIF edit date.
- `set_creation_time` (Windows only): also sets "Date created".
- Real OS hidden-file detection (Windows hidden/system attribute, macOS hidden flag, plus dot-names).
- Content-based duplicate detection across the whole output folder, under any name.
- `tools/check_windows_creation_time.py`.
- Project files: README with full reference, LICENSE, CONTRIBUTING, `pyproject.toml` (optional
  `pip install .` with a `photo-organizer` command), GitHub Actions CI, issue and pull request templates.
- Test suite of 280+ tests, run by CI on Linux, Windows and macOS for Python 3.9 to 3.13.

### Changed

- **Breaking:** pure standard-library Python. ExifTool is no longer used or needed; the `exiftool_path`
  option is gone.
- **Breaking:** only `.jpg`, `.jpeg`, `.png` and `.bmp` are supported. Videos are no longer processed.
  Other files are reported and listed in `unknown_files.csv`.
- **Breaking:** `duplicate_policy` offers `skip_identical` and `rename`; the `error` policy was removed.
  Same-name files are always numbered `NAME_001`, `NAME_002` ...
- **Breaking:** the EXIF edit date (`DateTime`) is no longer used unless `use_exif_modify_date = yes`.
- **Breaking:** report columns `date_recorded` and `date_used` were added, the `conflict` status was removed,
  and the `date_source` values are now `exif_datetime_original`, `exif_datetime_digitized`, `filename`,
  `exif_datetime_modified`, `filesystem_mtime` and `unknown`.
- `config.ini` is now `config.example.ini`; copy it to `config.ini`.
- Files are read far fewer times: hashing happens while copying, and a test run only hashes when another file
  of the same size exists.
- File names are handled by Python directly, so non-ASCII names no longer depend on how an external program
  receives command-line arguments.
- File-name dates with an impossible time (for example `20190704_256012`) now give the date instead of nothing.

### Fixed

- Dates such as 1904, 1970 or 2099 no longer create bogus folders.
- A test run now predicts the same destinations as a live run, including duplicates and renames.

## [0.1.0] - prototype, never tagged

ExifTool-based script: sorted by EXIF date into `YYYY_MM` or `YYYY/MM`, copy or verified move, duplicate policies
`skip_identical`, `rename` and `error`, test run and CSV report.
