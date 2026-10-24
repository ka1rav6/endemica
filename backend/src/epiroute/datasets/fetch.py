"""Downloading reference datasets into ``data/raw``.

Design rules that matter for AGENTS.md section 13:

* **Never overwrite good data with a failure.** A download goes to a temporary
  file in the same directory and is moved into place only after it completes,
  so an interrupted transfer cannot truncate an existing dataset.
* **Idempotent.** A file already present is skipped unless ``force`` is set, so
  ``just data-fetch`` is cheap to re-run.
* **Recorded.** Each successful download returns its size and SHA-256 so the
  caller can write a ``dataset_versions`` row.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from epiroute.core.clock import utc_now
from epiroute.core.config import Settings, get_settings
from epiroute.core.errors import ExternalServiceError
from epiroute.core.http import build_client, request_with_retry
from epiroute.datasets.registry import DOWNLOADABLE, DatasetSpec, get_spec

logger = logging.getLogger(__name__)

# Read in 1 MiB chunks: large enough to be efficient, small enough that the
# 17 MB UN population file does not sit in memory twice.
_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Outcome of one dataset download.

    Attributes:
        key: Dataset key from the registry.
        path: Where the file now is.
        bytes_written: Size on disk. 0 when the download was skipped.
        sha256: Hex digest of the file's content.
        skipped: True when an existing file was reused.
        error: Failure message, or ``None`` on success.
    """

    key: str
    path: Path
    bytes_written: int
    sha256: str | None
    skipped: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the dataset is now present on disk."""
        return self.error is None


def file_sha256(path: Path) -> str:
    """Return the hex SHA-256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_dataset(
    key: str, *, settings: Settings | None = None, force: bool = False
) -> FetchResult:
    """Download one registered dataset into ``data/raw``.

    Args:
        key: Dataset key from :mod:`epiroute.datasets.registry`.
        settings: Settings override, used by tests.
        force: Re-download even when the file exists.

    Returns:
        A :class:`FetchResult`. Failures are returned rather than raised, so
        one unavailable source does not abort the whole fetch.

    Raises:
        KeyError: If the key is not registered.
        ValueError: If the dataset has no direct download URL.
    """
    settings = settings or get_settings()
    spec = get_spec(key)
    if spec.url is None:
        msg = (
            f"dataset '{key}' has no direct download URL; it is acquired by "
            f"its own module (see docs/data-sources.md)"
        )
        raise ValueError(msg)

    target = settings.raw_data_dir / spec.filename
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and not force:
        logger.info("dataset already present", extra={"dataset": key, "path": str(target)})
        return FetchResult(
            key=key,
            path=target,
            bytes_written=0,
            sha256=file_sha256(target),
            skipped=True,
        )

    logger.info("downloading dataset", extra={"dataset": key, "url": spec.url})
    # Write to a sibling temporary file so the move into place is atomic on the
    # same filesystem; a failed transfer then leaves the previous file intact.
    fd, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{spec.filename}.", suffix=".part"
    )
    temporary = Path(temp_name)
    written = 0
    try:
        with build_client(settings) as client:
            response = request_with_retry(client, "GET", spec.url, service=spec.name)
            if response.status_code != 200:
                msg = f"HTTP {response.status_code}"
                raise ExternalServiceError(spec.name, msg, status_code=response.status_code)
            with open(fd, "wb") as handle:  # noqa: PTH123 - fd from mkstemp
                for chunk in response.iter_bytes(_CHUNK_SIZE):
                    handle.write(chunk)
                    written += len(chunk)
        if written == 0:
            msg = "response body was empty"
            raise ExternalServiceError(spec.name, msg)
        temporary.replace(target)
    except (ExternalServiceError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        logger.warning(
            "dataset download failed; existing file left untouched",
            extra={"dataset": key, "error": str(exc)},
        )
        return FetchResult(
            key=key, path=target, bytes_written=0, sha256=None, skipped=False, error=str(exc)
        )

    digest = file_sha256(target)
    logger.info(
        "dataset downloaded",
        extra={
            "dataset": key,
            "path": str(target),
            "bytes": written,
            "sha256": digest[:12],
            "retrieved_at": utc_now().isoformat(),
        },
    )
    return FetchResult(key=key, path=target, bytes_written=written, sha256=digest, skipped=False)


def fetch_all(
    *, settings: Settings | None = None, force: bool = False, only: list[str] | None = None
) -> list[FetchResult]:
    """Download every registered dataset that has a direct URL.

    Args:
        settings: Settings override.
        force: Re-download files that already exist.
        only: Restrict to these dataset keys.

    Returns:
        One :class:`FetchResult` per attempted dataset, in registry order.
    """
    specs: tuple[DatasetSpec, ...] = DOWNLOADABLE
    if only:
        wanted = set(only)
        specs = tuple(s for s in specs if s.key in wanted)
    return [fetch_dataset(spec.key, settings=settings, force=force) for spec in specs]
