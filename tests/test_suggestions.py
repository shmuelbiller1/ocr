"""Tests for the modules that propose corrections."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hebrew_workbench.suggestions import (
    KIND_GRAMMAR,
    KIND_SPELLING,
    KIND_STYLE,
    GrammarModule,
    SpellingModule,
    StyleModule,
    Suggestion,
    SuggestionRegistry,
    SuggestionSession,
)


class SpellingTests(unittest.TestCase):
    def make_module(self, words: str) -> SpellingModule:
        folder = tempfile.mkdtemp()
        path = Path(folder) / "words.txt"
        path.write_text(words, encoding="utf-8")
        module = SpellingModule()
        module.set_dictionary(path)
        return module

    def test_a_word_that_is_not_in_the_list_is_proposed(self) -> None:
        module = self.make_module("שלום\nבית\n")
        proposals = module.check("ברוך בית שלום")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].original, "ברוך")
        self.assertEqual(proposals[0].module, KIND_SPELLING)

    def test_a_word_that_is_in_the_list_is_not_proposed(self) -> None:
        module = self.make_module("שלום\nבית\n")
        self.assertEqual(module.check("שלום בית"), [])

    def test_a_short_word_is_not_proposed(self) -> None:
        module = self.make_module("שלום\n")
        self.assertEqual(module.check("זה בית"), [])

    def test_the_alternatives_of_a_word_are_kept(self) -> None:
        module = self.make_module("שלום/תחתונות/שלום\n")
        proposals = module.check("שלום")
        self.assertEqual(proposals, [])

    def test_the_other_spelling_of_a_word_is_proposed_with_a_replacement(self) -> None:
        """The spellings of a word that are separated by a slash are known."""
        module = self.make_module("שלום/תחתונות\n")
        proposals = module.check("תחתונות")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].original, "תחתונות")
        self.assertEqual(proposals[0].replacement, "שלום")

    def test_every_spelling_of_a_word_can_be_proposed(self) -> None:
        module = self.make_module("שלום/תחתונות/תחתוניות\n")
        proposals = module.check("תחתונות")
        self.assertEqual(
            [item.replacement for item in proposals], ["שלום", "תחתוניות"]
        )

    def test_the_preferred_spelling_of_a_word_is_not_proposed(self) -> None:
        module = self.make_module("שלום/תחתונות\n")
        self.assertEqual(module.check("שלום"), [])

    def test_a_module_without_a_list_cannot_work(self) -> None:
        module = SpellingModule()
        self.assertFalse(module.available())
        self.assertIn("מילון", module.unavailable_reason())
        self.assertEqual(module.check("שלום"), [])

    def test_the_licence_of_the_list_is_found_next_to_it(self) -> None:
        folder = Path(tempfile.mkdtemp())
        (folder / "words.txt").write_text("שלום\n", encoding="utf-8")
        (folder / "LICENSE").write_text("the licence of the list", encoding="utf-8")
        module = SpellingModule()
        module.set_dictionary(folder / "words.txt")
        self.assertIn("licence", module.licence_text())


class GrammarTests(unittest.TestCase):
    def test_a_space_before_a_comma_is_proposed(self) -> None:
        proposals = GrammarModule().check("שלום , עולם")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].replacement, ",")

    def test_a_missing_space_after_a_comma_is_proposed(self) -> None:
        proposals = GrammarModule().check("שלום,עולם")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].replacement, ", ")

    def test_two_spaces_are_proposed_to_be_one(self) -> None:
        proposals = GrammarModule().check("שלום  עולם")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].replacement, " ")

    def test_a_correct_text_has_no_proposals(self) -> None:
        self.assertEqual(GrammarModule().check("שלום, עולם"), [])

    def test_an_opening_quote_keeps_the_space_before_it(self) -> None:
        """The space before a quote that opens a quotation is correct."""
        self.assertEqual(GrammarModule().check('שלום "עולם"'), [])

    def test_a_space_before_a_closing_quote_is_proposed(self) -> None:
        proposals = GrammarModule().check('אמר "שלום עולם " ולא')
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].replacement, '"')


class StyleTests(unittest.TestCase):
    def test_the_style_module_is_not_implemented_and_says_so(self) -> None:
        module = StyleModule()
        self.assertFalse(module.available())
        self.assertIn("לא", module.unavailable_reason())
        self.assertEqual(module.check("שלום"), [])

    def test_the_rules_that_will_be_here_are_written_down(self) -> None:
        from hebrew_workbench.suggestions import PLANNED_RULES

        self.assertTrue(PLANNED_RULES)
        for rule in PLANNED_RULES:
            self.assertIn("source", rule)
            self.assertIn("state", rule)


class RegistryTests(unittest.TestCase):
    def test_every_kind_is_a_module_of_its_own(self) -> None:
        registry = SuggestionRegistry()
        self.assertIsNotNone(registry.module(KIND_SPELLING))
        self.assertIsNotNone(registry.module(KIND_GRAMMAR))
        self.assertIsNotNone(registry.module(KIND_STYLE))
        self.assertIsNot(registry.module(KIND_SPELLING), registry.module(KIND_GRAMMAR))

    def test_the_style_module_is_off_when_the_program_starts(self) -> None:
        registry = SuggestionRegistry()
        self.assertFalse(registry.is_enabled(KIND_STYLE))
        self.assertTrue(registry.is_enabled(KIND_GRAMMAR))

    def test_a_module_that_is_off_does_not_propose_anything(self) -> None:
        registry = SuggestionRegistry()
        registry.set_enabled(KIND_GRAMMAR, False)
        self.assertEqual(registry.check("שלום ,עולם"), [])

    def test_a_module_that_breaks_does_not_stop_the_others(self) -> None:
        class Broken(StyleModule):
            id = "broken"
            kind = "broken"

            def check(self, text):
                raise RuntimeError("the module is broken")

        registry = SuggestionRegistry()
        registry.modules.append(Broken())
        proposals = registry.check("שלום , עולם")
        self.assertEqual(len(proposals), 1)


class SessionTests(unittest.TestCase):
    def make_session(self) -> SuggestionSession:
        session = SuggestionSession("שלום ,עולם")
        from hebrew_workbench.suggestions import Suggestion

        session.set_suggestions(
            [
                Suggestion(
                    module=KIND_GRAMMAR,
                    original=" ,",
                    replacement=",",
                    message="אין רווח לפני הפסיק",
                    start=4,
                    end=6,
                )
            ],
            "שלום ,עולם",
        )
        return session

    def test_accepting_a_proposal_changes_the_text(self) -> None:
        session = self.make_session()
        outcome = session.accept(session.pending()[0])
        self.assertIsNotNone(outcome)
        text, position = outcome
        self.assertEqual(text, "שלום,עולם")
        self.assertEqual(position, 4)
        self.assertEqual(session.pending(), [])

    def test_a_refused_proposal_is_not_applied(self) -> None:
        session = self.make_session()
        session.refuse(session.pending()[0])
        self.assertEqual(session.current_text, "שלום ,עולם")
        self.assertEqual(session.pending(), [])

    def test_the_changes_can_be_undone(self) -> None:
        session = self.make_session()
        session.accept(session.pending()[0])
        text = session.undo_all()
        self.assertEqual(text, "שלום ,עולם")
        self.assertEqual(session.accepted, [])

    def test_the_log_of_the_changes_can_be_written_and_read(self) -> None:
        session = self.make_session()
        session.accept(session.pending()[0])
        log = session.change_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["original"], " ,")
        self.assertEqual(log[0]["replacement"], ",")

    def test_a_proposal_that_does_not_fit_the_text_is_not_applied(self) -> None:
        session = self.make_session()
        session.current_text = "טקסט אחר"
        self.assertIsNone(session.accept(session.pending()[0]))

    def test_the_places_of_a_new_round_are_not_moved_by_earlier_corrections(
        self,
    ) -> None:
        """A new round of proposals has the places of the text as it is.

        The corrections of the earlier round are kept, so that they can
        still be taken back, but they must not move the places of the
        new proposals.
        """
        from hebrew_workbench.suggestions import Suggestion

        session = SuggestionSession("שלום ,עולם")
        session.set_suggestions(
            [
                Suggestion(
                    module=KIND_GRAMMAR,
                    original=" ,",
                    replacement=",",
                    message="אין רווח לפני הפסיק",
                    start=4,
                    end=6,
                )
            ],
            "שלום ,עולם",
        )
        session.accept(session.pending()[0])
        self.assertEqual(session.current_text, "שלום,עולם")

        # A new round, on the text as it is now.
        session.set_suggestions(
            [
                Suggestion(
                    module=KIND_GRAMMAR,
                    original="עולם",
                    replacement="עולם!",
                    message="סימן קריאה",
                    start=5,
                    end=9,
                )
            ],
            "שלום,עולם",
        )
        outcome = session.accept(session.pending()[0])
        self.assertIsNotNone(outcome)
        text, position = outcome
        self.assertEqual(text, "שלום,עולם!")
        self.assertEqual(position, 5)

    def test_the_undo_keeps_what_the_user_wrote_after_the_correction(self) -> None:
        session = self.make_session()
        session.accept(session.pending()[0])
        # The user wrote something after the correction was made.
        text = session.undo_all("שלום,עולם ועוד מילה")
        self.assertEqual(text, "שלום ,עולם ועוד מילה")

    def test_the_proposals_are_taken_away_when_the_corrections_are_undone(self) -> None:
        """A proposal of the old places is of no use after the undo."""
        session = self.make_session()
        session.accept(session.pending()[0])
        session.set_suggestions(
            [
                Suggestion(
                    module=KIND_GRAMMAR,
                    original="עולם!",
                    replacement="עולם.",
                    message="",
                    start=7,
                    end=12,
                )
            ],
            session.current_text,
        )
        self.assertEqual(len(session.pending()), 1)
        session.undo_all()
        # The places of the proposals belonged to the text before the
        # undo, and they are of no use now.
        self.assertEqual(session.pending(), [])

    def test_the_corrections_are_taken_back_whatever_the_order_of_acceptance(
        self,
    ) -> None:
        """The place of a correction is kept when another one is accepted."""
        session = SuggestionSession("a,b,c")
        first = Suggestion(
            module=KIND_GRAMMAR,
            original=",",
            replacement=", ",
            message="",
            start=1,
            end=2,
        )
        second = Suggestion(
            module=KIND_GRAMMAR,
            original=",",
            replacement=", ",
            message="",
            start=3,
            end=4,
        )
        session.set_suggestions([first, second], "a,b,c")

        # The second correction is accepted first, and then the first
        # one, so that the place of the first one is not the place it
        # has in the text any more.
        session.accept(second)
        session.accept(first)
        self.assertEqual(session.current_text, "a, b, c")

        text = session.undo_all()
        self.assertEqual(text, "a,b,c")
        self.assertEqual(session.last_undo_skipped, [])

    def test_the_corrections_that_depend_on_each_other_are_taken_back(self) -> None:
        """A correction that was made on the text of another one."""
        session = SuggestionSession("a ,b")
        first = Suggestion(
            module=KIND_GRAMMAR,
            original=" ,",
            replacement=",",
            message="",
            start=1,
            end=3,
        )
        session.set_suggestions([first], "a ,b")
        session.accept(first)
        self.assertEqual(session.current_text, "a,b")

        # The suggestions are checked again, and the space after the
        # comma is added.
        second = Suggestion(
            module=KIND_GRAMMAR,
            original=",",
            replacement=", ",
            message="",
            start=1,
            end=2,
        )
        session.set_suggestions([second], session.current_text)
        session.accept(second)
        self.assertEqual(session.current_text, "a, b")

        text = session.undo_all()
        self.assertEqual(text, "a ,b")
        self.assertEqual(session.last_undo_skipped, [])

    def test_the_undo_does_not_change_a_text_that_was_not_corrected(self) -> None:
        """A correction is not taken back in a place that was not corrected."""
        session = SuggestionSession("שלום , עולם, סוף")
        from hebrew_workbench.suggestions import Suggestion

        session.set_suggestions(
            [
                Suggestion(
                    module=KIND_GRAMMAR,
                    original=" ,",
                    replacement=",",
                    message="אין רווח לפני הפסיק",
                    start=4,
                    end=6,
                )
            ],
            "שלום , עולם, סוף",
        )
        session.accept(session.pending()[0])
        self.assertEqual(session.current_text, "שלום, עולם, סוף")
        # The user deleted the first clause, so the correction is not
        # in the text any more.  The comma that is left was never
        # corrected, and it must not be changed.
        text = session.undo_all("עולם, סוף")
        self.assertEqual(text, "עולם, סוף")
        self.assertEqual(len(session.last_undo_skipped), 1)

    def test_the_undo_finds_the_correction_after_a_change_before_it(self) -> None:
        """The place of a correction is found even when the text moved."""
        session = SuggestionSession("שלום ,עולם")
        from hebrew_workbench.suggestions import Suggestion

        session.set_suggestions(
            [
                Suggestion(
                    module=KIND_GRAMMAR,
                    original=" ,",
                    replacement=",",
                    message="אין רווח לפני הפסיק",
                    start=4,
                    end=6,
                )
            ],
            "שלום ,עולם",
        )
        session.accept(session.pending()[0])
        # The user wrote something before the correction.
        text = session.undo_all("טקסט שנכתב לפני שלום,עולם")
        self.assertEqual(text, "טקסט שנכתב לפני שלום ,עולם")
        self.assertEqual(session.last_undo_skipped, [])
        self.assertEqual(session.accepted, [])

    def test_the_changes_of_a_saved_project_are_taken_back_into_the_session(
        self,
    ) -> None:
        session = self.make_session()
        session.accept(session.pending()[0])
        log = session.change_log()

        restored = SuggestionSession("שלום,עולם")
        restored.restore_accepted(log)
        self.assertEqual(len(restored.accepted), 1)
        self.assertTrue(restored.undo_available)
        self.assertEqual(restored.undo_all(), "שלום ,עולם")


if __name__ == "__main__":
    unittest.main()
