"""Project contract (PRD 8 project.json, P01~P04)."""
from __future__ import annotations

import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

BRAND_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{0,4}$")

ReportProfile = Literal["diagnostic", "proposal"]
# P0 UI must not expose unimplemented profiles (PRD 3).
IMPLEMENTED_PROFILES: tuple[str, ...] = ("diagnostic",)


class Period(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> "Period":
        if self.start > self.end:
            raise ValueError("period.start가 period.end보다 늦습니다")
        return self

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


class Target(BaseModel):
    age_min: Optional[int] = Field(default=None, ge=0, le=120)
    age_max: Optional[int] = Field(default=None, ge=0, le=120)
    gender: Literal["all", "female", "male"] = "all"
    label: str

    @model_validator(mode="after")
    def _range(self) -> "Target":
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("target.age_min이 age_max보다 큽니다")
        return self


class KeywordGroup(BaseModel):
    entity: str
    keywords: list[str] = Field(min_length=1)


class OfficialProfile(BaseModel):
    channel: str
    url: str


class Brand(BaseModel):
    id: str
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    target: Optional[Target] = None
    competitors: list[str] = Field(min_length=1, max_length=4)
    keyword_groups: list[KeywordGroup] = Field(default_factory=list)
    official_profiles: list[OfficialProfile] = Field(default_factory=list)
    # Benchmarks are manual case references only; never in share denominators (PRD 3).
    benchmarks: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not BRAND_ID_RE.match(v):
            raise ValueError("brand id는 ^[A-Z][A-Z0-9]{0,4}$ 형식이어야 합니다")
        return v

    @property
    def entity_set(self) -> list[str]:
        """Competition set used for shares: self + competitors, in configured order."""
        return [self.name, *self.competitors]


class SectionWindow(BaseModel):
    section_id: str
    label: str
    start: date
    end: date
    source: Literal["user", "import_default"] = "user"

    @model_validator(mode="after")
    def _ordered(self) -> "SectionWindow":
        if self.start > self.end:
            raise ValueError(f"{self.section_id} 기간의 시작일이 종료일보다 늦습니다")
        return self


class ScopeSetting(BaseModel):
    """Override for one research-scope item (팩트북 표준 목차 §3.5). Unset fields use the catalog default."""
    item_id: str
    enabled: bool = True
    period: Literal["inherit", "months", "custom"] = "inherit"
    months: Optional[int] = Field(default=None, ge=1, le=60)
    start: Optional[date] = None
    end: Optional[date] = None
    channels: Optional[list[str]] = None
    targets: Optional[list[str]] = None  # competitor/benchmark items: which of them to look at
    max_items: Optional[int] = Field(default=None, ge=1, le=30)
    focus: Optional[str] = Field(default=None, max_length=300)  # what to look at first, written by the AI on request
    keywords: list[str] = Field(default_factory=list, max_length=5)  # extra search words that go with `focus`

    @model_validator(mode="after")
    def _period(self) -> "ScopeSetting":
        if self.period == "months" and self.months is None:
            raise ValueError(f"{self.item_id}: 최근 몇 개월인지 입력하세요")
        if self.period == "custom":
            if self.start is None or self.end is None:
                raise ValueError(f"{self.item_id}: 시작일과 종료일을 모두 입력하세요")
            if self.start > self.end:
                raise ValueError(f"{self.item_id} 기간의 시작일이 종료일보다 늦습니다")
        return self


class BudgetPolicy(BaseModel):
    mode: Literal["offline", "live"] = "offline"
    external_calls_enabled: bool = False
    run_budget_usd: Optional[str] = None


class Project(BaseModel):
    name: str = Field(min_length=1)
    client: str = Field(min_length=1)
    timezone: str = "Asia/Seoul"
    period: Period
    brands: list[Brand] = Field(min_length=1, max_length=3)
    enabled_slides: list[str]
    template_version: str = "1.0"
    budget_policy: BudgetPolicy = Field(default_factory=BudgetPolicy)
    report_profile: ReportProfile = "diagnostic"
    collection_cutoff: Optional[date] = None
    section_windows: list[SectionWindow] = Field(default_factory=list)
    scope: list[ScopeSetting] = Field(default_factory=list)
    target_hypothesis: Optional[str] = None
    # Which fields were filled by explicit legacy-import defaults (PRD 8 project.json).
    import_defaults_applied: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cross_checks(self) -> "Project":
        ids = [b.id for b in self.brands]
        if len(ids) != len(set(ids)):
            raise ValueError("brand id가 중복됩니다")
        self_names = {b.name for b in self.brands}
        for b in self.brands:
            # P02: another self brand cannot be registered as this brand's competitor.
            clash = self_names.intersection(b.competitors) - {b.name}
            if clash:
                raise ValueError(f"{b.name}: 다른 자사 브랜드({', '.join(sorted(clash))})를 경쟁사로 등록할 수 없습니다")
            if b.name in b.competitors:
                raise ValueError(f"{b.name}: 자기 자신을 경쟁사로 등록할 수 없습니다")
            if len(set(b.competitors)) != len(b.competitors):
                raise ValueError(f"{b.name}: 경쟁사가 중복됩니다")
            overlap = set(b.benchmarks).intersection(b.entity_set)
            if overlap:
                raise ValueError(f"{b.name}: 벤치마크는 경쟁 세트와 겹칠 수 없습니다 ({', '.join(sorted(overlap))})")
            # P02: another self brand cannot be registered as this brand's benchmark either.
            bench_clash = self_names.intersection(b.benchmarks) - {b.name}
            if bench_clash:
                raise ValueError(f"{b.name}: 다른 자사 브랜드({', '.join(sorted(bench_clash))})를 벤치마크로 등록할 수 없습니다")
            _check_keywords(b)
        if self.report_profile not in IMPLEMENTED_PROFILES:
            raise ValueError("proposal 프로필은 P1입니다. 현재는 diagnostic만 지원합니다")
        return self

    def brand(self, brand_id: str) -> Brand:
        for b in self.brands:
            if b.id == brand_id:
                return b
        raise KeyError(brand_id)

    def window_for(self, section_id: str) -> Optional[SectionWindow]:
        for w in self.section_windows:
            if w.section_id == section_id:
                return w
        return None


def _check_keywords(brand: Brand) -> None:
    """Block alias collisions and the same keyword appearing in several entity groups."""
    owner: dict[str, str] = {}
    names = {brand.name: brand.name, **{a: brand.name for a in brand.aliases}}
    for kw_name, ent in names.items():
        owner[kw_name.replace(" ", "").lower()] = ent
    for comp in brand.competitors:
        key = comp.replace(" ", "").lower()
        if key in owner and owner[key] != comp:
            raise ValueError(f"{brand.name}: 별칭 '{comp}'이 다른 브랜드와 충돌합니다")
    seen: dict[str, str] = {}
    for group in brand.keyword_groups:
        if group.entity not in brand.entity_set:
            raise ValueError(f"{brand.name}: 검색어 그룹 '{group.entity}'은 경쟁 세트에 없습니다")
        for kw in group.keywords:
            key = kw.replace(" ", "").lower()
            if key in seen and seen[key] != group.entity:
                raise ValueError(f"{brand.name}: 검색어 '{kw}'가 {seen[key]}·{group.entity} 그룹에 중복됩니다")
            seen[key] = group.entity


def load_project(data: dict) -> Project:
    """Load project.json; legacy quantitative fixtures get explicit import defaults.

    PRD 8: legacy fixtures get report_profile=diagnostic and their existing period as
    explicit import defaults. This does NOT create 3-month / 3-year windows for other
    sections.
    """
    data = dict(data)
    applied: list[str] = []
    if "report_profile" not in data:
        data["report_profile"] = "diagnostic"
        applied.append("report_profile")
    if "section_windows" not in data and isinstance(data.get("period"), dict):
        period = data["period"]
        windows = []
        slides = set(data.get("enabled_slides", []))
        if slides & {"2-8a", "2-8b", "2-8c", "2-8d"}:
            windows.append({"section_id": "search", "label": "9M", "start": period["start"],
                            "end": period["end"], "source": "import_default"})
        if "3-1" in slides:
            windows.append({"section_id": "influencer", "label": "기간", "start": period["start"],
                            "end": period["end"], "source": "import_default"})
        data["section_windows"] = windows
        applied.append("section_windows")
    data["import_defaults_applied"] = applied + list(data.get("import_defaults_applied", []))
    return Project.model_validate(data)
