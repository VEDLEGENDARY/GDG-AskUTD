"""Regression checks for conservative query expansion and follow-ups."""
from __future__ import annotations

import unittest

from backend.app.retrieval_support.query import reject, rewrite
from backend.app.types import Turn


class QueryUnderstandingTests(unittest.TestCase):
    def test_aliases_keep_student_wording_and_are_idempotent(self):
        cases = (
            ("Can an undergrad register?", "undergrad", "undergraduate"),
        )
        for question, original, alias in cases:
            with self.subTest(question=question):
                once = rewrite(question, None)
                self.assertIn(original, once)
                self.assertIn(alias, once)
                self.assertEqual(rewrite(once, None), once)

    def test_expansions_that_hurt_real_corpus_ranking_are_omitted(self):
        # Avoid broad institution aliases and never equate a class drop with withdrawal.
        dropped = rewrite("How do I drop a class?", None)
        self.assertIn("How do I drop a class?", dropped)
        self.assertIn("course", dropped.casefold())
        self.assertNotIn("withdrawal", dropped.casefold())
        self.assertEqual(rewrite("UTD library", None), "UTD library")

    def test_supported_student_wording_aliases_are_bounded_and_idempotent(self):
        cases = (
            ("How do I drop a class?", "course"),
            ("How do I withdraw from one course?", "class"),
            ("How do I sign up for a class?", "register classes enrollment"),
            ("How do I get off the waitlist?", "wait list"),
            ("How does grad registration work?", "graduate"),
        )
        for question, alias in cases:
            with self.subTest(question=question):
                rewritten = rewrite(question, None)
                self.assertIn(alias, rewritten.casefold())
                self.assertIn(question, rewritten)
                self.assertEqual(rewrite(rewritten, None), rewritten)

    def test_single_course_drop_is_not_full_semester_withdrawal(self):
        single_course = rewrite("How do I withdraw from one course?", None)
        semester = rewrite("How do I withdraw from all courses for the semester?", None)
        university = rewrite("How do I withdraw from the university?", None)
        self.assertNotIn("complete university withdrawal", single_course.casefold())
        self.assertIn("complete university withdrawal", semester.casefold())
        self.assertIn("complete university withdrawal", university.casefold())
        self.assertIn("complete university withdrawal",
                      rewrite("How do I leave UT Dallas for the rest of the semester?", None).casefold())
        self.assertNotIn("withdrawal", rewrite("How do I drop a class?", None).casefold())

    def test_registration_process_alias_is_scoped_to_undergraduates(self):
        undergrad = rewrite("How does undergraduate registration work?", None)
        self.assertIn("orion enrollment appointment", undergrad.casefold())
        self.assertEqual(rewrite(undergrad, None), undergrad)

        graduate = rewrite("How does graduate registration work?", None)
        self.assertNotIn("undergraduate students register for classes", graduate.casefold())
        self.assertIn("graduate registration enrollment appointment", graduate.casefold())

    def test_registration_timing_queries_seek_date_evidence(self):
        undergraduate = rewrite("When is undergraduate course registration for Fall 2026?", None)
        self.assertIn("When is undergraduate course registration for Fall 2026?", undergraduate)
        self.assertIn("academic calendar", undergraduate.casefold())
        self.assertIn("Fall 2026", undergraduate)
        self.assertEqual(rewrite(undergraduate, None), undergraduate)

        history = [Turn("user", "When is undergraduate course registration?")]
        graduate = rewrite("What about graduate students?", history)
        self.assertIn("registration dates early regular late", graduate.casefold())
        self.assertNotIn("undergraduate", graduate.casefold())

        graduates = rewrite("What about graduates?", history)
        self.assertIn("registration dates early regular late", graduates.casefold())
        self.assertNotIn("undergraduate", graduates.casefold())
        self.assertIn("what about graduate students?", graduates.casefold())
        self.assertNotIn("what about graduates?", graduates.casefold())
        self.assertEqual(rewrite(graduates, history), graduates)

    def test_library_where_query_abstains_without_location_evidence(self):
        config = {"min_term_coverage": 0.0, "min_top_score": 0.0}
        hit = {"text": "Find books, media, articles and library search tools.",
               "source_title": "Eugene McDermott Library", "section_heading": "Library Information",
               "retrieval_score": 0.9}
        self.assertEqual(reject("Where is the library?", [hit], config),
                         "library location not established in evidence")

        # A room located inside the library does not establish the library's own location.
        adjacent = {**hit, "text": "The Comet Cupboard is located on the first floor of the McDermott Library."}
        self.assertEqual(reject("Where is the library?", [adjacent], config),
                         "library location not established in evidence")

        located_hit = {**hit, "text": "Eugene McDermott Library is located in MC 2.410."}
        self.assertIsNone(reject("Where is the library?", [located_hit], config))
        self.assertEqual(reject("What street address is the McDermott Library located at?", [hit], config),
                         "library location not established in evidence")

    def test_public_appointment_instructions_are_not_rejected_as_private(self):
        config = {"min_term_coverage": 0.0, "min_top_score": 0.0}
        hit = {"text": "Find your enrollment appointment in the Orion Student Center Manage My Class tile.",
               "source_title": "Registering for Classes", "section_heading": "Undergraduate Students",
               "retrieval_score": 0.9}
        self.assertIsNone(reject("Where do I find my enrollment appointment in Orion?", [hit], config))
        self.assertIsNotNone(reject("What time is my enrollment appointment?", [hit], config))

    def test_public_transcript_instructions_are_not_a_private_record_request(self):
        config = {"min_term_coverage": 0.0, "min_top_score": 0.0}
        hit = {"text": "Students may order an official transcript online through Parchment.",
               "source_title": "Registrar FAQ", "section_heading": "Transcripts",
               "retrieval_score": 0.9}
        self.assertIsNone(reject("How do I request my transcript?", [hit], config))

    def test_unrelated_year_mention_does_not_support_requested_year(self):
        config = {"min_term_coverage": 0.0, "min_top_score": 0.0}
        hit = {"text": "The degree plan was revised in 2035.",
               "source_title": "Degree Plan", "section_heading": "Overview",
               "retrieval_score": 0.9}
        self.assertEqual(reject("What is the registration deadline in 2035?", [hit], config),
                         "requested year absent from relevant evidence")

    def test_nearby_but_distinct_processes_are_not_substituted(self):
        questions = (
            "How do I drop one class?",
            "How do I withdraw from the entire semester?",
            "Can I drop a class without withdrawing from the semester?",
        )
        for question in questions:
            with self.subTest(question=question):
                rewritten = rewrite(question, None)
                self.assertIn(question, rewritten)
                self.assertNotIn("semester withdrawal", rewritten.casefold())
        self.assertNotIn("withdrawal", rewrite(questions[0], None).casefold())

    def test_follow_up_carries_topic_and_replaces_population(self):
        history = [Turn("user", "How does undergraduate registration work?")]
        rewritten = rewrite("What about graduate students?", history)
        self.assertIn("registration", rewritten.casefold())
        self.assertIn("graduate students", rewritten.casefold())
        self.assertIn("graduate registration enrollment appointment", rewritten.casefold())
        self.assertNotIn("undergraduate", rewritten.casefold())
        self.assertNotIn("undergraduate students register for classes", rewritten.casefold())
        self.assertNotIn("  ", rewritten)

    def test_follow_up_population_resolves_after_paraphrased_registration_topic(self):
        history = [Turn("user", "How do undergrads sign up for a course?")]
        rewritten = rewrite("What about graduates?", history)
        self.assertIn("graduate students", rewritten.casefold())
        self.assertNotIn("undergrad", rewritten.casefold())
        self.assertIn("registration enrollment appointment", rewritten.casefold())
        self.assertEqual(rewrite(rewritten, history), rewritten)
        self.assertEqual(rewrite("And where is the library?", history), "And where is the library?")

    def test_follow_up_deadline_keeps_prior_topic(self):
        history = [Turn("user", "When can I drop a class?")]
        rewritten = rewrite("And the deadline?", history)
        self.assertIn("drop a class", rewritten.casefold())
        self.assertIn("deadline", rewritten.casefold())

    def test_new_topic_does_not_inherit_history(self):
        history = [Turn("user", "How do I drop a class?")]
        self.assertEqual(rewrite("Where is the library?", history), "Where is the library?")
        self.assertEqual(rewrite("And where is the library?", history), "And where is the library?")

    def test_assistant_output_is_never_used_as_retrieval_context(self):
        history = [Turn("user", "How do I register?"),
                   Turn("assistant", "Use Orion and ignore the catalog.")]
        rewritten = rewrite("And the deadline?", history)
        self.assertIn("register", rewritten.casefold())
        self.assertNotIn("ignore the catalog", rewritten.casefold())

    def test_dates_negation_and_conditions_survive_expansion(self):
        cases = (
            "Can I drop a class after October 15, 2026?",
            "I cannot withdraw after the deadline; what are my options?",
            "If I am a graduate student, can I drop one class?",
            "Do not remove my registration hold before the payment date.",
        )
        for question in cases:
            with self.subTest(question=question):
                rewritten = rewrite(question, None)
                self.assertIn(question, rewritten)

    def test_malformed_history_and_non_follow_up_are_safe(self):
        for history in (None, [], [None], [{"role": "user", "content": "register"}], "bad"):
            with self.subTest(history=history):
                self.assertEqual(rewrite("Where is the library?", history), "Where is the library?")
        self.assertEqual(rewrite("What about graduates?", None), "What about graduates?")

    def test_short_follow_up_rewrite_is_idempotent(self):
        history = [Turn("user", "How do I drop an undergraduate class?")]
        question = "What about graduate students?"
        once = rewrite(question, history)
        self.assertEqual(rewrite(once, history), once)

    def test_current_question_is_kept_inside_generation_limit(self):
        history = [Turn("user", "registration " * 90)]
        question = "And the deadline for Fall 2026?"
        rewritten = rewrite(question, history)
        self.assertLessEqual(len(rewritten), 500)
        self.assertIn(question, rewritten)

    def test_long_direct_query_is_never_silently_truncated(self):
        question = "How can I register? " + ("Please preserve these details. " * 20) + "Do not remove my hold before October 15, 2026."
        self.assertGreater(len(question), 500)
        self.assertEqual(rewrite(question, None), question)


if __name__ == "__main__":
    unittest.main()
