# Endemica — Implementation & Preparation Plan

HackIIITD 2026 (Esya '26, IIIT Delhi) · prepared 15 Oct 2026

This is the team's working document. Judges will not read it; the deck stands alone.

---

## 0. What the official page actually says (checked 15 Oct 2026 on Unstop)

| Item | Requirement | Status |
|---|---|---|
| Round 1 deadline | 16 Oct 2026, 11:59 PM IST | verified |
| Format | PPT or PDF via Unstop | verified |
| Length | "around 8 to 9 slides in total (not more than that)" | verified — our deck is 9 |
| Must cover | Team details, problem statement, proposed solution, target users, technical architecture & stack, TinyFish integration plan, scalability/feasibility/use case, MVP/prototype (optional) | verified — mapped below |
| TinyFish slide | A dedicated slide titled **"How do you plan to integrate the TinyFish API?"** | verified — slide 5 uses this exact title |
| Code / links | No deployed links or coded material in Round 1; "may result in negative marking". A Figma-style UI prototype is allowed | verified — deck has a concept UI built from shapes, no repo or URL |
| Scoring | "Total: 25 Marks"; per-criterion rubric not published | rubric **unverified** |
| Shortlist | ~60–70 teams to the offline finale | verified |
| Finale | 24-hour offline hack at IIIT Delhi, 24–25 Oct 2026; judged on execution, innovation, scalability, TinyFish API usage, impact | verified |
| Team | 2–4 members, cross-college allowed, every member should create a TinyFish account | verified |
| TinyFish | "Projects that do not use it will not be considered" | verified |
| Pre-written code before the finale | Not addressed on the page | **unverified — ask in the official WhatsApp group before writing app code early** |

Deck-to-requirement map: 1 Team · 2 Problem + target users · 3 Solution + concept UI (prototype) · 4 Method · 5 TinyFish (exact title) · 6 Architecture & stack · 7 Data & validation · 8 Scalability, feasibility, use case · 9 Safeguards, roadmap, references.

**Before submitting:** replace every `[bracketed]` placeholder on slide 1, export to PDF as a backup, and check the file opens on a machine without Calibri (it falls back cleanly to Carlito/Arial).

---

## 1. Product in one paragraph

An interactive world map that (a) shows sourced, current outbreak reports, (b) shows which destinations are linked to them by air, directly or through hubs, and (c) for a selected destination shows three **separate** quantities — already present, ≥1 infected arrival within T days, and sustained local transmission — each as a low/central/high range with its inputs on sliders and its sources one click away. A scenario timeline replaces the original "last safe day to leave" idea; it is a threshold marker under stated worst-case assumptions, never a safety date.

Non-goals: diagnosis, official forecasts, individual medical or travel advice.

---

## 2. Architecture

```
            ┌──────────────────────────── SOURCES ────────────────────────────┐
            │ WHO DON API (JSON) · report pages (WHO/ECDC/PAHO/Africa CDC)     │
            │ OpenFlights · BTS T-100 · Eurostat · OpenSky (Zenodo)            │
            │ WorldPop/UN pop · OWID · JHU CSSE · OxCGRT · Natural Earth       │
            └───────┬──────────────────────────────┬───────────────────────────┘
                    │ live                          │ bulk, pre-downloaded
     ┌──────────────▼──────────────┐       ┌───────▼──────────────────┐
     │ 1 ACQUIRE                    │       │ 1b BULK LOADERS (pandas)  │
     │ TinyFish Search (discover)   │       │ CSV/Parquet → tidy tables │
     │ TinyFish Monitor (webhook)   │       └───────┬──────────────────┘
     │ WHO DON API poll             │               │
     └──────────────┬──────────────┘               │
     ┌──────────────▼──────────────┐               │
     │ 2 EXTRACT                    │               │
     │ TinyFish Fetch → markdown    │               │
     │ TinyFish Agent + output_schema│              │
     └──────────────┬──────────────┘               │
     ┌──────────────▼──────────────┐               │
     │ 3 VALIDATE & DEDUPE          │               │
     │ pydantic · ISO-3 · grounding │               │
     └──────────────┬──────────────┘               │
     ┌──────────────▼───────────────────────────────▼──┐
     │ 4 STORE  SQLite (records, runs, flags) + Parquet │
     └──────────────┬──────────────────────────────────┘
     ┌──────────────▼──────────────┐
     │ 5 FEATURES  prevalence band, │
     │ passenger matrix F, eff. dist│
     ├─────────────────────────────┤
     │ 6 MODEL  λ, P(import),       │
     │ P(establish), markers, bands │
     └──────────────┬──────────────┘
     ┌──────────────▼──────────────┐      ┌─────────────────────────────┐
     │ 7 FastAPI (JSON)             │◀────▶│ 8–9 React + MapLibre + deck.gl│
     │ /outbreaks /risk /routes ... │      │ map · panel · sliders · timeline│
     └─────────────────────────────┘      └─────────────────────────────┘
     10 Freshness & errors: every response carries retrieved_at + status; cached snapshot fallback.
```

| # | Component | Why it exists |
|---|---|---|
| 1 | Acquisition | Live reports arrive irregularly; Monitor + polling avoid manual refresh |
| 2 | Extraction (TinyFish) | Counts/places/dates live in prose; many official sources have no API |
| 3 | Validation | An extractor can be wrong; nothing unverified should look like data |
| 4 | Storage | SQLite is zero-ops; Parquet keeps the passenger matrix fast |
| 5 | Feature engineering | Converts observations to model inputs and keeps the observed/estimated label |
| 6 | Risk model | Transparent formulas from the briefing note; bands not points |
| 7 | API | One small service, cacheable, testable with fixtures |
| 8 | Map | The product is spatial; MapLibre (open, no token) + deck.gl ArcLayer |
| 9 | Scenario controls | Every assumption visible and movable |
| 10 | Freshness / errors | Demo must survive API failures; users must see data age |

### Stack decision

| Layer | Choice | Rejected / why |
|---|---|---|
| Frontend | React + TypeScript + Vite | Next.js: SSR unneeded |
| Map | MapLibre GL JS + deck.gl (ArcLayer, ScatterplotLayer) | Mapbox: token + billing; Leaflet: weak for arcs at scale |
| Charts | Recharts (small) | — |
| Backend | Python 3.11 + FastAPI + httpx + pydantic v2 | Node: the model and data work are in Python |
| Data | pandas, NumPy, networkx | scikit-learn only if the gravity model needs regularisation |
| Store | SQLite + Parquet | PostGIS: not needed at country resolution |
| Jobs | Manual `POST /admin/ingest` + optional APScheduler | Celery/queues: overkill |
| Deploy (finale only) | Local laptop; optional single container | Kubernetes/microservices: no |

---

## 3. TinyFish integration (verified against docs.tinyfish.ai, 15 Oct 2026)

All calls are **server-side**. Key in `TINYFISH_API_KEY` env var, loaded via `.env` that is in `.gitignore`. Never log request headers.

| Product | Endpoint (from docs) | Use in Endemica | Limits / cost (docs & pricing page) |
|---|---|---|---|
| Search | `GET https://api.search.tinyfish.ai` params `query`, `include_domains`, `recency_minutes`, `domain_type` | Discover new reports on who.int, ecdc.europa.eu, paho.org, africacdc.org | Free; 30 req/min. Pricing page says 500/hour; reference page says 12,000/day — treat 500/hour as the binding limit |
| Fetch | `POST https://api.fetch.tinyfish.ai` body `urls` (≤10), `format` (`markdown`/`json`/`html`), `include_etag_and_last_modified`, `ttl` | Report page → clean text + `published_date`; text is also the grounding reference | Free up to 1,000 successful URLs/day; 150 URLs/min; client timeout ≥150 s |
| Agent | `POST https://agent.tinyfish.ai/v1/automation/run-async` body `url`, `goal`, `output_schema`; poll `GET /v1/runs/{id}` (statuses PENDING/RUNNING/COMPLETED/FAILED/CANCELLED) | Structured extraction from narrative pages; multi-page navigation where there is no API; border-policy pages → σ flag | $0.016/step; 2 concurrent runs; new wallets start with $8 (≈500 steps). `max_steps` is beta-gated (403 if not enabled) — do not send it |
| Monitor | REST (see /monitor/api-reference) | Page monitor on the WHO DON listing and ECDC weekly threat report → webhook to `/hooks/tinyfish` | $0.005/completed run; ≤50 monitors; webhook posts every run (dedupe by content hash) |

Auth for all: header `X-API-Key: $TINYFISH_API_KEY`.

Error handling: 401 → stop and alert; 402 (`INSUFFICIENT_CREDITS`) → switch to Fetch-only mode; 429 → back off using `retry_after` when present; run-level `SITE_BLOCKED`/`TIMEOUT`/`TASK_FAILED` → mark record `extraction_failed`, keep the source link on the map with "details unavailable".

### Agent extraction contract

```json
{
  "url": "<report page>",
  "goal": "Read this public-health outbreak report. Return the disease name exactly as written, every country and sub-national place mentioned as affected, confirmed/probable/suspected case counts and deaths with the period they cover, and the report date. Copy the sentence each number came from into evidence. If a value is not stated, return null. Do not infer or calculate numbers.",
  "output_schema": {
    "type": "object",
    "properties": {
      "disease": {"type": "string"},
      "report_date": {"type": ["string","null"]},
      "locations": {"type": "array", "items": {"type": "object", "properties": {
        "country": {"type": "string"}, "subnational": {"type": ["string","null"]},
        "cases_confirmed": {"type": ["integer","null"]}, "cases_suspected": {"type": ["integer","null"]},
        "deaths": {"type": ["integer","null"]}, "period": {"type": ["string","null"]},
        "evidence": {"type": "string"}}, "required": ["country","evidence"]}}
    },
    "required": ["disease","locations"]
  }
}
```

Check the schema against the Structured Output allowlist (`/key-concepts/structured-output`) before the event; unsupported keywords are rejected before execution. If `["integer","null"]` unions are rejected, use plain types and treat sentinel values as null.

### Validation gate (our code, not TinyFish)

1. pydantic parse; reject on schema error.
2. Country name → ISO-3 via a fixed lookup table (pycountry + manual aliases such as "Türkiye", "DR Congo").
3. **Grounding:** each extracted integer must appear in the Fetch text (also try with thousands separators/spaces, e.g. `1 234`, `1,234`) and `evidence` must be a substring of the Fetch text. Fail → `status: unverified` (shown greyed, excluded from the model).
4. Sanity: counts ≥ 0, deaths ≤ cases when both exist, report date ≤ retrieved date.
5. Dedupe on (`source_url`, country, period).
6. Write provenance: `source_url`, `run_id`, `retrieved_at`, `published_at`, `status`, `warnings`.

### σ policy flag (P1)

Agent goal on an official government entry-requirements page: return `{measure: "entry screening|quarantine|ban|none stated", applies_to, effective_date, evidence}`. Stored as `pending_review`; a human clicks "confirm" in an admin view before σ changes. Default σ = 0 with a visible "no confirmed measure" label.

### WHO DON API facts we checked

- `https://www.who.int/api/news/diseaseoutbreaknews` returns OData JSON with `value[]` items containing `Title`, `PublicationDate`, `PublicationDateAndTime`, `DonId`, `UrlName`, `ItemDefaultUrl`, `Summary`, `Overview`, `Epidemiology`, `Assessment`, `Advice`, `Response`, `FurtherInformation` (HTML strings).
- Default ordering is **not** by date, and `Epidemiology` is often null or empty; counts are commonly in `Overview` prose.
- OData `$orderby` / `$top` behaviour was **not confirmed** through our fetch tool (the redirect dropped the query). Test `?$orderby=PublicationDateAndTime desc&$top=50` with curl before the event. Fallback: page through and sort locally.
- Public item pages are `https://www.who.int/emergencies/disease-outbreak-news/item/<UrlName>`; confirm the pattern on 3 recent items.

---

## 4. Data-source inventory

| Source | Contains | Resolution | Live/historical | Access | Licence (verify) | Biases / missingness | Role | Fallback |
|---|---|---|---|---|---|---|---|---|
| WHO DON API | Outbreak bulletins | Event, country | Live + archive since 1996 | Free JSON | WHO terms | Publication lag; counts in prose | Live outbreak layer | Cached snapshot |
| WHO/ECDC/PAHO/Africa CDC pages | Reports, alerts | Event | Live | TinyFish Fetch/Agent | Each site's terms | Inconsistent formats | Extra outbreaks, context | WHO only |
| OWID covid-19-data | Cases, tests | Country-day | Historical (archived) | GitHub CSV | CC BY | Testing-dependent | Calibration prevalence | JHU archive |
| JHU CSSE archive | Cases | Country/admin-day, to Mar 2023 | Historical | GitHub CSV | CC BY 4.0 (verify) | Same | First-case dates, cross-check | OWID |
| OxCGRT | Border/travel policy | Country-day, 2020–2022 | Historical | GitHub CSV | CC BY 4.0 | Coding judgement | σ in calibration | Manual flags |
| Nextstrain | Lineage introductions | Lineage | Historical | Builds/visualisation; sequences via GISAID (gated) | Per build | Sequencing coverage uneven | Better arrival label | First-case dates |
| WHO FluNet, SARS 2003 tables, Ebola sitreps, PAHO Zika | Validation outbreaks | Country-week | Historical | Downloads/PDF | WHO/PAHO | Messy, sparse | Held-out tests | Published first-arrival dates from papers |
| WorldPop / UN WPP | Population | Country (and grids) | Annual | Download | CC BY 4.0 / UN | Estimates | Denominator N | UN WPP |
| Natural Earth admin-0 | Boundaries | 110m/50m | Static | GeoJSON (GitHub) | Public domain | Disputed borders simplified | Map | — |
| OpenFlights | Airports, routes | Airport pair | Stale (≈2014) | Download | ODbL | Outdated, no volume | Topology | OpenSky |
| OpenSky COVID dataset | Flights (ADS-B) | Flight, 2019–2022 | Historical | Zenodo | CC BY 4.0 (verify) | Weak coverage Africa/Asia; flights ≠ people | Volume shock in COVID years | — |
| BTS T-100 International Market | Enplaned passengers | Airport-pair-month since 1990 | Historical, monthly | transtats.bts.gov | US public domain | Only US-touching markets | Observed F, gravity training | — |
| Eurostat avia_par_* | Passengers | Airport-pair-month | Historical | Eurostat API/bulk | Eurostat reuse | Europe only | Observed F, gravity training | — |
| WorldPop air-passenger matrices (Huang 2013, Mao 2015) | Modelled passengers incl. ≤2 transfers | Airport-pair, 2010 | Stale | Download | CC BY (verify) | Modelled, 2010 | Global prior for F | Gravity model |
| OAG / IATA | True O–D bookings | Itinerary | Live | Paid | Commercial | — | Future upgrade | — |

Rule: a passenger number that is not from BTS/Eurostat is labelled `modelled` in the API and UI.

### Gravity model for missing flows

Fit on observed BTS + Eurostat country pairs (aggregate airports to countries, use 2019 to avoid the COVID shock):

`log F_mn = β0 + β1·log Seats_mn + β2·log Pop_m + β3·log Pop_n − β4·log Dist_mn + ε`

where Seats come from route frequency × typical aircraft seats (OpenFlights equipment codes) when schedule data exist; drop the seat term when they don't. Score on held-out BTS routes (random 20%) with MAE on log scale and report it; apply only where no observed F exists; carry a ×/÷ uncertainty factor from the residual spread into the low/high bands.

---

## 5. Modelling approach

Reference implementation: `model_reference.py` (runs its own tests: `python model_reference.py`). It reproduces the briefing note's 14-day chart (3% / 75% / 97%) exactly.

- **Presence** `P_present`: if local cases are reported → `observed`. Otherwise `not_estimable` in the MVP (P2: surveillance-sensitivity model). Flights never feed this.
- **Importation**: `λ_n = Σ_m (I_m/N_m)·F_mn·α_m·(1−σ_mn)`, `P = 1 − exp(−λT)`. `I_m = reported active cases × under-reporting factor u`. Bands: u ∈ {low, central, high}; F ∈ {observed, or modelled × residual factor}.
- **Establishment**: per-introduction `1 − q`, `q = (1 + R(1−q)/k)^(−k)`; over T days `1 − exp(−λT(1−q))` (Poisson thinning). R ≤ 1 ⇒ 0. For vector-borne pathogens the profile sets R from a vector-suitability flag (P2), otherwise "not estimable".
- **Effective distance** (P1): `d(m,n) = 1 − ln(F_mn/F_m)`, shortest path with networkx Dijkstra; used to rank and to explain "via hub" paths.
- **Scenario markers** (P1): upper band (high u, high R, σ = 0, schedules unchanged, prevalence growing at a user-set doubling time); first day cumulative probability ≥ user threshold (default 50%). Shown as "scenario day +N", purple, with the assumptions listed.

Pathogen parameter profiles (documented assumptions, each with a citation field to fill from literature before use; values below are placeholders for the UI defaults, to be checked):

| Profile | α (relative boarding) | R range | k | Source to confirm |
|---|---|---|---|---|
| respiratory_default | 0.5 (0.2–0.8) | 1.2–3.0 | 0.1–0.5 | COVID-19 dispersion literature; briefing note |
| low_mobility_severe (Ebola-like) | 0.05 | 1.2–2.0 | 0.2 | Ebola sitrep literature |
| hospital_amplified (MERS-like) | 0.2 | <1 community | — | WHO MERS assessments |
| vector_borne (Zika-like) | 0.8 | set by vector flag | — | PAHO/Zika literature |

### Calibration & validation (post-finale, P2 — do not claim results earlier)

1. Build the weekly panel: origin × destination × week with prevalence, passengers, OxCGRT σ, label = first case or new lineage within 14 days.
2. Fit the passenger coefficient (and α for COVID) on the first wave (Jan–Mar 2020). Freeze.
3. Test: Delta and Omicron introduction order; H1N1 2009 and SARS 2003 arrival-order rank correlation (Spearman) with effective distance; nothing refit.
4. Negative control: Ebola 2014–16 and MERS — international establishment must stay low.
5. Report per-outbreak metrics with confidence intervals; state that a single pandemic does not establish general accuracy.

---

## 6. Repository layout

```
endemica/
  README.md                 # run commands, env vars, data provenance
  .env.example              # TINYFISH_API_KEY=   (no real values)
  .gitignore                # .env, data/raw, data/cache
  backend/
    app/main.py             # FastAPI app, routers
    app/routers/{outbreaks,risk,routes,admin,hooks}.py
    app/tinyfish/{client.py,goals.py,schemas.py}
    app/ingest/{who_don.py,extract.py,validate.py,grounding.py}
    app/model/{importation.py,establishment.py,effdist.py,gravity.py,markers.py}
    app/data/{loaders.py,iso.py}
    app/db.py               # SQLite via sqlite3/SQLModel
    tests/                  # pytest, fixtures/ with saved API + TinyFish responses
  frontend/
    src/{App.tsx,api.ts,types.ts}
    src/components/{WorldMap.tsx,CountryPanel.tsx,ScenarioControls.tsx,Timeline.tsx,Legend.tsx,SourceBadge.tsx}
  data/
    raw/                    # downloads (gitignored)
    processed/              # countries.parquet, flows.parquet, routes.parquet, population.parquet
    snapshot/               # offline demo: outbreaks.json, risk_cache.json
  scripts/{download_all.sh,build_processed.py,make_snapshot.py}
  docs/{data_dictionary.md,assumptions.md,demo_script.md}
```

---

## 7. API design

| Method & path | Returns |
|---|---|
| `GET /health` | status, data ages per source |
| `GET /outbreaks?pathogen=&country=&since=&status=` | normalized records (see `sample_outbreak_record.json`) |
| `GET /outbreaks/{id}` | one record with provenance and evidence text |
| `GET /routes?origin=ISO3&top=20` | edges `{origin,dest,passengers_per_day,value_type: observed|modelled, via_hub?}` |
| `GET /risk/{dest_iso3}?pathogen=&T=14&u=&alpha=&sigma=&R=&k=&pax_scale=` | `{presence, import:{low,central,high}, establish:{low,central,high}, top_origins[], inputs{…with value_type}, confidence, warnings[]}` |
| `GET /scenario/{dest_iso3}?threshold=0.5&doubling_days=7&…` | `{import_day, establish_day, prevalence_day, assumptions}` (each nullable) |
| `POST /admin/ingest` | triggers WHO poll + TinyFish extraction; returns run summary |
| `POST /admin/policy-flags/{id}/confirm` | confirms a σ flag |
| `POST /hooks/tinyfish` | Monitor webhook receiver (idempotent on content hash) |

Contract rules: every numeric output carries `value_type` ∈ {observed, estimated, modelled, scenario}; when inputs are missing the field is `null` with a `reason`, never 0.

---

## 8. Before the hackathon (16–23 Oct)

Rule check first: ask organizers in the WhatsApp group whether pre-written code is allowed. Until answered, treat **data preparation, design, and throwaway spikes** as allowed and **app code** as "write at the venue". If they allow it, the "spike" items below can become the starting repo.

### Accounts & keys (day 1)
- [ ] Every member signs up on TinyFish via the event link (required by organizers).
- [ ] One team key in a password manager; `.env.example` committed without values.
- [ ] Check wallet balance shows the $8 starter credit; note Agent concurrency (2).

### Downloads (store in `data/raw/`, record URL + date + licence in `docs/data_dictionary.md`)
- [ ] Natural Earth `ne_110m_admin_0_countries.geojson` (and 50m for zoom)
- [ ] OpenFlights `airports.dat`, `routes.dat`, `planes.dat`
- [ ] BTS T-100 International Market, 2019 and 2023 (CSV via TranStats)
- [ ] Eurostat `avia_par_*` country-pair tables, 2019 and 2023
- [ ] WorldPop global flight matrices (Huang 2013 / Mao 2015) if downloadable
- [ ] UN WPP 2024 total population by country
- [ ] OWID `owid-covid-data.csv`; JHU CSSE time series (archive)
- [ ] OxCGRT final release CSV
- [ ] OpenSky COVID flight dataset — one or two months only (it is large)
- [ ] WHO DON full archive via the API → `data/raw/who_don_all.json`

### URLs / schemas to verify (paste results into the doc)
- [ ] WHO DON OData `$orderby`, `$top`, `$filter` on `PublicationDateAndTime`
- [ ] WHO DON item URL pattern from `UrlName`
- [ ] TinyFish Fetch on 3 DON item pages: is `published_date` filled? how clean is the text?
- [ ] TinyFish Agent `output_schema` with our schema: accepted? steps used per page? (budget: aim ≤15 steps/page)
- [ ] TinyFish Monitor API reference: create-page-monitor fields, webhook payload shape
- [ ] One ECDC weekly threat report page and one PAHO alert page through Fetch

### Preprocessing (scripts can be throwaway notebooks)
- [ ] ISO-3 lookup with aliases for every source's country names (largest source of join bugs)
- [ ] Airport → country map; aggregate routes to country pairs
- [ ] Country-pair passenger table: observed (BTS/Eurostat) flagged
- [ ] Gravity model fit + held-out score written down
- [ ] Combined `flows.parquet` (observed + modelled, value_type column)
- [ ] `population.parquet`
- [ ] Small COVID first-wave panel (≈20 countries) to sanity-check the import formula
- [ ] Test fixtures: 5 saved DON JSON items, 3 saved TinyFish Fetch responses, 2 Agent results (one deliberately wrong to test grounding)

### Design & pitch
- [ ] Figma (or slides) of map + panel + sliders + timeline, matching the deck
- [ ] Demo script (section 13) rehearsed on paper
- [ ] Colour tokens: amber = import, coral = outbreak/establish, teal = observed/source, purple = scenario

---

## 9. Team & workstreams (assumes 4; with 3, merge D into A)

| Role | Owns |
|---|---|
| A Data & model | loaders, flows, model, scenario markers, tests for math |
| B Backend & TinyFish | FastAPI, TinyFish client, ingest, validation gate, SQLite |
| C Frontend | map, arcs, panel, sliders, timeline, legend, source badges |
| D Integration & pitch | API contract, fixtures, snapshot, error states, demo, slides, timekeeping |

---

## 10. 24-hour schedule (H0 = start of hacking)

| Block | Goal | Tasks | Deliverable / acceptance | Owner | Claude use | Risk → fallback |
|---|---|---|---|---|---|---|
| H0–1 | Repo + env | scaffold backend/frontend, `.env`, CI-less `make dev`, copy processed data | `make dev` serves `/health` + blank map | D (all) | Generate scaffold from master spec | Tooling issues → pair on one laptop |
| H1–3 | Data & schema | load parquet, ISO table, SQLite schema, outbreak model | `pytest tests/test_loaders.py` green; record schema frozen | A, B | Write loaders + tests from data dictionary | Join failures → restrict to top 60 countries |
| H1–4 | Map shell | MapLibre basemap, country polygons, click-to-select | Click any country → id in state | C | Component from prompt; manual styling | Basemap tiles fail → GeoJSON-only map |
| H2–5 | **M3 TinyFish live** | client (Fetch + Agent async + poll), goals, grounding | One real DON page → validated record in DB | B | Client + retries + tests on fixtures | Agent fails/out of credit → Fetch + regex fallback, record marked `fetch_only` |
| H3–6 | **M5 Model** | importation, establishment, bands | Unit tests: monotonic in F, σ; reproduces 3/75/97% | A | Port `model_reference.py`; ask for property tests | — |
| H5–7 | **M4 Ingest** | WHO DON poll → extract → validate → store, `/outbreaks` | ≥10 real records with provenance | B | Pagination + dedupe | WHO API down → archive snapshot |
| H6–8 | **M6 Risk API** | `/risk`, `/routes`, `value_type` everywhere | curl returns bands for 3 destinations | A, D | Endpoint + response models | Slow → precompute cache |
| H7–10 | **M7 Map data** | outbreak markers, arcs (deck.gl), legend | Real records on map with source links | C | ArcLayer integration | deck.gl issues → MapLibre line layer |
| H10–11 | Sleep/rest rotation | two people rest 90 min each between H10–H16 | — | all | — | — |
| H10–13 | **M8 Panel + sliders** | country panel, three metrics, sliders call `/risk` | Moving σ lowers import, never changes presence | C, A | Panel component; debounce | — |
| H12–14 | P1: effective distance + via-hub | networkx paths, "via DXB" labels | Top origins list shows hub paths | A | Dijkstra + tests | Skip if behind |
| H13–15 | P1: Monitor webhook + σ flags | `/hooks/tinyfish`, policy flag admin | Monitor run creates/updates record | B | Webhook handler | Skip; show manual "Run ingest" button |
| H15–17 | **M9 End-to-end** | snapshot script, offline mode, scenario timeline | Demo runs with Wi-Fi off | D, C | Snapshot script | — |
| H17–19 | **M10 Hardening** | error states, "not estimable", data-age badges, tests | Kill TinyFish key → UI still works, shows warning | all | Ask Claude to list failure modes, then test by hand | — |
| H19–21 | Polish | copy, colours, legend text, loading states | Two outsiders understand the panel in 30 s | C, D | Microcopy suggestions | — |
| H21–23 | **M11 Pitch** | update deck with real screenshots, rehearse 3× | ≤ allotted time, demo + backup video | D (all) | Tighten script | Live demo fails → recorded video |
| H23–24 | Buffer | bug fixes only, freeze code at H23:30 | — | all | — | — |

Milestones M1–M11 map to the user-requested list: M1 repo/env (H1), M2 schema/data (H3), M3 TinyFish on a real source (H5), M4 ingest (H7), M5 model (H6), M6 country API (H8), M7 map (H10), M8 selection + scenarios (H13), M9 end-to-end (H17), M10 errors/tests (H19), M11 rehearsal (H23).

### Scope

| P0 (must) | P1 (if core works) | P2 (later) |
|---|---|---|
| Map + real WHO records + source links | Hub arcs + effective distance | Full COVID calibration, held-out tests |
| TinyFish Fetch → Agent → grounding gate on a real page | Gravity proxy across all pairs | Live seats × load factor |
| Import model with bands, establishment as separate metric | Monitor webhook ingest | Admin-1 resolution |
| Country panel with three separated quantities | σ policy flags with confirm | Surveillance-sensitivity P(present) |
| Sliders: T, σ, u, passenger scale, R, k | Scenario markers timeline | Alerts/subscriptions |
| Offline snapshot | | Licensed O–D data |

No fake trained model at any point. If calibration is not done, the UI says "parameters from literature/assumption".

---

## 11. Claude Pro workflow

Usage caps vary by plan and load; we have not verified exact quotas, so plan as if each person gets a limited number of long messages per few hours. Spread work across members' accounts and keep prompts small.

**Shared source of truth:** `docs/SPEC.md` (≤ 2 pages: goals, API contract, schemas, colour/value-type rules). Every prompt starts by pasting SPEC.md's relevant section, not the whole repo.

**Master spec prompt (start of event):**
> You are helping a 4-person team build Endemica in 24 hours. Read this SPEC. Rules: Python 3.11 FastAPI backend, React+TS+Vite frontend, MapLibre + deck.gl. Every numeric output has value_type ∈ {observed, estimated, modelled, scenario}; missing inputs return null with a reason, never 0. TinyFish calls are server-side only, key from env. Reply with code for ONE file at a time plus its tests. Ask before inventing an API field. SPEC: …

**Repo inspection prompt:**
> Here is `tree -L 3` and the contents of app/main.py and app/routers/risk.py. List mismatches with the SPEC contract and the smallest change to fix each. Do not rewrite files.

**Task prompts:**
- Ingestion: "Write `ingest/who_don.py`: fetch the WHO DON OData endpoint, paginate, map fields to `OutbreakSource` (schema below), dedupe by DonId/UrlName. Include pytest tests using `tests/fixtures/don_sample.json`."
- TinyFish client: "Write `tinyfish/client.py` with `fetch(urls)`, `agent_run_async(url, goal, schema)`, `poll(run_id, timeout)`, using httpx, the endpoints and fields below (pasted from docs). Handle 401, 402, 429 with `retry_after`, and run statuses FAILED/CANCELLED. Tests with respx mocks."
- Grounding: "Write `grounding.py`: given fetch text and an extraction dict, verify every integer appears (accept '1,234', '1 234', '1234') and every evidence string is a substring after whitespace normalisation. Return per-field verdicts. Include adversarial tests."
- Model: "Port `model_reference.py` into `model/importation.py` and `model/establishment.py` with NumPy vectorisation over origins. Keep the reference self-tests as pytest tests and add property tests: monotonic in passengers, decreasing in σ, establishment 0 when R ≤ 1."
- API: "Write `routers/risk.py` implementing GET /risk/{iso3} per contract; inputs validated with pydantic; return low/central/high."
- Frontend map: "Write `WorldMap.tsx`: MapLibre with a GeoJSON country layer, deck.gl ArcLayer for routes (props: routes[]), ScatterplotLayer for outbreaks; colour tokens below; onCountryClick(iso3)."
- Tests: "Given this function and its docstring, write tests that would fail if the formula were wrong. Do not change the function."

**Habits:**
- One file per request; run the tests before accepting; paste the failing output back, not the whole file.
- If two attempts fail, debug by hand (print the inputs) instead of asking for a rewrite.
- Keep a `docs/DECISIONS.md` log so new chats don't relitigate choices.
- When limits hit: switch member/account, fall back to docs + the reference implementation, or use another assistant for boilerplate only; never block on the AI for model logic — it is already written in `model_reference.py`.

---

## 12. Tests & definition of done

- [ ] `make dev` (documented in README) starts backend and frontend from a clean clone.
- [ ] Map renders country boundaries and ≥10 real WHO outbreak records with working source links.
- [ ] At least one record created end-to-end through TinyFish Fetch + Agent on a real official page, passing the grounding check; or the documented `fetch_only` fallback is visible if Agent fails.
- [ ] Every record shows source URL, published and retrieved times, extraction status.
- [ ] Selecting a destination with inputs returns import and establishment bands; without inputs shows "not estimable".
- [ ] Raising passengers raises P(import); raising σ lowers it; neither changes P(present). (automated test)
- [ ] Establishment is displayed separately and equals 0 when R ≤ 1. (automated test)
- [ ] Model reproduces 3% / 75% / 97% reference values. (automated test)
- [ ] Grounding test rejects a fabricated number. (automated test)
- [ ] With the network disabled, the app loads the snapshot and labels data age.
- [ ] No API key in the frontend bundle, repo, logs or slides (`git grep -i tinyfish_api_key` shows only env usage).
- [ ] Scenario markers are labelled "scenario" and list their assumptions.

---

## 13. Demo script (3 minutes)

1. (20 s) Problem: reports are prose, risk is opaque.
2. (40 s) Click "Run ingest": a WHO report goes through TinyFish → validation → appears on the map with a source badge; open the evidence sentence.
3. (60 s) Select a destination: three separate numbers with ranges; show top origins via hubs.
4. (40 s) Drag σ and passenger volume; ranges move in the expected direction; presence does not.
5. (20 s) Scenario timeline with its assumptions; state it is not a safety date.

Backup: screen recording of the same flow on the offline snapshot.

---

## 14. Risks & fallbacks

| Risk | Likelihood | Fallback |
|---|---|---|
| TinyFish Agent slow or out of credit | Medium | Fetch (free) + regex extraction, records marked `fetch_only`; cache all runs |
| Agent output_schema rejected | Medium | Simplify schema (no unions); validate on our side |
| WHO API changes/down | Low | Pre-downloaded archive snapshot |
| Venue Wi-Fi poor | Medium | Offline snapshot; map tiles replaced by GeoJSON layer |
| Country-name joins fail | High | ISO alias table prepared beforehand |
| Passenger data gaps | High | Gravity proxy labelled `modelled`; "not estimable" when even that is missing |
| Over-scope | High | P0 freeze at H8; P1 only after M8 |
| Misreading outputs as advice | Medium | Copy and colours separate value types; disclaimer; links to WHO guidance |

---

## 15. After the hackathon

1. Run the calibration/validation plan and publish results (including failures).
2. Replace 2010 flow priors with current schedules × seats × load factor; license O–D data if possible.
3. Add ECDC, PAHO, Africa CDC and national sources as new TinyFish goals with source-specific tests.
4. Sub-national resolution where reports allow.
5. Subscriptions/alerts for destinations; public changelog of model versions.
6. External review by an epidemiologist before any public launch.

---

## References

- Briefing note: "How disease-spread probabilities get their data", 14 Oct 2026 (team document).
- Brockmann D, Helbing D. The hidden geometry of complex, network-driven contagion phenomena. Science 2013;342:1337–1342.
- Lloyd-Smith JO et al. Superspreading and the effect of individual variation on disease emergence. Nature 2005;438:355–359.
- Huang Z et al. PLOS ONE 2013;8:e64317 · Mao L et al. J Transport Geography 2015;48:52–60.
- WHO DON API; OWID covid-19-data; JHU CSSE COVID-19; OxCGRT covid-policy-dataset; BTS T-100; Eurostat avia; OpenFlights; OpenSky COVID dataset (Zenodo); Nextstrain; GLEAM (gleamviz.org).
- TinyFish docs: docs.tinyfish.ai (Agent API reference, Fetch API reference, Search API reference, Monitor), tinyfish.ai/pricing — accessed 15 Oct 2026.
- HackIIITD 2026 Unstop listing — accessed 15 Oct 2026.
