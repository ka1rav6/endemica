"""A committed fingerprint of the WHO archive, so two checkouts can see where they differ.

Two people running the same commit were getting different numbers, and the
pipeline had no way to show them why. Three things vary independently and all
three are invisible from the app:

* ``data/raw`` is not in version control, so each checkout downloads the WHO
  archive at its own moment and gets however many bulletins existed then;
* ``--limit`` stops the ingest early, and a different limit is a different
  database from the same archive;
* extraction runs either through the TinyFish Agent or through the
  deterministic parser, depending on whether ``TINYFISH_API_KEY`` is set, and
  the two read different figures out of the same prose.

The manifest records which bulletins a download contained, by identifier and
by hash of the fields the parser reads. It is committed, so ``ingest-archive``
can say which records this machine is missing or holding extra rather than
leaving two people to compare screenshots. The database fingerprint beside it
does the same for the rows that came out: same manifest and same fingerprint
means the two checkouts genuinely agree.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_NAME = "who_don_manifest.json"

# The fields the parser reads. Hashing the whole item would make the manifest
# churn on fields nobody uses, such as WHO's own internal ordering keys.
_HASHED_FIELDS = (
    "ItemDefaultUrl",
    "Title",
    "PublicationDate",
    "PublicationDateAndTime",
    "OverrideDatePublication",
    "Summary",
    "regionscountries",
)


def manifest_path(data_dir: Path) -> Path:
    return data_dir / MANIFEST_NAME


def _identifier(item: dict[str, Any]) -> str:
    url = str(item.get("ItemDefaultUrl") or "")
    return url.rsplit("/", 1)[-1] or str(item.get("Title") or "")[:80]


def item_digest(item: dict[str, Any]) -> str:
    payload = {field: item.get(field) for field in _HASHED_FIELDS}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Manifest:
    records: dict[str, str]

    @property
    def digest(self) -> str:
        """One hash over the whole set, for a single-line comparison."""
        encoded = json.dumps(dict(sorted(self.records.items())), sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        return json.dumps(
            {
                "record_count": len(self.records),
                "digest": self.digest,
                "records": dict(sorted(self.records.items())),
            },
            indent=2,
        )


def build(items: list[dict[str, Any]]) -> Manifest:
    return Manifest(
        {
            _identifier(item): item_digest(item)
            for item in items
            if isinstance(item, dict) and _identifier(item)
        }
    )


def load(path: Path) -> Manifest | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, dict):
        return None
    return Manifest({str(key): str(value) for key, value in records.items()})


@dataclass(frozen=True, slots=True)
class Comparison:
    missing: tuple[str, ...]
    extra: tuple[str, ...]
    changed: tuple[str, ...]

    @property
    def identical(self) -> bool:
        return not (self.missing or self.extra or self.changed)

    def describe(self) -> list[str]:
        if self.identical:
            return ["the local archive matches the committed manifest exactly"]
        lines = []
        if self.missing:
            lines.append(
                f"{len(self.missing)} bulletin(s) in the manifest are not in the local "
                f"archive, starting with {', '.join(self.missing[:5])}"
            )
        if self.extra:
            lines.append(
                f"{len(self.extra)} bulletin(s) were downloaded that the manifest does "
                f"not list, starting with {', '.join(self.extra[:5])}. WHO has published "
                "since the manifest was committed."
            )
        if self.changed:
            lines.append(
                f"{len(self.changed)} bulletin(s) have different text from the manifest, "
                f"starting with {', '.join(self.changed[:5])}. WHO revises bulletins in "
                "place."
            )
        return lines


def compare(expected: Manifest, found: Manifest) -> Comparison:
    missing = sorted(set(expected.records) - set(found.records))
    extra = sorted(set(found.records) - set(expected.records))
    changed = sorted(
        key
        for key in set(expected.records) & set(found.records)
        if expected.records[key] != found.records[key]
    )
    return Comparison(tuple(missing), tuple(extra), tuple(changed))
