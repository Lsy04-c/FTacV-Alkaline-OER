#!/usr/bin/env python3
"""Raw-cmaes 适配版 CMA-ES 合成恢复筛选。

搜索 z∈[0,1]^n（经 denormalize_vector 映射回编码坐标），带 bounds、
盒子中点温启动 mean、sigma=0.25、popsize=4+3ln(n)，CMA 收敛
(should_stop) 后以当前最优点倍增 popsize 重启（IPOP 式）。

设计背景（2026-08-06）：
- optuna 4.9.0 弃用了 CmaEsSampler 的 restart_strategy/x0，无法做适配，
  故直接用 raw cmaes 包。
- smoke 分辨率(256点)下 truth 点 Tafel 特征提取失败、landscape 失真，
  正式筛选必须全量(8192点)；--smoke 仅作本地机制自检。

用法:
  python screen_cmaes_raw.py --mode legacy --seed 7 --trials 500
  python screen_cmaes_raw.py --smoke --trials 30   # 本地自检
"""
import argparse
import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Mapping, Optional, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))


def _load_cmaes():
    """Load the optional raw-CMA dependency at execution time.

    Keeping this import lazy lets callers inspect/validate a search contract
    without the optional optimizer installed, while the runtime error remains
    explicit and auditable when an actual CMA run is requested.
    """
    try:
        import cmaes
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "raw CMA-ES requires the optional 'cmaes' package; "
            "install it with 'pip install cmaes'"
        ) from exc
    return cmaes


def _formal_execution_provenance() -> dict[str, object]:
    """Require a clean checkout and bind a formal run to its source commit."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain=v1"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("formal CMA requires a Git worktree with a resolvable commit") from exc
    if not commit or dirty:
        raise ValueError("formal CMA requires a clean worktree")
    return {"source_commit": commit, "dirty": False}

from oer_aem.inversion import (
    DEFAULT_PARAM_SPECS,
    InversionObjective,
    decode_vector,
    denormalize_vector,
    encode_params,
    normalize_vector,
)
from oer_aem.recovery import recovery_metrics, truth_library, validate_free_parameters
from oer_aem.search_policy import (
    build_scientific_parameter_selection,
    derive_cma_sigma,
    load_profile_sigma_contract,
    selection_evidence_hash,
    validate_cma_sigma,
    validate_parameter_selection_evidence,
)
from run_synthetic_recovery import build_recovery_problem, make_synthetic_target

NOISE_FRACTION = 0.001495726085983469
TARGET_SEED = 1443515106
FREE = ["k0_2", "k0_3", "G_OH", "G_O"]


def run_raw_cmaes(
    mode: str,
    seed: int,
    trials: int,
    smoke: bool = False,
    free_names: Sequence[str] = FREE,
    fixed_override: Optional[Mapping[str, float]] = None,
    init: str = "mid",
    sigma: float = 0.25,
    init_point: Optional[Mapping[str, float]] = None,
    profile_half_width: Optional[float] = None,
    profile_summary: Optional[Path] = None,
    diagnostic: bool = False,
) -> dict:
    validate_free_parameters(free_names, allow_diagnostic=diagnostic)
    if profile_half_width is not None and profile_summary is not None:
        raise ValueError("provide either profile_summary or profile_half_width, not both")
    profile_contract = None
    execution_provenance = None
    if profile_summary is not None:
        if not diagnostic:
            execution_provenance = _formal_execution_provenance()
        profile_contract = load_profile_sigma_contract(
            profile_summary,
            free_names,
            feature_mode=mode,
            expected_truth_id="mixed_b",
            expected_configuration={
                "n_points": 8192,
                "points_per_cycle": 32,
                "feature_grid_size": 128,
                "fit_harmonics": [1, 2, 3],
                "grid_points": 41,
                "noise_fraction": 0.0,
            },
            expected_source_commit=(
                str(execution_provenance["source_commit"])
                if execution_provenance is not None
                else None
            ),
        )
        profile_half_width = float(profile_contract["selected_half_width"])
    elif profile_half_width is None and not diagnostic:
        raise ValueError("formal CMA screening requires a profile summary")
    elif profile_half_width is not None and not diagnostic:
        raise ValueError(
            "formal CMA screening requires a hashed profile summary; "
            "numeric half-width is diagnostic-only"
        )
    if profile_half_width is not None:
        sigma = derive_cma_sigma(profile_half_width)
    validate_cma_sigma(sigma, diagnostic=diagnostic)
    cmaes = _load_cmaes()
    truths = truth_library(DEFAULT_PARAM_SPECS)
    truth = next(t for t in truths if t["truth_id"] == "mixed_b")
    params = truth["parameters"]  # 真值：用于生成 target 与恢复度量
    selection = build_scientific_parameter_selection(
        params,
        free_names=free_names,
        fixed_override=fixed_override,
        specs=DEFAULT_PARAM_SPECS,
        diagnostic=diagnostic,
    )
    selection_evidence = selection.to_evidence()
    validate_parameter_selection_evidence(selection_evidence, formal=not diagnostic)
    selection_hash = selection_evidence_hash(selection_evidence)
    original_truth = dict(params)
    # 优化器的固定参数：可把某个非自由参数钉在大值（准平衡区降维实验）。
    # The selection is the source of truth; do not reconstruct fixed values by
    # subtracting free names again in the runner.
    opt_truth = dict(params)
    opt_truth.update(dict(selection.fixed_params))
    effective_truth = dict(opt_truth)
    job = {
        "feature_mode": mode,
        "truth_id": "mixed_b",
        "truth_params": opt_truth,
        "noise_fraction": NOISE_FRACTION,
        "seed": seed,
        "target_seed": TARGET_SEED,
        "trials": trials,
        "free_parameters": list(free_names),
        "backend": "lsoda",
        # Keep role evidence on the job payload so any downstream input-hash
        # implementation binds the scientific assignment, not only the truth.
        "parameter_selection": selection_evidence,
        "parameter_selection_sha256": selection_hash,
        "profile_source": profile_contract,
    }
    config, free_specs = build_recovery_problem(job, smoke=smoke)
    if free_specs != selection.free_specs:
        raise RuntimeError("runner free specs diverged from parameter selection")
    config = replace(config, fixed_params=selection.fixed_params)
    target = make_synthetic_target(
        effective_truth,
        config=config,
        noise_fraction=NOISE_FRACTION,
        seed=TARGET_SEED,
    )
    objective = InversionObjective(target, config, free_specs)

    dim = len(free_specs)
    bounds = np.tile(np.array([0.0, 1.0]), (dim, 1))
    popsize = int(4 + 3 * np.log(dim))
    if init == "truth":
        # 温启动到 truth（诊断盆地稳定性：能停住说明纯探索问题）
        mean = normalize_vector(encode_params(effective_truth, free_specs), free_specs)
    elif init == "random":
        # 随机起点（多起点粗搜）
        mean = np.random.default_rng(seed).uniform(0.0, 1.0, size=dim)
    elif init == "point" and init_point is not None:
        # 从指定参数点细化（两阶段：粗搜 best → 小步长 refine）
        mean = normalize_vector(
            encode_params({k: v for k, v in init_point.items() if k in [s[0] for s in free_specs]},
                          free_specs), free_specs)
    else:
        mean = np.full(dim, 0.5)  # 盒子中点（默认，不取巧）
    optimizer = cmaes.CMA(mean=mean, sigma=sigma, bounds=bounds, seed=seed,
                          population_size=popsize)

    best_value = float("inf")
    best_z: np.ndarray | None = None
    n_eval = 0
    n_restarts = 0
    while n_eval < trials:
        # cmaes 0.13 的 ask() 每次返回一个个体；攒满一代再 tell()
        pop = min(popsize, trials - n_eval)
        xs = [optimizer.ask() for _ in range(pop)]
        vals = []
        for x in xs:
            v = objective(denormalize_vector(np.asarray(x, dtype=float), free_specs))
            vals.append(float(v))
            n_eval += 1
            if v < best_value:
                best_value = float(v)
                best_z = np.array(x, dtype=float)
        if pop < popsize:
            break  # 预算在最后一代耗尽，不 tell
        optimizer.tell(list(zip(xs, vals)))
        if optimizer.should_stop():
            n_restarts += 1
            popsize = min(popsize * 2, max(4, trials // 4))
            mean = best_z if best_z is not None else np.full(dim, 0.5)
            optimizer = cmaes.CMA(mean=mean, sigma=sigma, bounds=bounds,
                                  seed=seed + 1000 * n_restarts,
                                  population_size=popsize)

    enc_best = denormalize_vector(best_z, free_specs) if best_z is not None else None
    best_params = decode_vector(enc_best, free_specs) if enc_best is not None else {}
    metrics = recovery_metrics(
        truth=effective_truth, estimate=best_params, specs=free_specs
    )
    return {
        "mode": mode,
        "seed": seed,
        "trials": trials,
        "smoke": smoke,
        "sampler": "cmaes_raw",
        "best_value": best_value,
        "best_params": best_params,
        "n_forward": int(objective.n_forward),
        "n_ode_fail": int(objective.n_ode_fail),
        "n_feature_fail": int(objective.n_feature_fail),
        "n_tafel_fail": int(objective.n_tafel_fail),
        "n_restarts": int(n_restarts),
        "search_policy": {
            "diagnostic": bool(diagnostic),
            "profile_half_width": None if profile_half_width is None else float(profile_half_width),
            "profile_source": profile_contract,
            "execution_source": execution_provenance,
            "sigma": float(sigma),
            "role_policy": "diagnostic_opt_in" if diagnostic else "formal_fixed_roles",
            "parameter_selection": selection_evidence,
            "selection_evidence_sha256": selection_hash,
        },
        "provenance": {
            "parameter_selection": selection_evidence,
            "parameter_selection_sha256": selection_hash,
            "profile_source": profile_contract,
            "execution_source": execution_provenance,
        },
        "original_truth": original_truth,
        "effective_truth": effective_truth,
        "truth": effective_truth,
        "metrics": {
            name: {"normalized_bound_error": metrics[name]["normalized_bound_error"]}
            for name, *_ in free_specs
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="legacy",
                    choices=["legacy", "complex_snr", "lockin_only", "hybrid"])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--trials", type=int, default=500)
    ap.add_argument("--smoke", action="store_true", help="smoke 分辨率（仅自检，landscape 失真）")
    ap.add_argument("--free", default=",".join(FREE),
                    help="自由参数（逗号分隔），默认 6 个")
    ap.add_argument("--fixed-override", default=None,
                    help="把非自由参数钉在给定值，如 'k0_1=10000'（准平衡区降维）")
    ap.add_argument("--init", default="mid", choices=["mid", "truth", "random", "point"],
                    help="CMA 初始 mean：mid=盒子中点（默认）；truth=温启动；random=随机起点；"
                         "point=从 --init-point 指定参数点")
    ap.add_argument("--init-point", default=None,
                    help="--init point 时的自由参数值，如 'k0_2=0.25,k0_3=158,G_OH=1.4'")
    ap.add_argument("--sigma", type=float, default=0.25,
                    help="CMA 初始步长（z 空间）；正式路径需由 --profile-half-width 派生")
    ap.add_argument("--profile-half-width", type=float, default=None,
                    help="profile 在归一化坐标中的半宽；仅诊断路径允许裸数字")
    ap.add_argument("--profile-summary", type=Path, default=None,
                    help="正式 profile_summary.json；按所有 free 参数的最窄宽度派生 sigma")
    ap.add_argument("--diagnostic", action="store_true",
                    help="允许固定角色/大步长，仅用于诊断，不得作为 formal 证据")
    ap.add_argument("--out", default=None, help="结果 JSON 输出路径")
    args = ap.parse_args()

    free_names = [s.strip() for s in args.free.split(",") if s.strip()]
    fixed_override = None
    if args.fixed_override:
        fixed_override = {}
        for spec in args.fixed_override.split(","):
            name, _, value = spec.partition("=")
            fixed_override[name.strip()] = float(value)
    init_point = None
    if args.init_point:
        init_point = {}
        for spec in args.init_point.split(","):
            name, _, value = spec.partition("=")
            init_point[name.strip()] = float(value)

    t0 = time.perf_counter()
    res = run_raw_cmaes(args.mode, args.seed, args.trials, smoke=args.smoke,
                        free_names=free_names, fixed_override=fixed_override,
                        init=args.init, sigma=args.sigma, init_point=init_point,
                        profile_half_width=args.profile_half_width,
                        profile_summary=args.profile_summary,
                        diagnostic=args.diagnostic)
    res["runtime_seconds"] = round(time.perf_counter() - t0, 2)
    print(json.dumps(res, indent=2, default=float))
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=2, default=float))


if __name__ == "__main__":
    main()
