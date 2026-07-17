#!/usr/bin/env python3
"""A/H 股深度投研 MCP 服务：财报、新闻、宏观与行业供需。

数据通过 AkShare 读取公开源；本服务只提供只读研究，不连接真实交易。
所有结果带研究类别、来源与抓取时间，供 Agent 循环和结算层校验证据覆盖。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sys
import time
from typing import Any, Callable, Dict, List, Tuple


def _send(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _ok(req_id: Any, result: Dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error_content(req_id: Any, message: str) -> None:
    _ok(req_id, {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    })


def _akshare():
    try:
        import akshare as ak
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise RuntimeError(
            "缺少 akshare；请执行 pip install akshare 后重试"
        ) from exc
    return ak


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        try:
            return _clean(value.item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


def _records(frame: Any, *, limit: int, sort_field: str = "") -> List[Dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    work = frame.copy()
    if sort_field and sort_field in work.columns:
        work = work.sort_values(sort_field, ascending=False)
    rows = work.head(max(1, min(20, int(limit)))).to_dict("records")
    return [_clean(dict(row)) for row in rows]


def _symbol(args: Dict[str, Any]) -> str:
    raw = str(args.get("symbol") or "").strip().upper()
    if not raw:
        raise ValueError("需要 symbol（例如 600519.SH、300750.SZ 或 00700.HK）")
    return raw


def _a_share_code(symbol: str) -> Tuple[str, str]:
    code = symbol.split(".")[0].lstrip("0") or "0"
    code = code.zfill(6)
    suffix = symbol.split(".")[-1] if "." in symbol else ""
    if suffix == "HK":
        raise ValueError("该调用仅支持 A 股代码")
    market = "sh" if suffix in {"SH", "SS"} or code.startswith(("5", "6", "9")) else "sz"
    return code, f"{market}{code}"


def _canonical_symbol(symbol: str) -> str:
    """统一输出带市场后缀的代码，便于结算层与订单匹配。

    002185 → 002185.SZ；600519 → 600519.SH；600036.SS → 600036.SH。
    """
    raw = str(symbol or "").strip().upper()
    if not raw:
        return raw
    if raw.endswith(".SS"):
        raw = raw[:-3] + ".SH"
    if "." in raw:
        num, _, suf = raw.partition(".")
        if suf == "HK":
            padded = (num.lstrip("0") or "0").zfill(5)
            return f"{padded}.HK"
        code = (num.lstrip("0") or "0").zfill(6)
        if suf in {"SH", "SZ"}:
            return f"{code}.{suf}"
        market = "SH" if code.startswith(("5", "6", "9")) else "SZ"
        return f"{code}.{market}"
    if not raw.isdigit():
        return raw
    code = (raw.lstrip("0") or "0").zfill(6)
    market = "SH" if code.startswith(("5", "6", "9")) else "SZ"
    return f"{code}.{market}"


_STATEMENT_NAMES = {
    "income": "利润表",
    "balance": "资产负债表",
    "cash_flow": "现金流量表",
}

_STATEMENT_FIELDS = {
    "income": [
        "报告日", "营业总收入", "营业收入", "营业总成本", "营业利润",
        "利润总额", "净利润", "归属于母公司所有者的净利润",
        "基本每股收益", "公告日期", "币种", "是否审计",
    ],
    "balance": [
        "报告日", "货币资金", "应收账款", "存货", "流动资产合计",
        "资产总计", "短期借款", "流动负债合计", "负债合计",
        "归属于母公司股东权益合计", "公告日期", "币种", "是否审计",
    ],
    "cash_flow": [
        "报告日", "经营活动产生的现金流量净额",
        "投资活动产生的现金流量净额", "筹资活动产生的现金流量净额",
        "现金及现金等价物净增加额", "期末现金及现金等价物余额",
        "公告日期", "币种", "是否审计",
    ],
}


def _financial_statements(args: Dict[str, Any]) -> Dict[str, Any]:
    symbol = _canonical_symbol(_symbol(args))
    statement = str(args.get("statement") or "income").strip().lower()
    if statement not in _STATEMENT_NAMES:
        raise ValueError("statement 只能是 income、balance 或 cash_flow")
    limit = int(args.get("limit") or 4)
    if symbol.endswith(".HK"):
        code = symbol.split(".")[0].zfill(5)
        frame = _akshare().stock_financial_hk_report_em(
            stock=code,
            symbol=_STATEMENT_NAMES[statement],
            indicator="年度",
        )
        rows = []
        if frame is not None and not frame.empty:
            dates = sorted(
                {
                    str(value) for value in frame["REPORT_DATE"].dropna().tolist()
                },
                reverse=True,
            )[:max(1, min(12, limit))]
            for report_date in dates:
                subset = frame[
                    frame["REPORT_DATE"].astype(str) == report_date
                ]
                items = {
                    str(row["STD_ITEM_NAME"]): _clean(row["AMOUNT"])
                    for _, row in subset.iterrows()
                    if row.get("STD_ITEM_NAME") not in (None, "")
                    and _clean(row.get("AMOUNT")) is not None
                }
                rows.append({
                    "报告日": report_date,
                    "证券名称": str(
                        subset.iloc[0].get("SECURITY_NAME_ABBR") or ""
                    ),
                    "项目": dict(list(items.items())[:80]),
                })
        source_uri = "https://data.eastmoney.com/hkstock/financial.html"
        source_name = "东方财富港股财务报表"
    else:
        code, sina_code = _a_share_code(symbol)
        frame = _akshare().stock_financial_report_sina(
            stock=sina_code,
            symbol=_STATEMENT_NAMES[statement],
        )
        fields = [
            name for name in _STATEMENT_FIELDS[statement]
            if name in frame.columns
        ]
        if fields:
            frame = frame[fields]
        rows = _records(
            frame,
            limit=limit,
            sort_field="报告日",
        )
        source_uri = (
            "https://quotes.sina.cn/cn/api/openapi.php/"
            "CompanyFinanceService.getFinanceReport2022"
        )
        source_name = "新浪财经公司财务报表"
    return {
        "research_categories": ["financials", statement],
        "subject_id": symbol,
        "symbol": symbol,
        "symbols": list(dict.fromkeys([
            symbol,
            symbol.split(".")[0],
        ])),
        "statement": statement,
        "records": rows,
        "source_uri": source_uri,
        "source_name": source_name,
        "record_count": len(rows),
        "query_code": code,
    }


def _company_news(args: Dict[str, Any]) -> Dict[str, Any]:
    symbol = _canonical_symbol(_symbol(args))
    code, _ = _a_share_code(symbol)
    frame = _akshare().stock_news_em(symbol=code)
    rows = _records(
        frame,
        limit=int(args.get("limit") or 8),
        sort_field="发布时间",
    )
    return {
        "research_categories": ["news", "catalyst"],
        "subject_id": symbol,
        "symbol": symbol,
        "symbols": list(dict.fromkeys([
            symbol,
            symbol.split(".")[0],
        ])),
        "news": rows,
        "source_uri": "https://so.eastmoney.com/news/s",
        "source_name": "东方财富个股新闻",
        "record_count": len(rows),
    }


_MACRO_DATASETS: Dict[str, Tuple[str, str, List[str]]] = {
    "gdp": ("macro_china_gdp", "季度", ["macro"]),
    "cpi": ("macro_china_cpi", "月份", ["macro"]),
    "pmi": ("macro_china_pmi", "月份", ["macro", "industry"]),
    "money_supply": ("macro_china_money_supply", "月份", ["macro", "liquidity"]),
    "retail": (
        "macro_china_consumer_goods_retail",
        "月份",
        ["macro", "industry", "supply_demand"],
    ),
}


def _macro_indicators(args: Dict[str, Any]) -> Dict[str, Any]:
    indicator = str(args.get("indicator") or "pmi").strip().lower()
    spec = _MACRO_DATASETS.get(indicator)
    if spec is None:
        raise ValueError(
            "indicator 只能是 gdp、cpi、pmi、money_supply 或 retail"
        )
    fn_name, sort_field, categories = spec
    frame = getattr(_akshare(), fn_name)()
    rows = _records(
        frame,
        limit=int(args.get("limit") or 6),
        sort_field=sort_field,
    )
    return {
        "research_categories": categories,
        "subject_id": f"CHN:{indicator}",
        "indicator": indicator,
        "records": rows,
        "source_uri": "https://data.eastmoney.com/center/macro.html",
        "source_name": "东方财富中国宏观数据",
        "record_count": len(rows),
    }


def _industry_supply_demand(args: Dict[str, Any]) -> Dict[str, Any]:
    dataset = str(args.get("dataset") or "pmi").strip().lower()
    if dataset in {"pmi", "retail"}:
        return _macro_indicators({
            "indicator": dataset,
            "limit": args.get("limit") or 8,
        })
    if dataset != "futures_inventory":
        raise ValueError("dataset 只能是 pmi、retail 或 futures_inventory")
    contract = str(args.get("contract") or "").strip()
    if not contract:
        raise ValueError(
            "futures_inventory 需要 contract（例如 a、cu、al、rb、i、sc）"
        )
    frame = _akshare().futures_inventory_em(symbol=contract)
    rows = _records(
        frame,
        limit=int(args.get("limit") or 12),
        sort_field="日期",
    )
    return {
        "research_categories": ["industry", "supply_demand"],
        "subject_id": f"futures:{contract}",
        "dataset": dataset,
        "contract": contract,
        "records": rows,
        "source_uri": "https://data.eastmoney.com/ifdata/kcsj.html",
        "source_name": "东方财富期货库存",
        "record_count": len(rows),
    }


_SYM = {
    "symbol": {
        "type": "string",
        "description": "A/H 股代码，例如 600519.SH、300750.SZ、00700.HK",
    },
}

_TOOLS: Dict[
    str,
    Tuple[str, Dict[str, Any], List[str], Callable[[Dict[str, Any]], Dict[str, Any]]],
] = {
    "china_financial_statements": (
        "读取 A/H 股结构化利润表、资产负债表或现金流量表；用于基本面、盈利质量和偿债能力研究。",
        {
            **_SYM,
            "statement": {
                "type": "string",
                "enum": ["income", "balance", "cash_flow"],
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 12},
        },
        ["symbol"],
        _financial_statements,
    ),
    "china_company_news": (
        "读取 A 股个股最新财经新闻与事件催化剂，返回标题、正文摘要、发布时间和来源链接。",
        {**_SYM, "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
        ["symbol"],
        _company_news,
    ),
    "china_macro_indicators": (
        "读取中国 GDP、CPI、PMI、货币供应量或社零数据，用于宏观与流动性研究。",
        {
            "indicator": {
                "type": "string",
                "enum": ["gdp", "cpi", "pmi", "money_supply", "retail"],
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        ["indicator"],
        _macro_indicators,
    ),
    "china_industry_supply_demand": (
        "读取制造业 PMI、消费需求或商品期货库存，辅助判断行业景气、库存与供需变化。",
        {
            "dataset": {
                "type": "string",
                "enum": ["pmi", "retail", "futures_inventory"],
            },
            "contract": {
                "type": "string",
                "description": "期货品种代码，例如 a、cu、al、rb、i、sc",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        ["dataset"],
        _industry_supply_demand,
    ),
}


def _handle(req: Dict[str, Any]) -> None:
    method = str(req.get("method") or "")
    req_id = req.get("id")
    params = req.get("params") or {}
    if method == "initialize":
        _ok(req_id, {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "aiworld-china-market-research", "version": "1.0.0"},
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
            _error_content(req_id, f"unknown_tool:{name}")
            return
        try:
            result = entry[3](params.get("arguments") or {})
        except Exception as exc:  # noqa: BLE001
            _error_content(req_id, str(exc))
            return
        _ok(req_id, {
            "content": [{"type": "text", "text": f"{name} 读取成功"}],
            "structuredContent": {"fetched_at": time.time(), **result},
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
