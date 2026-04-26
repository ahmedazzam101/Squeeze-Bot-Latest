from squeeze_bot.data.discovery import MarketDiscoveryClient


def test_symbols_from_movers_payload():
    payload = {"gainers": [{"symbol": "ABC"}], "most_actives": [{"symbol": "XYZ"}]}
    assert MarketDiscoveryClient._symbols_from_payload(payload) == ["ABC", "XYZ"]

