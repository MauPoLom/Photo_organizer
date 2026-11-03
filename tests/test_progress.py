"""The progress line: a one-line counter on stderr, shown only on a terminal."""
import io
import unittest

import photo_organizer as org
from tests.helpers import Base, exif_jpeg


class FakeTerminal(io.StringIO):
    def __init__(self, tty=True):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


class BrokenTerminal(FakeTerminal):
    def write(self, text):
        raise OSError("console gone")


class ProgressClass(unittest.TestCase):
    def test_counts_and_percentages_end_at_100(self):
        term = FakeTerminal()
        p = org.Progress(3, term)
        for _ in range(3):
            p.step()
        p.finish()
        text = term.getvalue()
        self.assertIn("3/3  100%", text)
        self.assertTrue(text.endswith("\r"))  # the line is erased again

    def test_silent_when_not_a_terminal(self):
        term = FakeTerminal(tty=False)
        p = org.Progress(2, term)
        p.step(); p.step(); p.finish()
        self.assertEqual(term.getvalue(), "")

    def test_silent_with_nothing_to_do(self):
        term = FakeTerminal()
        p = org.Progress(0, term)
        p.finish()
        self.assertEqual(term.getvalue(), "")

    def test_broken_console_never_raises(self):
        p = org.Progress(2, BrokenTerminal())
        p.step(); p.step(); p.finish()


class ProgressInRun(Base):
    def test_not_shown_when_output_is_redirected(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go()
        self.assertNotIn("\r", self.stderr)
        self.assertNotIn("1/1", self.stderr)

    def test_counts_only_files_that_are_processed(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("b.jpg", exif_jpeg("2019:07:05 15:30:12"))
        self.put("notes.txt", b"x")
        c = self.conf()
        term = FakeTerminal()
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(term):
            org.run(c)
        self.assertIn("2/2  100%", term.getvalue())
        self.assertNotIn("3/3", term.getvalue())


if __name__ == "__main__":
    unittest.main()
