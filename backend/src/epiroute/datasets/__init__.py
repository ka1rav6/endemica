"""Reference-data acquisition and normalisation.

Each module here owns one external dataset: it knows the source URL, the
licence, how to parse the file and what the result means. The
:mod:`epiroute.datasets.registry` module is the single place where source
metadata lives, so `just data-check` and ``GET /health`` can report provenance
without any module having to be imported.

The pipeline is: ``data-fetch`` (download to ``data/raw``) ->
``data-build`` (normalise into ``data/processed``) -> ``data-load``
(insert into PostgreSQL). Each step is idempotent.
"""
