# What is actually modelled, and the mathematics of it

EpiRoute fits three statistical models and evaluates a fourth as a challenger. None of them is a neural network. Everything else on screen is closed-form epidemiology evaluated per request, not a trained model.

| Model | What it answers | Served to the website |
| --- | --- | --- |
| Next-country hazard | Chance a country that has not reported yet files its first report within 28 days | **Yes**, for every disease, as an ordering. The percentage is indicative and carries a band. |
| Gravity regression | Passenger volume on a country pair no statistical office reports | **Yes.** Those volumes feed the arrival rate used everywhere else. |
| Gradient-boosted trees | The same question as the hazard, three features | No. It is fitted and scored on every training run as a challenger, and it loses on the split that matters. |
| Branching process | Chance one introduction starts sustained transmission | Served, but it is solved per request from the pathogen profile, not fitted to data. |

Training is offline. Nothing refits while the site is open. `just train-model` writes `data/processed/model_card.json` and regenerates `MODEL_EVALUATION.md` in the repository root. A request only reads the card.

`MODEL_EVALUATION.md` is the live numbers. This document is the reasoning: what each formula is, why that formula and not another, and what the measurements mean.

---

## 1. The next-country hazard

### The question, stated precisely

Fix a destination country *i* that has not yet reported a case of the disease, and fix a moment *t*. Let *T<sub>i</sub>* be the day its first report is published. The model estimates

> P(*T<sub>i</sub>* ≤ *t* + *H*) for *H* = 28 days

This is a **survival** question — the time until a first event — and the model's form follows from that rather than from convenience.

### Why complementary log-log

Suppose first reports arrive as a Poisson process with a constant rate λ<sub>i</sub> events per day over the horizon. Then the number of reports in *H* days is Poisson(λ<sub>i</sub>*H*), and

```
P(at least one report in H days) = 1 − exp(−λ_i · H)
```

Let the rate depend on covariates through a log link, λ<sub>i</sub> = exp(η<sub>i</sub>) with η<sub>i</sub> = **x**<sub>i</sub>ᵀ**β**. Substituting:

```
P_i = 1 − exp(−exp(η_i) · H)
```

Rearranged, that is the complementary log-log link:

```
log(−log(1 − P_i)) = η_i + log H
```

Three properties follow, and each is the reason this link was chosen over logistic regression.

**The horizon is inside the model.** `log H` enters as a known offset. A model fitted at *H* = 28 can be evaluated at *H* = 7 by changing one number, and the coefficients keep their meaning. A logistic model fitted to the same 0/1 labels has no *H* in it at all: its intercept silently absorbs the horizon, so its coefficients mean something different for a 7-day question than for a 28-day one, and there is no correct way to re-express them. The app exposes the horizon as a control, so this matters.

**The coefficients are rate multipliers.** exp(β<sub>j</sub>) is the factor by which the *hazard* changes per unit of *x<sub>j</sub>*, not an odds ratio. Doubling passenger volume multiplies the arrival rate, which is a mechanistic statement; it does not multiply an odds.

**It is asymmetric in the right direction.** Almost every row of the panel sits at a tiny rate, where `1 − exp(−λH) ≈ λH`. The link is near-linear in the rate in exactly the regime where the data lives, and saturates at 1 only when the rate is large. A logit is symmetric about 0.5, which is nowhere near where these events are.

To stop a wild coefficient overflowing, η is clipped to [−40, 40] before exponentiating.

### The features

Each training row is one destination in one forecast week, for a destination that had **not** reported by that week. Four columns, intercept first:

| Column | Definition | Monotone? |
| --- | --- | --- |
| 1 | intercept | — |
| `log_lambda` | log λ<sub>i</sub>, the modelled infectious-arrival rate per day, floored at 10⁻¹² | β ≥ 0 |
| `log_inbound` | log(1 + daily passengers arriving from countries that have already reported) | β ≥ 0 |
| `log_affected` | log(1 + number of countries that have already reported) | free |

The arrival rate is

```
λ_i = Σ over affected origins j  ( prevalence_j × passengers_{j→i} per day × α )
```

and the prevalence of origin *j* in the training panel is

```
prevalence_j = (new cases in the latest already-published week / 7) × D × u / population_j
```

with *D* = 7 days infectious, *u* = 4× under-reporting, α = 0.5 boarding factor. An origin with no weekly case row yet is treated as one new case per week. Screening σ is not in the training rate; it is a live scenario control only.

The monotone constraints are not regularisation. They are the statement that this is a mechanism: a higher arrival rate, or more arriving passengers, may not *lower* the estimated chance of a first report. A fit that wanted to say otherwise would be fitting noise, and the constraint says so out loud.

`log_affected` is unconstrained because its sign is a genuine empirical question. It is fitted **negative** (−0.387), and that is interpretable: as an outbreak spreads, the countries still unreported are increasingly the ones least connected to it. It is a survivorship term, and the data says it points down.

### What the coefficient of exactly zero means

The served fit is

```
η = −7.5914 + 0.0000 · log_lambda + 0.4919 · log_inbound − 0.3872 · log_affected
```

`log_lambda`'s coefficient is **zero**, sitting on its constrained boundary. This is the single most important fact about the model and it is not a bug.

On the rows that have travel evidence, `log_lambda` and `log_inbound` correlate at **0.74**. λ is a product of prevalence and passengers, so it carries passenger volume inside it. Separating the two:

| quantity | correlation with the label |
| --- | --- |
| `log_inbound` (passenger volume) | **0.305** |
| `log_lambda` (rate) | 0.075 |
| log(λ / inbound) — the passenger-weighted mean origin prevalence | **−0.055** |

The prevalence *composition* of λ carries no signal about which country reports next. Passenger volume carries nearly all of it. So the unconstrained optimum for β on `log_lambda` is slightly negative, the monotone projection clips it to zero, and the term drops out.

The ablation `hazard_without_lambda` removes it entirely and **reproduces the served model to every printed digit on every fold**. That is the proof, not the suspicion.

The term is kept anyway, constrained to be non-negative, so that its measured zero appears as a row in `MODEL_EVALUATION.md` rather than as an omission nobody can see. A reader who wants to know whether EpiRoute's case-count pipeline improves on raw air traffic gets an answer: on this evidence, for this question, it does not.

That is a statement about *this panel and this question*, not about prevalence in general. Prevalence is doing real work in the importation and establishment probabilities on the country panel, which are different questions with different evidence.

### How it is fitted

Maximum penalised likelihood, by projected gradient ascent. For *n* rows with labels *y<sub>i</sub>* ∈ {0,1}, writing *r<sub>i</sub>* = *H*·exp(η<sub>i</sub>):

```
ℓ(β) = Σ_i [ y_i · log(1 − exp(−r_i)) − (1 − y_i) · r_i ] − ρ · Σ_{j≥1} β_j²
```

The first bracket is the Bernoulli log-likelihood under *P<sub>i</sub>* = 1 − exp(−*r<sub>i</sub>*): an event contributes log *P<sub>i</sub>*, a non-event contributes log(1 − *P<sub>i</sub>*) = −*r<sub>i</sub>* exactly.

The gradient with respect to η<sub>i</sub> is

```
∂ℓ/∂η_i = r_i · ( y_i · exp(−r_i)/(1 − exp(−r_i)) − (1 − y_i) )
```

and ∇<sub>β</sub>ℓ = **X**ᵀ(∂ℓ/∂η) − 2ρ·β (intercept excluded from the penalty). For a tiny rate, `exp(−r)/(1 − exp(−r))` loses all precision, so it is replaced by its limit 1/*r* below *r* = 10⁻⁸. Almost every row of this panel is in that regime, so this is not an edge case — it is the common path.

Four implementation choices, each with a reason:

**Ridge ρ = 10⁻³ on slopes only.** It keeps the Hessian conditioned when a column is nearly collinear with another — which, given the 0.74 correlation above, is the actual situation. It excludes the intercept because penalising the intercept shrinks the predicted base rate towards 0.5, which is not a prior anyone holds about first-report hazards.

**Columns are standardised before fitting, and coefficients returned on the original scale.** This was not cosmetic. One scalar step size cannot suit a matrix whose columns are a column of ones, a log rate near −12 and a log passenger count near 8: the well-scaled directions converge while the others crawl, and the fit stops with the *mean* probability about right and the individual slopes still near where they started.

On synthetic data at those column scales, with true slopes [0.8, 0.2, 0.3] and an intercept of 3.25 (4,000 rows, base rate 0.47):

| | intercept | slope 1 | slope 2 | slope 3 |
| --- | --- | --- | --- | --- |
| truth | 3.25 | 0.80 | 0.20 | 0.30 |
| unstandardised fit | −2.30 | 0.45 | 0.30 | 0.54 |
| standardised fit | 3.44 | **0.82** | **0.20** | **0.31** |

Every slope is wrong without the step and every slope is recovered with it. Without it the model looked like it had learned nothing, and the diagnosis was the optimiser, not the data. `test_badly_scaled_columns_still_recover_every_slope` pins this.

**Armijo backtracking.** Each iteration halves the trial step up to 40 times until the penalised likelihood strictly improves, then grows the next step by 1.5×. A step that cannot improve ends the fit. At most 2000 iterations; gradient-norm tolerance 10⁻⁹.

**The monotone constraint is a projection, not a penalty.** After each step, a constrained coefficient that went negative is set to 0. So the fitted value is either exactly zero or a genuine interior optimum — never a compromise between the data and a penalty weight someone chose. That is what makes "the coefficient is zero" a measurement.

**The intercept is initialised to reproduce the observed base rate** with every slope at zero: β<sub>0</sub> = log(−log(1 − ȳ)/*H*). A fit that cannot improve on that is then visibly a model that learned nothing, rather than one that failed to converge.

The fit is deterministic. No random seed, no shuffling, no initialisation noise.

### How it is scored

Two splits, because they answer two different questions.

**Leave-one-outbreak-out.** Fit on mpox, score every COVID-19 country-week. Fit on COVID-19, score every mpox country-week. This is the split that decides serving, because every disease in the app other than those two is a pathogen the model has never seen — which is exactly the position a held-out fold puts it in.

**Forward chaining.** Fit on the first *k* weeks of one outbreak, score the weeks after them, for *k* = 4…15. Twenty-three folds. This is the question the app asks week to week, and it gives enough folds for a spread to mean something.

Leakage guards, enforced in code rather than by convention:

- A row's `latest_input_at` must not be after its `forecast_at`. No row may be scored using evidence published after the moment being forecast.
- An outbreak may not appear on both sides of a leave-one-out fold.
- Passenger flows come from a fixed era per outbreak, not from a table that has since been updated with later data.
- A **permutation test**: refit on shuffled training labels, score the untouched test fold, five seeded rounds. The served model scores 0.535 — near chance, so no feature is secretly carrying the answer. *The monotone constraint is dropped for the permutation fit only*, because a constrained fit on noise can only return zero or positive slopes, and a positive slope ranks the right way; leaving the constraint in produced a spurious 0.55–0.57 and the number meant nothing.

### The metrics, defined

| Metric | Definition | Reading |
| --- | --- | --- |
| Brier score | mean((*P<sub>i</sub>* − *y<sub>i</sub>*)²) | Lower is better. Decomposes into calibration + refinement, so it penalises both a wrong level and a useless ordering. |
| Brier skill | 1 − (model Brier / reference Brier) | Positive means it beats that reference. Negative means the reference won. |
| ROC AUC | P(a random positive scores above a random negative) | 0.5 is chance. This is a pure **ordering** measure and ignores the level entirely. |
| Calibration slope | slope of logit(observed rate) on logit(mean prediction) across up to 10 quantile bins | 1 means predictions move one-for-one with reality. <1 means over-confident spread. |
| Calibration intercept | that same line read at a predicted probability of ½ | 0 means the level is right. The sign says which way it is wrong. |
| Top-20 precision | share of the 20 highest-scored rows that did report | What the screen actually shows. |
| Top-20 recall | share of *all* positives inside those 20 rows | **Reported, not gated.** With 642 positives in a fold, 20 rows cap recall at 0.031. A 0.5 bar on it was unreachable by construction and had to go. |
| Arrival-order ρ | Spearman correlation between score and actual day of first report, among rows that did report | Measures ordering *in time*, which is a harder question than ordering by whether. |

Calibration is fitted on centred *x* and the intercept reconstructed, because `polyfit` on uncentred logits was ill-conditioned and emitted warnings; a degenerate bin spread or a `LinAlgError` returns NaN rather than a fabricated number.

### The three-way status, and why it exists

A single pass/fail flag forced a false choice: either serve a model whose ordering is good and whose level is wrong, labelled "calibrated", or serve nothing. So the gates are split.

| Status | Means | Effect |
| --- | --- | --- |
| `calibrated` | ranking **and** calibration gates pass on both folds | Order and percentage both served as findings. |
| `ranking_validated` | ranking gates pass on both folds; calibration does not | Order served. Percentage shown as indicative with a band and a note. Map still shades. |
| `not_validated` | ranking gates fail, or the panel hash does not match the card | Falls back to the plain Poisson formula, labelled as such. |

Ranking gates: `brier_skill_vs_uncalibrated` ≥ 0.10, `roc_auc` ≥ 0.70, `monotone_in_lambda`.
Calibration gates: `calibration_slope` in [0.5, 1.5], |`calibration_intercept`| ≤ 0.5.

The current status is **`ranking_validated`**. Both folds pass every ranking gate (AUC 0.783 and 0.768). Both fail the calibration intercept — at +1.11 and −1.64, roughly one logit from zero **in opposite directions**.

That opposite sign is the whole diagnosis. COVID-19's panel has 642 positives in 1893 rows (34%); mpox's has 334 in 2925 (11%). The base rate differs threefold. A single intercept fitted on one pathogen cannot level the other, and whichever one you fit on, you miss the other in the opposite direction.

### The repair that was tried and rejected

The slopes transfer well — 0.92 and 1.21, close to the ideal 1. Only the level is wrong. So the obvious fix is to keep the transferred slopes and refit *only the intercept* online, on the live outbreak's own first reports, using only weeks whose 28-day label window has already closed (no leakage). That was implemented and measured:

| held-out outbreak | | AUC | Brier | slope | intercept |
| --- | --- | --- | --- | --- | --- |
| covid_2020 | transferred | 0.783 | 0.250 | 0.92 | 1.11 |
| covid_2020 | refitted online | 0.569 | 0.261 | 0.29 | −0.18 |
| mpox_2022 | transferred | 0.768 | 0.149 | 1.21 | −1.64 |
| mpox_2022 | refitted online | 0.670 | 0.116 | 0.33 | −1.94 |

It does what it was designed to do to COVID-19's level — 1.11 to −0.18, inside the gate — and it destroys the ordering. AUC falls from 0.783 to 0.569, and the slope collapses on both folds.

The reason is structural, not a tuning failure. An intercept refitted each week is a *different* intercept each week, so rows from different weeks are no longer scored on one scale, and the pooled ordering is exactly what breaks. It would buy a calibration gate by spending the only thing the model has earned.

So the status stays `ranking_validated`, and nothing in the serving path rescales the probability. The level of a first-report hazard depends on the pathogen and on how hard countries are looking for it. Two outbreaks are not enough to learn it, and no amount of post-processing on two outbreaks adds a third.

### Overfitting, measured rather than asserted

Every fold reports train Brier, test Brier and the gap.

- Held-out mpox: test − train = **−0.051**. The model does *better* on data it never saw, which happens when the held-out fold has an easier base rate. Not overfitting.
- Held-out COVID-19: **+0.165**. Real, and consistent with 4 parameters on 4,818 rows being asked to transfer between two different pathogens.
- Forward chaining: gaps run +0.24 early (few positives, wide variance) to −0.10 late.

Four parameters on 4,818 rows is the main defence. The ablation table is the second: a feature that does not earn its place is visible as an ablation that scores as well without it.

### The feature that was rejected for not transferring

`hazard_with_population` adds log₁₀ destination population:

| | forward-chained AUC | held-out mpox AUC | held-out mpox Brier |
| --- | --- | --- | --- |
| served (no population) | 0.745 | **0.768** | **0.149** |
| with population | **0.803** | 0.633 | 0.209 |

Population is the best feature available *inside* an outbreak and one of the worst *across* pathogens. That is not surprising on reflection — how much of a population is exposed depends on how the pathogen spreads, so a population coefficient learned on a respiratory virus is a wrong coefficient for a contact-network one. It is excluded, and the numbers that excluded it are printed.

This is also the clearest illustration of why forward chaining alone would have been the wrong basis for a decision: it would have chosen the feature that fails on new pathogens, which is the app's actual use case.

### What the model does not do

- **It does not order arrivals in time.** Arrival-order ρ is 0.007 and 0.063 across the held-out folds — chance. The app's arrival-order view is a record of what happened, not a forecast of what will.
- **It does not give a trustworthy absolute probability for a pathogen outside the panel.** See the calibration section. The served band comes from refitting without each outbreak, so it is the spread between those two worlds — not a confidence interval.
- **It says nothing where no passengers arrive from an affected country.** 7.0% of panel rows are in that position. Serving returns `no_inbound_travel_from_affected_countries` rather than handing back the intercept as if it were a finding.

### How it is served

A request to `GET /api/v1/risk/next` computes, for each destination with no report:

1. λ and inbound passengers summed over affected origins, from live data.
2. The number of affected origins.
3. η from the card's `served_beta`, then *P* = 1 − exp(−exp(η)·28).
4. A low–high band by re-evaluating with each fold's coefficient vector (`band_beta`).

The card is refused — and the plain Poisson formula used instead, labelled — if the file is missing, the status is `not_validated`, the horizon is not 28, the travel coefficients are negative, or `panel_sha256` no longer matches `data/labels/panel.parquet`. That last check is what stops a card from outliving the data it was validated on.

The model serves **every** disease, not just the two it trained on, and the response says so: `"This pathogen is not in the training panel."` Earlier versions restricted serving to COVID-19 and mpox, which was backwards — a held-out fold is precisely a measurement of how the model does on a pathogen it has not seen, and both held-out folds passed their ranking gates. Restricting serving to the two trained outbreaks withheld the model from exactly the case its evaluation covers.

---

## 2. The challenger: gradient-boosted trees

A monotone-constrained `HistGradientBoostingClassifier` on the same features, the same two splits, the same gate thresholds and the same status rule. `max_depth=2`, `max_iter=50`, `learning_rate=0.1`, `random_state=0`, `monotonic_cst=[1, 1, 0]`. Depth two and fifty rounds because the panel has 976 positives across two outbreaks: a deeper or longer ensemble has room to fit one outbreak's idiosyncrasies and nothing to stop it.

For a long time this never ran at all. scikit-learn was declared in the `dev` extra and never installed, so the comparison returned `None` on every training run and the card recorded nothing. With it installed:

| | Challenger AUC | Served AUC | Challenger Brier | Served Brier |
| --- | --- | --- | --- | --- |
| held out covid_2020 | 0.644 | **0.783** | **0.246** | 0.250 |
| held out mpox_2022 | 0.684 | **0.768** | 0.267 | **0.149** |
| forward chaining (mean of 23) | 0.731 | **0.745** | **0.115** | 0.172 |

Read the two together. **Inside** an outbreak the ensemble wins on Brier, because the weeks it predicts resemble the weeks it was fitted on. **Across** pathogens it loses, and loses on the measure that matters for a disease the model has never seen. That gap is the overfitting the held-out split exists to expose, and it is the argument for serving four parameters instead of fifty trees.

It is recorded rather than served even if it were to win, for two reasons stated on the card. A tree ensemble predicts a *constant* outside the range of arrival rates it was fitted on, and a new pathogen is exactly the case that sits outside that range. And serving it would mean storing a fitted estimator in `data/` and deserialising it on the request path, coupling the running API to a library version, for a model whose advantage — if it had one — is a few hundredths of a Brier score.

What would change that decision is recorded on the card too: a third and fourth training outbreak, so that a held-out fold becomes a test of generalisation rather than a test of transfer between two pathogens.

---

## 3. The gravity model for passenger flows

This one runs as part of building the passenger table (`just model-fit`), not inside `just train-model`. It exists because Eurostat and the US DOT between them observe only **1,884 of the 50,400** directed country pairs the app needs — 3.7%. A missing flow cannot be treated as zero without silently claiming two countries are unconnected. (Those 3.7% of pairs are not 3.7% of the traffic that matters: weighted by the flows that actually enter a destination's arrival rate, the observed share averages 9.7% per panel row.)

Ordinary least squares via `numpy.linalg.lstsq` on observed pairs:

```
log10(passengers per day) = b0
  + b1 · log10(origin population)
  + b2 · log10(destination population)
  + b3 · log10(distance in km)
  + b4 · log10(1 + direct OpenFlights routes)
  + b5 · log10(1 + airlines on those routes)
```

This is the standard gravity specification from trade and transport economics: interaction scales with the product of masses and decays with distance, which is linear in logs. The two route-topology terms are not part of the classical form; they are there because scheduled connectivity is a stronger predictor of passenger volume than distance alone, and OpenFlights provides it.

At least 100 observed flows are required. The holdout is 20% of **unordered** country pairs at seed `20261024` — unordered so that a route and its reverse cannot be split across the split, which would leak.

Exponentiating a least-squares prediction on a log scale gives the **median**, not the mean, of a log-normal. The stored flow is corrected to the mean by shifting with the log₁₀ residual spread. Getting this wrong understates every modelled flow by a systematic factor.

The residual spread becomes a **multiplicative** uncertainty band on modelled routes, capped at 100×, and pairs with no OpenFlights route get a wider band (residual scale × 1.5). Multiplicative because the error is log-normal: a flow of 10 and a flow of 10,000 do not have the same absolute uncertainty. That factor is what carries flow uncertainty into the low–high risk band, so the band widens on exactly the routes where the passenger figure is a guess.

Held-out metrics are returned by `GET /api/v1/model/gravity` and printed in `MODEL_EVALUATION.md`: `r2_log`, `mae_log10`, `rmse_log10`, `median_ratio_error`, and the share of pairs within 2×, 5× and 10×. The API labels these passenger numbers as `modelled`, never `observed`.

---

## 4. The per-request epidemiology

These are solved on every risk request from `backend/src/epiroute/epidemiology/`. They are not loaded from `model_card.json` and nothing about them is fitted.

### Prevalence from a cumulative count

WHO publishes cumulative totals; the model needs people who are infectious *now*. With two reports for the same country and pathogen:

```
infectious = (new cases / days between reports) × D × u
prevalence = infectious / population
```

With one report and a stated outbreak start of age *A* days, cases are assumed to have accumulated evenly:

```
infectious = cumulative cases × min(1, D / A) × u
```

The `min(1, D/A)` is the fraction of cases still within one infectious period. An outbreak younger than *D* has had no time for recoveries, so the fraction is 1. Without this factor, treating every historical case as currently infectious inflates prevalence by *A*/*D* — about 13× at the 90-day age assumed when a report states no start date, and 52× for an outbreak a year old, with a 7-day infectious period.

A flat or downward-revised total yields **no** prevalence rather than zero: the outbreak may simply have stopped, and the model does not invent current cases from an old cumulative number.

### Importation

Arrivals as a Poisson process. Per origin: `prevalence × passengers per day × α × (1 − σ)`. Summed over origins to give λ, then `P = 1 − exp(−λT)`. Same algebra as the hazard's link function, with no fitted coefficients — which is exactly why the fitted hazard is worth having: it asks whether that arithmetic can be improved on by learning from what actually happened.

### Establishment

Each arrival starts a branching process whose offspring distribution is negative binomial with mean *R* and dispersion *k* (Lloyd-Smith et al., *Nature* 2005 — chosen over Poisson offspring because superspreading is the dominant feature of real introduction data, and *k* ≈ 0.1 for SARS-CoV-2 means most introductions die out even when *R* is well above 1).

The extinction probability *q* is the smallest root in [0,1] of the probability generating function fixed point:

```
q = (1 + R(1 − q)/k)^(−k)
```

One introduction establishes with probability 1 − *q*. Establishing introductions are a thinned Poisson process, so

```
P(spread takes off in T days) = 1 − exp(−λ · T · (1 − q))
```

If *R* ≤ 1 extinction is certain and this is 0 — a result, not a missing value. Vector-borne and waterborne diseases get no *R*: whether they establish depends on mosquito ecology or on water and sanitation, which this model does not represent, so establishment is reported as not estimable while importation is still reported.

### Travel-risk index

A weighted mean of the available answers, scaled 0–10: local presence 0.40, importation 0.30, establishment 0.15, connectivity 0.15. A missing input is dropped and the remaining weights renormalised — never replaced with zero. If every input is missing the index is not estimable. It is a scenario composite, it has not been validated against later outbreaks, and the next-country hazard is deliberately **not** an input to it.

---

## 5. Where the training data comes from

| Input | Source | Note |
| --- | --- | --- |
| First-report dates, COVID-19 | Johns Hopkins CSSE confirmed time series | Cross-checked against Our World in Data. |
| First-report dates, mpox 2022 | Global.health line list | Our World in Data mpox file as fallback. |
| Weekly case counts (training prevalence) | The same two sources | 195 countries of COVID-19 weekly cases. |
| Passenger flows | Eurostat `avia_par`, US DOT T-100 | Observed where published; gravity-modelled elsewhere, and labelled. |
| Population | UN World Population Prospects 2024 | Denominator for prevalence. |
| Route topology | OpenFlights airports and routes | Feeds the gravity model's connectivity terms. |

These training label files are **separate** from the WHO bulletins the live map counts as reports. That separation is deliberate: the labels are what happened, the bulletins are what a user can click through to.

### The COVID-19 exception in the live data

Every disease in the live map comes from WHO Disease Outbreak News — except COVID-19, and the reason is worth recording because it looked like a bug for a long time.

WHO stopped describing COVID-19 in Disease Outbreak News after January 2020 and moved it to a dedicated dashboard. Of 3,159 bulletins in the DON archive, only **17** published after December 2019 mention COVID-19 at all, and most of those are variant notices carrying no country counts. Grounding those against their narratives yields 10 reports over 6 countries. The DON archive is simply not the surveillance record for this one disease.

So COVID-19's counts are read from WHO's own `WHO-COVID-19-global-daily-data.csv` and written into the same report and observation tables, one report per calendar month, dated at the last day WHO actually reported inside that month. COVID-19 now covers 227 countries, 778,558,360 cumulative cases and 7,113,255 deaths — a case fatality ratio of 0.91%, matching WHO's published totals. Nothing downstream needs a special case.

A country only enters a snapshot when its cumulative total **moved** since the previous one. WHO repeats every country's running total every day whether or not it changed, and storing an unmoved total as a fresh observation would say the country reported this month when it stopped reporting years ago. In the last month of the file only 49 of 227 countries moved; carrying the other 178 forward made every one of them register as currently reporting, which took the "active in the last 90 days" view from 55 countries to 227 and flattened the map. Dropping them loses nothing, because the series is a running maximum: a country's total still stands at whatever the last month that moved it recorded.

Because WHO revises that file in place, `just data-fingerprint` reports its SHA-256 alongside every grounded figure. Two checkouts that downloaded it on different days now get a one-line diff instead of a mystery.

---

## 6. Reproducing all of it

```bash
just data-fetch        # reference datasets
just data-build        # processed tables
just data-load         # into PostgreSQL
just model-fit         # the gravity model
just ingest-archive    # WHO DON, offline, deterministic
just ingest-covid      # WHO's COVID-19 table
just labels-build      # first-report dates and weekly cases
just train-model       # panel, folds, gates, card, MODEL_EVALUATION.md
just data-fingerprint  # compare two checkouts
```

`just train-model` rebuilds the panel only when asked (`--rebuild-panel`) or when it is missing, so a training run on an unchanged panel is reproducible and fast. Panel build is 1.8 seconds; the full training run is under a minute.
