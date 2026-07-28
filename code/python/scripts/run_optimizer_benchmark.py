#!/usr/bin/env python3
"""Run the frozen Gate A6 fixed-budget optimizer benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python"))
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.inversion import (  # noqa: E402
    InversionConfig,
    InversionObjective,
    denormalize_vector,
    encode_params,
    make_synthetic_target,
)
from oer_aem.optimizer_benchmark import (  # noqa: E402
    DEVELOPMENT_OPTIMIZERS,
    OPTIMIZATION_BUDGET,
    build_confirmation_jobs,
    build_development_jobs,
    run_benchmark_job,
    select_development_candidate,
    summarize_confirmation_gate,
)
from scripts.run_synthetic_recovery import (  # noqa: E402
    git_state_full,
    validate_backend,
)


ALGORITHM_CONTRACT = {
    "tpe": {"n_startup_trials": 10},
    "sobol_pattern": {
        "sobol_points": 64,
        "initial_step": 0.125,
        "minimum_step": 1.0 / 1024.0,
    },
    "de_fixed": {
        "strategy": "DE/rand/1/bin",
        "population": 20,
        "generations": 4,
        "mutation_factor": 0.8,
        "crossover_probability": 0.7,
        "boundary": "reflection",
    },
}
WORKFLOW_OWNED_FILES = {
    "STATUS.json",
    "._status_signal",
    "stdout.log",
    "stderr.log",
    "task_spec.snapshot.yaml",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("development", "confirmation"),
        required=True,
    )
    parser.add_argument("--backend", choices=("cn", "lsoda"), required=True)
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--noise-evidence", type=Path)
    parser.add_argument("--development-evidence", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--max-jobs", "--max_jobs", type=int)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _atomic_write_text(path: Path, text: str, *, prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=prefix,
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _atomic_json(path: Path, value: Any, *, prefix: str) -> None:
    _atomic_write_text(
        path,
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)
        + "\n",
        prefix=prefix,
    )


def _atomic_jsonl(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    prefix: str,
) -> None:
    text = "".join(
        json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
        for row in rows
    )
    _atomic_write_text(path, text, prefix=prefix)


def _assert_finite(value: Any, *, location: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite value at {location}")
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite(item, location=f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_finite(item, location=f"{location}[{index}]")


def _read_noise_evidence(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path.resolve()
    raw = resolved.read_bytes()
    try:
        evidence = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("noise evidence is not valid JSON") from exc
    return {
        "resolved_path": str(resolved),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "selected_noise_fraction": float(
            evidence["selected_noise_fraction"]
        ),
    }


def _read_development_evidence(
    path: Path | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if path is None:
        raise ValueError(
            "confirmation requires --development-evidence"
        )
    resolved = path.resolve()
    raw = resolved.read_bytes()
    try:
        evidence = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("development evidence is not valid JSON") from exc
    if not isinstance(evidence, dict):
        raise ValueError("development evidence must be a JSON object")
    _assert_finite(evidence, location="development_evidence")
    if evidence.get("schema_version") != 1:
        raise ValueError("development evidence schema_version must equal 1")
    if evidence.get("selected_optimizer") != "sobol_pattern":
        raise ValueError(
            "development evidence must select sobol_pattern"
        )
    if evidence.get("source_commit") != (
        "a5b93f55e540682cc8cddb1fabbe63a7e0e92326"
    ):
        raise ValueError("development evidence source_commit mismatch")
    if evidence.get("source_results_sha256") != (
        "e93ccab24c4a91d9d4d9a2b8e014826b6b1a07b7d0891c6e7dd944b78e17b432"
    ):
        raise ValueError("development evidence source hash mismatch")
    rows = evidence.get("development_rows")
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError(
            "development evidence must contain exactly three rows"
        )
    expected_pairs = {
        ("k0_2", "k0_3"),
        ("k0_2", "G_O"),
        ("k0_3", "G_O"),
    }
    if {
        tuple(row.get("free_parameters", [])) for row in rows
    } != expected_pairs:
        raise ValueError("development evidence pair matrix mismatch")
    for row in rows:
        if (
            row.get("optimizer") != "sobol_pattern"
            or row.get("truth_id") != "center"
            or float(row.get("noise_fraction", -1.0)) != 0.0
            or int(row.get("seed", -1)) != 7
            or int(row.get("optimization_calls", -1)) != 100
            or row.get("success") is not True
        ):
            raise ValueError("development evidence row contract mismatch")
    metadata = {
        "resolved_path": str(resolved),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_commit": evidence["source_commit"],
        "source_results_sha256": evidence["source_results_sha256"],
        "source_selection_sha256": evidence[
            "source_selection_sha256"
        ],
    }
    return metadata, rows


def _select_specs(names):
    from oer_aem.inversion import DEFAULT_PARAM_SPECS

    by_name = {spec[0]: spec for spec in DEFAULT_PARAM_SPECS}
    return tuple(by_name[name] for name in names)


class _UnitObjective:
    def __init__(self, objective: InversionObjective, specs) -> None:
        self.objective = objective
        self.specs = specs

    def __call__(self, unit) -> float:
        return float(
            self.objective(denormalize_vector(unit, self.specs))
        )

    @property
    def n_ode_fail(self) -> int:
        return int(self.objective.n_ode_fail)

    @property
    def n_tafel_fail(self) -> int:
        return int(self.objective.n_tafel_fail)

    @property
    def n_forward(self) -> int:
        return int(self.objective.n_forward)


def _configuration(job: dict[str, Any], *, backend: str, smoke: bool):
    specs = _select_specs(job["free_parameters"])
    free_names = set(job["free_parameters"])
    fixed = tuple(
        (name, float(value))
        for name, value in job["truth_params"].items()
        if name not in free_names
    )
    config = InversionConfig(
        n_points=256 if smoke else 8192,
        points_per_cycle=32,
        feature_grid_size=128,
        fit_harmonics=(1, 2, 3),
        feature_mode="hybrid",
        solver_backend=backend,
        seed=int(job["seed"]),
        fixed_params=fixed,
    )
    return config, specs


def _execute_job(
    job: dict[str, Any],
    *,
    backend: str,
    smoke: bool,
) -> dict[str, Any]:
    config, specs = _configuration(job, backend=backend, smoke=smoke)
    started = time.perf_counter()

    def objective_factory(received_job):
        target = make_synthetic_target(
            received_job["truth_params"],
            config=config,
            noise_fraction=float(received_job["noise_fraction"]),
            seed=int(received_job["target_seed"]),
        )
        optimization = _UnitObjective(
            InversionObjective(target, config=config, specs=specs),
            specs,
        )
        diagnostic_objective = InversionObjective(
            target,
            config=config,
            specs=specs,
        )
        truth_encoded = encode_params(
            received_job["truth_params"],
            specs,
        )

        def truth_diagnostic() -> float:
            return float(diagnostic_objective(truth_encoded))

        return optimization, truth_diagnostic

    row = run_benchmark_job(job, objective_factory=objective_factory)
    row["runtime_seconds"] = time.perf_counter() - started
    row["configuration"] = {
        "n_points": config.n_points,
        "points_per_cycle": config.points_per_cycle,
        "feature_grid_size": config.feature_grid_size,
        "fit_harmonics": list(config.fit_harmonics),
        "feature_mode": config.feature_mode,
        "solver_backend": config.solver_backend,
        "fixed_params": [list(item) for item in config.fixed_params],
    }
    row["truth_diagnostic_sequence"] = int(row["optimization_calls"]) + 1
    return row


def _job_contract(
    job: dict[str, Any],
    *,
    backend: str,
    smoke: bool,
) -> dict[str, Any]:
    config, _ = _configuration(job, backend=backend, smoke=smoke)
    return {
        "job": job,
        "backend": backend,
        "smoke": smoke,
        "algorithm_contract": ALGORITHM_CONTRACT[job["optimizer"]],
        "configuration": {
            "n_points": config.n_points,
            "points_per_cycle": config.points_per_cycle,
            "feature_grid_size": config.feature_grid_size,
            "fit_harmonics": list(config.fit_harmonics),
            "feature_mode": config.feature_mode,
            "fixed_params": [list(item) for item in config.fixed_params],
        },
    }


def _run_contract_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": plan["schema_version"],
        "source_commit": plan["provenance"]["source_commit"],
        "dirty": plan["provenance"]["dirty"],
        "dirty_paths": plan["provenance"].get("dirty_paths", []),
        "phase": plan["phase"],
        "backend": plan["backend"],
        "budget": plan["budget"],
        "workers": plan["workers"],
        "is_smoke": plan["is_smoke"],
        "noise_evidence": plan["noise_evidence"],
        "development_evidence": plan.get("development_evidence"),
        "algorithm_contract": plan["algorithm_contract"],
        "jobs": [
            {
                "job_id": job["job_id"],
                "job_input_hash": job["job_input_hash"],
            }
            for job in plan["jobs"]
        ],
    }


def _prepare_output(output: Path, *, resume: bool) -> None:
    output.mkdir(parents=True, exist_ok=True)
    scientific = {
        path.name
        for path in output.iterdir()
        if path.name not in WORKFLOW_OWNED_FILES
        and not path.name.startswith(".")
    }
    allowed = {
        "benchmark_plan.json",
        "results.jsonl",
        "evaluations.jsonl",
        "summary.json",
        "selection.json",
        "confirmation_gate.json",
        "development_evidence.snapshot.json",
    }
    if not resume and scientific:
        raise FileExistsError("output contains existing scientific artifacts")
    if resume and not scientific <= allowed:
        raise FileExistsError("resume directory contains unknown artifacts")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    if raw and not raw.endswith("\n"):
        raise ValueError(f"{path.name} ends with an incomplete line")
    rows = []
    for number, line in enumerate(raw.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid JSON in {path.name} line {number}"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path.name} line {number} is not an object")
        _assert_finite(row, location=f"{path.name}:{number}")
        rows.append(row)
    return rows


def _iter_rows(
    jobs: list[dict[str, Any]],
    *,
    workers: int,
    backend: str,
    smoke: bool,
):
    if workers == 1:
        for job in jobs:
            yield _execute_job(job, backend=backend, smoke=smoke)
        return
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as executor:
        futures = {
            executor.submit(
                _execute_job,
                job,
                backend=backend,
                smoke=smoke,
            ): job["job_id"]
            for job in jobs
        }
        for future in as_completed(futures):
            yield future.result()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.backend != "cn" and not args.smoke:
        raise ValueError("formal optimizer benchmark requires backend=cn")
    if args.budget != OPTIMIZATION_BUDGET:
        raise ValueError("optimizer benchmark requires budget=100")
    if args.workers < 1:
        raise ValueError("workers must be positive")
    if args.max_jobs is not None and args.max_jobs < 1:
        raise ValueError("--max-jobs must be positive")
    if args.smoke and args.max_jobs not in (None, 3):
        raise ValueError("optimizer smoke requires exactly three jobs")
    validate_backend(args.backend)
    noise_evidence = _read_noise_evidence(args.noise_evidence)
    development_evidence = None
    development_rows = None
    selected_noise = (
        noise_evidence["selected_noise_fraction"]
        if noise_evidence
        else None
    )
    if args.phase == "development":
        if args.development_evidence is not None:
            raise ValueError(
                "development phase does not accept development evidence"
            )
        jobs = build_development_jobs(noise_fraction=selected_noise)
    else:
        if noise_evidence is None:
            raise ValueError(
                "confirmation requires --noise-evidence"
            )
        development_evidence, development_rows = (
            _read_development_evidence(args.development_evidence)
        )
        jobs = build_confirmation_jobs(noise_fraction=selected_noise)
    if args.smoke and args.phase == "confirmation":
        jobs = [
            next(
                job
                for job in jobs
                if tuple(job["free_parameters"]) == pair
            )
            for pair in (
                ("k0_2", "k0_3"),
                ("k0_2", "G_O"),
                ("k0_3", "G_O"),
            )
        ]
    elif args.max_jobs is not None:
        jobs = jobs[: args.max_jobs]
    if args.smoke and len(jobs) != 3:
        raise ValueError("optimizer smoke requires exactly three jobs")
    if (
        not args.smoke
        and args.phase == "confirmation"
        and len(jobs) != 51
    ):
        raise ValueError("formal confirmation requires 51 jobs")

    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[variable] = "1"

    provenance = {
        **git_state_full(),
        "python": platform.python_version(),
    }
    if args.backend == "cn":
        from oer_aem.cpp_bridge import library_path

        provenance["solver_library"] = library_path()
    for job in jobs:
        job["backend"] = args.backend
        job["job_input_hash"] = _sha256(
            _job_contract(job, backend=args.backend, smoke=args.smoke)
        )
    plan = {
        "schema_version": 1,
        "phase": args.phase,
        "backend": args.backend,
        "budget": args.budget,
        "workers": args.workers,
        "is_smoke": args.smoke,
        "noise_evidence": noise_evidence,
        "development_evidence": development_evidence,
        "algorithm_contract": ALGORITHM_CONTRACT,
        "jobs": jobs,
        "provenance": provenance,
    }
    plan["resume_fingerprint"] = _sha256(_run_contract_from_plan(plan))

    output = args.output.resolve()
    _prepare_output(output, resume=args.resume)
    development_snapshot_path = (
        output / "development_evidence.snapshot.json"
    )
    if args.phase == "confirmation":
        assert development_evidence is not None
        source_path = Path(
            development_evidence["resolved_path"]
        )
        if args.resume:
            if not development_snapshot_path.is_file():
                raise ValueError(
                    "resume requires development evidence snapshot"
                )
            snapshot_hash = hashlib.sha256(
                development_snapshot_path.read_bytes()
            ).hexdigest()
            if snapshot_hash != development_evidence["sha256"]:
                raise ValueError(
                    "development evidence snapshot hash mismatch"
                )
        else:
            _atomic_write_text(
                development_snapshot_path,
                source_path.read_text(encoding="utf-8"),
                prefix=".development_evidence.",
            )
    plan_path = output / "benchmark_plan.json"
    if args.resume:
        if not plan_path.exists():
            raise ValueError("resume requires benchmark_plan.json")
        existing_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        stored = existing_plan.get("resume_fingerprint")
        if (
            stored != _sha256(_run_contract_from_plan(existing_plan))
            or stored != plan["resume_fingerprint"]
        ):
            raise ValueError(
                "resume_fingerprint mismatch; refuse mixed evidence"
            )
    else:
        _atomic_json(plan_path, plan, prefix=".benchmark_plan.")

    result_path = output / "results.jsonl"
    evaluation_path = output / "evaluations.jsonl"
    results = _load_jsonl(result_path) if args.resume else []
    evaluations = _load_jsonl(evaluation_path) if args.resume else []
    expected_hashes = {
        job["job_id"]: job["job_input_hash"] for job in jobs
    }
    result_by_id: dict[str, dict[str, Any]] = {}
    for row in results:
        job_id = row.get("job_id")
        if (
            job_id not in expected_hashes
            or row.get("job_input_hash") != expected_hashes[job_id]
            or job_id in result_by_id
        ):
            raise ValueError("resume result job/hash mismatch")
        result_by_id[job_id] = row
    evaluation_by_id: dict[str, list[dict[str, Any]]] = {
        job_id: [] for job_id in result_by_id
    }
    for row in evaluations:
        job_id = row.get("job_id")
        if job_id not in evaluation_by_id:
            raise ValueError("orphan resume evaluation")
        evaluation_by_id[job_id].append(row)
    for job_id, rows in evaluation_by_id.items():
        if len(rows) != OPTIMIZATION_BUDGET:
            raise ValueError(f"resume evaluation count mismatch for {job_id}")

    remaining = [
        job for job in jobs if job["job_id"] not in result_by_id
    ]
    for completed in _iter_rows(
        remaining,
        workers=args.workers,
        backend=args.backend,
        smoke=args.smoke,
    ):
        job_id = completed["job_id"]
        if job_id not in expected_hashes or job_id in result_by_id:
            raise ValueError("worker returned unexpected or duplicate job")
        trace = completed.pop("evaluations")
        if len(trace) != OPTIMIZATION_BUDGET:
            raise ValueError("worker returned incorrect evaluation count")
        completed["job_input_hash"] = expected_hashes[job_id]
        _assert_finite(completed, location=job_id)
        result_by_id[job_id] = completed
        evaluation_by_id[job_id] = [
            {
                "job_id": job_id,
                "job_input_hash": expected_hashes[job_id],
                "sequence": index,
                "kind": "optimization",
                **evaluation,
            }
            for index, evaluation in enumerate(trace, start=1)
        ]
        ordered_ids = [
            job["job_id"]
            for job in jobs
            if job["job_id"] in result_by_id
        ]
        _atomic_jsonl(
            result_path,
            [result_by_id[item] for item in ordered_ids],
            prefix=".results.",
        )
        _atomic_jsonl(
            evaluation_path,
            [
                evaluation
                for item in ordered_ids
                for evaluation in evaluation_by_id[item]
            ],
            prefix=".evaluations.",
        )

    ordered_results = [result_by_id[job["job_id"]] for job in jobs]
    execution_passed = len(ordered_results) == len(jobs) and all(
        row["success"] for row in ordered_results
    )
    if args.smoke:
        if args.phase == "development":
            gate = {
                "scientific_gate_passed": None,
                "selected_optimizer": None,
                "next_action": "RUN_FORMAL_DEVELOPMENT",
            }
        else:
            gate = {
                "scientific_gate_passed": None,
                "eligible_pairs": [],
                "next_action": "RUN_FORMAL_CONFIRMATION",
            }
    elif args.phase == "development":
        gate = select_development_candidate(ordered_results)
    else:
        assert development_rows is not None
        gate = summarize_confirmation_gate(
            development_rows,
            ordered_results,
        )
    if args.phase == "development":
        gate_path = output / "selection.json"
        gate_prefix = ".selection."
    else:
        gate_path = output / "confirmation_gate.json"
        gate_prefix = ".confirmation_gate."
    summary = {
        "execution_passed": execution_passed,
        "scientific_gate_passed": gate["scientific_gate_passed"],
        "job_count": len(jobs),
        "completed_jobs": len(ordered_results),
        "optimization_calls": sum(
            int(row["optimization_calls"]) for row in ordered_results
        ),
        "diagnostic_truth_calls": sum(
            int(row["diagnostic_truth_calls"]) for row in ordered_results
        ),
        "n_ode_fail": sum(
            int(row.get("n_ode_fail", 0)) for row in ordered_results
        ),
        "source_commit": provenance["source_commit"],
        "is_smoke": args.smoke,
    }
    _atomic_json(output / "summary.json", summary, prefix=".summary.")
    _atomic_json(gate_path, gate, prefix=gate_prefix)
    print(output)


if __name__ == "__main__":
    main()
