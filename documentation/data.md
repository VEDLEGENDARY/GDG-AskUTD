# Data: registry, corpus cleanup and benchmark

This file covers Task 4: the document registry (`backend/data/documents.json`), the
cleanup of the automatically chunked documents, the benchmark questions for them, the
end-to-end evaluation script, and the corpus counts before and after.

## Commands

```bash
python scripts/build_registry.py --report /tmp/registry_report.md   # rebuild documents.json
python scripts/audit_corpus.py --docs 119-198 --show 5                # audit report on stdout
python scripts/fix_chunks.py --docs 119-198 --dry-run                 # preview cleanup
python scripts/fix_chunks.py --docs 119-198                           # apply it, refill counts
python evaluate/evaluate_chunks.py --validate-only                    # must exit 0
python scripts/eval_e2e.py --split dev --json evaluate/runs/e2e_dev.json
python -m unittest discover -s backend/tests -p "test_*.py"
```

`build_registry.py` caches PDF text in the system temp folder (keyed by file hash), so
reruns take a few seconds. Pass `--no-cache` to force a fresh extraction.

## Document registry

`backend/data/documents.json` holds one entry per chunked document:

```json
{"doc_id": "doc132", "title": "Office of the Registrar: Final Exam Assignments",
 "source_url": "https://registrar.utdallas.edu/...", "pdf": "https___registrar-...pdf", "chunks": 6}
```

- `title` is the most common `source_title` among the doc's chunks.
- `pdf` is the file in `backend/data/raw_pdfs/`, or `null` when it could not be recovered.
- `source_url` is derived from the PDF filename (rule below), or `null`.
- `chunks` is the number of chunks in the doc's chunk file.

Current totals: 198 documents, 3,003 chunks, 157 documents with a URL and 41 with
`null` (11 unmatched older docs, doc002 on a non-UTD host, and the 29 docs added in P6
whose PDFs are named after the page title instead of the URL).

### How PDFs were matched to docs 001 to 118

Docs 119 onward list their PDF in `doc_sources.json`. For the older docs that mapping
was lost, so `build_registry.py` recovers it:

1. Extract text from every PDF not already claimed in `doc_sources.json` with
   `pdf_to_text.extract_text`.
2. Compare each `raw_text/docNNN.txt` with every PDF using Jaccard similarity on
   5-word shingles.
3. Accept the best PDF only when its score is at least 0.6 and either it beats the
   runner-up by 0.15 or more, or the doc text is word-for-word identical to that PDF
   and no other. Near-identical degree plans from different years fail the margin and
   stay unmatched unless the text is an exact match.
4. Cross-check with the chunk text: the doc's joined chunks must also score that PDF
   best (within 0.02). This guards against a stale `raw_text` file.
5. Some policy PDFs extract as letter-spaced text ("P o l i c y"). When more than half
   the tokens are single characters, the comparison falls back to 30-character
   shingles on text with spaces removed (doc089, doc091 and doc094 matched this way).

One PDF may back several docs. doc026, doc028 and doc118 come from the same graduate
catalog PDF, and doc036 and doc117 both come from the academic calendar PDF, so those
docs share a URL.

Result: 107 of 118 older docs recovered, 11 unmatched. Nothing below the rules was
guessed; unmatched docs keep `pdf` and `source_url` as `null`.

### URL rule

Filenames follow `documentation/naming.md` (`:` and `/` became `_`, `.` became `-`).
`filename_to_url` reverses that:

1. Only names starting with `https___` are URLs. Anything else (for example
   `Academic Advising - UTD Registrar.pdf`) gets `null`.
2. Remove the trailing `.pdf` (also a doubled `.pdf .pdf`).
3. If the name repeats the prefix (`https___host_https___host_...`), use the inner URL.
4. The host turns hyphens back into dots only for `<name>-utdallas-edu`. Other hosts
   (for example `bpb-us-e2-wpmucdn-com`) get `null` because their dots and hyphens
   cannot be told apart.
5. In the path, `_` becomes `/` and hyphens stay. After `files/YYYY/MM/` the rest is a
   single uploaded file name, so underscores in it are kept.
6. A trailing `-pdf` or `-html` on the last segment becomes `.pdf` or `.html`; a
   trailing `_` becomes a trailing `/`.

Low-confidence URLs (flagged in the report, worth a click before relying on them):

| docs | concern |
| --- | --- |
| doc020 to doc087 engineering files (54 docs) | doubled URL prefix in the filename and `.pdf` inferred from `-pdf` |
| doc051 | also keeps an underscore inside the uploaded file name (`PreReqMnr-CS_Minor.pdf`) |
| doc006, doc007 | `.pdf` inferred from a trailing `-pdf` |
| doc001, doc088 | uploaded file with no recorded extension |
| doc119 | last segment `headingContact` looks like an in-page anchor |
| doc002 | non-UTD host, URL left `null` |
| doc170 to doc198 | filename is a page title, URL left `null` |

### Recovered matches

| doc | PDF | score | runner-up | note |
| --- | --- | --- | --- | --- |
| doc001 | `https___bbs-utdallas-edu_files_2026_04_technical-standards-for-admission-comd-2026.pdf` | 1.00 | 0.03 | word shingles |
| doc002 | `https___bpb-us-e2-wpmucdn-com_sites-utdallas-edu_dist_1_1496_files_2024_07_2024-2025-IPECBA-Degree-Plan-pdf.pdf` | 1.00 | 0.02 | word shingles |
| doc003 | `https___catalog-utdallas-edu_2025_graduate_policies_registration-and-enrollment.pdf` | 1.00 | 0.07 | word shingles |
| doc004 | `https___catalog-utdallas-edu_2025_undergraduate_home.pdf` | 1.00 | 0.86 | exact text match, word shingles |
| doc005 | `https___catalog-utdallas-edu_2025_undergraduate_policies_academic.pdf` | 1.00 | 0.06 | word shingles |
| doc006 | `https___catalog-utdallas-edu_2025_undergraduate_policies_admission-policies-pdf.pdf` | 1.00 | 0.06 | word shingles |
| doc007 | `https___catalog-utdallas-edu_2025_undergraduate_policies_course-policies-pdf.pdf` | 1.00 | 0.01 | word shingles |
| doc008 | `https___catalog-utdallas-edu_2025_undergraduate_policies_degree-plans.pdf` | 0.99 | 0.02 | word shingles |
| doc009 | `https___catalog-utdallas-edu_2025_undergraduate_policies_ferpa.pdf` | 0.99 | 0.03 | word shingles |
| doc010 | `https___catalog-utdallas-edu_2025_undergraduate_policies_graduation.pdf` | 1.00 | 0.02 | word shingles |
| doc011 | `https___catalog-utdallas-edu_2025_undergraduate_policies_registration.pdf` | 1.00 | 0.07 | word shingles |
| doc012 | `https___conduct-utdallas-edu_faculty.pdf` | 0.86 | 0.19 | word shingles |
| doc013 | `https___conduct-utdallas-edu_policies.pdf` | 0.93 | 0.04 | word shingles |
| doc014 | `https___conduct-utdallas-edu_policies_hazing.pdf` | 1.00 | 0.04 | word shingles |
| doc015 | `https___conduct-utdallas-edu_students_dishonesty.pdf` | 0.99 | 0.02 | word shingles |
| doc016 | `https___dox-utdallas-edu_catalog1014.pdf` | 0.88 | 0.09 | word shingles |
| doc017 | `https___dox-utdallas-edu_memo1289.pdf` | 0.99 | 0.00 | word shingles |
| doc018 | `https___dox-utdallas-edu_publication1758.pdf` | 0.96 | 0.00 | word shingles |
| doc019 | `https___dox-utdallas-edu_syl155858.pdf` | 0.99 | 0.01 | word shingles |
| doc020 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_21-22-CE-Degree-Plan-1-pdf.pdf` | 1.00 | 0.92 | exact text match, word shingles |
| doc021 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_21-22-CS-Degree-Plan-pdf.pdf` | 1.00 | 0.98 | exact text match, word shingles |
| doc023 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_22-23-CE-Degree-Plan-pdf.pdf` | 1.00 | 0.87 | exact text match, word shingles |
| doc024 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_22-23-CS-Degree-Plan-pdf.pdf` | 0.99 | 0.82 | word shingles |
| doc026 | `https___www-utdallas-edu_golden_CGSACN_CGS2010-2012-April6-130pm.pdf` | 1.00 | 0.11 | word shingles; PDF shared by 3 docs |
| doc027 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_4YEAR-CS-2021-pdf.pdf` | 1.00 | 0.74 | word shingles |
| doc028 | `https___www-utdallas-edu_golden_CGSACN_CGS2010-2012-April6-130pm.pdf` | 0.99 | 0.11 | word shingles; PDF shared by 3 docs |
| doc029 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_4YEAR-SE-2021-pdf.pdf` | 1.00 | 0.70 | word shingles |
| doc032 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CE-DP-2018-2019-pdf.pdf` | 0.98 | 0.83 | word shingles |
| doc033 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CE-DP-2019-2020-pdf.pdf .pdf` | 1.00 | 0.70 | word shingles |
| doc034 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CE-DP-2020-2021-pdf.pdf` | 1.00 | 0.92 | exact text match, word shingles |
| doc035 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CE-FC-2016-2017-pdf.pdf` | 1.00 | 0.89 | exact text match, word shingles |
| doc036 | `https___www-utdallas-edu_academics_calendar.pdf` | 1.00 | 0.89 | exact text match, word shingles; PDF shared by 2 docs |
| doc037 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CE-FC-2019-2020-pdf.pdf` | 1.00 | 0.26 | word shingles |
| doc038 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CS-DP-2016-2017-pdf.pdf` | 0.97 | 0.77 | word shingles |
| doc039 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CS-DP-2017-2018-pdf.pdf` | 1.00 | 0.96 | exact text match, word shingles |
| doc041 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CS-DP-2019-2020-pdf.pdf` | 1.00 | 0.84 | word shingles |
| doc042 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CS-DP-2020-2021-pdf.pdf` | 1.00 | 0.98 | exact text match, word shingles |
| doc043 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CS-FC-2016-2017-pdf.pdf` | 1.00 | 0.84 | word shingles |
| doc045 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CS-FC-2018-2019-pdf.pdf` | 1.00 | 0.96 | exact text match, word shingles |
| doc047 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_Math-SE-Guided-Electives-1-pdf.pdf` | 1.00 | 0.06 | word shingles |
| doc048 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_Options-for-CE-Elective-Labs-22-23-pdf.pdf` | 1.00 | 0.00 | word shingles |
| doc049 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_Options-for-CS-Guided-Electives-22-23-pdf.pdf` | 1.00 | 0.80 | word shingles |
| doc050 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_Options-for-SE-Guided-Electives-22-23-pdf.pdf` | 1.00 | 0.64 | word shingles |
| doc051 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_PreReqMnr-CS_Minor-pdf.pdf` | 1.00 | 0.05 | word shingles |
| doc052 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-DP-2016-2017-pdf.pdf` | 0.97 | 0.80 | word shingles |
| doc053 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-DP-2017-2018-pdf.pdf` | 1.00 | 0.96 | exact text match, word shingles |
| doc055 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-DP-2019-2020-pdf.pdf` | 1.00 | 0.89 | exact text match, word shingles |
| doc056 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-DP-2020-2021-pdf.pdf` | 1.00 | 0.96 | exact text match, word shingles |
| doc057 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-FC-2016-2017-pdf.pdf` | 1.00 | 0.83 | word shingles |
| doc059 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-FC-2018-2019-pdf.pdf` | 1.00 | 0.96 | exact text match, word shingles |
| doc060 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-FC-2019-2020-pdf.pdf` | 1.00 | 0.45 | word shingles |
| doc061 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_01_4YEAR-CS-Flow-2023-26a86e39a89c76e7-pdf.pdf` | 1.00 | 0.81 | word shingles |
| doc062 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_01_4YEAR-SE-Flow-2023-8892d09bcf9aa9f1-pdf.pdf` | 1.00 | 0.81 | word shingles |
| doc065 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_01_Options-for-CE-Guided-Electives-2eb90a5dd864a1e7-pdf.pdf` | 1.00 | 0.54 | word shingles |
| doc066 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_01_Options-for-CS-Guided-Electives-23-24-f8f4d618858a2f75-pdf.pdf` | 1.00 | 0.80 | word shingles |
| doc067 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_01_Options-for-SE-Guided-Electives-23-24-b7882bacce3f82fc-pdf.pdf` | 1.00 | 0.64 | word shingles |
| doc068 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_01_SE-Degree-Plan-2023-2024-5cdb81a288d8e7d1-pdf.pdf` | 1.00 | 0.46 | word shingles |
| doc069 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_05_24-25-CE-Math-Technical-Electives-pdf.pdf` | 1.00 | 0.06 | word shingles |
| doc070 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_05_24-25-CE-Technical-Electives-pdf.pdf` | 1.00 | 0.54 | word shingles |
| doc071 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_05_24-25-CS-Technical-Electives-pdf.pdf` | 1.00 | 0.77 | word shingles |
| doc072 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_05_CE-Degree-Plan-24-25-Final-pdf.pdf` | 1.00 | 0.44 | word shingles |
| doc073 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_06_SE-Degree-Plan-24-25-Final-Updated-06102024-pdf.pdf` | 1.00 | 0.45 | word shingles |
| doc074 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_08_CS-PDF-pdf.pdf` | 1.00 | 0.73 | word shingles |
| doc075 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2025_04_CE-Degree-Plan-25-26-pdf.pdf` | 1.00 | 0.44 | word shingles |
| doc076 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2025_04_CS-Degree-Plan-25-26-pdf.pdf` | 1.00 | 0.53 | word shingles |
| doc077 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2025_04_SE-Degree-Plan-25-26-pdf.pdf` | 1.00 | 0.57 | word shingles |
| doc078 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2025_06_4YEAR-CE-2022-Flow-Chart-CORRECTED-pdf.pdf` | 0.98 | 0.78 | word shingles |
| doc079 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2025_06_4YEAR-CE-Flow-Chart-2023-CORRECTED-pdf.pdf` | 0.98 | 0.78 | word shingles |
| doc080 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2025_06_SE-24-25-Flowchart-corrected-pdf.pdf` | 1.00 | 0.71 | word shingles |
| doc081 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2025_06_SE-25-26-Flow-ChartCorrected-pdf.pdf` | 1.00 | 0.71 | word shingles |
| doc082 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2025_07_CE-24-25-Flowchart-Corrected-pdf.pdf` | 1.00 | 0.23 | word shingles |
| doc083 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2025_07_CS-25-26-FlowChart-pdf.pdf` | 1.00 | 0.73 | word shingles |
| doc084 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2026_04_CS-Degree-Plan-26-27-pdf.pdf` | 1.00 | 0.53 | word shingles |
| doc085 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2026_04_SE-26-27-Course-Map-pdf.pdf` | 1.00 | 0.64 | word shingles |
| doc086 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2026_04_SE-Degree-Plan-26-27-pdf.pdf` | 1.00 | 0.57 | word shingles |
| doc087 | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2026_07_CE-Course-Map-26-27-4-pdf.pdf` | 1.00 | 0.23 | word shingles |
| doc088 | `https___osim-utdallas-edu_files_2025_04_BSBARF-Finish-in-Four.pdf` | 1.00 | 0.02 | word shingles |
| doc089 | `https___policy-utdallas-edu_utdbp3051.pdf` | 0.97 | 0.00 | character shingles on a letter-spaced PDF |
| doc090 | `https___policy-utdallas-edu_utdbp3090.pdf` | 1.00 | 0.08 | word shingles |
| doc091 | `https___policy-utdallas-edu_utdbp3102.pdf` | 1.00 | 0.01 | character shingles on a letter-spaced PDF |
| doc092 | `https___policy-utdallas-edu_utdbp3105.pdf` | 1.00 | 0.08 | word shingles |
| doc093 | `https___policy-utdallas-edu_utdpp1009.pdf` | 1.00 | 0.09 | word shingles |
| doc094 | `https___policy-utdallas-edu_utdpp1047.pdf` | 1.00 | 0.02 | character shingles on a letter-spaced PDF |
| doc095 | `https___policy-utdallas-edu_utdpp1056.pdf` | 1.00 | 0.06 | word shingles |
| doc096 | `https___policy-utdallas-edu_utdpp1062.pdf` | 1.00 | 0.04 | word shingles |
| doc097 | `https___policy-utdallas-edu_utdpp1064.pdf` | 1.00 | 0.02 | word shingles |
| doc098 | `https___policy-utdallas-edu_utdpp1095.pdf` | 1.00 | 0.09 | word shingles |
| doc099 | `https___policy-utdallas-edu_utdpp1120.pdf` | 1.00 | 0.05 | word shingles |
| doc100 | `https___policy-utdallas-edu_utdpp1121.pdf` | 1.00 | 0.09 | word shingles |
| doc101 | `https___policy-utdallas-edu_utdpp1124.pdf` | 1.00 | 0.08 | word shingles |
| doc102 | `https___policy-utdallas-edu_utdsp5001.pdf` | 1.00 | 0.02 | word shingles |
| doc103 | `https___policy-utdallas-edu_utdsp5002.pdf` | 1.00 | 0.05 | word shingles |
| doc104 | `https___policy-utdallas-edu_utdsp5003.pdf` | 1.00 | 0.01 | word shingles |
| doc105 | `https___policy-utdallas-edu_utdsp5005.pdf` | 1.00 | 0.07 | word shingles |
| doc106 | `https___policy-utdallas-edu_utdsp5008.pdf` | 1.00 | 0.06 | word shingles |
| doc107 | `https___policy-utdallas-edu_utdsp5010.pdf` | 0.90 | 0.03 | word shingles |
| doc108 | `https___registrar-utdallas-edu_registration_dropping-a-class.pdf` | 1.00 | 0.05 | word shingles |
| doc109 | `https___registrar-utdallas-edu_registration_enrollment-status.pdf` | 0.71 | 0.02 | word shingles |
| doc110 | `https___registrar-utdallas-edu_registration_registering-for-classes.pdf` | 1.00 | 0.06 | word shingles |
| doc111 | `https___registrar-utdallas-edu_registration_registering-for-classes_register-class-number.pdf` | 0.86 | 0.09 | word shingles |
| doc112 | `https___registrar-utdallas-edu_registration_registering-for-classes_search-using-class-attributes.pdf` | 1.00 | 0.15 | word shingles |
| doc113 | `https___registrar-utdallas-edu_registration_schedule-planner_mobile-registration.pdf` | 1.00 | 0.07 | word shingles |
| doc114 | `https___registrar-utdallas-edu_registration_schedule-planner_schedule-planner-guide-for-students.pdf` | 1.00 | 0.13 | word shingles |
| doc115 | `https___registrar-utdallas-edu_registration_schedule-planner_schedule-planner-validation.pdf` | 0.88 | 0.06 | word shingles |
| doc116 | `https___registrar-utdallas-edu_transcripts_official.pdf` | 1.00 | 0.03 | word shingles |
| doc117 | `https___www-utdallas-edu_academics_calendar.pdf` | 1.00 | 0.89 | exact text match, word shingles; PDF shared by 2 docs |
| doc118 | `https___www-utdallas-edu_golden_CGSACN_CGS2010-2012-April6-130pm.pdf` | 0.99 | 0.11 | word shingles; PDF shared by 3 docs |

### Unmatched docs

| doc | title | best candidate | reason |
| --- | --- | --- | --- |
| doc022 | B.S. in Software Engineering Degree Plan (2021-2022 Catalog) | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_21-22-SE-Degree-Plan-pdf.pdf` | ambiguous, runner-up `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-DP-2020-2021-pdf.pdf` scored 0.95 |
| doc025 | BS Computer Engineering Suggested Four Year Plan (2020-2021 Catalog) | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_4YEAR-CE-2020-pdf.pdf` | best score 0.58 is below 0.6 |
| doc030 | BS Software Engineering Suggested Four Year Plan, 2022-2023 Catalog | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_4YEAR-SE-2022-pdf.pdf` | ambiguous, runner-up `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_01_4YEAR-SE-Flow-2023-8892d09bcf9aa9f1-pdf.pdf` scored 0.78 |
| doc031 | B.S. in Computer Engineering Degree Plan, 2016-2018 Catalog | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CE-DP-2016-2017-pdf.pdf` | ambiguous, runner-up `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CE-DP-2018-2019-pdf.pdf` scored 0.75 |
| doc040 | B.S. in Computer Science Degree Plan (2018-2019 Catalog) | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CS-DP-2018-2019-pdf.pdf` | ambiguous, runner-up `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CS-DP-2017-2018-pdf.pdf` scored 0.94 |
| doc044 | BS Computer Science Suggested Four Year Plan (2017-2018 Catalog) | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CS-FC-2017-2018-pdf.pdf` | ambiguous, runner-up `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CS-FC-2018-2019-pdf.pdf` scored 0.94 |
| doc046 | BS Computer Science Suggested Four Year Plan (2020-2021 Catalog) | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_CS-FC-2020-2021-pdf.pdf` | best score 0.57 is below 0.6 |
| doc054 | B.S. in Software Engineering Degree Plan (2018-2019 Catalog) | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-DP-2018-2019-pdf.pdf` | ambiguous, runner-up `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-DP-2017-2018-pdf.pdf` scored 0.94 |
| doc058 | BS Software Engineering Suggested Four Year Plan (2017-2018 Catalog) | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-FC-2017-2018-pdf.pdf` | ambiguous, runner-up `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_SE-FC-2018-2019-pdf.pdf` scored 0.94 |
| doc063 | B.S. in Computer Engineering Degree Plan (2023-2024 Catalog) | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_01_CE-Degree-Plan-c6dc21d255b641ac-pdf.pdf` | ambiguous, runner-up `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2023_07_22-23-CE-Degree-Plan-pdf.pdf` scored 0.66 |
| doc064 | B.S. in COMPUTER SCIENCE (2023-2024 Catalog) | `https___engineering-utdallas-edu_https___engineering-utdallas-edu_files_2024_01_CS-Degree-Plan-23-24-39ec537c1014b856-pdf.pdf` | best score 0.36 is below 0.6 |

## Corpus cleanup (docs 119 to 198)

Docs 119 onward came from the automatic splitter in `add_documents.py`. Docs 001 to 118
are hand-chunked and were not touched; `fix_chunks.py` refuses any range below doc119.

### Audit

`audit_corpus.py` flags, for any doc range:

| issue | rule |
| --- | --- |
| short / long | under 15 or over 250 words |
| navigation | mostly capitalized menu words with almost no sentences |
| duplicate / near_duplicate | identical normalized text, or 80% shingle overlap |
| odd_characters | private-use glyphs, replacement characters, letter-spaced text |
| page_furniture | site footers, cookie or chatbot text, print headers, calls to action |
| missing_title / bad_title | empty title, breadcrumb title (`A > B`), or a cut-off title |
| missing_heading | empty section heading |

### Cleanup decisions

- Titles: breadcrumb titles such as `UT Dallas > Office of Financial Aid > Aid
  Programs` were replaced with one readable title per doc (the `TITLES` table).
- Furniture: the chatbot greeting, table widget text ("Showing 1 to 5 of 5 entries"),
  "Updated:" build stamps, all-caps calls to action, icon glyphs, social media widgets
  and fixed footer menus are removed. Footer phrases are only removed as a run that
  also contains a footer marker (privacy policy, copyright, "Related Pages"), so a
  mailing address inside real content survives.
- Headings: site chrome headings and broken headings (table rows, dates, phone numbers,
  cut-off phrases) are folded back into the text, and the chunk inherits the previous
  good heading.
- Repeated sentences inside one doc are removed, except questions, so FAQ lists stay.
- Fragments under 30 words are merged into a neighbor (capped at 250 words); chunks
  that are pure navigation or letter-spaced garbage are dropped, but a doc never loses
  its last chunk.
- Merged chunks keep the first chunk id. No question references a chunk id; evidence
  is matched by doc id and phrases.
- `fill_chunk_counts.process` reruns on every changed file. The script is idempotent
  (a second run changes nothing, which a test checks).

Left as is on purpose: the course catalog index page (doc120) reads like navigation
but is the content; doc121 and doc122 share accreditation and inclusion boilerplate
because both catalogs print it; contact lines with the campus address are useful
answers, not furniture. Some P6 pages have words glued together by the PDF extractor
("deadlinereceive"); that is in the source text and was not rewritten.

### Counts before and after

| | main before Task 4 | after cleanup (P2) | after new docs (P6) |
| --- | --- | --- | --- |
| documents | 169 | 169 | 198 |
| chunks, whole corpus | 2,907 | 2,879 | 3,003 |
| chunks, docs 119 to 169 | 275 | 247 | 247 |
| audit flags, docs 119 to 169 | 250 | 10 | 10 |
| chunks, docs 170 to 198 | | | 124 (141 before cleanup) |
| audit flags, docs 170 to 198 | | | 15 (92 before cleanup) |
| audit flags, whole corpus | 857 | 616 | 631 |

Cleanup on docs 119 to 169: 256 titles fixed, 80 chunks with furniture stripped, 68
headings repaired, 34 repeated sentences removed, 14 fragments merged, 6 navigation
chunks and 1 letter-spaced chunk dropped. Most remaining whole-corpus flags are in the
hand-chunked docs 001 to 118 (short degree plan rows, the duplicated graduate catalog
docs), which this task must not change.

### New documents (P6)

Of the 64 raw PDFs with no doc, 29 were added as doc170 to doc198 with
`python add_documents.py`, then cleaned with `fix_chunks.py` and registered:
University Career Center (12twenty, career fairs, Comet Treks, international
students), advising (Jindal, Interdisciplinary Studies, Exploratory, Undergraduate
Education, Jonsson, Bass, NSM, BBS, EPPS), Student Success Center (coaching, peer
tutoring, supplemental instruction, writing center, home), scholarships (freshman,
transfer, costs and aid), Financial Aid home, Comet Promise, McDermott Library, Testing
Center, Student Union, University Housing, Housing Availability, University Recreation.

Skipped (35):

- Near-duplicates of existing docs (70% or more of their shingles already in the
  corpus): the 2026-2027 undergraduate catalog page, Registrar academic advising,
  academic calendar, Financial Aid contact page, course catalogs index.
- The 14 remaining engineering degree plans and flow charts: older or alternate
  versions of plans already in the corpus (they are the candidates of the 11
  unmatched docs).
- Generic or list content that would crowd out policy answers: Career Readiness Guide
  (10,500 words), What Can I Do With This Major, Networking, degree program lists
  (undergraduate and graduate).
- Pages for other audiences or with little lasting content: Post Jobs and Internships
  (employers), Student Organizations (career center), Student Academic Resources (link
  hub), Community Standards landing page (the policies are already docs 012 to 015),
  Dine On Campus (menus), Gaming and Esports, Athletics, UT Dallas Culture, Student
  Spaces, the Summer 2025 orientation slide deck.
- `sample.pdf` (no text).

## Benchmark questions for the new documents

40 questions with ids prefixed `data-` were appended to `evaluate/questions.json`
under a `// Data questions (Task 4)` comment. No existing entry was changed.

- 20 dev and 20 test; each split has 15 answerable and 5 unanswerable (25%).
- Topics: Bursar deadlines, final exams, graduation application, three-repeat rule,
  six-withdrawal rule, excessive hours and tuition rebate, meningitis vaccine,
  notarization and transcripts, FERPA, auditing, concurrent enrollment, AP credit,
  financial aid forms, disbursement and scholarships, residency, orientation, Galaxy,
  admissions facts.
- Multi-evidence: 5 in dev and 2 in test (one spans two documents).
- Unanswerable questions ask for personal records (balances, decisions, offers),
  future terms or charts that are not published (Spring 2031 exams, a 2031-2032 AP
  chart), or data the pages never give (parking permit prices, rebate totals, staff
  schedules). Each has an `unanswerable_reason`.
- Every evidence group was checked against the whole corpus. Where the same text
  appears in another doc, the group uses `doc_ids` (rebate text in doc135 and doc166,
  audit rules in doc133 and doc142, the cross-listed rule in doc007 and doc136, EDI in
  doc116 and doc150).
- Drafts that overlapped existing questions were replaced (meningitis proof timing,
  FERPA complaint window, six-drop exemptions, third-attempt tuition, exam credit on
  another transcript, a personal withdrawal count), so dev and test do not leak.
- New category `policy_lookup` marks single-fact lookups; the other categories reuse
  the existing names.

## Scores

Retrieval leaderboard with `evaluate/config.example.json` (tuned on dev only; the test
split was only run to check the 1 point guard and report the result):

| stage | dev, all | test, all | dev, original 82 | test, original 82 |
| --- | --- | --- | --- | --- |
| main before Task 4 | 45.84 | 53.18 | 45.84 | 53.18 |
| after cleanup (P2) | 46.76 | 53.14 | 46.76 | 53.14 |
| after new questions (P3) | 51.36 | 55.84 | 46.76 | 53.14 |
| after new documents (P6) | 51.31 | 55.76 | 46.70 | 53.06 |

On the 20 `data-` questions per split, complete evidence is 0.867 in both splits
(leaderboard 70.38 dev, 66.92 test). Abstention is still 0 for the baseline retriever,
which never returns an empty result.

## End-to-end evaluation

`scripts/eval_e2e.py --split dev|test [--limit N] [--json out.json] [--top-k K] [--fallback]`
runs each question through `backend.app.retrieval.retrieve` and
`backend.app.generation.generate_answer`. If either module is missing (or `--fallback`
is set) it uses the evaluator's lexical `Retriever` and a small extractive picker (the
two passage sentences that share the most key terms with the question, cited as `[n]`).
It reports, per question and in total:

- retrieval metrics from `evaluate_chunks.grade` (recall, complete evidence, precision,
  retrieval abstention) and the same leaderboard score;
- answer abstention accuracy: abstained exactly when the question is unanswerable;
- citation validity: the answer has at least one `[n]` and every `[n]` maps to a
  citation whose chunk was retrieved (no orphans);
- citation support: share of cited sentences where at least half of the sentence's key
  terms appear in a cited passage;
- answer length in words, and retrieval, generation and total latency.

Fallback run on the final corpus (no backend modules merged yet):

| metric | dev | test |
| --- | --- | --- |
| retrieval leaderboard score | 51.31 | 55.76 |
| complete evidence | 0.571 | 0.636 |
| answer abstention accuracy | 0.755 | 0.755 |
| abstained when unanswerable | 0.000 | 0.000 |
| citation validity | 1.000 | 1.000 |
| citation support | 1.000 | 1.000 |
| mean answer words | 68.6 | 68.9 |
| latency p50 / p95 ms | 33.2 / 39.5 | 33.1 / 40.3 |

Citation numbers are trivially perfect for the extractive picker because it copies
sentences; they become meaningful once Task 2's generator is merged. Rerun after Tasks 1
to 3 merge and update `README.md`.
