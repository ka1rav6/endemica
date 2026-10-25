"""Endemica — outbreak intelligence over the air-travel network.

The package is organised as a modular monolith:

* :mod:`endemica.core` — configuration, logging and shared error types.
* :mod:`endemica.schemas` — Pydantic models forming the API contract.
* :mod:`endemica.db` — SQLAlchemy models, session handling and migrations.
* :mod:`endemica.datasets` — acquisition and normalisation of reference data.
* :mod:`endemica.epidemiology` — the mathematical models, free of I/O.
* :mod:`endemica.ingestion` — WHO Disease Outbreak News acquisition pipeline.
* :mod:`endemica.tinyfish` — the TinyFish HTTP client and extraction goals.
* :mod:`endemica.repositories` — persistence boundary.
* :mod:`endemica.services` — application logic coordinating the above.
* :mod:`endemica.api` — FastAPI routers; no computation lives here.

Dependencies point inwards: ``api -> services -> repositories/epidemiology``.
"""

__version__ = "0.1.0"
