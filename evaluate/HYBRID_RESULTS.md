# Balanced hybrid retrieval: results and limits

**The 90–95 target has not been reached across all groups.** The balanced configuration improves the weaker sets, but the hard repository benchmark remains substantially below the target. All scores below use the unchanged reference evidence and weighted leaderboard.

| Test set | Balanced score |
| --- | ---: |
| Starter test (10) | 83.59 |
| Realistic test (9) | 87.14 |
| Audit (15) | 96.14 |
| Repository hard test (32) | 58.51 |

## Realistic requests by difficulty

| Difficulty | Complete evidence |
| --- | ---: |
| easy | 2/2 |
| medium | 1/1 |
| hard | 3/4 |

These difficulty rows report complete-evidence counts, not the weighted leaderboard. Small groups make percentages unstable; one hard miss changes that group by 25 percentage points.

## Implementation

- Added local semantic candidate retrieval with all-MiniLM-L6-v2 and MS MARCO MiniLM cross-encoder passage reranking, using already cached ONNX models.
- Combined semantic scores with lexical/metadata coverage and clause-aware retrieval. Additional passages must still respect the 900 estimated-token budget and three-chunk per-document cap.
- Added a private-record detector trained only on development question labels, with five-fold stratified calibration, explicit public/procedural safeguards, and frozen coefficients for unseen queries.
- Selected one balanced setting by the lowest development-suite score, then average development score. All test results are reported; the audit has no development split and did not select settings.
- No question IDs, reference phrases or document relevance labels enter passage retrieval. Answerability training uses only the dev unanswerable flag.

## Evidence and limitations

The starter, realistic and audit suites retain the earlier 1,028-chunk Lokesh corpus in evaluate/exports/previous-lokesh. The repository hard suite uses the current 2,632 chunks from 118 files in backend/data/chunks. Scores are separate evaluations, not one pooled estimate. Reference labels and chunk contents were not edited to improve scores.

All hard benchmark questions were checked for reference-evidence feasibility within 900 tokens and up to six passages; none were intrinsically infeasible. The remaining losses therefore cannot be dismissed as merely an impossible token limit. They include incomplete multi-part evidence and unsupported personal facts that the answerability detector still accepts.

The small earlier test sets have already been inspected in this chat and are regression checks, not untouched generalization benchmarks. Questions are author-written rather than authentic student logs. The local WordPiece implementation targets these cached English uncased BERT tokenizer specifications; multilingual/special-token parity has not been established. Models encode at most 256 tokens per candidate representation and rerank up to 512 combined tokens, which can miss facts deep in long passages.

A separate configuration emphasizing the earlier suites is retained under runs/hybrid-final (87.19 starter, 87.86 realistic, 92.27 audit, 41.81 hard test). It was not chosen as the balanced recommendation because its weakest development-suite result was lower. Keeping several profiles does not establish that any profile reaches 90 everywhere.

## Run a new question

This machine has a working Python 3.10 installation with NumPy and ONNX Runtime. The bundled Python used earlier lacks ONNX Runtime. The model snapshots are read from the local Hugging Face cache; no model download or API call was made.

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe" evaluate/query_hybrid.py --query "I am a graduate student. How do I drop a class before Census Day?"
```

The CLI loads hybrid.config.json and hybrid.detector.json, evaluates new questions without fitting on reference labels, and returns candidate evidence or an abstention reason. It does not generate a final answer or perform university account actions. Neural inference is slower than the earlier lexical-only exercise; cached features speed repeated evaluation.

## Checks and artifacts

- Eight semantic and seven hybrid tests pass (15 new tests). A catalog-scope filtering experiment was rejected because it lowered the hard development result; policies in one catalog can also apply to students at other levels. Its separate diagnostic results are retained under runs/hybrid-balanced-scoped.
- The existing full evaluator suite still fails with the existing config.example.json (four failures and one error, including corpus-feasibility checks and synthetic retrieval cases). The 40-word maximum filter and strict threshold affect those tests. Existing config, evaluator, tests and search edits were left intact; no claim is made that the full repo test suite is green.
- Frozen settings: hybrid.config.json; answerability coefficients/calibration: hybrid.detector.json.
- Full evidence per question: runs/hybrid-balanced/results.json.
- Model-only comparisons: runs/semantic-student/results.json and runs/semantic-hard/results.json.
- Earlier and focused hybrid profiles and all dev settings comparisons remain under runs/.

## Hard-test misses

- test-hard-transfer-gpa-and-record: Does accepted coursework from another college enter the UT Dallas GPA, and can undergraduate and graduate history be requested as separate official transcripts under the notation policy?
- test-hard-retention-versus-school: I am in poor academic standing and already have a school advisor. Is the retention-office advising optional for me, and how does that differ from a student in good standing?
- test-hard-exam-credit-proof: I have examination credit on another colleges transcript and am approaching my graduating term. What is the petition cutoff, and what evidence must come from the testing organization instead?
- test-hard-core-cr-restriction: I want to take a normally letter-graded core requirement without a letter grade and later repeat a previously letter-graded class that way. Explain both restrictions and the minimum performance needed to earn CR in an eligible course.
- test-hard-parent-early-registration: I am parenting a child and want an earlier enrollment slot. What eligibility caveat does the registration page give, and which self-identification step should I complete to determine eligibility?
- test-hard-graduate-after-census: A graduate student wants to leave a course after census but before the withdrawal deadline. What submission routes are listed, and how should the student check that the change actually happened?
- test-hard-appeal-panel-endpoint: After the department rejects my academic appeal under UTDSP5005, how quickly must I approach the school dean, how long does the panel have to respond while classes meet, and is its recommendation appealable under that policy?
- test-hard-retaliation-oral-vs-appeal: Under the suspected-unlawful-activity policy, will an anonymous oral allegation count as a retaliation complaint? If an investigation is declined, what form and deadline apply to appealing that decision?
- test-hard-youth-work-limits: Using the pay-administration text, compare the job restrictions for a sixteen-year-old with the school-week and summer-evening limits for a fifteen-year-old.
- test-hard-ce-two-designs: In the 2024-2025 computer engineering plan, identify both senior design course numbers and give the technical elective lab hours. Retrieve the second project too, even though it is split from the first.
- test-hard-se-intro-year-change: Compare the introductory two-credit course in the software engineering plans for 2024-2025 and 2026-2027. Give its title and code for each year, rather than pulling a neighboring CS plan.
- test-hard-faculty-versus-student-route: Distinguish a faculty members academic-freedom grievance route from a students challenge to an academic decision: what faculty committee or policy is named, and what must the student first attempt under UTDSP5005?
- test-hard-my-aid: If I withdraw from my current class today, exactly how many dollars of my financial aid will I have to repay?
- test-hard-my-panel-outcome: What did the academic appeals panel decide about the grievance I submitted last month?
- test-hard-my-transfer-map: Will the unspecified course on my old colleges transcript satisfy the major requirement I still need?
- test-hard-unpublished-se: For the 2035-2036 software engineering plan, give the required introductory course number and its minimum passing grade.
