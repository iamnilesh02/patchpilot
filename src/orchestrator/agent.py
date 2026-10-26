from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Dict, Any
from src.engine.ast_context import ASTContextEngine
from src.engine.nebius_client import NebiusTokenFactoryClient
from src.guardrails.safety import SafetyTamperGate
from src.sandbox.runner import SandboxRunner


class AgentState(str, Enum):
    IDLE = "IDLE"
    ANALYZING = "ANALYZING"
    RETRIEVING_CONTEXT = "RETRIEVING_CONTEXT"
    TIER_ROUTING = "TIER_ROUTING"
    PATCHING = "PATCHING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    SECURITY_REJECTED = "SECURITY_REJECTED"


class PatchPilotAgent:
    """Coordinates context parsing, Nebius model generation, safety checks, and test feedback."""

    def __init__(
        self,
        workspace_dir: Path,
        state_listener: Optional[Callable[[AgentState, Dict[str, Any]], None]] = None,
    ):
        self.workspace = workspace_dir.resolve()
        self.sandbox = SandboxRunner(self.workspace)
        self.ast_engine = ASTContextEngine(self.workspace)
        self.guardrail = SafetyTamperGate(self.workspace)
        self.client = NebiusTokenFactoryClient()
        self.state_listener = state_listener or (lambda s, p: None)

    def _notify(self, state: AgentState, payload: Dict[str, Any]):
        self.state_listener(state, payload)

    def run_repair_loop(self, test_target: Optional[str] = None, max_iterations: int = 3) -> Dict[str, Any]:
        self._notify(AgentState.ANALYZING, {"message": "Executing initial baseline suite"})
        baseline = self.sandbox.run_pytest(test_target)

        if baseline["passed"]:
            self._notify(AgentState.RESOLVED, {"message": "All tests are passing."})
            return {"resolved": True, "iterations": 0, "total_cost": 0.0, "total_tokens": 0}

        accumulated_cost = 0.0
        total_tokens = 0
        current_error_log = baseline["output"]

        for iteration in range(1, max_iterations + 1):
            self._notify(
                AgentState.RETRIEVING_CONTEXT,
                {"iteration": iteration, "message": "Extracting syntax tree coordinates"},
            )
            ast_ctx = self.ast_engine.extract_context(current_error_log)
            
            # Safe Fallback: if ast_ctx could not be resolved from traceback
            if not ast_ctx:
                impl_files = [f for f in self.workspace.glob("*.py") if not f.name.startswith("test_")]
                if not impl_files:
                    self._notify(AgentState.FAILED, {"error": "No implementation files found."})
                    break
                target_f = impl_files[0]
                rel_f = str(target_f.relative_to(self.workspace))
                code = target_f.read_text(encoding="utf-8")
                prompt_ctx = f"FILE: {rel_f}\nERROR LOG:\n{current_error_log}\nSOURCE:\n{code}"
                exc_type = "RuntimeError"
            else:
                rel_f = ast_ctx.failing_file
                code = self.sandbox.read_file(rel_f)
                prompt_ctx = ast_ctx.condensed_prompt
                exc_type = ast_ctx.exception_type

            self._notify(
                AgentState.TIER_ROUTING,
                {"exception": exc_type, "iteration": iteration},
            )

            try:
                payload, telemetry = self.client.generate_patch(
                    condensed_ast_context=prompt_ctx,
                    full_source_code=code,
                    relative_path=rel_f,
                    exception_type=exc_type,
                    iteration=iteration,
                )
            except Exception as e:
                self._notify(AgentState.FAILED, {"error": f"API call failed: {str(e)}", "iteration": iteration})
                break

            accumulated_cost += telemetry.cost_usd
            total_tokens += telemetry.total_tokens

            # Strip code markdown wrappers
            rep_code = payload.get("replacement_code", "")
            if "```python" in rep_code:
                rep_code = rep_code.split("```python")[1].split("```")[0].strip()
            elif "```" in rep_code:
                rep_code = rep_code.split("```")[1].split("```")[0].strip()
            payload["replacement_code"] = rep_code

            # Guardrail inspection
            target_patch_file = payload.get("relative_path") or rel_f
            is_safe, reason = self.guardrail.validate_patch(
                relative_path=target_patch_file,
                proposed_code=payload["replacement_code"],
                original_code=code,
            )

            if not is_safe:
                self._notify(AgentState.SECURITY_REJECTED, {"reason": reason, "iteration": iteration})
                continue

            # Apply patch
            self._notify(AgentState.PATCHING, {"file": target_patch_file, "iteration": iteration})
            self.sandbox.write_file(target_patch_file, payload["replacement_code"])

            # Verify in sandbox
            self._notify(AgentState.VERIFYING, {"iteration": iteration})
            verification = self.sandbox.run_pytest(test_target)

            if verification["passed"]:
                self._notify(
                    AgentState.RESOLVED,
                    {
                        "iteration": iteration,
                        "cost": accumulated_cost,
                        "tokens": total_tokens,
                        "diagnosis": payload.get("diagnosis", ""),
                    },
                )
                return {
                    "resolved": True,
                    "iterations": iteration,
                    "total_cost": accumulated_cost,
                    "total_tokens": total_tokens,
                    "diagnosis": payload.get("diagnosis", ""),
                }

            current_error_log = verification["output"]

        self._notify(AgentState.FAILED, {"iterations": max_iterations, "cost": accumulated_cost})
        return {
            "resolved": False,
            "iterations": max_iterations,
            "total_cost": accumulated_cost,
            "total_tokens": total_tokens,
        }