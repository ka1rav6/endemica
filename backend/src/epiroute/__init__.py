"""EpiRoute — outbreak intelligence over the air-travel network.

The package is organised as a modular monolith:

* :mod:`epiroute.core` — configuration, logging and shared error types.
* :mod:`epiroute.schemas` — Pydantic models forming the API contract.
* :mod:`epiroute.db` — SQLAlchemy models, session handling and migrations.
* :mod:`epiroute.datasets` — acquisition and normalisation of reference data.
* :mod:`epiroute.epidemiology` — the mathematical models, free of I/O.
* :mod:`epiroute.ingestion` — WHO Disease Outbreak News acquisition pipeline.
* :mod:`epiroute.tinyfish` — the TinyFish HTTP client and extraction goals.
* :mod:`epiroute.repositories` — persistence boundary.
* :mod:`epiroute.services` — application logic coordinating the above.
* :mod:`epiroute.api` — FastAPI routers; no computation lives here.

Dependencies point inwards: ``api -> services -> repositories/epidemiology``.
"""

__version__ = "0.1.0"
