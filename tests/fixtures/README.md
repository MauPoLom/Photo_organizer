# Test fixtures from real devices

These files came from real phones and were **sanitised before being added**. They exist so that the tests exercise
the file structures that real devices produce, not only structures built by the test helpers.

| File | Origin | What was kept | What was removed |
|---|---|---|---|
| `IMG_9347.HEIC` | iPhone HEIC photo | The `ftyp` and `meta` boxes byte for byte (49 image items, a grid item, an Exif item, `iloc` version 1), the 64-bit `mdat` header, the item offsets | All image data; the Exif block was rebuilt with the date, time zone offset and sub-second fields only; the file is cut off right after the Exif item (its image items point beyond the end) |
| `IMG20260715143429.jpg` | Android JPEG (original camera file) | The marker/segment layout: Exif first, ICC profile, a maximum-length (65535 byte) vendor segment, quantisation and Huffman tables, scan header; big-endian Exif | All image data; the vendor debug segments were zeroed (same length); the Exif block was rebuilt with the date, time zone offset and sub-second fields only |
| `IMG_20210727_133442.jpg` | Android JPEG after a re-encode (no EXIF) | Header segments (JFIF, ICC profile, tables) | All image data (the file ends right after the scan header) |
| `20260822_185518.jpg` | Samsung Galaxy A57 JPEG (original camera file) | Segment layout (Exif first, ICC profile, a 38971-byte vendor blob, tables, restart interval), little-endian Exif with a negative UTC offset, the closing bytes of Samsung's trailer after the image | All image data; the vendor blob was zeroed; the Exif block was rebuilt with date, offset and sub-second fields only; the 221-byte trailer (it held a network country code, a UTC time and scene information) was zeroed except its final 12 structure bytes |

The file names are the original ones; they contain only a capture date or counter. The ICC profiles that remain are
the standard colour profiles (for example Display P3), not personal data.

## Rules for new fixtures

1. Only add files whose owner agreed. Never commit a real photo.
2. Remove the image data (nothing after the scan header for JPEG, nothing after the Exif item for HEIC).
3. Rebuild the Exif block with date fields only: IFD0 `DateTime`, and in the Exif IFD `DateTimeOriginal`,
   `DateTimeDigitized`, `OffsetTime*` and `SubSecTime*`. No make, model, serial number, lens, maker note,
   GPS or thumbnail.
4. Keep files under 100 KB.
5. Describe the new file in the table above. `tests/test_real_world_fixtures.py` checks the anonymity rules and that every
   fixture is documented here.
