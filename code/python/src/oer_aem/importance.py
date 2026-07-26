"""参数重要性分析模块 — 局部单参数敏感性分析。

回答：在当前 AEM 模型和实验条件下，哪些参数最影响 FTacV 特征？
     哪些值得反演？哪些应固定或仅作为诊断？

用法：
    from oer_aem.importance import analyze_parameter_importance
    result = analyze_parameter_importance(base_params, config)
"""

import copy
import warnings
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .inversion import InversionConfig, extract_features
from .physics import OERPhysics
from .thermodynamics import apply_alkaline_aem
from .signal import OERSignal
from .defaults import initialize_oer_parameters

# ============================================================
# 一、扰动规则与物理边界
# ============================================================

PERTURBATION_RULES: Dict[str, Tuple[str, float]] = {
    "k0_1":   ("log10", 0.25),
    "k0_2":   ("log10", 0.25),
    "k0_3":   ("log10", 0.25),
    "k0_4":   ("log10", 0.25),
    "k0_pre": ("log10", 0.25),
    "gamma":  ("log10", 0.25),
    "G_OH":   ("linear", 0.05),
    "G_O":    ("linear", 0.05),
    "scaling_OOH_OH": ("linear", 0.05),
    "E0_pre": ("linear", 0.03),
    "Cdl":    ("percent", 0.20),
    "Ru":     ("percent", 0.20),
    "A":      ("percent", 0.05),
}

DEFAULT_PHYSICAL_BOUNDS: Dict[str, Tuple[float, float]] = {
    "k0_1":   (1e-3, 1e6),
    "k0_2":   (1e-3, 1e6),
    "k0_3":   (1e-3, 1e6),
    "k0_4":   (1e-3, 1e6),
    "k0_pre": (1e-2, 1e6),
    "gamma":  (1e-12, 1e-6),
    "G_OH":   (0.5, 2.2),
    "G_O":    (1.5, 4.0),
    "scaling_OOH_OH": (2.4, 3.8),
    "E0_pre": (1.0, 2.0),
    "Cdl":    (1e-6, 1e-3),
    "Ru":     (0.1, 500.0),
    "A":      (0.001, 10.0),
}

PARAMETER_LIST = list(PERTURBATION_RULES.keys())


def _mode_specific_feature_names(
    feature_mode: str,
    fit_harmonics: Sequence[int],
) -> List[str]:
    """Return signed feature channels that match one objective mode."""
    harmonics = tuple(sorted(int(value) for value in fit_harmonics))
    if feature_mode == "legacy":
        return [
            f"H{harmonic} {descriptor}"
            for harmonic in harmonics
            for descriptor in (
                "shape",
                "peak amplitude",
                "peak potential",
                "shape_raw",
                "peak amplitude_raw",
            )
        ]
    complex_names = [
        f"Complex H{harmonic} {component}"
        for harmonic in harmonics
        for component in ("real", "imag")
    ]
    lockin_names = [
        f"Lockin H{harmonic} {component}"
        for harmonic in harmonics
        for component in ("real", "imag")
    ]
    if feature_mode == "complex_snr":
        return complex_names
    if feature_mode == "lockin_only":
        return lockin_names
    if feature_mode in {"hybrid", "combined"}:
        return complex_names + lockin_names
    raise ValueError(f"unsupported feature mode: {feature_mode}")


def _apply_perturbation(base: float, delta: float, rule: str) -> Tuple[float, float]:
    """返回 (plus_value, minus_value)。"""
    if rule == "log10":
        lb = np.log10(max(base, 1e-30))
        return 10 ** (lb + delta), 10 ** (lb - delta)
    elif rule == "linear":
        return base + delta, base - delta
    elif rule == "percent":
        return base * (1 + delta), base / (1 + delta)
    else:
        raise ValueError(f"Unknown perturbation rule: {rule}")


def _clamped_perturbation(base: float, delta: float, rule: str, name: str
                          ) -> Tuple[float, float, Dict[str, bool]]:
    """返回 (plus, minus, flags)，超出边界的值截断并标注。"""
    plus, minus = _apply_perturbation(base, delta, rule)
    flags = {"plus_clamped": False, "minus_clamped": False}
    if name in DEFAULT_PHYSICAL_BOUNDS:
        lo, hi = DEFAULT_PHYSICAL_BOUNDS[name]
        if plus > hi:
            plus = hi; flags["plus_clamped"] = True
        if minus < lo:
            minus = lo; flags["minus_clamped"] = True
    return plus, minus, flags

# ============================================================
# 二、前向模型封装
# ============================================================

def _run_forward(params: Dict[str, Any], config: InversionConfig
                 ) -> Optional[Dict[str, Any]]:
    """运行一次 ODE 正演 + 特征提取，返回特征 dict 或 None（ODE 失败时）。"""
    p = copy.deepcopy(params)
    p["n_points"] = config.n_points
    p["points_per_cycle"] = config.points_per_cycle
    p["E_start"] = config.E_start
    p["E_end"] = config.E_end
    p["f"] = config.f
    p["dE"] = config.dE
    p["total_time"] = config.total_time
    p["t_span"] = np.linspace(0.0, float(config.total_time), config.n_points)
    p["omega"] = 2.0 * np.pi * config.f
    p["v"] = float(config.scan_rate)

    # 重新生成热力学约束
    p = apply_alkaline_aem(p)
    p = OERPhysics.initialize_system(p)

    try:
        t, y, E_actual, i_total = OERPhysics.solve_ode_system(p)
    except Exception:
        return None

    if len(i_total) == 0 or np.all(np.isnan(i_total)):
        return None

    features = extract_features(i_total, config)
    if features is None:
        return None

    # ---- 归一化特征（extract_features 已输出） ----
    dc_env = features["dc"]
    harms = features["harm"]
    e_grid = features["e_grid"]

    features["dc_amplitude"] = float(np.max(dc_env)) if len(dc_env) > 0 else 0.0
    for k, h in enumerate(harms):
        idx = int(np.argmax(h)) if len(h) > 0 else 0
        features[f"H{k+1}_peak_amplitude"] = float(h[idx])
        features[f"H{k+1}_peak_potential"] = float(e_grid[idx])

    if "complex_harmonics" in features:
        coefficients = np.asarray(
            features["complex_harmonics"]["complex"],
            dtype=complex,
        )
        for harmonic in config.fit_harmonics:
            coefficient = coefficients[harmonic - 1]
            features[f"Complex H{harmonic} real"] = float(coefficient.real)
            features[f"Complex H{harmonic} imag"] = float(coefficient.imag)
    if "lockin" in features:
        valid = np.asarray(features["lockin"]["valid_mask"], dtype=bool)
        channels = features["lockin"]["complex"]
        for harmonic in config.fit_harmonics:
            channel = np.asarray(channels[harmonic - 1], dtype=complex)
            features[f"Lockin H{harmonic} real"] = np.where(
                valid, channel.real, 0.0
            )
            features[f"Lockin H{harmonic} imag"] = np.where(
                valid, channel.imag, 0.0
            )

    onset = _extract_onset(dc_env, e_grid)
    features["onset"] = onset

    # ---- 真实幅值特征（非归一化，用于敏感性计算） ----
    df_raw = 1.0 / max(np.mean(np.diff(t)), 1e-12)
    proc = OERSignal.process_current(i_total, df_raw, p)
    raw_dc = np.asarray(proc[:, 0], dtype=float)
    features["dc_amplitude_raw"] = float(np.max(raw_dc)) if len(raw_dc) > 0 else 0.0
    features["dc_shape_raw"] = raw_dc
    for k in range(7):
        rh = np.asarray(proc[:, k+1], dtype=float)
        features[f"H{k+1}_peak_amplitude_raw"] = float(np.max(np.abs(rh))) if len(rh) > 0 else 0.0
        features[f"H{k+1}_shape_raw"] = rh

    return features


def _extract_onset(dc: np.ndarray, e_grid: np.ndarray, frac: float = 0.05) -> Optional[float]:
    """DC 包络达到最大值的 frac 倍时的电位。"""
    if len(dc) == 0:
        return None
    mx = np.max(dc)
    if mx < 1e-30:
        return None
    thresh = mx * frac
    idx = np.argmax(dc >= thresh)
    if idx is None or idx == 0:
        return None
    return float(e_grid[idx])

# ============================================================
# 三、特征距离与权重
# ============================================================

def _resolve_feature(features: Dict[str, Any], name: str) -> Any:
    if name in features:
        return features[name]
    if name == "DC shape":
        return features.get("dc")
    if name == "DC amplitude":
        return features.get("dc_amplitude")
    if name == "DC shape_raw":
        return features.get("dc_shape_raw")
    if name == "DC amplitude_raw":
        return features.get("dc_amplitude_raw")
    if name == "Tafel":
        return features.get("tafel")
    if name.startswith("H"):
        harmonic, descriptor = name.split(" ", 1)
        index = int(harmonic[1:]) - 1
        if descriptor == "shape":
            harms = features.get("harm", [])
            return harms[index] if index < len(harms) else None
        key = f"{harmonic}_{descriptor.replace(' ', '_')}"
        return features.get(key)
    return features.get(name)


def _feature_distance(fa: Dict[str, Any], fb: Dict[str, Any], name: str) -> float:
    """计算两个特征 dict 在指定特征上的归一化距离。"""
    a, b = _resolve_feature(fa, name), _resolve_feature(fb, name)
    if a is None or b is None:
        return 0.0

    a_arr = np.asarray(a, dtype=float).reshape(-1)
    b_arr = np.asarray(b, dtype=float).reshape(-1)

    if len(a_arr) > 1:
        denom = max(np.max(np.abs(a_arr)), 1e-30)
        return float(np.sqrt(np.mean((a_arr - b_arr) ** 2)) / denom)
    else:
        denom = max(abs(float(a_arr[0])), 1e-30)
        return float(abs(float(a_arr[0]) - float(b_arr[0])) / denom)


def _normalized_central_difference(
    plus: Any,
    minus: Any,
    baseline: Any,
    parameter_plus: float,
    parameter_minus: float,
    parameter_rule: str,
) -> np.ndarray | float:
    """Return a signed, baseline-normalized central-difference response."""
    plus_values = np.asarray(plus, dtype=float)
    minus_values = np.asarray(minus, dtype=float)
    baseline_values = np.asarray(baseline, dtype=float)
    if (
        plus_values.shape != minus_values.shape
        or plus_values.shape != baseline_values.shape
    ):
        raise ValueError("plus, minus, and baseline features must have matching shapes")

    if parameter_rule == "log10":
        parameter_span = np.log10(parameter_plus) - np.log10(parameter_minus)
    elif parameter_rule in {"linear", "percent"}:
        parameter_span = parameter_plus - parameter_minus
    else:
        raise ValueError(f"Unknown perturbation rule: {parameter_rule}")
    if not np.isfinite(parameter_span) or abs(parameter_span) <= np.finfo(float).eps:
        raise ValueError("parameter perturbation span must be finite and non-zero")

    feature_scale = max(float(np.max(np.abs(baseline_values))), 1e-30)
    response = (plus_values - minus_values) / parameter_span / feature_scale
    if response.ndim == 0:
        return float(response)
    return response


def _build_signed_sensitivity_matrix(
    base_features: Dict[str, Any],
    perturbed: Dict[Tuple[str, str], Optional[Dict[str, Any]]],
    base_params: Dict[str, float],
    parameter_names: Sequence[str],
    perturbation_rules: Dict[str, Tuple[str, float]],
    active_names: Sequence[str],
) -> Tuple[List[str], np.ndarray]:
    """Build a signed matrix, expanding vector features into separate rows."""
    for parameter in parameter_names:
        if (
            perturbed.get((parameter, "plus")) is None
            or perturbed.get((parameter, "minus")) is None
        ):
            raise ValueError(f"missing perturbation result for {parameter}")

    eligible_names: List[str] = []
    for feature_name in active_names:
        values = [_resolve_feature(base_features, feature_name)]
        for parameter in parameter_names:
            values.extend(
                [
                    _resolve_feature(
                        perturbed[(parameter, "plus")], feature_name
                    ),
                    _resolve_feature(
                        perturbed[(parameter, "minus")], feature_name
                    ),
                ]
            )
        if any(value is None for value in values):
            continue
        arrays = [np.asarray(value, dtype=float) for value in values]
        if any(array.shape != arrays[0].shape for array in arrays[1:]):
            continue
        if not all(np.all(np.isfinite(array)) for array in arrays):
            continue
        eligible_names.append(feature_name)

    columns: List[np.ndarray] = []
    row_names: List[str] = []
    for parameter in parameter_names:
        plus_features = perturbed.get((parameter, "plus"))
        minus_features = perturbed.get((parameter, "minus"))
        rule, delta = perturbation_rules[parameter]
        plus_parameter, minus_parameter, _ = _clamped_perturbation(
            base_params[parameter], delta, rule, parameter
        )
        values: List[float] = []
        current_names: List[str] = []
        for feature_name in eligible_names:
            baseline = _resolve_feature(base_features, feature_name)
            plus = _resolve_feature(plus_features, feature_name)
            minus = _resolve_feature(minus_features, feature_name)
            if baseline is None or plus is None or minus is None:
                continue
            response = np.asarray(
                _normalized_central_difference(
                    plus, minus, baseline, plus_parameter, minus_parameter, rule
                ),
                dtype=float,
            ).reshape(-1)
            values.extend(response.tolist())
            current_names.extend(
                [feature_name] if response.size == 1 else
                [f"{feature_name}[{index}]" for index in range(response.size)]
            )
        if not columns:
            row_names = current_names
        elif current_names != row_names:
            raise ValueError("signed sensitivity feature rows are inconsistent")
        columns.append(np.asarray(values, dtype=float))
    if not columns:
        return [], np.empty((0, 0), dtype=float)
    return row_names, np.column_stack(columns)


def _compute_feature_weights(harmonic_quality: Dict[str, Any]) -> Dict[str, float]:
    """从实验数据谐波质量报告计算特征权重（不依赖模型正演）。

    harmonic_quality 应为 assess_harmonic_quality() 的返回值，
    也可来自 /api/data/analyze 的 harmonic_quality 字段。
    """
    channels = harmonic_quality.get("channels", [])
    fit = set(harmonic_quality.get("fit_harmonics", [1,2,3]))

    w = {"DC shape": 1.0, "DC amplitude": 1.0, "DC shape_raw": 1.0,
         "DC amplitude_raw": 1.0, "Tafel": 1.0, "onset": 0.5}
    for ch in channels:
        k = ch["harmonic"]
        chosen = k in fit
        rel = float(ch.get("relative_rms", 0.0))
        hw = float(np.clip(rel if chosen else 0.0, 0.0, 1.0))
        w[f"H{k} shape"] = hw
        w[f"H{k} peak amplitude"] = hw
        w[f"H{k} peak potential"] = hw * 0.5 if chosen else 0.0
        w[f"H{k} shape_raw"] = hw
        w[f"H{k} peak amplitude_raw"] = hw
    return w

# ============================================================
# 四、敏感性评分
# ============================================================

def _compute_scores(base_features: Dict[str, Any],
                    perturbed: Dict[str, Dict[str, Any]],
                    weights: Dict[str, float],
                    active_names: List[str]) -> Dict[str, Dict[str, Any]]:
    """逐参数计算敏感性分数。perturbed: {(param, dir): features}"""
    names = list(PERTURBATION_RULES.keys())
    result = {}
    for name in names:
        plus_key = (name, "plus")
        minus_key = (name, "minus")
        f_plus = perturbed.get(plus_key)
        f_minus = perturbed.get(minus_key)

        per_feature = {}
        total_w = 0.0
        total_s = 0.0
        ode_fail = 0
        if f_plus is None: ode_fail += 1
        if f_minus is None: ode_fail += 1

        for fn in active_names:
            if fn not in weights or weights[fn] <= 0:
                continue
            d_list = []
            if f_plus is not None:
                d_list.append(_feature_distance(f_plus, base_features, fn))
            if f_minus is not None:
                d_list.append(_feature_distance(f_minus, base_features, fn))
            if not d_list:
                continue
            chg = float(np.mean(d_list))
            per_feature[fn] = chg
            total_s += chg * weights[fn]
            total_w += weights[fn]

        score = total_s / max(total_w, 1e-30) if total_w > 0 else 0.0
        result[name] = {
            "score": score,
            "per_feature_changes": per_feature,
            "ode_failures": ode_fail,
        }
    return result

# ============================================================
# 五、后处理：分级 / 主特征 / 耦合警告
# ============================================================

def _classify(score: float, ode_fail: int) -> str:
    if ode_fail >= 2:
        return "unresolved"
    if score >= 0.5: return "strong"
    if score >= 0.2: return "medium"
    if score >= 0.05: return "weak"
    return "unresolved"


def _top_features(per_feature: Dict[str, float], n: int = 3) -> List[str]:
    items = sorted(per_feature.items(), key=lambda x: x[1], reverse=True)
    return [k for k, _ in items[:n]]


def _coupling_warnings(scores: Dict[str, Dict]) -> List[str]:
    w = []
    # gamma / A / Cdl 耦合
    dc_corr = []
    for n in ["gamma", "A", "Cdl"]:
        pf = scores.get(n, {}).get("per_feature_changes", {})
        dc_corr.append(pf.get("DC amplitude", 0.0))
    if all(v > 0.05 for v in dc_corr):
        w.append("gamma、A、Cdl 均影响 DC amplitude，可能互相补偿，反演时不宜同时自由拟合。")
    # G_OH 是核心描述符
    gh = scores.get("G_OH", {}).get("per_feature_changes", {})
    if gh.get("Tafel", 0) > 0.1 and gh.get("onset", 0) > 0.1:
        w.append("G_OH 同时影响 Tafel 斜率和 onset 电位，是核心机理解释参数。")
    # k0_4 弱影响
    k4 = scores.get("k0_4", {}).get("score", 0)
    if k4 < 0.05:
        w.append("k0_4 在当前实验条件下影响极弱，不应自由反演，建议固定或给窄边界。")
    # 预氧化耦合
    ep = scores.get("E0_pre", {}).get("per_feature_changes", {})
    kp = scores.get("k0_pre", {}).get("per_feature_changes", {})
    if ep.get("H1 shape", 0) > 0.05 and kp.get("H1 shape", 0) > 0.05:
        w.append("E0_pre 和 k0_pre 可能耦合——建议先固定一个，反演另一个。")
    return w

# ============================================================
# 六、顶层入口
# ============================================================

def analyze_parameter_importance(
    base_params: Dict[str, Any],
    config: Optional[InversionConfig] = None,
    feature_weights: Optional[Dict[str, float]] = None,
    exp_harmonic_quality: Optional[Dict[str, Any]] = None,
    fit_harmonics: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """运行局部单参数敏感性分析，返回结构化重要性报告。

    Parameters
    ----------
    base_params : dict
        完整参数字典（含扫描参数和 AEM 参数）。
    config : InversionConfig, optional
        扫描配置。为 None 时自动从 base_params 推导。
    feature_weights : dict, optional
        手动指定特征权重。为 None 时从 exp_harmonic_quality 自动计算。
    exp_harmonic_quality : dict, optional
        实验数据的谐波质量报告（assess_harmonic_quality 返回值）。
        用于自动计算特征权重和决定 active harmonics。
    fit_harmonics : List[int], optional
        1-based 谐波列表（如 [1,2,3]）。传入时覆盖 exp_harmonic_quality 中的 fit_harmonics。

    Returns
    -------
    dict  with keys: active_features, diagnostic_features,
          parameter_importance, feature_weights, feature_sensitivity_matrix,
          metadata, warnings
    """
    if config is None:
        config = InversionConfig(
            E_start=base_params.get("E_start", 0.924),
            E_end=base_params.get("E_end", 1.923),
            f=base_params.get("f", 1.0),
            dE=base_params.get("dE", 0.16),
            n_points=base_params.get("n_points", 8192),
            points_per_cycle=base_params.get("points_per_cycle", 256),
            feature_grid_size=200,
        )

    # ---- 基准正演 ----
    base_features = _run_forward(base_params, config)
    if base_features is None:
        return {"success": False, "error": "基准正演失败，无法继续分析。"}

    # ---- 谐波权重与 active harmonics（来自实验数据） ----
    if exp_harmonic_quality is None:
        exp_harmonic_quality = {"fit_harmonics": fit_harmonics or [1,2,3,4,5,6,7],
                                "channels": []}
    if fit_harmonics is not None:
        exp_harmonic_quality = dict(exp_harmonic_quality)
        exp_harmonic_quality["fit_harmonics"] = fit_harmonics

    if feature_weights is None:
        feature_weights = _compute_feature_weights(exp_harmonic_quality)

    use_fit = set(exp_harmonic_quality.get("fit_harmonics", [1,2,3,4,5,6,7]))
    use_diag = {1,2,3,4,5,6,7} - use_fit

    def _build_names(tag_set):
        names = []
        for k in sorted(tag_set):
            for sfx in ["shape", "peak amplitude", "peak potential", "shape_raw", "peak amplitude_raw"]:
                name = f"H{k} {sfx}"
                if name in feature_weights and feature_weights[name] > 0:
                    names.append(name)
        return names

    active_names = (
        ["DC shape", "DC shape_raw", "DC amplitude", "DC amplitude_raw"]
        + _mode_specific_feature_names(config.feature_mode, sorted(use_fit))
        + ["Tafel", "onset"]
    )
    diag_names = _build_names(use_diag) if config.feature_mode == "legacy" else []
    for name in _mode_specific_feature_names(
        config.feature_mode, sorted(use_fit)
    ):
        feature_weights.setdefault(name, 1.0)

    # ---- 扰动循环 ----
    perturbed: Dict[Tuple[str, str], Dict] = {}
    n_forward = 0
    n_ode_fail = 0

    for name in PARAMETER_LIST:
        if name not in base_params:
            continue
        base_val = base_params[name]
        rule, delta = PERTURBATION_RULES[name]
        plus_val, minus_val, flags = _clamped_perturbation(base_val, delta, rule, name)

        for direction, dval in [("plus", plus_val), ("minus", minus_val)]:
            p = copy.deepcopy(base_params)
            p[name] = dval
            feat = _run_forward(p, config)
            n_forward += 1
            if feat is None:
                n_ode_fail += 1
                perturbed[(name, direction)] = None
            else:
                perturbed[(name, direction)] = feat

    # ---- 评分 ----
    raw_scores = _compute_scores(base_features, perturbed, feature_weights, active_names)
    signed_features, signed_matrix = _build_signed_sensitivity_matrix(
        base_features=base_features,
        perturbed=perturbed,
        base_params=base_params,
        parameter_names=[name for name in PARAMETER_LIST if name in base_params],
        perturbation_rules=PERTURBATION_RULES,
        active_names=active_names,
    )
    included_sensitivity_features = [
        name
        for name in active_names
        if name in signed_features
        or any(row.startswith(f"{name}[") for row in signed_features)
    ]
    excluded_sensitivity_features = [
        name for name in active_names
        if name not in included_sensitivity_features
    ]

    param_importance = []
    for name in PARAMETER_LIST:
        s = raw_scores.get(name, {"score": 0.0, "per_feature_changes": {}, "ode_failures": 2})
        score = s["score"]
        pf = s["per_feature_changes"]
        ode = s["ode_failures"]
        level = _classify(score, ode)
        main_f = _top_features(pf)
        clamped = (name in base_params and
                   (_clamped_perturbation(base_params[name], PERTURBATION_RULES[name][1],
                                          PERTURBATION_RULES[name][0], name)[2]["plus_clamped"]
                    or _clamped_perturbation(base_params[name], PERTURBATION_RULES[name][1],
                                             PERTURBATION_RULES[name][0], name)[2]["minus_clamped"]))
        param_importance.append({
            "name": name, "score": round(score, 4),
            "level": level, "main_features": main_f,
            "warning": None, "clamped": clamped, "ode_failures": ode,
            "per_feature_changes": {k: round(v, 4) for k, v in pf.items()},
        })

    param_importance.sort(key=lambda x: x["score"], reverse=True)

    # 耦合警告
    warnings_list = _coupling_warnings(raw_scores)

    # 敏感矩阵
    sens_matrix = []
    for fn in active_names:
        row = {"feature": fn, "changes": {}}
        for pi in param_importance:
            row["changes"][pi["name"]] = pi["per_feature_changes"].get(fn, 0.0)
        sens_matrix.append(row)

    return {
        "success": True,
        "active_features": active_names,
        "diagnostic_features": diag_names,
        "parameter_importance": param_importance,
        "feature_weights": {k: round(v, 4) for k, v in feature_weights.items()},
        "feature_sensitivity_matrix": sens_matrix,
        "included_sensitivity_features": included_sensitivity_features,
        "excluded_sensitivity_features": excluded_sensitivity_features,
        "signed_feature_sensitivity_matrix": [
            {
                "feature": feature,
                "changes": {
                    parameter: float(signed_matrix[row_index, parameter_index])
                    for parameter_index, parameter in enumerate(
                        [name for name in PARAMETER_LIST if name in base_params]
                    )
                },
            }
            for row_index, feature in enumerate(signed_features)
        ],
        "warnings": warnings_list,
        "metadata": {
            "n_forward_runs": n_forward,
            "n_ode_failures": n_ode_fail,
            "param_order": PARAMETER_LIST,
            "config": {
                "E_start": config.E_start, "E_end": config.E_end,
                "f": config.f, "dE": config.dE,
                "n_points": config.n_points,
            },
        },
    }
