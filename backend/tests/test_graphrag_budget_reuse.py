"""Unit tests: graphrag artifact-completeness gate used to avoid wasted rebuilds."""
import pandas as pd

from app.models.knowledge_bundle_model import GraphRagRun
from app.services.knowledge_bundle_service import knowledge_bundle_service


def _run_with_root(root) -> GraphRagRun:
    return GraphRagRun(
        course_id=1,
        run_id="grr_test",
        status="FAILED",
        artifact_root_uri=str(root),
        input_content_hash="h",
        effective_config_hash="c",
        regeneration_reason="r",
    )


def _write_parquet(output_dir, name, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_parquet(output_dir / f"{name}.parquet", index=False)


def test_has_complete_artifacts_true(tmp_path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True)
    for name in ("documents", "text_units", "entities", "relationships"):
        _write_parquet(output_dir, name, [{"id": "x", "title": "t"}])
    run = _run_with_root(tmp_path)
    assert knowledge_bundle_service._has_complete_graph_artifacts(run) is True


def test_has_complete_artifacts_false_when_entities_empty(tmp_path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True)
    _write_parquet(output_dir, "documents", [{"id": "x", "title": "t"}])
    _write_parquet(output_dir, "text_units", [{"id": "tu"}])
    # entities / relationships empty -> must NOT be treated as reusable
    _write_parquet(output_dir, "entities", [])
    _write_parquet(output_dir, "relationships", [])
    run = _run_with_root(tmp_path)
    assert knowledge_bundle_service._has_complete_graph_artifacts(run) is False


def test_has_complete_artifacts_false_when_missing(tmp_path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True)
    _write_parquet(output_dir, "documents", [{"id": "x", "title": "t"}])
    _write_parquet(output_dir, "text_units", [{"id": "tu"}])
    _write_parquet(output_dir, "entities", [{"id": "e"}])
    # relationships parquet missing
    run = _run_with_root(tmp_path)
    assert knowledge_bundle_service._has_complete_graph_artifacts(run) is False


def test_has_complete_artifacts_false_without_root(tmp_path) -> None:
    run = _run_with_root(tmp_path / "nonexistent")
    assert knowledge_bundle_service._has_complete_graph_artifacts(run) is False
