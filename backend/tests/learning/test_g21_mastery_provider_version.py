"""Test: mastery provider_version is consistently two-part "1.0"."""

from app.platform.mastery.contracts import MASTERY_PROVIDER_VERSION
from app.platform.mastery.rule_baseline import RuleBasedMasteryProvider


class TestMasteryProviderVersion:
    """G2.1: provider_version must be two-part "1.0" (not three-part "1.0.0")."""

    def test_provider_version_constant_is_two_part(self):
        """The MASTERY_PROVIDER_VERSION constant must be two-part."""
        assert MASTERY_PROVIDER_VERSION == "1.0"
        assert MASTERY_PROVIDER_VERSION.count(".") == 1, (
            f"Expected exactly one dot, got {MASTERY_PROVIDER_VERSION!r}"
        )

    def test_rule_based_provider_returns_correct_version(self):
        """RuleBasedMasteryProvider.compute() result must have
        provider_version == "1.0" (two-part)."""
        provider = RuleBasedMasteryProvider()
        # Provide enough evidence for a successful computation
        metadata = {
            "evidence_dict": {
                "quiz_accuracy": [
                    {
                        "evidence_id": "ev-1",
                        "value": 0.85,
                    }
                ],
                "node_completion": [
                    {
                        "evidence_id": "ev-2",
                        "value": 1.0,
                    }
                ],
            }
        }
        result = provider.compute(
            student_id=1,
            course_id=1,
            metadata=metadata,
        )
        assert result.provider_version == "1.0", (
            f"Expected '1.0', got {result.provider_version!r}"
        )
