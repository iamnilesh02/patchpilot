from pathlib import Path
from src.engine.ast_context import ASTContextEngine


def test_ast_context_parses_syntax_scope(tmp_path: Path):
    engine = ASTContextEngine(tmp_path)
    sample_file = tmp_path / "calc.py"
    sample_file.write_text(
        "class Calculator:\n    def divide(self, a, b):\n        return a / b\n",
        encoding="utf-8",
    )

    mock_traceback = f'  File "{sample_file}", line 3, in divide\n    return a / b\nZeroDivisionError: division by zero'
    ctx = engine.extract_context(mock_traceback)

    assert ctx is not None
    assert ctx.failing_file == "calc.py"
    assert ctx.enclosing_class == "Calculator"
    assert ctx.enclosing_function == "divide"
    assert ctx.exception_type == "ZeroDivisionError"