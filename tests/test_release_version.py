"""Keep the published download guide consistent with the executable version."""
from pathlib import Path
import unittest

from hebrew_workbench import __version__
from tools.build_one_click import NOTICE_NAME, MANIFEST_NAME, MISHKEFET_NOTICE_NAME


class ReleaseVersionTests(unittest.TestCase):
    def test_release_notes_and_download_names_match_app_version(self):
        notes = (Path(__file__).resolve().parents[1] / 'docs/RELEASE_NOTES.md').read_text(encoding='utf-8')
        self.assertIn(f'v{__version__}', notes.splitlines()[0])
        for suffix in ('one-click.exe', 'all-models-noncommercial-one-click.exe', 'win64.zip'):
            self.assertIn(f'HebrewNotesWorkbench-{__version__}-{suffix}', notes)
        for name in (NOTICE_NAME, MANIFEST_NAME, MISHKEFET_NOTICE_NAME):
            self.assertIn(name.removeprefix('HebrewNotesWorkbench/'), notes)
        self.assertIn('בגרסת ZIP', notes)
        self.assertIn('כלולים בגרסת All Models בלבד', notes)
        self.assertIn('CC-BY-NC-SA-4.0', notes)
        self.assertIn('still unverified', notes)

    def test_current_installation_guides_describe_all_models_edition(self):
        root = Path(__file__).resolve().parents[1]
        for filename in ('README.md', 'docs/ASSISTED_DECODING.md', 'docs/ENGINES.md',
                         'docs/OCR_ACCURACY.md', 'docs/THIRD_PARTY.md', 'docs/AGENT_BUILD_PLAN.md'):
            with self.subTest(filename=filename):
                self.assertIn('All Models', (root / filename).read_text(encoding='utf-8'))
        assisted = (root / 'docs/ASSISTED_DECODING.md').read_text(encoding='utf-8')
        self.assertNotIn('These files are not bundled', assisted)
        self.assertNotIn('These data files are not redistributed by this project', assisted)


if __name__ == '__main__':
    unittest.main()
