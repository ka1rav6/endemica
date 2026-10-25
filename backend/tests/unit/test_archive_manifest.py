"""The manifest says which bulletins a checkout has, so two of them can be compared."""

from __future__ import annotations

from typing import Any

from endemica.ingestion import manifest as manifest_module


def item(name: str, summary: str = "text", title: str = "Cholera") -> dict[str, Any]:
    return {
        "ItemDefaultUrl": f"/emergencies/disease-outbreak-news/item/{name}",
        "Title": title,
        "PublicationDate": "2026-01-01",
        "Summary": summary,
    }


def test_two_downloads_of_the_same_bulletins_hash_the_same() -> None:
    first = manifest_module.build([item("2026-DON1"), item("2026-DON2")])
    second = manifest_module.build([item("2026-DON2"), item("2026-DON1")])
    assert first.digest == second.digest


def test_a_later_download_names_the_bulletins_the_manifest_does_not_list() -> None:
    committed = manifest_module.build([item("2026-DON1")])
    found = manifest_module.build([item("2026-DON1"), item("2026-DON2")])
    comparison = manifest_module.compare(committed, found)
    assert comparison.extra == ("2026-DON2",)
    assert not comparison.missing
    assert not comparison.identical
    assert any("2026-DON2" in line for line in comparison.describe())


def test_a_shorter_download_names_what_is_missing() -> None:
    committed = manifest_module.build([item("2026-DON1"), item("2026-DON2")])
    found = manifest_module.build([item("2026-DON1")])
    comparison = manifest_module.compare(committed, found)
    assert comparison.missing == ("2026-DON2",)
    assert not comparison.extra


def test_a_bulletin_whose_text_changed_is_reported_as_changed_not_missing() -> None:
    committed = manifest_module.build([item("2026-DON1", summary="first wording")])
    found = manifest_module.build([item("2026-DON1", summary="revised wording")])
    comparison = manifest_module.compare(committed, found)
    assert comparison.changed == ("2026-DON1",)
    assert not comparison.missing
    assert not comparison.extra


def test_identical_archives_say_so_in_one_line() -> None:
    built = manifest_module.build([item("2026-DON1")])
    comparison = manifest_module.compare(built, built)
    assert comparison.identical
    assert comparison.describe() == ["the local archive matches the committed manifest exactly"]


def test_a_missing_manifest_file_is_absent_rather_than_empty(tmp_path: Any) -> None:
    assert manifest_module.load(manifest_module.manifest_path(tmp_path)) is None


def test_a_written_manifest_reads_back_with_the_same_digest(tmp_path: Any) -> None:
    built = manifest_module.build([item("2026-DON1"), item("2026-DON2")])
    path = manifest_module.manifest_path(tmp_path)
    path.write_text(built.to_json(), encoding="utf-8")
    reloaded = manifest_module.load(path)
    assert reloaded is not None
    assert reloaded.digest == built.digest
