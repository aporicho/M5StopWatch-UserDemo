#!/usr/bin/env python3
"""Run the optional local correction model against the checked-in quality corpus."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ble_stt.correction import ConservativeCorrector, normalize_transcript  # noqa: E402
from ble_stt.correction_models import CorrectionModelStatus, correction_model_status  # noqa: E402
from ble_stt.llama_runtime import LlamaServerClient  # noqa: E402
from ble_stt.preferences import CorrectionPreferences  # noqa: E402


DEFAULT_CORPUS = PROJECT_ROOT / "tests" / "fixtures" / "correction_cases.jsonl"


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: case must be a JSON object")
            for key in ("id", "category", "input", "expected"):
                if not isinstance(value.get(key), str) or not value[key]:
                    raise ValueError(f"{path}:{line_number}: {key} must be a non-empty string")
            glossary = value.get("glossary", [])
            if not isinstance(glossary, list) or not all(isinstance(term, str) for term in glossary):
                raise ValueError(f"{path}:{line_number}: glossary must be a string array")
            cases.append(value)
    return cases


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def evaluate(
    cases: list[dict[str, Any]],
    *,
    timeout: float,
    show_progress: bool,
    model_path: Path | None = None,
    runtime_path: Path | None = None,
) -> dict[str, Any]:
    status = correction_model_status()
    if model_path is not None:
        resolved_model = model_path.expanduser().resolve()
        resolved_runtime = (
            runtime_path.expanduser().resolve()
            if runtime_path is not None
            else Path(status.runtime_path or "").expanduser().resolve()
        )
        status = CorrectionModelStatus(
            repository="local-evaluation",
            filename=resolved_model.name,
            state="ready",
            installed=resolved_model.is_file(),
            disk_bytes=resolved_model.stat().st_size if resolved_model.is_file() else 0,
            path=str(resolved_model),
            revision=None,
            sha256=None,
            runtime_available=resolved_runtime.is_file(),
            runtime_path=str(resolved_runtime) if resolved_runtime.is_file() else None,
            message="local evaluation model ready",
        )
    if not status.ready:
        raise RuntimeError(status.message)

    corrector = ConservativeCorrector(LlamaServerClient(status))
    rows: list[dict[str, Any]] = []
    started = time.monotonic()
    try:
        for index, case in enumerate(cases, start=1):
            glossary = tuple(case.get("glossary", ()))
            preferences = CorrectionPreferences(
                enabled=True,
                glossary=glossary,
                timeout_seconds=timeout,
            )
            result = corrector.correct(case["input"], preferences)
            expected = normalize_transcript(case["expected"])
            raw = normalize_transcript(case["input"])
            passed = result.text == expected
            rows.append(
                {
                    "id": case["id"],
                    "category": case["category"],
                    "input": raw,
                    "expected": expected,
                    "actual": result.text,
                    "passed": passed,
                    "expected_change": expected != raw,
                    "state": result.state,
                    "reason": result.reason,
                    "latency_ms": result.latency_ms,
                }
            )
            if show_progress and (index == 1 or index % 10 == 0 or index == len(cases)):
                passed_count = sum(1 for row in rows if row["passed"])
                print(
                    f"[{index:>3}/{len(cases)}] exact={passed_count / index:.1%}",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        if corrector.client is not None:
            corrector.client.close()

    category_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        category_rows[row["category"]].append(row)

    changed_rows = [row for row in rows if row["expected_change"]]
    preserved_rows = [row for row in rows if not row["expected_change"]]
    latencies = [int(row["latency_ms"]) for row in rows]
    categories = {
        category: {
            "cases": len(values),
            "passed": sum(1 for row in values if row["passed"]),
            "accuracy": sum(1 for row in values if row["passed"]) / len(values),
        }
        for category, values in sorted(category_rows.items())
    }
    return {
        "model": status.filename,
        "cases": len(rows),
        "passed": sum(1 for row in rows if row["passed"]),
        "exact_accuracy": sum(1 for row in rows if row["passed"]) / len(rows),
        "correction_accuracy": (
            sum(1 for row in changed_rows if row["passed"]) / len(changed_rows) if changed_rows else 1.0
        ),
        "preservation_accuracy": (
            sum(1 for row in preserved_rows if row["passed"]) / len(preserved_rows)
            if preserved_rows
            else 1.0
        ),
        "false_changes": sum(1 for row in preserved_rows if not row["passed"]),
        "reasons": dict(Counter(str(row["reason"]) for row in rows)),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 1) if latencies else 0,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": max(latencies, default=0),
        },
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "categories": categories,
        "failures": [row for row in rows if not row["passed"]],
    }


def print_report(report: dict[str, Any], failure_limit: int) -> None:
    print(
        f"纠错评测：{report['passed']}/{report['cases']} 精确通过 "
        f"({report['exact_accuracy']:.1%})"
    )
    print(
        f"应纠正准确率 {report['correction_accuracy']:.1%} · "
        f"应保持准确率 {report['preservation_accuracy']:.1%} · "
        f"误改 {report['false_changes']} 条"
    )
    latency = report["latency_ms"]
    print(
        f"延迟 mean/p50/p95/max = {latency['mean']}/{latency['p50']}/"
        f"{latency['p95']}/{latency['max']} ms · 总耗时 {report['elapsed_seconds']}s"
    )
    print("\n分类结果：")
    for category, value in report["categories"].items():
        print(
            f"  {category:<26} {value['passed']:>3}/{value['cases']:<3} "
            f"{value['accuracy']:.1%}"
        )
    failures = report["failures"][: max(0, failure_limit)]
    if failures:
        print(f"\n前 {len(failures)} 条失败：")
        for row in failures:
            print(f"  [{row['id']}] {row['input']}")
            print(f"    期望：{row['expected']}")
            print(f"    实际：{row['actual']} ({row['state']}/{row['reason']})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--runtime-path", type=Path)
    parser.add_argument("--failures", type=int, default=20)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--minimum-accuracy", type=float, default=0.0)
    parser.add_argument("--minimum-preservation", type=float, default=0.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_cases(args.corpus)
    if args.category:
        selected = set(args.category)
        cases = [case for case in cases if case["category"] in selected]
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        print("没有匹配的评测用例。", file=sys.stderr)
        return 2
    try:
        report = evaluate(
            cases,
            timeout=max(0.5, args.timeout),
            show_progress=not args.as_json,
            model_path=args.model_path,
            runtime_path=args.runtime_path,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"无法运行纠错评测：{exc}", file=sys.stderr)
        return 2
    if args.as_json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_report(report, args.failures)
    if report["exact_accuracy"] < args.minimum_accuracy:
        return 1
    if report["preservation_accuracy"] < args.minimum_preservation:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
