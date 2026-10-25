from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "disease": {"type": "string"},
        "report_date": {"type": "string"},
        "locations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "country": {"type": "string"},
                    "subnational": {"type": "string"},
                    "cases_confirmed": {"type": "integer"},
                    "cases_probable": {"type": "integer"},
                    "cases_suspected": {"type": "integer"},
                    "deaths": {"type": "integer"},
                    "period": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["country", "evidence"],
            },
        },
    },
    "required": ["disease", "locations"],
}


class ExtractedLocation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    country: str
    subnational: str | None = None
    cases_confirmed: int | None = None
    cases_probable: int | None = None
    cases_suspected: int | None = None
    deaths: int | None = None
    period: str | None = None
    evidence: str | None = None

    def numeric_fields(self) -> dict[str, int | None]:
        return {
            "cases_confirmed": self.cases_confirmed,
            "cases_probable": self.cases_probable,
            "cases_suspected": self.cases_suspected,
            "deaths": self.deaths,
        }


class ExtractedReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    disease: str | None = None
    report_date: str | None = None
    locations: list[ExtractedLocation] = Field(default_factory=list)


class FetchedPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    final_url: str | None = None
    title: str | None = None
    description: str | None = None
    language: str | None = None
    text: str = ""
    author: str | None = None
    published_date: str | None = None


class FetchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[FetchedPage] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class AgentRunStarted(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str | None = None
    error: str | None = None


class AgentRunStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    status: str
    num_of_steps: int | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status.upper() in {"COMPLETED", "FAILED", "CANCELLED"}

    @property
    def succeeded(self) -> bool:
        return self.status.upper() == "COMPLETED" and self.result is not None


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    url: str
    snippet: str | None = None
    site_name: str | None = None
    date: str | None = None
    position: int | None = None


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str | None = None
    results: list[SearchResult] = Field(default_factory=list)
