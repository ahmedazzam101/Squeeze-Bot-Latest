from pathlib import Path

from squeeze_bot.backtest.replay import replay_trades


def test_replay_trades_runs(tmp_path: Path):
    fixture = tmp_path / "sample.csv"
    fixture.write_text(
        "symbol,timestamp,close,composite_score,acceleration_score,acceleration_rising\n"
        "TEST,1,10,75,80,true\n"
        "TEST,2,12,80,85,true\n"
        "TEST,3,11,70,70,false\n"
    )
    metrics = replay_trades(fixture)
    assert metrics.trades == 1
