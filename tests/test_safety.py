from pathlib import Path
from src.guardrails.safety import SafetyTamperGate


def test_safety_gate_blocks_test_modifications(tmp_path: Path):
    gate = SafetyTamperGate(tmp_path)
    is_safe, reason = gate.validate_patch(
        relative_path="tests/test_auth.py",
        proposed_code="def test_auth(): pass",
        original_code="",
    )
    assert not is_safe
    assert "Tamper Gate Violation" in reason


def test_safety_gate_blocks_subprocess_injection(tmp_path: Path):
    gate = SafetyTamperGate(tmp_path)
    is_safe, reason = gate.validate_patch(
        relative_path="utils.py",
        proposed_code="import os\nos.system('rm -rf /')",
        original_code="",
    )
    assert not is_safe