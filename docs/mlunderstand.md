# What is actually modelled

EpiRoute fits three numerical models. They do not all run in the product, and none of them is a neural network.

| Model | What it answers | Served to the website today |
| --- | --- | --- |
| Next-country hazard | Chance a country that has not reported yet files its first report within 28 days | No. The card on disk failed its gates, so the list uses the plain arrival formula instead. |
| Gradient-boosted tree | The same question, with three features | No. Training may record it. The server is hard-wired to ignore it. |
| Gravity regression | Passenger volume on a country pair that has no observed count | Yes. Those volumes feed the arrival rate used everywhere else. |

The three numbers on a country panel — already here, an infected traveller arrives, local spread takes off — are closed-form epidemiology, not a trained model. The 0–10 travel-risk index is a weighted average of those answers. The next-country model is deliberately left out of that index.

Training is offline. Nothing refits a model while the site is open. `just train-model` writes `data/processed/model_card.json`. A request only reads that file.

## What a request does today

`GET /api/v1/risk/next` ranks countries for the selected disease. The page calls it with a 28-day horizon and shows the top 20 under **Most likely to report next**.

The arrival rate for a destination that has not reported is

```
λ = Σ over origins that have reported  (prevalence × passengers per day × α × (1 − σ))
```

Prevalence comes from the same case logic as the country panel. Passengers are observed Eurostat or US DOT counts where those exist, and gravity-model estimates where they do not. `α` is the pathogen profile’s boarding factor unless the scenario controls override it. `σ` is the screening factor, 0 unless you set it.

The probability shown while the card is not validated is

```
P = 1 − exp(−λ × horizon)
```

That is a Poisson chance of at least one infected arrival. It is not the fitted hazard.

The map paints those countries only when `calibration_status` is `calibrated`. With the current card the map receives an empty forecast list. The panel still prints the uncalibrated percentages and the line “not validated — the number below is the uncalibrated scenario”.

`GET /api/v1/model/card` returns the card. A missing file, a status other than `calibrated`, or a card whose `panel_sha256` no longer matches `data/labels/panel.parquet` all count as not validated.

The hazard is applied only when all of these are true:

- the card status is `calibrated`
- the horizon is exactly 28 days
- the pathogen profile is `covid_19` or `mpox` (mapped to the training outbreaks `covid_2020` and `mpox_2022`)
- the fold that held that outbreak out stored `serve_b0`, `serve_b1`, and `serve_g`, with `serve_b1 ≥ 0`

Any other disease, including Ebola, measles, and influenza, stays on the uncalibrated formula even if a future card passes.

## The next-country hazard

This is the model `just train-model` is built to serve. It is a complementary log-log regression, fit by a grid search on the negative log-likelihood, then a short local search. It is not scikit-learn.

```
η = b0 + b1 × log(λ) + g × log10(destination population)
P = 1 − exp(−exp(η) × 28)
```

`exp(η)` is clipped to `exp(−40)` … `exp(40)` before that last step, so a wild coefficient cannot overflow.

### Parameters

| Symbol | Role | Constraint |
| --- | --- | --- |
| `b0` | Intercept. One value per training outbreak. At request time the server uses `serve_b0` from the fold that held the live outbreak out, which is the median intercept of the outbreaks that were trained on. With a single training outbreak that median is that outbreak’s intercept. | Searched, then refit per outbreak with the slopes held fixed. |
| `b1` | Slope on `log(λ)`. A larger arrival rate cannot lower the probability. | At least 0. The grid runs from 0 to 2. |
| `g` | Slope on `log10` of the destination’s population. | Grid from −1 to 1. Sign is free. |
| Horizon | Days in the survival formula. | Fixed at 28 for both fitting and the served model. |

The grid is 29 values of `b0` from −12 to 2, 9 values of `b1`, and 5 values of `g`. Eight rounds of ±0.25 steps follow, halving the step when a round finds nothing better.

The card’s top-level `b1` and `g` are whatever the last fold wrote. They are not what a request uses. A request uses that outbreak’s fold: `serve_b0`, `serve_b1`, `serve_g`.

### Features the hazard sees

Each training row is one destination in one forecast week, and only a destination that had not yet reported by that week.

| Column | Meaning in the training panel |
| --- | --- |
| `lambda` | Arrival rate. Sum over origins that had already reported of `prevalence × passengers per day × 0.5`. |
| `log_population` | `log10` of the destination population from `countries.parquet`. Missing populations are stored as `log10(1e7)` and flagged `population_imputed`. |
| `label` | 1 when that destination’s first report falls in the next 1 to 28 days. 0 otherwise, including countries that never appear in the label file. |
| `arrival_day` | Days from the forecast week to the first report. Empty when the country never reports. Used for one gate, not as a feature. |
| `inbound_passengers` | Sum of daily passengers from already-affected origins. Not an input to the hazard. Used by the simple baseline and by the tree. |

Training prevalence is fixed, and it is not the live scenario:

```
prevalence = (new cases in the latest already-published week / 7) × 7 × 4 / origin population
```

The 7 is the infectious period, the 4 is the under-reporting multiplier, and the 0.5 above is `α`. If a country has no weekly case row yet, incidence is treated as one new case per week. Screening `σ` is not in the training rate.

Passenger rows are the observed flows for a fixed year: 2019 for `covid_2020`, 2022 for `mpox_2022`. Modelled gravity flows are not the training passenger feature. The panel starts the week after the outbreak’s first label date and runs for 16 weeks.

Labels come from `just labels-build`:

- COVID-19 first-report dates from the Johns Hopkins CSSE confirmed time series, checked against Our World in Data.
- Mpox 2022 first-report dates from the Global.health line list, with the Our World in Data mpox file as the fallback.

Those files are first-report dates for training. They are separate from the WHO bulletins the live map counts as reports.

### How it is scored

Training is leave-one-outbreak-out. Fit on mpox, score every COVID country-week. Fit on COVID, score every mpox country-week. A row’s `latest_input_at` must not be after its `forecast_at`, and an outbreak must not sit on both sides of a fold. The card is `calibrated` only when both folds run and both pass every gate.

| Gate | Passes when | What it measures |
| --- | --- | --- |
| `brier_skill_vs_uncalibrated` | ≥ 0.10 | Brier skill against `1 − exp(−λ × 28)`, the formula the site uses when the card fails. |
| `brier_skill_vs_best_simple` | ≥ 0.03 | Brier skill against `1 − exp(−inbound passengers / 100000)`, a ranking by traffic alone. |
| `roc_auc` | ≥ 0.70 | Chance a randomly chosen positive country-week is scored above a randomly chosen negative one. |
| `calibration_slope` | 0.5 to 1.5 | Slope of logit(observed rate) against logit(mean prediction) across up to 10 quantile bins. 1 means the predicted probabilities match the observed rates. |
| `calibration_intercept` | absolute value ≤ 0.5 | That same line, read at a predicted probability of one half. |
| `top_20_recall` | ≥ 0.50 | Share of all positive country-weeks in the held-out panel that fall inside the 20 highest scores. This is one list for the whole panel, not a top 20 each week, so the bar is strict. |
| `arrival_order_spearman` | ≥ 0.50 | Among country-weeks that do report inside 28 days (at least 3 of them), rank correlation between a higher score and an earlier report. |
| `monotone_in_lambda` | `b1 ≥ 0` | The fit itself cannot rank a higher arrival rate as safer. |

Brier score is the mean squared error between the predicted probability and the 0/1 label. Lower is better. Skill is `1 − (model Brier / reference Brier)`. Positive skill means the model beats that reference. Negative skill means the reference was better.

There is also a helper that would reject a model whose AUC stays at 0.6 or above after the labels are shifted by 8 weeks. Training does not call it.

### What the current card found

`data/processed/model_card.json` and `data/snapshot/model_card.json` agree. `passed` is false and `status` is `not_validated`. A later `just train-model` replaces these numbers.

Held out COVID-19, trained on mpox. Served coefficients would have been `b0 = −8.5625`, `b1 = 0.0625`, `g = 0.625`. Brier 0.247.

| Gate | Value | Result |
| --- | ---: | --- |
| Skill vs uncalibrated arrival formula | 0.254 | pass |
| Skill vs traffic-only baseline | 0.227 | pass |
| ROC AUC | 0.811 | pass |
| Calibration slope | 1.197 | pass |
| Calibration intercept | 2.221 | fail |
| Top-20 recall | 0.014 | fail |
| Arrival-order Spearman | 0.140 | fail |
| Monotone in λ | yes | pass |

The COVID ranking is better than both baselines, and the probabilities are ordered in the right direction. They are far too high around one half (the intercept), and the single top-20 list almost never contains the country-weeks that actually reported next.

Held out mpox, trained on COVID-19. Served coefficients would have been `b0 = −10.59375`, `b1 = 0.015625`, `g = 1.03125`. Brier 0.221.

| Gate | Value | Result |
| --- | ---: | --- |
| Skill vs uncalibrated arrival formula | −1.185 | fail |
| Skill vs traffic-only baseline | −1.082 | fail |
| ROC AUC | 0.649 | fail |
| Calibration slope | 0.397 | fail |
| Calibration intercept | −1.920 | fail |
| Top-20 recall | 0.027 | fail |
| Arrival-order Spearman | 0.043 | fail |
| Monotone in λ | yes | pass |

A hazard learned on COVID-19 is worse than the plain arrival formula on mpox. That is why the card does not unlock the fitted coefficients, including for COVID-19. Both outbreaks have to pass.

The claim stored on the card is limited even if a future run passes: a held-out chance of a first report within 28 days for the outbreaks on the card, not a forecast for a new pathogen.

## The boosted tree

`scikit-learn` is a backend dependency. During `just train-model`, if `HistGradientBoostingClassifier` imports, the same leave-one-outbreak-out panel is fit with:

| Setting | Value |
| --- | --- |
| Features | `lambda`, `inbound_passengers`, `log_population` |
| Monotonic constraints | `[1, 1, 0]` — a higher arrival rate or more inbound passengers cannot decrease the score; population is free |
| `max_depth` | 2 |
| `max_iter` | 50 |
| `learning_rate` | 0.1 |
| `random_state` | 0 |

It is scored with the same gates. The current card has no `boosted` block, so that comparison did not run when this card was written.

If a later run passes every gate on both outbreaks, the card still sets `boosted_shipped` to false and keeps serving the hazard. The comment in the trainer says a single tree fit on every outbreak would have seen the held-out one, so the tree is a record, not the number on the page.

## The gravity model

This one does run, and it runs as part of building the passenger table (`just model-fit`), not inside `just train-model`.

It is ordinary least squares, via `numpy.linalg.lstsq`, on observed country-pair passenger counts:

```
log10(passengers per day) = b0
    + b1 × log10(origin population)
    + b2 × log10(destination population)
    + b3 × log10(distance in km)
    + b4 × log10(1 + direct OpenFlights routes)
    + b5 × log10(1 + airlines on those routes)
```

The fit needs at least 100 observed flows. The holdout is 20% of unordered country pairs, seed `20261024`, so a route and its reverse stay on the same side of the split. Exponentiating the prediction is a median. The stored flow is the mean, shifted by the log10 residual spread.

Held-out metrics, returned by `GET /api/v1/model/gravity`:

| Metric | Meaning |
| --- | --- |
| `r2_log` | Variance explained on the log10 passenger target. |
| `mae_log10` | Mean absolute error on that log10 scale. |
| `rmse_log10` | Root mean squared error on that scale. |
| `median_ratio_error` | Typical factor by which the prediction misses the observed count. |
| `within_factor_2`, `_5`, `_10` | Share of held-out pairs predicted within 2×, 5×, and 10× of the truth. |

The residual spread becomes a multiplicative uncertainty band on modelled routes, capped at 100×. Pairs with no OpenFlights route use a wider band (the residual scale times 1.5). The API labels those passenger numbers as modelled. They then enter `λ` for importation, establishment, and the next-country list.

## What the other screen numbers are

These are calculated on each risk request from the formulas in `backend/src/epiroute/epidemiology/`. They are not loaded from `model_card.json`.

| Screen number | Formula | Output |
| --- | --- | --- |
| Already here | A grounded case count for this country inside the lookback window. | Present or not, plus the report count. Flights are not an input. |
| Infected traveller arrives | `1 − exp(−λ × horizon)` for the selected country. Default horizon on this panel is 14 days. | A scenario probability and a low-to-high band from the under-reporting and parameter ranges. |
| Local spread takes off | Branching-process extinction probability from `R` and `k`, then `1 − exp(−λ × horizon × (1 − q))`. If `R ≤ 1`, establishment is 0. | A second scenario probability. Blank when the profile says this model cannot represent that pathogen. |
| Travel-risk index | Weighted mean of those answers, scaled to 0–10. | A scenario summary. The code and the page both say it is not a forecast. |

The next-country list is the only place the hazard would replace `1 − exp(−λ × 28)`. Until the card passes, that list is the same Poisson formula, summed over every destination that has not reported, and cut to 20 rows.
