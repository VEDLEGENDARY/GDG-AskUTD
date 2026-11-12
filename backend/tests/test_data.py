"""Offline checks for the document registry, corpus cleanup, benchmark and e2e script."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.setdefault("LLM_PROVIDER", "extractive")

from audit_corpus import audit, letter_spaced, navigation_like  # noqa: E402
from backend.app.types import Answer, Citation, Passage  # noqa: E402
from build_registry import (  # noqa: E402
    build_registry,
    filename_to_url,
    load_chunk_docs,
    match_documents,
)
from eval_e2e import citation_report, extractive_answer, main as e2e_main  # noqa: E402
from fix_chunks import clean_doc, main as fix_main, strip_furniture  # noqa: E402

DATA = ROOT / "backend" / "data"
REGISTRY = DATA / "documents.json"
SOURCES = DATA / "doc_sources.json"
QUESTIONS = ROOT / "evaluate" / "questions.json"


def chunk(chunk_id: str, text: str, heading: str = "Overview", title: str = "Title") -> dict:
    """Minimal chunk record for fixtures."""
    return {
        "chunk_id": chunk_id,
        "doc_id": chunk_id.split("_")[0],
        "text": text,
        "source_title": title,
        "section_heading": heading,
        "n_sentences": 1,
        "token_count": 1,
    }


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        cls.chunk_docs = load_chunk_docs(DATA / "chunks")

    def test_every_chunk_doc_has_one_entry(self) -> None:
        ids = [entry["doc_id"] for entry in self.registry]
        self.assertEqual(len(ids), len(set(ids)), "doc ids must be unique")
        self.assertEqual(set(ids), set(self.chunk_docs))

    def test_entry_fields_and_counts(self) -> None:
        for entry in self.registry:
            with self.subTest(doc=entry["doc_id"]):
                self.assertEqual(set(entry), {"doc_id", "title", "source_url", "pdf", "chunks"})
                self.assertTrue(entry["title"].strip())
                self.assertEqual(entry["chunks"], len(self.chunk_docs[entry["doc_id"]]))

    def test_urls_are_https_or_null(self) -> None:
        web_sources = json.loads((DATA / "web_sources.json").read_text(encoding="utf-8"))
        for entry in self.registry:
            url = entry["source_url"]
            with self.subTest(doc=entry["doc_id"]):
                self.assertTrue(url is None or url.startswith("https://"), url)
                if entry["pdf"] is None:
                    self.assertEqual(url, web_sources.get(entry["doc_id"], {}).get("url"))
                    if url:
                        self.assertRegex(url, r"^https://(?:[a-z0-9-]+\.)*utdallas\.edu/")

    def test_pdfs_exist_and_sources_are_respected(self) -> None:
        sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        for entry in self.registry:
            if entry["pdf"]:
                self.assertTrue((DATA / "raw_pdfs" / entry["pdf"]).is_file(), entry["pdf"])
            if entry["doc_id"] in sources:
                self.assertEqual(entry["pdf"], sources[entry["doc_id"]])

    def test_chunk_ids_are_unique_and_well_formed(self) -> None:
        seen: set[str] = set()
        for doc_id, records in self.chunk_docs.items():
            for record in records:
                self.assertRegex(record["chunk_id"], rf"^{doc_id}_p\d+_c\d+$")
                self.assertNotIn(record["chunk_id"], seen)
                seen.add(record["chunk_id"])


class UrlRuleTests(unittest.TestCase):
    def test_known_patterns(self) -> None:
        cases = {
            "https___www-utdallas-edu_academics_calendar_.pdf": "https://www.utdallas.edu/academics/calendar/",
            "https___registrar-utdallas-edu_legislative-policies_6-withdrawal_.pdf":
                "https://registrar.utdallas.edu/legislative-policies/6-withdrawal/",
            "https___catalog-utdallas-edu_.pdf": "https://catalog.utdallas.edu/",
            "https___policy-utdallas-edu_utdbp3102.pdf": "https://policy.utdallas.edu/utdbp3102",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(filename_to_url(name).url, expected)
                self.assertEqual(filename_to_url(name).concerns, ())

    def test_low_confidence_cases_are_flagged(self) -> None:
        doubled = filename_to_url(
            "https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_PreReqMnr-CS_Minor-pdf.pdf"
        )
        self.assertEqual(doubled.url, "https://engineering.utdallas.edu/files/2023/07/PreReqMnr-CS_Minor.pdf")
        self.assertEqual(len(doubled.concerns), 3)
        self.assertTrue(filename_to_url("https___bursar-utdallas-edu_headingContact.pdf").concerns)

    def test_unknown_hosts_and_titles_give_null(self) -> None:
        self.assertIsNone(filename_to_url("https___bpb-us-e2-wpmucdn-com_sites-utdallas-edu_x.pdf").url)
        self.assertIsNone(filename_to_url("Dine On Campus.pdf").url)


class MatcherTests(unittest.TestCase):
    TEXT_A = " ".join(f"alpha{i} policy statement about registration rule {i}" for i in range(40))
    TEXT_B = " ".join(f"beta{i} housing guide residence hall item {i}" for i in range(40))

    def test_clear_match_is_accepted(self) -> None:
        matches = match_documents(
            {"doc001": self.TEXT_A}, {"doc001": self.TEXT_A}, {"a.pdf": self.TEXT_A, "b.pdf": self.TEXT_B}
        )
        self.assertTrue(matches["doc001"].accepted)
        self.assertEqual(matches["doc001"].pdf, "a.pdf")

    def test_near_duplicate_pdfs_are_ambiguous_unless_exact(self) -> None:
        variant = self.TEXT_A.replace("alpha3 ", "gamma3 ")
        pdfs = {"a.pdf": self.TEXT_A, "a2.pdf": variant}
        self.assertTrue(match_documents({"d": self.TEXT_A}, {"d": self.TEXT_A}, pdfs)["d"].accepted)
        other = self.TEXT_A.replace("alpha5 ", "delta5 ")
        result = match_documents({"d": other}, {"d": other}, pdfs)["d"]
        self.assertFalse(result.accepted)
        self.assertIn("ambiguous", result.reason)

    def test_unrelated_text_stays_unmatched(self) -> None:
        result = match_documents({"d": self.TEXT_B}, {"d": self.TEXT_B}, {"a.pdf": self.TEXT_A})["d"]
        self.assertFalse(result.accepted)

    def test_letter_spaced_pdf_falls_back_to_characters(self) -> None:
        spaced = " ".join(self.TEXT_A.replace(" ", ""))
        result = match_documents({"d": self.TEXT_A}, {"d": self.TEXT_A}, {"s.pdf": spaced, "b.pdf": self.TEXT_B})["d"]
        self.assertTrue(result.accepted)
        self.assertIn("letter-spaced", result.reason)

    def test_registry_uses_sources_then_matches(self) -> None:
        docs = {"doc001": [chunk("doc001_p1_c1", "x", title="One")], "doc119": [chunk("doc119_p1_c1", "y")]}
        sources = {"doc119": "https___catalog-utdallas-edu_.pdf"}
        matches = match_documents({"doc001": self.TEXT_A}, {"doc001": self.TEXT_A}, {"a.pdf": self.TEXT_A})
        entries = build_registry(docs, sources, matches)
        self.assertEqual([e["pdf"] for e in entries], ["a.pdf", "https___catalog-utdallas-edu_.pdf"])
        self.assertEqual(entries[1]["source_url"], "https://catalog.utdallas.edu/")


class AuditAndCleanupTests(unittest.TestCase):
    FOOTER = "Related Pages Privacy Policy 800 W. Campbell Road Richardson, Texas 75080-3021 Contact Us"
    CHATBOT = "May I help you? Hi there! I’m a chatbot here to answer your questions. What would you like to know?"

    def test_audit_flags_known_problems(self) -> None:
        records = [
            chunk("doc200_p1_c1", "Too short."),
            chunk("doc200_p2_c1", "Real content sentence here. " * 5 + self.FOOTER, title="UT Dallas > Office >"),
            chunk("doc200_p3_c1", "N e e d a s s i s t a n c e ? C l i c k"),
            chunk("doc201_p1_c1", "Too short."),
        ]
        findings = audit(records)
        self.assertLessEqual({"doc200_p1_c1", "doc201_p1_c1"}, {row["chunk_id"] for row in findings["short"]})
        self.assertNotIn("doc200_p2_c1", {row["chunk_id"] for row in findings["short"]})
        self.assertEqual({row["chunk_id"] for row in findings["duplicate"]}, {"doc200_p1_c1", "doc201_p1_c1"})
        self.assertIn("doc200_p2_c1", {row["chunk_id"] for row in findings["page_furniture"]})
        self.assertIn("doc200_p2_c1", {row["chunk_id"] for row in findings["bad_title"]})
        self.assertIn("doc200_p3_c1", {row["chunk_id"] for row in findings["odd_characters"]})

    def test_detectors(self) -> None:
        self.assertTrue(letter_spaced("N e e d a s s i s t a n c e ? C l i c k"))
        self.assertTrue(navigation_like("Deadlines Forms Code of Conduct Grants Loans Waivers Work Study Estimated Costs"))
        self.assertFalse(navigation_like("Students must submit the form. The office reviews it within two weeks."))

    def test_strip_furniture_keeps_content(self) -> None:
        text = f"Grades post after finals. {self.CHATBOT} Showing 1 to 5 of 5 entries {self.FOOTER}"
        self.assertEqual(strip_furniture(text), "Grades post after finals.")
        address = "Mail forms to 800 W. Campbell Road Richardson, Texas 75080-3021 by Friday."
        self.assertEqual(strip_furniture(address), address)

    def test_clean_doc_repairs_merges_and_dedupes(self) -> None:
        body = "Students may appeal a withdrawal decision in writing to the registrar office."
        records = [
            chunk("doc130_p1_c1", body + " Appeals are reviewed by a committee each term in the order they"
                  " arrive, and decisions are sent by email within ten business days.", title="Old"),
            chunk("doc130_p2_c1", "graduates may also apply.", heading="Teacher Center: For students and"),
            chunk("doc130_p3_c1", self.CHATBOT + " " + self.FOOTER),
            chunk("doc130_p4_c1", body + " What do I need to do?"),
        ]
        cleaned, stats = clean_doc("doc130", records)
        texts = [c["text"] for c in cleaned]
        self.assertEqual([c["chunk_id"] for c in cleaned], ["doc130_p1_c1"])
        self.assertIn("Teacher Center: For students and graduates may also apply.", texts[0])
        self.assertEqual(texts[0].count(body), 1)
        self.assertEqual(cleaned[0]["source_title"], "Office of Financial Aid: Scholarships")
        self.assertGreaterEqual(stats["navigation_dropped"], 1)

    def test_fix_refuses_hand_chunked_docs(self) -> None:
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            fix_main(["--docs", "001-169", "--dry-run"])

    def test_fix_is_idempotent_on_committed_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "chunks"
            shutil.copytree(DATA / "chunks", target, ignore=shutil.ignore_patterns("__pycache__"))
            before = {p.name: p.read_text(encoding="utf-8") for p in target.glob("doc1[1-9]*.json")}
            with self.assertLogs("fix_chunks", level="INFO"):
                fix_main(["--chunks", str(target)])
            after = {p.name: p.read_text(encoding="utf-8") for p in target.glob("doc1[1-9]*.json")}
            self.assertEqual(before, after)


class QuestionTests(unittest.TestCase):
    def test_data_questions_are_balanced(self) -> None:
        text = "\n".join(line for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
                         if not line.lstrip().startswith("//"))
        questions = [q for q in json.loads(text) if q["id"].startswith("data-")]
        self.assertGreaterEqual(len(questions), 40)
        splits = [q["split"] for q in questions]
        self.assertEqual(splits.count("dev"), splits.count("test"))
        unanswerable = [q for q in questions if q["unanswerable"]]
        self.assertTrue(0.2 <= len(unanswerable) / len(questions) <= 0.3)
        for question in unanswerable:
            self.assertEqual(question["evidence"], [])
            self.assertTrue(question["unanswerable_reason"])
        for question in questions:
            for group in question["evidence"]:
                doc = group.get("doc_id") or group["doc_ids"][0]
                self.assertGreaterEqual(int(re.sub(r"\D", "", doc)), 119)


class EndToEndTests(unittest.TestCase):
    PASSAGE = Passage(
        chunk_id="doc900_p1_c1",
        doc_id="doc900",
        text="An official transcript costs $10 to order online. The office opens at 8 a.m. on weekdays.",
        source_title="Registrar",
        section_heading="Transcripts",
        score=1.0,
    )

    def test_extractive_answer_cites_supporting_sentence(self) -> None:
        answer = extractive_answer("How much is an official transcript?", [self.PASSAGE])
        self.assertFalse(answer.abstained)
        self.assertEqual(answer.text, "An official transcript costs $10 to order online. [1]")
        self.assertEqual([c.chunk_id for c in answer.citations], ["doc900_p1_c1"])
        report = citation_report(answer, [self.PASSAGE])
        self.assertEqual((report["citation_valid"], report["citation_support"]), (True, 1.0))

    def test_no_passages_abstains(self) -> None:
        answer = extractive_answer("How much is an official transcript?", [], "No answer.")
        self.assertEqual((answer.text, answer.abstained, answer.citations), ("No answer.", True, []))
        self.assertIsNone(citation_report(answer, [])["citation_valid"])

    def test_orphan_and_unsupported_citations_are_caught(self) -> None:
        cite = Citation(1, "doc900_p1_c1", "doc900", "Registrar", "Transcripts", "snippet")
        orphan = Answer("Transcripts cost $10 [2].", [cite])
        self.assertEqual(citation_report(orphan, [self.PASSAGE])["orphan_markers"], [2])
        self.assertFalse(citation_report(orphan, [self.PASSAGE])["citation_valid"])
        unsupported = Answer("Parking permits require a campus vehicle sticker [1].", [cite])
        self.assertEqual(citation_report(unsupported, [self.PASSAGE])["citation_support"], 0.0)

    def test_cli_runs_offline_and_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "e2e.json"
            stdout = io.StringIO()
            with redirect_stdout(stdout), self.assertLogs("eval_e2e", level="INFO"):
                self.assertEqual(e2e_main(["--split", "dev", "--limit", "3", "--fallback", "--json", str(out)]), 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("| citation validity |", stdout.getvalue())
        self.assertEqual(payload["generator"], "extractive-fallback")
        self.assertEqual(len(payload["results"]), 3)
        for row in payload["results"]:
            self.assertEqual(row["question"]["split"], "dev")
            self.assertIn("evidence_recall", row["metrics"])
            self.assertGreaterEqual(row["latency_ms"], 0)


if __name__ == "__main__":
    unittest.main()
