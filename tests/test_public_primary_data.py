from __future__ import annotations

from datetime import date
from unittest import TestCase
from unittest.mock import MagicMock

from kabu_per_bot.public_primary_data import EStatApiClient, EStatApiError, EdinetApiClient


class _Response:
    def __init__(self, *, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class PublicPrimaryDataTest(TestCase):
    def test_edinet_collect_recent_filings_filters_ticker_and_sorts(self) -> None:
        calls: list[str] = []

        def _fake_get(url: str, *, params: dict, headers: dict, timeout: float):
            _ = url, headers, timeout
            target_date = params["date"]
            calls.append(target_date)
            if target_date == "2026-03-01":
                return _Response(
                    status_code=200,
                    payload={
                        "results": [
                            {
                                "docID": "S100AAAA",
                                "secCode": "72030",
                                "ordinanceCode": "010",
                                "formCode": "030000",
                                "docDescription": "有価証券報告書",
                                "submitDateTime": "2026-03-01T09:00:00+09:00",
                            },
                            {
                                "docID": "S100BBBB",
                                "secCode": "67580",
                                "ordinanceCode": "010",
                                "formCode": "030000",
                                "docDescription": "有価証券報告書",
                                "submitDateTime": "2026-03-01T08:00:00+09:00",
                            },
                        ]
                    },
                )
            if target_date == "2026-02-28":
                return _Response(
                    status_code=200,
                    payload={
                        "results": [
                            {
                                "docID": "S100CCCC",
                                "secCode": "72030",
                                "ordinanceCode": "010",
                                "formCode": "043000",
                                "docDescription": "四半期報告書",
                                "submitDateTime": "2026-02-28T12:00:00+09:00",
                            }
                        ]
                    },
                )
            return _Response(status_code=200, payload={"results": []})

        http_client = MagicMock()
        http_client.get.side_effect = _fake_get

        client = EdinetApiClient(api_key="dummy", http_client=http_client)
        filings = client.collect_recent_filings(
            ticker="7203:TSE",
            lookback_days=2,
            max_items=2,
            today=date(2026, 3, 1),
        )
        # cache hit check
        filings_second = client.collect_recent_filings(
            ticker="7203:TSE",
            lookback_days=2,
            max_items=2,
            today=date(2026, 3, 1),
        )

        self.assertEqual(len(filings), 2)
        self.assertEqual(filings[0].doc_id, "S100AAAA")
        self.assertEqual(filings[1].doc_id, "S100CCCC")
        self.assertEqual(filings, filings_second)
        self.assertEqual(calls, ["2026-03-01", "2026-02-28"])

    def test_estat_fetch_latest_metric_picks_latest_time(self) -> None:
        http_client = MagicMock()
        http_client.get.return_value = _Response(
            status_code=200,
            payload={
                "GET_STATS_DATA": {
                    "STATISTICAL_DATA": {
                        "DATA_INF": {
                            "VALUE": [
                                {"@time": "2025M12", "$": "108.5"},
                                {"@time": "2026M01", "$": "109.2"},
                            ]
                        }
                    }
                }
            },
        )

        client = EStatApiClient(app_id="dummy", http_client=http_client)
        point = client.fetch_latest_metric(stats_data_id="0003412313")

        self.assertIsNotNone(point)
        assert point is not None
        self.assertEqual(point.time_key, "2026M01")
        self.assertEqual(point.value, 109.2)

    def test_estat_fetch_latest_metric_raises_when_api_status_error(self) -> None:
        http_client = MagicMock()
        http_client.get.return_value = _Response(
            status_code=200,
            payload={
                "GET_STATS_DATA": {
                    "RESULT": {
                        "STATUS": "100",
                        "ERROR_MSG": "appId is invalid.",
                    }
                }
            },
        )

        client = EStatApiClient(app_id="dummy", http_client=http_client)

        with self.assertRaises(EStatApiError):
            _ = client.fetch_latest_metric(stats_data_id="0003412313")
