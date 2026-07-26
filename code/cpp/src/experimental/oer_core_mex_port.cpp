/* oer_core_mex_port.cpp — Standalone C++ OER solver adapted from OER_Core_Mex.
 *
 * Replaces the MATLAB mexFunction entry point with a plain extern "C" API
 * callable from Python via ctypes.  The core physics (compute_kinetics,
 * model, solve_*, simulate_walker) is untouched.
 *
 * Build (macOS):
 *   c++ -O3 -march=native -shared -fPIC -std=c++17 -o liboermex.dylib oer_core_mex_port.cpp
 * Build (Linux):
 *   c++ -O3 -march=native -shared -fPIC -std=c++17 -o liboermex.so oer_core_mex_port.cpp
 */

#include <cstdio>
#include <cstdlib>
#include <vector>
#include <cmath>
#include <cstring>
#include <algorithm>
#include <thread>
#include <complex>

/*
 * OER_Core_Mex.cpp
 * Optimized C++ implementation with Batch Parallel Processing (std::thread).
 * Refactored to remove global variables and unify kinetic calculations.
 * Optimized memory allocation with Workspace.
 * Optimized Sparse Matrix with CSR (Compressed Sparse Row).
 */

// Parameter Indices Enum
enum ParamIdx {
    E_START = 0, V_SCAN = 1, DE = 2, OMEGA = 3,
    RU = 4, CDL = 5, A_AREA = 6, GAMMA = 7,
    K01 = 8, K02 = 9, K03 = 10, K04 = 11,
    E01 = 12, E02 = 13, E03 = 14, E04 = 15,
    ALPHA = 16, RTF = 17, INVRC = 18,
    GAMMAF_CDL = 19,
    N_POINTS = 20, T_TOTAL = 21, N_GRID = 22,
    KC1 = 23, KAD1 = 24, KC2 = 25, KAD2 = 26, KC3 = 27, KAD3 = 28,
    HENRY_CONST = 29,
    ACTIVITY_COEFF_H = 30,
    BAND_START = 31,
    WEIGHT_START = 39,
    USE_STEADY_STATE = 47
};

struct Params {
    double E_start, v, dE, omega;
    double Ru, Cdl, A, gamma;
    double k01, k02, k03, k04;
    double E01, E02, E03, E04, a;
    double kc1, kad1, kc2, kad2, kc3, kad3;
    double Henry_const;
    double activity_coeff_H;
    double RTF, invRC, gammaF_Cdl;
    double t_total;
    int n_points;
    int N;
    bool use_steady_state;
    double band[8];
    double harmonic_weights[8];
};

// CSR Matrix Type
struct CSRMatrix {
    std::vector<double> values;
    std::vector<int> col_indices;
    std::vector<int> row_ptr;
};

// Simulation Context to replace globals
struct SimContext {
    const CSRMatrix& M_H;
    const CSRMatrix& M_O2;
    const double* v_H;
    const double* v_O2;
    int num_states;
};

// Unified Kinetics Result
struct KineticsResult {
    double rC1, rE1, rE2, rC2, rE3, rE4, rC3;
    // Derivatives w.r.t [H2O, OH, O, OH2O, OOH, OO, phi, C_H, C_O2]
    double drC1[9], drE1[9], drE2[9], drC2[9], drE3[9], drE4[9], drC3[9];

    KineticsResult() {
        std::memset(drC1, 0, 9*sizeof(double));
        std::memset(drE1, 0, 9*sizeof(double));
        std::memset(drE2, 0, 9*sizeof(double));
        std::memset(drC2, 0, 9*sizeof(double));
        std::memset(drE3, 0, 9*sizeof(double));
        std::memset(drE4, 0, 9*sizeof(double));
        std::memset(drC3, 0, 9*sizeof(double));
    }
};

// Workspace to avoid repeated allocations
struct SolverWorkspace {
    // For Schur
    std::vector<double> z, temp_z, S, Y, rhs_s;

    // For Tridiagonal
    std::vector<double> c_prime, d_prime;

    // For D_block (Reusable buffers)
    std::vector<double> diag_vec, upper_vec, lower_vec, rhs_vec;

    // For Newton/Main Loop
    std::vector<double> J, R_vec, y_new, f_val, f_val_new, rhs;

    void reallocate(int num_states, int N) {
        int n_s = 7;
        int n_d = 2 * N;
        if (z.size() < n_d) z.resize(n_d);
        if (temp_z.size() < num_states) temp_z.resize(num_states);
        if (S.size() < n_s * n_s) S.resize(n_s * n_s);
        if (Y.size() < n_d * n_s) Y.resize(n_d * n_s);
        if (rhs_s.size() < n_s) rhs_s.resize(n_s);

        if (c_prime.size() < N) c_prime.resize(N);
        if (d_prime.size() < N) d_prime.resize(N);

        if (diag_vec.size() < N) diag_vec.resize(N);
        if (upper_vec.size() < N) upper_vec.resize(N);
        if (lower_vec.size() < N) lower_vec.resize(N);
        if (rhs_vec.size() < N) rhs_vec.resize(N);

        if (J.size() < num_states * num_states) J.resize(num_states * num_states);
        if (R_vec.size() < num_states) R_vec.resize(num_states);
        if (y_new.size() < num_states) y_new.resize(num_states);
        if (f_val.size() < num_states) f_val.resize(num_states);
        if (f_val_new.size() < num_states) f_val_new.resize(num_states);
        if (rhs.size() < num_states) rhs.resize(num_states);
    }
};

// FFT Constants and Helpers
const double PI = 3.14159265358979323846;

inline double safe_exp(double x) {
    if (x > 80.0) return 5.5406e34;
    if (x < -80.0) return 1.8049e-35;
    return exp(x);
}

typedef std::complex<double> Complex;

void fft(std::vector<Complex>& a, bool invert) {
    int n = a.size();
    if ((n & (n - 1)) != 0) {
        // Warning handled by caller or ignored for performance
    }

    for (int i = 1, j = 0; i < n; i++) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) std::swap(a[i], a[j]);
    }

    for (int len = 2; len <= n; len <<= 1) {
        double ang = 2 * PI / len * (invert ? -1 : 1);
        Complex wlen(cos(ang), sin(ang));
        for (int i = 0; i < n; i += len) {
            Complex w(1);
            for (int j = 0; j < len / 2; j++) {
                Complex u = a[i + j];
                Complex v = a[i + j + len / 2] * w;
                a[i + j] = u + v;
                a[i + j + len / 2] = u - v;
                w *= wlen;
            }
        }
    }
    if (invert) {
        for (Complex& x : a) x /= n;
    }
}

double process_and_calculate_error(const std::vector<double>& i_total, const Params& p,
                                   const double* I_exp_ptr, double* I_sim_ptr, bool has_exp) {
    int n = i_total.size();
    std::vector<Complex> fa(n);
    for(int i=0; i<n; ++i) fa[i] = Complex(i_total[i], 0);
    fft(fa, false);

    double bin_width = (double)(n - 1) / (n * p.t_total);
    double total_error = 0.0;
    double weight_sum = 0.0;

    for (int k = 0; k < 8; ++k) {
        double center_freq = k * p.omega / (2 * PI);
        double bandwidth = p.band[k];
        double bw_half = bandwidth / 2.0;

        std::vector<Complex> Y_filtered(n, Complex(0,0));
        for (int i = 0; i < n; ++i) {
            double freq = (i <= n/2) ? i * bin_width : (n - i) * bin_width;
            if (std::abs(freq - center_freq) <= bw_half) {
                if (k == 0) Y_filtered[i] = fa[i];
                else if (i > 0 && i < n/2) Y_filtered[i] = fa[i] * 2.0;
                else Y_filtered[i] = Complex(0,0);
            }
        }

        fft(Y_filtered, true);

        double sum_sq_diff = 0.0;
        double sum_sq_exp = 0.0;
        const double* exp_col = has_exp ? (I_exp_ptr + k * n) : nullptr;
        double* sim_col = I_sim_ptr ? (I_sim_ptr + k * n) : nullptr;

        for (int i = 0; i < n; ++i) {
            double val = std::abs(Y_filtered[i]);
            if (sim_col) sim_col[i] = val;
            if (has_exp) {
                double diff = val - exp_col[i];
                sum_sq_diff += diff * diff;
                sum_sq_exp += exp_col[i] * exp_col[i];
            }
        }

        if (has_exp) {
            double denom = sum_sq_exp / n;
            if (denom <= 1e-12) denom = 1e-12;
            double error = (sum_sq_diff / n) / denom;
            total_error += error * p.harmonic_weights[k];
        }
        weight_sum += p.harmonic_weights[k];
    }

    if (weight_sum <= 0) weight_sum = 1.0;
    return total_error / weight_sum;
}

// Unified Kinetics Calculation
void compute_kinetics(double t, const double* y, const Params& p, KineticsResult& res, bool calc_derivs) {
    double theta_H2O = y[0];
    double theta_OH = y[1];
    double theta_O = y[2];
    double theta_OH2O = y[3];
    double theta_OOH = y[4];
    double theta_OO = y[5];
    double phi_s = y[6];
    double C_H_0 = y[7];
    double C_O2_0 = y[7 + p.N];

    double theta_star = 1.0 - theta_H2O - theta_OH - theta_O - theta_OH2O - theta_OOH - theta_OO;

    // Potential dependent terms
    double eta1 = phi_s - p.E01; double eta2 = phi_s - p.E02;
    double eta3 = phi_s - p.E03; double eta4 = phi_s - p.E04;

    double arg1 = p.RTF * eta1; double arg2 = p.RTF * eta2;
    double arg3 = p.RTF * eta3; double arg4 = p.RTF * eta4;

    double ef1 = safe_exp((1.0 - p.a) * arg1); double eb1 = safe_exp(-p.a * arg1);
    double ef2 = safe_exp((1.0 - p.a) * arg2); double eb2 = safe_exp(-p.a * arg2);
    double ef3 = safe_exp((1.0 - p.a) * arg3); double eb3 = safe_exp(-p.a * arg3);
    double ef4 = safe_exp((1.0 - p.a) * arg4); double eb4 = safe_exp(-p.a * arg4);

    // Dynamic Activity
    double factor_H = 1000.0 * p.activity_coeff_H;
    double a_H = C_H_0 * factor_H;

    // Dynamic Pressure
    double factor_P = 1000.0 / p.Henry_const;
    double P_O2 = C_O2_0 * factor_P;

    // Rates
    res.rC1 = p.kc1 * (theta_star - theta_H2O / p.kad1);
    res.rE1 = p.k01 * (theta_H2O * ef1 - theta_OH * a_H * eb1);
    res.rE2 = p.k02 * (theta_OH * ef2 - theta_O * a_H * eb2);
    res.rC2 = p.kc2 * (theta_O - theta_OH2O / p.kad2);
    res.rE3 = p.k03 * (theta_OH2O * ef3 - theta_OOH * a_H * eb3);
    res.rE4 = p.k04 * (theta_OOH * ef4 - theta_OO * a_H * eb4);
    res.rC3 = p.kc3 * (theta_OO - theta_star * P_O2 / p.kad3);

    if (!calc_derivs) return;

    // Derivatives
    // Indices: 0-5 (Thetas), 6 (phi), 7 (C_H), 8 (C_O2)

    // rC1
    for(int k=0; k<6; ++k) res.drC1[k] = -p.kc1;
    res.drC1[0] -= p.kc1 / p.kad1;

    // rE1
    double da_f = (1-p.a)*p.RTF; double da_b = -p.a*p.RTF;
    res.drE1[0] = p.k01 * ef1;
    res.drE1[1] = p.k01 * (-a_H * eb1);
    res.drE1[6] = p.k01 * (theta_H2O * ef1 * da_f - theta_OH * a_H * eb1 * da_b);
    res.drE1[7] = p.k01 * (-theta_OH * factor_H * eb1);

    // rE2
    res.drE2[1] = p.k02 * ef2;
    res.drE2[2] = p.k02 * (-a_H * eb2);
    res.drE2[6] = p.k02 * (theta_OH * ef2 * da_f - theta_O * a_H * eb2 * da_b);
    res.drE2[7] = p.k02 * (-theta_O * factor_H * eb2);

    // rC2
    res.drC2[2] = p.kc2;
    res.drC2[3] = -p.kc2 / p.kad2;

    // rE3
    res.drE3[3] = p.k03 * ef3;
    res.drE3[4] = p.k03 * (-a_H * eb3);
    res.drE3[6] = p.k03 * (theta_OH2O * ef3 * da_f - theta_OOH * a_H * eb3 * da_b);
    res.drE3[7] = p.k03 * (-theta_OOH * factor_H * eb3);

    // rE4
    res.drE4[4] = p.k04 * ef4;
    res.drE4[5] = p.k04 * (-a_H * eb4);
    res.drE4[6] = p.k04 * (theta_OOH * ef4 * da_f - theta_OO * a_H * eb4 * da_b);
    res.drE4[7] = p.k04 * (-theta_OO * factor_H * eb4);

    // rC3
    for(int k=0; k<6; ++k) res.drC3[k] = p.kc3 * (P_O2 / p.kad3);
    res.drC3[5] += p.kc3;
    res.drC3[8] = -p.kc3 * theta_star * factor_P / p.kad3;
}

void model(double t, const double* y, double* dydt, const Params& p, const SimContext& ctx) {
    KineticsResult res;
    compute_kinetics(t, y, p, res, false);

    dydt[0] = res.rC1 - res.rE1;
    dydt[1] = res.rE1 - res.rE2;
    dydt[2] = res.rE2 - res.rC2;
    dydt[3] = res.rC2 - res.rE3;
    dydt[4] = res.rE3 - res.rE4;
    dydt[5] = res.rE4 - res.rC3;

    double E_dc = p.E_start + p.v * t;
    double E = E_dc + p.dE * sin(p.omega * t);

    double r_elec_sum = res.rE1 + res.rE2 + res.rE3 + res.rE4;
    dydt[6] = (E - y[6]) * p.invRC - p.gammaF_Cdl * r_elec_sum;

    double flux_H = p.gamma * r_elec_sum;
    double flux_O2 = p.gamma * res.rC3;

    const double* C_H = &y[7];
    const double* C_O2 = &y[7 + p.N];

    for (int i = 0; i < p.N; ++i) {
        double sum_H = 0.0;
        // CSR Matrix Vector Multiplication
        for (int k = ctx.M_H.row_ptr[i]; k < ctx.M_H.row_ptr[i+1]; ++k) {
            sum_H += ctx.M_H.values[k] * C_H[ctx.M_H.col_indices[k]];
        }
        dydt[7 + i] = sum_H + ctx.v_H[i] * flux_H;

        double sum_O2 = 0.0;
        for (int k = ctx.M_O2.row_ptr[i]; k < ctx.M_O2.row_ptr[i+1]; ++k) {
            sum_O2 += ctx.M_O2.values[k] * C_O2[ctx.M_O2.col_indices[k]];
        }
        dydt[7 + p.N + i] = sum_O2 + ctx.v_O2[i] * flux_O2;
    }
}

// ... Solvers ...
void solve_tridiagonal(int n, const std::vector<double>& diag, const std::vector<double>& upper,
                       const std::vector<double>& lower, std::vector<double>& b, SolverWorkspace& ws) {
    // Uses ws.c_prime, ws.d_prime
    ws.c_prime[0] = upper[0] / diag[0];
    ws.d_prime[0] = b[0] / diag[0];
    for (int i = 1; i < n; i++) {
        double temp = diag[i] - lower[i-1] * ws.c_prime[i-1];
        if (i < n - 1) ws.c_prime[i] = upper[i] / temp;
        ws.d_prime[i] = (b[i] - lower[i-1] * ws.d_prime[i-1]) / temp;
    }
    b[n-1] = ws.d_prime[n-1];
    for (int i = n - 2; i >= 0; i--) b[i] = ws.d_prime[i] - ws.c_prime[i] * b[i+1];
}

void solve_D_block(int N, const std::vector<double>& J, int num_states, std::vector<double>& x, SolverWorkspace& ws) {
    // Block H
    int start_H = 7;
    // Use workspace vectors
    for(int i=0; i<N; ++i) {
        ws.diag_vec[i] = J[(start_H + i) + (start_H + i) * num_states];
        ws.rhs_vec[i] = x[start_H + i];
        if (i < N-1) {
            ws.upper_vec[i] = J[(start_H + i) + (start_H + i + 1) * num_states];
            ws.lower_vec[i] = J[(start_H + i + 1) + (start_H + i) * num_states];
        }
    }
    solve_tridiagonal(N, ws.diag_vec, ws.upper_vec, ws.lower_vec, ws.rhs_vec, ws);
    for(int i=0; i<N; ++i) x[start_H + i] = ws.rhs_vec[i];

    // Block O2
    int start_O2 = 7 + N;
    for(int i=0; i<N; ++i) {
        ws.diag_vec[i] = J[(start_O2 + i) + (start_O2 + i) * num_states];
        ws.rhs_vec[i] = x[start_O2 + i];
        if (i < N-1) {
            ws.upper_vec[i] = J[(start_O2 + i) + (start_O2 + i + 1) * num_states];
            ws.lower_vec[i] = J[(start_O2 + i + 1) + (start_O2 + i) * num_states];
        }
    }
    solve_tridiagonal(N, ws.diag_vec, ws.upper_vec, ws.lower_vec, ws.rhs_vec, ws);
    for(int i=0; i<N; ++i) x[start_O2 + i] = ws.rhs_vec[i];
}

void solve_linear_system_schur_optimized(int num_states, int N, const std::vector<double>& J, std::vector<double>& b, SolverWorkspace& ws) {
    int n_s = 7;
    int n_d = 2 * N;
    int start_diff = 7;

    // Use ws.z, ws.temp_z, ws.S, ws.Y, ws.rhs_s

    for(int i=0; i<n_d; ++i) ws.z[i] = b[start_diff+i];

    std::fill(ws.temp_z.begin(), ws.temp_z.end(), 0.0);
    for(int i=0; i<n_d; ++i) ws.temp_z[start_diff+i] = ws.z[i];
    solve_D_block(N, J, num_states, ws.temp_z, ws);
    for(int i=0; i<n_d; ++i) ws.z[i] = ws.temp_z[start_diff+i];

    for(int j=0; j<n_s; ++j) {
        for(int i=0; i<n_s; ++i) ws.S[i + j*n_s] = J[i + j*num_states];
    }

    for(int j=0; j<n_s; ++j) {
        std::fill(ws.temp_z.begin(), ws.temp_z.end(), 0.0);
        for(int i=0; i<n_d; ++i) ws.temp_z[start_diff+i] = J[(start_diff+i) + j*num_states];
        solve_D_block(N, J, num_states, ws.temp_z, ws);
        for(int i=0; i<n_d; ++i) ws.Y[i + j*n_d] = ws.temp_z[start_diff+i];

        for(int i=0; i<n_s; ++i) {
            double val = J[i + start_diff*num_states] * ws.temp_z[start_diff] + J[i + (start_diff+N)*num_states] * ws.temp_z[start_diff+N];
            ws.S[i + j*n_s] -= val;
        }
    }

    for(int i=0; i<n_s; ++i) {
        ws.rhs_s[i] = b[i];
        double val = J[i + start_diff*num_states] * ws.z[0] + J[i + (start_diff+N)*num_states] * ws.z[N];
        ws.rhs_s[i] -= val;
    }

    // Solve S (7x7) via Gaussian elimination
    for (int i = 0; i < n_s; ++i) {
        int max_row = i;
        double max_val = std::abs(ws.S[i + i * n_s]);
        for (int k = i + 1; k < n_s; ++k) {
            if (std::abs(ws.S[k + i * n_s]) > max_val) {
                max_val = std::abs(ws.S[k + i * n_s]);
                max_row = k;
            }
        }
        if (max_row != i) {
            for (int k = i; k < n_s; ++k) std::swap(ws.S[i + k * n_s], ws.S[max_row + k * n_s]);
            std::swap(ws.rhs_s[i], ws.rhs_s[max_row]);
        }
        double pivot = ws.S[i + i * n_s];
        for (int k = i + 1; k < n_s; ++k) {
            double factor = ws.S[k + i * n_s] / pivot;
            ws.rhs_s[k] -= factor * ws.rhs_s[i];
            for (int j = i; j < n_s; ++j) ws.S[k + j * n_s] -= factor * ws.S[i + j * n_s];
        }
    }
    for (int i = n_s - 1; i >= 0; --i) {
        double sum = 0.0;
        for (int j = i + 1; j < n_s; ++j) sum += ws.S[i + j * n_s] * ws.rhs_s[j];
        ws.rhs_s[i] = (ws.rhs_s[i] - sum) / ws.S[i + i * n_s];
    }

    for(int i=0; i<n_s; ++i) b[i] = ws.rhs_s[i];

    // x_d = z - Y * x_s
    for(int i=0; i<n_d; ++i) {
        double sum_Yx = 0.0;
        for(int j=0; j<n_s; ++j) sum_Yx += ws.Y[i + j*n_d] * ws.rhs_s[j];
        b[start_diff+i] = ws.z[i] - sum_Yx;
    }
}

void solve_linear_system_dense(int n, std::vector<double>& A, std::vector<double>& b) {
    for (int i = 0; i < n; ++i) {
        int max_row = i;
        double max_val = std::abs(A[i + i * n]);
        for (int k = i + 1; k < n; ++k) {
            if (std::abs(A[k + i * n]) > max_val) {
                max_val = std::abs(A[k + i * n]);
                max_row = k;
            }
        }
        if (max_row != i) {
            for (int k = i; k < n; ++k) std::swap(A[i + k * n], A[max_row + k * n]);
            std::swap(b[i], b[max_row]);
        }
        double pivot = A[i + i * n];
        for (int k = i + 1; k < n; ++k) {
            double factor = A[k + i * n] / pivot;
            b[k] -= factor * b[i];
            for (int j = i; j < n; ++j) A[k + j * n] -= factor * A[i + j * n];
        }
    }
    for (int i = n - 1; i >= 0; --i) {
        double sum = 0.0;
        for (int j = i + 1; j < n; ++j) sum += A[i + j * n] * b[j];
        b[i] = (b[i] - sum) / A[i + i * n];
    }
}

void solve_linear_system_auto(int num_states, int N, std::vector<double>& J, std::vector<double>& R_vec, SolverWorkspace& ws) {
    if (N < 20) {
        // For small systems, direct dense solve is fine.
        // We can use ws.J for safety but solve_linear_system_dense modifies A in place.
        solve_linear_system_dense(num_states, J, R_vec);
    } else {
        solve_linear_system_schur_optimized(num_states, N, J, R_vec, ws);
    }
}

// Relaxation Solver
void solve_steady_state_relaxation(Params& p, std::vector<double>& y, const SimContext& ctx, SolverWorkspace& ws) {
    y[6] = p.E_start;
    for(int i=0; i<6; ++i) y[i] = std::max(0.0, std::min(1.0, y[i]));

    double dt = 1e-9;
    double max_dt = 1.0;
    double growth_factor = 1.5;
    int max_steps = 200;

    double saved_v = p.v;
    double saved_dE = p.dE;
    p.v = 0.0;
    p.dE = 0.0;

    // Use workspace
    std::fill(ws.f_val.begin(), ws.f_val.end(), 0.0);
    KineticsResult res;

    for(int step=0; step<max_steps; ++step) {
        model(0.0, y.data(), ws.f_val.data(), p, ctx);

        double norm = 0.0;
        for(double v : ws.f_val) norm += v*v;
        if (sqrt(norm) < 1e-10) break;

        std::fill(ws.J.begin(), ws.J.end(), 0.0);

        // Compute Derivatives
        compute_kinetics(0.0, y.data(), p, res, true);

        int idx_CH = 7;
        int idx_CO2 = 7 + p.N;
        int indices[9] = {0, 1, 2, 3, 4, 5, 6, idx_CH, idx_CO2};

        for(int k=0; k<9; ++k) {
            int col = indices[k];
            ws.J[0 + col * ctx.num_states] = res.drC1[k] - res.drE1[k];
            ws.J[1 + col * ctx.num_states] = res.drE1[k] - res.drE2[k];
            ws.J[2 + col * ctx.num_states] = res.drE2[k] - res.drC2[k];
            ws.J[3 + col * ctx.num_states] = res.drC2[k] - res.drE3[k];
            ws.J[4 + col * ctx.num_states] = res.drE3[k] - res.drE4[k];
            ws.J[5 + col * ctx.num_states] = res.drE4[k] - res.drC3[k];

            double d_sum_elec = res.drE1[k] + res.drE2[k] + res.drE3[k] + res.drE4[k];
            double d_dphi = -p.gammaF_Cdl * d_sum_elec;
            if(col == 6) d_dphi -= p.invRC;
            ws.J[6 + col * ctx.num_states] = d_dphi;

            double d_fluxH = p.gamma * d_sum_elec;
            double d_fluxO2 = p.gamma * res.drC3[k];

            ws.J[idx_CH + col * ctx.num_states] = ctx.v_H[0] * d_fluxH;
            ws.J[idx_CO2 + col * ctx.num_states] = ctx.v_O2[0] * d_fluxO2;
        }

        // Add Diffusion (CSR)
         for (int i = 0; i < p.N; ++i) {
            for (int k = ctx.M_H.row_ptr[i]; k < ctx.M_H.row_ptr[i+1]; ++k) {
                int j = ctx.M_H.col_indices[k];
                ws.J[(7 + i) + (7 + j) * ctx.num_states] += ctx.M_H.values[k];
            }
            for (int k = ctx.M_O2.row_ptr[i]; k < ctx.M_O2.row_ptr[i+1]; ++k) {
                int j = ctx.M_O2.col_indices[k];
                ws.J[(7 + p.N + i) + (7 + p.N + j) * ctx.num_states] += ctx.M_O2.values[k];
            }
        }

        // (I - dt*J) * dy = dt * f
        for(int i=0; i<ctx.num_states; ++i) {
            ws.rhs[i] = dt * ws.f_val[i];
            for(int j=0; j<ctx.num_states; ++j) ws.J[i + j*ctx.num_states] *= -dt;
            ws.J[i + i*ctx.num_states] += 1.0;
        }

        solve_linear_system_auto(ctx.num_states, p.N, ws.J, ws.rhs, ws);
        for(int i=0; i<ctx.num_states; ++i) y[i] += ws.rhs[i];

        for(int i=0; i<6; ++i) y[i] = std::max(0.0, std::min(1.0, y[i]));
        for(int i=7; i<ctx.num_states; ++i) y[i] = std::max(0.0, y[i]);

        dt *= growth_factor;
        if(dt > max_dt) dt = max_dt;
    }

    p.v = saved_v;
    p.dE = saved_dE;
    if (std::abs(p.v) > 1e-9) y[6] = p.E_start - p.v / p.invRC;
}

void simulate_walker(int walker_idx, Params p, const double* y0_base,
                     double* y_out_ptr, double* i_out_ptr, double* E_out_ptr,
                     SimContext ctx, bool shared_y0,
                     const double* I_exp_ptr, double* objective_out, double* I_sim_ptr) {

    double dt = p.t_total / (p.n_points - 1);
    double t = 0.0;

    // Initialize Workspace
    SolverWorkspace ws;
    ws.reallocate(ctx.num_states, p.N);

    std::vector<double> y(ctx.num_states);
    if (shared_y0) {
        for (int i = 0; i < ctx.num_states; ++i) y[i] = y0_base[i];
    } else {
        for (int i = 0; i < ctx.num_states; ++i) y[i] = y0_base[i + walker_idx * ctx.num_states];
    }

    if (p.use_steady_state) solve_steady_state_relaxation(p, y, ctx, ws);

    std::vector<double> i_total_vec(p.n_points);
    KineticsResult res;

    size_t point_stride = p.n_points;
    size_t state_stride = p.n_points * ctx.num_states;
    size_t walker_offset = state_stride * walker_idx;

    for (int i = 0; i < ctx.num_states; ++i) y_out_ptr[0 + point_stride * i + walker_offset] = y[i];

    double E_dc = p.E_start + p.v * t;
    double E_ac = p.dE * sin(p.omega * t);
    double E_actual = E_dc + E_ac;
    double i_current = (E_actual - y[6]) / p.Ru;

    i_out_ptr[0 + p.n_points * walker_idx] = i_current;
    i_total_vec[0] = i_current;
    E_out_ptr[0 + p.n_points * walker_idx] = E_actual;

    model(t, y.data(), ws.f_val.data(), p, ctx);

    for (int step = 1; step < p.n_points; ++step) {
        double t_next = t + dt;
        // Use ws.y_new instead of reallocating
        for(int i=0; i<ctx.num_states; ++i) ws.y_new[i] = y[i];

        for (int iter = 0; iter < 10; ++iter) {
            model(t_next, ws.y_new.data(), ws.f_val_new.data(), p, ctx);
            for (int i = 0; i < ctx.num_states; ++i) ws.R_vec[i] = ws.y_new[i] - y[i] - 0.5 * dt * (ws.f_val[i] + ws.f_val_new[i]);

            double norm = 0.0;
            for (double val : ws.R_vec) norm += val * val;
            if (sqrt(norm) < 1e-8) break;

            // Compute Derivatives at y_new
            compute_kinetics(t_next, ws.y_new.data(), p, res, true);

            std::fill(ws.J.begin(), ws.J.end(), 0.0);
            for(int i=0; i<ctx.num_states; ++i) ws.J[i + i*ctx.num_states] = 1.0;

            int idx_CH = 7;
            int idx_CO2 = 7 + p.N;
            int indices[9] = {0, 1, 2, 3, 4, 5, 6, idx_CH, idx_CO2};

            for(int k=0; k<9; ++k) {
                int col = indices[k];
                // Note: -0.5 * dt * J_f

                double J_val_0 = res.drC1[k] - res.drE1[k];
                ws.J[0 + col * ctx.num_states] -= 0.5 * dt * J_val_0;

                double J_val_1 = res.drE1[k] - res.drE2[k];
                ws.J[1 + col * ctx.num_states] -= 0.5 * dt * J_val_1;

                double J_val_2 = res.drE2[k] - res.drC2[k];
                ws.J[2 + col * ctx.num_states] -= 0.5 * dt * J_val_2;

                double J_val_3 = res.drC2[k] - res.drE3[k];
                ws.J[3 + col * ctx.num_states] -= 0.5 * dt * J_val_3;

                double J_val_4 = res.drE3[k] - res.drE4[k];
                ws.J[4 + col * ctx.num_states] -= 0.5 * dt * J_val_4;

                double J_val_5 = res.drE4[k] - res.drC3[k];
                ws.J[5 + col * ctx.num_states] -= 0.5 * dt * J_val_5;

                double d_sum_elec = res.drE1[k] + res.drE2[k] + res.drE3[k] + res.drE4[k];
                double d_dphi = -p.gammaF_Cdl * d_sum_elec;
                if (col == 6) d_dphi -= p.invRC;
                ws.J[6 + col * ctx.num_states] -= 0.5 * dt * d_dphi;

                double d_fluxH = p.gamma * d_sum_elec;
                double d_fluxO2 = p.gamma * res.drC3[k];

                ws.J[idx_CH + col * ctx.num_states] -= 0.5 * dt * (ctx.v_H[0] * d_fluxH);
                ws.J[idx_CO2 + col * ctx.num_states] -= 0.5 * dt * (ctx.v_O2[0] * d_fluxO2);
            }

            for (int col = 0; col < p.N; ++col) {
                int j = 7 + col;
                for (int k = ctx.M_H.row_ptr[col]; k < ctx.M_H.row_ptr[col+1]; ++k) {
                     ws.J[(7 + ctx.M_H.col_indices[k]) + j * ctx.num_states] -= 0.5 * dt * ctx.M_H.values[k];
                }
                int j2 = 7 + p.N + col;
                for (int k = ctx.M_O2.row_ptr[col]; k < ctx.M_O2.row_ptr[col+1]; ++k) {
                     ws.J[(7 + p.N + ctx.M_O2.col_indices[k]) + j2 * ctx.num_states] -= 0.5 * dt * ctx.M_O2.values[k];
                }
            }

            for (int i = 0; i < ctx.num_states; ++i) ws.R_vec[i] = -ws.R_vec[i];
            solve_linear_system_auto(ctx.num_states, p.N, ws.J, ws.R_vec, ws);
            for (int i = 0; i < ctx.num_states; ++i) ws.y_new[i] += ws.R_vec[i];

            for(int i=0; i<6; ++i) ws.y_new[i] = std::max(0.0, std::min(1.0, ws.y_new[i]));
            for(int i=7; i<ctx.num_states; ++i) ws.y_new[i] = std::max(0.0, ws.y_new[i]);
        }

        for(int i=0; i<ctx.num_states; ++i) y[i] = ws.y_new[i];
        t = t_next;
        model(t, y.data(), ws.f_val.data(), p, ctx);

        for (int i = 0; i < ctx.num_states; ++i) y_out_ptr[step + point_stride * i + walker_offset] = y[i];

        E_dc = p.E_start + p.v * t;
        E_ac = p.dE * sin(p.omega * t);
        E_actual = E_dc + E_ac;

        i_current = (E_actual - y[6]) / p.Ru;
        i_out_ptr[step + p.n_points * walker_idx] = i_current;
        i_total_vec[step] = i_current;
        E_out_ptr[step + p.n_points * walker_idx] = E_actual;
    }

    if (I_exp_ptr || I_sim_ptr) {
        // Skipped in standalone mode — objective computed in Python.
    }
}

/* ==================================================================
 * extern "C" API — replaces the MATLAB mexFunction
 * ================================================================== */

extern "C" {

/* Parameter layout — must match the ParamIdx enum at the top of this file.
 * The Python side packs a flat double array in this order.            */
enum {
    PE_START = 0, PE_V_SCAN = 1, PE_DE = 2, PE_OMEGA = 3,
    PE_RU = 4, PE_CDL = 5, PE_A = 6, PE_GAMMA = 7,
    PE_K01 = 8, PE_K02 = 9, PE_K03 = 10, PE_K04 = 11,
    PE_E01 = 12, PE_E02 = 13, PE_E03 = 14, PE_E04 = 15,
    PE_ALPHA = 16, PE_RTF = 17, PE_INVRC = 18,
    PE_GAMMAF_CDL = 19,
    PE_N_POINTS = 20, PE_T_TOTAL = 21, PE_N_GRID = 22,
    PE_KC1 = 23, PE_KAD1 = 24, PE_KC2 = 25, PE_KAD2 = 26,
    PE_KC3 = 27, PE_KAD3 = 28,
    PE_HENRY = 29,
    PE_ACTIVITY_H = 30,
    PE_BAND_START = 31,  // band[8] at 31..38, weights[8] at 39..46
    PE_USE_STEADY = 47
};

static void pack_params(const double* src, Params& p) {
    p.E_start = src[PE_START];
    p.v       = src[PE_V_SCAN];
    p.dE      = src[PE_DE];
    p.omega   = src[PE_OMEGA];
    p.Ru      = src[PE_RU];
    p.Cdl     = src[PE_CDL];
    p.A       = src[PE_A];
    p.gamma   = src[PE_GAMMA];
    p.k01     = src[PE_K01];
    p.k02     = src[PE_K02];
    p.k03     = src[PE_K03];
    p.k04     = src[PE_K04];
    p.E01     = src[PE_E01];
    p.E02     = src[PE_E02];
    p.E03     = src[PE_E03];
    p.E04     = src[PE_E04];
    p.a       = src[PE_ALPHA];
    p.RTF     = src[PE_RTF];
    p.invRC   = src[PE_INVRC];
    p.gammaF_Cdl = src[PE_GAMMAF_CDL];
    p.n_points = (int)src[PE_N_POINTS];
    p.t_total  = src[PE_T_TOTAL];
    p.N        = (int)src[PE_N_GRID];
    p.kc1 = src[PE_KC1]; p.kad1 = src[PE_KAD1];
    p.kc2 = src[PE_KC2]; p.kad2 = src[PE_KAD2];
    p.kc3 = src[PE_KC3]; p.kad3 = src[PE_KAD3];
    p.Henry_const = src[PE_HENRY];
    p.activity_coeff_H = src[PE_ACTIVITY_H];
    for (int i = 0; i < 8; ++i) {
        p.band[i] = src[PE_BAND_START + i];
        p.harmonic_weights[i] = src[PE_BAND_START + 8 + i];
    }
    p.use_steady_state = (src[PE_USE_STEADY] != 0.0);
}

int oer_mex_solve(
    const double* param_array,  // [48] in ParamIdx order
    int n_points,               // number of output time points
    const double* y0_in,        // [num_states] initial state, NULL → steady state
    int num_states,             // number of state variables (6 for no transport)
    int N,                      // transport grid size (1 = no transport)
    const double* M_H,          // [N*N] H⁺ transport matrix, or NULL
    const double* v_H,          // [N] H⁺ drift vector, or NULL
    const double* M_O2,         // [N*N] O₂ transport matrix, or NULL
    const double* v_O2,         // [N] O₂ drift vector, or NULL
    double* t_out,              // [n_points] time (may be NULL)
    double* y_out,              // [n_points * num_states] state (may be NULL)
    double* i_out,              // [n_points] total current (may be NULL)
    double* E_out               // [n_points] applied potential (may be NULL)
) {
    if (n_points < 2 || num_states < 6) return -1;

    Params p;
    pack_params(param_array, p);
    p.n_points = n_points;
    p.N = N;
    p.t_total = (n_points > 1) ? (n_points - 1) * p.t_total / (p.n_points - 1) : p.t_total;

    // Build CSR matrices from dense (or use identity for N=1)
    CSRMatrix M_H_csr, M_O2_csr;
    if (M_H && N > 0) {
        M_H_csr.row_ptr.resize(N + 1);
        M_H_csr.row_ptr[0] = 0;
        for (int i = 0; i < N; ++i) {
            for (int j = 0; j < N; ++j) {
                double val = M_H[i + j * N];  // column-major
                if (val != 0.0) {
                    M_H_csr.values.push_back(val);
                    M_H_csr.col_indices.push_back(j);
                }
            }
            M_H_csr.row_ptr[i + 1] = (int)M_H_csr.values.size();
        }
    }
    if (M_O2 && N > 0) {
        M_O2_csr.row_ptr.resize(N + 1);
        M_O2_csr.row_ptr[0] = 0;
        for (int i = 0; i < N; ++i) {
            for (int j = 0; j < N; ++j) {
                double val = M_O2[i + j * N];
                if (val != 0.0) {
                    M_O2_csr.values.push_back(val);
                    M_O2_csr.col_indices.push_back(j);
                }
            }
            M_O2_csr.row_ptr[i + 1] = (int)M_O2_csr.values.size();
        }
    }

    // Default v_H/v_O2
    std::vector<double> v_H_default, v_O2_default;
    if (!v_H) { v_H_default.resize(std::max(1, N), 0.0); v_H = v_H_default.data(); }
    if (!v_O2) { v_O2_default.resize(std::max(1, N), 0.0); v_O2 = v_O2_default.data(); }

    SimContext ctx = {M_H_csr, M_O2_csr, v_H, v_O2, num_states};

    // Run single walker
    std::vector<double> y0_local(num_states);
    if (y0_in) {
        std::memcpy(y0_local.data(), y0_in, num_states * sizeof(double));
    } else {
        // Default: bare surface
        std::fill(y0_local.begin(), y0_local.end(), 0.0);
        y0_local[0] = 1.0;
        y0_local[6] = p.E_start;
    }

    simulate_walker(0, p, y0_local.data(),
                    y_out, i_out, E_out,
                    ctx, true, nullptr, nullptr, nullptr);

    // Fill t_out
    if (t_out) {
        double dt = p.t_total / (n_points - 1);
        for (int i = 0; i < n_points; ++i) t_out[i] = i * dt;
    }

    return 0;
}

}  // extern "C"

/* ====  ORIGINAL mexFunction (removed — replaced by oer_mex_solve above)  ==== */
#if 0
void mexFunction(int nlhs, mxArray *plhs[], int nrhs, const mxArray *prhs[]) {
    if (nrhs < 6) mexErrMsgIdAndTxt("OER:Inputs", "Need at least 6 inputs.");

    double* param_matrix = mxGetPr(prhs[0]);
    size_t num_params = mxGetM(prhs[0]);
    size_t num_walkers = mxGetN(prhs[0]);

    if (num_params < 45) mexErrMsgIdAndTxt("OER:ParamSize", "Param vector too small.");

    double* y0_global = mxGetPr(prhs[1]);
    size_t y0_rows = mxGetM(prhs[1]);
    size_t y0_cols = mxGetN(prhs[1]);
    int num_states = (int)y0_rows;
    bool shared_y0 = (y0_cols == 1);

    if (!shared_y0 && y0_cols != num_walkers) mexErrMsgIdAndTxt("OER:Y0Size", "y0 mismatch.");

    double* M_H_ptr_raw = mxGetPr(prhs[2]);
    double* v_H_ptr = mxGetPr(prhs[3]);
    double* M_O2_ptr_raw = mxGetPr(prhs[4]);
    double* v_O2_ptr = mxGetPr(prhs[5]);

    double* I_exp = nullptr;
    if (nrhs >= 7 && !mxIsEmpty(prhs[6])) I_exp = mxGetPr(prhs[6]);

    int N = (int)param_matrix[N_GRID];
    int n_points = (int)param_matrix[N_POINTS];

    CSRMatrix M_H_csr;
    M_H_csr.row_ptr.resize(N + 1);
    M_H_csr.row_ptr[0] = 0;
    for (int i = 0; i < N; ++i) {
        for (int j = 0; j < N; ++j) {
            double val = M_H_ptr_raw[i + j * N];
            if (val != 0.0) {
                M_H_csr.values.push_back(val);
                M_H_csr.col_indices.push_back(j);
            }
        }
        M_H_csr.row_ptr[i+1] = M_H_csr.values.size();
    }

    CSRMatrix M_O2_csr;
    M_O2_csr.row_ptr.resize(N + 1);
    M_O2_csr.row_ptr[0] = 0;
    for (int i = 0; i < N; ++i) {
        for (int j = 0; j < N; ++j) {
            double val = M_O2_ptr_raw[i + j * N];
            if (val != 0.0) {
                M_O2_csr.values.push_back(val);
                M_O2_csr.col_indices.push_back(j);
            }
        }
        M_O2_csr.row_ptr[i+1] = M_O2_csr.values.size();
    }

    SimContext ctx = {M_H_csr, M_O2_csr, v_H_ptr, v_O2_ptr, num_states};

    plhs[0] = mxCreateDoubleMatrix(n_points, 1, mxREAL);
    mwSize dims[3] = {(mwSize)n_points, (mwSize)num_states, (mwSize)num_walkers};
    plhs[1] = mxCreateNumericArray(3, dims, mxDOUBLE_CLASS, mxREAL);
    plhs[2] = mxCreateDoubleMatrix(n_points, num_walkers, mxREAL);
    plhs[3] = mxCreateDoubleMatrix(n_points, num_walkers, mxREAL);

    double* objs_out = nullptr;
    if (nlhs >= 5) {
        plhs[4] = mxCreateDoubleMatrix(num_walkers, 1, mxREAL);
        objs_out = mxGetPr(plhs[4]);
    }

    double* I_sim_out = nullptr;
    if (nlhs >= 6) {
        mwSize dims_sim[3] = {(mwSize)n_points, 8, (mwSize)num_walkers};
        plhs[5] = mxCreateNumericArray(3, dims_sim, mxDOUBLE_CLASS, mxREAL);
        I_sim_out = mxGetPr(plhs[5]);
    }

    double* t_out = mxGetPr(plhs[0]);
    double* y_out = mxGetPr(plhs[1]);
    double* i_out = mxGetPr(plhs[2]);
    double* E_out = mxGetPr(plhs[3]);

    double t_total = param_matrix[T_TOTAL];
    double dt = t_total / (n_points - 1);
    for(int i=0; i<n_points; ++i) t_out[i] = i * dt;

    std::vector<std::thread> threads;
    for (int k = 0; k < num_walkers; ++k) {
        Params p;
        double* pv = &param_matrix[k * num_params];

        p.E_start = pv[E_START]; p.v = pv[V_SCAN]; p.dE = pv[DE]; p.omega = pv[OMEGA];
        p.Ru = pv[RU]; p.Cdl = pv[CDL]; p.A = pv[A_AREA]; p.gamma = pv[GAMMA];
        p.k01 = pv[K01]; p.k02 = pv[K02]; p.k03 = pv[K03]; p.k04 = pv[K04];
        p.E01 = pv[E01]; p.E02 = pv[E02]; p.E03 = pv[E03]; p.E04 = pv[E04];
        p.a = pv[ALPHA]; p.RTF = pv[RTF]; p.invRC = pv[INVRC];
        p.gammaF_Cdl = pv[GAMMAF_CDL];
        p.n_points = (int)pv[N_POINTS];
        p.t_total = pv[T_TOTAL];
        p.N = (int)pv[N_GRID];

        p.kc1 = pv[KC1]; p.kad1 = pv[KAD1];
        p.kc2 = pv[KC2]; p.kad2 = pv[KAD2];
        p.kc3 = pv[KC3]; p.kad3 = pv[KAD3];
        p.Henry_const = pv[HENRY_CONST];
        p.activity_coeff_H = pv[ACTIVITY_COEFF_H];

        if (num_params >= 48) p.use_steady_state = (pv[USE_STEADY_STATE] > 0.5);
        else p.use_steady_state = true;

        for(int b=0; b<8; ++b) p.band[b] = pv[BAND_START + b];
        for(int w=0; w<8; ++w) p.harmonic_weights[w] = pv[WEIGHT_START + w];

        double* walker_obj_ptr = objs_out ? &objs_out[k] : nullptr;

        threads.emplace_back(simulate_walker, k, p, y0_global, y_out, i_out, E_out,
                             ctx, shared_y0, I_exp, walker_obj_ptr, I_sim_out);
    }

    for (auto& th : threads) {
        if (th.joinable()) th.join();
    }
}
#endif  // 0 — end of removed mexFunction
