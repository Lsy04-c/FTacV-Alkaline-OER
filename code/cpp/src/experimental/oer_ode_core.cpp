/* oer_ode_core.cpp — Crank-Nicolson OER AEM solver with analytical Jacobian.
 *
 * Replaces scipy.integrate.solve_ivp(LSODA).  The Python side computes all
 * derived parameters (E01–E04, RTF, invRC, gammaF_Cdl, total_time, …) via
 * params_from_vector() and packs them into a flat double array.  This C++
 * solver receives the pre-computed array and performs only integration.
 *
 * Build (macOS):
 *   c++ -O3 -march=native -shared -fPIC -std=c++17 -o liboercore.dylib oer_ode_core.cpp
 * Build (Linux):
 *   c++ -O3 -march=native -shared -fPIC -std=c++17 -o liboercore.so oer_ode_core.cpp
 */

#include <cmath>
#include <cstring>
#include <algorithm>

extern "C" {

/* ------ parameter array index (all doubles, pre-computed by Python) ------ */
enum {
    P_E_START,      //  0
    P_E_END,        //  1
    P_F,            //  2  fundamental frequency (Hz)
    P_DE,           //  3  AC amplitude (V)
    P_RU,           //  4  uncompensated resistance (Ω)
    P_CDL,          //  5  double-layer capacitance (F)
    P_A_AREA,       //  6  electrode area (cm²)
    P_GAMMA,        //  7  active-site density (mol/cm²)
    P_K0_1,         //  8
    P_K0_2,         //  9
    P_K0_3,         // 10
    P_K0_4,         // 11
    P_K0_PRE,       // 12  pre-oxidation rate constant
    P_G_OH,         // 13
    P_G_O,          // 14
    P_SCALING,      // 15  scaling_OOH_OH
    P_ALPHA,        // 16  transfer coefficient
    P_E01,          // 17  equilibrium potential step 1 (V)
    P_E02,          // 18
    P_E03,          // 19
    P_E04,          // 20
    P_E0_PRE,       // 21  pre-oxidation equilibrium potential (V)
    P_RTF,          // 22  F/(RT) in V⁻¹
    P_INVRC,        // 23  1/(Ru * Cdl) in s⁻¹
    P_GAMMAF_CDL,   // 24  gamma * F / Cdl (base, before beta_recon)
    P_TOTAL_TIME,   // 25  total simulation time (s)
    P_SCAN_RATE,    // 26  potential scan rate (V/s)
    P_OMEGA,        // 27  2πf
    P_BETA_RECON,   // 28  reconstruction amplitude (0 = M0)
    P_E_RECON,      // 29  reconstruction centre potential (V)
    P_W_RECON,      // 30  reconstruction width (V)
    P_FARADAY,      // 31  Faraday constant (C/mol)
    P_N_FIELDS      // 32  total number of double fields
};

/* ------ helpers ------ */
static inline double safe_exp(double x) {
    if (x > 100.0)  return 2.6881171418161356e43;
    if (x < -100.0) return 0.0;
    return std::exp(x);
}
static inline double clamp01(double x) { return std::max(0.0, std::min(1.0, x)); }

/* ------ 6×6 dense LU solve (in-place) ------ */
static int solve_6x6(double* A, double* b) {
    int piv[6];
    for (int i = 0; i < 6; ++i) piv[i] = i;

    for (int col = 0; col < 6; ++col) {
        int best = col;
        double best_val = std::abs(A[col + best * 6]);
        for (int row = col + 1; row < 6; ++row) {
            double v = std::abs(A[col + row * 6]);
            if (v > best_val) { best_val = v; best = row; }
        }
        if (best_val < 1e-30) return -1;
        if (best != col) {
            std::swap(piv[col], piv[best]);
            for (int j = 0; j < 6; ++j) std::swap(A[j + col * 6], A[j + best * 6]);
        }
        double inv = 1.0 / A[col + col * 6];
        for (int row = col + 1; row < 6; ++row) {
            double f = A[col + row * 6] * inv;
            A[col + row * 6] = f;
            for (int j = col + 1; j < 6; ++j)
                A[j + row * 6] -= f * A[j + col * 6];
        }
    }
    double y[6];
    for (int i = 0; i < 6; ++i) {
        y[i] = b[piv[i]];
        for (int j = 0; j < i; ++j) y[i] -= A[j + i * 6] * y[j];
    }
    for (int i = 5; i >= 0; --i) {
        double s = y[i];
        for (int j = i + 1; j < 6; ++j) s -= A[j + i * 6] * b[j];
        b[i] = s / A[i + i * 6];
    }
    return 0;
}

/* ------ effective gamma (M1: potential-dependent site density) ------ */
static inline double effective_gamma(double E_app, const double* p) {
    double g0 = p[P_GAMMA];
    double beta = p[P_BETA_RECON];
    if (beta <= 0.0) return g0;
    double c = p[P_E_RECON], w = std::max(p[P_W_RECON], 1e-6);
    double x = std::max(-60.0, std::min(60.0, (E_app - c) / w));
    return g0 * (1.0 + beta / (1.0 + std::exp(-x)));
}

/* ------ RHS + analytical Jacobian ------ */
static void eval_rhs_and_jac(
    double t, const double* y, const double* p,
    double dydt[6], double J[36])   // J col-major: J[col * 6 + row]
{
    double th_s = y[0], th_ox = y[1], th_OH = y[2];
    double th_O = y[3], th_OOH = y[4], phi = y[5];

    // normalise coverages
    double sum = th_s + th_ox + th_OH + th_O + th_OOH;
    if (sum > 1e-12) {
        double inv = 1.0 / sum;
        th_s *= inv; th_ox *= inv; th_OH *= inv;
        th_O *= inv;  th_OOH *= inv;
    }

    double E_dc  = p[P_E_START] + p[P_SCAN_RATE] * t;
    double E_ac  = p[P_DE] * std::sin(p[P_OMEGA] * t);
    double E_app = E_dc + E_ac;

    double RTF  = p[P_RTF];
    double a    = p[P_ALPHA];
    double b    = 1.0 - a;
    double a_OH = 1.0, a_H2O = 1.0;

    // overpotentials
    double eta_pre = phi - p[P_E0_PRE];
    double eta_1   = phi - p[P_E01];
    double eta_2   = phi - p[P_E02];
    double eta_3   = phi - p[P_E03];
    double eta_4   = phi - p[P_E04];

    // BV rate constants
    double bRTF  =  b * RTF, maRTF = -a * RTF;
    double kfp = ( bRTF * eta_pre < 600) ? p[P_K0_PRE] * safe_exp( bRTF * eta_pre) : 1e100;
    double krp = (maRTF * eta_pre < 600) ? p[P_K0_PRE] * safe_exp(maRTF * eta_pre) : 1e100;
    double kf1 = ( bRTF * eta_1   < 600) ? p[P_K0_1]   * safe_exp( bRTF * eta_1)   : 1e100;
    double kr1 = (maRTF * eta_1   < 600) ? p[P_K0_1]   * safe_exp(maRTF * eta_1)   : 1e100;
    double kf2 = ( bRTF * eta_2   < 600) ? p[P_K0_2]   * safe_exp( bRTF * eta_2)   : 1e100;
    double kr2 = (maRTF * eta_2   < 600) ? p[P_K0_2]   * safe_exp(maRTF * eta_2)   : 1e100;
    double kf3 = ( bRTF * eta_3   < 600) ? p[P_K0_3]   * safe_exp( bRTF * eta_3)   : 1e100;
    double kr3 = (maRTF * eta_3   < 600) ? p[P_K0_3]   * safe_exp(maRTF * eta_3)   : 1e100;
    double kf4 = ( bRTF * eta_4   < 600) ? p[P_K0_4]   * safe_exp( bRTF * eta_4)   : 1e100;
    double kr4 = (maRTF * eta_4   < 600) ? p[P_K0_4]   * safe_exp(maRTF * eta_4)   : 1e100;

    // reaction rates
    double rp = kfp * th_s   * a_OH - krp * th_ox * a_H2O;
    double r1 = kf1 * th_ox  * a_OH - kr1 * th_OH;
    double r2 = kf2 * th_OH  * a_OH - kr2 * th_O  * a_H2O;
    double r3 = kf3 * th_O   * a_OH - kr3 * th_OOH;
    double r4 = kf4 * th_OOH * a_OH - kr4 * th_ox * a_H2O;

    // coverage derivatives (rows 0–4)
    dydt[0] = -rp;
    dydt[1] =  rp - r1 + r4;
    dydt[2] =  r1 - r2;
    dydt[3] =  r2 - r3;
    dydt[4] =  r3 - r4;

    // surface potential (row 5) — effective gamma for M1
    double g_eff   = effective_gamma(E_app, p);
    double gF_Cdl  = g_eff * p[P_FARADAY] / p[P_CDL];  // current gammaF_Cdl
    double r_elec  = rp + r1 + r2 + r3 + r4;
    dydt[5] = (E_app - phi) * p[P_INVRC] - gF_Cdl * r_elec;

    // non-negative clamping
    for (int i = 0; i < 5; ++i)
        if (y[i] <= 0.0 && dydt[i] < 0.0) dydt[i] = 0.0;

    if (!J) return;
    std::memset(J, 0, 36 * sizeof(double));

    // φs-derivatives of BV rate constants
    double dkfp = kfp *  bRTF,  dkrp = krp * maRTF;
    double dkf1 = kf1 *  bRTF,  dkr1 = kr1 * maRTF;
    double dkf2 = kf2 *  bRTF,  dkr2 = kr2 * maRTF;
    double dkf3 = kf3 *  bRTF,  dkr3 = kr3 * maRTF;
    double dkf4 = kf4 *  bRTF,  dkr4 = kr4 * maRTF;

    // Row 0: dθ*/dt = -r_pre
    J[0*6+0] = -kfp;   J[1*6+0] =  krp;
    J[5*6+0] = -(dkfp * th_s - dkrp * th_ox);

    // Row 1: dθox/dt = r_pre - r1 + r4
    J[0*6+1] =  kfp;   J[1*6+1] = -krp - kf1 - kr4;
    J[2*6+1] =  kr1;   J[4*6+1] =  kf4;
    J[5*6+1] = (dkfp*th_s - dkrp*th_ox) - (dkf1*th_ox - dkr1*th_OH)
             + (dkf4*th_OOH - dkr4*th_ox);

    // Row 2: dθOH/dt = r1 - r2
    J[1*6+2] =  kf1;   J[2*6+2] = -kr1 - kf2;
    J[3*6+2] =  kr2;
    J[5*6+2] = (dkf1*th_ox - dkr1*th_OH) - (dkf2*th_OH - dkr2*th_O);

    // Row 3: dθO/dt = r2 - r3
    J[2*6+3] =  kf2;   J[3*6+3] = -kr2 - kf3;
    J[4*6+3] =  kr3;
    J[5*6+3] = (dkf2*th_OH - dkr2*th_O) - (dkf3*th_O - dkr3*th_OOH);

    // Row 4: dθOOH/dt = r3 - r4
    J[3*6+4] =  kf3;   J[4*6+4] = -kr3 - kf4;
    J[1*6+4] =  kr4;
    J[5*6+4] = (dkf3*th_O - dkr3*th_OOH) - (dkf4*th_OOH - dkr4*th_ox);

    // Row 5: dφs/dt  (dominant diagonal + coverage coupling)
    double dr_dphi = (dkfp*th_s - dkrp*th_ox) + (dkf1*th_ox - dkr1*th_OH)
                   + (dkf2*th_OH - dkr2*th_O) + (dkf3*th_O - dkr3*th_OOH)
                   + (dkf4*th_OOH - dkr4*th_ox);
    J[5*6+5] = -p[P_INVRC] - gF_Cdl * dr_dphi;
    J[0*6+5] = -gF_Cdl *  kfp;
    J[1*6+5] = -gF_Cdl * (-krp - kf1 - kr4);
    J[2*6+5] = -gF_Cdl * ( kr1 - kf2);
    J[3*6+5] = -gF_Cdl * ( kr2 - kf3);
    J[4*6+5] = -gF_Cdl * ( kr3 - kf4);
}

/* ------ steady-state relaxation ------ */
static void find_steady_state(double* y, const double* p) {
    double dydt[6];
    // Start from bare surface
    y[0] = 1.0; y[1] = 0.0; y[2] = 0.0;
    y[3] = 0.0; y[4] = 0.0; y[5] = p[P_E_START];

    for (int k = 0; k < 5000; ++k) {
        eval_rhs_and_jac(0.0, y, p, dydt, nullptr);
        double max_abs = 0.0;
        for (int i = 0; i < 6; ++i) max_abs = std::max(max_abs, std::abs(dydt[i]));
        if (max_abs < 1e-6) break;

        double dt = std::min(1e-6, 1e-4 / std::max(max_abs, 1e-12));
        for (int i = 0; i < 6; ++i) y[i] += dt * dydt[i];
        for (int i = 0; i < 5; ++i) y[i] = clamp01(y[i]);
        y[5] = std::max(0.0, y[5]);
    }
}

/* ==================================================================
 * Public C API
 * ================================================================== */

/* Debug: evaluate RHS at a single (t, y) point.  Returns dydt[6]. */
int oer_rhs_debug(
    const double* p,        // [P_N_FIELDS]
    double t,
    const double* y,        // [6]
    double* dydt            // [6] output
) {
    eval_rhs_and_jac(t, y, p, dydt, nullptr);
    return 0;
}

/* Debug: compute steady state and return y0[6]. */
int oer_steady_state_debug(
    const double* p,        // [P_N_FIELDS]
    double* y0              // [6] output
) {
    find_steady_state(y0, p);
    return 0;
}

int oer_solve(
    const double* p,        // [P_N_FIELDS] pre-computed parameters
    int n_points,           // number of time steps
    const double* y0_in,    // [6] initial state, or NULL → use steady state
    double* t_out,          // [n_points] time (may be NULL)
    double* y_out,          // [n_points * 6] state trajectory (may be NULL)
    double* i_out,          // [n_points] total current (may be NULL)
    double* E_out           // [n_points] applied potential (may be NULL)
) {
    if (n_points < 2) return -1;

    double y[6];
    if (y0_in) {
        std::memcpy(y, y0_in, 6 * sizeof(double));
    } else {
        find_steady_state(y, p);
    }

    double total_time = p[P_TOTAL_TIME];
    double dt         = total_time / (n_points - 1);
    double Ru         = p[P_RU];
    double scan_rate  = p[P_SCAN_RATE];
    double E_start    = p[P_E_START];
    double dE         = p[P_DE];
    double omega      = p[P_OMEGA];

    double dydt[6];
    double t = 0.0;

    // store t=0
    if (t_out) t_out[0] = t;
    if (y_out) for (int s = 0; s < 6; ++s) y_out[s] = y[s];
    double E_app = E_start + scan_rate * t + dE * std::sin(omega * t);
    if (E_out) E_out[0] = E_app;
    if (i_out) i_out[0] = (E_app - y[5]) / Ru;

    eval_rhs_and_jac(t, y, p, dydt, nullptr);
    double fn[6]; std::memcpy(fn, dydt, 6 * sizeof(double));

    for (int step = 1; step < n_points; ++step) {
        double t_next = t + dt;
        double E_app_next = E_start + scan_rate * t_next + dE * std::sin(omega * t_next);
        double y_new[6];

        // ------ coverages: forward Euler (explicit) ------
        for (int s = 0; s < 5; ++s)
            y_new[s] = y[s] + dt * fn[s];

        // ------ φ: backward Euler (analytic, closed-form) ------
        // dφ/dt = (E_app - φ) * invRC - γF_Cdl * r_elec
        // => φ_new = (φ_old + dt*E_app*invRC - dt*γF_Cdl*r_elec) / (1 + dt*invRC)
        // We evaluate r_elec at the NEW coverages (semi-implicit coupling)
        double f_tmp[6];
        y_new[5] = y[5];  // temporary φ for r_elec evaluation
        eval_rhs_and_jac(t_next, y_new, p, f_tmp, nullptr);
        double r_elec_new = -(f_tmp[0] + f_tmp[1] + f_tmp[2] + f_tmp[3] + f_tmp[4]);  // r_elec = -sum(dθ/dt) + dθox contributions
        // Better: re-derive r_elec from the rates
        // Actually r_elec = r_pre + r1 + r2 + r3 + r4 = -dθ*/dt + dθox contributions...
        // Let me just recompute r_elec properly using the eval at the new coverages.
        // The simplest: compute f at (t_next, y_new_with_tmp_phi) and extract r_elec from the φ equation:
        // f[5] = (E_app - φ) * invRC - γF_Cdl * r_elec
        // => r_elec = ((E_app - φ) * invRC - f[5]) / γF_Cdl
        double gamma_eff_new = effective_gamma(E_app_next, p);
        double gF_Cdl_new = gamma_eff_new * p[P_FARADAY] / p[P_CDL];
        double r_elec = 0.0;
        if (gF_Cdl_new > 1e-30)
            r_elec = ((E_app_next - y[5]) * p[P_INVRC] - f_tmp[5]) / gF_Cdl_new;

        double denom = 1.0 + dt * p[P_INVRC];
        y_new[5] = (y[5] + dt * (E_app_next * p[P_INVRC] - gF_Cdl_new * r_elec)) / denom;
        y_new[5] = std::max(0.0, y_new[5]);

        // clamp coverages
        for (int s = 0; s < 5; ++s) y_new[s] = clamp01(y_new[s]);

        std::memcpy(y,  y_new, 6 * sizeof(double));
        eval_rhs_and_jac(t_next, y, p, fn, nullptr);  // fn for next step
        t = t_next;

        std::memcpy(y,  y_new, 6 * sizeof(double));
        eval_rhs_and_jac(t_next, y, p, fn, nullptr);
        t = t_next;

        if (t_out) t_out[step] = t;
        if (y_out) for (int s = 0; s < 6; ++s) y_out[step * 6 + s] = y[s];
        E_app = E_start + scan_rate * t + dE * std::sin(omega * t);
        if (E_out) E_out[step] = E_app;
        if (i_out) i_out[step] = (E_app - y[5]) / Ru;
    }
    return 0;
}

}  // extern "C"
