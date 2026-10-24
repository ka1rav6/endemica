# AGENTS.md — EpiRoute

> **Project:** EpiRoute — Outbreak Intelligence and Air-Travel Risk Mapping  
> **Event:** HackIIITD 2026  
> **Purpose:** Provide transparent, source-backed outbreak intelligence by combining public-health reports, air-travel networks, and epidemiological models.  
> **Primary objective:** Build a reliable, demonstrable, well-documented MVP first, then expand it incrementally without compromising correctness.

This file defines the engineering standards, development workflow, architecture, documentation requirements, testing strategy, and Git conventions that all AI coding agents and human contributors must follow.

**Read this file before making any changes to the repository.**

If the repository contains additional `AGENTS.md` files in subdirectories, follow those instructions alongside this file. More-specific instructions may refine these rules but must not weaken the project's security, correctness, testing, or documentation requirements.

---

# 1. Core Engineering Principles

Every implementation decision must follow these principles, in order of importance.

1. **Correctness over feature count.** A smaller working application is preferable to a large application full of broken features.
2. **Incremental development.** Implement one small, verifiable change at a time.
3. **Frequent, meaningful Git commits.** Every completed logical unit of work should be committed separately.
4. **Documentation is part of implementation.** A feature is incomplete if its documentation is missing or outdated.
5. **Reproducibility.** Another developer must be able to set up, run, test, and build the project using documented commands.
6. **Transparency.** Every displayed epidemiological value must be traceable to its inputs, assumptions, sources, and calculation method.
7. **Graceful degradation.** External API failures must not prevent the application from starting or invalidate previously cached data.
8. **Security by default.** API credentials must remain server-side, dependencies must be controlled, and external data must be treated as untrusted.
9. **Simple architecture.** Prefer a modular monolith over unnecessary microservices.
10. **No fabricated functionality.** Never claim that an integration, test, dataset, or model works unless it has actually been implemented and verified.

When time is limited, reduce the scope of the implementation rather than lowering these standards.

---

# 2. Project Overview

## 2.1 What We Are Building

EpiRoute is an outbreak-intelligence application that connects public-health reports to the global air-travel network.

Users should be able to:

- Explore reported disease outbreaks on an interactive map.
- Inspect outbreak reports and their original sources.
- Select a destination and inspect relevant origin countries and travel routes.
- Understand the probability of an infected traveller arriving within a specified time horizon.
- Inspect local outbreak presence separately from importation risk.
- Understand the probability of an imported infection establishing sustained local transmission.
- Change model assumptions and explore different scenarios.
- Inspect uncertainty ranges and data-quality limitations.
- View the assumptions and provenance behind displayed values.
- Continue exploring a cached dataset when live services are unavailable.

The application is intended for **situational awareness and educational analysis**. It is not a diagnostic tool, an official public-health forecast, or a substitute for official travel guidance.

## 2.2 Three Distinct Risk Concepts

These concepts must remain separate throughout the application, its API, and its documentation.

### A. Local presence

Question: Is there evidence that the pathogen is already present in the selected destination?

Inputs may include:

- Reported local cases.
- Reporting dates.
- Population estimates.
- Assumptions about under-reporting.
- Source quality and reporting delays.

Flight connectivity alone must never be interpreted as evidence that a disease is present in a country.

If the available evidence is insufficient, report the value as unknown or not estimable rather than inventing a probability.

### B. Importation risk

Question: What is the probability that at least one infected traveller arrives within the selected time horizon?

A simplified model may use:

\[
\lambda_n =
\sum_m
\frac{I_m}{N_m}
F_{mn}
\alpha
(1-\sigma_{mn})
\]

where:

- \(I_m/N_m\) represents estimated pathogen prevalence at origin \(m\).
- \(F_{mn}\) represents passenger flow from origin \(m\) to destination \(n\).
- \(\alpha\) represents the relative probability that an infected person boards a flight.
- \(\sigma_{mn}\) represents screening effectiveness.

Under a constant-rate Poisson assumption:

\[
P(\text{at least one arrival within }T)
=
1-e^{-\lambda_n T}
\]

This simplified formula is valid only when its assumptions are appropriate.

The implementation must document the units, time horizon, input definitions, and assumptions used by each calculation.

Do not silently substitute flight counts for passenger counts. If passenger flows are estimated from flight schedules, label them as estimates.

### C. Local establishment risk

Question: Given an introduction, what is the probability that sustained local transmission develops?

Potential inputs include:

- The pathogen's reproduction number \(R\).
- Transmission-cluster dispersion \(k\).
- Pathogen-specific infectiousness and transmission characteristics.
- Local environmental conditions when epidemiologically relevant.

For the branching-process model, document the exact probability equation, the numerical solution method, the meaning of its parameters, and its limitations.

Do not assume that a high importation probability implies a high establishment probability.

**Important:** The equations above are model specifications, not proof that a particular probability is accurate. Every model output must be identified as estimated, modelled, or scenario-based as appropriate.

---

# 3. Technology Stack and Architecture

## 3.1 Preferred Stack

Use the following stack unless the repository already contains a working implementation that provides a compelling reason to retain a different choice.

### Backend

- Python.
- FastAPI.
- Pydantic for request validation and typed data models.
- SQLite for lightweight persistent storage.
- Parquet for suitable cached tabular datasets.
- NetworkX for graph-based analysis where appropriate.
- Pytest for testing.
- Ruff for Python linting and formatting.

### Frontend

- React.
- TypeScript with strict type checking.
- Vite.
- MapLibre GL for interactive mapping.
- deck.gl for appropriate network visualizations.
- A consistent, accessible component and styling system.

### Development and tooling

- Git.
- A root-level `justfile`.
- Python virtual environments and a reproducible dependency specification.
- A Node.js package manager with a committed lockfile.
- Automated tests and static checks.
- Environment variables for configuration and credentials.

Before adding a dependency, check whether the required functionality can be implemented using the existing stack.

Do not add dependencies simply because they are popular.

## 3.2 Architectural Boundaries

Organize the application into logical modules.

The following is the target structure, not a requirement to create every directory immediately:

```text
epiroute/
├── AGENTS.md
├── README.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── LICENSE
├── .gitignore
├── .env.example
├── justfile
│
├── docs/
│   ├── architecture.md
│   ├── development.md
│   ├── api.md
│   ├── data-sources.md
│   ├── data-model.md
│   ├── epidemiological-models.md
│   ├── testing.md
│   ├── security.md
│   ├── decisions/
│   └── runbooks/
│
├── backend/
│   ├── pyproject.toml
│   ├── src/
│   │   └── epiroute/
│   │       ├── main.py
│   │       ├── api/
│   │       ├── core/
│   │       ├── schemas/
│   │       ├── models/
│   │       ├── services/
│   │       ├── ingestion/
│   │       ├── epidemiology/
│   │       ├── graph/
│   │       ├── repositories/
│   │       └── storage/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── fixtures/
│
├── frontend/
│   ├── package.json
│   ├── package-lock.json
│   ├── index.html
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   ├── hooks/
│   │   ├── lib/
│   │   ├── services/
│   │   ├── types/
│   │   └── styles/
│   └── tests/
│
├── data/
│   ├── README.md
│   ├── raw/
│   ├── processed/
│   └── cache/
│
├── scripts/
│   └── README.md
│
└── .github/
    └── workflows/
```

Adapt this structure to the actual repository. Do not reorganize working code merely to match the example.

Generated files, downloaded datasets, secrets, build artifacts, and runtime databases should not be committed unless there is a deliberate, documented reason to include them.

## 3.3 Dependency Direction

Maintain clear boundaries:

- API routes call application services.
- Application services coordinate business logic.
- Epidemiological models contain mathematical logic rather than HTTP or database logic.
- Ingestion modules acquire and normalize external data.
- Repositories manage persistence.
- Frontend services communicate with the backend API.
- UI components display data and collect user input.
- Configuration is centralized rather than duplicated across modules.

Avoid circular imports, duplicated business logic, and large files that combine unrelated responsibilities.

Do not put epidemiological calculations directly inside React components or API route handlers.

---

# 4. Mandatory Incremental Git Workflow

**This is one of the highest-priority requirements in this document.**

The project must be developed through many small, meaningful commits rather than a few enormous commits.

The goal is a reviewable development history that demonstrates how the application was built.

## 4.1 Commit Frequency

Aim for:

- One commit per small, logically complete implementation step.
- Several commits during a substantial feature.
- Separate commits for independent fixes, tests, documentation, and refactoring when practical.
- A commit after completing each independently verifiable unit of work.

A typical commit should modify one cohesive concern.

Prefer multiple small commits over one large commit that introduces an entire subsystem.

Do not impose an arbitrary minimum number of commits or split a trivial change into meaningless commits just to inflate the count.

**Every commit must represent real progress.**

## 4.2 Required Development Loop

Follow this loop continuously:

1. Inspect the repository and current Git status.
2. Read the applicable `AGENTS.md` instructions.
3. Identify the next smallest useful task.
4. Review the relevant existing code and documentation.
5. State the intended change and its acceptance criteria.
6. Implement only that change.
7. Add or update relevant tests.
8. Update affected documentation and comments.
9. Run the relevant checks using the root `justfile`.
10. Review the diff for correctness, unrelated modifications, and accidental secrets.
11. Commit the completed change.
12. Verify that the commit exists and the working tree is in the expected state.
13. Select the next task and repeat.

Do not implement several unrelated features before running tests or committing.

If a task reveals a separate problem, finish the current logical unit when safe, then address the additional problem in its own change.

## 4.3 Commit Size

As a guideline, aim for commits that are small enough to review in a few minutes.

Prefer changes such as:

```text
chore: initialize Python project
chore: add backend dependency configuration
feat: add health endpoint
test: cover health endpoint
docs: document local backend setup
feat: define outbreak report schema
test: validate outbreak report fields
feat: add outbreak repository interface
test: cover outbreak repository
feat: add local presence model
test: cover local presence calculations
docs: explain local presence assumptions
```

These are examples of possible commit messages, not a requirement to implement these exact changes in this order.

Avoid commits such as:

```text
initial commit
implement everything
finish backend and frontend
final fixes
miscellaneous changes
```

## 4.4 Commit Message Convention

Use Conventional Commits.

Supported prefixes include:

- `feat:` — New functionality.
- `fix:` — Bug fixes.
- `test:` — Test-only changes.
- `docs:` — Documentation.
- `refactor:` — Behavior-preserving code improvements.
- `perf:` — Performance improvements.
- `build:` — Build system or dependency changes.
- `ci:` — Continuous integration.
- `chore:` — Maintenance.
- `style:` — Formatting-only changes that do not affect behavior.

Examples:

```text
feat(ingestion): add WHO report response parser
test(ingestion): cover missing epidemiology fields
fix(ingestion): reject negative case counts
docs(ingestion): document report validation
feat(api): expose outbreak report provenance
test(api): cover outbreak provenance response
```

Use the scope when it improves clarity.

Commit messages must describe the actual change, not merely the file names.

## 4.5 Testing Before Committing

Every commit must be in a coherent state.

Before committing:

- Run the relevant unit tests.
- Run the relevant formatting and lint checks.
- Run type checks where applicable.
- Verify affected functionality.
- Review the staged diff.

For documentation-only commits, run checks relevant to the changed documentation when available. Do not unnecessarily run expensive integration suites for a spelling correction.

If a check cannot be run because of an unavailable external service or environment dependency, state that limitation explicitly.

Never claim that tests passed when they were not executed.

Do not knowingly commit broken code and plan to repair it in a later commit.

## 4.6 Git Safety

- Never rewrite published history unless explicitly instructed.
- Never force-push without explicit authorization.
- Never discard unrelated user changes.
- Never run destructive Git commands against uncommitted user work.
- Do not automatically amend previous commits to conceal intermediate work.
- Do not commit API keys, credentials, personal information, or unapproved datasets.
- Do not change Git identity configuration without authorization.
- Do not bypass hooks or required checks to make a commit succeed.

Before the first commit, inspect `git status` and the existing history.

If Git commits cannot be created because the environment lacks permission or configuration, explain the specific blocker. Continue with incremental implementation without pretending that commits were created.

## 4.7 Task Completion Reports

At the end of each meaningful work session, report:

- What was implemented.
- Which tests and checks were executed.
- Which commits were created.
- What remains incomplete.
- Any known limitations or blockers.
- The recommended next task.

Do not report an entire feature as complete merely because its interface exists.

---

# 5. Documentation Requirements

Documentation is mandatory for all meaningful functionality.

**Code, tests, and documentation should evolve together.**

## 5.1 Required Root Documentation

### `README.md`

The README must explain:

- What EpiRoute does.
- The problem it addresses.
- Its primary features.
- The high-level architecture.
- Prerequisites.
- Initial setup.
- Environment configuration.
- How to start the application.
- How to run tests.
- How to run linting and formatting.
- How to build the frontend.
- How to initialize and populate the database.
- How to use cached data.
- How to troubleshoot common problems.
- The limitations of the current implementation.
- Where to find detailed documentation.

Use the root `justfile` as the primary reference for executable development commands.

Do not duplicate lengthy setup instructions in multiple files. Link to the relevant detailed documentation instead.

### `CONTRIBUTING.md`

Document:

- Repository conventions.
- Branching expectations.
- Commit message conventions.
- The incremental development workflow.
- Coding standards.
- Testing expectations.
- Documentation requirements.
- Pull request or review expectations, if applicable.

### `CHANGELOG.md`

Maintain a chronological record of significant changes.

Group changes under meaningful categories such as:

- Added.
- Changed.
- Fixed.
- Removed.
- Known limitations.

Update the changelog when a change materially affects user-facing functionality, architecture, configuration, or developer workflows.

Do not add a changelog entry for every trivial formatting-only commit.

### `docs/architecture.md`

Describe:

- Major application components.
- Responsibilities of each module.
- Data flow from source acquisition to UI rendering.
- Dependency boundaries.
- Storage choices.
- External service integrations.
- Error-handling strategy.
- Offline operation.
- Important architectural decisions.

Update this file when the architecture materially changes.

### `docs/data-sources.md`

For every integrated source, document:

- Name and official source URL.
- Purpose.
- Data fields consumed.
- Geographic coverage.
- Temporal coverage, where known.
- Acquisition method.
- Authentication requirements.
- Update frequency.
- Data licensing or usage restrictions, where known.
- Known limitations.
- Validation performed.
- Fallback behavior.

Clearly distinguish official observations from estimates and model-generated values.

### `docs/epidemiological-models.md`

Document every implemented epidemiological model.

For each model, explain:

1. The question it answers.
2. The mathematical definition.
3. Every variable and its units.
4. The source of each input.
5. The assumptions.
6. Missing-data behavior.
7. Numerical methods.
8. Uncertainty handling.
9. Validation performed.
10. Known limitations.
11. A worked example.

The worked example must use clearly labelled illustrative data unless it is explicitly based on a cited real observation.

### Other documentation

Create or update additional documentation as appropriate:

- `docs/api.md`
- `docs/data-model.md`
- `docs/testing.md`
- `docs/security.md`
- `docs/development.md`
- `docs/decisions/`
- `docs/runbooks/`

Do not create empty documentation files just to satisfy the directory structure.

Each document should provide useful information.

## 5.2 Documentation for Code

Public modules, classes, functions, API endpoints, and non-trivial internal abstractions should have documentation explaining their purpose and usage.

For Python, use clear docstrings.

Example:

```python
def calculate_importation_probability(
    daily_arrival_rate: float,
    horizon_days: float,
) -> float:
    """Calculate the probability of at least one infected arrival.

    Assumes a constant, non-negative arrival rate and a Poisson
    process over the requested time horizon.

    Args:
        daily_arrival_rate: Expected infected arrivals per day.
        horizon_days: Prediction horizon in days.

    Returns:
        Probability of at least one infected arrival, between 0 and 1.

    Raises:
        ValueError: If the rate or horizon is negative or non-finite.
    """
```

This example establishes a documentation style; it is not a complete implementation.

For TypeScript, document exported interfaces, complex hooks, public utilities, and non-obvious behavior.

For API endpoints, document request fields, response fields, error responses, and relevant assumptions.

For data schemas, document fields whose meaning or interpretation is not obvious from their names and types.

## 5.3 Comments

Comments should explain intent, reasoning, assumptions, and non-obvious behavior.

Good comments answer questions such as:

- Why is this validation necessary?
- Why does this algorithm use this approximation?
- Why is this fallback preferable to another?
- What external contract does this code depend on?
- Why is a numerical edge case handled specially?
- What would go wrong if this code were simplified?

Avoid comments that merely translate code into English.

Bad:

```python
# Increment i by one.
i += 1
```

Better:

```python
# Keep the original report timestamp for provenance; normalize a
# separate value for chronological comparisons.
```

Use comments to preserve important reasoning that would otherwise be lost during refactoring.

Do not leave outdated comments after changing the implementation.

## 5.4 Mathematical Code

Epidemiological and graph algorithms require especially careful documentation.

Every non-trivial formula must have:

- A documented mathematical definition.
- Explicit variable names.
- Explicit units.
- Input validation.
- Defined behavior for boundary conditions.
- Tests against known or analytically verifiable examples.
- A reference to the relevant documentation or literature where appropriate.

Avoid unexplained magic numbers.

If a numerical constant represents an assumption, expose it through a clearly named configuration value or model parameter when appropriate.

Do not imply scientific validation merely because a formula has been implemented correctly.

---

# 6. The Root `justfile` Is the Primary Command Interface

**Every routine development operation must be accessible through the root `justfile` wherever practical.**

Contributors and AI agents should not need to remember long sequences of commands or search through source files to discover how to operate the project.

Use the official `just` command runner.

Reference: https://just.systems/

## 6.1 Required Recipes

As the corresponding functionality is implemented, provide recipes for:

| Category | Expected recipes |
|---|---|
| Discovery | `just`, `just --list` |
| Setup | `just setup`, `just setup-backend`, `just setup-frontend` |
| Configuration | `just config-check` |
| Development | `just dev`, `just dev-backend`, `just dev-frontend` |
| Lifecycle | `just start`, `just stop`, `just status` |
| Testing | `just test`, `just test-backend`, `just test-frontend` |
| Quality | `just lint`, `just format`, `just format-check`, `just typecheck` |
| Build | `just build`, `just build-backend`, `just build-frontend` |
| Data | `just data-check`, `just data-ingest`, `just data-validate` |
| Storage | `just db-init`, `just db-reset`, `just db-status` |
| API | `just api-docs`, `just api-check` |
| Dependencies | `just deps`, `just deps-check` |
| Diagnostics | `just doctor`, `just logs` |
| Cleanup | `just clean` |
| Git workflow | `just git-status`, `just git-log` |

These recipes define the intended interface. Implement them as their underlying operations become available.

Do not leave recipes that silently do nothing or claim to perform operations that are not implemented.

If an operation is unavailable, either omit it until it can be implemented or make the recipe report a clear, actionable error.

## 6.2 Command Interface Rules

1. Keep the `justfile` at the repository root.
2. Add new routine commands to it when introducing new functionality.
3. Keep recipes readable and narrowly scoped.
4. Use shared variables and helper recipes to avoid unnecessary duplication.
5. Quote paths and arguments appropriately.
6. Propagate command failures rather than hiding them.
7. Avoid destructive defaults.
8. Document environment variables and prerequisites.
9. Prefer portable commands when practical.
10. Do not hardcode developer-specific absolute paths.
11. Do not require globally installed Python or Node packages when project-local alternatives are practical.
12. Keep the recipes consistent with the actual dependency and directory structure.
13. Ensure that `just --list` provides a useful overview.
14. Update the README whenever the command interface changes materially.

## 6.3 Command Discoverability

A new contributor should be able to start with:

```bash
just
just doctor
just setup
just dev
```

The exact sequence may evolve, but the intended workflow should remain simple and documented.

`just doctor` should check relevant prerequisites and configuration, such as:

- Python availability and version.
- Node.js and package-manager availability.
- Required project dependencies.
- Required environment variables.
- Writable runtime directories.
- Database availability or initialization state.
- Optional integration credentials.

A missing optional credential should not prevent unrelated parts of the application from running.

## 6.4 Setup Must Be Safe to Repeat

Where practical, setup and initialization commands should be idempotent.

Running setup twice should not corrupt the environment or unnecessarily destroy existing data.

Database-reset and cleanup commands must be explicitly destructive only when their names and documentation make that behavior clear.

Do not make `just setup` delete existing databases, cached datasets, or user configuration.

## 6.5 No Hidden Commands

If a script is added for development, ingestion, data preparation, testing, or maintenance, provide a corresponding `just` recipe when it is a routine operation.

Avoid undocumented operational scripts that developers must discover manually.

Low-level implementation details can remain inside scripts, but their supported invocation should be documented.

## 6.6 Justfile Verification

After adding or changing a recipe:

1. Check that `just` can parse the file.
2. Verify that the recipe appears in `just --list`.
3. Run the recipe when its prerequisites are available.
4. Verify that failures propagate correctly.
5. Update documentation if behavior changed.

---

# 7. Coding Standards

## 7.1 General

- Write code that is readable before attempting clever optimizations.
- Prefer explicit behavior over implicit conventions.
- Use descriptive names.
- Keep functions focused on one responsibility.
- Avoid duplicated business logic.
- Avoid premature abstraction.
- Avoid unnecessary global mutable state.
- Validate inputs at system boundaries.
- Handle errors explicitly.
- Use structured logging rather than scattered debug prints.
- Never silently swallow exceptions.
- Remove dead code and unused imports.
- Avoid adding speculative features unrelated to the current task.

Do not refactor unrelated files merely because they could be improved.

## 7.2 Python

- Use type annotations for public functions and important internal interfaces.
- Use Pydantic for external data validation where appropriate.
- Use Ruff for formatting and linting.
- Follow the project's configured Python version.
- Use meaningful exception types.
- Keep I/O separate from pure computational functions where practical.
- Avoid synchronous blocking operations inside asynchronous request handlers.
- Use explicit timeouts for external requests.
- Avoid broad `except Exception` handlers unless they are at a deliberate error boundary and preserve useful diagnostic information.
- Do not use mutable default arguments.
- Avoid unnecessary class hierarchies.

Keep mathematical functions easy to test independently of databases, network calls, and web frameworks.

## 7.3 TypeScript and React

- Enable and maintain strict TypeScript checking.
- Avoid `any` unless there is a documented, justified reason.
- Define explicit types for API responses.
- Validate external data at suitable runtime boundaries.
- Avoid placing complex application logic inside large components.
- Use reusable components when they represent genuine shared behavior.
- Keep state ownership clear.
- Handle loading, empty, error, stale-data, and unavailable-data states.
- Avoid unnecessary effects and duplicated state.
- Keep accessibility in mind.
- Avoid disabling lint rules without a specific justification.

A TypeScript interface alone does not validate data received over the network.

## 7.4 Naming and Formatting

Follow the conventions of the language and the existing repository.

- Python functions and variables: `snake_case`.
- Python classes: `PascalCase`.
- TypeScript variables and functions: `camelCase`.
- React components and TypeScript types: `PascalCase`.
- Constants: descriptive names following the conventions of their module.
- Tests: names that explain the behavior being verified.

Use the configured formatter rather than repeatedly making manual formatting changes.

---

# 8. Testing Strategy

Testing must evolve alongside the implementation.

Do not postpone all testing until the application appears complete.

## 8.1 Unit Tests

Test individual components in isolation.

Examples include:

- Parsing outbreak reports.
- Validating report schemas.
- Normalizing country codes.
- Handling missing values.
- Calculating local presence estimates.
- Calculating importation probabilities.
- Solving branching-process equations.
- Constructing graph edges.
- Calculating effective distances.
- Serializing API responses.

Use deterministic inputs wherever possible.

## 8.2 Integration Tests

Test interactions between modules.

Examples include:

- API routes with the application services.
- Services with repositories.
- Database initialization and persistence.
- Ingestion and schema validation.
- Cache reads and writes.
- API responses consumed by frontend services.

Use temporary databases and controlled fixtures when possible.

Tests must not require paid services or live credentials unless they are explicitly classified as optional integration tests.

## 8.3 Frontend Tests

Test important user-visible behavior, including:

- Loading outbreak reports.
- Rendering empty and error states.
- Selecting a destination.
- Changing model assumptions.
- Displaying data provenance.
- Distinguishing observed, estimated, modelled, and scenario values.
- Showing uncertainty ranges.
- Handling unavailable API responses.

Avoid brittle tests that depend unnecessarily on implementation details.

## 8.4 Model Tests

Epidemiological models require mathematical tests, not just ordinary application tests.

For the Poisson importation model, test that:

- A zero arrival rate produces zero probability.
- A zero time horizon produces zero probability.
- Increasing the arrival rate cannot decrease the probability.
- Increasing the time horizon cannot decrease the probability.
- The output remains within the valid probability range.
- Known numerical examples produce the expected result within a stated tolerance.
- Invalid or non-finite inputs are handled explicitly.

For establishment models, test:

- Relevant boundary conditions.
- Numerical convergence.
- Parameter validation.
- Expected qualitative behavior.
- Known examples from the documented model.
- Failure behavior when a numerical solution cannot be obtained.

Do not write tests that merely repeat the implementation's formula without independently checking the expected result.

## 8.5 Ingestion Tests

External reports may be incomplete, malformed, duplicated, or inconsistent.

Test:

- Missing optional fields.
- Unexpected field types.
- Invalid country codes.
- Negative counts.
- Invalid dates.
- Duplicate source records.
- HTML extraction failures.
- Missing case counts.
- Empty responses.
- Timeouts and HTTP errors.
- Partial ingestion.
- Unverified extracted values.

Use saved fixtures for deterministic tests.

Do not make the normal test suite depend on the continued availability of an external website.

## 8.6 Quality Gates

Before a feature is considered complete, run the relevant checks through the root `justfile`.

The project should progressively support:

```bash
just test
just lint
just format-check
just typecheck
just build
```

Do not claim that all checks are available until the corresponding recipes have been implemented.

Do not weaken tests, remove assertions, or disable linting solely to make a failing implementation pass.

When a test reveals a real bug, fix the underlying issue rather than hiding the failure.

---

# 9. Data Ingestion and Provenance

## 9.1 Data Sources

Prefer official, documented sources where available.

Potential sources include:

- WHO Disease Outbreak News.
- ECDC and other national or regional public-health authorities.
- OpenFlights for airport and route topology.
- US BTS and Eurostat for passenger data in their respective coverage areas.
- OpenSky for historical flight observations where suitable.
- Our World in Data and the Johns Hopkins CSSE archive for historical COVID-19 data.
- WorldPop or UN population datasets.
- Other documented sources justified by the use case.

The actual availability, licensing, freshness, and completeness of every dataset must be verified before integration.

Do not claim that a source provides data it does not actually expose.

In particular:

- Flight counts are not passenger counts.
- Scheduled routes are not proof of current passenger movement.
- Reported case counts are not necessarily true infection counts.
- First confirmed cases are not necessarily the dates of initial introduction.
- Historical policy datasets do not automatically describe current border policy.

## 9.2 TinyFish Integration

TinyFish should be integrated through the backend, never directly from the browser.

Its purpose is to extract and normalize information from public-health reports or relevant official policy pages.

Treat extracted content as untrusted input.

For each extraction:

1. Retrieve the source content.
2. Extract the required fields.
3. Validate the output schema.
4. Validate numeric values and dates.
5. Normalize geographic identifiers.
6. Check extracted values against the available source text.
7. Record provenance.
8. Flag uncertain or unverifiable fields.
9. Persist valid records and relevant validation status.
10. Log failures without exposing secrets.

Do not assume that structured extraction guarantees scientific correctness.

A value that cannot be verified must not silently enter the model as a trusted observation.

## 9.3 Provenance Fields

Where applicable, source-derived records should retain fields such as:

```text
source_url
source_name
published_at
retrieved_at
source_identifier
extraction_status
validation_status
extraction_run_id
```

Model outputs should retain enough information to identify their input records, model version, calculation time, and relevant assumptions.

Choose the final schema based on actual source capabilities. Do not fabricate unavailable publication dates or extraction identifiers.

## 9.4 Data Classification

Distinguish the following categories throughout the application:

- **Observed:** Directly reported or measured by an identified source.
- **Estimated:** Inferred from data using a documented estimation procedure.
- **Modelled:** Produced by an explicit mathematical model.
- **Scenario:** Produced under user-selected or illustrative assumptions.
- **Unknown / not estimable:** Insufficient information to support a meaningful value.

The UI, API, and documentation must use consistent terminology.

Do not convert missing data into zero.

Do not display a scenario as an observed fact.

## 9.5 Validation and Persistence

Validate incoming data before persistence.

Use appropriate constraints for:

- Numeric values.
- Date ranges.
- Geographic identifiers.
- Required fields.
- Duplicate records.
- Source identifiers.
- Probability ranges.
- Missing or non-finite values.

Preserve enough raw source information to audit important transformations, subject to storage, licensing, and privacy constraints.

Make ingestion safe to retry.

A failed extraction must not erase previously valid records.

---

# 10. Epidemiological and Graph Models

## 10.1 Separation of Models

Implement local presence, importation, and establishment as distinct computational components.

Do not combine them into one opaque score.

Each model should expose clearly defined inputs and outputs.

Use shared schemas and documented interfaces so the frontend can display each result independently.

## 10.2 Uncertainty

Where sufficient information exists, expose low, central, and high scenarios.

Potential uncertain inputs include:

- Under-reporting multipliers.
- Passenger volumes.
- Probability of boarding while infectious.
- Screening effectiveness.
- Reproduction number.
- Cluster-size dispersion.

Document how the uncertainty band is calculated.

If the low, central, and high values are simple scenario bounds rather than statistically calibrated confidence intervals, label them as scenario ranges.

Do not describe arbitrary bounds as statistically rigorous confidence intervals.

## 10.3 Effective Distance

If effective-distance analysis is implemented, document the precise graph definition.

For a directed route network, an example is:

\[
P_{mn}=\frac{F_{mn}}{F_m}
\]

\[
d(m,n)=1-\ln(P_{mn})
\]

where \(F_{mn}\) is passenger flow from origin \(m\) to destination \(n\), and \(F_m\) is the total relevant outgoing flow from \(m\).

Effective distance is calculated using the appropriate shortest-path procedure over the resulting network.

Implementation requirements:

- Handle missing edges explicitly.
- Exclude or reject invalid flow values.
- Avoid taking the logarithm of zero.
- Document the interpretation of outgoing flow.
- Preserve edge direction where required.
- Define behavior for disconnected nodes.
- Test the implementation against small, hand-constructed graphs.

Do not infer passenger flow directly from an airport connection without an explicit estimation method.

## 10.4 Model Validation

Distinguish mathematical verification from empirical validation.

A passing unit test establishes that the code behaves as expected for the tested cases. It does not establish that the model accurately predicts real outbreaks.

Where historical evaluation is performed:

- Record the dataset and its version.
- Explain the training and evaluation periods.
- Avoid data leakage.
- Document the chosen outcome labels.
- Record evaluation metrics.
- Preserve the distinction between observed and estimated passenger flows.
- Document known biases and limitations.

Do not invent accuracy scores, historical results, or calibration claims.

---

# 11. Backend API Standards

Use FastAPI's generated API documentation as a useful development and inspection tool.

The backend should provide clearly defined endpoints for the implemented features.

Potential endpoint groups include:

```text
/health
/api/v1/outbreaks
/api/v1/outbreaks/{outbreak_id}
/api/v1/countries
/api/v1/countries/{country_code}
/api/v1/routes
/api/v1/risk/importation
/api/v1/risk/establishment
/api/v1/scenarios
/api/v1/sources
```

These are proposed endpoint names. Adjust them to the actual API design rather than creating empty endpoints to match the list.

Requirements:

- Use explicit request and response schemas.
- Validate inputs.
- Return appropriate HTTP status codes.
- Document expected errors.
- Keep computational logic outside route handlers.
- Avoid leaking internal stack traces.
- Apply sensible request timeouts.
- Avoid unrestricted outbound requests based on user-supplied URLs.
- Keep credentials out of responses.
- Version the API when appropriate.
- Provide stable identifiers for persisted entities.

An endpoint is not complete merely because it returns HTTP 200. Its response must have the documented meaning and correct behavior.

---

# 12. Frontend and User Experience

The frontend should make the underlying data and its limitations understandable.

## 12.1 Map

The map should progressively support:

- Reported outbreak locations.
- Relevant origin and destination routes.
- Route or hub visualization where data supports it.
- A selected destination.
- Risk overlays with meaningful legends.
- Distinguishable data categories.
- Tooltips and source details.
- Appropriate loading and failure states.

Do not display fabricated real-world routes or present illustrative arcs as actual passenger movement.

If illustrative data is used for a demo, identify it clearly.

## 12.2 Country Panel

A selected destination should display relevant information such as:

- Reported local outbreak status.
- Last known data-update time.
- Importation probability and time horizon.
- Establishment probability and its conditions.
- Uncertainty range.
- Important origin routes.
- Passenger-flow data quality.
- Model assumptions.
- Source links.
- Known limitations.

Do not force a numeric result when the required inputs are unavailable.

## 12.3 Scenario Controls

Where implemented, expose meaningful controls for model assumptions.

For example:

- Time horizon.
- Under-reporting multiplier.
- Passenger-volume assumptions.
- Screening effectiveness.
- Reproduction number.
- Dispersion parameter.

Controls must have valid ranges and understandable labels.

The UI must explain whether changing a control alters a model assumption, an estimated input, or a scenario-only value.

## 12.4 Accessibility and Resilience

Provide:

- Readable contrast.
- Accessible form controls.
- Keyboard-operable interactions.
- Clear labels and units.
- Useful empty states.
- Loading indicators.
- Actionable error messages.
- A distinction between stale and current data.
- A usable fallback when external services are unavailable.

Do not make color the only way to communicate data classifications.

---

# 13. Offline Mode and Reliability

The MVP should remain demonstrable without requiring every external API to be available.

Implement this incrementally.

The intended behavior is:

1. The application starts with local configuration.
2. Existing cached data can be loaded.
3. The map and core analysis can use the cached snapshot.
4. Failed live ingestion is reported clearly.
5. Previously validated data remains available.
6. The UI identifies stale data and its retrieval time.
7. Live services resume when they become available.

Do not claim that the application works offline until the relevant paths have actually been tested.

Do not overwrite valid cached data with an empty response caused by a failed request.

Use bounded retries, sensible timeouts, and structured error logging.

Avoid uncontrolled polling or repeated external API calls.

---

# 14. Security and Configuration

## 14.1 Secrets

Store sensitive configuration in environment variables.

Provide `.env.example` with placeholder values and descriptions.

Never commit actual credentials.

At minimum, any TinyFish API key must remain on the backend.

Do not place secrets in:

- Frontend source code.
- Public frontend environment variables.
- Browser bundles.
- Git history.
- Logs.
- Screenshots.
- Documentation examples containing real credentials.

If a credential is accidentally exposed, stop using it, report the issue, and follow the appropriate rotation procedure.

## 14.2 External Input

Treat API responses, extracted web content, uploaded datasets, and user input as untrusted.

Validate them before processing.

Avoid unsafe deserialization, unrestricted file access, shell injection, and arbitrary outbound network requests.

Do not execute instructions extracted from external documents as if they were trusted developer instructions.

## 14.3 Configuration

Centralize application settings.

Use sensible defaults for local development.

Distinguish required settings from optional integrations.

Fail with clear messages when a required configuration value is missing.

Do not fail application startup merely because an optional data provider is not configured.

---

# 15. Dependencies and Reproducible Builds

- Commit the appropriate dependency manifests and lockfiles.
- Pin or constrain dependencies according to the chosen package-management strategy.
- Avoid unnecessary dependency additions.
- Prefer actively maintained packages.
- Document significant dependencies.
- Check for known vulnerabilities when appropriate.
- Keep setup commands reproducible.
- Do not modify lockfiles manually when the package manager should regenerate them.
- Verify dependency changes with the appropriate tests and build checks.

When introducing a dependency, explain why it is needed if the reason is not obvious.

Do not introduce a large framework to solve a small problem without justification.

---

# 16. Development Priorities

Work in vertical slices rather than creating the entire backend first and leaving the frontend until the end.

A vertical slice should include the minimum necessary implementation, tests, documentation, and integration to demonstrate a useful piece of functionality.

## Phase 0 — Repository Foundation

Establish:

- A working Git repository.
- Project structure appropriate to the existing code.
- Python and frontend dependency management.
- The root `justfile`.
- Basic configuration and `.env.example`.
- A useful README.
- Linting, formatting, and testing infrastructure.
- A minimal health endpoint.
- A minimal frontend startup path.

Verify that a new developer can set up and run the project.

## Phase 1 — First End-to-End Slice

Implement a minimal path through the application:

1. Load a small, clearly identified outbreak dataset.
2. Validate its schema.
3. Persist or cache the records.
4. Expose them through the backend API.
5. Fetch them from the frontend.
6. Display the available reports.
7. Show source information.
8. Add tests and documentation.

This slice should work before introducing complex epidemiological models.

## Phase 2 — Real Outbreak Ingestion

Add:

- WHO report retrieval.
- Response parsing.
- Source normalization.
- Validation.
- Duplicate handling.
- Provenance storage.
- Error handling.
- Cached data fallback.

Introduce TinyFish extraction only where needed to obtain fields unavailable in structured source data.

Do not make the whole application dependent on successful extraction.

## Phase 3 — Importation Model

Implement:

- Explicit model inputs.
- Passenger-flow representation.
- Prevalence inputs.
- Boarding probability.
- Screening assumptions.
- Time-horizon calculations.
- Boundary-condition tests.
- Uncertainty scenarios.
- API integration.
- UI presentation.

Ensure that missing inputs produce an explicit unavailable result rather than a fabricated estimate.

## Phase 4 — Interactive Map

Integrate:

- Geographic boundaries.
- Outbreak locations.
- Destination selection.
- Source-backed report details.
- Relevant route visualization.
- Risk overlays.
- Tooltips and legends.

Only render data that the current implementation actually supports.

## Phase 5 — Establishment Model

Implement the selected branching-process method.

Document its mathematical assumptions, validate numerical behavior, and expose its output separately from importation risk.

Add the necessary tests and scenario controls.

## Phase 6 — Offline Reliability and Demo Polish

Add:

- Cached snapshots.
- Stale-data indicators.
- Graceful API failure handling.
- Clear loading and error states.
- Reproducible startup.
- Integration tests.
- Build verification.
- Demo documentation.

## Phase 7 — Optional Advanced Features

Only after the core MVP is reliable, consider:

- Effective-distance ranking.
- Hub-based route analysis.
- Historical calibration.
- Held-out outbreak evaluation.
- Automated report monitoring.
- Human-confirmed policy extraction.
- More sophisticated passenger-flow estimation.
- Additional geographic resolution.

Do not begin a sophisticated calibration pipeline while the basic application cannot reliably load and display outbreak records.

---

# 17. Definition of Done

A feature is complete only when the applicable requirements below have been satisfied.

### Implementation

- [ ] The feature solves the stated problem.
- [ ] It follows the established architecture.
- [ ] Inputs are validated.
- [ ] Errors are handled.
- [ ] Existing functionality is not unintentionally broken.
- [ ] No unrelated changes have been introduced.

### Tests

- [ ] Relevant unit tests exist.
- [ ] Relevant integration tests exist where needed.
- [ ] Boundary cases are covered.
- [ ] The relevant test suite passes.
- [ ] Any tests that could not be executed are explicitly identified.

### Documentation

- [ ] Public interfaces are documented.
- [ ] Non-obvious logic has appropriate comments.
- [ ] Mathematical assumptions are explained where relevant.
- [ ] Relevant documentation is updated.
- [ ] The README or `justfile` is updated if developer workflows change.
- [ ] Known limitations are documented.

### Tooling

- [ ] Relevant lint checks pass.
- [ ] Formatting is correct.
- [ ] Type checks pass where applicable.
- [ ] The build succeeds where applicable.
- [ ] Relevant commands are available through the root `justfile`.

### Git

- [ ] The diff has been reviewed.
- [ ] No secrets or unintended files are staged.
- [ ] The change is committed as a small, meaningful unit.
- [ ] The commit message follows the project's conventions.
- [ ] The working tree is in the expected state.

### Data and scientific correctness

For features involving epidemiological data:

- [ ] Sources are recorded.
- [ ] Data classifications are correct.
- [ ] Missing values are handled explicitly.
- [ ] Units are documented.
- [ ] Assumptions are visible.
- [ ] Numerical behavior is tested.
- [ ] Claims about validation are supported by actual evidence.

Not every checklist item applies to every change. Explain genuinely inapplicable requirements rather than mechanically performing irrelevant work.

---

# 18. Rules for AI Coding Agents

AI agents must follow these additional rules.

## 18.1 Inspect Before Editing

Before changing code:

- Inspect the repository structure.
- Read this `AGENTS.md`.
- Read relevant module documentation.
- Review the existing implementation.
- Check Git status.
- Identify the smallest useful next step.

Do not assume that a proposed architecture has already been implemented.

Do not overwrite working code without understanding its role.

## 18.2 Plan in Small Units

For substantial tasks, produce a short implementation plan with independently verifiable steps.

For example:

```text
1. Define the report schema.
2. Add schema validation tests.
3. Implement the parser.
4. Test malformed and incomplete records.
5. Document parser behavior.
6. Commit the parser implementation.
7. Integrate it with the ingestion service.
```

Then implement the steps incrementally.

Avoid generating an entire application in one operation.

## 18.3 Verify Before Claiming Success

After editing:

- Inspect the final diff.
- Run relevant checks through `just`.
- Read the test output.
- Investigate unexpected failures.
- Commit the completed logical unit.
- Report the actual result.

Do not claim that code compiles, tests pass, an API works, or a feature is complete without appropriate verification.

If verification is blocked, explain why and identify what remains unverified.

## 18.4 Do Not Invent Results

Never invent:

- API responses.
- External source records.
- Passenger volumes.
- Epidemiological measurements.
- Model calibration results.
- Test results.
- Commit hashes.
- Successful deployments.

Illustrative fixtures are acceptable when clearly labelled and kept separate from real observations.

## 18.5 Avoid Overengineering

Do not introduce:

- Microservices without a demonstrated need.
- Complex dependency-injection frameworks without a demonstrated need.
- Premature plugin architectures.
- Multiple competing configuration systems.
- Abstractions with only one trivial use.
- Unnecessary background workers.
- Sophisticated model calibration before the required data exists.

Prefer the simplest implementation that satisfies the requirements and leaves a reasonable path for future development.

## 18.6 Preserve Human Work

Do not remove or overwrite user-authored changes without understanding their purpose.

Do not revert unrelated modifications.

If a requested change conflicts with existing project decisions, explain the conflict and propose the smallest appropriate adjustment.

## 18.7 Keep Documentation Synchronized

When changing a public interface, update its documentation.

When changing a model, update its equations, assumptions, and tests.

When adding a script or operational command, update the root `justfile`.

When changing setup requirements, update the README and relevant development documentation.

Do not defer all documentation to the end of the project.

## 18.8 Report Progress Honestly

When working on a larger task, report progress in meaningful units rather than repeatedly claiming that the whole feature is nearly finished.

A useful progress report looks like:

```text
Completed:
- Added the outbreak report schema.
- Added tests for required and optional fields.
- Documented country-code normalization.
- Verified the relevant tests.

Commits:
- feat(schemas): add outbreak report schema
- test(schemas): cover outbreak report validation
- docs(schemas): document report fields

Remaining:
- Integrate the schema with the ingestion service.
```

The example illustrates the expected reporting style; only report work that was actually performed.

---

# 19. Final Operating Rules

These rules take precedence over convenience.

1. Make small, meaningful changes.
2. Commit completed units of work frequently.
3. Test before committing.
4. Document behavior, assumptions, and public interfaces.
5. Maintain the root `justfile` as the primary command interface.
6. Preserve the distinction between observed, estimated, modelled, scenario, and unknown values.
7. Never fabricate scientific evidence or test results.
8. Keep external API credentials server-side.
9. Preserve existing user work.
10. Prefer a reliable end-to-end MVP over an unfinished collection of advanced features.

**The standard for EpiRoute is not simply that the application runs. The codebase must be understandable, reproducible, testable, scientifically transparent, and easy for another developer to continue working on.**
