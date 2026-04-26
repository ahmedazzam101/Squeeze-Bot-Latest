from squeeze_bot.engines.scoring import structural_pressure_score
from squeeze_bot.models import StructuralData


def test_missing_structural_fields_are_neutral_not_bearish():
    score = structural_pressure_score(StructuralData(float_shares=25_000_000))
    assert score >= 40

