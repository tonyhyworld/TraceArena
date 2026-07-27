"""受限浏览器会话抽象。

默认使用无 JavaScript 的 HTTP 会话，保证开源安装无需额外浏览器依赖；部署者
可安装 Playwright 后替换为同一接口的 JS 实现。会话只允许白名单 HTTPS 域名，
并把导航和点击记录为可审计操作。
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from app.agent_os.web_research import WebResearchClient, open_allowed, validate_url


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[Dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        data = dict(attrs)
        href, text = data.get("href"), data.get("title", "")
        if href:
            self.links.append({"href": href, "label": text})


@dataclass
class BrowserSession:
    client: WebResearchClient = field(default_factory=WebResearchClient)
    session_id: str = field(default_factory=lambda: f"browser_{uuid.uuid4().hex[:12]}")
    current_url: str = ""
    current_text: str = ""
    links: List[Dict[str, str]] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)

    def navigate(self, url: str) -> Dict[str, Any]:
        safe = validate_url(url, self.client.hosts)
        page = self.client.fetch(safe)
        parser = _Links()
        # 重新抓取 HTML 仅用于获得 href；正文仍以 web_research 返回为准。
        from urllib.request import Request
        with open_allowed(Request(safe, headers={"User-Agent": "TraceArena-Browser/1.0"}), timeout=self.client.timeout_sec) as response:
            validate_url(response.geturl(), self.client.hosts)
            raw = response.read(self.client.max_bytes)
        parser.feed(raw.decode("utf-8", errors="replace"))
        self.current_url, self.current_text = safe, page.get("text", "")
        self.links = [{"id": str(i + 1), "href": urljoin(safe, item["href"]), "label": item.get("label", "")} for i, item in enumerate(parser.links[:100])]
        event = {"operation": "navigate", "url": safe, "source_hash": page.get("source_hash"), "link_count": len(self.links)}
        self.history.append(event)
        return {"session_id": self.session_id, "url": self.current_url, "text": self.current_text, "links": self.links, "event": event}

    def click(self, link_id: str) -> Dict[str, Any]:
        item = next((x for x in self.links if x.get("id") == str(link_id)), None)
        if item is None:
            raise ValueError("link_not_found")
        return self.navigate(item["href"])

    def extract(self, pattern: str = "") -> Dict[str, Any]:
        text = self.current_text
        if pattern:
            matches = re.findall(pattern, text, flags=re.IGNORECASE)
            return {"session_id": self.session_id, "url": self.current_url, "matches": matches[:100]}
        return {"session_id": self.session_id, "url": self.current_url, "text": text}
