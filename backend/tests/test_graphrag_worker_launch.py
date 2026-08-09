from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.platform.knowledge.document_ir_exporter import GraphRagInputManifest
from app.platform.knowledge.graphrag_runner import GraphRagRunner


@pytest.mark.skipif(os.name == "nt", reason="Linux venv symlink regression")
def test_isolated_worker_preserves_venv_python_symlink(tmp_path, monkeypatch):
    base_python = tmp_path / "base-python"
    base_python.write_text("base", encoding="utf-8")
    venv_python = tmp_path / "venv-python"
    venv_python.symlink_to(base_python)

    artifact_root = tmp_path / "artifacts"
    input_dir = artifact_root / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "input_manifest.json").write_text("{}", encoding="utf-8")
    manifest = GraphRagInputManifest(
        schema_version="course-graphrag-input/1.0",
        course_id=1,
        input_content_hash="input-hash",
        documents=(),
    )
    captured: dict[str, object] = {}

    def fake_run(arguments, **kwargs):
        captured["python"] = arguments[0]
        captured["environment"] = kwargs["env"]
        result_path = Path(arguments[arguments.index("--result") + 1])
        result_path.write_text(json.dumps({
            "input_content_hash": manifest.input_content_hash,
            "entities": [],
            "relationships": [],
            "text_units": [],
            "documents": [],
            "warnings": [],
            "estimated_input_tokens": 0,
            "estimated_max_cost": 0,
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(settings, "GRAPHRAG_WORKER_PYTHON", str(venv_python))
    monkeypatch.setattr(settings, "GRAPHRAG_MAX_INPUT_TOKENS", 123)
    monkeypatch.setattr(settings, "GRAPHRAG_MAX_ESTIMATED_COST_USD", 0.7)
    monkeypatch.setattr(
        "app.platform.knowledge.graphrag_runner.subprocess.run", fake_run
    )

    GraphRagRunner._run_isolated_worker(
        manifest=manifest,
        artifact_root=artifact_root,
    )

    assert captured["python"] == os.path.abspath(venv_python)
    assert captured["python"] != str(base_python)
    environment = captured["environment"]
    assert environment["GRAPHRAG_MAX_INPUT_TOKENS"] == "123"
    assert environment["GRAPHRAG_MAX_ESTIMATED_COST_USD"] == "0.7"
