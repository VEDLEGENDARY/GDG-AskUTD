"""Offline tests for the mentee 2 corpus audit and cleanup proposal tool.

Synthetic fixtures live in evaluate/mentee2/fixtures/. The production corpus is only read.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import mentee2_corpus as m  # noqa: E402
from evaluate import evaluate_chunks as ev  # noqa: E402

FIXTURES = ROOT / "evaluate" / "mentee2" / "fixtures"
FIXTURE_CHUNKS = FIXTURES / "chunks"
ALL_REVIEW = set(m.REVIEW_RULES)


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*.json")):
        digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()


def fixture_run(accept: set[str] | None = None) -> m.Proposer:
    chunks, _ = m.read_corpus(FIXTURE_CHUNKS)
    return m.Proposer(chunks, m.load_groups(FIXTURES / "labels.json"), accept, (3, 300), [],
                      m.read_raw_lines(FIXTURES / "raw_text")).run()


def staged(proposer: m.Proposer) -> dict[str, dict]:
    return {c["chunk_id"]: m.recount(c, o) for c, o in zip(proposer.chunks, proposer.source)}


def migrations(proposer: m.Proposer, rule: str) -> list[dict]:
    return [x for x in proposer.migrations if x["rule"] == rule]


class EvidencePreservationTests(unittest.TestCase):
    """A fee, a deadline, an eligibility exception, a negation and a table row survive every rule."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.safe = fixture_run()
        cls.full = fixture_run(ALL_REVIEW)
        cls.full_text = staged(cls.full)

    def test_fee_survives_safe_and_review_rules(self) -> None:
        text = self.full_text["doc901_p1_c1"]["text"]
        self.assertIn("The application fee is $75 for domestic applicants.", text)
        self.assertIn("applicants. Fee waivers are not available", text, "S5 adds the missing space only")
        self.assertNotIn("UT Dallas >", text, "R1 removes the breadcrumb when accepted")
        tuition = self.full_text["doc907_p1_c1"]["text"]
        self.assertIn("$1,234.56 per term.", tuition)

    def test_deadline_keeps_its_heading_context(self) -> None:
        # The heading glued to the end of c1 introduces c2; R5 moves it instead of deleting it.
        c1, c2 = self.full_text["doc901_p1_c1"], self.full_text["doc901_p1_c2"]
        self.assertTrue(c2["text"].startswith("The deadline is November 15."))
        self.assertEqual(c2["section_heading"], "Graduate Applications for Fall 2025")
        self.assertNotIn("Graduate Applications for Fall 2025", c1["text"])
        self.assertIn("2025", c2["section_heading"], "the year is preserved, never replaced")
        flagged = {f["chunk_id"]: f["detail"] for f in self.full.flags if f["rule"] == "F4"}
        self.assertIn("Fall 2025", flagged["doc901_p1_c1"], "time-scoped text is flagged for review")

    def test_r5_requires_a_standalone_source_line(self) -> None:
        chunks, _ = m.read_corpus(FIXTURE_CHUNKS)
        proposer = m.Proposer(chunks, [], ALL_REVIEW, (3, 300), [], raw_lines={}).run()
        self.assertFalse([p for p in proposer.proposals if p["rule"] == "R5"])

    def test_eligibility_exception_stays_with_its_rule_when_splitting(self) -> None:
        split = migrations(self.full, "M5")
        self.assertEqual(len(split), 1)
        proposal = split[0]
        self.assertEqual(proposal["status"], "proposal_only")
        self.assertFalse(proposal["right_starts"].startswith("However"))
        text = self.full_text["doc902_p1_c1"]["text"]
        left, right = text[:proposal["split_at"]], text[proposal["split_at"]:]
        side = left if "must complete 30 semester credit hours" in left else right
        self.assertIn("are exempt from this requirement", side, "rule and exception land in the same chunk")
        self.assertEqual(proposal["evidence_lost"], [])
        self.assertRegex(proposal["new_ids"][1], r"^doc902_p1_c\d+$")
        self.assertEqual(text, self.safe.source[2]["text"], "the split is proposed, never applied")

    def test_negation_is_protected(self) -> None:
        self.assertIn("may not drop a course", self.full_text["doc902_p1_c2"]["text"])
        guard = m.content_guard("Students may not drop a course.", "Students may drop a course.")
        self.assertEqual(guard["negations_removed"], ["not"])
        self.assertFalse(m.guard_clean(guard))

    def test_table_rows_keep_their_columns(self) -> None:
        proposal = next(p for p in self.full.proposals if p["chunk_id"] == "doc903_p1_c1" and p["rule"] == "R2")
        self.assertEqual([e["removed"].strip() for e in proposal["edits"]],
                         ["Privacy Policy. © The University of Texas at Dallas"])
        text = self.full_text["doc903_p1_c1"]["text"]
        for row in ("CS 1336 Programming Fundamentals 3", "CS 1337 Computer Science I 3", "MATH 2413 Differential Calculus 4"):
            self.assertIn(row, text)
        self.assertTrue(proposal["guard"]["order_preserved"])
        self.assertNotIn("numbers_removed", proposal["guard"])

    def test_short_chunk_is_kept_and_merge_is_only_proposed(self) -> None:
        self.assertEqual(self.full_text["doc903_p1_c2"]["text"], "MATH 2414.")
        merge = migrations(self.full, "M4")
        self.assertEqual(merge[0]["old_ids"], ["doc903_p1_c1", "doc903_p1_c2"])
        self.assertIn("doc903_p1_c2", {f["chunk_id"] for f in self.full.flags if f["rule"] == "F6"})

    def test_no_labelled_evidence_is_lost(self) -> None:
        manifest = m.manifest_for(self.full, FIXTURE_CHUNKS)
        self.assertEqual(manifest["evidence"]["lost_everywhere"], [])
        self.assertEqual(manifest["evidence"]["chunks_no_longer_supporting"], [])
        self.assertTrue(manifest["staged_changes"]["chunk_ids_unchanged"])


class SafeRuleTests(unittest.TestCase):
    def test_safe_rules_are_auto_and_keep_every_word(self) -> None:
        proposer = fixture_run()
        safe = [p for p in proposer.proposals if p["tier"] == "safe"]
        self.assertEqual({p["rule"] for p in safe}, {"S2", "S4", "S5"})
        for p in safe:
            self.assertEqual(p["status"], "auto", p)
            self.assertTrue(p["guard"]["signature_equal"])
        self.assertFalse([p for p in proposer.proposals if p["tier"] == "review" and p["applied"]],
                         "review rules are never applied without --accept")
        text = staged(proposer)["doc907_p1_c1"]["text"]
        self.assertEqual(text, "Tuition is $1,234.56 per term. Payment is due August 20. Late fees apply after that date. "
                               "Footnote 1 Curriculum hours count once. Contact Parker.Ellis@example.edu for help.")

    def test_safe_rule_that_drops_a_word_would_be_blocked(self) -> None:
        proposer = m.Proposer([], [])
        guard = m.content_guard("Fees are not refundable.", "Fees are refundable.")
        self.assertEqual(proposer._status(m.RULES["S3"], guard, set()), "blocked")
        self.assertEqual(proposer._status(m.RULES["R1"], guard, {"q#0"}), "blocked")

    def test_normalization_is_idempotent(self) -> None:
        first = fixture_run(ALL_REVIEW)
        rerun = m.Proposer(list(staged(first).values()), m.load_groups(FIXTURES / "labels.json"), ALL_REVIEW,
                           (3, 300), [], m.read_raw_lines(FIXTURES / "raw_text")).run()
        self.assertEqual([p for p in rerun.proposals if p["tier"] == "safe"], [])
        self.assertEqual(list(staged(rerun).values()), list(staged(first).values()))

    def test_email_and_line_breaks_untouched(self) -> None:
        self.assertEqual(m.s5("Email Parker.Ellis@utdallas.edu today."), [])
        self.assertEqual(m.s3("Row one\nRow two"), [], "line breaks may separate table rows")


class DeduplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.proposer = fixture_run(ALL_REVIEW)

    def test_one_copy_always_survives(self) -> None:
        retired = migrations(self.proposer, "M2")
        self.assertEqual(sorted(x["old_ids"][0] for x in retired), ["doc904_p1_c2", "doc904_p1_c4"])
        self.assertTrue(all(x["mapping"][x["old_ids"][0]] == "doc904_p1_c1" for x in retired))
        after = m.apply_migrations_in_memory(list(staged(self.proposer).values()), self.proposer.migrations)
        survivors = [c["chunk_id"] for c in after if "accepted as your signature" in c["text"]]
        self.assertIn("doc904_p1_c1", survivors)
        self.assertIn("doc905_p1_c1", survivors, "cross-doc copies are never retired")
        self.assertIn("doc904_p1_c3", survivors, "same text under another heading is different context")
        support = m.EvidenceIndex(m.load_groups(FIXTURES / "labels.json")).corpus_support(after)
        self.assertTrue(support["fx-duplicate#0"])

    def test_cross_doc_and_context_duplicates_are_flagged_not_removed(self) -> None:
        details = {f["detail"] for f in self.proposer.flags if f["rule"] == "F2"}
        self.assertEqual(details, {"cross_doc", "same_doc_different_heading"})

    def test_only_copy_of_evidence_blocks_retirement(self) -> None:
        furniture = migrations(self.proposer, "M1")
        self.assertEqual([x["old_ids"] for x in furniture], [["doc906_p1_c2"]])
        self.assertEqual(furniture[0]["status"], "blocked")
        self.assertEqual(furniture[0]["evidence_only_copy"], ["fx-furniture-only#0"])

    def test_retirement_allowed_without_labels(self) -> None:
        chunks, _ = m.read_corpus(FIXTURE_CHUNKS)
        proposer = m.Proposer(chunks, [], None).run()
        self.assertEqual([x["status"] for x in migrations(proposer, "M1")], ["proposal_only"])

    def test_real_contact_heading_is_kept(self) -> None:
        self.assertFalse([p for p in self.proposer.proposals if p["rule"] == "R4" and p["doc_id"] == "doc906"])
        self.assertFalse(m.chrome_heading("Contact Us"))
        self.assertTrue(m.chrome_heading("Public Course and Syllabus Information Privacy Policy"))


class OutputSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "runs"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_refuses_paths_outside_root_or_on_inputs(self) -> None:
        with self.assertRaises(ValueError):
            m.check_output(m.CHUNKS_DIR / "staged", [], self.root)
        with self.assertRaises(ValueError):
            m.check_output(Path(self.tmp.name) / "elsewhere", [], self.root)
        with self.assertRaises(ValueError):
            m.check_output(self.root, [], self.root)
        source = self.root / "stage" / "chunks"
        with self.assertRaises(ValueError, msg="output containing the input would overwrite it"):
            m.check_output(self.root / "stage", [source], self.root)
        self.assertEqual(m.check_output(self.root / "ok", [], self.root), (self.root / "ok").resolve())

    def test_refuses_symlink_into_corpus(self) -> None:
        link = self.root / "link"
        os.symlink(m.DATA_DIR, link)
        with self.assertRaises(ValueError):
            m.check_output(link / "out", [], self.root)
        target = self.root / "out"
        target.mkdir()
        os.symlink(m.REGISTRY, target / "manifest.json")
        with self.assertRaises(ValueError):
            m.write_file(target / "manifest.json", "{}", target.resolve(), [])

    def test_stage_is_deterministic_and_leaves_source_untouched(self) -> None:
        before = tree_hash(FIXTURE_CHUNKS)
        chunks, files = m.read_corpus(FIXTURE_CHUNKS)
        outputs = []
        for name in ("a", "b"):
            proposer = m.Proposer(chunks, m.load_groups(FIXTURES / "labels.json"), {"R1", "R2"}, (3, 300), [],
                                  m.read_raw_lines(FIXTURES / "raw_text")).run()
            outputs.append(m.stage(proposer, FIXTURE_CHUNKS, files, self.root / name, False, self.root))
        self.assertEqual(tree_hash(FIXTURE_CHUNKS), before)
        for name in (m.MANIFEST, "migration.json", "flags.json", "chunks/synthetic.json"):
            self.assertEqual((outputs[0] / name).read_bytes(), (outputs[1] / name).read_bytes(), name)
        manifest = json.loads((outputs[0] / m.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(manifest["accepted_review_rules"], ["R1", "R2"])
        self.assertFalse(json.loads((outputs[0] / "migration.json").read_text(encoding="utf-8"))["applied"])
        removed = [e["removed"] for p in manifest["proposals"] if p["rule"] == "R1" for e in p["edits"]]
        self.assertEqual(removed, ["UT Dallas > Office of Graduate Admission > "], "the page name segment is kept")
        with self.assertRaises(ValueError, msg="non-empty output needs --replace"):
            m.stage(proposer, FIXTURE_CHUNKS, files, self.root / "a", False, self.root)
        m.stage(proposer, FIXTURE_CHUNKS, files, self.root / "a", True, self.root)

    def test_replace_refuses_foreign_directory(self) -> None:
        foreign = self.root / "foreign"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("not ours", encoding="utf-8")
        chunks, files = m.read_corpus(FIXTURE_CHUNKS)
        with self.assertRaises(ValueError):
            m.stage(m.Proposer(chunks, []).run(), FIXTURE_CHUNKS, files, foreign, True, self.root)
        self.assertTrue((foreign / "keep.txt").exists())


class ProductionCorpusTests(unittest.TestCase):
    """Read-only checks against the real corpus and the production retrieval pipeline."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.chunks, _ = m.read_corpus(m.CHUNKS_DIR)
        cls.before = tree_hash(m.CHUNKS_DIR)
        cls.proposer = m.Proposer(cls.chunks, m.load_groups(), ALL_REVIEW, m.index_limits(), m.load_registry(),
                                  m.read_raw_lines()).run()

    def test_full_cleanup_loses_no_benchmark_evidence(self) -> None:
        manifest = m.manifest_for(self.proposer, m.CHUNKS_DIR)
        self.assertEqual(manifest["evidence"]["lost_everywhere"], [])
        self.assertEqual(manifest["evidence"]["chunks_no_longer_supporting"], [])
        self.assertTrue(manifest["staged_changes"]["chunk_ids_unchanged"])
        self.assertTrue(all(p["status"] == "auto" for p in self.proposer.proposals if p["tier"] == "safe"))
        self.assertEqual(tree_hash(m.CHUNKS_DIR), self.before, "source corpus is read-only")

    def test_review_edits_never_touch_protected_facts_silently(self) -> None:
        for p in self.proposer.proposals:
            if p["field"] != "text":
                continue
            removed = "".join(e["removed"] for e in p["edits"])
            if re.search(r"\d", removed):
                self.assertIn("numbers_removed", p["guard"], p["chunk_id"])
            self.assertTrue(p["guard"]["order_preserved"], p["chunk_id"])
            self.assertNotIn("negations_removed", p["guard"], p["chunk_id"])

    def test_adapter_matches_production_retrieve(self) -> None:
        from backend.app.retrieval import load_urls, retrieve
        config = m.production_config()
        index = m.build_index(self.chunks, config)
        urls = load_urls(m.ROOT / config["registry_path"])
        questions = ev.read_questions(m.QUESTIONS, self.chunks, "dev")[:25]
        for q in questions + [{"query": "what about the deadline for that"}, {"query": "  "}]:
            self.assertEqual(m.staged_retrieve(index, config, urls, q["query"]), retrieve(q["query"]), q["query"])


if __name__ == "__main__":
    unittest.main()
