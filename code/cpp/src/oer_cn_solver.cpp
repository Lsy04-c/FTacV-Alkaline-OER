/* oer_cn_solver.cpp — 6-state OER Crank-Nicolson Newton solver.
 * Matches the algorithm in simulate_walker from OER_Core_Mex,
 * adapted for the simpler 6-state model (no θ_OO, no transport).
 *
 * Build: c++ -O3 -march=native -shared -fPIC -std=c++17 -o liboercn.dylib oer_cn_solver.cpp
 */

#include <cmath>
#include <cstring>
#include <algorithm>
#include <cstdio>

extern "C" {

/* ------ parameter layout (32 doubles, matching Python params_from_vector) ------ */
enum {
    P_E_START, P_E_END, P_F, P_DE,
    P_RU, P_CDL, P_A, P_GAMMA,
    P_K0_1, P_K0_2, P_K0_3, P_K0_4, P_K0_PRE,
    P_G_OH, P_G_O, P_SCALING, P_ALPHA,
    P_E01, P_E02, P_E03, P_E04, P_E0_PRE,
    P_RTF, P_INVRC, P_GAMMAF_CDL, P_TOTAL_TIME, P_SCAN_RATE,
    P_OMEGA, P_BETA_RECON, P_E_RECON, P_W_RECON, P_FARADAY,
    P_N_FIELDS
};

#define NSTATE 6

/* Minimum internal CN subdivisions per requested output interval.  The
 * default keeps easy screen cases fast; formal experiments may compile a
 * stricter build with -DCN_MIN_SUBDIVISIONS=4 or 8 and record that flag. */
#ifndef CN_MIN_SUBDIVISIONS
#define CN_MIN_SUBDIVISIONS 1
#endif

/* ------ helpers ------ */
static inline double safe_exp(double x) {
    if (x > 100.0)  return 2.6881171418161356e43;
    if (x < -100.0) return 0.0;
    return std::exp(x);
}
static inline double clamp01(double x) { return (x < 0.0) ? 0.0 : ((x > 1.0) ? 1.0 : x); }

/* ------ 6×6 dense LU solve (in-place, column-major: A[col*N + row]) ------ */
static int solve6(double* A, double* b) {
    int piv[NSTATE];
    for (int i = 0; i < NSTATE; ++i) piv[i] = i;
    for (int col = 0; col < NSTATE; ++col) {
        // Find pivot in column 'col', rows col..N-1
        int best = col;
        double bv = std::abs(A[col * NSTATE + best]);
        for (int r = col + 1; r < NSTATE; ++r) {
            double v = std::abs(A[col * NSTATE + r]);
            if (v > bv) { bv = v; best = r; }
        }
        if (bv < 1e-30) return -1;
        if (best != col) {
            std::swap(piv[col], piv[best]);
            // Swap ROWS 'col' and 'best': swap A[c*N + col] ↔ A[c*N + best] for all c
            for (int c = 0; c < NSTATE; ++c)
                std::swap(A[c * NSTATE + col], A[c * NSTATE + best]);
        }
        double inv = 1.0 / A[col * NSTATE + col];
        for (int r = col + 1; r < NSTATE; ++r) {
            double f = A[col * NSTATE + r] * inv;
            A[col * NSTATE + r] = f;  // store L[r][col]
            for (int c = col + 1; c < NSTATE; ++c)
                A[c * NSTATE + r] -= f * A[c * NSTATE + col];
        }
    }
    // Forward: solve L*y = P*b (L stored in lower triangle of A)
    double y[NSTATE];
    for (int i = 0; i < NSTATE; ++i) {
        y[i] = b[piv[i]];
        for (int j = 0; j < i; ++j)
            y[i] -= A[j * NSTATE + i] * y[j];  // L[i][j] = A[col=j, row=i]
    }
    // Backward: solve U*x = y (U stored in upper triangle of A)
    for (int i = NSTATE - 1; i >= 0; --i) {
        double s = y[i];
        for (int j = i + 1; j < NSTATE; ++j)
            s -= A[j * NSTATE + i] * b[j];  // U[i][j] = A[col=j, row=i]
        b[i] = s / A[i * NSTATE + i];
    }
    return 0;
}

/* ------ effective gamma ------ */
static inline double eff_gamma(double E, const double* p) {
    double g = p[P_GAMMA], beta = p[P_BETA_RECON];
    if (beta <= 0) return g;
    double c = p[P_E_RECON], w = std::max(p[P_W_RECON], 1e-6);
    double x = std::max(-60.0, std::min(60.0, (E - c) / w));
    return g * (1.0 + beta / (1.0 + std::exp(-x)));
}

/* ------ RHS + analytical Jacobian ------ */
static void rhs_and_jac(
    double t, const double* y, const double* p,
    double f[NSTATE], double J[NSTATE * NSTATE])
{
    double th_s = y[0], th_ox = y[1], th_OH = y[2];
    double th_O = y[3], th_OOH = y[4], phi = y[5];

    double sum = th_s + th_ox + th_OH + th_O + th_OOH;
    if (sum > 1e-12) { double inv = 1.0 / sum;
        th_s *= inv; th_ox *= inv; th_OH *= inv;
        th_O *= inv; th_OOH *= inv; }

    double E = p[P_E_START] + p[P_SCAN_RATE] * t + p[P_DE] * std::sin(p[P_OMEGA] * t);
    double RTF = p[P_RTF], a = p[P_ALPHA], b = 1.0 - a;
    double bRTF = b * RTF, maRTF = -a * RTF;

    double ep = phi - p[P_E0_PRE], e1 = phi - p[P_E01], e2 = phi - p[P_E02];
    double e3 = phi - p[P_E03], e4 = phi - p[P_E04];

    auto kbv = [&](double k0, double eta, double& kf, double& kr, double& dkf, double& dkr) {
        kf = ( bRTF * eta < 600) ? k0 * safe_exp( bRTF * eta) : 1e100;
        kr = (maRTF * eta < 600) ? k0 * safe_exp(maRTF * eta) : 1e100;
        dkf = kf *  bRTF;
        dkr = kr * maRTF;
    };

    double kfp,krp,kf1,kr1,kf2,kr2,kf3,kr3,kf4,kr4;
    double dkfp,dkrp,dkf1,dkr1,dkf2,dkr2,dkf3,dkr3,dkf4,dkr4;
    kbv(p[P_K0_PRE], ep, kfp, krp, dkfp, dkrp);
    kbv(p[P_K0_1],   e1, kf1, kr1, dkf1, dkr1);
    kbv(p[P_K0_2],   e2, kf2, kr2, dkf2, dkr2);
    kbv(p[P_K0_3],   e3, kf3, kr3, dkf3, dkr3);
    kbv(p[P_K0_4],   e4, kf4, kr4, dkf4, dkr4);

    double a_OH = 1.0, a_H2O = 1.0;
    double rp = kfp * th_s   * a_OH - krp * th_ox * a_H2O;
    double r1 = kf1 * th_ox  * a_OH - kr1 * th_OH;
    double r2 = kf2 * th_OH  * a_OH - kr2 * th_O  * a_H2O;
    double r3 = kf3 * th_O   * a_OH - kr3 * th_OOH;
    double r4 = kf4 * th_OOH * a_OH - kr4 * th_ox * a_H2O;

    f[0] = -rp;
    f[1] =  rp - r1 + r4;
    f[2] =  r1 - r2;
    f[3] =  r2 - r3;
    f[4] =  r3 - r4;

    double g_eff  = eff_gamma(E, p);
    double gF_Cdl = g_eff * p[P_FARADAY] / p[P_CDL];
    double r_elec = rp + r1 + r2 + r3 + r4;
    f[5] = (E - phi) * p[P_INVRC] - gF_Cdl * r_elec;

    // Non-negative clamping for coverage derivatives
    bool clamped[NSTATE] = {false};
    for (int i = 0; i < 5; ++i) {
        if (y[i] <= 0 && f[i] < 0) { f[i] = 0; clamped[i] = true; }
    }

    if (!J) return;
    std::memset(J, 0, NSTATE * NSTATE * sizeof(double));

    // Row 0: dθ*/dt
    J[0*6+0] = -kfp;   J[1*6+0] =  krp;
    J[5*6+0] = -(dkfp * th_s - dkrp * th_ox);

    // Row 1: dθox/dt
    J[0*6+1] =  kfp;   J[1*6+1] = -krp - kf1 - kr4;
    J[2*6+1] =  kr1;   J[4*6+1] =  kf4;
    J[5*6+1] = (dkfp*th_s - dkrp*th_ox) - (dkf1*th_ox - dkr1*th_OH)
             + (dkf4*th_OOH - dkr4*th_ox);

    // Row 2: dθOH/dt
    J[1*6+2] =  kf1;   J[2*6+2] = -kr1 - kf2;
    J[3*6+2] =  kr2;
    J[5*6+2] = (dkf1*th_ox - dkr1*th_OH) - (dkf2*th_OH - dkr2*th_O);

    // Row 3: dθO/dt
    J[2*6+3] =  kf2;   J[3*6+3] = -kr2 - kf3;
    J[4*6+3] =  kr3;
    J[5*6+3] = (dkf2*th_OH - dkr2*th_O) - (dkf3*th_O - dkr3*th_OOH);

    // Row 4: dθOOH/dt
    J[3*6+4] =  kf3;   J[4*6+4] = -kr3 - kf4;
    J[1*6+4] =  kr4;
    J[5*6+4] = (dkf3*th_O - dkr3*th_OOH) - (dkf4*th_OOH - dkr4*th_ox);

    // Row 5: dφ/dt = (E-φ)*invRC - gF_Cdl * (rp + r1 + r2 + r3 + r4)
    // ∂/∂(θ*)   = -gF_Cdl * kfp
    // ∂/∂(θox)  = -gF_Cdl * (-krp - kf1 - kr4) = +gF_Cdl*(krp + kf1 + kr4)
    // ∂/∂(θOH)  = -gF_Cdl * (-kr1 + kf2) = +gF_Cdl*(kr1 - kf2)
    // ∂/∂(θO)   = -gF_Cdl * (-kr2 + kf3) = +gF_Cdl*(kr2 - kf3)
    // ∂/∂(θOOH) = -gF_Cdl * (-kr3 + kf4) = +gF_Cdl*(kr3 - kf4)
    double dr_dphi = (dkfp*th_s - dkrp*th_ox) + (dkf1*th_ox - dkr1*th_OH)
                   + (dkf2*th_OH - dkr2*th_O) + (dkf3*th_O - dkr3*th_OOH)
                   + (dkf4*th_OOH - dkr4*th_ox);
    J[5*6+5] = -p[P_INVRC] - gF_Cdl * dr_dphi;
    J[0*6+5] = -gF_Cdl * kfp;
    J[1*6+5] =  gF_Cdl * (krp + kf1 + kr4);
    J[2*6+5] =  gF_Cdl * (kr1 - kf2);
    J[3*6+5] =  gF_Cdl * (kr2 - kf3);
    J[4*6+5] =  gF_Cdl * (kr3 - kf4);

    // Clamping is applied after assembly; applying it before memset erased
    // the rows and made Newton's derivative inconsistent with its RHS.
    for (int i = 0; i < 5; ++i) {
        if (clamped[i]) {
            for (int j = 0; j < NSTATE; ++j) J[j * NSTATE + i] = 0.0;
        }
    }
}

/* ------ steady-state relaxation (matches solve_steady_state_relaxation) ------ */
static bool steady_state(double* y, const double* p) {
    y[0] = 1.0; for (int i = 1; i < 5; ++i) y[i] = 0.0;
    y[5] = p[P_E_START];

    // Newton method for steady state: solve f(y) = 0
    for (int iter = 0; iter < 50; ++iter) {
        double f[NSTATE], J[NSTATE * NSTATE];
        rhs_and_jac(0.0, y, p, f, J);
        double norm = 0.0;
        for (int i = 0; i < NSTATE; ++i) norm += f[i] * f[i];
        if (std::sqrt(norm) < 1e-12) return true;

        // J * dy = -f
        for (int i = 0; i < NSTATE; ++i) f[i] = -f[i];  // reuse f as -f
        if (solve6(J, f) != 0) return false;
        for (int i = 0; i < NSTATE; ++i) y[i] += f[i];
        for (int i = 0; i < 5; ++i) y[i] = clamp01(y[i]);
        y[5] = std::max(0.0, y[5]);
    }
    return false;
}

/* ==================================================================
 * Main solver — matches simulate_walker algorithm
 * ================================================================== */
int oer_cn_solve(
    const double* p, int n, const double* y0_in,
    double* t_out, double* y_out, double* i_out, double* E_out)
{
    if (n < 2 || !p || !i_out || !(p[P_RU] > 0.0) || !(p[P_TOTAL_TIME] > 0.0)) return -1;

    double y[NSTATE];
    if (y0_in) std::memcpy(y, y0_in, NSTATE * sizeof(double));
    else if (!steady_state(y, p)) return -2;

    double dt   = p[P_TOTAL_TIME] / (n - 1);
    double Ru   = p[P_RU], E0 = p[P_E_START], v = p[P_SCAN_RATE];
    double dE   = p[P_DE], om = p[P_OMEGA];

    double t = 0.0;
    if (t_out) t_out[0] = t;
    if (y_out) for (int s = 0; s < NSTATE; ++s) y_out[s] = y[s];
    double Ea = E0 + v * t + dE * std::sin(om * t);
    if (E_out) E_out[0] = Ea;
    if (i_out) i_out[0] = (Ea - y[5]) / Ru;
    if (!std::isfinite(i_out[0])) return -3;

    // f_val = f(y_old) — stored for the Newton residual
    double f_val[NSTATE];
    rhs_and_jac(t, y, p, f_val, nullptr);

        // Per-step workspace
    double y_new[NSTATE], f_new[NSTATE], J[NSTATE * NSTATE];
    double R[NSTATE];

    for (int step = 1; step < n; ++step) {
        /*
         * A single output interval can be much larger than the fastest
         * kinetic time scale.  Retry only failed intervals with 2, 4, ...
         * internal CN substeps.  This preserves the requested output grid,
         * leaves easy cases at one step, and never accepts a failed Newton
         * solve as a finite-looking trajectory.
         */
        double y_start[NSTATE], f_start[NSTATE];
        for (int s = 0; s < NSTATE; ++s) {
            y_start[s] = y[s];
            f_start[s] = f_val[s];
        }
        bool interval_converged = false;
        for (int subdivisions = CN_MIN_SUBDIVISIONS;
             subdivisions <= 64 && !interval_converged;
             subdivisions *= 2) {
            double y_trial[NSTATE], f_trial[NSTATE];
            for (int s = 0; s < NSTATE; ++s) {
                y_trial[s] = y_start[s];
                f_trial[s] = f_start[s];
            }
            double t_trial = t;
            bool subdivision_failed = false;
            const double sub_dt = dt / static_cast<double>(subdivisions);

            for (int substep = 0; substep < subdivisions; ++substep) {
                double tn = t_trial + sub_dt;
                for (int s = 0; s < NSTATE; ++s) y_new[s] = y_trial[s];

                bool converged = false;
                for (int iter = 0; iter < 50; ++iter) {
                    rhs_and_jac(tn, y_new, p, f_new, J);

                    double rnorm = 0.0;
                    for (int s = 0; s < NSTATE; ++s) {
                        R[s] = y_new[s] - y_trial[s]
                            - 0.5 * sub_dt * (f_trial[s] + f_new[s]);
                        rnorm += R[s] * R[s];
                    }
                    if (std::sqrt(rnorm) < 1e-8) {
                        converged = true;
                        break;
                    }

                    // J_sys = I - (h/2) * analytical df/dy.
                    double J_sys[NSTATE * NSTATE];
                    for (int i = 0; i < NSTATE * NSTATE; ++i)
                        J_sys[i] = -0.5 * sub_dt * J[i];
                    for (int i = 0; i < NSTATE; ++i)
                        J_sys[i * NSTATE + i] += 1.0;

                    // J_sys * dy = -R
                    for (int s = 0; s < NSTATE; ++s) R[s] = -R[s];
                    if (solve6(J_sys, R) != 0) break;

                    // Accept only a genuine residual decrease.  If no trial
                    // decreases the residual, this substep is a hard failure
                    // and the outer interval retry must reduce its step size.
                    double candidate[NSTATE], f_candidate[NSTATE];
                    bool line_search_accepted = false;
                    double lambda = 1.0;
                    for (int trial = 0; trial < 8; ++trial, lambda *= 0.5) {
                        for (int s = 0; s < NSTATE; ++s)
                            candidate[s] = y_new[s] + lambda * R[s];
                        for (int s = 0; s < 5; ++s)
                            candidate[s] = clamp01(candidate[s]);
                        candidate[5] = std::max(0.0, candidate[5]);
                        rhs_and_jac(tn, candidate, p, f_candidate, nullptr);
                        double candidate_norm = 0.0;
                        for (int s = 0; s < NSTATE; ++s) {
                            double residual = candidate[s] - y_trial[s]
                                - 0.5 * sub_dt * (f_trial[s] + f_candidate[s]);
                            candidate_norm += residual * residual;
                        }
                        if (candidate_norm < rnorm) {
                            for (int s = 0; s < NSTATE; ++s) {
                                y_new[s] = candidate[s];
                                f_new[s] = f_candidate[s];
                            }
                            line_search_accepted = true;
                            break;
                        }
                    }
                    if (!line_search_accepted) break;
                }

                if (!converged) {
                    subdivision_failed = true;
                    break;
                }
                for (int s = 0; s < NSTATE; ++s) y_trial[s] = y_new[s];
                t_trial = tn;
                rhs_and_jac(t_trial, y_trial, p, f_trial, nullptr);
            }

            if (!subdivision_failed) {
                for (int s = 0; s < NSTATE; ++s) {
                    y[s] = y_trial[s];
                    f_val[s] = f_trial[s];
                }
                t += dt;
                interval_converged = true;
            }
        }

        // Never accept an unconverged implicit interval.  Keep this distinct
        // from -2 (steady-state initialization failure) for provenance.
        if (!interval_converged) return -4;

        if (t_out) t_out[step] = t;
        if (y_out) for (int s = 0; s < NSTATE; ++s) y_out[step * NSTATE + s] = y[s];
        Ea = E0 + v * t + dE * std::sin(om * t);
        if (E_out) E_out[step] = Ea;
        if (i_out) i_out[step] = (Ea - y[5]) / Ru;
        if (!std::isfinite(i_out[step])) return -3;
    }
    return 0;
}

/* Batch screen-only entry point. Parameters are n_cases contiguous blocks of
 * P_N_FIELDS doubles; currents are n_cases contiguous blocks of n_points
 * doubles. Each case gets an independent status code. */
int oer_cn_solve_batch(
    const double* params, int n_cases, int n_points,
    double* currents, int* statuses)
{
    if (!params || !currents || !statuses || n_cases < 1 || n_points < 2) return -1;
    for (int index = 0; index < n_cases; ++index) {
        const double* p = params + index * P_N_FIELDS;
        double* output = currents + index * n_points;
        statuses[index] = oer_cn_solve(p, n_points, nullptr, nullptr, nullptr, output, nullptr);
    }
    return 0;
}

}  // extern "C"
