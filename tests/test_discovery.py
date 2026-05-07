from squeeze_bot.data.discovery import MarketDiscoveryClient


def test_symbols_from_movers_payload():
    payload = {"gainers": [{"symbol": "ABC"}], "most_actives": [{"symbol": "XYZ"}]}
    assert MarketDiscoveryClient._symbols_from_payload(payload) == ["ABC", "XYZ"]


def test_common_stock_filter_excludes_warrants_and_units():
    assert MarketDiscoveryClient._looks_like_common_stock("GME")
    assert MarketDiscoveryClient._looks_like_common_stock("UBER")
    assert not MarketDiscoveryClient._looks_like_common_stock("JOBY.WS")
    assert not MarketDiscoveryClient._looks_like_common_stock("ATIIW")
    assert not MarketDiscoveryClient._looks_like_common_stock("ATIIU")
