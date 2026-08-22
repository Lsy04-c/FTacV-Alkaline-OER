/* 低维 Bonke 分子催化模型的定步长 Crank-Nicolson 求解器（加速可行性原型）。
 * 2 状态 [theta_ox, phi_s]，Newton 迭代 + 2x2 解析 Jacobian。
 * 通过 ctypes 调用，与仓库既有 cpp/oer_cn_solver.cpp 的桥接方式一致。 */
#include <math.h>

static inline void rhs(double th, double ph, double t,
                       double RTF, double a, double k0, double kf, double E0e,
                       double om, double Es, double v, double dE,
                       double invRC, double gFC,
                       double *fa, double *fb, double *kfw, double *krv)
{
    if (th < 0.0) th = 0.0; else if (th > 1.0) th = 1.0;
    double E_app = Es + v * t + dE * sin(om * t);
    double eta = ph - E0e;
    double x1 = (1.0 - a) * RTF * eta;
    double x2 = -a * RTF * eta;
    if (x1 > 700.0) x1 = 700.0;
    if (x2 > 700.0) x2 = 700.0;
    double kf_ = k0 * exp(x1);
    double kr_ = k0 * exp(x2);
    double r_et = kf_ * (1.0 - th) - kr_ * th;
    *fa = r_et - kf * th;
    *fb = (E_app - ph) * invRC - gFC * r_et;
    *kfw = kf_; *krv = kr_;
}

int mc_cn_solve(const double *y0, double t_end, long n_steps, long n_out,
                double RTF, double a, double k0, double kf, double E0e,
                double om, double Es, double v, double dE,
                double invRC, double gFC, double Ru,
                double *out_t, double *out_i)
{
    if (n_steps <= 0 || n_out <= 0 || n_steps % n_out != 0) return -1;
    const double dt = t_end / (double)n_steps;
    const long stride = n_steps / n_out;
    double th = y0[0], ph = y0[1];
    long idx = 0;

    for (long step = 0; step < n_steps; ++step) {
        double t = (double)step * dt;
        if (step % stride == 0 && idx < n_out) {
            out_t[idx] = t;
            out_i[idx] = (Es + v * t + dE * sin(om * t) - ph) / Ru;
            ++idx;
        }
        double tn = t + dt;
        double f1a, f1b, kfw, krv;
        rhs(th, ph, t, RTF, a, k0, kf, E0e, om, Es, v, dE, invRC, gFC,
            &f1a, &f1b, &kfw, &krv);

        double tha = th + dt * f1a, pha = ph + dt * f1b;
        for (int it = 0; it < 12; ++it) {
            double f2a, f2b;
            rhs(tha, pha, tn, RTF, a, k0, kf, E0e, om, Es, v, dE, invRC, gFC,
                &f2a, &f2b, &kfw, &krv);
            double ga = tha - th - 0.5 * dt * (f1a + f2a);
            double gb = pha - ph - 0.5 * dt * (f1b + f2b);
            if (fabs(ga) < 1e-14 && fabs(gb) < 1e-14) break;
            double dret_dth = -(kfw + krv);
            double dret_dph = RTF * ((1.0 - a) * kfw * (1.0 - tha) + a * krv * tha);
            double j11 = 1.0 - 0.5 * dt * (dret_dth - kf);
            double j12 = -0.5 * dt * dret_dph;
            double j21 = -0.5 * dt * (-gFC * dret_dth);
            double j22 = 1.0 - 0.5 * dt * (-invRC - gFC * dret_dph);
            double det = j11 * j22 - j12 * j21;
            if (det == 0.0) return -2;
            tha -= (ga * j22 - j12 * gb) / det;
            pha -= (j11 * gb - j21 * ga) / det;
        }
        th = tha; ph = pha;
    }
    return 0;
}
