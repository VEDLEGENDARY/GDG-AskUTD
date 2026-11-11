"""Experimental, deterministic passage reranking."""

import re


def _programs(text: str) -> set[str]:
    """Recognize explicit program names, ignoring capitalization."""
    names = ("computer science", "computer engineering")
    return {
        name
        for name in names
        if re.search(r"\b" + re.escape(name) + r"\b", text, re.I)
    }


def rerank(
    query: str,
    candidates: list[dict],
    *,
    use_program: bool = True,
    use_catalog: bool = True,
) -> list[dict]:
    requested_programs = _programs(query)
    requested_catalogs = _catalog_ranges(query)
    ranked = []

    for candidate in candidates:
        result = dict(candidate)
        score = candidate["retrieval_score"]
        title = candidate.get("source_title", "")

        described_programs = _programs(title)
        described_catalogs = _catalog_ranges(title)

        if (
            use_program
            and len(requested_programs) == 1
            and len(described_programs) == 1
        ):
            if requested_programs == described_programs:
                score += 0.10
            else:
                score -= 0.10

        # Only penalize an explicit mismatch. Unknown scope stays neutral.
        if (
            use_catalog
            and requested_catalogs
            and described_catalogs
            and requested_catalogs.isdisjoint(described_catalogs)
        ):
            score -= 0.10

        result["precision_score"] = score
        ranked.append(result)

    return sorted(
        ranked,
        key=lambda item: (-item["precision_score"], item["chunk_id"]),
    )
def _catalog_ranges(text: str) -> set[tuple[str, str]]:
    """Extract explicit year ranges, allowing spaces and common dashes."""
    return set(
        re.findall(
            r"\b((?:19|20)\d{2})\s*[-\u2013\u2014]\s*((?:19|20)\d{2})\b",
            text,
        )
    )


def _catalog_quantity_facets(query: str) -> list[tuple[str, str]]:
    """Recognize a few numeric facts, not arbitrary leftover query words.

    Unknown intents deliberately defer to the existing content checks.
    Patterns describe evidence shapes, not benchmark answers or expected values.
    """
    quantity = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    facets = []
    for direction in ("lower", "upper"):
        if re.search(rf"\b{direction}\b", query, re.I) and re.search(r"\bdivision\b", query, re.I):
            facets.append((f"{direction}-division quantity",
                           rf"\b{quantity}\s+{direction}[-\s]+division\b"))
    if re.search(r"\belectives?\b", query, re.I) and re.search(
            r"\b(?:hours?|total|number|how many)\b", query, re.I):
        facets.append(("elective quantity",
                       rf"\b{quantity}\s+(?:hours?\s+of\s+)?(?:free\s+)?electives?\b"
                       rf"|\belectives?\s*\(?\s*{quantity}\s+hours?\b"))
    return facets


def _scope_programs(query: str) -> set[str]:
    """Exclude a few explicit negative scopes; not a general negation parser."""
    excluded = set(re.findall(
        r"\b(?:do not substitute|excluding|rather than|instead of)\s+(?:the\s+)?"
        r"(computer science|computer engineering)\b", query.lower(),
    ))
    return _programs(query) - excluded


def evidence_reason(query: str, hits: list[dict]) -> str | None:
    """Conservative additional checks after selection, never a proof of truth.

    Recognized compound facets may be supported across documents. Explicit
    program/catalog scopes must occur together in a substantive passage;
    separate unrelated year mentions cannot establish that scope. Existing
    production checks must still be applied by the caller.
    """
    bodies = [h.get("text", "") for h in hits]
    if not any(body.strip() for body in bodies):
        return "precision: no body evidence"

    requested = _catalog_ranges(query)
    programs = _scope_programs(query)
    if requested and re.search(r"\b(?:catalogs?|plans?|degrees?)\b", query, re.I):
        facets = _catalog_quantity_facets(query)
        for catalog in sorted(requested):
            # When one catalog is shared by multiple requested programs, require
            # evidence for each program. Multi-year/program pairings are not inferred.
            scopes = sorted(programs) if len(requested) == 1 else (
                sorted(programs) if len(programs) == 1 else [None]
            )
            for program in scopes or [None]:
                bodies_in_scope = []
                for hit in hits:
                    body = hit.get("text", "")
                    title = hit.get("source_title", "")
                    context = title + " " + body
                    # Metadata can identify scope but cannot supply body facts.
                    if len(body.split()) < 8 or catalog not in _catalog_ranges(context):
                        continue
                    described = _programs(title) or _programs(body)
                    if program is not None and program not in described:
                        continue
                    bodies_in_scope.append(body)
                scope = "-".join(catalog) + (f" / {program}" if program else "")
                if not bodies_in_scope:
                    return "precision: missing program/catalog body evidence for " + scope
                for name, pattern in facets:
                    # Each fact must occur in a body, never by joining fragments
                    # from titles or across passage boundaries.
                    if not any(re.search(pattern, b, re.I) for b in bodies_in_scope):
                        return f"precision: missing {name} for {scope}"

    # These narrow paired intents do not split arbitrary questions on 'and'.
    if (re.search(r"\bclass standing\b", query, re.I)
            and re.search(r"\bdeclare\b.*\bmajor\b", query, re.I)):
        if not any(re.search(r"\b(?:freshman|sophomore|junior|senior)\b", b, re.I)
                   and re.search(r"\d", b) for b in bodies):
            return "precision: missing class standing evidence"
        if not any(re.search(r"\bdeclare\b.*\bmajor\b", b, re.I | re.S)
                   and re.search(r"\d", b) for b in bodies):
            return "precision: missing major declaration evidence"

    if (re.search(r"\beligib(?:le|ility)\b", query, re.I)
            and re.search(r"\b(?:documents?|paperwork)\b", query, re.I)):
        if not any(re.search(r"\b(?:eligible|eligibility|qualify)\b", b, re.I)
                   and re.search(r"\b(?:must|required|requires|if|only|minimum)\b", b, re.I)
                   for b in bodies):
            return "precision: missing eligibility conditions"
        if not any(re.search(r"\b(?:submit|provide|upload|required documents)\b", b, re.I)
                   and re.search(r"\b(?:transcripts?|passport|resume|documents?|letters?|"
                                 r"certificates?|forms?)\b", b, re.I)
                   for b in bodies):
            return "precision: missing required documents evidence"
    return None
