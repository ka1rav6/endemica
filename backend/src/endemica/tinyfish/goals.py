from __future__ import annotations

OUTBREAK_EXTRACTION_GOAL = (
    "Read this public-health outbreak report. Return the disease name exactly as written, "
    "every country and sub-national place mentioned as affected, confirmed, probable and "
    "suspected case counts and deaths with the period they cover, and the report date. "
    "Copy the exact sentence each number came from into evidence, verbatim and complete. "
    "Do not shorten the sentence. If a value is not stated, return null. Do not infer, "
    "calculate, or carry a number over from a different sentence. Never report recoveries, "
    "contacts, tests, samples or vaccination figures as case counts."
)

BORDER_POLICY_GOAL = (
    "Read this official government entry-requirements page. Return the current "
    "health-related entry measure for international arrivals as one of: entry_screening, "
    "quarantine, entry_ban, or none_stated. State who it applies to, its effective date, "
    "and copy the exact sentence stating it into evidence. If the page states no "
    "health-related entry measure, return none_stated. Do not infer a measure."
)

BORDER_POLICY_SCHEMA = {
    "type": "object",
    "properties": {
        "measure": {
            "type": "string",
            "enum": ["entry_screening", "quarantine", "entry_ban", "none_stated"],
        },
        "applies_to": {"type": "string"},
        "effective_date": {"type": "string"},
        "evidence": {"type": "string"},
    },
    "required": ["measure", "evidence"],
}
