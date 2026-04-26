from __future__ import annotations

from squeeze_bot.models import CatalystData, MarketSnapshot, Scores, SocialData, StructuralData
from squeeze_bot.utils import clamp, score_linear


def structural_pressure_score(data: StructuralData) -> float:
    def metric(value: float, low: float, high: float, neutral: float = 50.0) -> float:
        return neutral if value <= 0 else score_linear(value, low, high)

    short_interest = metric(data.short_interest_pct_float, 10, 40)
    float_score = 100 - score_linear(data.float_shares, 10_000_000, 100_000_000) if data.float_shares else 50.0
    days_to_cover = metric(data.days_to_cover, 2, 8)
    borrow_fee = metric(data.borrow_fee_pct, 5, 80)
    utilization = metric(data.borrow_utilization_pct, 50, 98)
    ftd = metric(data.fails_to_deliver_ratio, 0.5, 5)
    short_volume = metric(data.short_sale_volume_ratio, 35, 70)
    return clamp(
        short_interest * 0.30
        + float_score * 0.20
        + days_to_cover * 0.15
        + borrow_fee * 0.10
        + utilization * 0.10
        + ftd * 0.075
        + short_volume * 0.075
    )


def acceleration_score(snapshot: MarketSnapshot, catalyst: CatalystData, social: SocialData, previous_score: float | None = None) -> tuple[float, bool]:
    volume_growth = score_linear(snapshot.volume_growth_pct, 50, 500)
    price_velocity = score_linear(snapshot.price_velocity_pct, 1, 20)
    volatility = score_linear(snapshot.volatility_expansion_pct, 20, 250)
    news_growth = score_linear(catalyst.frequency_growth_pct, 50, 500)
    social_velocity = score_linear(social.mention_velocity_pct, 50, 800)
    score = clamp(volume_growth * 0.30 + price_velocity * 0.30 + volatility * 0.15 + news_growth * 0.15 + social_velocity * 0.10)
    return score, previous_score is None or score >= previous_score


def catalyst_strength_score(catalyst: CatalystData, claude_catalyst_quality: float = 0.0) -> float:
    frequency = score_linear(catalyst.frequency_growth_pct, 50, 500)
    headline_presence = clamp(catalyst.news_count_24h * 12.5)
    claude_score = clamp(claude_catalyst_quality * 100)
    if claude_score:
        return clamp(frequency * 0.25 + headline_presence * 0.25 + claude_score * 0.50)
    return clamp(frequency * 0.45 + headline_presence * 0.55)


def social_pressure_score(social: SocialData) -> float:
    mentions = score_linear(social.mention_velocity_pct, 50, 800)
    trends = score_linear(social.google_trends_change_pct, 25, 400)
    sentiment = score_linear(social.reddit_sentiment_shift, 0.1, 0.8)
    return clamp(mentions * 0.50 + trends * 0.35 + sentiment * 0.15)


def composite_score(structural: float, acceleration: float, catalyst: float, social: float) -> float:
    return clamp(structural * 0.40 + acceleration * 0.30 + catalyst * 0.20 + social * 0.10)


def build_scores(
    snapshot: MarketSnapshot,
    structural_data: StructuralData,
    catalyst_data: CatalystData,
    social_data: SocialData,
    claude_catalyst_quality: float = 0.0,
    previous_acceleration: float | None = None,
) -> Scores:
    structural = structural_pressure_score(structural_data)
    acceleration, rising = acceleration_score(snapshot, catalyst_data, social_data, previous_acceleration)
    catalyst = catalyst_strength_score(catalyst_data, claude_catalyst_quality)
    social = social_pressure_score(social_data)
    composite = composite_score(structural, acceleration, catalyst, social)
    return Scores(structural, acceleration, catalyst, social, composite, rising)
