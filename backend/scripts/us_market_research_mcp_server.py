#!/usr/bin/env python3
"""US public-market research MCP server.

This connector owns source-specific URL construction and response validation.
Agents provide business parameters (ticker, form, date, series) rather than
inventing transport URLs. Sources are read-only and publicly verifiable:
SEC EDGAR, Nasdaq's public earnings calendar, and Federal Reserve FRED.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


_TICKER_CACHE: Dict[str, Dict[str, Any]] = {}
_TICKER_CACHE_AT = 0.0
_CACHE_TTL_SEC = 24 * 60 * 60
_MAX_RESPONSE_BYTES = 8_000_000


def _send(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _ok(req_id: Any, result: Dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error_content(
    req_id: Any,
    message: str,
    *,
    failure_class: str = "tool_execution",
    retryable: bool = False,
) -> None:
    _ok(req_id, {
        "content": [{"type": "text", "text": message}],
        "structuredContent": {
            "failure_class": failure_class,
            "retryable": retryable,
            "message": message,
        },
        "isError": True,
    })


def _user_agent() -> str:
    return os.getenv(
        "AIWORLD_SEC_USER_AGENT",
        "AIWorld-Research/1.0 contact=admin@example.com",
    )


def _fetch(
    url: str,
    *,
    accept: str,
    timeout: float = 15.0,
    browser_agent: bool = False,
) -> Tuple[bytes, Dict[str, str]]:
    headers = {
        "Accept": accept,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/126 Safari/537.36"
            if browser_agent else _user_agent()
        ),
    }
    request = Request(url, headers=headers)
    with urlopen(request, timeout=max(2.0, min(25.0, timeout))) as response:
        status = int(getattr(response, "status", 200) or 200)
        content_type = str(response.headers.get("Content-Type") or "")
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
    if status < 200 or status >= 300:
        raise RuntimeError(f"http_status:{status}")
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("response_too_large")
    if not raw.strip():
        raise ValueError("empty_response")
    return raw, {"content_type": content_type, "source_uri": url}


def _fetch_json(
    url: str, *, timeout: float = 15.0, browser_agent: bool = False,
) -> Tuple[Any, Dict[str, Any]]:
    raw, metadata = _fetch(
        url,
        accept="application/json,text/plain;q=0.8",
        timeout=timeout,
        browser_agent=browser_agent,
    )
    text = raw.decode("utf-8", errors="replace").lstrip()
    if text.startswith(("<!DOCTYPE", "<html", "<HTML")):
        raise ValueError("invalid_response_content_type:html")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid_response_json:{exc.msg}@{exc.pos}"
        ) from exc
    metadata.update({
        "fetched_at": time.time(),
        "source_hash": hashlib.sha256(raw).hexdigest(),
    })
    return data, metadata


def _normalize_symbol(arguments: Dict[str, Any]) -> str:
    symbol = str(arguments.get("symbol") or "").strip().upper()
    if symbol.endswith(".US"):
        symbol = symbol[:-3]
    if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
        raise ValueError("invalid symbol: use a US ticker such as AAPL.US")
    return symbol


def _ticker_index() -> Dict[str, Dict[str, Any]]:
    global _TICKER_CACHE, _TICKER_CACHE_AT
    if _TICKER_CACHE and time.time() - _TICKER_CACHE_AT < _CACHE_TTL_SEC:
        return _TICKER_CACHE
    payload, _ = _fetch_json(
        "https://www.sec.gov/files/company_tickers.json",
        timeout=18,
    )
    if not isinstance(payload, dict):
        raise ValueError("invalid_response_contract:company_tickers")
    index: Dict[str, Dict[str, Any]] = {}
    for row in payload.values():
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker:
            index[ticker] = row
    if not index:
        raise ValueError("empty_dataset:company_tickers")
    _TICKER_CACHE = index
    _TICKER_CACHE_AT = time.time()
    return index


def _company_identity(symbol: str) -> Dict[str, Any]:
    row = _ticker_index().get(symbol)
    if not row:
        raise ValueError(f"data_unavailable: SEC CIK not found for {symbol}")
    cik = int(row.get("cik_str") or 0)
    if cik <= 0:
        raise ValueError(f"invalid_response_contract: CIK for {symbol}")
    return {
        "symbol": f"{symbol}.US",
        "ticker": symbol,
        "name": str(row.get("title") or symbol),
        "cik": cik,
        "cik_padded": f"{cik:010d}",
    }


def _sec_submissions(identity: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    data, meta = _fetch_json(
        "https://data.sec.gov/submissions/"
        f"CIK{identity['cik_padded']}.json",
        timeout=18,
    )
    if not isinstance(data, dict):
        raise ValueError("invalid_response_contract:sec_submissions")
    return data, meta


def _recent_filings(
    submissions: Dict[str, Any],
    *,
    forms: List[str],
    limit: int,
) -> List[Dict[str, Any]]:
    recent = ((submissions.get("filings") or {}).get("recent") or {})
    if not isinstance(recent, dict):
        return []
    columns = {
        key: value for key, value in recent.items() if isinstance(value, list)
    }
    size = max((len(value) for value in columns.values()), default=0)
    wanted = {item.upper() for item in forms if item}
    rows: List[Dict[str, Any]] = []
    for index in range(size):
        form = str(
            columns.get("form", [])[index]
            if index < len(columns.get("form", [])) else ""
        ).upper()
        if wanted and form not in wanted:
            continue
        row = {
            key: values[index] if index < len(values) else None
            for key, values in columns.items()
            if key in {
                "accessionNumber", "filingDate", "reportDate",
                "acceptanceDateTime", "act", "form", "fileNumber",
                "filmNumber", "items", "primaryDocument",
                "primaryDocDescription",
            }
        }
        accession = str(row.get("accessionNumber") or "").replace("-", "")
        primary = str(row.get("primaryDocument") or "")
        if accession and primary:
            cik = int(submissions.get("cik") or 0)
            row["filing_url"] = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{accession}/{primary}"
            )
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _sec_filings(arguments: Dict[str, Any]) -> Dict[str, Any]:
    identity = _company_identity(_normalize_symbol(arguments))
    forms_raw = arguments.get("forms") or ["10-K", "10-Q", "8-K", "6-K", "FORM 4"]
    forms = [str(item).upper() for item in forms_raw]
    limit = max(1, min(30, int(arguments.get("limit") or 12)))
    submissions, metadata = _sec_submissions(identity)
    rows = _recent_filings(submissions, forms=forms, limit=limit)
    return {
        **identity,
        "subject_id": identity["symbol"],
        "symbols": [identity["symbol"]],
        "research_categories": ["filings", "catalyst"],
        "forms_requested": forms,
        "filings": rows,
        "record_count": len(rows),
        "evidence_eligible": bool(rows),
        "source_name": "SEC EDGAR submissions",
        **metadata,
    }


_FACT_TAGS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "diluted_eps": ("EarningsPerShareDiluted",),
    "assets": ("Assets",),
    "liabilities": ("Liabilities", "LiabilitiesCurrent"),
    "equity": (
        "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditure": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForAdditionsToPropertyPlantAndEquipment",
    ),
}


def _latest_fact(facts: Dict[str, Any], tags: Tuple[str, ...]) -> Dict[str, Any]:
    for tag in tags:
        node = facts.get(tag)
        if not isinstance(node, dict):
            continue
        units = node.get("units") or {}
        candidates: List[Dict[str, Any]] = []
        for unit, entries in units.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("form") or "").upper() not in {
                    "10-K", "10-Q", "20-F", "40-F",
                }:
                    continue
                candidates.append({"unit": unit, "tag": tag, **entry})
        if candidates:
            candidates.sort(
                key=lambda item: (
                    str(item.get("filed") or ""),
                    str(item.get("end") or ""),
                ),
                reverse=True,
            )
            return candidates[0]
    return {}


def _financial_statements(arguments: Dict[str, Any]) -> Dict[str, Any]:
    identity = _company_identity(_normalize_symbol(arguments))
    url = (
        "https://data.sec.gov/api/xbrl/companyfacts/"
        f"CIK{identity['cik_padded']}.json"
    )
    payload, metadata = _fetch_json(url, timeout=22)
    facts = ((payload or {}).get("facts") or {}).get("us-gaap") or {}
    if not isinstance(facts, dict):
        raise ValueError("data_unavailable: no US-GAAP company facts")
    metrics = {
        label: _latest_fact(facts, tags)
        for label, tags in _FACT_TAGS.items()
    }
    metrics = {key: value for key, value in metrics.items() if value}
    if not metrics:
        raise ValueError("empty_dataset: no comparable financial facts")
    return {
        **identity,
        "subject_id": identity["symbol"],
        "symbols": [identity["symbol"]],
        "research_categories": ["financials"],
        "statement": str(arguments.get("statement") or "summary"),
        "metrics": metrics,
        "record_count": len(metrics),
        "evidence_eligible": True,
        "source_name": "SEC EDGAR XBRL company facts",
        **metadata,
    }


def _company_material_events(arguments: Dict[str, Any]) -> Dict[str, Any]:
    identity = _company_identity(_normalize_symbol(arguments))
    submissions, metadata = _sec_submissions(identity)
    limit = max(1, min(30, int(arguments.get("limit") or 10)))
    rows = _recent_filings(
        submissions, forms=["8-K", "6-K"], limit=limit,
    )
    return {
        **identity,
        "subject_id": identity["symbol"],
        "symbols": [identity["symbol"]],
        "research_categories": (
            ["news", "catalyst", "filings"] if rows else ["filings"]
        ),
        "material_events": rows,
        "record_count": len(rows),
        "evidence_eligible": bool(rows),
        "source_name": "SEC EDGAR material-event filings",
        "source_note": (
            "Authoritative 8-K/6-K event disclosures; this is not an "
            "unverified media-news feed."
        ),
        **metadata,
    }


def _earnings_calendar(arguments: Dict[str, Any]) -> Dict[str, Any]:
    date_text = str(arguments.get("date") or "").strip()
    if not date_text:
        date_text = dt.datetime.now(
            ZoneInfo("America/New_York")
        ).date().isoformat()
    try:
        query_date = dt.date.fromisoformat(date_text)
    except ValueError as exc:
        raise ValueError("invalid argument: date must be YYYY-MM-DD") from exc
    url = "https://api.nasdaq.com/api/calendar/earnings?" + urlencode({
        "date": query_date.isoformat(),
    })
    payload, metadata = _fetch_json(
        url, timeout=18, browser_agent=True,
    )
    rows = (((payload or {}).get("data") or {}).get("rows") or [])
    if not isinstance(rows, list):
        raise ValueError("invalid_response_contract:nasdaq_earnings")
    symbol = str(arguments.get("symbol") or "").strip().upper()
    if symbol.endswith(".US"):
        symbol = symbol[:-3]
    if symbol:
        rows = [
            row for row in rows
            if isinstance(row, dict)
            and str(row.get("symbol") or "").upper() == symbol
        ]
        if not rows:
            raise ValueError(
                f"data_unavailable: no scheduled earnings for {symbol} "
                f"on {query_date.isoformat()}"
            )
    limit = max(1, min(200, int(arguments.get("limit") or 50)))
    rows = rows[:limit]
    canonical = f"{symbol}.US" if symbol else ""
    return {
        "symbol": canonical,
        "subject_id": canonical,
        "symbols": [canonical] if canonical else [],
        "date": query_date.isoformat(),
        "research_categories": ["earnings", "catalyst"],
        "earnings": rows,
        "record_count": len(rows),
        "evidence_eligible": bool(rows),
        "source_name": "Nasdaq earnings calendar",
        **metadata,
    }


_FRED_SERIES = {
    "fed_funds": "DFF",
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "cpi": "CPIAUCSL",
    "unemployment": "UNRATE",
    "payrolls": "PAYEMS",
    "vix": "VIXCLS",
}


def _fred_latest(series_id: str) -> Dict[str, Any]:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode({
        "id": series_id,
    })
    raw, metadata = _fetch(
        url, accept="text/csv,text/plain;q=0.8", timeout=18,
    )
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8", errors="replace")))
    rows = list(reader)
    valid = [
        row for row in rows
        if str(row.get(series_id) or "").strip() not in {"", "."}
    ]
    if not valid:
        raise ValueError(f"empty_dataset:FRED {series_id}")
    latest = valid[-1]
    return {
        "series_id": series_id,
        "observation_date": latest.get("observation_date"),
        "value": latest.get(series_id),
        "source_uri": metadata["source_uri"],
        "source_hash": hashlib.sha256(raw).hexdigest(),
    }


def _macro_indicators(arguments: Dict[str, Any]) -> Dict[str, Any]:
    requested = arguments.get("indicators") or [arguments.get("indicator") or "fed_funds"]
    indicators = [str(item).strip().lower() for item in requested if str(item).strip()]
    unknown = [item for item in indicators if item not in _FRED_SERIES]
    if unknown:
        raise ValueError(
            "invalid argument: unsupported indicators "
            + ", ".join(unknown)
            + "; allowed="
            + ", ".join(sorted(_FRED_SERIES))
        )
    observations = [
        {"indicator": item, **_fred_latest(_FRED_SERIES[item])}
        for item in indicators
    ]
    return {
        "research_categories": ["macro"],
        "observations": observations,
        "record_count": len(observations),
        "evidence_eligible": bool(observations),
        "source_name": "Federal Reserve Bank of St. Louis FRED",
        "fetched_at": time.time(),
    }


_SYMBOL = {
    "symbol": {
        "type": "string",
        "description": "US ticker, preferably with .US suffix (for example AAPL.US)",
    },
}
_TOOLS: Dict[
    str,
    Tuple[str, Dict[str, Any], List[str], Callable[[Dict[str, Any]], Dict[str, Any]]],
] = {
    "us_sec_filings": (
        "Read authoritative recent SEC filings for a US issuer.",
        {
            **_SYMBOL,
            "forms": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "minimum": 1, "maximum": 30},
        },
        ["symbol"],
        _sec_filings,
    ),
    "us_financial_statements": (
        "Read normalized latest financial facts from SEC XBRL company facts.",
        {
            **_SYMBOL,
            "statement": {
                "type": "string",
                "enum": ["summary", "income", "balance", "cash_flow"],
            },
        },
        ["symbol"],
        _financial_statements,
    ),
    "us_company_material_events": (
        "Read authoritative recent 8-K/6-K material-event disclosures.",
        {**_SYMBOL, "limit": {"type": "integer", "minimum": 1, "maximum": 30}},
        ["symbol"],
        _company_material_events,
    ),
    "us_earnings_calendar": (
        "Read the Nasdaq earnings calendar for a date, optionally filtered by ticker.",
        {
            **_SYMBOL,
            "date": {"type": "string", "description": "YYYY-MM-DD; defaults to today"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        [],
        _earnings_calendar,
    ),
    "us_macro_indicators": (
        "Read latest official macro observations from FRED.",
        {
            "indicator": {"type": "string", "enum": sorted(_FRED_SERIES)},
            "indicators": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(_FRED_SERIES)},
            },
        },
        [],
        _macro_indicators,
    ),
}


def _failure_metadata(exc: Exception) -> Tuple[str, bool]:
    text = str(exc).lower()
    if any(token in text for token in ("timeout", "temporar", "502", "503", "504")):
        return "transient_transport", True
    if any(token in text for token in ("invalid argument", "invalid symbol")):
        return "invalid_request", False
    if any(token in text for token in ("invalid_response", "empty_response")):
        return "data_format", False
    if any(token in text for token in ("data_unavailable", "empty_dataset", "not found")):
        return "data_unavailable", False
    if any(token in text for token in ("401", "403", "forbidden")):
        return "permission", False
    return "tool_execution", False


def _handle(request: Dict[str, Any]) -> None:
    method = str(request.get("method") or "")
    req_id = request.get("id")
    params = request.get("params") or {}
    if method == "initialize":
        _ok(req_id, {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "aiworld-us-market-research",
                "version": "1.0.0",
            },
        })
    elif method == "notifications/initialized":
        return
    elif method == "tools/list":
        _ok(req_id, {"tools": [
            {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
            for name, (description, properties, required, _fn) in _TOOLS.items()
        ]})
    elif method == "tools/call":
        name = str(params.get("name") or "")
        entry = _TOOLS.get(name)
        if entry is None:
            _error_content(
                req_id, f"unknown_tool:{name}",
                failure_class="invalid_request",
            )
            return
        try:
            result = entry[3](params.get("arguments") or {})
        except Exception as exc:  # noqa: BLE001 - external data boundary
            failure_class, retryable = _failure_metadata(exc)
            _error_content(
                req_id, str(exc),
                failure_class=failure_class,
                retryable=retryable,
            )
            return
        _ok(req_id, {
            "content": [{
                "type": "text",
                "text": f"{name} returned verified public data",
            }],
            "structuredContent": result,
            "isError": False,
        })
    elif req_id is not None:
        _send({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        })


def main() -> None:
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(request, dict):
            _handle(request)


if __name__ == "__main__":
    main()
