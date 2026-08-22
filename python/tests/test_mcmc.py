"""自适应协方差 MCMC 的采样正确性测试。"""

import numpy as np
import pytest

from oer_aem.mcmc import run_adaptive_mcmc


def test_recovers_known_gaussian_posterior():
    """在已知高斯目标上，后验均值和标准差应被正确恢复。"""
    lower = np.array([-5.0, -5.0])
    upper = np.array([5.0, 5.0])
    true_mean = np.array([1.0, -2.0])
    true_std = np.array([0.5, 0.8])

    def log_posterior(unit):
        theta = lower + unit * (upper - lower)
        return float(-0.5 * np.sum(((theta - true_mean) / true_std) ** 2))

    result = run_adaptive_mcmc(
        log_posterior,
        x0_unit=np.array([0.5, 0.5]),
        lower=lower,
        upper=upper,
        names=("a", "b"),
        n_iterations=12000,
        thin=4,
        n_chains=4,
        seed=7,
    )

    summary = result.summary()
    assert summary["a"]["mean"] == pytest.approx(true_mean[0], abs=0.08)
    assert summary["b"]["mean"] == pytest.approx(true_mean[1], abs=0.12)
    assert summary["a"]["std"] == pytest.approx(true_std[0], rel=0.15)
    assert summary["b"]["std"] == pytest.approx(true_std[1], rel=0.15)


def test_recovers_known_correlation():
    """强相关目标的后验相关系数应被正确恢复。"""
    lower = np.array([-6.0, -6.0])
    upper = np.array([6.0, 6.0])
    rho = 0.8
    inv = np.linalg.inv(np.array([[1.0, rho], [rho, 1.0]]))

    def log_posterior(unit):
        theta = lower + unit * (upper - lower)
        return float(-0.5 * theta @ inv @ theta)

    result = run_adaptive_mcmc(
        log_posterior,
        x0_unit=np.array([0.5, 0.5]),
        lower=lower,
        upper=upper,
        names=("a", "b"),
        n_iterations=12000,
        thin=4,
        n_chains=4,
        seed=11,
    )
    assert result.correlation()[0, 1] == pytest.approx(rho, abs=0.08)


def test_rhat_detects_convergence():
    """收敛良好的链 R-hat 应接近 1。"""
    lower = np.array([-5.0])
    upper = np.array([5.0])

    def log_posterior(unit):
        theta = lower + unit * (upper - lower)
        return float(-0.5 * np.sum(theta ** 2))

    result = run_adaptive_mcmc(
        log_posterior,
        x0_unit=np.array([0.5]),
        lower=lower,
        upper=upper,
        names=("a",),
        n_iterations=8000,
        n_chains=4,
        seed=3,
    )
    assert result.gelman_rubin()[0] < 1.1


def test_out_of_bounds_proposals_are_rejected():
    """采样点必须全部落在给定边界内。"""
    lower = np.array([0.0])
    upper = np.array([1.0])

    result = run_adaptive_mcmc(
        lambda unit: 0.0,  # 均匀目标
        x0_unit=np.array([0.5]),
        lower=lower,
        upper=upper,
        names=("a",),
        n_iterations=3000,
        n_chains=2,
        seed=5,
    )
    pooled = result.pooled
    assert pooled.min() >= 0.0
    assert pooled.max() <= 1.0


def test_non_finite_start_is_rejected():
    with pytest.raises(ValueError):
        run_adaptive_mcmc(
            lambda unit: -np.inf,
            x0_unit=np.array([0.5]),
            lower=np.array([0.0]),
            upper=np.array([1.0]),
            names=("a",),
            n_iterations=100,
            n_chains=1,
        )
