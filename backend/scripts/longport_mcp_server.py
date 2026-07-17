#!/usr/bin/env python3
"""Longbridge / Longport 行情研究 MCP 服务（港股 / 美股 / A股，官方券商 SDK）。

用官方 longport SDK（API Key 认证），适配本项目"无头 + stdio"架构——不走官方
托管 MCP 的 OAuth 浏览器授权。凭证从**本进程环境变量**读，agent 沙箱看不到明文：
    LONGPORT_APP_KEY / LONGPORT_APP_SECRET / LONGPORT_ACCESS_TOKEN
（在 backend/.env 配置；access_token 在 https://open.longportapp.com 开发者后台生成）。

**只读研究工具，绝不含真实下单**（本项目交易由结算层模拟，不碰真实券商订单）。
标的格式：港股 700.HK，美股 AAPL.US，A股 600519.SH / 000001.SZ。
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

# ── stdio 协议隔离（关键）──
# longport SDK（Rust）会在首次取行情时把"行情配额"横幅直接打到 OS 层 stdout(fd1)，
# 污染 MCP 的 JSON-RPC 流——客户端逐行 json.loads 会在横幅行 `+------+` 上炸掉。
# 因为它是 fd 级写入（绕过 Python 的 sys.stdout），只能在 fd 级隔离：把原始
# stdout(fd1，即通往父进程的管道)复制出来专供 JSON-RPC，再把 fd1 重定向到 stderr，
# 于是 SDK 及任何库/print 的 stdout 输出都进 stderr（对父进程无害），
# JSON-RPC 独占这条干净管道。必须在任何 longport 调用之前完成。
_JSONRPC_OUT = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
os.dup2(2, 1)

_QUOTE_CTX = None
_INIT_ERROR: Optional[str] = None

# calc_indexes 默认取的实用指标（价值投资/风控关键）
_DEFAULT_INDEXES = [
    "LastDone", "ChangeRate", "PeTtmRatio", "PbRatio", "TotalMarketValue",
    "TurnoverRate", "Volume", "DividendRatioTtm", "YtdChangeRate",
    "VolumeRatio", "Amplitude",
]


def _send(payload: Dict[str, Any]) -> None:
    # 只往私有干净通道写 JSON-RPC；SDK/print 的杂输出已被隔离到 stderr。
    _JSONRPC_OUT.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    _JSONRPC_OUT.flush()


def _ok(req_id: Any, result: Dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error_content(req_id: Any, message: str) -> None:
    _ok(req_id, {"content": [{"type": "text", "text": message}], "isError": True})


def _obj_to_dict(obj: Any, *, _depth: int = 0, _seen: Optional[set] = None) -> Any:
    """把 longport SDK 的原生对象转成可 JSON 化的普通结构。

    datetime/枚举等类型有自引用类属性（如 datetime.min.min 恒等于自身），
    通用反射遍历会死循环——必须显式特判，并用深度上限 + 已访问对象集合
    做兜底防护，任何未预见的自引用结构都不会再让整个 MCP 进程炸栈。
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    if _depth > 6:
        return str(obj)
    if isinstance(obj, (list, tuple)):
        return [_obj_to_dict(x, _depth=_depth + 1, _seen=_seen) for x in obj]
    if isinstance(obj, dict):
        return {k: _obj_to_dict(v, _depth=_depth + 1, _seen=_seen)
                for k, v in obj.items()}

    seen = _seen if _seen is not None else set()
    if id(obj) in seen:
        return str(obj)
    seen = seen | {id(obj)}

    # PyO3 枚举（TradeStatus.Normal / TradeSession.Intraday / Period.Day ...）：
    # 恒无 __dict__，且 str() 恒为 "类型名.成员名"——比穷举类型名后缀更通用，
    # 也修正了会漏判某些枚举类型、进而落回反射踩自引用类属性的问题。
    if not hasattr(obj, "__dict__"):
        text = str(obj)
        if text.startswith(type(obj).__name__ + "."):
            return text

    out: Dict[str, Any] = {}
    for attr in dir(obj):
        if attr.startswith("_"):
            continue
        try:
            value = getattr(obj, attr)
        except Exception:
            continue
        if callable(value):
            continue
        out[attr] = _obj_to_dict(value, _depth=_depth + 1, _seen=seen)
    return out or str(obj)


def _get_ctx():
    global _QUOTE_CTX, _INIT_ERROR
    if _QUOTE_CTX is not None:
        return _QUOTE_CTX
    if _INIT_ERROR is not None:
        raise RuntimeError(_INIT_ERROR)
    try:
        from longport.openapi import Config, QuoteContext

        _QUOTE_CTX = QuoteContext(Config.from_apikey_env())
        return _QUOTE_CTX
    except Exception as exc:  # noqa: BLE001
        _INIT_ERROR = (
            "Longport 初始化失败：请确认 backend/.env 已配置 "
            "LONGPORT_APP_KEY / LONGPORT_APP_SECRET / LONGPORT_ACCESS_TOKEN "
            f"（access_token 在长桥开发者后台生成）。原始错误：{exc}"
        )
        raise RuntimeError(_INIT_ERROR)


def _symbols(args: Dict[str, Any]) -> List[str]:
    raw = args.get("symbols") or ([args["symbol"]] if args.get("symbol") else [])
    syms = [str(s).strip() for s in raw if str(s).strip()]
    if not syms:
        raise ValueError("需要 symbols（如 ['700.HK','600519.SH']）")
    return syms


def _one_symbol(args: Dict[str, Any]) -> str:
    sym = str(args.get("symbol") or "").strip()
    if not sym:
        raise ValueError("需要 symbol（如 '600519.SH'）")
    return sym


def _name_from_static_row(row: Dict[str, Any]) -> str:
    for key in ("name_cn", "name_zh", "name", "name_en", "display_name"):
        val = row.get(key)
        if val not in (None, ""):
            return str(val).strip()
    return ""


def _call_quote(args):
    """实时报价；顺带挂上证券中文名（来自 static_info），供观众端持仓展示。"""
    syms = _symbols(args)
    quotes = _obj_to_dict(_get_ctx().quote(syms))
    if not isinstance(quotes, list):
        quotes = list(quotes) if quotes else []

    name_by_symbol: Dict[str, str] = {}
    try:
        static_rows = _obj_to_dict(_get_ctx().static_info(syms))
        if not isinstance(static_rows, list):
            static_rows = []
        for row in static_rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            name = _name_from_static_row(row)
            if sym and name:
                name_by_symbol[sym] = name
    except Exception:
        # 名称是展示增强；行情本身仍可用。
        pass

    enriched = []
    for row in quotes:
        if not isinstance(row, dict):
            enriched.append(row)
            continue
        item = dict(row)
        sym = str(item.get("symbol") or "").strip()
        if sym and name_by_symbol.get(sym):
            item.setdefault("name", name_by_symbol[sym])
            item.setdefault("name_cn", name_by_symbol[sym])
        enriched.append(item)

    return {
        "symbols": syms,
        "quotes": enriched,
        "names": name_by_symbol,
    }


def _call_calc_indexes(args):
    from longport.openapi import CalcIndex

    syms = _symbols(args)
    names = [str(n) for n in (args.get("indexes") or _DEFAULT_INDEXES)]
    indexes = [getattr(CalcIndex, n) for n in names if hasattr(CalcIndex, n)]
    if not indexes:
        indexes = [getattr(CalcIndex, n) for n in _DEFAULT_INDEXES]
        names = list(_DEFAULT_INDEXES)
    data = _get_ctx().calc_indexes(syms, indexes)
    return {"symbols": syms, "indexes": names, "data": _obj_to_dict(data)}


def _call_static_info(args):
    syms = _symbols(args)
    return {"symbols": syms, "static_info": _obj_to_dict(_get_ctx().static_info(syms))}


def _call_candlesticks(args):
    from longport.openapi import AdjustType, Period

    sym = _one_symbol(args)
    period = getattr(Period, str(args.get("period") or "Day"), Period.Day)
    count = max(1, min(1000, int(args.get("count") or 60)))
    bars = _get_ctx().candlesticks(sym, period, count, AdjustType.ForwardAdjust)
    return {"symbol": sym, "period": str(args.get("period") or "Day"),
            "candlesticks": _obj_to_dict(bars)}


def _call_filings(args):
    sym = _one_symbol(args)
    return {"symbol": sym, "filings": _obj_to_dict(_get_ctx().filings(sym))}


def _call_capital_flow(args):
    sym = _one_symbol(args)
    return {"symbol": sym, "capital_flow": _obj_to_dict(_get_ctx().capital_flow(sym))}


def _call_capital_distribution(args):
    sym = _one_symbol(args)
    return {"symbol": sym,
            "capital_distribution": _obj_to_dict(_get_ctx().capital_distribution(sym))}


def _call_depth(args):
    sym = _one_symbol(args)
    return {"symbol": sym, "depth": _obj_to_dict(_get_ctx().depth(sym))}


def _call_intraday(args):
    sym = _one_symbol(args)
    return {"symbol": sym, "intraday": _obj_to_dict(_get_ctx().intraday(sym))}


def _call_trades(args):
    sym = _one_symbol(args)
    count = max(1, min(1000, int(args.get("count") or 20)))
    return {"symbol": sym, "trades": _obj_to_dict(_get_ctx().trades(sym, count))}


_SYM = {"symbol": {"type": "string"}}
_SYMS = {"symbols": {"type": "array", "items": {"type": "string"}}, "symbol": {"type": "string"}}
_TOOLS = {
    "longport_quote": ("实时报价（港/美/A股，官方券商源）。symbols=['700.HK','600519.SH']", _SYMS, ["symbols"], _call_quote),
    "longport_calc_indexes": ("一站式估值/技术指标：PE、PB、总市值、涨跌幅、换手率、股息率、量比、振幅等。symbols + 可选 indexes（指标名数组，缺省取常用一组）", {**_SYMS, "indexes": {"type": "array", "items": {"type": "string"}}}, ["symbols"], _call_calc_indexes),
    "longport_static_info": ("证券基础信息（名称、交易所、每手股数、货币等）。symbols", _SYMS, ["symbols"], _call_static_info),
    "longport_candlesticks": ("历史 K 线。symbol、period(Day/Week/Month/Min_5/Min_60 等)、count", {**_SYM, "period": {"type": "string"}, "count": {"type": "number"}}, ["symbol"], _call_candlesticks),
    "longport_filings": ("公司财报与公告列表（基本面/事件研究）。symbol", _SYM, ["symbol"], _call_filings),
    "longport_capital_flow": ("资金流入流出时序。symbol", _SYM, ["symbol"], _call_capital_flow),
    "longport_capital_distribution": ("资金分布（大/中/小单净流入）。symbol", _SYM, ["symbol"], _call_capital_distribution),
    "longport_depth": ("盘口买卖档。symbol", _SYM, ["symbol"], _call_depth),
    "longport_intraday": ("当日分时行情。symbol", _SYM, ["symbol"], _call_intraday),
    "longport_trades": ("逐笔成交。symbol、count(默认20)", {**_SYM, "count": {"type": "number"}}, ["symbol"], _call_trades),
}


def _handle(req: Dict[str, Any]) -> None:
    method = str(req.get("method") or "")
    req_id = req.get("id")
    params = req.get("params") or {}
    if method == "initialize":
        _ok(req_id, {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "aiworld-longport", "version": "1.1.0"},
        })
    elif method == "notifications/initialized":
        return
    elif method == "tools/list":
        _ok(req_id, {"tools": [
            {"name": name, "description": desc,
             "inputSchema": {"type": "object", "properties": props, "required": required}}
            for name, (desc, props, required, _fn) in _TOOLS.items()
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
        _send({"jsonrpc": "2.0", "id": req_id,
               "error": {"code": -32601, "message": f"Method not found: {method}"}})


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
