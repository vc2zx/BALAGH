"""Independent conservative safety signals; matches are prompts for review, not facts."""
from __future__ import annotations

import re

from balagh.triage import normalize_text


HAZARDS = (
    r"دخان|smoke", r"حريق|fire", r"تسرب غاز|gas leak", r"انفجار|explosion",
    r"سلك(?:\s+كهربا\w*)?\s+مكشوف|live wire", r"صعق|electrocution", r"انهيار|collapse",
    r"محاصر|trapped", r"\bمصاب(?:ه|ة|ين|ون)?\b|injured",
)
NEGATION = re.compile(r"(?:لا يوجد|لا توجد|ليس هناك|ما فيه|بدون|لم يحدث|no|not|without)\s+(?:\w+\s+){0,3}$")
HISTORICAL = re.compile(r"(?:امس|أمس|yesterday|تم إخماده|تم اخماده|extinguished|انتهى|ended|سابقا|previously)")


def safety_signals(title: str, description: str) -> dict:
    text = normalize_text(f"{title} {description}")
    observed: list[str] = []
    negated: list[str] = []
    historical = False
    urgent = False
    for clause in re.split(r"[.،؛\n]|(?:^|\s)(?:لكن|ولكن|بينما|ثم|والان)\s+", text):
        clause_historical = bool(HISTORICAL.search(clause))
        for expression in HAZARDS:
            for match in re.finditer(expression, clause):
                before = clause[max(0, match.start() - 50):match.start()]
                if NEGATION.search(before):
                    negated.append(match.group())
                else:
                    observed.append(match.group())
                    if clause_historical and not re.search(r"الان|حاليا|في هذه اللحظه", clause[match.end():]):
                        historical = True
                    else:
                        urgent = True
    return {
        "urgent_review": urgent,
        "possible_hazard_terms": sorted(set(observed)),
        "negated_terms": sorted(set(negated)),
        "historical_context": historical,
        "note": (
            "Text may indicate a current hazard; staff must verify."
            if urgent else
            "Hazard language appears historical; staff must verify timing."
            if observed and historical else
            "No current hazard signal identified by this limited text check."
        ),
    }
