# Contributing

Thanks for helping. The project has a few firm rules that keep it simple to trust and to run:

1. **Standard library only.** The program must run with a plain Python install. No runtime dependencies.
   (Test-only extras such as Pillow may be used *optionally*, and tests must skip when they are missing.)
2. **Python 3.9 compatible.** No `match`, no `X | Y` at runtime (annotations are fine thanks to
   `from __future__ import annotations`), no parenthesised multi-line `with`, nothing newer than 3.9 in the
   standard library unless guarded.
3. **Never lose or overwrite a photo.** Any change near copying, moving or deleting needs tests for the failure
   paths, not just the happy path.
4. **Real devices beat invented files.** `tests/fixtures/` holds sanitised files from real phones; see its README for
   the rules before adding one (owner's consent, no image data, date fields only).
5. **Hostile input is normal input.** A parser must bound its work on a crafted file (counts, sizes, loops that must consume
   data) and report damage as a warning, never raise or hang. Add a test with a crafted file and a deadline.
6. **Tests use real files.** Build JPEG/PNG/BMP bytes (see `tests/helpers.py`) and run the real code. Mock only
   things that cannot happen in a test (a failing disk, the Windows API off Windows).

## Setup

```bash
git clone https://github.com/MauPoLom/photo-organizer.git
cd photo-organizer
python run_tests.py                 # nothing to install; writes test-report.txt with the environment
python -m unittest discover -v      # the same tests, plain output
```

Run one module or test:

```bash
python -m unittest tests.test_transfer -v
python -m unittest tests.test_config.Paths.test_missing_input_folder
```

## Layout

| Path | What |
|---|---|
| `photo_organizer.py` | Whole program. Sections: configuration, EXIF reading, date choice, scanning, hashing/duplicates, Windows creation time, transfer, `run()`, `main()` |
| `tests/helpers.py` | Byte-level JPEG/PNG/BMP builders and the `Base` test case (temp folders, config writer, `go()` to run the organizer) |
| `tests/test_*.py` | One module per area (EXIF, dates, scanning, transfer, config, end-to-end, CLI, Windows, release checks, Pillow interop) |
| `tools/` | Helper scripts that are not part of the program (`inspect_exif.py` is the first thing to run on a photo that sorts wrongly) |

## Making a change

1. Open an issue first for anything bigger than a bug fix, so the idea can be shaped before you write code.
2. Write the test first or together with the change, and for a bug fix run it against the old code to see it fail.
3. Keep the change focused; unrelated clean-ups belong in a separate pull request.
4. Add a line under **Unreleased** in `CHANGELOG.md`.
5. Run `python -m unittest discover` locally. CI runs it on Linux, Windows and macOS for Python 3.9 to 3.13.

### Adding or changing a config option

The release tests fail until all of these agree:

- `read_config()` in `photo_organizer.py` (default, parsing, validation)
- `config.example.ini` (with a comment that says what it does)
- the option tables in `README.md`
- tests for the default, a valid value and invalid values in `tests/test_config.py`, plus behaviour tests

### Adding a file type

Each type needs a reader that returns the same tag dictionary as `read_exif_dates()` (or nothing), tests with
byte-level fixtures including truncated and corrupted variants, an entry in `SUPPORTED_EXTENSIONS`, and the
README table. A format that cannot be read with the standard library alone needs a discussion first, because
of rule 1.

### Changing the report

The CSV columns, status names and `date_source` values are a public interface. Changing them is a breaking
change (see Versioning below); update README and CHANGELOG, and the release tests will tell you what else.

## Versioning and releases

[Semantic Versioning](https://semver.org). The only place the version is written is `__version__` in
`photo_organizer.py`.

| Change | Bump |
|---|---|
| Bug fix, no behaviour change otherwise | patch (`1.1.0` to `1.1.1`) |
| New option or feature, backwards compatible | minor (`1.1.0` to `1.2.0`) |
| Renamed/removed option, changed folder naming, changed CSV columns or statuses | major (`1.1.0` to `2.0.0`) |

Release checklist:

1. Describe the changes under `## [Unreleased]` in `CHANGELOG.md`.
2. `python tools/release.py minor --dry-run` (or `patch`, `major`, `set X.Y.Z`) to see what will change, then without
   `--dry-run`. It writes `__version__` and the creation time (`__created__`, UTC) into `photo_organizer.py` and turns
   the changelog section into `## [X.Y.Z] - YYYY-MM-DD`. Never edit those two lines by hand.
3. `python run_tests.py` must pass (the release tests check that version, creation time and changelog agree).
4. Commit, then tag and push (the tool prints these commands):

   ```bash
   git commit -am "Release X.Y.Z"
   git tag -a vX.Y.Z -m "Version X.Y.Z"
   git push origin main --tags
   ```

5. Create a GitHub release from the tag and paste the changelog section.

## Reporting bugs

Run `python run_tests.py` and attach `test-report.txt`: it starts with the operating system and Python version, whether
long paths, symlinks and hard links work on that machine, and ends with a summary of what failed or was skipped.

Use the bug report template. The most useful information: the version, the relevant rows of
`organizer_report.csv`, and, when EXIF is involved, a copy of the photo.
