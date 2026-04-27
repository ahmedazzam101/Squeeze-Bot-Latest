from __future__ import annotations

from datetime import UTC, datetime, timedelta

import requests

from squeeze_bot.config import Settings
from squeeze_bot.models import CatalystData, SocialData, StructuralData


class EnrichmentClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def structural_data(self, symbol: str) -> StructuralData:
        data = StructuralData()
        if self.settings.fmp_api_key:
            data = self._fmp_structural(symbol, data)
        return data

    def catalyst_data(self, symbol: str) -> CatalystData:
        headlines: list[str] = []
        if self.settings.finnhub_api_key:
            headlines.extend(self._finnhub_headlines(symbol))
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
            return data
        if isinstance(profile, list) and profile:
            item = profile[0]
            data.float_shares = float(item.get("floatShares") or item.get("sharesOutstanding") or 0)
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
            return []
        items = response.json()
        if not isinstance(items, list):
            return []
        return [str(item.get("headline", "")) for item in items if item.get("headline")]

    def _reddit_mentions(self, symbol: str) -> int:
        if not (self.settings.reddit_client_id and self.settings.reddit_client_secret):
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
            return sum(1 for _ in subreddits.search(query, sort="new", time_filter="hour", limit=100))
        except Exception:
            return 0

    def _google_trends_change(self, symbol: str) -> float:
        try:
            from pytrends.request import TrendReq

            trends = TrendReq(hl="en-US", tz=360)
            trends.build_payload([symbol], timeframe="now 1-d", geo="US")
            frame = trends.interest_over_time()
            if frame.empty or symbol not in frame:
                return 0.0
            values = frame[symbol].tail(12).tolist()
            if len(values) < 6:
                return 0.0
            baseline = sum(values[:6]) / 6
            recent = sum(values[6:]) / 6
            return ((recent - baseline) / baseline * 100) if baseline else 0.0
        except Exception:
            return 0.0
