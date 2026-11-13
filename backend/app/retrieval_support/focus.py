"""Question intent signals shared by retrieval and the extractive reader."""
from __future__ import annotations

import re
from dataclasses import dataclass

MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
DATE = rf"\b{MONTH}\.?\s+\d{{1,2}}\b"
DROP_OUTCOME = re.compile(
    r"\b(?:what happens\s*if|when (?:can|may|is it (?:ok|okay|allowed) to)|"
    r"what are the consequences (?:of|if))\b[^?!.]*"
    r"\b(?:drop(?:ping)?[^?!.]*\b(?:class(?:es)?|courses?|it)|withdraw\w*)\b",
    re.I,
)
_YEAR_RANGE = re.compile(r"\b((?:19|20)\d{2})\s*[-\u2013\u2014]\s*(\d{2})\b")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")
_MONTH_END = re.compile(rf"\b{MONTH}\.$", re.I)


def normalize_years(text: str) -> str:
    """Expand consecutive abbreviated catalog years while retaining other ranges."""
    def expand(match: re.Match) -> str:
        year = int(match[1])
        return f"{year}-{year + 1}" if (year + 1) % 100 == int(match[2]) else match[0]

    return _YEAR_RANGE.sub(expand, text)


def evidence_sentences(text: str) -> list[str]:
    """Keep abbreviated calendar dates in one extract."""
    start = 0
    sentences = []
    for match in _SENTENCE_BOUNDARY.finditer(text):
        if text[match.end()].isdigit() and _MONTH_END.search(text[:match.start()]):
            continue
        sentences.append(text[start:match.start()])
        start = match.end()
    return [*sentences, text[start:]]


@dataclass(frozen=True)
class Focus:
    name: str
    question: re.Pattern[str]
    topic: re.Pattern[str]
    fact: re.Pattern[str]

    def supports(self, text: str, heading: str = "") -> bool:
        if self.name in DATE_FOCUSES:
            return any(self.topic.search(sentence) and self.fact.search(sentence)
                       for sentence in evidence_sentences(text))
        return bool(self.topic.search(text + " " + heading) and self.fact.search(text))


def _focus(name: str, question: str, topic: str, fact: str) -> Focus:
    return Focus(name, *(re.compile(pattern, re.I | re.S) for pattern in (question, topic, fact)))


# Fact shapes use policy vocabulary. The values and dates themselves come from passages.
FOCUSES = (
    _focus("fall break", r"\b(?:when|what (?:day|date)|start|begin)\b.*\bfall break\b|\bfall break\b.*\b(?:when|start|begin)\b",
           r"\bfall break\b", DATE),
    _focus("degree conferral date", r"\b(?:when|what (?:day|date))\b.*\b(?:conferral|graduation|graduate)\b(?!.*\b(?:ceremon\w*|commencement|application|deadline)\b)",
           r"\bdegree conferral date\b", DATE),
    _focus("graduation ceremony date", r"\b(?:when|what (?:day|date))\b.*\b(?:commencement|graduation|graduation ceremony)\b",
           r"\b(?:commencement|graduation ceremon\w*)\b", DATE),
    _focus("withdrawal deadline", r"\b(?:when|what (?:day|date)|last day|deadline)\b.*\bwithdraw\w*\b|\bwithdrawal (?:period|deadline)\b.*\b(?:end|when|date)\b",
           r"\b(?:withdrawal period|withdrawal deadline|last day to withdraw)\b", DATE),
    _focus("class drop timing and consequences", DROP_OUTCOME.pattern,
           r"\b(?:dropp?\w*|withdraw\w*)\b",
           r"\b(?:census day|withdrawal deadline|last day to (?:drop|withdraw)|"
           r"(?:appear|recorded|reflected) on (?:the |a |your |their )?(?:student.s )?transcript|"
           r"(?:grade|notation) of [\"'“]?W\b|six[- ]drop limit)\b"),
    _focus("tuition payment", r"\b(?:pay|payment)\b.{0,36}\b(?:tuition|bursar bill)\b|\btuition\s+payment\b",
           r"\b(?:tuition|bursar|ezpay)\b", r"\b(?:ezpay|echeck|payment methods?|credit card|payment plans?|flywire)\b"),
    _focus("tuition estimate", r"\btuition\b.*\b(?:estimate|cost)\b|\b(?:estimate|cost)\b.*\btuition\b",
           r"\b(?:tuition|cost of attendance)\b",
           r"\b(?:tuition (?:calculator|estimate|is based)|cost of attendance|rate plan|tuition rates)\b"),
    _focus("accommodation complaint", r"\b(?:accommodation|disability)\b.*\b(?:complaint|grievance|not being followed|isn.t being followed|not implemented)\b",
           r"\b(?:accommodation|disability)\b", r"\b(?:grievance|accessability|ada coordinator|informal resolution)\b"),
    _focus("FAFSA verification", r"\b(?:fafsa|financial aid)\b.*\bverification\b|\bverification\b.*\bfafsa\b",
           r"\b(?:verification|fafsa)\b", r"\b(?:tax information|verification worksheets?|proof of high school|financial aid uploader|to do list)\b"),
    _focus("off-campus work authorization", r"\b(?:work|employment)\b.{0,30}\boff[- ]campus\b|\boff[- ]campus\b.{0,30}\b(?:work|employment)\b",
           r"\b(?:f[- ]?1|isso|off[- ]campus employment)\b", r"\b(?:work authorization|curricular practical training|optional practical training)\b"),
    _focus("transcript ordering", r"\b(?:how|where)\b.*\b(?:request|order|get)\b.*\btranscript\b",
           r"\btranscripts?\b", r"\b(?:my academics|order official transcript|parchment|utd student center)\b"),
    _focus("course audit", r"\b(?:can|how|could|eligible|may)\b.*\baudit\b",
           r"\b(?:audit|auditing)\b", r"\b(?:cannot be audited|eligible course|instructor approval|without earning credit)\b"),
    _focus("registration holds", r"\bregistration hold\b|\b(?:find|check|resolve|remove|release)\b.{0,35}\bholds?\b",
           r"\b(?:registration holds?|orion|student center)\b", r"\b(?:tasks tile|department|academic advisor|office that placed)\b"),
    _focus("waitlist instructions", r"\b(?:how|steps?)\b.*\bwait\s*list\w*\b",
           r"\bwait\s*list\w*\b", r"\b(?:orion|schedule planner|shopping cart|select|edit|add|allow|enable|check)\b"),
    _focus("complete withdrawal and six-drop limit",
           r"\b(?:withdraw\w*|dropp?\w*)\b.*\ball\b.*\b(?:six|6)\b",
           r"\b(?:complete withdrawal|all classes|all courses)\b",
           r"\b(?:excludes?|does not count|not count|exempt|not included)\b"),
    _focus("three course repeat", r"\b(?:three|3)[ -]course repeat\b|\b(?:third|3rd)\s+(?:attempt|time)\b",
           r"\b(?:three[ -]course repeat|third time|third attempt)\b", r"\b(?:penalty|tuition|attempts?|charge\w*)\b"),
    _focus("undergraduate course load limit",
           r"\b(?:max(?:imum)?|allowed|limit|at most)\b.*\b(?:credit hours|course load|undergraduate)\b|"
           r"\b(?:credit hours|course load)\b.*\b(?:allowed|maximum|limit)\b",
           r"\b(?:course load|long semester|enroll|register|overloads?)\b",
           r"\b(?:max(?:imum)?|may not (?:take|enroll)|more than|up to|no more than|exceed)\b.{0,60}\b\d+\s+(?:semester\s+)?(?:credit\s+)?hours\b|\b\d+\s+(?:semester\s+)?(?:credit\s+)?hours\b.{0,32}\b(?:maximum|limit)\b"),
    _focus("academic standing GPA", r"\b(?:gpa|grade point average)\b.*\b(?:academic standing|good standing)\b|\b(?:academic standing|good standing)\b.*\b(?:gpa|grade point average)\b",
           r"\b(?:academic standing|academic probation|scholastic (?:status|progress)|academic status)\b",
           r"\b\d\.\d+\b.{0,50}\b(?:gpa|grade point average)\b|\b(?:gpa|grade point average)\b.{0,50}\b\d\.\d+\b"),
    _focus("dining venue hours", r"\b(?:what time|when|hours)\b.*\b(?:dining hall|dining venue)\b",
           r"\b(?:dining hall|dining venue|dining hours)\b",
           r"\b(?:open|close|hours)\b.{0,55}\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)\b"),
    _focus("institutional totals", r"\btotal amount\b.*\b(?:paid|awarded|disbursed|distributed)\b",
           r"\b(?:annual report|aggregate|total amount|total disbursed)\b", r"\$\s*\d[\d,]*"),
    _focus("parking permit price", r"\bparking permit\b.*\b(?:cost|price|fee)\b|\b(?:cost|price|fee)\b.*\bparking permit\b",
           r"\bparking permit\b", r"\$\s*\d+"),
    _focus("honors GPA cutoff", r"\b(?:gpa|grade point average)\b.*\b(?:summa|magna|cum laude)\b",
           r"\b(?:summa|magna|cum laude)\b", r"\b[234]\.\d{1,3}\b"),
    _focus("graduation rate", r"\bgraduation rate\b", r"\bgraduation rate\b", r"\b\d+(?:\.\d+)?\s*(?:%|percent\b)"),
    _focus("current enrollment statistics", r"\b(?:how many|number of)\b.*\b(?:computer science students|students taking|are taking|students (?:are )?enrolled)\b",
           r"\b(?:enrollment|headcount|enrolled)\b", r"\b\d[\d,]*\s+(?:computer science\s+)?students\b"),
    _focus("gap year and admission deferment", r"\b(?:gap year|defer (?:my |undergraduate )?admission)\b",
           r"\b(?:gap year|deferment|defer undergraduate admission)\b", r"\b(?:freshm[ae]n|admitted|admission)\b"),
    _focus("tutoring comparison", r"(?=.*\bpeer tutoring\b)(?=.*\bsupplemental instruction\b)",
           r"\b(?:peer tutoring|supplemental instruction)\b", r"\b(?:study sessions|tutoring for|drop-in)\b"),
    _focus("study abroad", r"\bstudy abroad\b", r"\b(?:study abroad|education abroad)\b",
           r"\b(?:exchange|programs?|destinations?|apply|application|partners?|study abroad opportunities)\b"),
    _focus("degree credit total", r"\bhow many\b.*\bcredit hours\b.*\b(?:master|ms\b|degree)\w*",
           r"\b(?:master(?:'s)?|degree requirements|degree plan)\b",
           r"\b(?:minimum|total|requires?|degree requirements)\b.{0,55}\b\d+\s+(?:semester\s+)?credit hours\b|\b\d+\s+(?:semester\s+)?credit hours\b.{0,25}\bminimum\b"),
)


def focus_for(question: str) -> Focus | None:
    """A focused fact check applies to a single request, not an entire comparison."""
    focus = next((item for item in FOCUSES if item.question.search(question)), None)
    if focus and focus.name in {"accommodation complaint", "registration holds", "tutoring comparison"}:
        return focus
    if re.search(r"\b(?:contrast|compare|versus)\b|\band\s+(?:how|what|when|which|does|can)\b", question, re.I):
        return None
    return focus


def session_scope(question: str) -> str | None:
    if re.search(r"\bfirst\s+8[- ]week\b", question, re.I):
        return "first"
    if re.search(r"\bsecond\s+8[- ]week\b", question, re.I):
        return "second"
    if re.search(r"\bfull[- ]term\b", question, re.I):
        return "full"
    return None


def title_matches_scope(question: str, title: str, section: str) -> bool:
    """Require session-specific evidence to come from that session's section."""
    scope = session_scope(question)
    if not scope:
        return True
    pattern = r"\bfull[- ]term\b" if scope == "full" else rf"\b{scope}\s+8[- ]week\b"
    return bool(re.search(pattern, title + " " + section, re.I))


DATE_FOCUSES = frozenset({"fall break", "degree conferral date", "graduation ceremony date", "withdrawal deadline"})
WITHDRAWAL_DATE = re.compile(rf"\b(?:withdrawal period ends|withdrawal deadline is|last day to withdraw is)\s+{DATE}", re.I)


def scope_matches(question: str, title: str, section: str, *, default_full_term: bool = False) -> bool:
    focus = focus_for(question)
    if focus and focus.name == "institutional totals":
        return bool(re.search(r"\b(?:annual report|statistics|institutional research|fact book)\b", title, re.I))
    if focus and focus.name == "honors GPA cutoff":
        school = re.search(r"\b([a-z]+) school\b", question, re.I)
        if school and not re.search(r"\b" + re.escape(school[1]) + r"\b", title + " " + section, re.I):
            return False
    if focus and focus.name in {"graduation rate", "current enrollment statistics"}:
        program = re.search(r"\b(?:computer science|computer engineering|software engineering)\b", question, re.I)
        if program and not re.search(r"\b" + re.escape(program[0]) + r"\b", title + " " + section, re.I):
            return False
    if focus and focus.name in DATE_FOCUSES:
        years = set(re.findall(r"\b20\d{2}\b", question))
        if years and not years.issubset(set(re.findall(r"\b20\d{2}\b", title + " " + section))):
            return False
    if focus and focus.name == "academic standing GPA":
        if re.search(r"\b(?:admissions?|financial aid)\b", title + " " + section, re.I):
            return False
        graduate = re.search(r"\bgrad(?:uate)?\b", question, re.I)
        undergraduate = re.search(r"\bundergrad(?:uate)?\b", question, re.I)
        if graduate and not undergraduate and re.search(r"\bundergraduate\b", title, re.I):
            return False
        if undergraduate and not graduate and re.search(r"\bgraduate\b", title, re.I):
            return False
    if focus and focus.name == "course audit" and re.search(r"\bCS\s*\d{4}\b", question, re.I):
        return bool(re.search(r"\b(?:cannot|may not|ineligible)\b", section, re.I))
    if default_full_term and focus and focus.name == "withdrawal deadline" and not session_scope(question):
        return bool(re.search(r"\bfull[- ]term\b", section, re.I))
    return title_matches_scope(question, title, section)


_AP_EXAMS = (
    ("AP Calculus BC", re.compile(r"\b(?:ap\s+)?calc(?:ulus)?\s+bc\b", re.I)),
    ("AP Physics C: Mechanics", re.compile(r"\b(?:ap\s+)?physics\s+c\s*[:\-]?\s*mechanics\b", re.I)),
)
_SCORE_BEFORE = re.compile(r"\b([1-5])\s+(?:on|in|for)\s+(?:the\s+)?$", re.I)
_SCORE_AFTER = re.compile(r"\b(?:score(?:d)?\s+(?:of\s+)?|(?:got|earned)\s+)(?:a\s+)?([1-5])\b", re.I)
_SCORE_ROW = re.compile(r"\bscore of ([1-5])(?: or ([1-5]))?\s+earns?\s+\d+\s+semester credit hours\b", re.I)


def ap_requests(question: str) -> dict[str, int | None]:
    if not re.search(r"\b(?:AP|advanced placement)\b", question, re.I):
        return {}
    exams = {}
    for exam, pattern in _AP_EXAMS:
        if match := pattern.search(question):
            before = _SCORE_BEFORE.search(question[:match.start()])
            tail = re.split(r"\band\s+(?:a\s+)?[1-5]\s+on\b|[;?].*\bAP\b", question[match.end():], maxsplit=1, flags=re.I)[0]
            after = _SCORE_AFTER.search(tail)
            exams[exam] = int((before or after)[1]) if before or after else None
    return exams


def ap_row_supports(text: str, exam: str, score: int | None) -> bool:
    if exam.casefold() not in text.casefold():
        return False
    row = _SCORE_ROW.search(text)
    return bool(row and (score is None or str(score) in row.groups()))
