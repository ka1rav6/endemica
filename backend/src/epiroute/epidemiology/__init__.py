"""Epidemiological models.

Every module here is pure computation over plain Python and NumPy types: no
HTTP, no database, no FastAPI. That is what makes the models testable against
analytic results and keeps the three risk concepts separable:

* :mod:`epiroute.epidemiology.prevalence` — origin prevalence I/N with its
  under-reporting band.
* :mod:`epiroute.epidemiology.importation` — arrival rate lambda and
  P(at least one infected arrival within T).
* :mod:`epiroute.epidemiology.establishment` — branching-process probability
  that an introduction leads to sustained local transmission.
* :mod:`epiroute.epidemiology.effective_distance` — Brockmann-Helbing
  effective distance over the passenger-flow network.
* :mod:`epiroute.epidemiology.profiles` — per-pathogen parameter profiles,
  each carrying the citation for its values.
* :mod:`epiroute.epidemiology.scenario` — upper-band threshold markers.

A passing test here establishes that the implementation matches its documented
equation. It does **not** establish that the model predicts real outbreaks;
see docs/epidemiological-models.md section "Validation".
"""
