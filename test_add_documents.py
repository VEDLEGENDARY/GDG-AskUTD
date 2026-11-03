"""Checks for the chunking helpers in add_documents.py."""
import unittest

import add_documents as ad


class ChunkingTests(unittest.TestCase):
    def test_two_chunk_tail_merge_does_not_crash(self):
        body = " ".join(f"Sentence number {i} has several plain words in it." for i in range(30))
        chunks = ad.chunk_section(body)
        self.assertTrue(chunks)
        self.assertTrue(all(len(c.split()) <= ad.MAX_WORDS for c in chunks))

    def test_short_sections_are_merged(self):
        lines = ["Drop Policy", "Students may drop a class before the census date.", "Refunds", "Refunds follow the academic calendar deadlines."]
        sections = ad.split_sections(lines)
        self.assertEqual(len(sections), 1)
        self.assertIn("census date", sections[0][1])

    def test_clean_lines_strips_browser_furniture(self):
        lines = ad.clean_lines("11/2/25, 3:14 PM Registrar\nReal content here.\nhttps://example.edu/page 1/3\n2")
        self.assertEqual([l for l in lines if l], ["Real content here."])

    def test_ligatures_replaced(self):
        self.assertEqual(ad.clean_lines("o\ufb03ce")[0], "office")

    def test_chunks_have_no_newlines(self):
        for c in ad.chunk_section("First sentence here.\nSecond sentence continues. " * 20):
            self.assertNotIn("\n", c)


if __name__ == "__main__":
    unittest.main()
