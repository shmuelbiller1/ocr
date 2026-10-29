"""Keep the published download guide consistent with the executable version."""
from pathlib import Path
import unittest

from hebrew_workbench import __version__


class ReleaseVersionTests(unittest.TestCase):
    def test_release_notes_and_download_names_match_app_version(self):
        notes = (Path(__file__).resolve().parents[1] / 'docs/RELEASE_NOTES.md').read_text(encoding='utf-8')
        self.assertIn(f'v{__version__}', notes.splitlines()[0])
        for suffix in ('one-click.exe', 'all-models-noncommercial-one-click.exe', 'win64.zip'):
            self.assertIn(f'HebrewNotesWorkbench-{__version__}-{suffix}', notes)
        self.assertIn('CC-BY-NC-SA-4.0', notes)
        self.assertIn('still unverified', notes)


if __name__ == '__main__':
    unittest.main()
