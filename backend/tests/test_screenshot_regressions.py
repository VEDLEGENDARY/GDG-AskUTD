"""Replay representative failures from the November 10 screenshot sessions."""
from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from backend.app import generation, retrieval
from backend.app.llm.extractive import ExtractiveLLM
from backend.app.retrieval_support.query import rewrite
from backend.app.types import Turn

# Each row checks the answer text, the evidence, and likely wrong alternatives.
CASES = (
    ("AP Calc BC",
     "How much course credit can I get from my AP Calc BC AP exam? I scored a 4 and am an engineering major.",
     None, ("8 semester credit hours", "MATH 2414"), ("art history",)),
    ("two AP scores",
     "I got a 4 on AP Calculus BC and a 5 on AP Physics C: Mechanics. What credit would UT Dallas give me for those?",
     None, ("8 semester credit hours", "4 semester credit hours", "PHYS 2325", "PHYS 2125"), ("magnetism",)),
    ("tuition estimate",
     "What is my tuition estimate for next semester? I am taking 5 3 credit hour courses which is 15 credit hours in total.",
     None, ("tuition estimate", "Bursar Account"), ("rebate", "pay administration")),
    ("tuition payment", "How do I pay my tuition?", None, ("EZPay", "Make a Payment"), ("hazardous duty pay",)),
    ("fall break", "When will fall break start for 2026 fall semester?", None, ("Nov. 23",), ("schedule planner",)),
    ("degree conferral", "What day is graduation in the spring 2027 semester?", None,
     ("degree conferral", "May 22, 2027"), ("ceremony is",)),
    ("official transcript", "How can I request my transcript?", None, ("Orion", "Order Official Transcript"), ()),
    ("waitlist", "How do I waitlist for a class?", None, ("waitlist", "Orion"), ("class number for registration",)),
    ("registration hold",
     "I have a registration hold, but I'm not sure which office placed it. How can I find out what it means, resolve it, and tell whether it affects my ability to enroll?",
     None, ("Orion", "Tasks tile", "department"), ()),
    ("three-course repeat",
     "How does the Texas three-course repeat rule work, and could I end up paying higher tuition for repeating a class?",
     None, ("third time", "penalty fee"), ()),
    ("complete withdrawal and aid",
     "If I withdraw from all my classes in the middle of the semester, what happens to my financial aid and could I owe money back?",
     None, ("60 percent", "Title IV", "must be returned"), ()),
    ("SAP",
     "How is Satisfactory Academic Progress measured for financial aid, and what can I do if I fail to meet it?",
     None, ("cumulative GPA", "attempted", "appeal"), ()),
    ("FAFSA verification",
     "What forms might I need to submit if the Office of Financial Aid selects my FAFSA for verification?",
     None, ("verification worksheets", "To Do List"), ()),
    ("accommodations",
     "I'm a student with a disability whose accommodation isn't being followed in one class. What process should I use to address it, and what documentation or contacts might be relevant?",
     None, ("AccessAbility Resource Center", "grievance"), ()),
    ("off-campus employment",
     "I'm an international undergraduate student who wants to work off campus during the semester. What rules should I know?",
     None, ("work authorization", "off-campus employment"), ()),
    ("full-term withdrawal", "When does the withdrawal period end in Fall 2026?", None, ("Nov. 9",), ("Nov. 25", "Sept. 28")),
    ("first session", "what if the class is only in the first 8-week session?",
     "When does the withdrawal period end in Fall 2026?", ("Sept. 28",), ("Nov. 9", "Nov. 25")),
    ("second session", "and for the second 8-week session?",
     "When does the withdrawal period end for the first 8-week session in Fall 2026?",
     ("Nov. 25",), ("Nov. 9", "Sept. 28")),
    ("undergraduate GPA", "What GPA does an undergrad need to stay in good academic standing?",
     None, ("2.000",), ("3.000", "assured admission")),
    ("graduate GPA", "is it the same for grad students or do they need higher?",
     "What GPA does an undergrad need to stay in good academic standing?", ("3.00",), ("2.000", "assured admission")),
    ("catalog comparison",
     "I'm on the 2026-27 CS degree plan and my friend is on 2025-26. How many CS technical elective and free elective hours does each of us need?",
     None, ("12 technical elective", "10 free elective", "9 technical elective", "13 free elective"), ("2021-2022",)),
    ("auditing CS", "Can I audit CS 3345 in the spring? I just want to sit in on the lectures.",
     None, ("Computer Science", "cannot be audited"), ()),
    ("complete withdrawal and six-drop limit",
     "I'm thinking about withdrawing from all four of my classes this semester. Would that use up four of my six allowed withdrawals?",
     None, ("excludes complete withdrawal", "all classes"), ("biology",)),
    ("CS master's", "How many credit hours do you need for the master's in computer science at UT Dallas?",
     None, ("33 semester credit hours",), ("fast track",)),
    ("gap year",
     "what if I take a gap year",
     "I am an incoming freshman in computer science I have all my pre requisites build me a schedule for each year",
     ("defer undergraduate admission", "two full semesters"), ("dissertation",)),
    ("tutoring versus SI",
     "What is the difference between peer tutoring and Supplemental Instruction at UT Dallas, and which is better for a hard STEM course?",
     None, ("Peer Tutoring", "Supplemental Instruction", "study sessions"), ()),
    ("semester course load", "How many credit hours am i allowed per semester as an undergraduate student",
     None, ("more than 19", "up to 21"), ("120 semester credit hours",)),
)

UNSUPPORTED = (
    ("How many computer science students are at UTD?", None),
    ("From those, how many are taking physics right now?", "How many computer science students are at UTD?"),
    ("What is the four-year graduation rate for computer science majors at UTD?", None),
    ("I am currently a CS student 60 credit hours within my course can I switch to Finance and graduate on time?", None),
    ("How many credits must I take next semester to graduate on time?", "I am taking CS 3377 and CS 3345."),
    ("When is the Spring 2027 commencement ceremony?", None),
)


class ScreenshotRegressionTests(unittest.TestCase):
    def answer(self, question, previous=None):
        history = [Turn("user", previous)] if previous else None
        result = retrieval.retrieve(question, history=history)
        answer = generation.generate_answer(rewrite(question, history), result.passages, history)
        return result, answer

    def test_replays_supported_screenshot_requests(self):
        with patch.object(generation, "_override", ExtractiveLLM()):
            for name, question, previous, required, forbidden in CASES:
                with self.subTest(name=name):
                    result, answer = self.answer(question, previous)
                    self.assertFalse(answer.abstained, result.reason)
                    self.assertTrue(answer.citations)
                    self.assertLessEqual(len(result.passages), 5)
                    for fact in required:
                        self.assertIn(fact.casefold(), answer.text.casefold())
                    for distraction in forbidden:
                        self.assertNotIn(distraction.casefold(), answer.text.casefold())
                    ids = {p.chunk_id for p in result.passages}
                    self.assertTrue(all(c.chunk_id in ids for c in answer.citations))
                    self.assertEqual({int(n) for n in re.findall(r"\[(\d+)\]", answer.text)},
                                     {c.n for c in answer.citations})

    def test_unsupported_requests_have_no_citations(self):
        with patch.object(generation, "_override", ExtractiveLLM()):
            for question, previous in UNSUPPORTED:
                with self.subTest(question=question):
                    _, answer = self.answer(question, previous)
                    self.assertTrue(answer.abstained, answer.text)
                    self.assertEqual(answer.citations, [])
