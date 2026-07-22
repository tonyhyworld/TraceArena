import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
NOTEBOOK = (
    ROOT
    / "examples/investment_benchmark/TraceArena_Investment_Benchmark_v1.ipynb"
)


def test_colab_quickstart_is_pinned_safe_and_verifies_published_report():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    source = "\n".join(
        "".join(cell.get("source") or []) for cell in notebook["cells"]
    )
    assert 'RELEASE = "v0.1.12"' in source
    assert "investment_benchmark.py" in source
    assert "generated == published" in source
    assert 'generated["official_model_leaderboard"] is False' in source
    assert 'generated["execution_boundary"]["network"] == "disabled"' in source
    assert 'generated["execution_boundary"]["brokerage"] == "disabled"' in source
    assert "API_KEY" not in source
    assert "real orders" in source
    assert "not financial advice" in source
