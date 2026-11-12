# Handoff 02: corpus quality and evidence integrity (mentee 2)

Branch `codex/mentee-2-corpus`, baseline commit `f763b1c75302879d25035445b12b5757746b3970`
(`main` at the start of the assignment, current retrieval and grounding work included).

## Summary

`scripts/mentee2_corpus.py` audits the corpus and proposes cleanup without ever writing to
`backend/data/`. Edits are split into tiers:

- **safe** rules are character-level fixes that keep every word.
- **review** rules remove furniture or repair headings. Chunk IDs stay the same, every edit is recorded with its exact span, and each one is guarded.
- **migrations** (merges, splits, retired IDs) are written as a mapping and never applied.
- **flags** need a human decision and come with no edit.

Main findings:

- The corpus is cleaner than the audit counts suggest. Of 3,003 chunks, the recommended
  stage changes 90 chunks (text or heading) and keeps every chunk ID.
- No benchmark evidence is lost. All 300 evidence groups in both splits stay supported, and no
  chunk that supported a group stops supporting it.
- The effect on retrieval metrics is small. Dev leaderboard 61.84 to 61.85, with complete
  evidence and recall unchanged. Mean context drops by 2.5 estimated tokens per query.
- The useful quality wins are about context, not scores. Headings glued onto the wrong chunk
  move back to the chunk they introduce (for example "How To Find Your Final Exam Assignment"),
  and 36 sentences that were cut across chunk boundaries (several of them rule plus exception)
  get merge proposals.
- Five chunks (course codes such as `CE 4348.`) are shorter than `min_chunk_words = 3`, so the
  production index never searches them. A merge proposal (M4) makes them visible.

Retrieval metrics are not answer accuracy. Nothing here shows that answers got more correct.

## Changed files

| file | purpose |
| --- | --- |
| `scripts/mentee2_corpus.py` | audit, proposal engine, staging, evaluation adapter, ablation |
| `backend/tests/test_mentee2_corpus.py` | 24 offline tests (synthetic fixtures plus read-only production checks) |
| `evaluate/mentee2/fixtures/chunks/synthetic.json` | synthetic chunks: fee, deadline, exception, negation, table, duplicates, furniture, encoding |
| `evaluate/mentee2/fixtures/labels.json` | synthetic evidence labels for the fixtures |
| `evaluate/mentee2/fixtures/raw_text/doc901.txt` | synthetic raw text with standalone heading lines |
| `evaluate/mentee2/review_manifest.json` | 35 hand-inspected proposals with verdicts and hashes |
| `documentation/mentee-tasks/handoff-02.md` | this report |

No shared file, corpus file, config or benchmark label was changed. Generated runs live in
`evaluate/runs/mentee-2/` (ignored by Git), so no copy of the corpus is committed.

## Commands

Run from the repository root (`py` on Windows):

```bash
python -m pytest backend/tests -q                       # or: python -m unittest discover -s backend/tests -p "test_*.py"
python scripts/eval_retrieval.py --split dev --json evaluate/runs/mentee-2/baseline-dev.json

python scripts/mentee2_corpus.py audit --json evaluate/runs/mentee-2/audit.json
python scripts/mentee2_corpus.py propose                                    # dry run, writes nothing
python scripts/mentee2_corpus.py propose --accept R1,R2,R3,R4,R5 \
    --skip R5:doc178_p1_c1,R5:doc195_p5_c1 \
    --write --out evaluate/runs/mentee-2/stage-recommended --replace       # staged corpus + manifests
python scripts/mentee2_corpus.py evaluate --staged evaluate/runs/mentee-2/stage-recommended \
    --split dev --json evaluate/runs/mentee-2/recommended-dev.json
python scripts/mentee2_corpus.py ablate --split dev --json evaluate/runs/mentee-2/ablation-dev.json
python evaluate/evaluate_chunks.py --validate-only --chunks evaluate/runs/mentee-2/stage-recommended/chunks
```

A staged run holds `chunks/` (same file names and JSON layout as the source, so `diff -u`
works), `manifest.json` (every proposal), `migration.json` (`"applied": false`) and `flags.json`.

### Safety properties

- **Dry run by default.** `--write` is needed to stage anything, and outputs must resolve
  (symlinks followed) inside `evaluate/runs/mentee-2/`.
- **Inputs are protected.** The tool refuses outputs on or around `backend/data`, the chunk
  directory, the registry, the questions, the config, the fixtures or the `--chunks` input,
  including an output directory that would contain the input. Each file is re-checked before
  writing and is never written through a symlink.
- **Earlier runs only.** `--replace` deletes only a directory holding this tool's own manifest.
- **Nothing is fetched.** No network access, and official sources are never replaced.
- **Deterministic.** There are no timestamps, so two runs give byte-identical manifests and
  chunks (tested).
- **Idempotent.** Running the tool on its own staged output proposes no safe edits (tested).
- **Compatible with existing tools.** `fix_chunks.py --dry-run` reports no changes on the staged
  corpus, so the existing idempotence test keeps passing after the mentor applies it.

## Audit (whole corpus, 3,003 chunks, 198 docs)

Corpus hash (evaluate_chunks fingerprint): `aa120d8cf208bdf3d5e363714416a1c3c3e997949530492d761bb9da91bfa7db`.

| issue | count | representative ids |
| --- | --- | --- |
| breadcrumb trail left in text (`UT Dallas > ... >`) | 45 | doc124_p1_c1, doc136_p1_c1, doc149_p1_c1, doc174_p1_c1 |
| footer or menu furniture, whole chunk | 44 | doc091_p51_c344, doc090_p13_c75, doc108_p3_c20, doc117_p4_c8 |
| footer run inside a content chunk | 2 | doc026_p1_c49, doc118_p1_c48 |
| footer text used as a section heading | 6 (plus 38 on furniture-only chunks) | doc026_p1_c49, doc118_p1_c48 |
| browser print stamp (`1 of 3 1/29/2007 2:35 PM`) | 3 | doc016_p1_c1, doc016_p1_c15, doc016_p1_c32 |
| corrupted encoding (`1Â Curriculum`) | 4 | doc026_p1_c12, doc118_p1_c11 |
| glued sentences (`Pay.Fulltime`) | 4 | doc089_p8_c46, doc133_p1_c2 |
| letter-spaced extraction (`S c h o o l`) | 15 | doc026_p1_c2, doc016_p1_c35 |
| heading glued to the end of the previous chunk | 17 | doc132_p1_c2, doc133_p16_c1, doc124_p3_c1 |
| chunk boundary mid-sentence | 58 (36 mergeable) | doc090_p7_c44, doc107_p3_c11 |
| exact duplicate copies | 169 (124 clusters) | doc026 and doc118 share 50 chunks |
| exact duplicate within one doc, same heading | 4 | doc091_p37_c249, doc108_p2_c15 |
| exact duplicate within one doc, different heading | 1 | doc091_p10_c45 |
| near duplicates (shingle Jaccard 0.8 to 1) | 124 pairs (81 differ in numbers, negations or conditions) | doc021_p1_c8 vs doc022_p1_c8 |
| version families with different catalog years | 9 families, 44 docs, 35 older versions | CS, CE, SE degree plans and flow charts |
| time-scoped text (term or catalog year) | 277 | doc132_p1_c1 (`Fall 2026`), doc189_p1_c3 |
| oversized (over 250 words) | 6 | doc006_p1_c3, doc019_p14_c44 |
| short (under 15 words), kept | 313 | doc016_p1_c12, doc078_p1_c24 |
| invisible to the index (under `min_chunk_words`) | 5 | doc078_p1_c24, doc079_p1_c4, doc087_p1_c7 |
| table-like chunks | 147 | doc002_p1_c2, doc020_p1_c5 |
| column header used as heading (`Pre-Requisite Course`) | 80 | doc065_p1_c10 |
| registry missing `source_url` (and `pdf`) | 41 (11) | doc002, doc170 to doc198, doc022 |
| generic heading `Overview` | 1,245 | most web pages |

`audit_corpus.py`'s `navigation` check flags 48 chunks, but almost all of them are degree-plan
tables, not menus. The real menus are the furniture-only chunks above.

## Rules

| rule | tier | what it does | count |
| --- | --- | --- | --- |
| S1 | safe | Unicode NFC | 0 |
| S2 | safe | drop zero-width, soft hyphen, BOM, control characters; non-breaking space to space | 0 |
| S3 | safe | collapse space or tab runs and trim; line breaks kept (they can separate table rows) | 0 |
| S4 | safe | repair cp1252 mojibake from a fixed table, plus a stray `Â` before a space | 4 |
| S5 | safe | add the space in `word.Word` / `20.Late`; emails, URLs, decimals skipped | 4 |
| R1 | review | remove a breadcrumb trail rooted at `UT Dallas` / `The University of Texas at Dallas` / `Harry W. Bass Jr.`, keep the page name | 45 |
| R2 | review | remove a footer run only when it contains a footer marker (privacy policy, copyright, Related Pages) | 2 |
| R3 | review | remove a browser print stamp; the printed URL stays as provenance | 3 |
| R4 | review | footer-text heading becomes `Overview`; a lone `Contact Us` or `Forms` is a real heading and is kept | 6 |
| R5 | review | move a Title Case heading glued to a chunk's end onto the next chunk; it must be a whole line in `raw_text` | 17 |
| M1 | migration | retire a furniture-only chunk | 44 |
| M2 | migration | retire a later exact duplicate with the same doc and heading | 4 |
| M3 | migration | merge a chunk ending mid-sentence with its continuation (same heading, at most 300 words) | 36 |
| M4 | migration | merge a chunk the index filters out into its neighbour | 5 |
| M5 | migration | split an oversized chunk at a sentence boundary that does not start with an exception cue | 4 (2 blocked) |
| F1 to F9 | flag | letter-spaced text, duplicates, near-duplicate variants, time scope, version families, short chunks, metadata, tables, mid-sentence boundaries | see audit |

### Guards on every proposal

- **Protected facts.** Numbers, money, percentages, dates, negations and condition words
  (`except`, `unless`, `only`, `must`, `eligible`, ...) removed or added are listed on the
  proposal.
- **Word order.** The proposal records whether word order survived (deletions only, so table
  rows keep their columns).
- **Safe rules must keep the word sequence identical.** Otherwise they are `blocked`.
- **Evidence labels.** Any edit that would stop a chunk supporting a benchmark evidence group
  is `blocked`, in any tier. Labels from both splits are used only as this do-not-lose guard,
  never for tuning.
- **Evidence floor for retirement.** A retirement (M1, M2) is blocked when the chunk is the last
  surviving support for any evidence group. Retirements are checked cumulatively, so
  deduplication cannot remove every copy.
- **Duplicates across docs are never retired.** Each copy is its own provenance (doc026 and
  doc118 come from the same PDF, but both are registered docs).
- **Years are never changed.** Time-scoped text is flagged only, and R5 carries a year such as
  `Fall 2026` into the heading untouched.

## Sample diffs (staged vs source)

doc132, R1 and R5 (the heading-context case):

```diff
-    "text": "UT Dallas > Office of the Registrar > Final Exam Assignments Final Exam Assignments. Fall 2026 Exam Dates: ...
+    "text": "Final Exam Assignments Final Exam Assignments. Fall 2026 Exam Dates: ...
@@ doc132_p1_c2
-    "text": "... Please check Orion the week before finals to verify final exam time and room assignment. How To Find Your Final Exam Assignment",
+    "text": "... Please check Orion the week before finals to verify final exam time and room assignment.",
@@ doc132_p2_c1
-    "section_heading": "Students",
+    "section_heading": "How To Find Your Final Exam Assignment Students",
```

doc026_p1_c12, S4: `component) 1Â Curriculum Requirements` becomes `component) 1 Curriculum Requirements`.

doc016_p1_c15, R3: `... hd-neuro . html 2 of 3 1/29/2007 2:35 PM hours part E ...` becomes
`... hd-neuro . html hours part E ...` (the guard lists `1/29/2007` as a removed date. That is
the capture date of the printed page, not a policy date).

doc090_p7_c44 + doc090_p8_c45, M3 (proposal only): `... accompanied by an advisor of their
choosing at meetings and` | `interviews at which they are present; however, no advisor may
examine ...` becomes one chunk, so the exception stays with its rule.

## Migration proposal (not applied)

`migration.json` maps old IDs to new IDs. New IDs follow the `docNNN_pX_cY` pattern that
`fill_chunk_counts.py` validates.

| rule | proposals | recommendation |
| --- | --- | --- |
| M1 retire furniture-only chunk | 44 | accept: pure footer or menu text, no labelled evidence |
| M3 merge mid-sentence boundary | 36 | accept: repairs real splits, several are rule plus `however` / `unless` |
| M4 merge index-invisible fragment | 5 | accept, or lower `min_chunk_words` instead (mentor-owned config) |
| M2 retire same-heading duplicate | 4 | reject: both reviewed cases are the same text in different procedures under broken or generic headings |
| M5 split oversized | 4 (+2 blocked) | reject: 2 of 4 cuts separate a requirement from its consequence, and all 6 chunks are already under the 300-word index limit |

## Manual review

`evaluate/mentee2/review_manifest.json` records 35 inspected proposals: 20 accept, 6 accept with
a note, 6 reject, and 3 flag decisions (keep both copies). Coverage: tables (doc064, doc078,
doc021 vs doc022), numbers and dates (doc016, doc090, doc189), exceptions (doc124, doc090,
doc107, doc019), negations (doc026, doc136) and repeated policy text (doc091, doc108,
doc026/doc118).

- **R1:** correct in every case. 24 of 45 drop context words that are not in the title or
  heading (most often `Legislative Policies`, `Establishing`). Each proposal's `note` lists them.
- **R5:** 14 of 17 correct. `doc178_p1_c1` (navigation) and `doc195_p5_c1` (call to action) are
  skipped in the recommended stage. `doc133_p4_c1` reads awkwardly.
- **Precision on proposal-only rules.** M3 looked correct in every sample. M2 and M5 did not,
  see the table above.

## Metrics

Machine: Apple M3, macOS 26.0.1 arm64, Python 3.12.14. Production settings from
`backend/retrieval_config.json`, top_k 5, 102 dev questions (the 102 test questions were run
once, as a regression check). The adapter reproduces `scripts/eval_retrieval.py` exactly on the
source corpus (dev 61.84), and a test checks passage-for-passage parity with `retrieve()`.
Staged corpus hash: `f488bbd952fddcca07c96ec1c6886ca0e122bedd4ba0ae7b0289ecece74ac2a4`.

### Before and after (recommended stage: safe + R1 to R5, two R5 skips)

| metric | dev before | dev after | test before | test after |
| --- | --- | --- | --- | --- |
| leaderboard | 61.84 | 61.85 | 59.71 | 59.58 |
| complete evidence | 0.571 | 0.571 | 0.610 | 0.610 |
| evidence recall | 0.731 | 0.731 | 0.755 | 0.755 |
| reciprocal rank | 0.742 | 0.746 | 0.796 | 0.802 |
| context precision | 0.484 | 0.485 | 0.539 | 0.530 |
| abstention correct | 0.76 | 0.76 | 0.40 | 0.40 |
| mean context tokens | 395.3 | 392.8 | 452.4 | 451.4 |
| cold index build ms | 120.0 | 123.2 | 119.9 | 372.4 |
| warm p50 / p95 ms | 15.8 / 30.9 | 14.2 / 18.2 | 14.0 / 19.2 | 20.4 / 153.3 |
| failures | 0 | 0 | 0 | 0 |

Before and after are measured in the same process on the same 2,998 indexed chunks. Latency is
noisy on this laptop. The test "after" timings came from one disturbed run. The nine dev
ablation runs all fall within cold 116 to 138 ms, p50 14.2 to 14.6 ms and p95 18.2 to 19.3 ms
(excluding the simulated-migration row). Cleanup does not change the index algorithm or the
chunk count, so no latency change is expected or claimed.

### Lost evidence (reported separately)

| check | result |
| --- | --- |
| evidence groups (both splits) | 300 |
| groups no longer supported anywhere | 0 |
| groups with a chunk that stopped supporting them | 0 |
| `evaluate_chunks.py --validate-only` on the staged corpus | dev and test pass, 0 infeasible |

### Per-query changes

| split | query | change | cause |
| --- | --- | --- | --- |
| dev | data-dev-tuition-rebate-rules | precision down (extra passage doc133_p17_c1) | R5 gives the rebate form chunk its heading `Texas Tuition Rebate`; on topic but not labelled |
| dev | dev-hard-unfinished-course | RR up | R1/R3 reorder passages |
| dev | data-dev-finaid-fax-dropoff | precision up | R1 |
| dev | nandhan-dev-conduct-records-retention | RR up | combined rules |
| test | nandhan-test-repeat-c-third-attempt | precision 1.0 to 0.5 (extra doc136_p1_c1) | R5; doc136 is the three-course repeat rule, on topic but not labelled |
| test | test-hard-nondegree-two-levels | precision 0.67 to 0.5 (extra doc145_p1_c1) | R1 shortens the chunk so it passes `min_score`; on topic, not labelled |
| test | data-test-transfer-credit-posting-time | RR 0.5 to 1.0 | R1 |

The test split was run once, as a regression check, and nothing was tuned on it. All
regressions are precision-only extra passages. No evidence was dropped.

### Ablation (dev)

| variant | leaderboard | delta | tokens | text changed | regressions |
| --- | --- | --- | --- | --- | --- |
| baseline | 61.84 | | 395.3 | | |
| safe only | 61.84 | 0.00 | 395.3 | 8 | 0 |
| safe + R1 | 61.85 | +0.01 | 392.3 | 53 | 0 |
| safe + R2 | 61.84 | 0.00 | 395.3 | 10 | 0 |
| safe + R3 | 61.84 | 0.00 | 395.3 | 11 | 0 |
| safe + R4 (headings only) | 61.84 | 0.00 | 395.3 | 8 | 0 |
| safe + R5 | 61.81 | -0.03 | 396.8 | 25 | 1 |
| safe + all review | 61.85 | +0.01 | 392.8 | 74 | 1 |
| + all migrations, simulated (IDs change) | 61.70 | -0.15 | 390.4 | 123 | 2 |

The simulated migration row is an experiment only. It loses recall on dev-hard-unfinished-course
because a merged chunk scores lower. Simulated p95 rose to 54 ms in that run. That was one noisy
measurement, not something worth acting on. The row is a reason to apply M1 and M3 separately
and remeasure, not all migrations at once.

## Limitations

- **Heuristic detection.** Rules are tuned to this corpus's furniture. Other site templates
  will need new phrases. R5 precision was about 82% in review.
- **Labels limit measurement.** Most quality gains (correct headings, no footer noise) fall on
  chunks the benchmark never asks about, so retrieval metrics barely move. Several measured
  regressions are on-topic passages missing from the labels.
- **Evidence guard scope.** The guard checks labelled phrases and protected token classes. It
  cannot prove an unlabelled fact survived. That is why removal rules are review-only and every
  removed span is recorded.
- **Not fixed.** Letter-spaced text (F1) and glued words such as `deadlinereceive` need
  re-extraction from the source PDFs, so they are flagged only. Near-duplicate version families
  are flagged. No current policy is inferred.
- **No answer evaluation.** Generation was not run, and no answer-accuracy claim is made.

## Problems outside my ownership (for the mentor)

1. **Five chunks are never searched** (doc078_p1_c24, doc079_p1_c4, doc080_p1_c5,
   doc087_p1_c7, doc087_p1_c23), because they have fewer than `min_chunk_words = 3` words.
   Fix with M4, or lower the limit in `backend/retrieval_config.json`.
2. **Two docs are duplicates.** doc026 and doc118 have 50 identical chunks (same catalog PDF).
   `max_per_document` does not stop both appearing. Consider collapsing identical text at
   retrieval time while keeping both citations (retrieval integration).
3. **Labels miss on-topic chunks.** doc133_p17_c1 (rebate form), doc136_p1_c1 and doc145_p1_c1
   are relevant for the regressed queries. Whether to add them is a label decision for the
   evaluation owner.
4. **Registry metadata is missing.** 41 docs have no `source_url` and 11 have no `pdf`.
5. **No pytest in CI.** pytest is not in any requirements file. CI runs `unittest discover`, which
   also picks up `test_mentee2_corpus.py`.

## Integration patch proposal (mentor applies after the other branches)

Step 1, after review: build the stage, apply it and rebuild. IDs are stable, so registry chunk
counts do not change.

```bash
python scripts/mentee2_corpus.py propose --accept R1,R2,R3,R4,R5 \
    --skip R5:doc178_p1_c1,R5:doc195_p5_c1 --write --out evaluate/runs/mentee-2/stage-recommended --replace
diff -ru backend/data/chunks evaluate/runs/mentee-2/stage-recommended/chunks | less    # review
cp evaluate/runs/mentee-2/stage-recommended/chunks/*.json backend/data/chunks/
python scripts/build_registry.py && python evaluate/evaluate_chunks.py --validate-only
python -m pytest backend/tests -q && python scripts/eval_retrieval.py --split dev
```

Step 2, a separate change so its effect is measured alone: apply M1 and M3 from
`migration.json`, refill counts with `fill_chunk_counts.py`, rebuild the registry (chunk counts
change) and remeasure.

Documentation proposal (not applied, `documentation/data.md` is shared):

```diff
@@ ## Corpus cleanup (docs 119 to 198)
+### Whole-corpus cleanup proposals (mentee 2)
+
+`scripts/mentee2_corpus.py` audits all docs (including the hand-chunked 001 to 118) and stages
+proposals under `evaluate/runs/mentee-2/` without touching `backend/data/`. Safe rules (S1 to S5)
+only normalize characters; review rules (R1 to R5) keep chunk ids and record exact removed spans;
+merges, splits and retirements (M1 to M5) are written to `migration.json` and never applied. See
+`documentation/mentee-tasks/handoff-02.md` for the rule list, guards and measurements.
```
