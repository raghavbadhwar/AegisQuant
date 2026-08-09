"""Cutoff-safe deterministic behavioural and relationship-graph features."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from aegis.contracts import BehavioralFeatures, GraphFeatures, canonical_sha256

from .hashing import build_hashed


@dataclass(frozen=True, slots=True)
class BehavioralObservation:
    """A sourced behavioural measurement for one ticker and time bucket."""

    ticker: str
    observed_at: datetime
    available_at: datetime
    source_id: str
    mentions: float
    sentiment: float
    volume: float
    price_return: float
    narrative: str

    def __post_init__(self) -> None:
        if not self.ticker.strip() or not self.source_id.strip() or not self.narrative.strip():
            raise ValueError("behavioural ticker, source_id, and narrative must not be empty")
        if self.observed_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("behavioural timestamps must be timezone-aware")
        if self.observed_at > self.available_at:
            raise ValueError("a behavioural observation cannot be available before it is observed")
        if not all(
            math.isfinite(item)
            for item in (self.mentions, self.sentiment, self.volume, self.price_return)
        ):
            raise ValueError("behavioural numeric inputs must be finite")
        if self.mentions < 0.0 or self.volume < 0.0:
            raise ValueError("behavioural mentions and volume must be non-negative")


GraphRelation = Literal[
    "supplier",
    "customer",
    "management",
    "ownership",
    "litigation_regulatory",
    "narrative",
    "common_exposure",
]
_GRAPH_RELATIONS = frozenset(
    {
        "supplier",
        "customer",
        "management",
        "ownership",
        "litigation_regulatory",
        "narrative",
        "common_exposure",
    }
)


@dataclass(frozen=True, slots=True)
class GraphEdgeObservation:
    """A weighted, sourced relationship edge known at ``available_at``."""

    source_ticker: str
    target_ticker: str
    relation: GraphRelation
    weight: float
    observed_at: datetime
    available_at: datetime
    source_id: str
    cluster: str | None = None

    def __post_init__(self) -> None:
        if not self.source_ticker.strip() or not self.target_ticker.strip():
            raise ValueError("graph edge tickers must not be empty")
        if self.source_ticker.upper() == self.target_ticker.upper():
            raise ValueError("graph self-edges are not valid relationship observations")
        if self.relation not in _GRAPH_RELATIONS:
            raise ValueError("unknown graph relationship type")
        if not math.isfinite(self.weight) or self.weight < 0.0:
            raise ValueError("graph edge weight must be finite and non-negative")
        if self.observed_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("graph timestamps must be timezone-aware")
        if self.observed_at > self.available_at:
            raise ValueError("a graph edge cannot be available before it is observed")
        if not self.source_id.strip():
            raise ValueError("graph edge source_id must not be empty")
        if self.cluster is not None and not self.cluster.strip():
            raise ValueError("graph edge cluster cannot be blank")


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}-{canonical_sha256(payload)[:20]}-v1"


def _validate_as_of(as_of: datetime) -> None:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _population_sd(values: Sequence[float]) -> float:
    center = _mean(values)
    return math.sqrt(_mean([(item - center) ** 2 for item in values]))


def _standardized_latest(values: Sequence[float]) -> float:
    if len(values) == 1:
        return 0.0
    baseline = values[:-1]
    center = _mean(baseline)
    scale = _population_sd(baseline)
    difference = values[-1] - center
    return difference / scale if scale > 1e-15 else difference


def _relative_latest(values: Sequence[float]) -> float:
    if len(values) == 1:
        return 0.0
    baseline = _mean(values[:-1])
    difference = values[-1] - baseline
    return difference / baseline if abs(baseline) > 1e-15 else difference


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) < 2 or len(left) != len(right):
        return 0.0
    left_mean = _mean(left)
    right_mean = _mean(right)
    numerator = math.fsum(
        (left_item - left_mean) * (right_item - right_mean)
        for left_item, right_item in zip(left, right, strict=True)
    )
    denominator = math.sqrt(
        math.fsum((item - left_mean) ** 2 for item in left)
        * math.fsum((item - right_mean) ** 2 for item in right)
    )
    return numerator / denominator if denominator > 1e-15 else 0.0


def calculate_behavioral_features(
    ticker: str,
    observations: Sequence[BehavioralObservation],
    *,
    as_of: datetime,
    calculator_id: str = "deterministic-behavioral-calculator-v1",
) -> BehavioralFeatures:
    """Calculate every behavioural contract field from cutoff-safe observations only."""
    _validate_as_of(as_of)
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("ticker must not be empty")
    selected = sorted(
        (
            item
            for item in observations
            if item.ticker.strip().upper() == symbol and item.available_at <= as_of
        ),
        key=lambda item: (item.observed_at, item.available_at, item.source_id, item.narrative),
    )
    if not selected:
        raise ValueError("behavioural features require cutoff-safe observations for the ticker")
    identities = [(item.observed_at, item.source_id, item.narrative) for item in selected]
    if len(set(identities)) != len(identities):
        raise ValueError(
            "behavioural observations must have unique time/source/narrative identities"
        )

    mentions = [item.mentions for item in selected]
    volumes = [item.volume for item in selected]
    sentiments = [item.sentiment for item in selected]
    price_returns = [item.price_return for item in selected]
    if len(mentions) >= 3:
        mention_acceleration = mentions[-1] - 2.0 * mentions[-2] + mentions[-3]
    elif len(mentions) == 2:
        mention_acceleration = mentions[-1] - mentions[-2]
    else:
        mention_acceleration = 0.0

    narrative_weights: dict[str, float] = defaultdict(float)
    for item in selected:
        narrative_weights[item.narrative] += item.mentions
    total_narrative_weight = math.fsum(narrative_weights.values())
    if total_narrative_weight > 0.0:
        narrative_saturation = max(narrative_weights.values()) / total_narrative_weight
    else:
        counts = Counter(item.narrative for item in selected)
        narrative_saturation = max(counts.values()) / len(selected)

    source_ids = tuple(sorted({item.source_id for item in selected}))
    safe_payload = {
        "ticker": symbol,
        "as_of": as_of,
        "calculator_id": calculator_id,
        "observations": [asdict(item) for item in selected],
    }
    return build_hashed(
        BehavioralFeatures,
        feature_id=_stable_id("behavioral-features", safe_payload),
        ticker=symbol,
        as_of=as_of,
        available_at=max(item.available_at for item in selected),
        attention_shock=_standardized_latest(mentions),
        mention_acceleration=mention_acceleration,
        sentiment_dispersion=_population_sd(sentiments),
        source_diversity=len(source_ids) / len(selected),
        narrative_saturation=narrative_saturation,
        abnormal_volume=_relative_latest(volumes),
        price_attention_reflexivity=_correlation(mentions, price_returns),
        source_ids=source_ids,
        calculator_id=calculator_id,
    )


def _concentration(edges: Sequence[GraphEdgeObservation]) -> float:
    total = math.fsum(edge.weight for edge in edges)
    if total <= 0.0:
        return 0.0
    by_counterparty: dict[str, float] = defaultdict(float)
    for edge in edges:
        by_counterparty[edge.target_ticker.upper()] += edge.weight
    return math.fsum((weight / total) ** 2 for weight in by_counterparty.values())


def calculate_graph_features(
    ticker: str,
    edges: Sequence[GraphEdgeObservation],
    *,
    as_of: datetime,
    graph_snapshot_id: str,
    calculator_id: str = "deterministic-graph-calculator-v1",
) -> GraphFeatures:
    """Calculate relationship risk features from the supplied cutoff-safe graph snapshot."""
    _validate_as_of(as_of)
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("ticker must not be empty")
    selected = sorted(
        (
            edge
            for edge in edges
            if edge.available_at <= as_of
            and (edge.source_ticker.upper() == symbol or edge.target_ticker.upper() == symbol)
        ),
        key=lambda edge: (
            edge.relation,
            edge.source_ticker.upper(),
            edge.target_ticker.upper(),
            edge.observed_at,
            edge.source_id,
        ),
    )
    if not selected:
        raise ValueError("graph features require cutoff-safe incident edges")
    identities = [
        (
            edge.source_ticker.upper(),
            edge.target_ticker.upper(),
            edge.relation,
            edge.observed_at,
            edge.source_id,
        )
        for edge in selected
    ]
    if len(set(identities)) != len(identities):
        raise ValueError("graph edges must have unique endpoint/relation/time/source identities")

    # Orient incident edges away from the subject so concentration always groups the counterparty.
    oriented = [
        GraphEdgeObservation(
            source_ticker=symbol,
            target_ticker=(
                edge.target_ticker if edge.source_ticker.upper() == symbol else edge.source_ticker
            ),
            relation=edge.relation,
            weight=edge.weight,
            observed_at=edge.observed_at,
            available_at=edge.available_at,
            source_id=edge.source_id,
            cluster=edge.cluster,
        )
        for edge in selected
    ]
    by_relation: dict[str, list[GraphEdgeObservation]] = defaultdict(list)
    for edge in oriented:
        by_relation[edge.relation].append(edge)

    cluster_weights: dict[str, float] = defaultdict(float)
    for edge in by_relation["common_exposure"]:
        cluster = edge.cluster or edge.target_ticker.upper()
        cluster_weights[cluster] += edge.weight
    common_cluster = (
        sorted(cluster_weights.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if cluster_weights
        else None
    )
    safe_payload = {
        "ticker": symbol,
        "as_of": as_of,
        "graph_snapshot_id": graph_snapshot_id,
        "calculator_id": calculator_id,
        "edges": [asdict(edge) for edge in selected],
    }
    return build_hashed(
        GraphFeatures,
        feature_id=_stable_id("graph-features", safe_payload),
        ticker=symbol,
        as_of=as_of,
        available_at=max(edge.available_at for edge in selected),
        supplier_concentration=_concentration(by_relation["supplier"]),
        customer_concentration=_concentration(by_relation["customer"]),
        director_executive_overlap=math.fsum(edge.weight for edge in by_relation["management"]),
        ownership_centrality=math.fsum(edge.weight for edge in by_relation["ownership"]),
        litigation_regulatory_exposure=math.fsum(
            edge.weight for edge in by_relation["litigation_regulatory"]
        ),
        narrative_propagation=math.fsum(edge.weight for edge in by_relation["narrative"]),
        common_exposure_cluster=common_cluster,
        graph_snapshot_id=graph_snapshot_id,
        calculator_id=calculator_id,
    )
