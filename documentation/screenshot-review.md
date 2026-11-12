# November 10 screenshot review

The review covered 44 PNGs in folders 1 through 4. Folders 1 and 3 were ordered by the capture times in their filenames. Folder 2 uses its numeric prefixes. Folder 4 starts with the unnumbered image, followed by 1 through 9, consistent with file metadata. The embedded PNG metadata has no usable capture timestamp. Folder 4 images 2 and 3 are byte-identical.

## 1. General campus questions

| Capture time | Request and observed failure |
| --- | --- |
| 2:13:52 | AP Calculus BC score of 4. The excerpt shows the wrong exam row. |
| 2:14:39 | 15-hour tuition estimate. The answer describes a tuition rebate instead of estimating charges. |
| 2:15:00 | Fall break, then explicit Fall 2026. A schedule-planner availability break was mistaken for an academic-calendar break. |
| 2:15:22 | Spring 2027 graduation date. The answer gives the general ceremony schedule without a specific date. |
| 2:15:32 | Transcript ordering. The answer includes the Orion route but foregrounds hold material from an unofficial transcript section. |
| 2:15:40 | Class waitlist. The answer describes registration with a class number. |
| 2:15:48 | Paying tuition. The answer quotes employee payroll policy. |
| 2:16:00 | One-course withdrawal across transcript, aid, tuition and graduation. The answer mixes financial aid application and repeat-course guidance and leaves most parts unanswered. |
| 2:16:12 | Academic dishonesty allegation and appeal. A course syllabus definition takes the place of an institutional procedure. The screenshot also shows the separate off-campus employment chat in the header. |
| 2:16:21 | Registration hold. The app refuses instead of explaining how to identify the hold in Orion and contact the listed department. |
| 2:17:14 | Accommodation not followed. The app refuses even though a public grievance procedure can be indexed. |

## 2. Policy and academic support

| File | Request and observed failure |
| --- | --- |
| 01-chat1.png | Post-census grade and six-drop count. It finds a W/WL excerpt and an exception but mixes pre-census instructions into the response. |
| 02-chat1.png | Six-drop follow-up about attendance before Fall 2007 and exemptions. The answer quotes the policy's start date and conditions but does not clearly resolve the hypothetical. |
| 03-chat1.png | Three-course repeat and higher tuition. The answer repeats a title without stating the rule or penalty. |
| 04-chat2.png | Complete withdrawal and aid repayment. The app refuses a public policy question that can be answered conditionally. |
| 05-chat2.png | Financial-aid academic progress and remedies. The response includes unrelated application timing and does not clearly explain the standards and appeal. |
| 06-chat2.png | FAFSA verification forms. The answer refuses even though the office publishes examples and a way to check the student's requested documents. |
| 07-chat3.png | Calculus BC and Physics C Mechanics scores. Flattened table rows cross exam and score boundaries. |
| 08-chat3.png | IB and A-level credit and score submission. The response finds submission guidance but provides limited evidence for each exam type. |
| 09-chat3.png | Texas residency for tuition. The answer quotes a first-person FAQ fragment and broad classification language. |
| 10-chat4.png | Peer tutoring versus Supplemental Instruction. The response repeats a tutoring FAQ question and omits the comparison. |

## 3. Dates, populations and follow-ups

| Capture time | Request and observed failure |
| --- | --- |
| 4:55:02 | Number of CS students. The refusal is appropriate without program-level enrollment data. |
| 4:55:19 | Number of those students currently taking physics. This requires a current intersection of two enrollment groups. A previous answer cannot provide that data. |
| 4:56:41 | Fall 2026 withdrawal deadline and the start of the first-session follow-up. The main question is refused despite an indexed calendar. |
| 4:56:49 | First eight-week session. The response mixes first and second session registration dates and long-semester policy. |
| 4:57:03 | Second eight-week session. The response lists exam and registration dates instead of the requested withdrawal deadline. |
| 4:57:19 | Undergraduate academic standing GPA. The response gives broad academic support and transfer admissions material. |
| 4:57:29 | Graduate GPA follow-up. The answer repeats the earlier population mismatch. |
| 4:57:39 | Graduate F-1 online credit. The relevant excerpt addresses how courses count toward full-time enrollment. It should remain specific to the cited population and enrollment conditions. |
| 4:57:54 | CS elective totals across 2026–27 and 2025–26. The answer mixes an older catalog with a course map and omits the totals. |
| 4:58:04 | Auditing CS 3345. A generic refusal misses the published restriction on auditing CS courses. |
| 4:58:16 | Complete withdrawal and six-drop count. The answer refuses instead of checking the complete-withdrawal exception. |
| 4:58:27 | Four-year CS graduation rate. A four-year course plan is not an outcome statistic. A university-wide rate does not establish the CS rate either. |
| 4:58:36 | Master's in CS credit total. An unrelated fast-track program and registration guide are cited. |

## 4. Academic planning and personal data

| File | Request and observed failure |
| --- | --- |
| image.png | Undergraduate semester credit limit. Enrollment status and independent-study percentages are not the course overload limit. |
| 1image.png | Can the student graduate on time with the listed courses? A degree audit and remaining requirements are missing. |
| 2image.png | Exact credits next semester to graduate on time. The current courses alone are insufficient. |
| 3image.png | Byte-identical to 2image.png. |
| 4image.png | Switch from CS to Finance and graduate on time. The answer substitutes graduate enrollment rules for an individual degree audit. |
| 5image.png | Worst-case completion timeline after the major switch. Public policies do not establish an individual timeline. |
| 6image.png | Incoming CS student's year-by-year schedule. The response blends different catalog years and supplies headings instead of a schedule. |
| 7image.png | Gap year after the freshman planning question. The response quotes graduate dissertation continuous enrollment. |
| 8image.png | CS study-abroad options. The answer cites a conduct-policy mention and unrelated financial aid. |
| 9image.png | Tuition cost. The response lists cost factors but stops before the official tuition estimate workflow. |

## Regression coverage and source changes

The backend suite replays 33 supported and unsupported questions derived from
these screenshots. It checks relevant answer facts, common distractions,
citation membership and abstention. The cases are regression checks authored
after seeing the screenshots. They do not measure generalization.

The verified web-source manifest records the official URL and review date for
each new short summary. The AP notes preserve exam/score association from the
official table. Four existing CS degree-plan chunks now include readable
elective totals from their own rows, with original text and IDs retained.
These summaries are snapshots. The system still needs current documents for
real-time schedules, policy updates and any newly published dates.

Remaining gaps include full multi-office withdrawal guidance, a complete
academic dishonesty appeal walkthrough, separate IB and A-level credit
requirements, residency eligibility, and personalized
degree planning. The current corpus cannot supply private records, live
enrollment intersections, or a student's individual graduation timeline.


## Benchmark after the changes

The shared benchmark questions, reference evidence, and scoring formulas are
unchanged. We used development runs to compare candidate strategies, then
replayed the existing test split. The test questions have been inspected in
earlier work and during regression diagnosis, so these results measure
regression performance.

| Retrieval metric | Previous dev | Updated dev | Previous test | Updated test |
| --- | ---: | ---: | ---: | ---: |
| Weighted score out of 100 | 61.06 | 65.61 | 59.69 | 67.73 |
| Evidence recall | 71.4% | 72.4% | 75.9% | 75.2% |
| Complete evidence | 58.4% | 58.4% | 61.0% | 59.7% |
| Context precision | 45.0% | 46.0% | 53.3% | 52.1% |
| Correct abstention | 72.0% | 100% | 40.0% | 100% |

| Test category | Count | Applicable result |
| --- | ---: | ---: |
| Policy lookup | 9 | 88.9% complete evidence |
| Policy exceptions | 25 | 68.0% complete evidence |
| Multi-evidence | 30 | 63.3% complete evidence |
| Multi-document | 9 | 22.2% complete evidence |
| Catalog comparison | 4 | 0% complete evidence |
| Private data | 14 | 100% correct abstention |
| Missing context | 7 | 100% correct abstention |
| Unavailable version | 4 | 100% correct abstention |

The extractive end-to-end test answered 69 of 77 answerable questions and
abstained on all 25 unanswerable questions. Citation validity and support were
100% under the evaluator's checks. This measures citation behavior and answer
availability. It does not score factual correctness or completeness for every
claim. The 80-90 target across all sections remains open, especially for
multi-document evidence and catalog comparisons.

```powershell
py -m pytest backend/tests/test_screenshot_regressions.py -q
py scripts/eval_retrieval.py --split dev
py scripts/eval_retrieval.py --split test
$env:LLM_PROVIDER='extractive'
py scripts/eval_e2e.py --split test
```
