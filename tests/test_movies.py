"""handle_movies and movies_folder: .mp4 and .mov files are filed into a sub-folder of their date folder."""
import os
import shutil
from datetime import datetime

import photo_organizer as org
from tests.helpers import BMP, Base, exif_jpeg

MTIME = datetime(2021, 5, 6, 7).timestamp()


class MoviesOff(Base):
    def test_default_leaves_movies_alone_and_lists_them(self):
        self.put("VID_20190704_153012.mp4", b"movie")
        self.put("clip.MOV", b"movie")
        self.go()
        self.assertEqual(self.outfiles(), [])
        self.assertEqual({r["status"] for r in self.rows()}, {"skipped_extension"})
        self.assertTrue((self.root / "unknown_files.csv").exists())

    def test_explicit_no_is_the_same(self):
        self.put("a.mp4", b"movie")
        self.go(handle_movies="no")
        self.assertEqual(self.row("a.mp4")["status"], "skipped_extension")


class MoviesOn(Base):
    def test_movie_goes_into_the_movies_folder_for_every_layout(self):
        self.put("VID_20190704_153012.mp4", b"movie")
        expected = {"YYYY_MM": "2019_07/movies", "YYYY/MM": "2019/07/movies", "YYYY/YYYY-MM": "2019/2019-07/movies",
                    "YYYY/MM/DD": "2019/07/04/movies", "YYYY": "2019/movies"}
        for layout, folder in expected.items():
            with self.subTest(layout):
                self.go(handle_movies="yes", output_folderstructure=layout)
                self.assertEqual(self.outfiles(), [folder + "/VID_20190704_153012.mp4"])
                shutil.rmtree(self.out)

    def test_folder_name_is_configurable(self):
        self.put("VID_20190704_153012.mov", b"movie")
        self.go(handle_movies="yes", movies_folder="films")
        self.assertEqual(self.outfiles(), ["2019_07/films/VID_20190704_153012.mov"])

    def test_photos_and_movies_are_sorted_side_by_side(self):
        self.put("IMG_1.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("VID_20190705_101500.mp4", b"movie")
        self.put("clip.avi", b"other video")
        self.go(handle_movies="yes")
        self.assertEqual(self.outfiles(), ["2019_07/IMG_1.jpg", "2019_07/movies/VID_20190705_101500.mp4"])
        self.assertEqual(self.row("clip.avi")["status"], "skipped_extension")  # other formats stay unsupported
        listed = (self.root / "unknown_files.csv").read_text(encoding="utf-8-sig")
        self.assertIn("clip.avi", listed)
        self.assertNotIn(".mp4", listed)

    def test_upper_case_extensions(self):
        self.put("VID_20190704_153012.MP4", b"a")
        self.put("VID_20190705_153012.Mov", b"b")
        self.go(handle_movies="yes")
        self.assertEqual(self.outfiles(), ["2019_07/movies/VID_20190704_153012.MP4", "2019_07/movies/VID_20190705_153012.Mov"])

    def test_modification_time_is_used_without_a_date_in_the_name(self):
        self.put("IMG_0042.MOV", b"movie", mtime=MTIME)
        self.go(handle_movies="yes")
        self.assertEqual(self.outfiles(), ["2021_05/movies/IMG_0042.MOV"])
        self.assertEqual(self.row("IMG_0042.MOV")["date_source"], org.SRC_MTIME)

    def test_file_name_date_beats_the_modification_time(self):
        self.put("VID_20190704_153012.mp4", b"movie", mtime=MTIME)
        self.go(handle_movies="yes")
        self.assertEqual(self.row("VID_20190704_153012.mp4")["date_source"], org.SRC_FILENAME)

    def test_no_date_at_all_goes_to_unknown_date_movies(self):
        self.put("IMG_0042.MOV", b"movie", mtime=MTIME)
        self.go(handle_movies="yes", use_filesystem_mtime="no")
        self.assertEqual(self.outfiles(), ["unknown_date/movies/IMG_0042.MOV"])
        shutil.rmtree(self.out)  # otherwise the second run rightly skips the identical movie
        self.go(handle_movies="yes", use_filesystem_mtime="no", unknown_date_folder="undated", movies_folder="films")
        self.assertEqual(self.outfiles(), ["undated/films/IMG_0042.MOV"])

    def test_no_misleading_exif_warning_for_movies(self):
        self.put("VID_20190704_153012.mp4", b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  ")
        self.go(handle_movies="yes")
        self.assertEqual(self.row("VID_20190704_153012.mp4")["details"], "")

    def test_a_movie_and_a_photo_with_the_same_name_do_not_collide(self):
        self.put("20190704_153012.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("20190704_153012.mp4", b"movie")
        self.go(handle_movies="yes")
        self.assertEqual(self.outfiles(), ["2019_07/20190704_153012.jpg", "2019_07/movies/20190704_153012.mp4"])

    def test_duplicate_movies_are_detected_by_content(self):
        self.put("a/VID_20190704_153012.mp4", b"same movie")
        self.put("b/copy.mp4", b"same movie")
        self.put("c/VID_20190704_153012.mp4", b"other movie")
        self.go(handle_movies="yes")
        self.assertEqual(self.outfiles(), ["2019_07/movies/VID_20190704_153012.mp4", "2019_07/movies/VID_20190704_153012_001.mp4"])
        self.assertEqual(self.row("copy.mp4")["status"], "skipped_identical")

    def test_a_second_run_finds_the_movies_already_there(self):
        self.put("VID_20190704_153012.mp4", b"movie")
        self.go(handle_movies="yes")
        self.go(handle_movies="yes")
        self.assertEqual(self.row("VID_20190704_153012.mp4")["status"], "skipped_identical")
        self.assertEqual(self.outfiles(), ["2019_07/movies/VID_20190704_153012.mp4"])

    def test_rename_by_date_needs_a_date_and_time_in_the_name(self):
        self.put("VID_20190704_153012.mp4", b"a")
        self.put("VID-20190705-WA0001.mp4", b"b")  # date only: keeps its name
        self.go(handle_movies="yes", rename_by_date="%Y%m%d_%H%M%S_{original}")
        self.assertEqual(self.outfiles(), ["2019_07/movies/20190704_153012_VID_20190704_153012.mp4",
                                           "2019_07/movies/VID-20190705-WA0001.mp4"])

    def test_move_mode_and_cleanup(self):
        self.put("trip/VID_20190704_153012.mp4", b"movie")
        self.go(handle_movies="yes", copy_mode="no", cleanup_empty_folders="yes")
        self.assertEqual(self.outfiles(), ["2019_07/movies/VID_20190704_153012.mp4"])
        self.assertFalse((self.inp / "trip").exists())

    def test_test_run_predicts_the_live_run(self):
        self.put("IMG_1.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("VID_20190704_153012.mp4", b"a")
        self.put("x/VID_20190704_153012.mp4", b"b")
        self.put("IMG_9.MOV", b"c", mtime=MTIME)
        self.go(handle_movies="yes", testrun="yes")
        planned = sorted((os.path.basename(r["source"]), os.path.relpath(r["destination"], self.out)) for r in self.rows())
        self.assertFalse(self.out.exists())
        self.go(handle_movies="yes")
        live = sorted((os.path.basename(r["source"]), os.path.relpath(r["destination"], self.out)) for r in self.rows())
        self.assertEqual(planned, live)

    def test_a_large_movie_is_streamed_and_verified(self):
        data = os.urandom(5 * 1024 * 1024 + 17)
        self.put("VID_20190704_153012.mp4", data)
        self.go(handle_movies="yes")
        self.assertEqual((self.out / "2019_07" / "movies" / "VID_20190704_153012.mp4").read_bytes(), data)

    def test_hidden_movies_are_still_skipped(self):
        self.put(".VID_20190704_153012.mp4", b"movie")
        self.go(handle_movies="yes")
        self.assertEqual(self.row(".VID_20190704_153012.mp4")["status"], "skipped_hidden")

    def test_bmp_and_other_photo_types_are_unaffected(self):
        self.put("x.bmp", BMP, mtime=MTIME)
        self.go(handle_movies="yes", use_filename_date="no")
        self.assertEqual(self.outfiles(), ["2021_05/x.bmp"])


class MoviesConfig(Base):
    def test_defaults(self):
        c = self.conf()
        self.assertEqual((c["handle_movies"], c["movies_folder"]), (False, "movies"))
        self.assertNotIn(".mp4", c["extensions"])

    def test_switching_on_adds_the_two_movie_types(self):
        c = self.conf(handle_movies="yes", extensions=".jpg")
        self.assertEqual(c["extensions"], {".jpg", ".mp4", ".mov"})

    def test_yes_no_error_names_the_option(self):
        with self.assertRaisesRegex(ValueError, r"\[organization\] handle_movies: expected yes or no"):
            self.conf(handle_movies="maybe")

    def test_folder_name_must_be_simple(self):
        for bad in ("", ".", "..", "a/b", "a\\b", "a:b", "x*"):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, "movies_folder must be a simple folder name"):
                self.conf(movies_folder=bad)

    def test_movie_types_cannot_be_added_through_extensions(self):
        with self.assertRaisesRegex(ValueError, r"supports only.*handle_movies = yes"):
            self.conf(extensions=".jpg,.mp4")
