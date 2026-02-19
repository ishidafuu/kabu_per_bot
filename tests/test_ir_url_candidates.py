from __future__ import annotations

import unittest

from kabu_per_bot.ir_url_candidates import (
    IrUrlCandidateDraft,
    IrUrlCandidateService,
    IrUrlCandidateValidator,
    VertexAiIrUrlSuggestor,
)


class FakeResponse:
    def __init__(self, *, status_code: int, url: str, headers: dict[str, str] | None = None, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.url = url
        self.headers = headers or {}
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http error: status={self.status_code}")

    def json(self) -> dict:
        return self._payload


class FakeHttpClient:
    def __init__(self, routes: dict[str, FakeResponse]) -> None:
        self._routes = routes
        self.calls: list[str] = []

    def get(self, url: str, timeout: float | None = None):
        del timeout
        self.calls.append(url)
        if url not in self._routes:
            raise RuntimeError("route not found")
        return self._routes[url]


class FakeVertexClient:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.last_payload: dict | None = None

    def post(self, url: str, *, headers: dict, json: dict, timeout: float):
        del url, headers, timeout
        self.last_payload = json
        return self._response


class StaticSuggestor:
    def __init__(self, rows: list[IrUrlCandidateDraft]) -> None:
        self._rows = rows

    def suggest(self, *, ticker: str, company_name: str, max_candidates: int) -> list[IrUrlCandidateDraft]:
        del ticker, company_name
        return self._rows[:max_candidates]


class IrUrlCandidatesTest(unittest.TestCase):
    def test_validator_marks_https_ir_path_as_valid(self) -> None:
        validator = IrUrlCandidateValidator(
            http_client=FakeHttpClient(
                {
                    "https://example.com/ir/news": FakeResponse(
                        status_code=200,
                        url="https://example.com/ir/news",
                        headers={"content-type": "text/html; charset=utf-8"},
                    )
                }
            )
        )
        row = validator.validate(
            IrUrlCandidateDraft(
                url="https://example.com/ir/news",
                title="IRニュース",
                reason="候補",
                confidence="High",
            )
        )
        self.assertEqual(row.validation_status, "VALID")
        self.assertGreaterEqual(row.score, 5)
        self.assertEqual(row.confidence, "High")

    def test_validator_rejects_non_https_url(self) -> None:
        validator = IrUrlCandidateValidator(http_client=FakeHttpClient({}))
        row = validator.validate(
            IrUrlCandidateDraft(
                url="http://example.com/ir/news",
                title="IRニュース",
                reason="候補",
                confidence="Med",
            )
        )
        self.assertEqual(row.validation_status, "INVALID")
        self.assertEqual(row.score, 0)
        self.assertIn("https", row.reason)

    def test_service_deduplicates_and_sorts_by_quality(self) -> None:
        validator = IrUrlCandidateValidator(
            http_client=FakeHttpClient(
                {
                    "https://example.com/contact": FakeResponse(
                        status_code=200,
                        url="https://example.com/contact",
                        headers={"content-type": "text/html"},
                    ),
                    "https://example.com/ir/library/report.pdf": FakeResponse(
                        status_code=200,
                        url="https://example.com/ir/library/report.pdf",
                        headers={"content-type": "application/pdf"},
                    ),
                }
            )
        )
        service = IrUrlCandidateService(
            suggestor=StaticSuggestor(
                [
                    IrUrlCandidateDraft(
                        url="https://example.com/contact",
                        title="Contact",
                        reason="候補A",
                        confidence="High",
                    ),
                    IrUrlCandidateDraft(
                        url="https://example.com/ir/library/report.pdf",
                        title="決算資料",
                        reason="候補B",
                        confidence="Med",
                    ),
                    IrUrlCandidateDraft(
                        url="https://example.com/ir/library/report.pdf",
                        title="重複",
                        reason="候補C",
                        confidence="Low",
                    ),
                ]
            ),
            validator=validator,
        )
        rows = service.suggest_candidates(
            ticker="3901:TSE",
            company_name="富士フイルム",
            max_candidates=5,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].url, "https://example.com/ir/library/report.pdf")

    def test_vertex_suggestor_parses_json_response(self) -> None:
        client = FakeVertexClient(
            FakeResponse(
                status_code=200,
                url="https://example.com",
                payload={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": (
                                            '{"candidates":['
                                            '{"url":"https://example.com/ir","title":"IR情報","reason":"公式IRページ","confidence":"High"}'
                                            "]}"
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        )
        suggestor = VertexAiIrUrlSuggestor(
            project_id="demo-project",
            credentials_provider=lambda: ("dummy-token", "ignored-project"),
            http_client=client,
        )
        rows = suggestor.suggest(
            ticker="3901:TSE",
            company_name="富士フイルム",
            max_candidates=5,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].url, "https://example.com/ir")
        self.assertEqual(rows[0].confidence, "High")
        self.assertEqual(
            client.last_payload["generationConfig"]["responseMimeType"],
            "application/json",
        )


if __name__ == "__main__":
    unittest.main()
