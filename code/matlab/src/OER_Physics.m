classdef OER_Physics
    % OER_Physics — 碱性 OER 微观动力学模型（含预氧化步骤）
    %
    % 模型参考：
    %   Bonke et al. (2016) JACS 138, 16095–16104.
    %   Snitkoff-Sol et al. (2024) Nat. Catal. 7, 139–147.
    %   Bergmann et al. (2015) Nat. Commun. 6, 8625.
    %
    % 反应步骤（5 步）：
    %   0. * + OH-  <=> *ox + H2O + e-       预氧化（Co3+ -> Co4+）
    %   1. *ox + OH- <=> *ox-OH + e-         AEM-1
    %   2. *ox-OH + OH- <=> *ox-O + H2O + e-  AEM-2
    %   3. *ox-O + OH- <=> *ox-OOH + e-       AEM-3
    %   4. *ox-OOH + OH- <=> *ox + O2 + H2O + e-  AEM-4

    methods(Static)

        %% --- 状态索引 ---
        function idx = get_state_indices(N)
            % N: 扩散网格点数（初始模型 N=2，暂不含传质）
            idx.theta_star    = 1;   % *   — 还原态 Co 位点
            idx.theta_ox      = 2;   % *ox — 氧化态 Co 位点（OER 活性位）
            idx.theta_OH      = 3;   % *ox-OH
            idx.theta_O       = 4;   % *ox-O
            idx.theta_OOH     = 5;   % *ox-OOH
            idx.phi_s         = 6;   % 表面电位 (V)
            idx.num_states    = 6;   % 不含传质时为 6
        end

        %% --- 参数列表（与 MEX 兼容的严格顺序） ---
        function list = get_param_list()
            list = {
                'E_start', 'v', 'dE', 'omega', ...       % 1-4
                'Ru', 'Cdl', 'A', 'gamma', ...            % 5-8
                'k0_pre', 'k0_1', 'k0_2', 'k0_3', 'k0_4', ... % 9-13
                'E0_pre', 'E01', 'E02', 'E03', 'E04', ... % 14-18
                'a', 'RTF', 'invRC', ...                  % 19-21
                'gammaF_Cdl', ...                          % 22
                'n_points', 'total_time', 'N' ...          % 23-25
            };
        end

        %% --- 参数打包 ---
        function param_vec = pack_parameters(params)
            list = OER_Physics.get_param_list();
            n_basic = length(list);
            total_len = n_basic + 8 + 8;  % +band +weights
            param_vec = zeros(total_len, 1);

            for i = 1:n_basic
                name = list{i};
                if isfield(params, name)
                    param_vec(i) = params.(name);
                else
                    error('OER_Physics:MissingParam', '缺少参数: %s', name);
                end
            end

            base_idx = n_basic;
            if isfield(params, 'band')
                param_vec(base_idx+1 : base_idx+8) = params.band(:);
            end
            base_idx = base_idx + 8;

            if isfield(params, 'harmonic_weights')
                param_vec(base_idx+1 : base_idx+8) = params.harmonic_weights(:);
            end
        end

        %% --- 系统初始化 ---
        function params = initialize_system(params)
            % 填充默认值
            if ~isfield(params, 'a'),  params.a = 0.5; end
            if ~isfield(params, 'N'),  params.N = 2; end
            if ~isfield(params, 'band'), params.band = ones(1,8)*0.01; end
            if ~isfield(params, 'harmonic_weights'), params.harmonic_weights = ones(1,8); end
            if ~isfield(params, 'use_steady_state'), params.use_steady_state = true; end
            if ~isfield(params, 'use_mex'), params.use_mex = false; end
            if ~isfield(params, 'use_fft'), params.use_fft = true; end

            % 物理常数
            if ~isfield(params, 'F'), params.F = 96485; end
            if ~isfield(params, 'R'), params.R = 8.314; end
            if ~isfield(params, 'T'), params.T = 298.15; end

            % 衍生常数
            params.RTF   = params.F / (params.R * params.T);
            params.invRC = 1 / (params.Ru * params.Cdl * params.A);
            params.gammaF_Cdl = params.gamma * params.F / params.Cdl;
            params.omega = 2 * pi * params.f;
        end

        %% --- 预氧化 + AEM 微观动力学模型（核心） ---
        function dydt = oer_model(t, y, params)
            % 提取状态变量
            theta_star = y(1);   % *   还原态 Co
            theta_ox   = y(2);   % *ox 氧化态 Co（活性位）
            theta_OH   = y(3);   % *ox-OH
            theta_O    = y(4);   % *ox-O
            theta_OOH  = y(5);   % *ox-OOH
            phi_s      = y(6);   % 表面电位

            % 归一化覆盖度
            theta_sum = theta_star + theta_ox + theta_OH + theta_O + theta_OOH;
            if theta_sum > 1e-12
                theta_star = theta_star / theta_sum;
                theta_ox   = theta_ox   / theta_sum;
                theta_OH   = theta_OH   / theta_sum;
                theta_O    = theta_O    / theta_sum;
                theta_OOH  = theta_OOH  / theta_sum;
            end

            % 施加电位
            E_dc  = params.E_start + params.v * t;
            E_app = E_dc + params.dE * sin(params.omega * t);

            % 模型假设（碱性，微纳体系）：
            %   a_OH- = a_H2O = 1, P_O2 ≈ 0
            a_OH  = 1;
            a_H2O = 1;

            % Butler-Volmer 指数
            RTF = params.RTF;
            a   = params.a;
            b   = 1 - a;

            % ---- 各步过电位 ----
            eta_pre = phi_s - params.E0_pre;
            eta_1   = phi_s - params.E01;
            eta_2   = phi_s - params.E02;
            eta_3   = phi_s - params.E03;
            eta_4   = phi_s - params.E04;

            % ---- BV 速率常数 ----
            % 步骤 0: * + OH- <=> *ox + H2O + e-
            k_fwd_pre = params.k0_pre * exp( b * RTF * eta_pre);
            k_rev_pre = params.k0_pre * exp(-a * RTF * eta_pre);

            % 步骤 1: *ox + OH- <=> *ox-OH + e-
            k_fwd_1 = params.k0_1 * exp( b * RTF * eta_1);
            k_rev_1 = params.k0_1 * exp(-a * RTF * eta_1);

            % 步骤 2: *ox-OH + OH- <=> *ox-O + H2O + e-
            k_fwd_2 = params.k0_2 * exp( b * RTF * eta_2);
            k_rev_2 = params.k0_2 * exp(-a * RTF * eta_2);

            % 步骤 3: *ox-O + OH- <=> *ox-OOH + e-
            k_fwd_3 = params.k0_3 * exp( b * RTF * eta_3);
            k_rev_3 = params.k0_3 * exp(-a * RTF * eta_3);

            % 步骤 4: *ox-OOH + OH- <=> *ox + O2 + H2O + e-
            k_fwd_4 = params.k0_4 * exp( b * RTF * eta_4);
            k_rev_4 = params.k0_4 * exp(-a * RTF * eta_4);

            % ---- 各步速率（正向 - 反向） ----
            r_pre = k_fwd_pre * theta_star * a_OH ...
                  - k_rev_pre * theta_ox   * a_H2O;

            r_1 = k_fwd_1 * theta_ox * a_OH ...
                - k_rev_1 * theta_OH;

            r_2 = k_fwd_2 * theta_OH * a_OH ...
                - k_rev_2 * theta_O  * a_H2O;

            r_3 = k_fwd_3 * theta_O * a_OH ...
                - k_rev_3 * theta_OOH;

            r_4 = k_fwd_4 * theta_OOH * a_OH ...
                - k_rev_4 * theta_ox  * a_H2O;  % P_O2≈0, 忽略反向 O2 项

            % ---- 覆盖度演化 ----
            dtheta_star = -r_pre + 0;               % 只有预氧化出入
            dtheta_ox   =  r_pre - r_1 + r_4;       % 预氧化产生, AEM-1消耗, AEM-4再生
            dtheta_OH   =  r_1 - r_2;
            dtheta_O    =  r_2 - r_3;
            dtheta_OOH  =  r_3 - r_4;

            % ---- 表面电位演化 ----
            r_elec_sum = r_pre + r_1 + r_2 + r_3 + r_4;
            dphi_s = (E_app - phi_s) * params.invRC ...
                   + params.gammaF_Cdl * r_elec_sum;

            % ---- 组装 dydt ----
            dydt = [dtheta_star; dtheta_ox; dtheta_OH; dtheta_O; dtheta_OOH; dphi_s];
        end

        %% --- ODE 求解 ---
        function [t, y, E_actual, i_total] = solve_ode_system(params)
            if ~isfield(params, 'RTF')
                params = OER_Physics.initialize_system(params);
            end

            num_states = 6;
            y0 = zeros(num_states, 1);
            y0(1) = 1.0;              % 初始全部为还原态 *
            y0(6) = params.E_start;   % 初始电位

            % 稳态初始化（可选）
            if params.use_steady_state
                y0 = OER_Physics.calculate_steady_state(params);
            end

            options = odeset('RelTol', 1e-5, 'AbsTol', 1e-6, ...
                'NonNegative', 1:5);  % 覆盖度非负

            try
                [t, y] = ode15s(@(t,y) OER_Physics.oer_model(t, y, params), ...
                    params.t_span, y0, options);
                E_dc = params.E_start + params.v * t;
                E_actual = E_dc + params.dE * sin(params.omega * t);
                i_total = (E_actual - y(:,6)) / params.Ru;
            catch ME
                warning('OER_Physics:ODESolverFailed', 'ODE 求解失败: %s', ME.message);
                t = params.t_span(:);
                y = NaN(length(t), num_states);
                E_actual = NaN(length(t), 1);
                i_total = NaN(length(t), 1);
            end
        end

        %% --- 稳态计算 ---
        function y0 = calculate_steady_state(params)
            num_states = 6;
            y0_guess = zeros(num_states, 1);
            y0_guess(1) = 1.0;
            y0_guess(6) = params.E_start;

            % 短时间松弛积分
            params_ss = params;
            params_ss.v = 0.0;
            params_ss.dE = 0.0;
            params_ss.omega = 0.0;

            ss_time = 5.0;
            options = odeset('RelTol', 1e-6, 'AbsTol', 1e-8, ...
                'NonNegative', 1:5);

            try
                [~, y_ss] = ode15s(@(t,y) OER_Physics.oer_model(t, y, params_ss), ...
                    [0 ss_time], y0_guess, options);
                y0 = y_ss(end, :)';
            catch
                warning('OER_Physics:SteadyStateFailed', ...
                    '稳态计算失败，使用默认初值');
                y0 = y0_guess;
            end
        end

        %% --- 获取默认 E0 值（基于 Bonke 2016 + AEM 标度关系） ---
        function params = apply_default_E0(params)
            % 若未提供 AEM 自由能参数，使用 Bonke 2016 的 CoOx 数据估算
            if ~isfield(params, 'E0_pre') && isfield(params, 'G_OH')
                % 从自由能生成所有 E0（调用 apply_alkaline_aem 的热力学部分）
                params = OER_Physics.apply_alkaline_aem_embedded(params);
            elseif ~isfield(params, 'E0_pre')
                % 使用 Bonke 2016 CoOx 的默认值（中性硼酸，仅供参考）
                params.E0_pre = 1.50;   % Co3+/4+ 氧化 ~1.5 V
                params.E01    = 1.55;   % * -> *OH, 略高于氧化电位
                params.E02    = 1.60;
                params.E03    = 1.70;
                params.E04    = 1.45;
            end
        end

        function params = apply_alkaline_aem_embedded(params)
            % 内嵌版 AEM 热力学约束（独立版见 apply_alkaline_aem.m）
            G_total = 4 * 1.23;

            G_OH = params.G_OH;
            G_O  = params.G_O;

            if ~isfield(params, 'scaling_OOH_OH')
                scaling_OOH_OH = 3.2;
            else
                scaling_OOH_OH = params.scaling_OOH_OH;
            end

            G_OOH = G_OH + scaling_OOH_OH;

            dG1 = G_OH;
            dG2 = G_O - G_OH;
            dG3 = G_OOH - G_O;
            dG4 = G_total - G_OOH;

            % AEM 平衡电位
            params.E01 = dG1;
            params.E02 = dG2;
            params.E03 = dG3;
            params.E04 = dG4;

            % 预氧化电位：取 Co3+/4+ 氧化 ≈ G_OH 位置
            % （Bonke 2016: E0_cat 在 1.9-2.1 V RHE，对应氧化步骤）
            if ~isfield(params, 'E0_pre')
                params.E0_pre = 1.50;  % Co3+/4+ in alkaline
            end

            % 存储
            params.G_OOH   = G_OOH;
            params.DeltaG1 = dG1;
            params.DeltaG2 = dG2;
            params.DeltaG3 = dG3;
            params.DeltaG4 = dG4;
        end

    end
end
