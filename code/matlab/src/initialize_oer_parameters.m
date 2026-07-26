function params = initialize_oer_parameters()
% initialize_oer_parameters  碱性 OER AEM 模型参数初始化
%
%   基于 Bonke 2016 JACS 的 CoOx 数据 + AEM 标度关系，
%   针对四氧化三钴碱性体系进行参数设置。
%
%   参考：
%     Bonke et al. (2016) JACS 138, 16095–16104.
%     Snitkoff-Sol et al. (2024) Nat. Catal. 7, 139–147.
%     Bergmann et al. (2015) Nat. Commun. 6, 8625.

    %% ==================== 数据路径 ====================
    params.data_path = "";  % 填入你的 FTacV 实验数据路径
    params.result_root = "";

    %% ==================== AEM 热力学参数（物理描述符） ====================
    % 中间体吸附自由能 (eV)
    params.G_OH = 1.55;             % *OH 吸附自由能
    params.G_O  = 3.10;             % *O 吸附自由能
    params.scaling_OOH_OH = 3.2;    % *OOH/*OH 标度偏移（可调）

    %% ==================== 预氧化参数 ====================
    % 步骤 0: * + OH- <=> *ox + H2O + e-
    % Bonke 2016: CoOx 的 E0_cat ≈ 1.94–2.00 V (中性 KPi)
    % 碱性条件下 Co3+/4+ 氧化电位较低，约 1.4–1.6 V vs RHE
    params.E0_pre = 1.50;
    params.k0_pre = 100;            % 预氧化速率 (s-1)

    %% ==================== AEM 动力学参数 ====================
    % 步骤 1-4: 标准速率常数 (s-1)
    params.k0_1 = 1e4;    % *ox -> *ox-OH, 快速 OH- 吸附
    params.k0_2 = 1e4;    % *ox-OH -> *ox-O
    params.k0_3 = 10;     % *ox-O -> *ox-OOH, O-O 键形成，较慢
    params.k0_4 = 1e3;    % *ox-OOH -> *ox + O2

    %% ==================== 电极与电解液参数 ====================
    params.electrode_type = 'Planar';
    params.A = 0.196;              % 电极面积 (cm2)
    params.Ru = 75;                % 未补偿电阻 (Ohm)
    params.Cdl = 60e-6;            % 双电层电容 (F/cm2)
    params.gamma = 1e-9;           % 活性位点总浓度 (mol/cm2)
                                   % 注：~1.8% Co 参与反应 (Bergmann 2015)，
                                   % 微纳体系实际值需根据实验调整

    %% ==================== FTacV 扫描参数 ====================
    params.Eref = 0;               % 参比偏置 (V)
    params.E_start = 0.9;          % 起始电位 (V vs RHE)
    params.E_end   = 1.8;          % 终止电位 (V vs RHE)
    params.n_points = 8192;        % 总采样点数
    params.points_per_cycle = 64;  % 每周期点数
    params.f = 9.02;               % 正弦频率 (Hz)
    params.dE = 0.08;              % 交流振幅 (V)

    %% ==================== 物理常数 ====================
    params.F = 96485;              % 法拉第常数 (C/mol)
    params.R = 8.314;              % 气体常数 (J/(mol·K))
    params.T = 298.15;             % 温度 (K)
    params.a = 0.5;                % 转移系数

    %% ==================== 数值参数 ====================
    params.N = 2;                  % 扩散网格（暂不透传质）
    params.use_steady_state = true;
    params.use_mex = false;        % 先用纯 MATLAB 调试
    params.use_fft = true;
    params.objective_mode = "ftacv";

    %% ==================== 谐波与滤波 ====================
    params.band = ones(1,8) * 0.01;
    params.harmonic_weights = [1, 1, 1, 1, 1, 1, 1, 1];

    %% ==================== 优化设置 ====================
    params.max_number = 50000;
    params.optimize_params = {
        'G_OH', 'G_O', 'scaling_OOH_OH', ...
        'log_k0_pre', 'log_k0_1', 'log_k0_2', 'log_k0_3', 'log_k0_4', ...
        'E0_pre', 'log_gamma', 'Ru'
    };

    % 优化范围
    params.G_OH_range = [1.0, 2.2];
    params.G_O_range  = [2.0, 4.0];
    params.scaling_OOH_OH_range = [2.8, 3.4];
    params.log_k0_pre_range = [-2, 5];
    params.log_k0_1_range  = [-2, 5];
    params.log_k0_2_range  = [-2, 5];
    params.log_k0_3_range  = [-2, 5];
    params.log_k0_4_range  = [-2, 5];
    params.E0_pre_range    = [1.2, 1.8];
    params.log_gamma_range = [-12, -7];
    params.Ru_range        = [0, 200];

    %% ==================== 衍生参数计算 ====================
    params.omega = 2 * pi * params.f;
    params.total_time = (params.n_points / params.points_per_cycle) / params.f;
    params.v = (params.E_end - params.E_start) / params.total_time;
    params.t_span = linspace(0, params.total_time, params.n_points);

    %% ==================== 应用 AEM 热力学约束生成 E01-E04 ====================
    params = OER_Physics.apply_alkaline_aem_embedded(params);

    %% ==================== 初始化系统 ====================
    params = OER_Physics.initialize_system(params);

    %% ==================== 构建初始优化向量 ====================
    [x0, ~, ~, names] = OER_Objective.get_optim_config(params);
    params.initial_x = array2table(x0(:)', 'VariableNames', names);

    %% ==================== 打印参数摘要 ====================
    fprintf('\n========== OER AEM 模型参数初始化完成 ==========\n');
    fprintf('热力学描述符:\n');
    fprintf('  G_OH  = %.2f eV\n', params.G_OH);
    fprintf('  G_O   = %.2f eV\n', params.G_O);
    fprintf('  scaling_OOH_OH = %.2f eV (G_OOH = %.2f eV)\n', ...
        params.scaling_OOH_OH, params.G_OOH);
    fprintf('平衡电位:\n');
    fprintf('  E0_pre = %.3f V (预氧化)\n', params.E0_pre);
    fprintf('  E01 = %.3f, E02 = %.3f, E03 = %.3f, E04 = %.3f V\n', ...
        params.E01, params.E02, params.E03, params.E04);
    fprintf('  ΣE0 = %.3f V (OER总 = 4.92 V)\n', ...
        params.E0_pre + params.E01 + params.E02 + params.E03 + params.E04);
    fprintf('理论过电位: η = %.3f V\n', ...
        max([params.E01, params.E02, params.E03, params.E04]) - 1.23);
    fprintf('==================================================\n\n');
end
