from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

import requests

from squeeze_bot.config import Settings
from squeeze_bot.models import CatalystData, SocialData, StructuralData


class EnrichmentClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._google_trends_cache: dict[str, tuple[datetime, float]] = {}
        self.source_status: Counter[str] = Counter()
        self.source_errors: Counter[str] = Counter()

    def reset_status(self) -> None:
        self.source_status.clear()
        self.source_errors.clear()

    def status_summary(self) -> dict[str, dict[str, int]]:
        return {"status": dict(self.source_status), "errors": dict(self.source_errors)}

    def structural_data(self, symbol: str) -> StructuralData:
        data = StructuralData()
        if self.settings.fmp_api_key:
            data = self._fmp_structural(symbol, data)
        else:
            self._mark_source("fmp", "missing")
        return data

    def catalyst_data(self, symbol: str) -> CatalystData:
        headlines: list[str] = []
        if self.settings.finnhub_api_key:
            headlines.extend(self._finnhub_headlines(symbol))
        else:
            self._mark_source("finnhub", "missing")
        return CatalystData(news_count_24h=len(headlines), news_count_baseline=2.0, headlines=headlines[:12])

    def social_data(self, symbol: str) -> SocialData:
        reddit_mentions = self._reddit_mentions(symbol)
        trends_change = self._google_trends_change(symbol)
        return SocialData(
            reddit_mentions_1h=reddit_mentions,
            reddit_mentions_baseline=5.0,
            reddit_sentiment_shift=0.0,
            google_trends_change_pct=trends_change,
        )

    def _fmp_structural(self, symbol: str, data: StructuralData) -> StructuralData:
        try:
            profile = requests.get(
                f"https://financialmodelingprep.com/api/v3/profile/{symbol}",
                params={"apikey": self.settings.fmp_api_key},
                timeout=10,
            ).json()
        except requests.RequestException:
            self._mark_source("fmp", "error", "request_failed")
            return data
        if isinstance(profile, list) and profile:
            item = profile[0]
            data.float_shares = float(item.get("floatShares") or item.get("sharesOutstanding") or 0)
            self._mark_source("fmp", "ok")
        else:
            self._mark_source("fmp", "empty")
        return data

    def _finnhub_headlines(self, symbol: str) -> list[str]:
        today = datetime.now(UTC).date()
        yesterday = today - timedelta(days=1)
        try:
            response = requests.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": symbol, "from": yesterday.isoformat(), "to": today.isoformat(), "token": self.settings.finnhub_api_key},
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException:
            self._mark_source("finnhub", "error", "request_failed")
            return []
        items = response.json()
        if not isinstance(items, list):
            self._mark_source("finnhub", "empty")
            return []
        headlines = [str(item.get("headline", "")) for item in items if item.get("headline")]
        self._mark_source("finnhub", "ok" if headlines else "empty")
        return headlines

    def _reddit_mentions(self, symbol: str) -> int:
        if not (self.settings.reddit_client_id and self.settings.reddit_client_secret):
            self._mark_source("reddit", "missing")
            return 0
        try:
            import praw

            reddit = praw.Reddit(
                client_id=self.settings.reddit_client_id,
                client_secret=self.settings.reddit_client_secret,
                user_agent=self.settings.reddit_user_agent,
            )
            query = f"${symbol} OR {symbol}"
            subreddits = reddit.subreddit("wallstreetbets+shortsqueeze+stocks+pennystocks")
            mentions = sum(1 for _ in subreddits.search(query, sort="new", time_filter="hour", limit=100))
            self._mark_source("reddit", "ok" if mentions else "empty")
            return mentions
        except Exception:
            self._mark_source("reddit", "error", "request_failed")
            return 0

    def _google_trends_change(self, symbol: str) -> float:
        if not self.settings.enable_google_trends:
            self._mark_source("google_trends", "disabled")
            return 0.0

        now = datetime.now(UTC)
        cached = self._google_trends_cache.get(symbol)
        if cached:
            cached_at, cached_value = cached
            refresh_after = timedelta(minutes=max(1, self.settings.google_trends_refresh_minutes))
            if now - cached_at < refresh_after:
                self._mark_source("google_trends", "cached")
                return cached_value

        try:
            from pytrends.request import TrendReq

            trends = TrendReq(hl="en-US", tz=360)
            trends.build_payload([symbol], timeframe="now 1-d", geo="US")
            frame = trends.interest_over_time()
            if frame.empty or symbol not in frame:
                self._mark_source("google_trends", "empty")
                return 0.0
            values = frame[symbol].tail(12).tolist()
            if len(values) < 6:
                self._mark_source("google_trends", "empty")
                return 0.0
            baseline = sum(values[:6]) / 6
            recent = sum(values[6:]) / 6
            change = ((recent - baseline) / baseline * 100) if baseline else 0.0
            self._google_trends_cache[symbol] = (now, change)
            self._mark_source("google_trends", "ok")
            return change
        except Exception:
            self._mark_source("google_trends", "error", "request_failed")
            return 0.0

    def _mark_source(self, source: str, status: str, error: str = "") -> None:
        self.source_status[f"{source}_{status}"] += 1
        if error:
            self.source_errors[f"{source}_{error}"] += 1
