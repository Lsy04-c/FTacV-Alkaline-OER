"""碱性 OER AEM 微观动力学模型与 FTacV 参数反演核心包。

本包是 MATLAB 代码 OER-FTAcV/ 的 Python 翻译，包含：
- thermodynamics: AEM 热力学约束与标度关系
- physics: 预氧化 + 5 步 AEM ODE 模型与求解器
- signal: 谐波提取、滤波、DC 分量
- objective: 目标函数与参数编解码
- io: 实验数据加载与导出
- core: 统一入口封装
- defaults: 默认参数与初始化

低维主线（2026-08 起）：
- molecular_catalysis: Bonke 2016 分子催化模型（表面氧化还原 + 赝一级催化步）
- low_dim_fit: 数据截断、HarmPer 与 MLE-ExpHarmPer 目标函数
- mcmc: 自适应协方差 MCMC，输出后验与相关矩阵
"""

from .thermodynamics import apply_alkaline_aem
from .physics import OERPhysics, get_state_indices, get_param_list
from .signal import OERSignal
from .objective import OERObjective
from .io import OERIO
from .core import OERCore
from .defaults import initialize_oer_parameters
from .calibration import calibrate, derive_per_area
from .inversion import (
    DEFAULT_PARAM_SPECS,
    InversionConfig,
    InversionObjective,
    InversionResult,
    TPEInverter,
    assess_fit_quality,
    decode_vector,
    encode_params,
    make_synthetic_target,
)
from .molecular_catalysis import (
    initialize_mc_system,
    calculate_mc_steady_state,
    simulate as simulate_molecular_catalysis,
)
from .low_dim_fit import (
    FIT_HARMONICS,
    LowDimObjective,
    PARAM_NAMES,
    harm_per,
    harmonic_envelopes,
    load_truncated,
    mle_exp_harm_per,
)
from .mcmc import MCMCResult, run_adaptive_mcmc
from .importance import (
    analyze_parameter_importance,
    PERTURBATION_RULES,
    DEFAULT_PHYSICAL_BOUNDS,
)

__all__ = [
    "apply_alkaline_aem",
    "OERPhysics",
    "get_state_indices",
    "get_param_list",
    "OERSignal",
    "OERObjective",
    "OERIO",
    "OERCore",
    "initialize_oer_parameters",
    "calibrate",
    "derive_per_area",
    "DEFAULT_PARAM_SPECS",
    "InversionConfig",
    "InversionObjective",
    "InversionResult",
    "TPEInverter",
    "assess_fit_quality",
    "decode_vector",
    "encode_params",
    "make_synthetic_target",
    "initialize_mc_system",
    "calculate_mc_steady_state",
    "simulate_molecular_catalysis",
    "FIT_HARMONICS",
    "LowDimObjective",
    "PARAM_NAMES",
    "harm_per",
    "harmonic_envelopes",
    "load_truncated",
    "mle_exp_harm_per",
    "MCMCResult",
    "run_adaptive_mcmc",
    "analyze_parameter_importance",
    "PERTURBATION_RULES",
    "DEFAULT_PHYSICAL_BOUNDS",
]
