import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional


class SandboxRunner:
    """Executes unit tests inside the workspace sandbox and captures logs."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def run_pytest(self, test_target: Optional[str] = None, timeout: int = 25) -> Dict[str, Any]:
        # Use sys.executable -m pytest to avoid Windows PATH issues with pytest.exe
        cmd = [sys.executable, "-m", "pytest", "-v"]
        if test_target:
            cmd.append(test_target)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.workspace_root)

        try:
            process = subprocess.run(
                cmd,
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            return {
                "passed": process.returncode == 0,
                "exit_code": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
                "output": process.stdout + ("\n" + process.stderr if process.stderr else ""),
            }
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Execution timed out.",
                "output": "Test runner timed out.",
            }

    def write_file(self, relative_path: str, content: str) -> None:
        target = self.workspace_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def read_file(self, relative_path: str) -> str:
        target = self.workspace_root / relative_path
        if not target.exists():
            raise FileNotFoundError(f"File {relative_path} not found in workspace.")
        return target.read_text(encoding="utf-8")