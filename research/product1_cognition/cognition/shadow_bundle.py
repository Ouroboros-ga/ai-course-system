"""Preflight and run a governed, read-only KG-MEST Shadow bundle.

The bundle is an offline hand-off format, not a production API.  It combines
the required governance assertions with plain exported graph and event records,
then emits a report without raw student IDs or original event payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from benchmarks.shadow_gate import ShadowGateInput, evaluate_shadow_gate

from .shadow_pipeline import ReadOnlyShadowResult, run_read_only_shadow


BUNDLE_SCHEMA_VERSION = "kg-mest-read-only-shadow-bundle/1.0"
BUNDLE_ARTIFACT_NAMES = ("graph_nodes", "graph_relations", "review_decisions", "learning_events")


@dataclass(frozen=True)
class ShadowBundleRunResult:
    status: str
    report: Mapping[str, Any]


def run_shadow_bundle(
    *,
    manifest: Mapping[str, Any],
    graph_nodes: list[Mapping[str, Any]],
    graph_relations: list[Mapping[str, Any]],
    review_decisions: list[Mapping[str, Any]],
    learning_events: list[Mapping[str, Any]],
) -> ShadowBundleRunResult:
    """Preflight governance declarations, then execute a no-write shadow run."""
    manifest_errors = _validate_manifest(
        manifest,
        graph_nodes=graph_nodes,
        graph_relations=graph_relations,
        review_decisions=review_decisions,
        learning_events=learning_events,
    )
    if manifest_errors:
        return ShadowBundleRunResult("rejected", {"status": "rejected", "error_codes": manifest_errors})
    gate = evaluate_shadow_gate(_gate_input(manifest["shadow_gate"]))
    if gate["status"] != "ready_for_shadow":
        return ShadowBundleRunResult("not_ready", {
            "status": "not_ready", "error_codes": gate["error_codes"], "promotion": gate["promotion"],
        })
    source_scope = manifest["source_scope"]
    result = run_read_only_shadow(
        course_key=str(manifest["course_key"]), graph_snapshot_id=str(manifest["graph_snapshot_id"]),
        graph_nodes=graph_nodes, graph_relations=graph_relations, review_decisions=review_decisions,
        source_student_id=int(source_scope["student_id"]), source_course_id=int(source_scope["course_id"]),
        student_key=str(manifest["student_key"]), data_version=str(manifest["data_version"]),
        learning_events=learning_events,
    )
    return ShadowBundleRunResult(result.status, _safe_report(manifest, result))


def _validate_manifest(
    manifest: Mapping[str, Any], *, graph_nodes: list[Mapping[str, Any]],
    graph_relations: list[Mapping[str, Any]], review_decisions: list[Mapping[str, Any]],
    learning_events: list[Mapping[str, Any]],
) -> tuple[str, ...]:
    errors: set[str] = set()
    if manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        errors.add("SHADOW_BUNDLE_SCHEMA_VERSION_INVALID")
    if manifest.get("data_classification") != "protected_pseudonymized":
        errors.add("SHADOW_BUNDLE_DATA_CLASSIFICATION_REQUIRED")
    for field in ("course_key", "graph_snapshot_id", "student_key", "data_version"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            errors.add(f"SHADOW_BUNDLE_{field.upper()}_MISSING")
    source_scope = manifest.get("source_scope")
    if not isinstance(source_scope, Mapping) or any(
        isinstance(source_scope.get(field), bool) or not isinstance(source_scope.get(field), int)
        for field in ("student_id", "course_id")
    ):
        errors.add("SHADOW_BUNDLE_SOURCE_SCOPE_INVALID")
    elif manifest.get("student_key") == str(source_scope["student_id"]):
        errors.add("SHADOW_BUNDLE_STUDENT_KEY_NOT_PSEUDONYMIZED")
    gate = manifest.get("shadow_gate")
    if not isinstance(gate, Mapping):
        errors.add("SHADOW_BUNDLE_GATE_DECLARATION_MISSING")
    elif _gate_errors(gate):
        errors.add("SHADOW_BUNDLE_GATE_DECLARATION_INVALID")
    hashes = manifest.get("artifact_sha256")
    artifacts = {
        "graph_nodes": graph_nodes,
        "graph_relations": graph_relations,
        "review_decisions": review_decisions,
        "learning_events": learning_events,
    }
    if not isinstance(hashes, Mapping) or set(hashes) != set(BUNDLE_ARTIFACT_NAMES):
        errors.add("SHADOW_BUNDLE_ARTIFACT_HASHES_REQUIRED")
    else:
        for name, artifact in artifacts.items():
            if hashes.get(name) != artifact_sha256(artifact):
                errors.add(f"SHADOW_BUNDLE_{name.upper()}_HASH_MISMATCH")
    return tuple(sorted(errors))


def artifact_sha256(value: Any) -> str:
    """Hash canonical JSON content, independent of whitespace or key order."""
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _gate_errors(gate: Mapping[str, Any]) -> bool:
    boolean_fields = (
        "research_tests_passed", "contract_ablation_passed", "graph_course_isolation_verified",
        "provider_contract_tests_passed", "append_only_audit_verified", "no_production_write_verified",
    )
    string_fields = ("graph_snapshot_status", "interaction_gold_status", "privacy_review_status")
    return any(type(gate.get(field)) is not bool for field in boolean_fields) or any(
        not isinstance(gate.get(field), str) for field in string_fields
    )


def _gate_input(gate: Mapping[str, Any]) -> ShadowGateInput:
    return ShadowGateInput(
        research_tests_passed=gate["research_tests_passed"],
        contract_ablation_passed=gate["contract_ablation_passed"],
        graph_snapshot_status=gate["graph_snapshot_status"],
        graph_course_isolation_verified=gate["graph_course_isolation_verified"],
        interaction_gold_status=gate["interaction_gold_status"],
        privacy_review_status=gate["privacy_review_status"],
        provider_contract_tests_passed=gate["provider_contract_tests_passed"],
        append_only_audit_verified=gate["append_only_audit_verified"],
        no_production_write_verified=gate["no_production_write_verified"],
    )


def _safe_report(manifest: Mapping[str, Any], result: ReadOnlyShadowResult) -> Mapping[str, Any]:
    """Keep raw source scope, event text, and payloads out of the report."""
    states = {
        concept_id: {
            "status": state.status,
            "values": dict(state.values),
            "observed_performance_score": state.observed_performance_score,
            "confidence": state.confidence,
            "evidence_refs": state.evidence_refs,
            "reason_codes": state.reason_codes,
            "confidence_reasons": state.confidence_reasons,
            "policy_versions": dict(state.policy_versions),
            "data_version": state.data_version,
        }
        for concept_id, state in sorted(result.states.items())
    }
    interactions = {
        concept_id: {
            "values": dict(state.values), "evidence_refs": state.evidence_refs,
            "reason_codes": state.reason_codes, "policy_version": state.policy_version,
            "classifier_provenance": state.classifier_provenance,
        }
        for concept_id, state in sorted(result.interactions.items())
    }
    recommendations = {
        concept_id: tuple({
            "concept_id": item.concept_id, "action_type": item.action_type, "priority": item.priority,
            "reason_codes": item.reason_codes, "evidence_refs": item.evidence_refs,
            "resource_ids": item.resource_ids, "policy_version": item.policy_version,
        } for item in items)
        for concept_id, items in sorted(result.recommendations.items())
    }
    return {
        "status": result.status,
        "course_key": manifest["course_key"],
        "graph_snapshot_id": manifest["graph_snapshot_id"],
        "data_version": manifest["data_version"],
        "error_codes": result.error_codes,
        "unmapped_event_refs": result.unmapped_event_refs,
        "states": states,
        "interactions": interactions,
        "recommendations": recommendations,
    }
