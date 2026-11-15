"""The question that is asked about a path that came from outside.

One module asks it, so that the tools, the worker and the engine all ask
it in the same way.  These tests are about the answer: a path inside one
of the folders that are allowed is given back resolved, and a path
outside them is refused and says why.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hebrew_workbench.safe_paths import (
    PathRefused,
    confine_path,
    default_bases,
    repository_base,
    temporary_base,
    working_base,
)


class TheFolderItselfIsAllowedTests(unittest.TestCase):
    """A folder that is allowed is not outside the folders that are allowed.

    The comparison was made on the prefix with a separator at the end,
    and the folder itself never has one.  So ``--corpus .``, ``--output
    .`` and the folder of the temporary files were each refused with a
    message that named the very folder it had just refused them for.
    """

    def test_the_folder_of_the_repository_is_allowed(self) -> None:
        self.assertEqual(
            confine_path(repository_base(), *default_bases()), Path(repository_base())
        )

    def test_the_folder_the_program_was_started_in_is_allowed(self) -> None:
        self.assertEqual(confine_path(".", *default_bases()), Path.cwd().resolve())

    def test_the_folder_of_the_temporary_files_is_allowed(self) -> None:
        self.assertEqual(
            confine_path(temporary_base(), *default_bases()), Path(temporary_base())
        )

    def test_a_folder_under_an_allowed_folder_is_allowed(self) -> None:
        self.assertEqual(
            confine_path("tools", *default_bases()), Path.cwd() / "tools"
        )

    def test_a_brother_folder_whose_name_begins_the_same_is_still_refused(self) -> None:
        """``/work`` is not inside ``/workspace``.

        The separator is what keeps the two apart, and it has to stay
        there now that the folder itself is allowed as well.
        """
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "workspace"
            base.mkdir()
            self.assertEqual(confine_path(base / "inside", base), base / "inside")
            with self.assertRaises(PathRefused):
                confine_path(Path(folder) / "work", base)

    def test_a_path_outside_is_refused_and_says_why(self) -> None:
        with self.assertRaises(PathRefused) as caught:
            confine_path(os.path.join(os.sep, "etc", "passwd"), *default_bases())
        message = str(caught.exception)
        self.assertIn("outside", message)
        # The refusal names the folders that may be used, so that a
        # person who was refused is told where to put the file.
        self.assertIn(repository_base(), message)


class TheFoldersOfTheProgramTests(unittest.TestCase):
    def test_the_three_folders_are_the_repository_the_work_and_the_temporary(self):
        bases = default_bases()
        self.assertEqual(len(bases), 3)
        self.assertEqual(bases[0], repository_base())
        self.assertEqual(bases[1], working_base())
        self.assertEqual(bases[2], temporary_base())


class TheFolderOfTheModelsTests(unittest.TestCase):
    """The program keeps its models in a folder of its own.

    It is outside the repository, and it is a folder the program chose,
    so a tool that is told to read a model from there may read it.  When
    it was not, every run that did not name a folder of models was
    refused - the stroke-width benchmark hands its children the folder of
    the models whether it was named or not.
    """

    def test_the_folder_of_the_models_is_allowed_for_a_model(self) -> None:
        from hebrew_workbench.engine.models import model_bases, models_directory

        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "models"
            home.mkdir()
            with patch.dict(
                os.environ, {"HEBREW_WORKBENCH_MODELS": str(home)}
            ):
                bases = model_bases()
                self.assertIn(str(home), bases)
                self.assertEqual(confine_path(home, *bases), home)
                self.assertEqual(
                    confine_path(home / "small.safetensors", *bases),
                    home / "small.safetensors",
                )
            self.assertNotIn(str(home), model_bases())
            self.assertTrue(str(models_directory()).endswith("models"))

    def test_a_refused_folder_of_models_is_said_the_way_the_installer_says_it(self):
        """A refused folder is not a traceback.

        The tool that downloads a model catches ``InstallError``, so a
        folder that is refused has to be one.
        """
        from hebrew_workbench.engine.models import MODEL_ARTIFACTS, InstallError

        artifact = MODEL_ARTIFACTS["kraken-ppocrv6-small"]
        outside = (
            Path(tempfile.gettempdir()).parent
            if os.name != "nt"
            else Path("C:\\")
        )
        if os.name == "nt":  # pragma: no cover - the build measures on Linux
            self.skipTest("every folder is inside the drive on Windows")
        from hebrew_workbench.engine.models import install_artifact

        with self.assertRaises(InstallError) as caught:
            install_artifact(artifact, destination=outside / "somewhere-else-entirely")
        self.assertIn("outside", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
