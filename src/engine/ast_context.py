import ast
import re
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel


class ASTContextResult(BaseModel):
    failing_file: str
    failing_line: int
    exception_type: str
    exception_message: str
    enclosing_function: Optional[str] = None
    enclosing_class: Optional[str] = None
    target_node_source: str
    imported_dependencies: List[str] = []
    symbol_references: List[str] = []
    condensed_prompt: str


class ASTContextEngine:
    """Parses pytest execution tracebacks and extracts isolated AST syntactic context."""

    # Handles both Unix (/) and Windows (\) file path formats
    TRACEBACK_REGEX = re.compile(
        r'File "([^"]+?\.py)", line (\d+)(?:, in (\w+))?\n\s*(.*?)\n([A-Za-z_][A-Za-z0-9_]*Error|Exception):\s*(.*)',
        re.DOTALL
    )
    PYTEST_ASSERT_REGEX = re.compile(r'([^\s:]+?\.py):(\d+): (?:in (\w+))?')
    SHORT_FAIL_REGEX = re.compile(r'FAILED\s+([^\s:]+?\.py)::')

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def parse_traceback(self, stderr_output: str) -> Optional[Dict[str, any]]:
        # Match standard Python traceback
        matches = list(self.TRACEBACK_REGEX.finditer(stderr_output))
        if matches:
            last = matches[-1]
            return {
                "file": last.group(1),
                "line": int(last.group(2)),
                "function": last.group(3) or "module",
                "exc_type": last.group(5),
                "exc_msg": last.group(6).splitlines()[0].strip() if last.group(6) else "",
            }

        # Match pytest assertion failure lines (e.g. test_module_1.py:3: in test_ratio)
        pytest_matches = list(self.PYTEST_ASSERT_REGEX.finditer(stderr_output))
        if pytest_matches:
            last = pytest_matches[-1]
            # Search for exception type in the tail lines
            exc_match = re.search(r'([A-Za-z_][A-Za-z0-9_]*Error|Exception):\s*(.*)', stderr_output)
            return {
                "file": last.group(1),
                "line": int(last.group(2)),
                "function": last.group(3) or "test_function",
                "exc_type": exc_match.group(1) if exc_match else "AssertionError",
                "exc_msg": exc_match.group(2).strip() if exc_match else "Test failure assertion.",
            }

        # Match generic pytest FAILED lines
        fail_match = self.SHORT_FAIL_REGEX.search(stderr_output)
        if fail_match:
            return {
                "file": fail_match.group(1),
                "line": 1,
                "function": "module",
                "exc_type": "AssertionError",
                "exc_msg": "Assertion failure detected in test run.",
            }

        return None

    def _locate_target_file(self, raw_file: str) -> Optional[Path]:
        """Locates the file even if path prefixes differ between sandbox and runner."""
        raw_p = Path(raw_file)
        # Direct check
        cand = raw_p if raw_p.is_absolute() else (self.workspace_root / raw_p)
        if cand.exists():
            return cand

        # Name-only fallback search inside workspace
        filename = raw_p.name
        for match in self.workspace_root.rglob(filename):
            if match.is_file():
                return match

        # Look for non-test implementation file if error was logged in test file
        if "test_" in filename:
            impl_name = filename.replace("test_", "")
            for match in self.workspace_root.rglob(impl_name):
                if match.is_file():
                    return match

        # Fallback: pick the first non-test .py file in workspace
        for match in self.workspace_root.glob("*.py"):
            if not match.name.startswith("test_"):
                return match

        return None

    def extract_context(self, stderr_output: str) -> Optional[ASTContextResult]:
        parsed = self.parse_traceback(stderr_output)
        if not parsed:
            # Emergency fallback: locate any implementation file in workspace
            impl_files = [f for f in self.workspace_root.glob("*.py") if not f.name.startswith("test_")]
            if not impl_files:
                return None
            target_path = impl_files[0]
            parsed = {
                "file": str(target_path),
                "line": 1,
                "function": "module",
                "exc_type": "RuntimeError",
                "exc_msg": "Test suite failure.",
            }
        else:
            target_path = self._locate_target_file(parsed["file"])
            if not target_path or not target_path.exists():
                return None

        # If the traceback points to test file, point context to the implementation file instead
        if target_path.name.startswith("test_"):
            impl_counterpart = self.workspace_root / target_path.name.replace("test_", "")
            if impl_counterpart.exists():
                target_path = impl_counterpart
                parsed["line"] = 1

        try:
            source_code = target_path.read_text(encoding="utf-8")
            tree = ast.parse(source_code, filename=str(target_path))
        except Exception:
            return None

        line_no = parsed["line"]
        enclosing_class = None
        enclosing_function = None
        target_node = None
        imported_deps = []
        symbol_refs = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_deps.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imported_deps.append(f"{module}.{alias.name}")

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.lineno <= line_no <= getattr(node, "end_lineno", line_no):
                    enclosing_class = node.name

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.lineno <= line_no <= getattr(node, "end_lineno", line_no):
                    enclosing_function = node.name
                    target_node = node
                    break

        if target_node:
            node_source = ast.get_source_segment(source_code, target_node) or ""
            for inner in ast.walk(target_node):
                if isinstance(inner, ast.Name):
                    symbol_refs.add(inner.id)
        else:
            # If function boundaries are not found, provide the full file source
            node_source = source_code

        rel_path = str(target_path.relative_to(self.workspace_root))

        condensed_prompt = (
            f"TARGET FILE: {rel_path} (Line {line_no})\n"
            f"EXCEPTION: {parsed['exc_type']}: {parsed['exc_msg']}\n"
            f"SCOPE: Class '{enclosing_class or 'Module'}' -> Function '{enclosing_function or 'Global'}'\n"
            f"LOCAL DEPENDENCIES: {', '.join(imported_deps[:8])}\n"
            f"RELEVANT CODE:\n```python\n{node_source}\n```"
        )

        return ASTContextResult(
            failing_file=rel_path,
            failing_line=line_no,
            exception_type=parsed["exc_type"],
            exception_message=parsed["exc_msg"],
            enclosing_function=enclosing_function,
            enclosing_class=enclosing_class,
            target_node_source=node_source,
            imported_dependencies=imported_deps,
            symbol_references=list(symbol_refs),
            condensed_prompt=condensed_prompt,
        )