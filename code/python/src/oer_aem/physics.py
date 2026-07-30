"""碱性 OER 微观动力学模型（含预氧化步骤）。

模型参考：
    Bonke et al. (2016) JACS 138, 16095–16104.
    Snitkoff-Sol et al. (2024) Nat. Catal. 7, 139–147.
    Bergmann et al. (2015) Nat. Commun. 6, 8625.

反应步骤（5 步）：
    0. * + OH-  <=> *ox + H2O + e-       预氧化（Co3+ -> Co4+）
    1. *ox + OH- <=> *ox-OH + e-         AEM-1
    2. *ox-OH + OH- <=> *ox-O + H2O + e-  AEM-2
    3. *ox-O + OH- <=> *ox-OOH + e-       AEM-3
    4. *ox-OOH + OH- <=> *ox + O2 + H2O + e-  AEM-4
"""

import warnings
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, Any, Tuple, List

import numpy as np
from scipy.integrate import solve_ivp

from .thermodynamics import apply_alkaline_aem


STOICHIOMETRIC_MATRIX = np.array(
    [
        [-1.0, 0.0, 0.0, 0.0, 0.0],
        [1.0, -1.0, 0.0, 0.0, 1.0],
        [0.0, 1.0, -1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, -1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, -1.0],
    ],
    dtype=float,
)
DYNAMIC_ATOL = np.array([3e-11, 3e-11, 3e-11, 3e-11, 3e-11, 1e-8])
STEADY_STATE_ENDPOINTS = (
    5.0,
    50.0,
    500.0,
    5000.0,
    50000.0,
    500000.0,
)
STEADY_STATE_RHS_MAX = 1e-8


def get_state_indices(N: int = 2) -> SimpleNamespace:
    """返回状态变量索引。N 为扩散网格点数（当前模型 N=2，暂不含传质）。"""
    _ = N  # 保留参数以兼容 MATLAB 接口
    idx = SimpleNamespace()
    idx.theta_star = 0    # *   — 还原态 Co 位点
    idx.theta_ox = 1      # *ox — 氧化态 Co 位点（OER 活性位）
    idx.theta_OH = 2      # *ox-OH
    idx.theta_O = 3       # *ox-O
    idx.theta_OOH = 4     # *ox-OOH
    idx.phi_s = 5         # 表面电位 (V)
    idx.num_states = 6    # 不含传质时为 6
    return idx


def get_param_list() -> List[str]:
    """返回与 MEX 兼容的参数名顺序（保留用于 API 兼容）。"""
    return [
        'E_start', 'v', 'dE', 'omega',        # 1-4
        'Ru', 'Cdl', 'A', 'gamma',             # 5-8
        'k0_pre', 'k0_1', 'k0_2', 'k0_3', 'k0_4',  # 9-13
        'E0_pre', 'E01', 'E02', 'E03', 'E04',  # 14-18
        'a', 'RTF', 'invRC',                   # 19-21
        'gammaF_Cdl',                          # 22
        'n_points', 'total_time', 'N'          # 23-25
    ]


def validate_physics_parameters(
    params: Dict[str, Any],
    *,
    require_time_grid: bool = False,
) -> None:
    """Reject values outside the numerical domain of the current ODE model."""
    strictly_positive = (
        "Ru",
        "Cdl",
        "A",
        "gamma",
        "F",
        "R",
        "T",
        "f",
    )
    nonnegative = (
        "k0_pre",
        "k0_1",
        "k0_2",
        "k0_3",
        "k0_4",
        "dE",
    )
    finite_fields = (
        "E_start",
        "v",
        "E0_pre",
        "E01",
        "E02",
        "E03",
        "E04",
    )
    for name in strictly_positive:
        value = float(params[name])
        if not np.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and strictly positive")
    for name in nonnegative:
        value = float(params[name])
        if not np.isfinite(value) or value < 0.0:
            raise ValueError(f"{name} must be finite and nonnegative")
    for name in finite_fields:
        if not np.isfinite(float(params[name])):
            raise ValueError(f"{name} must be finite")
    transfer = float(params.get("a", 0.5))
    if not np.isfinite(transfer) or not 0.0 <= transfer <= 1.0:
        raise ValueError("a must be finite and within [0, 1]")
    beta = float(params.get("beta_recon", 0.0))
    if not np.isfinite(beta) or beta < 0.0:
        raise ValueError("beta_recon must be finite and nonnegative")
    if beta > 0.0:
        width = float(params.get("w_recon", np.nan))
        if not np.isfinite(width) or width <= 0.0:
            raise ValueError(
                "w_recon must be finite and positive when beta_recon > 0"
            )
    if require_time_grid:
        total_time = float(params["total_time"])
        if not np.isfinite(total_time) or total_time <= 0.0:
            raise ValueError(
                "total_time must be finite and strictly positive"
            )
        grid = np.asarray(params["t_span"], dtype=float)
        if (
            grid.ndim != 1
            or len(grid) < 2
            or not np.all(np.isfinite(grid))
            or np.any(np.diff(grid) <= 0.0)
            or grid[0] < 0.0
            or grid[-1] > total_time
        ):
            raise ValueError(
                "t_span must be finite, strictly increasing, and within "
                "[0, total_time]"
            )


def pack_parameters(params: Dict[str, Any]) -> np.ndarray:
    """将参数字典打包为向量（保留 MATLAB 兼容顺序）。"""
    basic = get_param_list()
    n_basic = len(basic)
    vec = np.zeros(n_basic + 8 + 8)
    for i, name in enumerate(basic):
        if name in params:
            vec[i] = params[name]
        else:
            raise KeyError(f'缺少参数: {name}')

    base = n_basic
    if 'band' in params:
        vec[base:base + 8] = np.asarray(params['band']).reshape(8)
    base += 8
    if 'harmonic_weights' in params:
        vec[base:base + 8] = np.asarray(params['harmonic_weights']).reshape(8)
    return vec


def initialize_system(params: Dict[str, Any]) -> Dict[str, Any]:
    """填充默认值并计算派生物理常数。"""
    params = dict(params)

    # 默认值
    params.setdefault('a', 0.5)
    params.setdefault('N', 2)
    params.setdefault('band', np.ones(8) * 0.01)
    params.setdefault('harmonic_weights', np.ones(8))
    params.setdefault('use_steady_state', True)
    params.setdefault('use_mex', False)
    params.setdefault('use_fft', True)

    params.setdefault('F', 96485.0)
    params.setdefault('R', 8.314)
    params.setdefault('T', 298.15)

    validate_physics_parameters(params)

    # 衍生常数
    params['RTF'] = params['F'] / (params['R'] * params['T'])
    params['invRC'] = 1.0 / (params['Ru'] * params['Cdl'] * params['A'])
    params['gammaF_Cdl'] = params['gamma'] * params['F'] / params['Cdl']
    params['omega'] = 2 * np.pi * params['f']

    return params


def _safe_exp(x):
    """安全的 exp，防止 BV 指数过大导致 overflow。"""
    x = np.asarray(x, dtype=float)
    return np.exp(np.clip(x, -708, 708))


def effective_gamma(E, params):
    """Return fixed M0 site density or the opt-in M1 reconstruction profile."""
    gamma = float(params.get('gamma', 3e-9))
    beta = float(params.get('beta_recon', 0.0))
    potential = np.asarray(E, dtype=float)
    if beta == 0.0:
        return np.zeros_like(potential) + gamma

    center = float(params.get('E_recon', 1.55))
    width = max(float(params.get('w_recon', 0.05)), 1e-6)
    scaled = np.clip((potential - center) / width, -60.0, 60.0)
    return gamma * (1.0 + beta / (1.0 + np.exp(-scaled)))


@dataclass(frozen=True)
class ElementaryRates:
    """One instantaneous evaluation of the five elementary net rates."""

    applied_potential: float
    overpotentials: np.ndarray
    forward_constants: np.ndarray
    reverse_constants: np.ndarray
    net: np.ndarray
    normalized_coverages: np.ndarray
    original_coverage_sum: float


@dataclass(frozen=True)
class CurrentComponents:
    """Instantaneous external, capacitive and faradaic currents in amperes."""

    solution: float
    capacitive: float
    faradaic: float
    closure_residual: float


@dataclass(frozen=True)
class SteadyStateAttempt:
    """One bounded Radau relaxation stage."""

    elapsed_s: float
    rhs_norm: float
    success: bool
    message: str
    nfev: int


@dataclass(frozen=True)
class SteadyStateSolution:
    """Validated steady state plus adaptive-relaxation provenance."""

    state: np.ndarray
    elapsed_s: float
    rhs_norm: float
    attempts: tuple[SteadyStateAttempt, ...]


@dataclass(frozen=True)
class SolverAttempt:
    """One dynamic solver attempt and its observable completion state."""

    backend: str
    success: bool
    message: str
    nfev: int
    returned_points: int


@dataclass(frozen=True)
class ODESolution:
    """Dynamic trajectory with explicit backend provenance."""

    t: np.ndarray
    y: np.ndarray
    E_actual: np.ndarray
    i_total: np.ndarray
    backend_used: str
    fallback_used: bool
    attempts: tuple[SolverAttempt, ...]
    steady_state_elapsed_s: float | None
    steady_state_rhs_norm: float | None
    steady_state_attempts: tuple[SteadyStateAttempt, ...]


class DynamicSolverError(RuntimeError):
    """All registered dynamic backends failed."""

    def __init__(
        self,
        message: str,
        attempts: tuple[SolverAttempt, ...],
        *,
        steady_state: SteadyStateSolution | None = None,
    ):
        super().__init__(message)
        self.attempts = attempts
        self.steady_state_elapsed_s = (
            steady_state.elapsed_s if steady_state is not None else None
        )
        self.steady_state_rhs_norm = (
            steady_state.rhs_norm if steady_state is not None else None
        )
        self.steady_state_attempts = (
            steady_state.attempts if steady_state is not None else ()
        )


def elementary_rates(
    t: float,
    y: np.ndarray,
    params: Dict[str, Any],
    *,
    validate: bool = True,
) -> ElementaryRates:
    """Evaluate the existing five-step BV kinetics without state derivatives."""
    if validate:
        validate_physics_parameters(params)
    state = np.asarray(y, dtype=float)
    if state.shape != (6,):
        raise ValueError("physics state must contain six values")
    coverage = state[:5].copy()
    coverage_sum = float(np.sum(coverage))
    if coverage_sum > 1e-12:
        coverage /= coverage_sum
    theta_star, theta_ox, theta_OH, theta_O, theta_OOH = coverage
    phi_s = float(state[5])

    E_dc = params["E_start"] + params["v"] * t
    E_app = E_dc + params["dE"] * np.sin(params["omega"] * t)
    overpotentials = np.array(
        [
            phi_s - params["E0_pre"],
            phi_s - params["E01"],
            phi_s - params["E02"],
            phi_s - params["E03"],
            phi_s - params["E04"],
        ],
        dtype=float,
    )
    RTF = params["RTF"]
    a = params["a"]
    b = 1.0 - a
    k0 = np.array(
        [
            params["k0_pre"],
            params["k0_1"],
            params["k0_2"],
            params["k0_3"],
            params["k0_4"],
        ],
        dtype=float,
    )
    forward_exponents = b * RTF * overpotentials
    reverse_exponents = -a * RTF * overpotentials
    forward = np.array(
        [
            min(k0[index] * _safe_exp(value), 1e100)
            if value < 600
            else 1e100
            for index, value in enumerate(forward_exponents)
        ],
        dtype=float,
    )
    reverse = np.array(
        [
            min(k0[index] * _safe_exp(value), 1e100)
            if value < 600
            else 1e100
            for index, value in enumerate(reverse_exponents)
        ],
        dtype=float,
    )
    net = np.array(
        [
            forward[0] * theta_star - reverse[0] * theta_ox,
            forward[1] * theta_ox - reverse[1] * theta_OH,
            forward[2] * theta_OH - reverse[2] * theta_O,
            forward[3] * theta_O - reverse[3] * theta_OOH,
            forward[4] * theta_OOH - reverse[4] * theta_ox,
        ],
        dtype=float,
    )
    return ElementaryRates(
        applied_potential=float(E_app),
        overpotentials=overpotentials,
        forward_constants=forward,
        reverse_constants=reverse,
        net=net,
        normalized_coverages=coverage,
        original_coverage_sum=coverage_sum,
    )


def coverage_derivatives(net_rates: np.ndarray) -> np.ndarray:
    """Map five elementary rates to five coverage derivatives."""
    rates = np.asarray(net_rates, dtype=float)
    if rates.shape != (5,):
        raise ValueError("net rates must contain five values")
    return STOICHIOMETRIC_MATRIX @ rates


def _surface_potential_derivative(
    rates: ElementaryRates,
    phi_s: float,
    params: Dict[str, Any],
) -> float:
    gamma_eff = float(
        effective_gamma(rates.applied_potential, params)
    )
    gammaF_Cdl_eff = gamma_eff * params["F"] / params["Cdl"]
    return float(
        (rates.applied_potential - phi_s) * params["invRC"]
        - gammaF_Cdl_eff * float(np.sum(rates.net))
    )


def current_components(
    t: float,
    y: np.ndarray,
    params: Dict[str, Any],
) -> CurrentComponents:
    """Return the three currents implied by the existing circuit equation."""
    validate_physics_parameters(params)
    state = np.asarray(y, dtype=float)
    if state.shape != (6,) or not np.all(np.isfinite(state)):
        raise ValueError("physics state must contain six finite values")
    rates = elementary_rates(t, state, params, validate=False)
    dphi_s = _surface_potential_derivative(
        rates, float(state[5]), params
    )
    solution = float(
        (rates.applied_potential - state[5]) / params["Ru"]
    )
    capacitive = float(params["Cdl"] * params["A"] * dphi_s)
    gamma_eff = float(
        effective_gamma(rates.applied_potential, params)
    )
    faradaic = float(
        gamma_eff
        * params["F"]
        * params["A"]
        * float(np.sum(rates.net))
    )
    return CurrentComponents(
        solution=solution,
        capacitive=capacitive,
        faradaic=faradaic,
        closure_residual=float(solution - capacitive - faradaic),
    )


def validate_steady_state(
    state: np.ndarray,
    params: Dict[str, Any],
    *,
    rhs_t: float,
) -> float:
    """Validate one relaxed state and return its RHS infinity norm."""
    values = np.asarray(state, dtype=float)
    if values.shape != (6,) or not np.all(np.isfinite(values)):
        raise RuntimeError("steady state must contain six finite values")
    coverage = values[:5]
    if (
        float(np.min(coverage)) < -1e-8
        or float(np.max(coverage)) > 1.0 + 1e-8
    ):
        raise RuntimeError("steady-state coverage is outside physical range")
    coverage_sum = float(np.sum(coverage))
    if abs(coverage_sum - 1.0) > 1e-8:
        raise RuntimeError(
            f"steady-state coverage sum is {coverage_sum:.12g}"
        )
    derivative = _oer_model_rhs(float(rhs_t), values, params)
    rhs_norm = float(np.max(np.abs(derivative)))
    if not np.isfinite(rhs_norm) or rhs_norm > 1e-8:
        raise RuntimeError(
            f"steady-state RHS infinity norm is {rhs_norm:.12g}"
        )
    return rhs_norm


def _oer_model_rhs(t: float, y: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
    """ODE 右端函数（内部实现）。"""
    y = np.asarray(y, dtype=float)
    phi_s = y[5]
    rates = elementary_rates(t, y, params, validate=False)
    dtheta = coverage_derivatives(rates.net)

    # M0 uses fixed gamma. M1 is enabled only by beta_recon > 0.
    dphi_s = _surface_potential_derivative(rates, phi_s, params)

    return np.concatenate([dtheta, [dphi_s]])


class OERPhysics:
    """碱性 OER 物理模型入口类（对应 MATLAB OER_Physics）。"""

    @staticmethod
    def get_state_indices(N: int = 2) -> SimpleNamespace:
        return get_state_indices(N)

    @staticmethod
    def get_param_list() -> List[str]:
        return get_param_list()

    @staticmethod
    def pack_parameters(params: Dict[str, Any]) -> np.ndarray:
        return pack_parameters(params)

    @staticmethod
    def initialize_system(params: Dict[str, Any]) -> Dict[str, Any]:
        return initialize_system(params)

    @staticmethod
    def oer_model(t: float, y: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        return _oer_model_rhs(t, y, params)

    @staticmethod
    def solve_ode_system_detailed(params: Dict[str, Any]) -> ODESolution:
        """Solve the trajectory with explicit LSODA-to-BDF provenance."""
        if 'RTF' not in params:
            params = initialize_system(params)
        validate_physics_parameters(params, require_time_grid=True)

        y0 = np.zeros(6)
        y0[0] = 1.0
        y0[5] = params['E_start']

        steady_state = None
        if params.get('use_steady_state', True):
            steady_state = OERPhysics.calculate_steady_state_detailed(params)
            y0 = steady_state.state

        t_span = (0.0, float(params['total_time']))
        t_eval = np.asarray(params['t_span'])
        if t_eval.ndim == 0 or len(t_eval) == 0:
            t_eval = np.linspace(0.0, t_span[1], int(params['n_points']))

        attempts = []
        successful = None
        backend_used = ""
        for backend in ("LSODA", "BDF"):
            kwargs = {
                "fun": lambda t, y: _oer_model_rhs(t, y, params),
                "t_span": t_span,
                "y0": y0.copy(),
                "t_eval": t_eval,
                "method": backend,
                "rtol": 1e-6,
                "atol": DYNAMIC_ATOL.copy(),
                "max_step": min(
                    t_span[1] / 50.0,
                    1.0 / (params['f'] * 20),
                ),
            }
            if backend == "LSODA":
                kwargs["first_step"] = 1e-8
            try:
                sol = solve_ivp(**kwargs)
                complete = bool(
                    sol.success
                    and len(sol.t) == len(t_eval)
                    and np.asarray(sol.y).shape == (6, len(t_eval))
                )
                message = str(sol.message)
                if sol.success and not complete:
                    message = (
                        f"{message}; incomplete output "
                        f"{len(sol.t)}/{len(t_eval)}"
                    )
                attempts.append(
                    SolverAttempt(
                        backend=backend,
                        success=complete,
                        message=message,
                        nfev=int(getattr(sol, "nfev", -1)),
                        returned_points=int(len(sol.t)),
                    )
                )
                if complete:
                    successful = sol
                    backend_used = backend
                    break
            except Exception as exc:  # noqa: BLE001
                attempts.append(
                    SolverAttempt(
                        backend=backend,
                        success=False,
                        message=f"{type(exc).__name__}: {exc}",
                        nfev=-1,
                        returned_points=0,
                    )
                )
        if successful is None:
            detail = "; ".join(
                f"{item.backend}: {item.message}" for item in attempts
            )
            raise DynamicSolverError(
                f"dynamic solvers failed: {detail}",
                tuple(attempts),
                steady_state=steady_state,
            )

        t = np.asarray(successful.t, dtype=float)
        y = np.asarray(successful.y, dtype=float).T
        E_dc = params['E_start'] + params['v'] * t
        E_actual = E_dc + params['dE'] * np.sin(params['omega'] * t)
        i_total = (E_actual - y[:, 5]) / params['Ru']
        return ODESolution(
            t=t,
            y=y,
            E_actual=E_actual,
            i_total=i_total,
            backend_used=backend_used,
            fallback_used=backend_used != "LSODA",
            attempts=tuple(attempts),
            steady_state_elapsed_s=(
                steady_state.elapsed_s if steady_state is not None else None
            ),
            steady_state_rhs_norm=(
                steady_state.rhs_norm if steady_state is not None else None
            ),
            steady_state_attempts=(
                steady_state.attempts if steady_state is not None else ()
            ),
        )

    @staticmethod
    def solve_ode_system(params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """求解 ODE 系统，返回 (t, y, E_actual, i_total)。"""
        try:
            result = OERPhysics.solve_ode_system_detailed(params)
            return result.t, result.y, result.E_actual, result.i_total
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f'ODE 求解失败: {exc}', stacklevel=2)
            num_states = 6
            t = np.asarray(params['t_span']).reshape(-1)
            y = np.full((len(t), num_states), np.nan)
            E_actual = np.full(len(t), np.nan)
            i_total = np.full(len(t), np.nan)

        return t, y, E_actual, i_total

    @staticmethod
    def calculate_steady_state_detailed(
        params: Dict[str, Any],
    ) -> SteadyStateSolution:
        """Relax at the starting potential until the frozen RHS gate passes."""
        num_states = 6
        y0_guess = np.zeros(num_states)
        y0_guess[0] = 1.0
        y0_guess[5] = params['E_start']

        params_ss = dict(params)
        params_ss['v'] = 0.0
        params_ss['dE'] = 0.0
        params_ss['omega'] = 0.0
        params_ss = initialize_system(params_ss)

        attempts = []
        state = y0_guess
        elapsed = 0.0
        final_rhs = float("inf")
        for endpoint in STEADY_STATE_ENDPOINTS:
            segment_duration = endpoint - elapsed
            sol = solve_ivp(
                fun=lambda t, y: _oer_model_rhs(t, y, params_ss),
                t_span=(elapsed, endpoint),
                y0=state,
                method='Radau',
                rtol=1e-4,
                atol=1e-6,
                max_step=segment_duration / 50.0,
            )
            if not sol.success:
                final_time = float(sol.t[-1]) if len(sol.t) else elapsed
                raise RuntimeError(
                    "steady-state solver failed at "
                    f"t={final_time:.6g}/{endpoint:.6g}: {sol.message}"
                )
            candidate = np.asarray(sol.y[:, -1], dtype=float)
            if candidate.shape != (num_states,) or not np.all(
                np.isfinite(candidate)
            ):
                raise RuntimeError(
                    f"steady-state stage at {endpoint:g} s returned invalid state"
                )
            coverage = candidate[:5]
            if (
                float(np.min(coverage)) < -1e-8
                or float(np.max(coverage)) > 1.0 + 1e-8
                or abs(float(np.sum(coverage)) - 1.0) > 1e-8
            ):
                raise RuntimeError(
                    f"steady-state stage at {endpoint:g} s violated coverage"
                )
            final_rhs = float(
                np.max(np.abs(_oer_model_rhs(endpoint, candidate, params_ss)))
            )
            attempts.append(
                SteadyStateAttempt(
                    elapsed_s=float(endpoint),
                    rhs_norm=final_rhs,
                    success=True,
                    message=str(sol.message),
                    nfev=int(getattr(sol, "nfev", -1)),
                )
            )
            state = candidate
            elapsed = float(endpoint)
            if final_rhs <= STEADY_STATE_RHS_MAX:
                validate_steady_state(state, params_ss, rhs_t=elapsed)
                return SteadyStateSolution(
                    state=state,
                    elapsed_s=elapsed,
                    rhs_norm=final_rhs,
                    attempts=tuple(attempts),
                )
        raise RuntimeError(
            "steady-state did not reach the frozen RHS gate by "
            f"{elapsed:g} s: RHS infinity norm is {final_rhs:.12g}"
        )

    @staticmethod
    def calculate_steady_state(params: Dict[str, Any]) -> np.ndarray:
        """Return the validated adaptive steady-state vector."""
        return OERPhysics.calculate_steady_state_detailed(params).state

    @staticmethod
    def apply_default_E0(params: Dict[str, Any]) -> Dict[str, Any]:
        """若未提供 E0_pre，使用默认或从自由能生成。"""
        params = dict(params)
        if 'E0_pre' not in params and 'G_OH' in params:
            params = OERPhysics.apply_alkaline_aem_embedded(params)
        elif 'E0_pre' not in params:
            params['E0_pre'] = 1.50
            params['E01'] = 1.55
            params['E02'] = 1.60
            params['E03'] = 1.70
            params['E04'] = 1.45
        return params

    @staticmethod
    def apply_alkaline_aem_embedded(params: Dict[str, Any]) -> Dict[str, Any]:
        """内嵌版 AEM 热力学约束（调用独立模块）。"""
        params = dict(params)
        if 'E0_pre' not in params:
            params['E0_pre'] = 1.50
        return apply_alkaline_aem(params)


# 保持模块级别名，方便直接导入
apply_alkaline_aem_embedded = OERPhysics.apply_alkaline_aem_embedded
apply_default_E0 = OERPhysics.apply_default_E0
