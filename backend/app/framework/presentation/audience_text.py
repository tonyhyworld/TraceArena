"""观众文本净化。

内部 ID 可以存在于协议、账本和审计数据中，但不得进入角色独白、导演旁白
和其他面向观众的自然语言字段。
"""
from __future__ import annotations

import re
from typing import Dict, Optional


_GENERIC_LABELS = {
    "action_points": "行动余力",
    "risk_accumulation": "风险积累",
    "core_value": "关键程度",
    "core": "关键程度",
    "value": "价值",
    "stability": "稳定程度",
    "exposure": "暴露程度",
    "uncertainty": "不确定程度",
}


def audience_term_labels(
    terminology: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """构造供自然语言使用的术语表，并补齐常见指标短别名。"""
    labels = dict(_GENERIC_LABELS)
    labels.update(terminology or {})
    for key, label in list((terminology or {}).items()):
        if key.startswith("metric_"):
            short = key[len("metric_"):]
            labels.setdefault(short, label)
    return labels


def audience_label(
    key: str,
    terminology: Optional[Dict[str, str]] = None,
) -> str:
    """把单个内部键转换成观众可读名称。"""
    return audience_term_labels(terminology).get(str(key), str(key))


# 内部账本/协议 ID 的已知前缀（引擎与 Harness 自己生成的标识符命名空间）。
_INTERNAL_ID_PREFIXES = (
    "act", "eval", "delta", "seq", "mderiv", "mcp", "skill", "obs",
    "run", "htrace", "policy", "perception", "sandbox", "event",
    "activity", "settlement", "capability", "tool", "inline",
)
_INTERNAL_ID_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(_INTERNAL_ID_PREFIXES) + r")"
    r"[_:][A-Za-z0-9_:.-]+(?![A-Za-z0-9_])"
)


def sanitize_audience_text(
    text: object,
    terminology: Optional[Dict[str, str]] = None,
) -> str:
    """翻译已知内部词并删除已知内部 ID，返回自然文本（保留普通英文）。"""
    result = str(text or "")
    if not result:
        return ""

    labels = audience_term_labels(terminology)
    for key, label in sorted(labels.items(), key=lambda item: len(item[0]), reverse=True):
        result = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])",
            label,
            result,
        )

    # 只删已知命名空间的内部 ID（含括号包裹形式），其余英文一律保留。
    # 净化原则：**只删认识的内部 ID，绝不删普通英文**——股票代码（600036.SH）、
    # 数据来源（Yahoo Finance）、行业缩写（ETF/PE）都是正文内容。
    # 此前的"删除一切英文 token"兜底正则曾把代码后缀、来源名、证据编号全部
    # 剥掉，导致演绎与解释链大面积乱码，故废除。
    result = re.sub(
        r"[（(]\s*" + _INTERNAL_ID_RE.pattern + r"\s*[）)]", "", result
    )
    result = _INTERNAL_ID_RE.sub("", result)
    # snake_case 协议词（risk_control / target_not_found / provider_id …）
    # 也是内部词汇，删除。股票代码（600036.SH）数字开头、普通英文
    # （Yahoo Finance / ETF / http）无下划线，均不受影响。
    result = re.sub(
        r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+"
        r"(?![A-Za-z0-9_])",
        "",
        result,
    )
    # 删除 ID 被移除后留下的空赋值和破碎标点。
    result = re.sub(r"(?<=[\u4e00-\u9fff])\s*[:=]\s*(?=[，。；、]|$)", "", result)
    result = re.sub(r"\s*([，。；！？、])\s*", r"\1", result)
    result = re.sub(r"[，,]{2,}", "，", result)
    result = re.sub(r"[；;]{2,}", "；", result)
    result = re.sub(r"[。]{2,}", "。", result)
    result = re.sub(r"([，；、])(?=[。！？])", "", result)
    result = re.sub(r"\s+", " ", result)
    return result.strip(" ，,；;：:")


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_EN_PUBLIC_TERMS = {
    "稳健基金说": "Stable fund says",
    "成长基金说": "Growth fund says",
    "稳健基金": "Stable fund",
    "成长基金": "Growth fund",
    "导演": "Director",
    "系统": "System",
    "每位": "each",
    "两位": "two",
    "资深投资经理": "experienced investment manager",
    "投资经理": "investment manager",
    "投资策略": "investment strategy",
    "投资判断": "investment thesis",
    "验证证据": "verified evidence",
    "可验证证据": "verifiable evidence",
    "获得": "obtain",
    "提交了": " submitted ",
    "提交": "submitted",
    "等待": "wait",
    "进入": "enter",
    "开盘": "market open",
    "风险": "risk",
    "控制": "control",
    "价值": "value",
    "估值": "valuation",
    "股息率": "dividend yield",
    "资产负债表": "balance sheet",
    "利润表": "income statement",
    "现金流": "cash flow",
    "待入场": "awaiting entry",
    "演出缓冲补充中": "filling presentation buffer",
    "回合": "cycle",
    "已完成": "completed",
    "本回合结算结果": "Settlement result this cycle",
    "风格自检与该投资经理的既定策略不一致": (
        "Style self-check is inconsistent with this manager's stated strategy"
    ),
    "投资计划状态不是允许的标准状态": (
        "Investment plan status is not an allowed standard status"
    ),
    "可用": "Allowed",
    "外部证据": "External evidence",
    "行情": "market data",
    "已接入观测": "connected observations",
    "这些观测支撑本回合结算": (
        "These observations support this cycle's settlement"
    ),
    "未验证项不会当作成交依据": (
        "Unverified items are not used as fill evidence"
    ),
    "结算": "settlement",
    "世界已记录": "World event recorded",
    "中国石化": "Sinopec",
    "工商银行": "ICBC",
    "农业银行": "Agricultural Bank of China",
    "招商银行": "China Merchants Bank",
    "京东方": "BOE Technology",
    "长信科技": "Changxin Technology",
    "全志科技": "Allwinner Technology",
    "华天科技": "Huatian Technology",
    "东方日升": "Risen Energy",
    "易成新能": "Yicheng New Energy",
    "腾讯控股": "Tencent",
}


def contains_cjk(text: object) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def enforce_english_audience_text(
    text: object,
    *,
    fallback: str = "",
) -> str:
    """Best-effort public English guard for UI-facing fields.

    This is intentionally conservative: it translates common scenario/public
    terms, normalizes Chinese punctuation, then removes any remaining CJK glyphs
    so an en-US session never renders mixed-language public narration.
    """
    result = str(text or "")
    if not result:
        return fallback
    for zh, en in sorted(
        _EN_PUBLIC_TERMS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        result = result.replace(zh, en)
    result = (
        result.replace("：", ": ")
        .replace("；", "; ")
        .replace("，", ", ")
        .replace("。", ". ")
        .replace("、", ", ")
        .replace("“", '"')
        .replace("”", '"')
        .replace("（", "(")
        .replace("）", ")")
    )
    result = _CJK_RE.sub("", result)
    result = re.sub(r"\s+([,.;:!?])", r"\1", result)
    result = re.sub(r"\s+", " ", result).strip(" ,.;:")
    return result or fallback
