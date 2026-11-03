# Photo Organizer

[![CI](https://github.com/MauPoLom/photo-organizer/actions/workflows/ci.yml/badge.svg)](https://github.com/MauPoLom/photo-organizer/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

Sorts photos into date folders. One Python file, **no dependencies, no ExifTool, nothing to install**.

It reads the real capture date from EXIF, falls back to the date in the file name, and only then to the
file's modification time. Every copy is verified with SHA-256, nothing is ever overwritten, and a test run
shows exactly what would happen before a single file is touched.

> Supported types in this release: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.heic`, `.heif` (iPhone photos). Movies (`.mp4`, `.mov`) can be filed into a `movies` sub-folder with `handle_movies`; no other videos.
> Check your version with `--version`; changes per version are in the [changelog](CHANGELOG.md).

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Configuration reference](#configuration-reference)
- [Recipes](#recipes)
- [Reports and exit codes](#reports-and-exit-codes)
- [Safety guarantees](#safety-guarantees)
- [Platform notes](#platform-notes)
- [FAQ and troubleshooting](#faq-and-troubleshooting)
- [Limitations](#limitations)
- [Development](#development)
- [Versioning](#versioning)
- [License](#license)

## Features

- **Pure Python, standard library only.** Reads EXIF from JPEG, PNG and HEIC/HEIF itself; the image data is never decoded.
- **Careful date logic:** EXIF original, EXIF digitized, date in the file name, optional EXIF edit date,
  optional file modification time, otherwise an `unknown_date` folder.
- **Date sanity checks:** reset camera clocks (1970, 1980, 2099 ...) are rejected, with the reason in the report.
- **Time zone aware:** reads `OffsetTime*` tags; choose camera time, local time or UTC for the folder names.
- **Five folder layouts**, optional **rename by date**, and an **unknown-date bucket**.
- **Duplicate handling:** name clashes become `NAME_001`, `NAME_002` ...; identical content is detected even
  under a different name, anywhere in the output folder, also from earlier runs.
- **Safe copy or move:** hash-verified, atomic no-overwrite publish, originals deleted only after verification.
- **Test run by default**, CSV report for every file, separate `unknown_files.csv` for unsupported types.
- **Clear phases and a progress line:** the run says what it is doing (options, folders, scan, file handling, end) and shows a
  small `1234/5678  21%` counter on a terminal, so a long run never looks stuck.
- Optional: set the copy's modification time to the capture time, and on Windows its "Date created".
- Optional: remove input folders that a move left empty.
- Real OS-level hidden-file detection (Windows attributes, macOS flag, dot-names).

## Requirements

- **Python 3.9 or newer.** The test suite runs in CI on Linux and Windows with Python 3.9 to 3.13, and on macOS with 3.10 to 3.13.
- **No third-party packages. Nothing to `pip install`.** No ExifTool, no Pillow.
- If a future version adds a format that needs an extra library (for example video or RAW), this section will list
  the library and its `pip install` command.

## Installation

Pick one.

**A. Just the script (simplest).** Download `photo_organizer.py` and `config.example.ini`, or clone:

```bash
git clone https://github.com/MauPoLom/photo-organizer.git
cd photo-organizer
```

**B. As a command** (optional, still no dependencies):

```bash
python -m pip install .
photo-organizer --version
```

Both ways give the same program. Examples below use `python photo_organizer.py`; with option B write
`photo-organizer` instead. The package contains only the program, so with option B download
`config.example.ini` from the repository to create your `config.ini`.

## Quick start

1. Create your configuration from the example and set the two folders:

   ```bash
   cp config.example.ini config.ini        # Windows: copy config.example.ini config.ini
   ```

   ```ini
   [folders]
   input_folder = ./photos_input
   output_folder = ./photos_sorted
   ```

2. Run a **test run** (the default; it only writes the CSV reports):

   ```bash
   python photo_organizer.py --config config.ini
   ```

   ```text
   Photo Organizer 1.1.0 (created 2026-11-03 10:43:20 UTC)
   Starting program with options: testrun=yes, copy_mode=yes, verify=yes, duplicate_policy=skip_identical
   Input folder:   /home/me/photos_input
   Output folder:  /home/me/photos_sorted
   Reports folder: /home/me/reports
   Starting preliminary scan ...
   Preliminary scan completed: 5 file(s) to process, 2 skipped
   Starting file handling (test run: no file is changed) ...
   Mode: TEST ONLY (copy) | planned=4, skipped_extension=1, skipped_hidden=1, skipped_identical=1
   CSV report: /home/me/reports/organizer_report.csv
   WARNING: 1 file(s) with unsupported types were NOT processed. They are listed in /home/me/reports/unknown_files.csv
   Program end. See the reports for details.
   ```

   (The `WARNING` goes to stderr, so with redirected output it can appear in a different place. While files are being
   handled, a terminal also shows a progress counter; see [What you see while it runs](#what-you-see-while-it-runs).)

3. Open `organizer_report.csv` in the reports folder. When it looks right, set `testrun = no` in `config.ini` and run again.

Command line options are deliberately minimal:

| Option | Meaning |
|---|---|
| `--config FILE` | Configuration file (default `config.ini` in the current directory) |
| `--dry-run` | Force a test run, whatever the configuration says |
| `--version` | Print the version |

Everything else lives in `config.ini`.

### What you see while it runs

After the version line, the program says which phase it is in:

| Line | Meaning |
|---|---|
| `Starting program with options: testrun=yes, copy_mode=yes, verify=yes, duplicate_policy=skip_identical` | The settings that matter most for safety. `testrun=yes` means nothing is changed |
| `Input folder:`, `Output folder:`, `Reports folder:` | The three folders in use, as full paths |
| `Starting preliminary scan ...` | Lists the input folder (names only, no file is read) and, for `skip_identical`, the files already in the output folder |
| `Preliminary scan completed: 5 file(s) to process, 2 skipped` | Supported files found, and items skipped because of their type, a hidden name or a link. A file that later turns out to be identical to another is still counted as "to process". Items that could not be read are added as `N unreadable` |
| `Starting file handling ...` | The real work begins (in a test run the line says that no file is changed) |
| `Mode: ... \| planned=4, ...` and `CSV report: ...` | The summary and the report location |
| `Program end. See the reports for details.` | The last line of a normal run. It is not printed after Ctrl-C or an error |

During file handling a terminal also shows one line that counts the files, for example `1234/5678  21%`. It updates in
place and is erased when handling ends, before the summary prints. The total is the "to process" number above.

The progress line is written to stderr and only when stderr is a terminal, so redirected output, log files and scheduled
runs stay clean. There is no option for it.

### Version and creation time

Every run starts with one line that says which version it is and when that version was made (UTC):

```text
Photo Organizer 1.1.0 (created 2026-11-03 10:43:20 UTC)
Starting program with options: testrun=yes, copy_mode=yes, ...
```

The same text is shown by `--version` and at the top of `--help`, and it is the first line even when the configuration is
wrong, so a pasted log always says which version produced it. The version and the creation time are stored once, as
`__version__` and `__created__` in `photo_organizer.py`. They are written by `python tools/release.py`, never by hand;
`python tools/release.py check` verifies that they agree with the changelog. The creation time is when the version was
made, not when you installed or last copied the file.

### What a report looks like

A shortened real test-run report (paths trimmed):

| source | destination | date_source | status | details |
|---|---|---|---|---|
| `trip/IMG_0001.jpg` | `2019_07/IMG_0001.jpg` | `exif_datetime_original` | `planned` | |
| `broken_clock.jpg` | `2021_03/broken_clock.jpg` | `filesystem_mtime` | `planned` | DateTimeOriginal 1970-01-01 rejected (before year 1990) |
| `Screenshot_20210315-091500.png` | `2021_03/Screenshot_20210315-091500.png` | `filename` | `planned` | |
| `trip/IMG_0002.jpg` | `2019_07/IMG_0002 copy.jpg` | `exif_datetime_original` | `skipped_identical` | identical content already exists; original left untouched |
| `clip.mp4` | | | `skipped_extension` | unsupported type .mp4 |
| `.thumbnails` | | | `skipped_hidden` | hidden folder, contents not scanned |

## How it works

For every supported file the program does this, in order:

1. **Scan** the input folder (alphabetically, case-insensitive). Symlinks, junctions and hidden items are
   skipped and reported. Files of other types are reported and listed in `unknown_files.csv`.
2. **Read the EXIF dates** of JPEG, PNG and HEIC/HEIF files. The format is detected from the file's first bytes, not from
   its extension. Damaged EXIF never stops the run; it is noted in the report and the next date source is used.
3. **Choose the date** (see below).
4. **Build the destination** from the folder layout and the optional rename pattern.
5. **Check for duplicates**, then pick a free name (`NAME_001` ...).
6. **Copy or move** with verification, and optionally set the file times.

### Which date is used

The first usable date wins:

| # | Source | `date_source` value | Notes |
|---|---|---|---|
| 1 | EXIF `DateTimeOriginal` | `exif_datetime_original` | The moment the picture was taken |
| 2 | EXIF `DateTimeDigitized` | `exif_datetime_digitized` | Usually equal to 1 |
| 3 | Date in the file name | `filename` | `use_filename_date`; see patterns below |
| 4 | EXIF `DateTime` | `exif_datetime_modified` | Last edit time; **off by default** (`use_exif_modify_date`) |
| 5 | File modification time | `filesystem_mtime` | `use_filesystem_mtime` |
| 6 | none | `unknown` | File goes to the `unknown_date` folder |

Every candidate must pass the **sanity check**: not before `min_year` (default 1990) and not later than
tomorrow (`reject_future_dates`). This also applies to dates from file names and to the modification time.
A rejected date is explained in the `details` column, then the next source is tried.

Camera clocks that were reset to a plausible date (for example 2000-01-01) cannot be detected.

### Time zones

If the EXIF data records a UTC offset (`OffsetTimeOriginal`, `OffsetTimeDigitized`, `OffsetTime`, or a
suffix like `+02:00` in the date itself), it is used for two things:

- The **exact moment** when `change_timestamp` sets the file time.
- The **folder and file names**, according to `timezone_mode`:

| `timezone_mode` | Folder and name use |
|---|---|
| `wallclock` (default) | The time the camera showed |
| `local` | That moment converted to this computer's time zone |
| `utc` | That moment converted to UTC |

Dates without a recorded offset are always used as they are. When setting file times they are assumed to be
in this computer's local time zone.

### Date patterns in file names

| Example name | Date found |
|---|---|
| `IMG_20190704_153012.jpg` | 2019-07-04 15:30:12 |
| `PXL_20190704_153012345.jpg` | 2019-07-04 (time ignored) |
| `20190704153012.jpg` | 2019-07-04 15:30:12 |
| `Screenshot_20190704-153012.png` | 2019-07-04 15:30:12 |
| `Screenshot 2019-07-04 at 15.30.12.png` | 2019-07-04 15:30:12 |
| `Screenshot from 2019-07-04 15-30-12.png` | 2019-07-04 15:30:12 |
| `WhatsApp Image 2019-07-04 at 15.30.12.jpeg` | 2019-07-04 15:30:12 |
| `signal-2019-07-04-15-30-12.jpg` | 2019-07-04 15:30:12 |
| `IMG-20190704-WA0001.jpg` | 2019-07-04 (no time) |
| `FB_IMG_1562254212345.jpg` | none (a millisecond counter is not a date) |
| `IMG_20190230.jpg` | none (not a real date) |

A name with a date but no (valid) time gets the date only. Such a file is **never renamed** by
`rename_by_date`, because the time would be invented.

### File types

| Type | EXIF | Notes |
|---|---|---|
| JPEG (`.jpg`, `.jpeg`) | yes | Standard EXIF in the APP1 segment |
| PNG (`.png`) | rarely | Only the `eXIf` chunk is read; most PNGs have none and use the file name or modification time |
| HEIC/HEIF (`.heic`, `.heif`) | yes | Read from the file's box structure (`meta`, `iinf`, `iloc`); the image data is skipped, never decoded |
| BMP (`.bmp`) | no | The format has no metadata; file name or modification time is used |
| MP4 and MOV movies (`.mp4`, `.mov`) | not read | Only with `handle_movies = yes`; filed into a movies sub-folder, dated by file name or modification time |

### Folder layouts (`output_folderstructure`)

| Value | Example |
|---|---|
| `YYYY` | `2019/` |
| `YYYY_MM` | `2019_07/` |
| `YYYY/MM` | `2019/07/` |
| `YYYY/YYYY-MM` | `2019/2019-07/` |
| `YYYY/MM/DD` | `2019/07/04/` |

Files without any usable date go to `unknown_date/` (name configurable), regardless of the layout.

### Movies (`handle_movies`, `movies_folder`)

By default `.mp4` and `.mov` files are left alone and listed in `unknown_files.csv`. With `handle_movies = yes` they are
sorted like photos, into a sub-folder of their date folder (the name is `movies_folder`, default `movies`):

| `output_folderstructure` | Photo | Movie |
|---|---|---|
| `YYYY_MM` | `2019_07/IMG_1.jpg` | `2019_07/movies/VID_1.mp4` |
| `YYYY/MM` | `2019/07/IMG_1.jpg` | `2019/07/movies/VID_1.mp4` |
| `YYYY/MM/DD` | `2019/07/04/IMG_1.jpg` | `2019/07/04/movies/VID_1.mp4` |

- A movie has no EXIF, so its date comes from the **file name** (`VID_20190704_153012.mp4`) and otherwise from the **file
  modification time**. The creation time stored inside the movie is not read. A movie with neither goes to
  `unknown_date/movies`. Check the `date_source` column in the report.
- Everything else works as for photos: copy or move, SHA-256 verification, duplicate detection (also across names),
  `rename_by_date` (only for names that contain date and time), `skip_hidden`, the test run and the report.
- Movies are large. In copy mode they need the space twice, and with `verify = yes` each one is read a second time.
- Only `.mp4` and `.mov` (any letter case). Other video formats stay unsupported.

### Renaming by date (`rename_by_date`)

Empty means keep the original name. Otherwise it is a pattern of `strftime` codes plus `{original}` for
the old name without extension:

| Pattern | Result for `IMG_0042.JPG` taken 2019-07-04 15:30:12 |
|---|---|
| `%Y%m%d_%H%M%S` | `20190704_153012.JPG` |
| `%Y-%m-%d_%H%M%S_{original}` | `2019-07-04_153012_IMG_0042.JPG` |
| `{original}_%Y` | `IMG_0042_2019.JPG` |

Only files with a real capture time are renamed (EXIF original or digitized, or a file name with date
**and** time). The extension keeps its original case. Two photos with the same name afterwards get
`_001`, `_002` ...

### Duplicates (`duplicate_policy`)

- **Same name, different content:** the newcomer becomes `NAME_001.ext`, `NAME_002.ext` ... (three digits,
  growing to four after 999).
- **`skip_identical` (default):** a file whose *content* already exists anywhere in the output folder, under
  any name and in any sub-folder, including files from earlier runs, is not copied again. Only files of a type listed in
  `extensions` (plus movies with `handle_movies`) are compared. The original stays
  where it is, also in move mode. For duplicate detection a file is only read and hashed when another file of exactly the same size exists.
- **`rename`:** content is never compared; every name clash is numbered.
- If the same content appears several times in the input, the one scanned first is kept.

## Configuration reference

All options live in `config.ini` ([`config.example.ini`](config.example.ini) documents each one in place).
Relative paths are resolved against the folder that contains the configuration file, not against the working
directory. `~` and environment variables such as `${HOME}` are expanded. Comments must be on their own line:
a `;` after a value becomes part of the value (and usually produces an error).

### `[folders]`

| Option | Default | Description |
|---|---|---|
| `input_folder` | required | Folder to scan. Must exist |
| `output_folder` | required | Destination. Created when needed. Must not be inside the input folder or contain it |

### `[organization]`

| Option | Default | Values | Description |
|---|---|---|---|
| `output_folderstructure` | `YYYY_MM` | `YYYY`, `YYYY_MM`, `YYYY/MM`, `YYYY/YYYY-MM`, `YYYY/MM/DD` | Folder layout below the output folder |
| `unknown_date_folder` | `unknown_date` | a folder name | Where files without a usable date go |
| `handle_movies` | `no` | `yes`/`no` | `yes`: also sort `.mp4` and `.mov` files, into a sub-folder of their date folder |
| `movies_folder` | `movies` | a folder name | Name of that sub-folder, for example `2019_07/movies` |
| `testrun` | `yes` | `yes`/`no` | `yes`: only write the CSV reports |
| `copy_mode` | `yes` | `yes`/`no` | `yes`: copy. `no`: move (copy, verify, then delete the original) |
| `change_timestamp` | `no` | `yes`/`no` | Set the copy's modification time to the EXIF capture time (EXIF dates only) |
| `set_creation_time` | `no` | `yes`/`no` | Windows only: also set "Date created". Needs `change_timestamp = yes`; ignored with a warning elsewhere |
| `verify` | `yes` | `yes`/`no` | SHA-256 check of every copy. Must be `yes` when `copy_mode = no` |
| `rename_by_date` | empty | pattern | Rename by capture date; empty keeps names |
| `cleanup_empty_folders` | `no` | `yes`/`no` | After a move, remove input sub-folders emptied by this run. Never the input folder itself. Not simulated in a test run |

### `[dates]`

| Option | Default | Values | Description |
|---|---|---|---|
| `use_filename_date` | `yes` | `yes`/`no` | Use a date found in the file name |
| `use_exif_modify_date` | `no` | `yes`/`no` | Use EXIF `DateTime` (last edit) before the modification time |
| `use_filesystem_mtime` | `yes` | `yes`/`no` | Last resort. `no` sends such files to the unknown-date folder |
| `timezone_mode` | `wallclock` | `wallclock`, `local`, `utc` | Which time names the folders when an offset is recorded |
| `min_year` | `1990` | 1900 to 2100 | Earlier dates are rejected |
| `reject_future_dates` | `yes` | `yes`/`no` | Reject dates later than tomorrow |

### `[behavior]`

| Option | Default | Values | Description |
|---|---|---|---|
| `recursive` | `yes` | `yes`/`no` | Scan sub-folders |
| `duplicate_policy` | `skip_identical` | `skip_identical`, `rename` | See [Duplicates](#duplicates-duplicate_policy) |
| `skip_hidden` | `yes` | `yes`/`no` | Skip dot-names, the Windows hidden/system attribute and the macOS hidden flag |
| `extensions` | `.jpg,.jpeg,.png,.bmp,.heic,.heif` | subset of those six | File types to process. Others are refused with a clear message |
| `reports_folder` | `./reports` | path | Folder for both CSV reports. Relative to the folder of `config.ini`, created when needed. `.` keeps them next to `config.ini`. Must not be inside the input folder |
| `report_csv` | `organizer_report.csv` | file name | Report of every file, written in the reports folder. An absolute path is used as written (and then ignores `reports_folder`) |
| `report_skipped` | `yes` | `yes`/`no` | Skipped files (type, symlink, hidden) get a row and are counted |
| `unknown_files_csv` | `unknown_files.csv` | file name | Lists unsupported files, in the reports folder (an absolute path is used as written). Written, with a warning, only when there are some |

## Recipes

**First look, change nothing.** Keep `testrun = yes` and open `organizer_report.csv`.

**Archive by day, named by capture time:**

```ini
[organization]
output_folderstructure = YYYY/MM/DD
rename_by_date = %Y%m%d_%H%M%S_{original}
```

**Move, then tidy the input folder:**

```ini
[organization]
copy_mode = no
cleanup_empty_folders = yes
```

**Trust only real EXIF dates** (everything else is parked for you to review):

```ini
[dates]
use_filename_date = no
use_filesystem_mtime = no
```

**Merge into an existing library without duplicates.** Point `output_folder` at the library and keep
`duplicate_policy = skip_identical`. Photos already in the library (under any name, in any folder) are skipped.

**Keep file times honest after copying** (Windows):

```ini
[organization]
change_timestamp = yes
set_creation_time = yes
```

**Group by UTC day instead of camera time:**

```ini
[dates]
timezone_mode = utc
```

## Reports and exit codes

### `organizer_report.csv`

Always written, also in a test run, in the reports folder (`reports_folder`, by default a `reports` folder next to
`config.ini`) and overwritten on every run. UTF-8 with BOM, so Excel opens it correctly. Keep an old report by copying it first.

| Column | Content |
|---|---|
| `source` | The input file (or folder) |
| `destination` | Where it goes or went; for `skipped_identical` the existing identical file |
| `date_source` | Which source supplied the date, see the table above |
| `date_recorded` | The date as recorded, with its UTC offset when known |
| `date_used` | The time used for the folder name (differs from the above with `timezone_mode`) |
| `action` | `copy`, `move`, `skip`, `scan` or `remove_empty_folder` |
| `status` | See below |
| `details` | Notes: rejected dates, renames, warnings, errors |

| `status` | Meaning |
|---|---|
| `planned` | Test run: would be processed |
| `completed` | Copied or moved (or an empty folder removed) |
| `skipped_identical` | Identical content already in the output folder |
| `skipped_extension` | Unsupported file type |
| `skipped_symlink` | Symbolic link or junction (not followed) |
| `skipped_hidden` | Hidden file or folder (a folder counts once) |
| `error` | Could not be processed; see `details` |

### `unknown_files.csv`

Columns `path`, `extension`, `size_bytes`. Written, with a warning on screen, only when unsupported files
are found. It is overwritten when new ones are found and is never deleted by the program.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Finished. Skipped and unsupported files do not count as failures |
| `1` | At least one file ended in `error` |
| `2` | Configuration or startup problem (message on stderr) |
| `130` | Interrupted with Ctrl-C. The report so far is saved (an interrupt during the preliminary scan leaves an earlier report untouched); no file is left half-written |

## Safety guarantees

- **Nothing is overwritten.** On file systems with hard links (NTFS, ext4, APFS and most others) the final name is
  claimed in one atomic step, so even a file that appears at the last moment is never replaced. On FAT, exFAT and some
  network shares the program checks the name and then renames the finished copy. A half-written file can still never
  carry the final name there, but a file that someone else creates in the microseconds between the check and the rename
  could be replaced on Linux and macOS (Windows refuses).
- **Copies are verified.** The SHA-256 of the bytes read is compared with a re-read of the copy. A mismatch
  publishes nothing.
- **Originals are deleted only after verification**, in move mode, and only if the source is unchanged. If
  anything differs, the original stays and the verified copy is kept.
- **A bad file never stops the run.** It gets an `error` row and the rest continues.
- **Temporary files** (`.photo-organizer-*.tmp`) are removed after a successful copy, after a failed one and after Ctrl-C,
  and are never counted as photos. If the computer loses power or the process is killed, one can remain; it is safe to delete.
- **Read-only originals** are handled: the copy is read-only too, and in move mode the verified original is deleted
  after its read-only attribute is cleared.
- **The test run is faithful.** It predicts the same destinations as a real run (this is covered by tests).
- Do not run two instances on the same output folder at the same time.
- **What verification does and does not prove.** The copy is read back and compared, which catches errors in the program
  and in the copy. The read-back may be served from the operating system's cache, so it cannot promise to catch a silently
  failing disk. Keep a backup before a first move.

Move mode has no undo. Use copy mode first; `organizer_report.csv` records source and destination of every file.

## Platform notes

- **Windows:** paths may use backslashes. Hidden and system attributes are honoured. `set_creation_time`
  works through the Windows API (`ctypes`, no install). Long paths get the `\\?\` prefix when setting the
  creation time. Network shares and FAT/exFAT may refuse or round times; such a failure is a note in
  `details`, never an error. You can verify your drive with
  `python tools/check_windows_creation_time.py D:\photos_sorted`.
- **macOS:** the hidden flag is honoured. "Date created" is not set explicitly; macOS normally lowers it
  when the modification time is set to an earlier date.
- **Linux:** only dot-names count as hidden. "Date created" cannot be set.
- Symlinks are never followed on any system. Windows junctions are skipped only on Python 3.12 and newer.
- Windows limits paths to 260 characters unless long paths are enabled. A destination that is too long gives that file an
  `error` row; the others continue.
- Photos in a cloud folder that keeps files online only (OneDrive "Files On-Demand", for example) are downloaded when they are
  read. Make them available offline first if you do not want that during the run.

## FAQ and troubleshooting

**A photo landed in the month I copied it, not the month I took it.**
No usable date was found, so the modification time was used (see `date_source` and `details`). Check whether the
file has EXIF at all; PNG and BMP usually do not. Use `use_filesystem_mtime = no` to park such files instead.

**Why was a date rejected?**
`details` says so, for example `DateTimeOriginal 2099-01-01 rejected (in the future)`. Lower `min_year` if
your photos are genuinely older than 1990.

**Why is a file `skipped_identical` when I never copied it before?**
Another file with exactly the same bytes exists in the output folder (any name, any folder, of a supported type) or
earlier in the same run. `destination` shows which one.

**The same photo is in the output twice.**
Use `duplicate_policy = skip_identical`. With `rename`, content is never compared. Files that look identical
but differ by a single byte (re-saved, metadata edited) are different files.

**Where are my movies / RAW files?**
Set `handle_movies = yes` for `.mp4` and `.mov`; they go into a `movies` sub-folder. Other video formats and RAW files are not supported; they are listed in `unknown_files.csv`. The `.mov` half of an iPhone
Live Photo is listed there too unless `handle_movies = yes`, in which case it is filed into the movies folder. Either way the
HEIC half is sorted by its EXIF date and the two halves are not kept together.

**My HEIC photo went to the wrong month.**
Run `python tools/inspect_exif.py IMG_1234.HEIC`. It shows whether EXIF was found, the file structure and the
date that is used. A HEIC that was exported or edited by another program may have lost its EXIF; then the file name
or modification time is used. If the structure looks normal but no date is found, please open an issue with the
tool's output.

**Can I undo a move?**
There is no undo command. `organizer_report.csv` lists source and destination per file, so you can reverse it
by script. Prefer copy mode first.

**On Windows one file ended in `error` and the others were fine. The details mention a path length.**
Windows allows 259 characters for the whole path (output folder, date folders and file name) unless long paths are
enabled. The `details` column says how long the destination was. Either use a shorter output folder, a shorter
`output_folderstructure`, or `rename_by_date` to shorten the names, or switch on long paths: set the registry value
`LongPathsEnabled` (a DWORD, `1`) under `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem`, or enable the group policy
"Enable Win32 long paths", then restart the program. Microsoft's documentation calls this "Maximum Path Length Limitation".

**I get `ERROR: Unsupported extension(s) in config`.**
Only `.jpg`, `.jpeg`, `.png`, `.bmp`, `.heic` and `.heif` can be listed in `extensions`.

**`ERROR: [organization] testrun: expected yes or no, got 'yes ; comment'`.**
Put comments on their own line; a `;` after a value is part of the value.

**Why are the Windows and macOS "Date created" values the copy time?**
`change_timestamp` sets the modification time only. On Windows add `set_creation_time = yes`.

## Tested with real devices

The EXIF readers were checked against files from real phones, besides files built byte by byte and files written by
independent encoders. Each device below is represented by **one** file, so this shows the layouts work, not that every model
of that brand does.

| Source | Format | What it exercised |
|---|---|---|
| iPhone | HEIC | `iloc` version 1, 49 image items, grid and Exif items, 64-bit `mdat` size, big-endian Exif, `OffsetTime*` tags |
| Android phone (Qualcomm) | JPEG | Exif first, ICC profile, 65535-byte vendor segment, big-endian Exif |
| Samsung Galaxy A57 | JPEG | Little-endian Exif, **negative** UTC offset (-04:00), restart-interval marker, vendor trailer after the image |
| Android phones, after an upload re-encode | JPEG | No EXIF at all: file name and modification time are used |
| libavif (through Pillow) | AVIF | Box structure of an independent writer, same layout as HEIC. Used only to test the HEIC reader; `.avif` files are not processed |

Sanitised copies of these files (structure and dates only) are in `tests/fixtures/`. Not yet checked with real files:
Google Pixel, Huawei or Xiaomi photos, HEIC from non-Apple phones, HEIC edited or exported by other programs, DSLR and
mirrorless JPEGs, and the real Windows and macOS file-system behaviour, which the CI workflow covers once it has run.

### Operating systems

| System | What was run | Result |
|---|---|---|
| Linux (development machine, Python 3.12) | Full test suite, the four device files, packaging | All pass |
| Windows (one machine) | Full test suite of 0.3.2 (419 tests, 91 s), including the tests that call the real Windows API for "Date created", the read-only file tests, the long-path tests and `tools/check_windows_creation_time.py` | 403 passed, 16 skipped as designed (11 need Pillow, 3 need symlink rights, 1 needs `tzset`, 1 is for other systems), 0 failed. The first run, of 0.3.1, had one test that assumed long paths work; fixed in 0.3.2 |
| macOS 14.5, Python 3.13.2 | The program in everyday use | Runs. The full test suite has not been run there yet (`python run_tests.py` does that); the CI workflow covers macOS once pushed |

An image upload to a chat or cloud service often re-encodes photos and removes their EXIF; always sort the original files.

## Limitations

- Movies: only `.mp4` and `.mov`, and only filed away. Their date comes from the file name or modification time, never from
  inside the file. No other video formats, RAW, TIFF, GIF, WebP or AVIF in this release. With `handle_movies = yes` the `.mov` half of a Live Photo is
  filed into the movies folder, apart from its HEIC; without it, it is only listed in `unknown_files.csv`.
- XMP-only dates are not read.
- No sidecar (`.xmp`, `.aae`) or RAW+JPG pair handling.
- No undo for moves.
- Duplicates are exact byte matches; visually similar photos are not detected.

## Development

```bash
git clone https://github.com/MauPoLom/photo-organizer.git
cd photo-organizer
python run_tests.py            # standard library only; writes test-report.txt
python -m unittest discover    # the same tests, plain output
```

`python run_tests.py` is the easiest way to report a problem. It runs every test and writes the whole log to
`test-report.txt`. Plain `python -m unittest` prints the same environment block at the start and a one-line recap
at the end, so a pasted log always says where it came from. Options: `--brief` (dots instead of one line per test),
`--durations 10` (the ten slowest tests, Python 3.12 or newer) and `--report FILE`.

The environment block looks like this (Linux example; on Windows it shows the Windows version, build and edition):

```text
======================== Test environment ========================
Run started           : 2026-10-28T10:29:14+00:00
Program               : photo_organizer 1.1.0 (created 2026-11-03 10:43:20 UTC)
Operating system      : Ubuntu 24.04.4 LTS (kernel 6.18.44-fc-v180, x86_64)
Python                : 3.12.3 CPython, 64-bit (GCC 13.3.0)
Python executable     : /usr/bin/python3 (virtual environment: no)
CPU cores             : 1
Time zone             : UTC (UTC+00:00)
Encodings             : file names utf-8, locale utf-8, console utf-8, UTF-8 mode on
Temporary folder      : /tmp (4 characters)
Its file system       : ext4
Long paths (Windows)  : not applicable (not Windows)
Hard links            : yes (the program publishes copies atomically)
Symlinks              : allowed
POSIX tzset / SIGALRM : yes / yes
Pillow (optional)     : 12.1.1 (AVIF writing: yes)
==================================================================
```

| Line | Why it is there |
|---|---|
| `Run started` | Which run a log belongs to, with the UTC offset of the machine |
| `Program` | The version of `photo_organizer.py` that was tested |
| `Operating system` | Windows: name, feature release, build with update revision and edition. macOS: version. Linux: distribution and kernel |
| `Python` | Version, implementation, 32 or 64 bit and compiler |
| `Python executable` | Which Python ran, and whether it is a virtual environment |
| `CPU cores` | Explains a slow run |
| `Time zone` | The tests for `timezone_mode = local` depend on it |
| `Encodings` | The cause of most "character cannot be shown" problems on Windows |
| `Temporary folder` | Where the tests create files. Its length decides whether Windows' 259-character path limit is reached |
| `Its file system` | NTFS, exFAT, ext4 ... exFAT and FAT have no hard links, which selects the rename fallback |
| `Long paths (Windows)` | The registry switch `LongPathsEnabled`; off means paths over 259 characters fail |
| `Hard links` | Tested for real in the temporary folder |
| `Symlinks` | Tested for real; when not permitted (Windows without Developer Mode) the symlink tests are skipped |
| `POSIX tzset / SIGALRM` | Two POSIX-only features some tests use; without them one test is skipped and the crafted-file tests run without a time limit |
| `Pillow (optional)` | Not installed means the Pillow cross-check tests are skipped; `pip install pillow` enables them |

The report ends with a summary that counts passed, failed, errored and skipped tests, groups the skipped ones by reason
and lists the names of failed tests, followed by a line such as
`Tested on: Windows 11 24H2 (build 26100.2605, Pro, AMD64) | Python 3.13.1 CPython, 64-bit | photo_organizer 1.1.0 (created 2026-11-03 10:43:20 UTC)`.
`tools/inspect_exif.py` and `tools/check_windows_creation_time.py` start with the same line.

| Path | Purpose |
|---|---|
| `photo_organizer.py` | The whole program (single file, standard library only) |
| `config.example.ini` | Documented example configuration |
| `tests/` | Unit and end-to-end tests that build real JPEG/PNG/BMP/HEIC files byte by byte |
| `tests/fixtures/` | Sanitised files from real phones (structure and date fields only); see its README |
| `tools/check_windows_creation_time.py` | Windows self-check for `set_creation_time` |
| `tools/inspect_exif.py` | Shows what is read from a photo and which date would be used |
| `tools/release.py` | Makes a release: bumps the version, stamps the creation time, closes the changelog section |
| `tools/environment.py` | Describes the machine (used by the tests and the tools; run it directly to see the block above) |
| `run_tests.py` | Runs the whole suite and writes `test-report.txt` with the environment and a summary |
| `.github/workflows/ci.yml` | Tests on Linux and Windows for Python 3.9 to 3.13 and on macOS for 3.10 to 3.13 |

Tests worth knowing about: byte-level HEIC/JPEG/PNG fixtures, parser fuzzing and truncation, dry-run versus live equivalence for many option
combinations, simulated `kernel32` calls for the Windows API, release hygiene (version, changelog, every config
key documented here), and an optional Pillow cross-check (JPEG, PNG and AVIF files written by independent encoders) that runs only when Pillow happens to be installed.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow and the release checklist.

## Versioning

[Semantic Versioning](https://semver.org). The version lives in one place, `__version__` in
`photo_organizer.py`, and is printed by `--version`. Every change is listed in the [changelog](CHANGELOG.md).
Renamed or removed options, changed folder naming and changed CSV columns or statuses count as breaking and
only come with a new major version.

## License

[MIT](LICENSE), Copyright (c) 2026 MauPoLom.
