# How the risk numbers are calculated

EpiRoute does not publish one "probability of infection." A selected country gets three separate answers. Each one uses a different input, and a missing input stays blank. It is never filled in with zero.

The numbers are for situational awareness. They are not a forecast, not a diagnosis, and not a substitute for WHO or national travel advice.

## The three questions

1. **Is it already here?** Has a source report attributed cases to this country?
2. **Will an infected traveller arrive?** Within the chosen number of days, what is the chance that at least one infectious passenger lands here?
3. **Will local spread take off?** If infectious passengers do arrive, what is the chance that one of them starts a chain of transmission that does not die out?

Question 3 is smaller than question 2 whenever most chains die out. A high chance of an arrival does not mean a high chance of a local outbreak.

## What is taken from a source, and what is assumed

Case and death counts come from WHO Disease Outbreak News. A count is used only when that exact number appears in the retrieved page, inside the sentence the extractor quoted, next to words that match the field ("confirmed cases", "deaths"). A number the extractor invented, swapped, or copied from a vaccination or recovery figure is stored for audit and left out of the calculation.

Passenger volumes are published statistics where a statistical office reports them. Other routes are filled by a gravity model and labelled as estimates. Population comes from the reference country table.

These are assumptions, and the screen says so. They are not measurements from the outbreak page:

| Symbol | Meaning | Typical default |
| --- | --- | --- |
| D | Days a person stays infectious | From the pathogen profile (7 for a respiratory default, 9 for an Ebola-like illness) |
| u | Under-reporting multiplier | 2× / 4× / 10× (low / central / high) |
| α | Chance an infectious person boards, relative to anyone else | 0.5 respiratory, 0.02 Ebola-like |
| σ | Share of infectious travellers stopped by screening | 0 unless you set it, and never above 0.9 |
| R | Mean people infected by one case, at the destination | Profile range, for example 1.2–3.0 |
| k | How clustered transmission is. Small k means a few people cause most spread | Profile range, for example 0.1–0.5 |
| T | Horizon in days | Your choice |

The low-to-high band reruns the same formulas at the low and high ends of these inputs. It is a scenario range, not a statistical confidence interval.

## 1. How many people are infectious right now

WHO publishes a cumulative total, not the number of people who are infectious today. The model converts the total in one of two ways.

**Two reports for the same country and pathogen.** New cases divided by the days between the reports is the daily incidence. People infectious now are that incidence, times the infectious period, times under-reporting:

```
infectious people = (new cases / days between reports) × D × u
prevalence        = infectious people / population
```

A flat total, or a total that was revised downward, produces no prevalence. The outbreak may have stopped, and the model does not invent current cases from an old cumulative number.

**One report, and the page states when the outbreak was declared or began.** Cases are assumed to have accumulated evenly over that age A (in days):

```
infectious people = cumulative cases × min(1, D / A) × u
```

An outbreak younger than one infectious period has had no time for recoveries, so the fraction is 1. A single cumulative total with no start date is refused. Treating every historical case as still infectious would inflate the result by many times.

Reports older than 60 days are refused. The outbreak may be over.

**Worked example.** A country reports 100 cumulative cases, then 240 cases 14 days later. The infectious period is 7 days and under-reporting is 4×. The population is 10 million.

- New cases = 140, so 10 new reported cases per day.
- Infectious people = 10 × 7 × 4 = **280**.
- Prevalence = 280 / 10,000,000 = **2.8 per 100,000**.

The low and high ends of the same example use 2× and 10× instead of 4×, so 140 and 700 infectious people.

## 2. Chance that an infected traveller arrives

Arrivals are modelled as a steady Poisson process. For each origin country that has both a prevalence and a passenger flow to the destination:

```
daily rate from that origin = prevalence × passengers per day × α × (1 − σ)
```

The destination's rate λ is the sum over origins. The chance of at least one infectious arrival in T days is:

```
P(at least one arrival) = 1 − exp(−λ × T)
```

Zero rate or a zero horizon gives probability 0. A missing flow or a missing prevalence is omitted and listed. It is not treated as zero risk in silence.

**Same example, continued.** Prevalence 2.8 per 100,000, 2,000 passengers a day, α = 0.5, no screening, 14 days.

- λ = 0.000028 × 2,000 × 0.5 = **0.028 infectious arrivals per day**.
- λ × 14 = 0.392.
- P(at least one arrival) = 1 − exp(−0.392) = **about 32%**.

A published check of the same formula, with α = 0.5, no screening, and a 14-day horizon:

| Prevalence | Passengers per day | Chance of at least one arrival |
| --- | --- | --- |
| 10 per 100,000 | 50 | about 3% |
| 10 per 100,000 | 2,000 | about 75% |
| 1,000 per 100,000 | 50 | about 97% |

## 3. Chance that local spread takes off

Each arrival starts a branching process. The number of people one case infects follows a negative binomial distribution with mean R and dispersion k (Lloyd-Smith et al., Nature 2005). The probability q that the chain eventually dies out is the smallest solution of:

```
q = (1 + R × (1 − q) / k) ^ (−k)
```

One introduction starts sustained spread with probability 1 − q. Introductions that take off are a thinned Poisson process, so:

```
P(spread takes off within T days) = 1 − exp(−λ × T × (1 − q))
```

If R is 1 or below, extinction is certain and this probability is 0. That is a result, not a missing value.

Vector-borne diseases (Zika, dengue) and waterborne diseases (cholera) do not get an R. Whether they establish depends on mosquitoes or on water and sanitation, which this model does not represent, so establishment is reported as not estimable. Importation is still reported.

**Same example, continued.** R = 2.5 and k = 0.1, a COVID-like pattern where a few people cause most transmission. One introduction takes off about **14%** of the time (the solved value is 13.9%). With λ = 0.028 per day over 14 days:

```
P(spread takes off) = 1 − exp(−0.028 × 14 × 0.139) = about 5%
```

So this scenario is about a 32% chance that someone infectious arrives, and about a 5% chance that the arrival starts sustained local spread. Most introductions die out.

## What is deliberately left out

- The chance that a particular resident becomes infected. The model stops at "does a chain take off", not "how large does the epidemic get".
- Flight routes as evidence that disease is already present. Presence uses case reports only.
- Effective distance. That is a separate ranking of which origins are close in passenger flow, including journeys through a hub. It does not enter either probability.
- Any route with no passenger figure, and any origin with no usable case count. Those are listed as excluded.

## A short reading of the screen

- **Cases reported / No report on file** answers question 1.
- **Will an infected traveller arrive** is question 2. The value is modelled. The band is the scenario range.
- **Will sustained local transmission begin** is question 3, from the same arrival rate and the pathogen's R and k.
- **Not estimable** means an input was missing or the formula does not apply. It does not mean the risk is zero.
