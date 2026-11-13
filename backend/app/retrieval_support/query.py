"""Deterministic follow-up resolution and evidence checks."""
from __future__ import annotations

import re

from evaluate import evaluate_chunks as ev

from ..types import Turn
from .focus import DROP_OUTCOME, focus_for, normalize_years, session_scope, scope_matches

_PRIVATE = re.compile(
    r"^\s*(?:has|have|did|was|were|is)\b[^?.]*\b(?:my|me)\b[^?.]*\b(?:approved|accepted|processed|received|assigned|reviewed|excluded|recorded)\b"
    r"|^\s*(?:did|has|have|was|is)\b[^?.]*\b(?:approv\w*|receiv\w*|review\w*|process\w*|grant\w*|accept\w*)\b[^?.]*\b(?:my|i uploaded|i submitted)\b"
    r"|\b(?:assigned|corrected|actual)\s+(?:academic advisor|advisor|cumulative gpa|gpa|grade|balance)\b"
    r"|\bwhat is my (?:current |cumulative |corrected )*(?:gpa|grade|balance)\b"
    r"|\b(?:my|i)\b.{0,80}\b(?:already (?:used|submitted)|still owe)\b"
    r"|\b(?:what time|when|what day|what date|what exact date|which room)\b.*\bmy\b.*\b(?:appointment|exam)\b"
    r"|\b(?:which|who)\b.{0,80}\b(?:assigned to my|my permission to inspect)\b"
    r"|\b(?:which|who)\b.{0,50}\bmy\b.{0,35}\b(?:case officer|hearing officer|assigned advisor)\b"
    r"|\b(?:aid|work.study)\b.{0,65}\boffer(?:ed)? (?:to )?me\b"
    r"|\b(?:this class|course i am taking this semester)\b.{0,70}\b(?:credit.no credit|excluded|eligible)\b"
    r"|\b(?:my|i|me)\b.*\b(?:graduate|finish) on time\b"
    r"|\b(?:my|i|me)\b.*\b(?:worst case|worst-case)\b.*\b(?:graduate|finish)\b"
    r"|\bmy\s+(?:account|record|transcript|schedule|payroll)\b.{0,75}\b(?:right now|currently|already|today|this morning|yet)\b"
    r"|\b(?:is there|are there|do i have)\b.{0,50}\bholds?\b.{0,25}\bmy (?:account|record)\b"
    r"|\b(?:my|mine)\s+(?:completed hours|gpa|cumulative gpa|account balance)\b.{0,60}\b(?:am i|cutoff|right now|currently)\b"
    r"|\bhow many (?:times|credits?|hours?)\b.{0,55}\b(?:have i|did i)\b.{0,55}\b(?:used|changed|completed|earned|taken)\b"
    r"|\b(?:exactly|exact)\b.{0,70}\b(?:refund\w*|repay|owe|amount|dollars)\b.{0,80}\b(?:my|me|i)\b"
    r"|\b(?:my|me|i)\b.{0,100}\b(?:exactly|exact)\b.{0,80}\b(?:refund\w*|repay|owe|amount|dollars)\b"
    r"|\bwhat did\b.{0,90}\b(?:decide|rule|approve|reject)\b.{0,90}\b(?:my|i submitted|i filed)\b"
    r"|\b(?:what|which)\b.{0,70}\b(?:notes|permission number|access code)\b.{0,80}\b(?:my|me)\b"
    r"|^\s*(?:has|have|did)\b.{0,120}\b(?:certif\w*|post\w*|review\w*)\b.{0,80}\bmy\b"
    r"|\b(?:unspecified|unnamed|unidentified)\b.{0,40}\b(?:course|department|class|credit)\b"
    r"|\b(?:my|me)\b.{0,70}\b(?:schedule conflict|time conflict|without a conflict)\b"
    r"|\b(?:which|who)\b.{0,70}\bon duty\b.{0,30}\b(?:today|tomorrow|this|next)\b"
    r"|\b(?:that|this) department office\b"
    r"|^\s*(?:please\s+)?(?:withdraw me|drop my|enroll me|register me|submit my)\b",
    re.I | re.S,
)


def private_reason(query: str) -> str | None:
    """Distinguish requesting a public procedure from asking for a private fact."""
    return 'private record or missing course context' if _PRIVATE.search(query) else None


OUTSIDE = re.compile(r"\b(?:weather|joke|write (?:me )?(?:code|a program)|harvard|stanford)\b", re.I)
STOP = set('ut utd dallas texas university student students please tell explain about would could should will must many much when where who why get'.split())

# These expansions are deliberately narrow: they add search vocabulary without
# replacing a student's wording or conflating distinct university processes.
_ALIAS_RULES = (
    (re.compile(r"\bundergrad\b", re.I), "undergraduate"),
    (re.compile(r"\bgrad\b", re.I), "graduate"),
    (re.compile(r"\bcalc\s+(?:ab|bc)\b", re.I), "calculus"),
    (re.compile(r"\b(?:cs)\b.*\b(?:degree plan|major|elective)\b", re.I), "computer science"),
)
_ACTION = re.compile(r"\b(?:drop|add|withdraw|register|registration|enroll|enrollment)\b", re.I)
_CLASS_COURSE = re.compile(r"\b(?:class(?:es)?|course(?:s)?)\b", re.I)
_WAITLIST = re.compile(r"\bwait\s*list(?:ed|ing)?\b", re.I)
_SIGN_UP = re.compile(r"\bsign\s+up\s+for\s+(?:a\s+|the\s+)?(?:class(?:es)?|course(?:s)?)\b", re.I)
_ENROLL_REGISTER = re.compile(r"\b(?:enroll(?:ment)?|register(?:ing|ed|ation)?)\b", re.I)
_COMPLETE_WITHDRAWAL = re.compile(
    r"\bwithdraw\w*\s+(?:from\s+)?(?:all\s+|every\s+)?(?:classes|courses)\b"
    r"|\bwithdraw\w*\s+from\s+(?:the\s+)?(?:whole\s+)?(?:semester|university)\b"
    r"|\bcomplete(?:ly)?\s+withdraw\w*\s+from\s+(?:the\s+)?university\b"
    r"|\bleave\s+(?:ut\s+dallas|the\s+university|school)\b.{0,50}\b(?:semester|term|all\s+(?:classes|courses))\b", re.I,
)
_TOPIC_TERMS = {
    "registration": re.compile(r"\b(?:registration|register|enroll(?:ment)?|schedule planner|wait\s*list|sign\s+up)\b", re.I),
    "drop": re.compile(r"\b(?:drop|withdraw\w*)\b", re.I),
    "library": re.compile(r"\b(?:library|librar\w*|books?|study room)\b", re.I),
    "bursar": re.compile(r"\b(?:bursar|tuition|fees?|billing|payment)\b", re.I),
    "transcript": re.compile(r"\btranscript\b", re.I),
    "advising": re.compile(r"\b(?:advisor|advising|academic counselor)\b", re.I),
}
_FOLLOW_UP = re.compile(
    r"^(?:what about|how about|what if|what happens\s*if|and\b|does (?:that|it)\b|"
    r"can (?:they|i)\b|is (?:that|it)\b|what(?:'s| is) the deadline\b|"
    r"when is the deadline\b|where is it\b|from those\b)", re.I,
)
_UNDERGRAD_POPULATION = re.compile(r"\b(?:undergraduates?|undergrads?)(?:\s+students?)?\b", re.I)
_GRAD_POPULATION = re.compile(r"\b(?:graduates?|grads?)(?:\s+students?)?\b", re.I)
_POPULATION = re.compile(r"\b(?:undergraduates?|undergrads?|graduates?|grads?)(?:\s+students?)?\b", re.I)
_DROP_SCOPE_REPLY = re.compile(
    r"^(?:(?:i am|i'm)\s+(?:an?\s+)?)?"
    r"(?:undergrad\w*|grad\w*|(?:spring|summer|fall)\s+20\d{2}|full[- ]term|(?:first|second)\s+8[- ]week)\b",
    re.I,
)
_REGISTRATION_TIMING = re.compile(r"\b(?:when|what date|what time|deadline)\b.*\bregistration\b|\bregistration\b.*\bdeadline\b", re.I)
_REGISTRATION_PROCESS = re.compile(
    r"\bregistration\s+(?:work|process|procedure)\b|\bsign\s+up\s+for\b", re.I,
)
_REGISTRATION_TOPIC = re.compile(r"\b(?:registration|register\w*|enroll\w*|sign\s+up)\b", re.I)
_SCOPE_CONSTRAINT = re.compile(
    r"\b(?:20\d{2}|spring|summer|fall|winter|before|after|until|through|during|unless|if|only|not|never|cannot|can't|when|deadline|date|time)\b",
    re.I,
)
_LIBRARY_WHERE = re.compile(
    r"\bwhere\b.{0,80}\b(?:eugene\s+)?mcdermott\s+library\b"
    r"|\bwhere\s+is\s+the\s+library\b"
    r"|\b(?:address|located)\b.{0,80}\b(?:eugene\s+)?mcdermott\s+library\b"
    r"|\b(?:eugene\s+)?mcdermott\s+library\b.{0,80}\b(?:address|located)\b", re.I,
)
_LIBRARY_LOCATION_FACT = re.compile(
    r"\b(?:eugene )?mcdermott library\b.{0,80}\b(?:is located|located at|located in|is at|is in|address is)\b", re.I,
)


def _expand_aliases(query: str) -> str:
    """Append only supported equivalent terms; never rewrite the source phrase."""
    additions: list[str] = []
    folded = query.casefold()
    for source, target in _ALIAS_RULES:
        if source.search(query) and target.casefold() not in folded:
            additions.append(target)
    if _ACTION.search(query) and _CLASS_COURSE.search(query) and not _SIGN_UP.search(query):
        if re.search(r"\bclass\b", query, re.I) and not re.search(r"\bcourse\b", query, re.I):
            additions.append("course")
        elif re.search(r"\bcourse\b", query, re.I) and not re.search(r"\bclass\b", query, re.I):
            additions.append("class")
    if _WAITLIST.search(query):
        if re.search(r"\bwaitlist(?:ed|ing)?\b", query, re.I):
            additions.append("wait list")
        elif re.search(r"\bwait\s+list\b", query, re.I):
            additions.append("waitlist")
    if re.search(r"\baudit\b", query, re.I) and re.search(r"\bCS\s*\d{4}\b", query, re.I):
        additions.append("computer science course audit")
    if _SIGN_UP.search(query):
        additions.append("register classes enrollment")
    elif _ENROLL_REGISTER.search(query) and _CLASS_COURSE.search(query):
        has_registration_word = re.search(r"\b(?:register\w*|registration)\b", query, re.I)
        has_enrollment_word = re.search(r"\benroll(?:ment)?\b", query, re.I)
        if has_enrollment_word and not has_registration_word:
            additions.append("register")
        elif has_registration_word and not has_enrollment_word:
            additions.append("enroll")
    # Full-semester/university withdrawal has its own policy. Never infer it
    # from a request to drop or withdraw from one class.
    if _COMPLETE_WITHDRAWAL.search(query) and "complete university withdrawal" not in folded:
        additions.append("complete university withdrawal")
    additions = list(dict.fromkeys(
        phrase for phrase in additions
        if not re.search(r"\b" + r"\s+".join(map(re.escape, phrase.split())) + r"\b", query, re.I)
    ))
    if _REGISTRATION_PROCESS.search(query):
        if _GRAD_POPULATION.search(query):
            process_terms = "graduate registration enrollment appointment"
        elif _UNDERGRAD_POPULATION.search(query):
            process_terms = "Orion enrollment appointment"
        else:
            process_terms = ""
        if process_terms and process_terms.casefold() not in folded:
            additions.append(process_terms)
    if _REGISTRATION_TIMING.search(query):
        if _GRAD_POPULATION.search(query):
            timing_terms = "registration dates early regular late"
        elif _UNDERGRAD_POPULATION.search(query):
            timing_terms = "registration dates academic calendar enrollment appointment"
        else:
            timing_terms = "registration dates early regular late academic calendar"
        if timing_terms.casefold() not in folded:
            additions.append(timing_terms)
    suffix = " ".join(additions)
    return f"{query} {suffix}" if suffix and len(query) + len(suffix) + 1 <= 500 else query


def _history_user_question(history: list[Turn] | None) -> str | None:
    if not isinstance(history, list):
        return None
    for turn in reversed(history[-6:]):
        if isinstance(turn, Turn) and turn.role == 'user' and isinstance(turn.content, str):
            content = turn.content.strip()
            if content:
                return content[:500]
    return None


def rewrite(query: str, history: list[Turn] | None) -> str:
    """Conservatively expand aliases and resolve clear follow-ups from user turns."""
    return _rewrite(query, history, use_aliases=True, use_history=True)


def _rewrite(query: str, history: list[Turn] | None, *, use_aliases: bool, use_history: bool) -> str:
    if not isinstance(query, str) or not query.strip():
        return query
    original = normalize_years(query.strip())

    # The API schema enforces the generation boundary. Direct callers with a
    # longer string keep it intact; silently slicing it could lose conditions.
    if len(original) > 500:
        return original

    prior = _history_user_question(history) if use_history else None
    resolved = original
    if prior and DROP_OUTCOME.search(prior) and _DROP_SCOPE_REPLY.search(original):
        if len(prior) + len(original) < 500:
            resolved = f"{prior} {original}"
    elif prior and _FOLLOW_UP.search(original) and not _is_topic_change(original, prior):
        if session_scope(original):
            prior = re.sub(r"\b(?:(?:first|second)\s+8[- ]week|full[- ]term)(?:\s+session)?\b", "", prior, flags=re.I)
        # A population named in the follow-up replaces the prior population while
        # retaining the topic. This avoids searches that ask about both groups.
        canonical_registration_population = None
        if _POPULATION.search(original):
            prior = re.sub(r"\s+", " ", _POPULATION.sub('', prior)).strip()
            if (_GRAD_POPULATION.search(original)
                    and _REGISTRATION_TOPIC.search(prior)):
                original = _GRAD_POPULATION.sub("graduate students", original)
                canonical_registration_population = "graduate"
            elif _UNDERGRAD_POPULATION.search(original):
                original = _UNDERGRAD_POPULATION.sub("undergraduate students", original)
                if _REGISTRATION_TOPIC.search(prior):
                    canonical_registration_population = "undergraduate"
        if canonical_registration_population and not _SCOPE_CONSTRAINT.search(prior):
            # Strip generic wording that otherwise keeps the previous population's
            # best-matching paragraph above the requested population.
            resolved = f"How does registration work for {canonical_registration_population} students?"
            prior = ""
        prefix = prior.strip()
        if prefix and original.casefold() not in prefix.casefold():
            available = max(0, 500 - len(original) - 1)
            resolved = f"{prefix[:available].rstrip()} {original}" if available else original

    return _expand_aliases(resolved) if use_aliases else resolved


def _is_topic_change(current: str, prior: str) -> bool:
    """Do not carry an earlier subject into a clear, unrelated new subject."""
    current_topics = {name for name, pattern in _TOPIC_TERMS.items() if pattern.search(current)}
    prior_topics = {name for name, pattern in _TOPIC_TERMS.items() if pattern.search(prior)}
    if not current_topics or not prior_topics:
        return False
    return not current_topics.intersection(prior_topics)


def reject(query: str, hits: list[dict], config: dict) -> str | None:
    """Reject private records, missing time scope, and low-overlap evidence."""
    if OUTSIDE.search(query):
        return 'out of scope'
    if reason := private_reason(query):
        return reason
    if not hits:
        return 'no evidence above score threshold'
    focus = focus_for(query)
    if focus and not any(
        focus.supports(hit['text'], ev.metadata(hit))
        and scope_matches(query, hit.get('source_title', ''), hit.get('section_heading', ''), default_full_term=True)
        for hit in hits
    ):
        return f'missing evidence for {focus.name}'
    evidence = ' '.join(ev.context_text(h) for h in hits)
    if _LIBRARY_WHERE.search(query) and not _LIBRARY_LOCATION_FACT.search(evidence):
        return 'library location not established in evidence'
    years = re.findall(r'\b20\d{2}\b', query)
    topic_terms = set(ev.tokens(query)) - STOP - set(years)
    for year in years:
        supported = any(
            year in ev.tokens(ev.context_text(hit))
            and bool(topic_terms & set(ev.tokens(ev.context_text(hit))))
            for hit in hits
        )
        if not supported:
            return 'requested year absent from relevant evidence'
    terms = set(ev.tokens(query))-STOP
    coverage = max((len(terms & set(ev.tokens(ev.context_text(h))))/max(1, len(terms)) for h in hits), default=0)
    if not focus and coverage < config['min_term_coverage']:
        return 'weak query term coverage'
    if not focus and max(h['retrieval_score'] for h in hits) < config['min_top_score']:
        return 'weak top evidence score'
    return None
