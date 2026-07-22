"""Guard the main authenticated UI against new untranslated static copy."""

from pathlib import Path
import re


ROOT = Path(__file__).parents[2]
COMPONENTS = [
    "frontend/src/auth/ProfileCenter.vue",
    "frontend/src/operator/OperatorShell.vue",
    "frontend/src/operator/Console.vue",
    "frontend/src/operator/archive/RunArchive.vue",
    "frontend/src/operator/analysis/ModelAssessment.vue",
    "frontend/src/operator/factory/DataFactory.vue",
    "frontend/src/operator/UserManagement.vue",
]
HAN = re.compile(r"[\u3400-\u9fff]")
LITERAL_ATTR = re.compile(r'(?<!:)\b(?:title|placeholder|aria-label)="([^"]*[\u3400-\u9fff][^"]*)"')


def test_authenticated_ui_has_no_bare_chinese_static_copy() -> None:
    failures = []
    for relative in COMPONENTS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        template = source.split("<script", 1)[0]
        template = re.sub(r"<!--.*?-->", "", template, flags=re.S)
        for line_no, line in enumerate(template.splitlines(), 1):
            for value in LITERAL_ATTR.findall(line):
                failures.append(f"{relative}:{line_no}: literal attribute {value!r}")
            visible = re.sub(r"{{.*?}}", "", line)
            visible = re.sub(r"<[^>]+>", "", visible).strip()
            if visible and HAN.search(visible) and not line.lstrip().startswith((":", "?")):
                failures.append(f"{relative}:{line_no}: bare text {visible!r}")
    assert not failures, "Untranslated authenticated UI copy:\n" + "\n".join(failures)
