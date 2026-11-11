# Mentee 5 fixtures (retrieval efficiency)

Test-only material for checking that the optimized `LexicalIndex` returns exactly what the
mentor's baseline returned. Nothing here is imported by production code
(`backend/tests/test_mentee5_efficiency.py` enforces that).

| File | Purpose |
| --- | --- |
| `baseline_index.py` | Verbatim copy of `backend/app/retrieval_support/index.py` at commit `f763b1c75302879d25035445b12b5757746b3970`, renamed `BaselineLexicalIndex`. The parity reference. |
| `stress_queries.json` | Adversarial queries: unknown terms, stopwords only, punctuation only, repeated terms, very common terms, Unicode/full-width text, a long question and a 200x repeated query (`@REPEAT@`). |
| `synthetic.py` | Deterministic synthetic corpus and query generator (Zipf-like vocabulary, rare tokens, metadata-only terms, shared doc IDs) for scaling and parity. Synthetic timings are always labeled as synthetic. |

These are development fixtures. They contain no labels and do not touch `evaluate/questions.json`.
