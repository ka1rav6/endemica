# TinyFish fixtures

Real responses captured from the live TinyFish API on **24 October 2026**, used
so the ingestion tests are deterministic and do not spend Agent credits
(AGENTS.md section 8.5).

| File | Endpoint | Notes |
|---|---|---|
| `fetch_don622_response.json` | `POST https://api.fetch.tinyfish.ai` | WHO DON 2026-DON622 as markdown. `published_date` came back `null`, which is why EpiRoute takes the publication date from the WHO API instead. |
| `agent_run_don622_completed.json` | `GET https://agent.tinyfish.ai/v1/runs/{id}` | A `COMPLETED` run over the same page, 8 steps. The per-step trace was removed; nothing in EpiRoute reads it. |
| `search_who_response.json` | `GET https://api.search.tinyfish.ai` | Discovery results restricted to `who.int`. |

## Why the Agent fixture matters

This is a genuine Agent response, and it is **wrong in several places**. That
is the point: it is the test case for the validation gate, not an example of
correct extraction. Verified against the Fetch text of the same page:

| Row | Field | Reported | Problem | Caught by |
|---|---|---|---|---|
| 0 | `cases_suspected` | 9291 | The number appears nowhere in the source document | value grounding |
| 2 | `cases_suspected` | 123 | Appears nowhere in the source document | value grounding |
| 1, 3 | `cases_suspected` | 430, 3 | In the document, but not in the sentence the row cites | evidence-local grounding |
| 6 | `deaths` | 4687 | Borrowed from a different sentence about cumulative deaths | evidence-local grounding |
| 4 | `cases_suspected` | 2595 | The source says "2595 **recoveries**" | label proximity |
| 5 | `deaths` / `cases_suspected` | 976 / 482 | Swapped: the source says "976 confirmed **cases**, including 482 confirmed **deaths**" | label proximity |
| 7 | `cases_confirmed` | 1286 | Taken from a vaccination-coverage ratio "1286/1430", not a case count | label proximity |

Only one of the eight rows survives the gate unmodified. Structured extraction
does not guarantee correctness, which is why nothing reaches a model input
without being grounded in the source text first.
