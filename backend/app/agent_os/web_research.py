"""受控网页研究能力。

网页研究是 OS 的通用能力，不属于任何场景包。默认拒绝任意站点；部署者
必须显式配置允许的域名。返回值始终包含来源、抓取时间和内容哈希，方便
场景结算层把外部事实和模型推断区分开。
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_ALLOWED_HOSTS = {
    "arxiv.org", "www.arxiv.org", "pubmed.ncbi.nlm.nih.gov", "europepmc.org",
    "www.nature.com", "www.science.org", "www.nobelprize.org",
    "clinicaltrials.gov", "pubchem.ncbi.nlm.nih.gov", "www.sec.gov",
    "sec.gov", "github.com", "raw.githubusercontent.com",
}


def allowed_hosts() -> set[str]:
    configured = {
        item.strip().lower()
        for item in os.getenv("AIWORLD_WEB_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    }
    return configured or set(DEFAULT_ALLOWED_HOSTS)


def validate_url(url: str, hosts: Optional[Iterable[str]] = None) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("only_https_urls_are_allowed")
    host = parsed.hostname.lower()
    permitted = {str(item).lower().lstrip(".") for item in (hosts or allowed_hosts())}
    if host not in permitted and not any(host.endswith("." + item) for item in permitted):
        raise ValueError(f"url_host_not_allowed:{host}")
    return value


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "nav", "footer"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() in self._SKIP:
            self._skip += 1
        elif tag.lower() in {"p", "div", "li", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = re.sub(r"\s+", " ", data).strip()
            if text:
                self.parts.append(text)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", " ".join(self.parts)).strip()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise ValueError("redirect_not_allowed")


def open_allowed(request: Request, timeout: float):
    """打开单一白名单 URL，禁止 urllib 自动跟随到未审计域名。"""
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


@dataclass
class WebResearchClient:
    timeout_sec: float = 15.0
    max_bytes: int = 1_000_000
    hosts: Optional[Iterable[str]] = None

    def fetch(self, url: str) -> Dict[str, Any]:
        safe_url = validate_url(url, self.hosts)
        request = Request(
            safe_url,
            headers={
                "Accept": "text/html,application/xhtml+xml,text/plain",
                "User-Agent": "TraceArena-WebResearch/1.0 (+auditable-agent-world)",
            },
        )
        with open_allowed(request, timeout=max(2.0, min(60.0, self.timeout_sec))) as response:
            validate_url(response.geturl(), self.hosts)
            raw = response.read(self.max_bytes + 1)
            if len(raw) > self.max_bytes:
                raise ValueError("response_too_large")
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
        decoded = raw.decode(charset, errors="replace")
        if "html" in content_type:
            parser = _TextExtractor()
            parser.feed(decoded)
            text = parser.text()
        else:
            text = decoded.strip()
        return {
            "source_uri": safe_url,
            "fetched_at": time.time(),
            "source_hash": hashlib.sha256(raw).hexdigest(),
            "content_type": content_type,
            "text": text,
        }

    def search(self, query: str, *, limit: int = 5) -> Dict[str, Any]:
        """调用部署者配置的 JSON 搜索端点；没有配置时明确返回未配置。

        不偷偷绑定某一家搜索引擎。端点需要接受 ``q`` 和 ``limit`` 参数，
        返回 ``[{title,url,snippet}]`` 或 ``{"results": [...]}``。
        """
        endpoint = os.getenv("AIWORLD_WEB_SEARCH_ENDPOINT", "").strip()
        if not endpoint:
            return {"query": query, "results": [], "error": "search_endpoint_not_configured"}
        safe_endpoint = validate_url(endpoint, self.hosts)
        from urllib.parse import urlencode
        url = safe_endpoint + ("&" if "?" in safe_endpoint else "?") + urlencode({"q": query, "limit": max(1, min(20, int(limit)))})
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "TraceArena-WebResearch/1.0"})
        with open_allowed(request, timeout=max(2.0, min(30.0, self.timeout_sec))) as response:
            validate_url(response.geturl(), self.hosts)
            raw = response.read(self.max_bytes + 1)
            if len(raw) > self.max_bytes:
                raise ValueError("response_too_large")
            import json
            data = json.loads(raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
        results = data.get("results", data) if isinstance(data, dict) else data
        return {
            "query": query,
            "results": list(results or [])[: max(1, min(20, int(limit)))],
            "source_uri": safe_endpoint,
            "fetched_at": time.time(),
            "source_hash": hashlib.sha256(raw).hexdigest(),
        }
