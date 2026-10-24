"""Command-line interface.

Every routine operation is reachable through the root ``justfile``, which
delegates to this module. Commands are thin: they parse arguments, call a
service and print a human-readable report. The exit code is non-zero when the
operation failed, so ``just`` recipes propagate failures.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from epiroute.core.config import Settings, get_settings
from epiroute.core.logging import configure_logging

logger = logging.getLogger(__name__)

# Terminal markers used in reports. Plain ASCII alternatives are not used
# because every target shell here is UTF-8.
OK = "✓"
BAD = "✗"
WARN = "!"


def _print_header(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


# ---------------------------------------------------------------------------
# config-check
# ---------------------------------------------------------------------------


def cmd_config_check(args: argparse.Namespace) -> int:
    """Report configuration, distinguishing required from optional settings."""
    settings = get_settings()
    problems: list[str] = []

    rows: list[tuple[str, str, str]] = [
        ("environment", settings.env, "required"),
        ("log level", settings.log_level, "required"),
        ("database", settings.safe_database_url, "required"),
        ("data directory", str(settings.data_dir), "required"),
        ("CORS origins", ", ".join(settings.cors_origin_list) or "(none)", "required"),
        (
            "TinyFish",
            "configured" if settings.tinyfish_enabled else "not configured (direct_fetch mode)",
            "optional",
        ),
        ("WHO DON API", settings.who_don_api_url, "required"),
        ("ingest cap", f"{settings.ingest_max_records} records/run", "required"),
        ("HTTP timeout", f"{settings.http_timeout_seconds:g}s", "required"),
    ]

    if not args.quiet:
        _print_header("Configuration")
        for name, value, requirement in rows:
            marker = OK if requirement == "required" else " "
            print(f"  {marker} {name:<16} {value}  [{requirement}]")

    if not settings.data_dir.exists():
        problems.append(f"data directory does not exist: {settings.data_dir}")
    elif not _is_writable(settings.data_dir):
        problems.append(f"data directory is not writable: {settings.data_dir}")

    if problems:
        for problem in problems:
            print(f"  {BAD} {problem}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"  {OK} configuration valid")
    return 0


def _is_writable(path: object) -> bool:
    """Whether a directory accepts a new file."""
    import pathlib
    import tempfile

    directory = pathlib.Path(str(path))
    try:
        with tempfile.NamedTemporaryFile(dir=directory):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# db-status
# ---------------------------------------------------------------------------


def cmd_db_status(args: argparse.Namespace) -> int:
    """Report database connectivity, migration revision and row counts."""
    from sqlalchemy import func, inspect, select, text
    from sqlalchemy.exc import SQLAlchemyError

    from epiroute.db import models  # noqa: F401
    from epiroute.db.base import Base
    from epiroute.db.session import session_scope

    settings = get_settings()
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
            inspector = inspect(session.get_bind())
            tables = set(inspector.get_table_names())

            revision: str | None = None
            if "alembic_version" in tables:
                revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()

            counts: dict[str, int] = {}
            for name, table in sorted(Base.metadata.tables.items()):
                if name in tables:
                    counts[name] = (
                        session.execute(select(func.count()).select_from(table)).scalar() or 0
                    )
    except SQLAlchemyError as exc:
        if args.quiet:
            print("unreachable", file=sys.stderr)
        else:
            print(f"  {BAD} cannot connect to {settings.safe_database_url}", file=sys.stderr)
            print(f"      {type(exc).__name__}: start it with `just db-up`", file=sys.stderr)
        return 1

    if args.quiet:
        print(f"connected ({len(counts)} tables)")
        return 0

    _print_header("Database")
    print(f"  {OK} connected: {settings.safe_database_url}")
    if revision:
        print(f"  {OK} migration revision: {revision}")
    else:
        print(f"  {WARN} no migrations applied — run `just db-migrate`")

    missing = sorted(set(Base.metadata.tables) - set(counts))
    if missing:
        print(f"  {WARN} tables missing: {', '.join(missing)}")

    if counts:
        _print_header("Row counts")
        width = max(len(n) for n in counts)
        for name, count in counts.items():
            print(f"  {name:<{width}}  {count:>9,}")
    return 0 if revision and not missing else 1


# ---------------------------------------------------------------------------
# data-fetch / data-check
# ---------------------------------------------------------------------------


def _fetch_eurostat(*, force: bool) -> int:
    """Download Eurostat passenger tables for the live year and the training years."""
    from epiroute.datasets.eurostat import (
        DEFAULT_REFERENCE_YEAR,
        FLOW_YEARS,
        download_all,
        raw_filename,
    )

    settings = get_settings()
    failures = 0
    for year in FLOW_YEARS:
        path = settings.raw_data_dir / raw_filename(year)
        live = settings.raw_data_dir / "eurostat_avia_par.json.gz"
        live_ready = year != DEFAULT_REFERENCE_YEAR or live.exists()
        if path.exists() and live_ready and not force:
            print(f"  {OK} eurostat_avia_par_{year}: already present")
            continue
        try:
            written = download_all(year=year, settings=settings)
        except Exception as exc:
            failures += 1
            print(f"  {BAD} eurostat_avia_par_{year}: {exc}")
            continue
        print(f"  {OK} eurostat_avia_par_{year}: {written.stat().st_size / 1e6:.1f} MB")
    for label, fetch in _optional_fetches():
        try:
            written = fetch()
        except Exception as exc:
            print(f"  {BAD} {label}: {exc}")
            continue
        print(f"  {OK} {label}: {written.name}")
    return failures


def _optional_fetches() -> tuple[tuple[str, Callable[[], Path]], ...]:
    from epiroute.datasets.dot_t100 import download as download_dot
    from epiroute.datasets.worldbank import download as download_population

    fetches: tuple[tuple[str, Callable[[], Path]], ...] = (
        ("dot_t100", download_dot),
        ("worldbank_population", download_population),
    )
    return fetches


def cmd_data_fetch(args: argparse.Namespace) -> int:
    """Download the registered reference datasets."""
    from epiroute.datasets.fetch import fetch_all

    _print_header("Fetching datasets")
    results = fetch_all(force=args.force, only=args.only)
    failures = 0
    for result in results:
        if result.error:
            failures += 1
            print(f"  {BAD} {result.key}: {result.error}")
        elif result.skipped:
            print(f"  {OK} {result.key}: already present ({result.path.name})")
        else:
            print(f"  {OK} {result.key}: {result.bytes_written / 1e6:.1f} MB -> {result.path.name}")

    wanted = set(args.only) if args.only else None
    if wanted is None or "eurostat_avia_par" in wanted:
        failures += _fetch_eurostat(force=args.force)

    if failures:
        print(f"\n{failures} of {len(results)} datasets failed. Existing files were not modified.")
        return 1
    print(f"\n{len(results)} datasets ready in {get_settings().raw_data_dir}")
    return 0


def cmd_labels_build(_args: argparse.Namespace) -> int:
    """Download COVID and mpox first-report dates and write the audit sample."""
    from epiroute.calibration.labels import build_labels

    path = build_labels()
    print(f"{OK} labels written to {path}")
    return 0


def cmd_train_model(args: argparse.Namespace) -> int:
    """Fit the hazard, write the model card and rewrite the evaluation report.

    The panel in ``data/labels`` is committed, so training works on a fresh
    checkout and gives every checkout the same coefficients. Rebuilding it
    needs the processed flow and population tables and is therefore opt-in;
    it used to be unconditional, which is why ``train-model`` failed outright
    on any machine that had not fetched Eurostat's 2019 and 2022 tables.
    """
    from epiroute.calibration.labels import labels_dir
    from epiroute.calibration.panel import build_panel
    from epiroute.calibration.train import train

    panel = labels_dir() / "panel.parquet"
    if args.rebuild_panel or not panel.exists():
        reason = "asked for" if args.rebuild_panel else "missing"
        print(f"  rebuilding the training panel ({reason})")
        build_panel()
    card = train()
    print(f"{OK} model card written to {card}")

    from epiroute.calibration.report import REPORT_NAME, repository_root
    from epiroute.calibration.train import calibration_status, load_card

    print(f"{OK} evaluation report written to {repository_root() / REPORT_NAME}")
    stored = load_card() or {}
    print(f"  status: {calibration_status()}")
    print(f"  claim:  {stored.get('claim', '')}")
    return 0


def cmd_validate_model(_args: argparse.Namespace) -> int:
    """Print the calibration card. Exit 1 when the model is not validated."""
    from epiroute.calibration.train import calibration_status, load_card

    card = load_card()
    status = calibration_status()
    print(json.dumps({"status": status, "card": card}, indent=2, default=str))
    return 0 if status == "calibrated" else 1


def cmd_snapshot_build(_args: argparse.Namespace) -> int:
    """Copy the model card and label audit into the offline snapshot directory."""
    import shutil

    settings = get_settings()
    destination = settings.snapshot_data_dir
    destination.mkdir(parents=True, exist_ok=True)
    names = (
        settings.processed_data_dir / "model_card.json",
        settings.raw_data_dir.parent / "labels" / "label_audit.json",
        settings.processed_data_dir / "dot_eurostat_crosscheck.json",
    )
    copied = 0
    for path in names:
        if path.exists():
            shutil.copy2(path, destination / path.name)
            copied += 1
            print(f"  {OK} {path.name}")
    if copied == 0:
        print(f"{BAD} nothing to snapshot; build the tables and the model card first")
        return 1
    print(f"{OK} snapshot in {destination}")
    return 0


def cmd_snapshot_load(_args: argparse.Namespace) -> int:
    """Restore a snapshotted model card into the processed directory."""
    import shutil

    settings = get_settings()
    source = settings.snapshot_data_dir / "model_card.json"
    if not source.exists():
        print(f"{BAD} no snapshot at {source}")
        return 1
    settings.processed_data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, settings.processed_data_dir / "model_card.json")
    print(f"{OK} restored {source.name}")
    return 0


def cmd_qa_data(_args: argparse.Namespace) -> int:
    """Check passenger and population tables against their contracts."""
    import pandas as pd

    from epiroute.qa.contracts import check_flows, check_populations

    settings = get_settings()
    failures: list[str] = []
    flows = settings.processed_data_dir / "country_flows.parquet"
    countries = settings.processed_data_dir / "countries.parquet"
    if flows.exists():
        failures.extend(
            f"{item.check}: {item.detail}" for item in check_flows(pd.read_parquet(flows))
        )
    else:
        failures.append("flows_present: country_flows.parquet is missing")
    if countries.exists():
        failures.extend(
            f"{item.check}: {item.detail}" for item in check_populations(pd.read_parquet(countries))
        )
    if failures:
        for failure in failures:
            print(f"{BAD} {failure}")
        return 1
    print(f"{OK} data contracts passed")
    return 0


def cmd_data_check(args: argparse.Namespace) -> int:
    """Report which datasets are present, their size, age and provenance."""
    from datetime import UTC, datetime

    from epiroute.datasets.registry import DATASETS

    settings = get_settings()
    _print_header("Raw datasets")
    missing_required = 0
    for key, spec in DATASETS.items():
        path = settings.raw_data_dir / spec.filename
        if path.exists():
            stat = path.stat()
            age_days = (datetime.now(UTC).timestamp() - stat.st_mtime) / 86400
            print(f"  {OK} {key:<28} {stat.st_size / 1e6:>7.1f} MB  {age_days:>5.1f} days old")
        else:
            marker = BAD if spec.required else WARN
            print(f"  {marker} {key:<28} missing ({spec.filename})")
            if spec.required and spec.url is not None:
                missing_required += 1

    _print_header("Processed tables")
    for name in ("countries.parquet", "country_flows.parquet", "airport_routes.parquet"):
        path = settings.processed_data_dir / name
        if path.exists():
            print(f"  {OK} {name:<28} {path.stat().st_size / 1e6:>7.1f} MB")
        else:
            print(f"  {WARN} {name:<28} missing — run `just data-build`")

    if args.verbose:
        _print_header("Provenance")
        for key, spec in DATASETS.items():
            print(f"\n  {key}")
            print(f"    source:      {spec.name}")
            print(f"    url:         {spec.url or '(per-request; see module)'}")
            print(f"    licence:     {spec.licence}")
            print(f"    coverage:    {spec.coverage}")
            for limitation in spec.limitations:
                print(f"    limitation:  {limitation}")

    if missing_required:
        print(f"\n{missing_required} required dataset(s) missing — run `just data-fetch`")
        return 1
    return 0


# ---------------------------------------------------------------------------
# openapi
# ---------------------------------------------------------------------------


def cmd_data_build(args: argparse.Namespace) -> int:
    from epiroute.datasets.build import build_processed_tables

    _print_header("Building processed tables")
    result = build_processed_tables(population_year=args.population_year)
    print(f"  {OK} countries:        {result.countries:>6,}")
    print(f"  {OK} observed flows:   {result.observed_flows:>6,}")
    print(f"  {OK} modelled flows:   {result.modelled_flows:>6,}")
    print(f"  {OK} topology pairs:   {result.topology_pairs:>6,}")
    if result.gravity is None:
        print(f"  {WARN} no gravity model fitted (Eurostat table absent)")
    else:
        m = result.gravity.test_metrics
        print(
            f"  {OK} gravity model:    held-out R2(log) {m.r2_log:.3f}, "
            f"MAE {m.mae_log10:.3f} log10, band x{result.gravity.uncertainty_factor:.1f}"
        )
    for path in result.written:
        print(f"      wrote {path.name}")
    return 0


def cmd_data_load(_args: argparse.Namespace) -> int:
    from epiroute.datasets.load import load_reference_data
    from epiroute.db.session import session_scope

    _print_header("Loading reference data into PostgreSQL")
    with session_scope() as session:
        result = load_reference_data(session)
    print(f"  {OK} countries:         {result.countries:>6,}")
    print(f"  {OK} country flows:     {result.flows:>6,}")
    print(f"  {OK} dataset versions:  {result.dataset_versions:>6,}")
    print(f"  {OK} gravity fits:      {result.gravity_fits:>6,}")
    return 0


def cmd_model_fit(args: argparse.Namespace) -> int:
    from epiroute.datasets.build import build_processed_tables
    from epiroute.datasets.load import load_gravity_fit
    from epiroute.db.session import session_scope

    _print_header("Fitting the passenger-flow gravity model")
    result = build_processed_tables(population_year=args.population_year)
    if result.gravity is None:
        print(f"  {BAD} no observed passenger flows available", file=sys.stderr)
        return 1
    fit = result.gravity
    print(f"  specification: {fit.specification}")
    print(f"  training:      {fit.training_source} ({fit.training_period})")
    print(f"  rows:          {fit.n_train} train / {fit.n_test} held out (seed {fit.random_seed})")
    print(f"  intercept:     {fit.intercept:+.4f}")
    for name, value in fit.coefficients.items():
        print(f"    {name:<22} {value:+.4f}")
    _print_header("Held-out performance (measured, not asserted)")
    m = fit.test_metrics
    print(f"  R2 on log10 scale      {m.r2_log:.4f}")
    print(f"  MAE  (log10)           {m.mae_log10:.4f}")
    print(f"  RMSE (log10)           {m.rmse_log10:.4f}")
    print(f"  median ratio error     x{m.median_ratio_error:.2f}")
    print(f"  within a factor of 2   {m.within_factor_2:.1%}")
    print(f"  within a factor of 5   {m.within_factor_5:.1%}")
    print(f"  within a factor of 10  {m.within_factor_10:.1%}")
    print(f"  residual sigma(log10)  {fit.residual_sigma_log10:.4f}")
    print(f"  -> band factor         x{fit.uncertainty_factor:.1f}")
    if not args.no_db:
        with session_scope() as session:
            load_gravity_fit(session, get_settings().processed_data_dir / "gravity_fit.json")
        print(f"\n  {OK} fit stored in gravity_model_fits")
    return 0


def cmd_model_report(args: argparse.Namespace) -> int:
    """Print the gravity-model fit, or with --evaluation the whole report file."""
    if args.evaluation:
        from epiroute.calibration.report import REPORT_NAME, repository_root

        path = repository_root() / REPORT_NAME
        if not path.exists():
            print(f"{BAD} no evaluation report yet; run `just train-model`", file=sys.stderr)
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0
    path = get_settings().processed_data_dir / "gravity_fit.json"
    if not path.exists():
        print(f"{BAD} no gravity fit found; run `just model-fit`", file=sys.stderr)
        return 1
    print(json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2))
    return 0


def cmd_data_fingerprint(_args: argparse.Namespace) -> int:
    """Print what this database holds, in a form two checkouts can compare.

    Run it on both machines and diff the output. Equal digests mean the two
    agree on every figure the app would show. Different ones, with the counts
    and the extraction methods beside them, say which of the three usual causes
    it is: a different slice of the archive, a truncated ingest, or Agent
    extraction on one side and the deterministic parser on the other.
    """
    from epiroute.db.session import session_scope
    from epiroute.ingestion import manifest as manifest_module
    from epiroute.repositories.outbreaks import grounded_fingerprint

    settings = get_settings()
    with session_scope() as session:
        fingerprint = grounded_fingerprint(session)
    committed = manifest_module.load(manifest_module.manifest_path(settings.raw_data_dir.parent))
    fingerprint["archive_manifest_digest"] = committed.digest if committed else None
    fingerprint["archive_manifest_records"] = len(committed.records) if committed else 0
    fingerprint["tinyfish_key_present"] = bool(settings.tinyfish_api_key)
    print(json.dumps(fingerprint, indent=2, default=str))
    return 0


def cmd_data_validate(_args: argparse.Namespace) -> int:
    from epiroute.datasets.validate import validate_processed_tables

    _print_header("Validating processed tables")
    report = validate_processed_tables()
    for check in report.checks:
        marker = OK if check.passed else BAD
        print(f"  {marker} {check.name:<44} {check.detail}")
    print(f"\n{report.passed_count}/{len(report.checks)} checks passed")
    return 0 if report.ok else 1


def _warn_about_reproducibility(use_agent: bool, limit: int | None) -> None:
    """Say, before the ingest, what would make this database differ from another's.

    Both of these are invisible afterwards and both change the stored figures.
    The Agent and the deterministic parser read different numbers out of the
    same prose, and a limit covers a different slice of the archive, so two
    checkouts of one commit can disagree with nothing to point at.
    """
    if use_agent:
        print(
            f"  {BAD} Agent extraction is on. Its figures will not match a checkout "
            "without TINYFISH_API_KEY, which uses the deterministic parser. For "
            "identical data on two machines use: just data-archive && just ingest-archive"
        )
    if limit is not None:
        print(
            f"  {BAD} --limit {limit} covers only part of the archive, so this database "
            "will not match one built without it"
        )


def cmd_ingest(args: argparse.Namespace) -> int:
    from epiroute.db.session import session_scope
    from epiroute.ingestion.pipeline import run_ingestion

    settings = get_settings()
    _print_header("Ingesting WHO Disease Outbreak News")
    print(f"  tinyfish: {'enabled' if settings.tinyfish_enabled else 'not configured'}")
    print(f"  agent:    {'enabled' if not args.no_agent else 'disabled'}")
    _warn_about_reproducibility(settings.tinyfish_enabled and not args.no_agent, args.limit)
    with session_scope() as session:
        summary = run_ingestion(
            session, limit=args.limit, use_agent=not args.no_agent, trigger=args.trigger
        )
    print(f"\n  run id:               {summary.run_id}")
    print(f"  mode:                 {summary.mode}")
    print(f"  status:               {summary.status}")
    print(f"  records seen:         {summary.records_seen}")
    print(f"  records created:      {summary.records_created}")
    print(f"  records updated:      {summary.records_updated}")
    print(f"  records skipped:      {summary.records_skipped}")
    print(f"  observations stored:  {summary.observations_created}")
    print(f"  of which unverified:  {summary.observations_unverified}")
    if summary.warnings:
        codes: dict[str, int] = {}
        for warning in summary.warnings:
            code = str(warning.get("code"))
            codes[code] = codes.get(code, 0) + 1
        _print_header("Validation warnings (rejected values)")
        for code, count in sorted(codes.items(), key=lambda kv: -kv[1]):
            print(f"  {count:>5}  {code}")
    for error in summary.errors:
        print(f"  {BAD} {error}", file=sys.stderr)
    return 0 if summary.status == "succeeded" else 1


def cmd_data_archive(args: argparse.Namespace) -> int:
    import json

    from epiroute.ingestion.who_don import fetch_full_archive

    settings = get_settings()
    _print_header("Downloading the full WHO Disease Outbreak News archive")
    payload = fetch_full_archive(settings=settings, max_pages=args.max_pages)
    items = payload["value"]
    target = settings.raw_data_dir / "who_don_archive.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")
    dates = sorted(
        str(i.get("PublicationDate") or "")[:10] for i in items if i.get("PublicationDate")
    )
    print(f"  records: {len(items)}")
    if dates:
        print(f"  range:   {dates[0]} to {dates[-1]}")
    print(f"  written: {target}")

    # The manifest is committed and the archive is not, so this is what lets a
    # second checkout find out which bulletins it is missing instead of
    # wondering why its totals differ.
    from epiroute.ingestion import manifest as manifest_module

    built = manifest_module.build([item for item in items if isinstance(item, dict)])
    manifest_file = manifest_module.manifest_path(settings.raw_data_dir.parent)
    previous = manifest_module.load(manifest_file)
    if args.write_manifest:
        manifest_file.write_text(built.to_json(), encoding="utf-8")
        print(f"  manifest: written to {manifest_file} ({len(built.records)} records)")
    elif previous is not None:
        for line in manifest_module.compare(previous, built).describe():
            print(f"  manifest: {line}")
    else:
        print("  manifest: none committed yet; write one with --write-manifest")
    return 0 if items else 1


def cmd_ingest_archive(args: argparse.Namespace) -> int:
    from epiroute.db.session import session_scope
    from epiroute.ingestion.pipeline import ingest_records
    from epiroute.ingestion.who_don import load_archive

    settings = get_settings()
    path = settings.raw_data_dir / "who_don_archive.json"
    if not path.exists():
        print(f"  {BAD} {path} is missing; run `epiroute data-archive` first", file=sys.stderr)
        return 1

    _print_header("Ingesting the local WHO DON archive")

    # Say up front whether this machine is working from the same bulletins as
    # the manifest in the repository. An ingest that silently covers a
    # different set is the reason two checkouts disagree.
    import json as _json

    from epiroute.ingestion import manifest as manifest_module

    committed = manifest_module.load(manifest_module.manifest_path(settings.raw_data_dir.parent))
    if committed is not None:
        payload = _json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("value") if isinstance(payload, dict) else payload
        found = manifest_module.build([item for item in items or [] if isinstance(item, dict)])
        for line in manifest_module.compare(committed, found).describe():
            print(f"  manifest: {line}")

    records = load_archive(path, settings=settings, limit=args.limit)
    print(f"  records on disk: {len(records)}")
    if args.limit is not None:
        print(
            f"  {BAD} --limit {args.limit} truncates the ingest, so this database will "
            "not match one built without it"
        )
    with session_scope() as session:
        summary = ingest_records(
            session, records, settings=settings, client=None, use_agent=False, trigger="manual"
        )
    print(f"  records created:      {summary.records_created}")
    print(f"  records updated:      {summary.records_updated}")
    print(f"  records skipped:      {summary.records_skipped}")
    print(f"  observations stored:  {summary.observations_created}")
    print(f"  of which unverified:  {summary.observations_unverified}")
    return 0


def cmd_api_check(args: argparse.Namespace) -> int:
    import httpx

    base = args.base_url.rstrip("/")
    checks: list[tuple[str, str]] = [
        ("health", "/health"),
        ("countries", "/api/v1/countries"),
        ("outbreaks", "/api/v1/outbreaks?limit=5"),
        ("outbreak detail", "/api/v1/outbreaks?limit=1"),
        ("routes", "/api/v1/routes?limit=5"),
        ("sources", "/api/v1/sources"),
        ("pathogens", "/api/v1/pathogens"),
        ("gravity model", "/api/v1/model/gravity"),
        ("runs", "/api/v1/runs?limit=3"),
        ("risk (BEL)", "/api/v1/risk/BEL?horizon_days=14"),
        ("risk unknown country", "/api/v1/risk/QQQ"),
        ("risk bad parameter", "/api/v1/risk/BEL?horizon_days=9999"),
    ]
    expected_failures = {"risk unknown country": 404, "risk bad parameter": 422}

    _print_header(f"API check against {base}")
    failures = 0
    with httpx.Client(timeout=30.0) as client:
        for label, path in checks:
            try:
                response = client.get(f"{base}{path}")
            except httpx.HTTPError as exc:
                print(f"  {BAD} {label:<22} unreachable ({type(exc).__name__})")
                failures += 1
                continue
            want = expected_failures.get(label, 200)
            marker = OK if response.status_code == want else BAD
            if response.status_code != want:
                failures += 1
            size = len(response.content)
            print(f"  {marker} {label:<22} {response.status_code} (expected {want}) {size:>7,}B")

        detail = client.get(f"{base}/api/v1/outbreaks?limit=1").json()
        if detail.get("items"):
            report_id = detail["items"][0]["id"]
            response = client.get(f"{base}/api/v1/outbreaks/{report_id}")
            marker = OK if response.status_code == 200 else BAD
            if response.status_code != 200:
                failures += 1
            print(f"  {marker} {'outbreak by id':<22} {response.status_code}")

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print(f"all {len(checks) + 1} checks passed")
    return 0


def cmd_openapi(args: argparse.Namespace) -> int:
    """Write the OpenAPI schema to a file."""
    import pathlib

    from epiroute.main import create_app

    schema = create_app().openapi()
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{OK} wrote {output} ({len(schema.get('paths', {}))} paths)")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

Command = Callable[[argparse.Namespace], int]


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="epiroute",
        description="EpiRoute operations CLI. Prefer the root justfile recipes.",
    )
    parser.add_argument(
        "--log-level", default=None, help="Override the configured log level for this run."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("config-check", help="Validate configuration.")
    p.add_argument("--quiet", action="store_true", help="Print only failures.")
    p.set_defaults(func=cmd_config_check)

    p = subparsers.add_parser("db-status", help="Show database state and row counts.")
    p.add_argument("--quiet", action="store_true", help="Print a single status line.")
    p.set_defaults(func=cmd_db_status)

    p = subparsers.add_parser("data-fetch", help="Download reference datasets.")
    p.add_argument("--force", action="store_true", help="Re-download existing files.")
    p.add_argument("--only", nargs="*", default=None, help="Restrict to these dataset keys.")
    p.set_defaults(func=cmd_data_fetch)

    p = subparsers.add_parser("data-check", help="Report dataset presence and provenance.")
    p.add_argument("--verbose", action="store_true", help="Include full provenance.")
    p.set_defaults(func=cmd_data_check)

    p = subparsers.add_parser("data-build", help="Build processed tables from data/raw.")
    p.add_argument("--population-year", type=int, default=2024)
    p.set_defaults(func=cmd_data_build)

    p = subparsers.add_parser("data-load", help="Load processed tables into PostgreSQL.")
    p.set_defaults(func=cmd_data_load)

    p = subparsers.add_parser("data-validate", help="Validate the processed tables.")
    p.set_defaults(func=cmd_data_validate)

    p = subparsers.add_parser("labels-build", help="Download historical first-report dates.")
    p.set_defaults(func=cmd_labels_build)

    p = subparsers.add_parser(
        "train-model", help="Fit the hazard, write the model card and the evaluation report."
    )
    p.add_argument(
        "--rebuild-panel",
        action="store_true",
        help="Rebuild the training panel from the processed tables first.",
    )
    p.set_defaults(func=cmd_train_model)

    p = subparsers.add_parser("validate-model", help="Show whether the model card passed.")
    p.set_defaults(func=cmd_validate_model)

    p = subparsers.add_parser("qa-data", help="Check processed tables against data contracts.")
    p.set_defaults(func=cmd_qa_data)

    p = subparsers.add_parser("snapshot-build", help="Copy the model card into data/snapshot.")
    p.set_defaults(func=cmd_snapshot_build)

    p = subparsers.add_parser("snapshot-load", help="Restore the snapshotted model card.")
    p.set_defaults(func=cmd_snapshot_load)

    p = subparsers.add_parser("model-fit", help="Fit the gravity model and report held-out error.")
    p.add_argument("--population-year", type=int, default=2024)
    p.add_argument("--no-db", action="store_true", help="Do not store the fit in the database.")
    p.set_defaults(func=cmd_model_fit)

    p = subparsers.add_parser("model-report", help="Print the stored gravity-model report.")
    p.add_argument(
        "--evaluation",
        action="store_true",
        help="Print MODEL_EVALUATION.md instead of the gravity fit.",
    )
    p.set_defaults(func=cmd_model_report)

    p = subparsers.add_parser("ingest", help="Run a WHO Disease Outbreak News ingestion pass.")
    p.add_argument("--limit", type=int, default=None, help="Maximum records to ingest.")
    p.add_argument("--no-agent", action="store_true", help="Skip TinyFish Agent extraction.")
    p.add_argument("--trigger", default="manual", choices=["manual", "webhook", "scheduled"])
    p.set_defaults(func=cmd_ingest)

    p = subparsers.add_parser(
        "data-archive", help="Download every page of the WHO Disease Outbreak News archive."
    )
    p.add_argument("--max-pages", type=int, default=200)
    p.add_argument(
        "--write-manifest",
        action="store_true",
        help="Record the downloaded bulletins in data/who_don_manifest.json for commit.",
    )
    p.set_defaults(func=cmd_data_archive)

    p = subparsers.add_parser(
        "data-fingerprint",
        help="Print a comparable summary of every grounded figure in this database.",
    )
    p.set_defaults(func=cmd_data_fingerprint)

    p = subparsers.add_parser(
        "ingest-archive", help="Ingest the locally stored WHO DON archive without network calls."
    )
    p.add_argument("--limit", type=int, default=None, help="Maximum records to ingest.")
    p.set_defaults(func=cmd_ingest_archive)

    p = subparsers.add_parser("api-check", help="Smoke-check a running API.")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.set_defaults(func=cmd_api_check)

    p = subparsers.add_parser("openapi", help="Write the OpenAPI schema to a file.")
    p.add_argument("--output", required=True, help="Destination path.")
    p.set_defaults(func=cmd_openapi)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Returns:
        A process exit code: 0 on success, 1 on a reported failure, 2 on an
        unexpected exception.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    settings: Settings = get_settings()
    configure_logging(args.log_level or settings.log_level)

    command: Command = args.func
    try:
        return command(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception:
        # Deliberate top-level boundary: print the traceback for an operator
        # rather than letting argparse's caller swallow it.
        logger.exception("command failed", extra={"command": args.command})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
