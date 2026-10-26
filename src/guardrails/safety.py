import ast
from pathlib import Path
from typing import Tuple


class SafetyTamperGate:
    """Policy gate preventing test tampering, path traversal, and dangerous calls."""

    DISALLOWED_MODULES = {"subprocess", "shutil.rmtree", "os.system", "pty", "socket"}

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def validate_patch(
        self, relative_path: str, proposed_code: str, original_code: str
    ) -> Tuple[bool, str]:
        target_path = (self.workspace_root / relative_path).resolve()

        # 1. Path Traversal Guard
        if not str(target_path).startswith(str(self.workspace_root)):
            return False, "Security Violation: Proposed patch writes outside designated workspace."

        # 2. Anti-Cheating Invariant: Reject modification to tests
        if "test" in target_path.name.lower() or target_path.parts[-2].lower() == "tests":
            return False, "Tamper Gate Violation: Modifying tests or test assertions is strictly forbidden."

        # 3. Syntactic Integrity Check
        try:
            proposed_tree = ast.parse(proposed_code)
        except SyntaxError as e:
            return False, f"Syntax Error in generated patch: {str(e)}"

        # 4. Dangerous System Invocation Scanner
        for node in ast.walk(proposed_tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in self.DISALLOWED_MODULES:
                        return False, f"Prohibited module '{alias.name}' detected in proposed patch."
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in self.DISALLOWED_MODULES:
                    return False, f"Prohibited module import from '{mod}' detected in proposed patch."
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == "system":
                    return False, "Direct system execution call rejected."

        return True, "Patch passed security verification."