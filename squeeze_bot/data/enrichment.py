from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TypeVar

import requests

from squeeze_bot.config import Settings
from squeeze_bot.models import CatalystData, SocialData, StructuralData

T = TypeVar("T")


class EnrichmentClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = requests.Session()
        self._reddit = None
        self._structural_cache: dict[str, tuple[datetime, StructuralData]] = {}
        self._catalyst_cache: dict[str, tuple[datetime, CatalystData]] = {}
        self._social_cache: dict[str, tuple[datetime, SocialData]] = {}
        self._reddit_cache: dict[str, tuple[datetime, int]] = {}
        self._google_trends_cache: dict[str, tuple[datetime, float]] = {}
        self.source_status: Counter[str] = Counter()
        self.source_errors: Counter[str] = Counter()

    def reset_status(self) -> None:
        self.source_status.clear()
        self.source_errors.clear()

    def status_summary(self) -> dict[str, dict[str, int]]:
        return {"status": dict(self.source_status), "errors": dict(self.source_errors)}

    def structural_data(self, symbol: str) -> StructuralData:
        symbol = symbol.upper()
        cached = self._cache_get(self._structural_cache, symbol, self.settings.enrichment_cache_minutes)
        if cached is not None:
            self._mark_source("fmp", "cached")
            return cached
        data = StructuralData()
        if self.settings.fmp_api_key:
            data = self._fmp_structural(symbol, data)
        else:
            self._mark_source("fmp", "missing")
        self._cache_set(self._structural_cache, symbol, data)
        return data

    def catalyst_data(self, symbol: str) -> CatalystData:
        symbol = symbol.upper()
        cached = self._cache_get(self._catalyst_cache, symbol, self.settings.enrichment_cache_minutes)
        if cached is not None:
            self._mark_source("finnhub", "cached")
            return cached
        headlines: list[str] = []
        if self.settings.finnhub_api_key:
            headlines.extend(self._finnhub_headlines(symbol))
        else:
            self._mark_source("finnhub", "missing")
        data = CatalystData(news_count_24h=len(headlines), news_count_baseline=2.0, headlines=headlines[:12])
        self._cache_set(self._catalyst_cache, symbol, data)
        return data

    def social_data(self, symbol: str) -> SocialData:
        symbol = symbol.upper()
        cached = self._cache_get(self._social_cache, symbol, self.settings.enrichment_cache_minutes)
        if cached is not None:
            self._mark_source("social", "cached")
            return cached
        reddit_mentions = self._reddit_mentions(symbol)
        trends_change = self._google_trends_change(symbol)
        data = SocialData(
            reddit_mentions_1h=reddit_mentions,
            reddit_mentions_baseline=5.0,
            reddit_sentiment_shift=0.0,
            google_trends_change_pct=trends_change,
        )
        self._cache_set(self._social_cache, symbol, data)
        return data

    def _fmp_structural(self, symbol: str, data: StructuralData) -> StructuralData:
        profile_failed = False
        try:
            profile_response = self.http.get(
                f"https://financialmodelingprep.com/api/v3/profile/{symbol}",
                params={"apikey": self.settings.fmp_api_key},
                timeout=10,
            )
            profile_response.raise_for_status()
            profile = profile_response.json()
        except requests.RequestException as exc:
            self._mark_source("fmp", "error", self._request_error_key(exc))
            profile = []
            profile_failed = True
        if isinstance(profile, list) and profile:
            item = profile[0]
            data.float_shares = float(item.get("floatShares") or item.get("sharesOutstanding") or 0)
        data = self._fmp_float(symbol, data)
        if data.float_shares or data.short_interest_pct_float or data.days_to_cover:
            self._mark_source("fmp", "ok")
        elif profile_failed:
            self._mark_source("fmp", "unavailable")
        else:
            self._mark_source("fmp", "empty")
        return data

    def _fmp_float(self, symbol: str, data: StructuralData) -> StructuralData:
        try:
            response = self.http.get(
                "https://financialmodelingprep.com/api/v4/shares_float",
                params={"symbol": symbol, "apikey": self.settings.fmp_api_key},
                timeout=10,
            )
            response.raise_for_status()
            rows = response.json()
        except requests.RequestException as exc:
            self._mark_source("fmp_float", "error", self._request_error_key(exc))
            return data
        if isinstance(rows, list) and rows:
            item = rows[0]
        elif isinstance(rows, dict):
            item = rows
        else:
            return data
        data.float_shares = float(item.get("floatShares") or item.get("freeFloat") or data.float_shares or 0)
        return data

    def _finnhub_headlines(self, symbol: str) -> list[str]:
        today = datetime.now(UTC).date()
        yesterday = today - timedelta(days=1)
        try:
            response = self.http.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": symbol, "from": yesterday.isoformat(), "to": today.isoformat(), "token": self.settings.finnhub_api_key},
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            self._mark_source("finnhub", "error", self._request_error_key(exc))
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
        cached = self._cache_get(self._reddit_cache, symbol, self.settings.reddit_cache_minutes)
        if cached is not None:
            self._mark_source("reddit", "cached")
            return cached
        try:
            reddit = self._reddit_client()
            query = f"${symbol} OR {symbol}"
            subreddits = reddit.subreddit("wallstreetbets+shortsqueeze+stocks+pennystocks")
            mentions = sum(1 for _ in subreddits.search(query, sort="new", time_filter="hour", limit=100))
            self._mark_source("reddit", "ok" if mentions else "empty")
            self._cache_set(self._reddit_cache, symbol, mentions)
            return mentions
        except ModuleNotFoundError:
            self._mark_source("reddit", "error", "praw_missing")
            return 0
        except Exception as exc:
            self._mark_source("reddit", "error", self._generic_error_key(exc))
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
                self._google_trends_cache[symbol] = (now, 0.0)
                return 0.0
            values = frame[symbol].tail(12).tolist()
            if len(values) < 6:
                self._mark_source("google_trends", "empty")
                self._google_trends_cache[symbol] = (now, 0.0)
                return 0.0
            baseline = sum(values[:6]) / 6
            recent = sum(values[6:]) / 6
            change = ((recent - baseline) / baseline * 100) if baseline else 0.0
            self._google_trends_cache[symbol] = (now, change)
            self._mark_source("google_trends", "ok")
            return change
        except ModuleNotFoundError:
            self._mark_source("google_trends", "error", "pytrends_missing")
            self._google_trends_cache[symbol] = (now, 0.0)
            return 0.0
        except Exception as exc:
            self._mark_source("google_trends", "error", self._generic_error_key(exc))
            self._google_trends_cache[symbol] = (now, 0.0)
            return 0.0

    def _mark_source(self, source: str, status: str, error: str = "") -> None:
        self.source_status[f"{source}_{status}"] += 1
        if error:
            self.source_errors[f"{source}_{error}"] += 1

    def _reddit_client(self):
        if self._reddit is None:
            import praw

            self._reddit = praw.Reddit(
                client_id=self.settings.reddit_client_id,
                client_secret=self.settings.reddit_client_secret,
                user_agent=self.settings.reddit_user_agent,
                check_for_async=False,
            )
        return self._reddit

    @staticmethod
    def _cache_get(cache: dict[str, tuple[datetime, T]], symbol: str, minutes: int) -> T | None:
        cached = cache.get(symbol)
        if not cached:
            return None
        cached_at, value = cached
        if datetime.now(UTC) - cached_at < timedelta(minutes=max(1, minutes)):
            return value
        return None

    @staticmethod
    def _cache_set(cache: dict[str, tuple[datetime, T]], symbol: str, value: T) -> None:
        cache[symbol] = (datetime.now(UTC), value)

    @staticmethod
    def _request_error_key(exc: requests.RequestException) -> str:
        response = getattr(exc, "response", None)
        if response is not None and getattr(response, "status_code", None):
            return f"http_{response.status_code}"
        text = str(exc).lower()
        if "timed out" in text or "timeout" in text:
            return "timeout"
        if "connection" in text:
            return "connection"
        return "request_failed"

    @staticmethod
    def _generic_error_key(exc: Exception) -> str:
        text = str(exc).lower()
        name = exc.__class__.__name__.lower()
        if "429" in text or "too many requests" in text or "ratelimit" in text or "rate limit" in text:
            return "rate_limited"
        if "401" in text or "unauthorized" in text or "invalid_grant" in text:
            return "unauthorized"
        if "403" in text or "forbidden" in text:
            return "forbidden"
        if "timeout" in text or "timed out" in text:
            return "timeout"
        if "ssl" in text:
            return "ssl"
        return name[:50] or "failed"
