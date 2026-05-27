"""Pydantic models for the User Stats response payload.

These validate BOTH:
1. Raw output from core.profile_stats_v1 RPC (PURE-OLTP — no quota fields).
2. The Python-route-composed response that adds quota_snapshot fields on
   top of the raw payload.

Quota / Plan fields are typed as Optional with None defaults so the same
model passes for both states. The route layer fills them in via
billing.pricing_get_quota_snapshot before returning to the client.

Design rationale: see PR #118 deviation comment + 3 research subagent
reports synthesized 2026-05-27 (Stripe Entitlements + Auth0/Azure BFF +
CYBERTEC SECURITY DEFINER scope guidance).
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    """Common config: forbid unexpected fields so PURE-OLTP contract holds."""
    model_config = ConfigDict(extra="forbid")


# ─── meta ─────────────────────────────────────────────────────────────


class MetaSection(_Strict):
    workspace_id: str
    computed_at: datetime
    schema_version: int = 1


# ─── main_board ───────────────────────────────────────────────────────


class HeatmapCell(_Strict):
    date: date
    count: int


class ZettelCounters(_Strict):
    lifetime_count: int
    this_month_count: int


class KastenCounters(_Strict):
    lifetime_count: int


class QuotaSnapshot(_Strict):
    """Route-composed quota for a meter (zettel | kasten | rag_question).

    Mirrors the billing.pricing_get_quota_snapshot RPC return shape.
    `used` is the current period usage, `available` is the remaining count,
    `period` is one of {day, week, month, lifetime}.
    """
    used: int
    available: int | None  # None = unlimited
    period: str


class MainBoardSection(_Strict):
    heatmap: list[HeatmapCell] = Field(default_factory=list)
    zettels: ZettelCounters
    kastens: KastenCounters
    # Route-composed quota (None when validating raw RPC payload):
    zettels_quota: QuotaSnapshot | None = None
    kastens_quota: QuotaSnapshot | None = None


# ─── general ──────────────────────────────────────────────────────────


class MemberSince(_Strict):
    joined_at: datetime | None
    days_in_vault: int


class SparkPoint(_Strict):
    week: date
    count: int


class Zettels30d(_Strict):
    count: int
    prev_30d_count: int
    delta_pct: float | None
    sparkline_weekly: list[SparkPoint] = Field(default_factory=list)


class KgSize(_Strict):
    nodes: int
    edges: int


class SourceDiversity(_Strict):
    distinct_sources: int
    max_sources: int


class Plan(_Strict):
    """Route-composed plan tier + period end (from billing subscription)."""
    tier: str
    period_end: datetime | None = None


class GeneralSection(_Strict):
    member_since: MemberSince
    zettels_30d: Zettels30d
    kg_size: KgSize
    source_diversity: SourceDiversity
    # Route-composed (None when validating raw RPC payload):
    plan: Plan | None = None


# ─── zettel ───────────────────────────────────────────────────────────


class TopSource(_Strict):
    source_type: str | None
    count: int
    pct: float | None


class LatestZettel(_Strict):
    title: str | None
    source_type: str | None
    created_at: datetime | None


class SummaryChars(_Strict):
    mean: int
    min: int
    max: int


class ZettelSection(_Strict):
    top_source: TopSource
    latest: LatestZettel
    avg_summary_chars: SummaryChars
    avg_user_tags: float
    tagged_coverage_pct: float


# ─── kasten ───────────────────────────────────────────────────────────


class LargestKasten(_Strict):
    name: str | None
    icon: str | None
    color: str | None
    zettel_count: int
    last_added_at: datetime | None
    age_days: int | None


class MostCitedSource(_Strict):
    source_type: str | None
    count: int


class QuestionStreak(_Strict):
    current: int
    longest: int


class KastenSection(_Strict):
    largest: LargestKasten
    avg_conversation_depth: float
    most_cited_source_type: MostCitedSource
    question_streak: QuestionStreak


# ─── domain ───────────────────────────────────────────────────────────


class TagDelta(_Strict):
    tag: str
    delta_share: float


class DomainSection(_Strict):
    concentration_hhi: float
    emerging_top5: list[TagDelta] = Field(default_factory=list)
    declining_top5: list[TagDelta] = Field(default_factory=list)


# ─── activity ─────────────────────────────────────────────────────────


class WeekOverWeek(_Strict):
    this_week: int
    last_week: int
    delta_pct: float | None


class ChatVsCapture(_Strict):
    captures_30d: int
    chats_30d: int
    capture_pct: float | None


class ActivitySection(_Strict):
    current_streak: int
    longest_streak: int
    week_over_week: WeekOverWeek
    chat_vs_capture: ChatVsCapture


# ─── graph ────────────────────────────────────────────────────────────


class HubNode(_Strict):
    name: str
    type: str
    degree: int


class TagCoverage(_Strict):
    user_tag_count: int
    kg_node_count: int


class RelationMix(_Strict):
    relation: str
    count: int


class GraphSection(_Strict):
    mean_degree: float
    top_hubs_10: list[HubNode] = Field(default_factory=list)
    personal_vs_global_tags: TagCoverage
    relation_type_mix: list[RelationMix] = Field(default_factory=list)


# ─── top-level ────────────────────────────────────────────────────────


class StatsResponse(_Strict):
    """Full user-stats response payload.

    Validates raw core.profile_stats_v1 output (quota/plan fields None)
    AND the route-composed final response (quota/plan populated).
    """
    meta: MetaSection
    main_board: MainBoardSection
    general: GeneralSection
    zettel: ZettelSection
    kasten: KastenSection
    domain: DomainSection
    activity: ActivitySection
    graph: GraphSection
