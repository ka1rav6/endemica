"""Range and identity checks for the tables the model reads."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class ContractFailure:
    check: str
    detail: str


def check_flows(frame: pd.DataFrame) -> list[ContractFailure]:
    failures: list[ContractFailure] = []
    if frame.empty:
        return [ContractFailure("flows_present", "the passenger table is empty")]
    codes = pd.concat([frame["origin_iso3"], frame["dest_iso3"]])
    bad_codes = codes[codes.astype(str).str.len() != 3]
    if not bad_codes.empty:
        failures.append(ContractFailure("iso3", f"{len(bad_codes)} codes are not 3 letters"))
    self_pairs = frame[frame["origin_iso3"] == frame["dest_iso3"]]
    if not self_pairs.empty:
        failures.append(
            ContractFailure("no_self_pairs", f"{len(self_pairs)} rows fly to themselves")
        )
    passengers = frame["passengers_per_day"]
    if (passengers < 0).any():
        failures.append(ContractFailure("passenger_range", "a flow is negative"))
    if "value_type" in frame.columns:
        observed = frame[frame["value_type"] == "observed"]["passengers_per_day"]
        estimated = frame[frame["value_type"] != "observed"]["passengers_per_day"]
        if (observed > 250_000).any() or (estimated > 1_000_000).any():
            failures.append(
                ContractFailure(
                    "passenger_range",
                    "an observed or estimated flow is implausibly large",
                )
            )
    return failures


def check_populations(frame: pd.DataFrame) -> list[ContractFailure]:
    if "population" not in frame.columns:
        return [ContractFailure("population_column", "countries table has no population")]
    population = frame["population"].dropna()
    if (population < 100).any() or (population > 2.0e9).any():
        return [ContractFailure("population_range", "a population is outside 100 to 2 billion")]
    return []


def check_label_agreement(rate: float | None) -> list[ContractFailure]:
    if rate is None:
        return [ContractFailure("label_agreement", "no second source was available to check dates")]
    if rate < 0.90:
        return [
            ContractFailure(
                "label_agreement",
                f"only {rate:.0%} of first-case dates agree within 7 days",
            )
        ]
    return []
