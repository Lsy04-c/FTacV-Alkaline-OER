"""碱性 OER AEM 微观动力学模型与 FTacV 参数反演核心包。

本包是 MATLAB 代码 OER-FTAcV/ 的 Python 翻译，包含：
- thermodynamics: AEM 热力学约束与标度关系
- physics: 预氧化 + 5 步 AEM ODE 模型与求解器
- signal: 谐波提取、滤波、DC 分量
- objective: 目标函数与参数编解码
- io: 实验数据加载与导出
- core: 统一入口封装
- defaults: 默认参数与初始化
"""

from .thermodynamics import apply_alkaline_aem
from .physics import OERPhysics, get_state_indices, get_param_list
from .signal import OERSignal
from .objective import OERObjective
from .io import OERIO
from .core import OERCore
from .defaults import initialize_oer_parameters

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
]
