from __future__ import annotations

import json
import re

from squeeze_bot.config import Settings
from squeeze_bot.models import CatalystData, ClaudeAnalysis, ClaudeVote, MarketSnapshot, Scores, SocialData, StructuralData


class ClaudeAnalyzer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def analyze(
        self,
        snapshot: MarketSnapshot,
        structural: StructuralData,
        catalyst: CatalystData,
        social: SocialData,
        scores: Scores | None = None,
        position_status: str = "none",
    ) -> ClaudeAnalysis:
        if not self.settings.anthropic_api_key:
            return self._fallback(snapshot, catalyst, scores)

        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=self.settings.anthropic_api_key)
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=600,
                temperature=0,
                system=(
                    "You are the analysis layer for a rule-based trading system. "
                    "You do not predict prices and you do not place trades. "
                    "Classify catalyst quality, dilution/offering risk, manipulation risk, and setup coherence. "
                    "Return strict JSON only."
                ),
                messages=[{"role": "user", "content": json.dumps(self._payload(snapshot, structural, catalyst, social, scores, position_status), default=str)}],
            )
            text = response.content[0].text if response.content else "{}"
            parsed = self._parse_json(text)
            return ClaudeAnalysis(
                vote=ClaudeVote(parsed.get("vote", "WATCH")),
                confidence=float(parsed.get("confidence", 0.0)),
                catalyst_quality=float(parsed.get("catalyst_quality", 0.0)),
                manipulation_risk=float(parsed.get("manipulation_risk", 0.0)),
                dilution_risk=float(parsed.get("dilution_risk", 0.0)),
                summary=str(parsed.get("summary", "")),
                red_flags=list(parsed.get("red_flags", [])),
                raw=parsed,
            )
        except Exception as exc:
            fallback = self._fallback(snapshot, catalyst, scores)
            fallback.summary = f"Claude unavailable; fallback analysis used: {exc}"
            return fallback

    @staticmethod
    def _parse_json(text: str) -> dict:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                return json.loads(cleaned[start : end + 1])
            raise

    @staticmethod
    def _payload(
        snapshot: MarketSnapshot,
        structural: StructuralData,
        catalyst: CatalystData,
        social: SocialData,
        scores: Scores | None,
        position_status: str,
    ) -> dict:
        return {
            "allowed_votes": [
                "IGNORE",
                "WATCH",
                "BUY_CANDIDATE",
                "HOLD",
                "HOLD_BUT_TIGHTEN_STOP",
                "EXIT_WARNING",
                "EXIT_NOW_CATALYST_RISK",
            ],
            "symbol": snapshot.symbol,
            "position_status": position_status,
            "market": snapshot.__dict__,
            "structural": structural.__dict__,
            "catalyst": catalyst.__dict__,
            "social": social.__dict__,
            "scores": scores.__dict__ if scores else None,
            "json_schema": {
                "vote": "one allowed vote",
                "confidence": "0.0 to 1.0",
                "catalyst_quality": "0.0 to 1.0",
                "manipulation_risk": "0.0 to 1.0",
                "dilution_risk": "0.0 to 1.0",
                "summary": "short explanation",
                "red_flags": ["short strings"],
            },
        }

    @staticmethod
    def _fallback(snapshot: MarketSnapshot, catalyst: CatalystData, scores: Scores | None) -> ClaudeAnalysis:
        if scores and scores.composite >= 70 and catalyst.news_count_24h > 0:
            vote = ClaudeVote.BUY_CANDIDATE
            confidence = 0.55
        elif snapshot.rvol >= 2:
            vote = ClaudeVote.WATCH
            confidence = 0.45
        else:
            vote = ClaudeVote.IGNORE
            confidence = 0.35
        return ClaudeAnalysis(vote=vote, confidence=confidence, catalyst_quality=min(catalyst.news_count_24h / 4, 1.0), manipulation_risk=0.25, dilution_risk=0.0, summary="Fallback heuristic analysis.")
