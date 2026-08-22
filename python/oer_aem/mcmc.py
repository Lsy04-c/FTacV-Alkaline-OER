"""自适应协方差 MCMC（Haario AM），用于 FTacV 参数后验推断。

方法参考：
    Gundry, Kennedy, Keith, Robinson, Gavaghan, Bond, Zhang (2021)
    ChemElectroChem 8, 2238-2258.

该文比较了 7 种目标函数与两条贝叶斯路线，结论是谐波类方法优于总电流法，
并使用 Adaptive Covariance MCMC 计算后验。本模块实现同类采样器，避免为
项目引入新依赖（Legion 正式计算环境的依赖版本是钉住的）。

设计取舍记录在 `docs/superpowers/plans/2026-08-22-low-dim-bonke-model.md`：
本阶段输出后验与相关矩阵，**不**引入 phase gate 或预注册阈值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import numpy as np


@dataclass
class ChainResult:
    """单条链的采样结果。"""

    samples: np.ndarray          # (n_kept, n_params) 归一化空间
    log_posterior: np.ndarray    # (n_kept,)
    acceptance_rate: float
    seed: int


@dataclass
class MCMCResult:
    """多链采样结果与收敛诊断。"""

    chains: list = field(default_factory=list)
    names: Sequence[str] = ()
    lower: np.ndarray = None
    upper: np.ndarray = None

    @property
    def pooled_unit(self) -> np.ndarray:
        return np.concatenate([c.samples for c in self.chains], axis=0)

    @property
    def pooled(self) -> np.ndarray:
        """合并所有链，解码回真实参数空间。"""
        return self.decode(self.pooled_unit)

    def decode(self, unit: np.ndarray) -> np.ndarray:
        return self.lower + np.asarray(unit) * (self.upper - self.lower)

    def gelman_rubin(self) -> np.ndarray:
        """返回每个参数的 R-hat。需要至少 2 条等长链。"""
        if len(self.chains) < 2:
            return np.full(len(self.names), np.nan)
        n_min = min(c.samples.shape[0] for c in self.chains)
        stacked = np.stack([c.samples[-n_min:] for c in self.chains])  # (m, n, p)
        m, n, _ = stacked.shape
        chain_means = stacked.mean(axis=1)
        chain_vars = stacked.var(axis=1, ddof=1)
        within = chain_vars.mean(axis=0)
        between = n * chain_means.var(axis=0, ddof=1)
        var_hat = (n - 1) / n * within + between / n
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.sqrt(np.where(within > 0, var_hat / within, np.nan))

    def correlation(self) -> np.ndarray:
        """真实参数空间的后验相关矩阵。"""
        return np.corrcoef(self.pooled, rowvar=False)

    def summary(self) -> dict:
        pooled = self.pooled
        rhat = self.gelman_rubin()
        out = {}
        for i, name in enumerate(self.names):
            column = pooled[:, i]
            out[name] = {
                "mean": float(np.mean(column)),
                "median": float(np.median(column)),
                "std": float(np.std(column, ddof=1)),
                "q2.5": float(np.percentile(column, 2.5)),
                "q97.5": float(np.percentile(column, 97.5)),
                "rhat": float(rhat[i]),
            }
        return out


def _run_single_chain(
    log_posterior: Callable[[np.ndarray], float],
    x0_unit: np.ndarray,
    n_iterations: int,
    burn_in: int,
    thin: int,
    seed: int,
    adapt_start: int,
    target_acceptance: float,
) -> ChainResult:
    rng = np.random.default_rng(seed)
    n_params = x0_unit.size

    current = np.clip(np.asarray(x0_unit, dtype=float), 1e-6, 1 - 1e-6)
    current_lp = log_posterior(current)
    if not np.isfinite(current_lp):
        raise ValueError("MCMC 初值的后验为非有限值，请检查初值或边界")

    # Haario AM：以经验协方差自适应提议，scale 按接受率调整
    scale = 2.38 / np.sqrt(n_params)
    cov = np.eye(n_params) * (0.05 ** 2)
    mean = current.copy()
    n_accept = 0

    kept, kept_lp = [], []
    for step in range(1, n_iterations + 1):
        proposal = current + scale * rng.multivariate_normal(np.zeros(n_params), cov)
        if np.any(proposal <= 0.0) or np.any(proposal >= 1.0):
            proposal_lp = -np.inf
        else:
            proposal_lp = log_posterior(proposal)

        if np.log(rng.random()) < proposal_lp - current_lp:
            current, current_lp = proposal, proposal_lp
            n_accept += 1

        # 协方差与步长自适应（仅在 burn-in 内，之后冻结以保证细致平衡）
        if step <= burn_in:
            delta = current - mean
            mean = mean + delta / step
            cov = ((step - 1) * cov + np.outer(delta, current - mean)) / max(step, 1)
            if step > adapt_start:
                observed = n_accept / step
                scale *= np.exp((observed - target_acceptance) / np.sqrt(step))
                scale = float(np.clip(scale, 1e-4, 10.0))
            cov = cov + np.eye(n_params) * 1e-10

        if step > burn_in and (step - burn_in) % thin == 0:
            kept.append(current.copy())
            kept_lp.append(current_lp)

    return ChainResult(
        samples=np.asarray(kept),
        log_posterior=np.asarray(kept_lp),
        acceptance_rate=n_accept / n_iterations,
        seed=seed,
    )


def run_adaptive_mcmc(
    log_posterior_unit: Callable[[np.ndarray], float],
    x0_unit: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    names: Sequence[str],
    n_iterations: int = 6000,
    burn_in: Optional[int] = None,
    thin: int = 5,
    n_chains: int = 4,
    seed: int = 42,
    jitter: float = 0.05,
    adapt_start: int = 200,
    target_acceptance: float = 0.25,
) -> MCMCResult:
    """在 ``[0,1]^n`` 归一化空间运行多条自适应协方差链。

    ``log_posterior_unit`` 接受归一化向量。均匀先验由边界隐含，越界返回
    ``-inf``。各链从 ``x0_unit`` 附近的抖动点出发，以便用 R-hat 判断收敛。
    """
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    if burn_in is None:
        burn_in = n_iterations // 2

    rng = np.random.default_rng(seed)
    chains = []
    for index in range(n_chains):
        start = np.clip(
            np.asarray(x0_unit, dtype=float) + rng.normal(0.0, jitter, size=len(x0_unit)),
            1e-3,
            1 - 1e-3,
        )
        chains.append(
            _run_single_chain(
                log_posterior_unit,
                start,
                n_iterations=n_iterations,
                burn_in=burn_in,
                thin=thin,
                seed=seed + 1000 * index,
                adapt_start=adapt_start,
                target_acceptance=target_acceptance,
            )
        )

    return MCMCResult(chains=chains, names=tuple(names), lower=lower, upper=upper)
