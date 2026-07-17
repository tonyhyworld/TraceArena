"""
模块5:脱敏与字段白名单(Sanitizer)

出厂安全闸。导出的每一行(机器视图+决策卡)在落盘前必须过此闸,结构性
排除三类不该进训练集的东西:
  1. 凭证:API key / token(sk-xxx、Bearer、各家 *_API_KEY 的值)
  2. 身份:MINIMAX_GROUP_ID / user_id / 用户名等租户身份
  3. 领域敏感:场景包可声明脱敏钩子(如投资场景把真实日期打乱、代码脱敏)

设计:
  - 值扫描(正则):抓 sk-/Bearer/长 hex token 等凭证形态,替换为 [REDACTED];
  - 键黑名单:某些字段名(api_key/token/group_id/user_id)整条剔除;
  - 领域钩子:场景包训练数据配置可声明 sanitize 规则,
    这里留接口(replace/shift),默认不启用;
  - 审计:返回命中计数,供 packager 写进数据卡"已脱敏 N 处",可核查。

纪律:宁可误伤(多打码)不可漏放。凭证进训练集是不可逆的泄露。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

REDACTED = "[REDACTED]"

# ── 凭证值形态(命中即打码)──
_CREDENTIAL_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),            # OpenAI/DeepSeek 风格
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{16,}"),    # Bearer token
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"\b[a-fA-F0-9]{32,}\b"),              # 长 hex(key/hash)
]

# ── 键黑名单(字段名命中 → 整条剔除,不管值)──
_KEY_BLACKLIST = {
    "api_key", "apikey", "api_key_override", "token", "access_token",
    "secret", "password", "passwd", "pwd",
    "group_id", "minimax_group_id", "user_id", "username", "owner",
    "authorization",
}


@dataclass
class SanitizeReport:
    credential_hits: int = 0     # 打码的凭证值数
    dropped_keys: int = 0        # 剔除的黑名单字段数
    domain_transforms: int = 0   # 领域钩子改写数
    samples_scanned: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "credential_hits": self.credential_hits,
            "dropped_keys": self.dropped_keys,
            "domain_transforms": self.domain_transforms,
            "samples_scanned": self.samples_scanned,
        }


def _scan_str(text: str, report: SanitizeReport) -> str:
    if not text:
        return text
    out = text
    for pat in _CREDENTIAL_PATTERNS:
        out, n = pat.subn(REDACTED, out)
        report.credential_hits += n
    return out


def _sanitize_value(value: Any, report: SanitizeReport, hooks: List) -> Any:
    if isinstance(value, str):
        v = _scan_str(value, report)
        for hook in hooks:
            v2 = hook(v)
            if v2 != v:
                report.domain_transforms += 1
                v = v2
        return v
    if isinstance(value, list):
        return [_sanitize_value(x, report, hooks) for x in value]
    if isinstance(value, dict):
        return _sanitize_dict(value, report, hooks)
    return value


def _sanitize_dict(d: Dict[str, Any], report: SanitizeReport, hooks: List) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if str(k).lower() in _KEY_BLACKLIST:
            report.dropped_keys += 1
            continue
        out[k] = _sanitize_value(v, report, hooks)
    return out


def sanitize_sample(
    sample: Dict[str, Any],
    report: SanitizeReport,
    domain_hooks: List = None,
) -> Dict[str, Any]:
    """脱敏一条样本(机器视图或决策卡通用)。就地不改,返回新 dict。"""
    report.samples_scanned += 1
    return _sanitize_dict(sample, report, domain_hooks or [])


def build_domain_hooks(rules: List[Dict[str, Any]]) -> List:
    """把场景包声明的领域脱敏规则编译成钩子函数。

    支持的规则(确定性,不用 eval):
      {kind: replace, pattern: <regex>, to: <str>}  正则替换
    投资场景可用 replace 把真实日期/代码脱敏。规则由场景包提供,不硬编码。
    """
    hooks: List = []
    for rule in rules or []:
        kind = str(rule.get("kind", ""))
        if kind == "replace":
            try:
                pat = re.compile(str(rule.get("pattern", "")))
            except re.error:
                continue
            to = str(rule.get("to", REDACTED))
            hooks.append(lambda s, _p=pat, _t=to: _p.sub(_t, s))
    return hooks


def sanitize_rows(
    rows: List[Dict[str, Any]],
    domain_rules: List[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], SanitizeReport]:
    """批量脱敏。返回(脱敏后行, 审计报告)。"""
    report = SanitizeReport()
    hooks = build_domain_hooks(domain_rules or [])
    out = [sanitize_sample(r, report, hooks) for r in rows]
    return out, report
