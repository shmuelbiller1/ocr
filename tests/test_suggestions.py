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


if __name__ == "__main__":
    unittest.main()
