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

    from epiroute.db.base import Base
    from epiroute.db import models  # noqa: F401
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

    if failures:
        print(f"\n{failures} of {len(results)} datasets failed. Existing files were not modified.")
        return 1
    print(f"\n{len(results)} datasets ready in {get_settings().raw_data_dir}")
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
