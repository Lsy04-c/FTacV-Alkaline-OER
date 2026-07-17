classdef OER_Objective
    % OER_Objective — 目标函数与优化工具

    methods(Static)

        %% --- 目标函数（谐波归一化误差） ---
        function obj = calculate_objective(I_sim, I_exp, harmonic_weights)
            total_error = 0;
            for i = 1:size(I_sim, 2)
                denom = mean(I_exp(:,i).^2);
                if denom <= 0 || ~isfinite(denom), denom = 1e-12; end
                err = mean((I_sim(:,i) - I_exp(:,i)).^2) / denom;
                total_error = total_error + err * harmonic_weights(i);
            end
            obj = total_error / sum(harmonic_weights);
        end

        %% --- 从仿真结果计算目标函数 ---
        function obj = calculate_objective_from_simulation(t, y, E_actual, i_total, params, exp_data)
            mode = string(params.objective_mode);

            if strcmpi(mode, "lsv")
                exp_p = exp_data.potential(:);
                exp_i = exp_data.current(:);
                [exp_p, ord] = sort(exp_p);
                exp_i = exp_i(ord);
                [exp_p, ia] = unique(exp_p, 'stable');
                exp_i = exp_i(ia);
                i_exp = interp1(exp_p, exp_i, E_actual(:), 'pchip');
                j_sim = i_total(:) / params.A * 1e3;
                j_exp = i_exp(:) / params.A * 1e3;
                obj = sqrt(mean((j_sim - j_exp).^2));
                return;
            end

            % FTacV 模式
            i_total = real(double(i_total(:)));
            if nnz(isfinite(i_total)) < max(2, ceil(0.9 * numel(i_total)))
                obj = inf; return;
            end

            [~, I_sim, ~, I_exp] = OER_Objective.process_harmonics(t, i_total, params, exp_data);
            obj = OER_Objective.calculate_objective(I_sim, I_exp, params.harmonic_weights);
        end

        %% --- 谐波提取（简化版 FFT） ---
        function [tdc, I_sim, tdc_exp, I_exp] = process_harmonics(t, i_total, params, exp_data)
            df = 1/mean(diff(t));
            tdc = params.E_start + t(:) * params.v;

            % DC 分量
            if isfield(params, 'lp_filter_sos')
                I_dc = abs(filtfilt(params.lp_filter_sos, params.lp_filter_g, i_total));
            else
                I_dc = abs(lowpass(i_total, params.band(1)/2, df, ...
                    'ImpulseResponse', 'iir', 'Steepness', 0.8));
            end

            % 谐波提取
            harmonics = zeros(length(i_total), 7);
            for k = 1:7
                H = k;
                bw = params.band(H+1);
                lower = max(1e-9, H*params.f - bw/2);
                upper = min(df/2 - 1e-9, H*params.f + bw/2);
                if upper > lower
                    YHar = bandpass(i_total, [lower, upper], df, ...
                        'ImpulseResponse', 'iir', 'Steepness', 0.8);
                    harmonics(:,k) = abs(hilbert(YHar));
                end
            end

            I_sim = [I_dc, harmonics];

            if isempty(exp_data)
                tdc_exp = []; I_exp = [];
            elseif isfield(exp_data, 'I_processed')
                tdc_exp = exp_data.tdc;
                I_exp = exp_data.I_processed;
            else
                tdc_exp = tdc;
                I_exp = zeros(size(I_sim));
            end
        end

        %% --- 数据对齐 ---
        function I_sim_aligned = align_data(tdc, I_sim, tdc_exp)
            if length(tdc) == length(tdc_exp)
                I_sim_aligned = I_sim; return;
            end
            I_sim_aligned = zeros(length(tdc_exp), size(I_sim, 2));
            for i = 1:size(I_sim, 2)
                I_sim_aligned(:,i) = interp1(tdc, I_sim(:,i), tdc_exp, 'pchip', 'extrap');
            end
        end

        %% --- 参数解码 ---
        function current_p = decode_params(x_vals, params, param_names)
            current_p = params;
            for i = 1:length(param_names)
                p_name = param_names{i};
                val = x_vals(i);
                if startsWith(p_name, 'log_')
                    real_name = extractAfter(p_name, 'log_');
                    current_p.(real_name) = 10^val;
                else
                    current_p.(p_name) = val;
                end
            end
            % 重新生成 E0
            current_p = OER_Physics.apply_alkaline_aem_embedded(current_p);
        end

        %% --- 优化配置 ---
        function [x, lb, ub, names] = get_optim_config(params)
            names = params.optimize_params;
            N = length(names);
            x  = zeros(N, 1);
            lb = zeros(N, 1);
            ub = zeros(N, 1);

            for i = 1:N
                name = names{i};
                range_name = [name '_range'];
                if isfield(params, range_name)
                    range = params.(range_name);
                else
                    range = [-1e5, 1e5];
                end
                lb(i) = range(1);
                ub(i) = range(2);

                if isfield(params, name)
                    x(i) = params.(name);
                elseif startsWith(name, 'log_')
                    orig = extractAfter(name, 'log_');
                    if isfield(params, orig)
                        x(i) = log10(params.(orig));
                    else
                        x(i) = (lb(i) + ub(i)) / 2;
                    end
                else
                    x(i) = (lb(i) + ub(i)) / 2;
                end
                x(i) = max(lb(i), min(ub(i), x(i)));
            end
        end

    end
end
