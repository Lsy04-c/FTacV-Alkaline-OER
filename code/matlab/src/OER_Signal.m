classdef OER_Signal
    % OER_Signal — FTacV 信号处理（谐波提取、滤波、对齐）
    % 参照 HER_Signal.m 结构，适配碱性 OER AEM 模型

    methods(Static)

        %% --- 滤波器初始化 ---
        function params = initialize_filters(params)
            dt = params.total_time / (params.n_points - 1);
            fs = 1 / dt;

            % DC 低通滤波器
            fc = params.band(1) / 2;
            [z, p, k] = butter(6, fc / (fs / 2));
            [sos, g] = zp2sos(z, p, k);
            params.lp_filter_sos = sos;
            params.lp_filter_g = g;

            [~, d] = lowpass(zeros(32, 1), fc, fs, ...
                'ImpulseResponse', 'iir', 'Steepness', 0.8);
            params.lp_filter = d;
            params.lp_filter_fs = fs;
            params.lp_filter_fpass = fc;

            % 1-7 次谐波带通滤波器
            bp_filters = cell(7, 1);
            bp_edges = NaN(7, 2);
            for i = 1:7
                H = i;
                bw = params.band(H + 1);
                lower = H * params.f - bw / 2;
                upper = H * params.f + bw / 2;
                epsf = max(1e-9, 1e-6 * fs);
                lower = max(epsf, lower);
                upper = min(fs / 2 - epsf, upper);
                bp_edges(i, :) = [lower, upper];
                if upper <= lower
                    bp_filters{i} = [];
                else
                    [~, d_bp] = bandpass(zeros(32, 1), [lower, upper], fs, ...
                        'ImpulseResponse', 'iir', 'Steepness', 0.8);
                    bp_filters{i} = d_bp;
                end
            end
            params.bp_filters = bp_filters;
            params.bp_filter_edges = bp_edges;
            params.bp_filter_fs = fs;
        end

        %% --- 主数据处理入口 ---
        function [tdc, I_sim, tdc_exp, I_exp] = process_data(t, ~, i_total, params, exp_data)
            t = t(:);
            i_total = i_total(:);

            tdc = OER_Signal.compute_tdc(t, params);
            df_sim = OER_Signal.safe_df(t);
            I_sim = OER_Signal.process_current(i_total, df_sim, params);

            [tdc_exp, I_exp] = OER_Signal.process_experimental(exp_data, params);
        end

        %% --- FFT 提取 DC 分量 ---
        function I_dc = extract_dc_fft(signal, df, params)
            L = length(signal);
            Y = fft(signal);
            f_axis = df * (0:(L - 1))' / L;
            bw_half = params.band(1) / 2;

            mask = (f_axis <= bw_half) | (f_axis >= (df - bw_half));
            Y_filtered = zeros(size(Y));
            Y_filtered(mask) = Y(mask);
            I_dc = abs(ifft(Y_filtered));
        end

        %% --- FFT 提取谐波（1-7 次） ---
        function harmonics = extract_harmonics(signal, df, params)
            band = params.band;
            f0 = params.f;

            if params.use_fft
                L = length(signal);
                Y = fft(signal);
                f_axis = df * (0:(L - 1))' / L;
                harmonics = zeros(L, 7);
                half_L = floor(L / 2) + 1;

                for k = 1:7
                    H = k;
                    bw = band(H + 1);
                    center_freq = H * f0;

                    lb = center_freq - bw / 2;
                    ub = center_freq + bw / 2;
                    idx_pos = (f_axis >= lb) & (f_axis <= ub);
                    idx_pos(1) = false;
                    pos_mask = idx_pos & ((1:L)' > 1) & ((1:L)' < half_L + 1);

                    mask_analytic = zeros(size(Y));
                    mask_analytic(pos_mask) = 2;   % Hilbert 包络

                    harmonics(:, k) = abs(ifft(Y .* mask_analytic));
                end
            else
                % 时域带通 + Hilbert 包络
                harmonics = zeros(length(signal), 7);
                for i = 1:7
                    H = i;
                    bw = band(H + 1);
                    lower = H * f0 - bw / 2;
                    upper = H * f0 + bw / 2;
                    epsf = max(1e-9, 1e-6 * df);
                    lower = max(epsf, lower);
                    upper = min(df / 2 - epsf, upper);
                    if upper <= lower
                        YHarC = zeros(size(signal));
                    else
                        if isfield(params, 'bp_filters') && ~isempty(params.bp_filters{i})
                            YHarC = filtfilt(params.bp_filters{i}, signal);
                        else
                            YHarC = bandpass(signal, [lower, upper], df, ...
                                'ImpulseResponse', 'iir', 'Steepness', 0.8);
                        end
                    end
                    harmonics(:, i) = abs(hilbert(YHarC));
                end
            end
        end

        %% --- 数据对齐（插值到公共电位网格） ---
        function I_sim_aligned = align_data(tdc, I_sim, tdc_exp)
            tdc = tdc(:);
            tdc_exp = tdc_exp(:);

            if length(tdc) == length(tdc_exp)
                I_sim_aligned = I_sim;
                return;
            end

            [x_unique, keep_idx] = unique(tdc, 'stable');
            y_keep = I_sim(keep_idx, :);
            [x_sorted, sort_idx] = sort(x_unique);
            y_sorted = y_keep(sort_idx, :);

            I_sim_aligned = NaN(length(tdc_exp), size(I_sim, 2));
            for i = 1:size(I_sim, 2)
                yi = y_sorted(:, i);
                if length(x_sorted) > 1
                    I_sim_aligned(:, i) = interp1(x_sorted, yi, tdc_exp, 'pchip', 'extrap');
                else
                    I_sim_aligned(:, i) = yi(1);
                end
            end
        end

    end

    methods(Static, Access = private)

        function tdc = compute_tdc(t, params)
            tdc = params.E_start + t * params.v;
        end

        function df = safe_df(t)
            if length(t) > 1
                df = 1 / mean(diff(t));
            else
                df = 1.0;
            end
        end

        function I_processed = process_current(current, df, params)
            current = current(:);
            if ~isa(current, 'double'), current = double(current); end
            if ~isreal(current), current = real(current); end

            if any(~isfinite(current))
                if all(~isfinite(current)), current(:) = 0;
                else
                    current = fillmissing(current, 'linear', 'EndValues', 'nearest');
                    current(~isfinite(current)) = 0;
                end
            end

            if params.use_fft
                I_dc = OER_Signal.extract_dc_fft(current, df, params);
            else
                ydc = lowpass(current, params.band(1) / 2, df, ...
                    'ImpulseResponse', 'iir', 'Steepness', 0.8);
                I_dc = abs(ydc);
            end

            I_harm = OER_Signal.extract_harmonics(current, df, params);
            I_processed = [I_dc, I_harm];
        end

        function [tdc_exp, I_exp] = process_experimental(exp_data, params)
            if isempty(exp_data)
                tdc_exp = []; I_exp = []; return;
            end
            if isfield(exp_data, 'I_processed') && isfield(exp_data, 'tdc')
                tdc_exp = exp_data.tdc(:);
                I_exp = exp_data.I_processed;
                return;
            end

            current = exp_data.current(:);
            if isfield(exp_data, 'df')
                df = exp_data.df;
            else
                df = OER_Signal.safe_df(exp_data.time(:));
            end

            if isfield(exp_data, 'tdc')
                tdc_exp = exp_data.tdc(:);
            else
                tdc_exp = OER_Signal.compute_tdc(exp_data.time(:), params);
            end

            I_exp = OER_Signal.process_current(current, df, params);
        end

    end
end
