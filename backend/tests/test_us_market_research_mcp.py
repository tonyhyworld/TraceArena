from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "us_market_research_mcp_server.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "us_market_research_mcp_server", MODULE_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sec_filings_accept_business_parameters_and_normalize_ticker(monkeypatch):
    module = _load_module()
    module._TICKER_CACHE = {
        "AAPL": {"ticker": "AAPL", "title": "Apple Inc.", "cik_str": 320193}
    }
    module._TICKER_CACHE_AT = module.time.time()
    monkeypatch.setattr(
        module,
        "_sec_submissions",
        lambda identity: ({
            "cik": identity["cik"],
            "filings": {"recent": {
                "form": ["10-Q", "8-K"],
                "filingDate": ["2026-07-20", "2026-07-18"],
                "accessionNumber": [
                    "0000320193-26-000001", "0000320193-26-000002",
                ],
                "primaryDocument": ["a10q.htm", "a8k.htm"],
            }},
        }, {
            "source_uri": "https://data.sec.gov/submissions/test.json",
            "fetched_at": 1.0,
            "source_hash": "abc",
        }),
    )

    result = module._sec_filings({
        "symbol": "AAPL.US", "forms": ["10-Q"], "limit": 5,
    })

    assert result["subject_id"] == "AAPL.US"
    assert result["record_count"] == 1
    assert result["filings"][0]["form"] == "10-Q"
    assert set(result["research_categories"]) == {"filings", "catalyst"}


def test_earnings_calendar_validates_json_contract(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(
        module,
        "_fetch_json",
        lambda *_args, **_kwargs: ({
            "data": {"rows": [
                {"symbol": "AAPL", "epsForecast": "$1.50"},
                {"symbol": "MSFT", "epsForecast": "$3.00"},
            ]},
        }, {
            "source_uri": "https://api.nasdaq.com/test",
            "fetched_at": 1.0,
            "source_hash": "abc",
        }),
    )
    result = module._earnings_calendar({
        "symbol": "AAPL.US", "date": "2026-07-24",
    })
    assert result["record_count"] == 1
    assert result["earnings"][0]["symbol"] == "AAPL"
    assert result["research_categories"] == ["earnings", "catalyst"]
