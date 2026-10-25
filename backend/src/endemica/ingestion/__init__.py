"""Outbreak-report acquisition, extraction and validation.

The pipeline is deliberately linear and auditable:

1. :mod:`endemica.ingestion.who_don` — acquire bulletins from the WHO
   Disease Outbreak News API.
2. :mod:`endemica.ingestion.html_text` — render the narrative HTML to plain
   text, which becomes the grounding reference.
3. :mod:`endemica.ingestion.extraction` — obtain structured fields, either
   through the TinyFish Agent or the deterministic parser.
4. :mod:`endemica.ingestion.grounding` — check every extracted value against
   the source text. **Nothing reaches a model input without passing here.**
5. :mod:`endemica.ingestion.validate` — ISO normalisation, numeric and date
   sanity, deduplication.
6. :mod:`endemica.ingestion.pipeline` — orchestration, run records and
   failure isolation.

Extracted content is untrusted input throughout (AGENTS.md section 14.2).
"""
