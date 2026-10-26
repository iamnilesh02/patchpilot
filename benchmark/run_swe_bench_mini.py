import os
import re
import shutil
import time
from pathlib import Path
from openai import OpenAI
from tabulate import tabulate
from benchmark.fixtures.catalog import SEEDED_FIXTURES
from src.orchestrator.agent import PatchPilotAgent
from src.sandbox.runner import SandboxRunner

BENCH_WORKSPACE = Path("./.temp_benchmark_suite").resolve()


def run_baseline_engine(task: dict) -> dict:
    """Engine A: Naive single-shot prompt without AST parsing or tiering."""
    run_dir = BENCH_WORKSPACE / "naive" / task["fixture_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / task["impl_filename"]).write_text(task["impl_code"], encoding="utf-8")
    (run_dir / task["test_filename"]).write_text(task["test_code"], encoding="utf-8")

    runner = SandboxRunner(run_dir)
    initial = runner.run_pytest(task["test_filename"])
    if initial["passed"]:
        return {"resolved": True, "time": 0.0, "cost": 0.0, "iterations": 1}

    start = time.perf_counter()
    client = OpenAI(
        base_url=os.getenv("NEBIUS_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        api_key=os.getenv("NEBIUS_API_KEY", ""),
    )

    prompt = (
        f"Fix the bug in {task['impl_filename']}. Return ONLY the pure corrected Python code.\n"
        f"Error:\n{initial['output']}\n"
        f"Code:\n{task['impl_code']}"
    )

    try:
        resp = client.chat.completions.create(
            model="nvidia/nemotron-3.5-lightning-30b-a3b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2048,
        )
        duration = time.perf_counter() - start
        content = resp.choices[0].message.content or ""

        # Remove thinking tags and markdown fences
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        if "```python" in content:
            content = content.split("```python")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        runner.write_file(task["impl_filename"], content.strip())
        verify = runner.run_pytest(task["test_filename"])

        usage = resp.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        cost = (prompt_tokens * 0.08 / 1e6) + (completion_tokens * 0.25 / 1e6)

        return {
            "resolved": verify["passed"],
            "time": duration,
            "cost": cost,
            "iterations": 1,
        }
    except Exception as e:
        return {
            "resolved": False,
            "time": time.perf_counter() - start,
            "cost": 0.0,
            "iterations": 1,
        }


def run_patchpilot_engine(task: dict) -> dict:
    """Engine B: AST-Aware extraction + Cascaded Nebius Router + Guarded loop."""
    run_dir = BENCH_WORKSPACE / "patchpilot" / task["fixture_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / task["impl_filename"]).write_text(task["impl_code"], encoding="utf-8")
    (run_dir / task["test_filename"]).write_text(task["test_code"], encoding="utf-8")

    start = time.perf_counter()
    agent = PatchPilotAgent(run_dir)
    result = agent.run_repair_loop(test_target=task["test_filename"], max_iterations=3)
    duration = time.perf_counter() - start

    return {
        "resolved": result["resolved"],
        "time": duration,
        "cost": result["total_cost"],
        "iterations": result["iterations"],
    }


def main():
    if BENCH_WORKSPACE.exists():
        shutil.rmtree(BENCH_WORKSPACE)
    BENCH_WORKSPACE.mkdir(parents=True, exist_ok=True)

    print("Starting 30-Run Mini SWE-Bench across synthetic seeded fixtures...\n")
    baseline_stats = []
    patchpilot_stats = []

    for idx, task in enumerate(SEEDED_FIXTURES):
        print(f"[{idx+1:02d}/30] Executing {task['fixture_id']}...")
        baseline_stats.append(run_baseline_engine(task))
        patchpilot_stats.append(run_patchpilot_engine(task))

    def compute_metrics(metrics: list) -> list:
        total = len(metrics)
        pass_count = sum(1 for m in metrics if m["resolved"])
        avg_iter = sum(m["iterations"] for m in metrics) / total
        avg_cost = sum(m["cost"] for m in metrics) / total
        avg_time = sum(m["time"] for m in metrics) / total
        return [
            f"{(pass_count/total)*100:.1f}% ({pass_count}/{total})",
            f"{avg_iter:.2f}",
            f"${avg_cost:.6f}",
            f"{avg_time:.2f}s",
        ]

    table = [
        ["Engine A: Naive Baseline (Single-Shot)"] + compute_metrics(baseline_stats),
        ["Engine B: PatchPilot (AST + Cascaded Router)"] + compute_metrics(patchpilot_stats),
    ]

    headers = ["Engine Architecture", "Resolution %", "Mean Iterations", "Avg Cost / Fix ($)", "Mean Duration (s)"]
    print("\n" + tabulate(table, headers=headers, tablefmt="github"))

    shutil.rmtree(BENCH_WORKSPACE)


if __name__ == "__main__":
    main()