"""COVID-19 counts come from WHO's data table, because Outbreak News stopped covering it.

These tests pin the three properties the rest of the application depends on:
one snapshot per month taken at the last date WHO actually reported, cases and
deaths paired from the same row, and non-country reporting entities excluded.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from epiroute.ingestion import covid_global

HEADER = (
    "Date_reported,Country_code,Country,WHO_region,"
    "New_cases,Cumulative_cases,New_deaths,Cumulative_deaths"
)

KNOWN = {"THA", "JPN", "CHN"}
BY_ISO2 = {"TH": "THA", "JP": "JPN", "CN": "CHN"}


def write(tmp_path: Path, *rows: str) -> Path:
    target = tmp_path / "who.csv"
    target.write_text("\n".join((HEADER, *rows)) + "\n", encoding="utf-8")
    return target


def snapshots(path: Path) -> list[covid_global.Snapshot]:
    built, _ = covid_global.monthly_snapshots(path, known=KNOWN, by_iso2=BY_ISO2)
    return built


def test_a_month_is_summarised_at_the_last_date_who_reported() -> None:
    # Not the calendar month end: WHO's file stops at the 30th here, so
    # claiming data as of the 31st would overstate the coverage.
    path = write(
        _tmp_dir(),
        "2020-03-15,TH,Thailand,SEAR,10,100,1,5",
        "2020-03-30,TH,Thailand,SEAR,20,300,2,9",
    )
    built = snapshots(path)
    assert [snap.as_of for snap in built] == [date(2020, 3, 30)]
    assert built[0].counts[0].cases == 300
    assert built[0].counts[0].deaths == 9


def test_cases_and_deaths_come_from_the_same_row() -> None:
    path = write(
        _tmp_dir(),
        "2020-04-30,TH,Thailand,SEAR,1,500,1,20",
        "2020-04-30,JP,Japan,WPR,1,700,1,30",
    )
    counts = {count.iso3: (count.cases, count.deaths) for count in snapshots(path)[0].counts}
    assert counts == {"THA": (500, 20), "JPN": (700, 30)}


def test_every_month_in_the_file_becomes_one_report() -> None:
    path = write(
        _tmp_dir(),
        "2020-03-31,TH,Thailand,SEAR,1,100,0,1",
        "2020-04-30,TH,Thailand,SEAR,1,200,0,2",
        "2020-05-31,TH,Thailand,SEAR,1,300,0,3",
    )
    built = snapshots(path)
    assert [snap.month for snap in built] == ["2020-03", "2020-04", "2020-05"]
    assert [snap.source_identifier for snap in built] == [
        "who-covid19-2020-03",
        "who-covid19-2020-04",
        "who-covid19-2020-05",
    ]


def test_conveyances_are_not_countries_and_are_skipped() -> None:
    path = write(
        _tmp_dir(),
        "2020-02-29,TH,Thailand,SEAR,1,40,0,1",
        "2020-02-29,XJ,International conveyance (Diamond Princess),WPR,1,700,0,7",
    )
    built, detail = covid_global.monthly_snapshots(path, known=KNOWN, by_iso2=BY_ISO2)
    assert [count.iso3 for count in built[0].counts] == ["THA"]
    assert detail["entities_skipped"] == 1


def test_a_country_absent_from_the_reference_table_is_skipped() -> None:
    # Observations carry a foreign key to countries.iso3; writing a row for a
    # territory the reference table does not list would fail the insert.
    path = write(
        _tmp_dir(),
        "2020-02-29,TH,Thailand,SEAR,1,40,0,1",
        "2020-02-29,CW,Curacao,AMR,1,9,0,1",
    )
    built, detail = covid_global.monthly_snapshots(path, known=KNOWN, by_iso2=BY_ISO2)
    assert [count.iso3 for count in built[0].counts] == ["THA"]
    assert detail["entities_skipped"] == 1


def test_a_country_with_no_cases_yet_is_not_reported_as_an_outbreak_country() -> None:
    # A zero in the file means "nothing to report", not "an outbreak of size
    # zero". Storing it would put the country on the map.
    path = write(
        _tmp_dir(),
        "2020-01-31,TH,Thailand,SEAR,,2,,0",
        "2020-01-31,JP,Japan,WPR,,0,,0",
    )
    assert [count.iso3 for count in snapshots(path)[0].counts] == ["THA"]


def test_a_month_in_which_nobody_reported_anything_produces_no_report() -> None:
    path = write(
        _tmp_dir(),
        "2020-01-31,TH,Thailand,SEAR,,0,,0",
        "2020-02-29,TH,Thailand,SEAR,,5,,0",
    )
    assert [snap.month for snap in snapshots(path)] == ["2020-02"]


def test_blank_counts_are_not_read_as_zero() -> None:
    path = write(
        _tmp_dir(),
        "2020-06-30,TH,Thailand,SEAR,,,,",
    )
    built, detail = covid_global.monthly_snapshots(path, known=KNOWN, by_iso2=BY_ISO2)
    assert built == []
    assert detail["rows_without_counts"] == 1


def test_the_narrative_states_every_number_that_is_stored() -> None:
    # Grounding is recorded as verified against this text, so the text has to
    # contain the figures a reader would check.
    path = write(
        _tmp_dir(),
        "2020-07-31,TH,Thailand,SEAR,1,1234,1,56",
    )
    snapshot = snapshots(path)[0]
    narrative = covid_global._narrative(snapshot)
    assert "1234" in narrative
    assert "56" in narrative
    assert "2020-07-31" in narrative


def _tmp_dir() -> Path:
    """A fresh directory per call, so the helper can be used more than once."""
    import tempfile

    return Path(tempfile.mkdtemp())


def test_a_total_that_did_not_move_is_not_a_fresh_report() -> None:
    # WHO repeats every country's running total every day, moved or not.
    # Storing an unmoved total as a new observation would say the country
    # reported this month when it stopped reporting years ago.
    path = write(
        _tmp_dir(),
        "2020-01-31,TH,Thailand,SEAR,,10,,1",
        "2020-02-29,TH,Thailand,SEAR,,20,,2",
        "2020-03-31,TH,Thailand,SEAR,,20,,2",
        "2020-04-30,TH,Thailand,SEAR,,20,,2",
    )
    built, detail = covid_global.monthly_snapshots(path, known=KNOWN, by_iso2=BY_ISO2)
    assert [snap.month for snap in built] == ["2020-01", "2020-02"]
    assert detail["rows_unchanged_since_previous_month"] == 2


def test_a_country_that_resumes_reporting_comes_back() -> None:
    path = write(
        _tmp_dir(),
        "2020-01-31,TH,Thailand,SEAR,,10,,1",
        "2020-02-29,TH,Thailand,SEAR,,10,,1",
        "2020-03-31,TH,Thailand,SEAR,,30,,3",
    )
    built = snapshots(path)
    assert [snap.month for snap in built] == ["2020-01", "2020-03"]
    assert built[-1].counts[0].cases == 30


def test_one_country_going_quiet_does_not_drop_another() -> None:
    path = write(
        _tmp_dir(),
        "2020-01-31,TH,Thailand,SEAR,,10,,1",
        "2020-01-31,JP,Japan,WPR,,5,,0",
        "2020-02-29,TH,Thailand,SEAR,,10,,1",
        "2020-02-29,JP,Japan,WPR,,9,,1",
    )
    built = snapshots(path)
    assert [count.iso3 for count in built[-1].counts] == ["JPN"]
