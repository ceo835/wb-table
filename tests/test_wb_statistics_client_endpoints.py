from datetime import date

from src.clients.wb_statistics_client import WBStatisticsClient


def test_wb_statistics_client_uses_documented_endpoints(monkeypatch):
    client = WBStatisticsClient(token="test-token")
    captured = []

    def fake_get(endpoint, params=None, headers=None, **kwargs):
        captured.append((endpoint, params))
        return []

    monkeypatch.setattr(client, "get", fake_get)

    client.wb_statistics_orders(date_from=date(2026, 5, 31), date_to=date(2026, 6, 1), limit=1000)
    client.wb_report_detail_by_period(date_from=date(2026, 5, 31), date_to=date(2026, 6, 1))

    assert captured[0][0] == "/api/v1/supplier/orders"
    assert captured[1][0] == "/api/v5/supplier/reportDetailByPeriod"
    assert captured[1][1]["period"] == "daily"
    assert captured[1][1]["rrdid"] == 0
