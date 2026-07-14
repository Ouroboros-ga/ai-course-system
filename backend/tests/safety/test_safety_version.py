"""
Test for G2.1 contract version constant and ReasonCode stability semantics.

Verifies:
1. SAFETY_VERSION matches the registry entry "safety/1.0".
2. ReasonCode stability semantics are documented in the module docstring.
"""

from app.domain.safety.decision import SAFETY_VERSION, ReasonCode


class TestSafetyVersion:
    """SAFETY_VERSION contract constant."""

    def test_safety_version_value(self):
        """SAFETY_VERSION must equal the registry contract name."""
        assert SAFETY_VERSION == "safety/1.0", (
            f"Expected safety/1.0, got {SAFETY_VERSION!r}"
        )

    def test_safety_version_is_string(self):
        """SAFETY_VERSION must be a string."""
        assert isinstance(SAFETY_VERSION, str)


class TestReasonCodeStability:
    """ReasonCode stability semantics are documented."""

    def test_reason_code_stability_documented(self):
        """The module docstring must mention version stability semantics."""
        import app.domain.safety.decision as mod
        doc = mod.__doc__ or ""
        # The docstring should reference version stability
        assert "stable" in doc.lower(), "Module docstring must mention stability"
        assert "version" in doc.lower(), "Module docstring must mention version"

    def test_reason_code_enum_values_unique(self):
        """All reason codes must have unique values (stability invariant)."""
        values = [rc.value for rc in ReasonCode]
        assert len(values) == len(set(values)), "ReasonCode values must be unique"

    def test_reason_code_values_match_names(self):
        """Each ReasonCode's value must equal its member name (by convention)."""
        for rc in ReasonCode:
            assert rc.value == rc.name, (
                f"{rc.name} value {rc.value!r} must equal {rc.name!r}"
            )
