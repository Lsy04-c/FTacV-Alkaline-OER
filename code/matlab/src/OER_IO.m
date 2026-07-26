classdef OER_IO
    % OER_IO — 实验数据加载与导出
    % 参照 HER_IO.m 结构，适配碱性 OER AEM 模型

    methods(Static)

        %% --- 加载 FTacV 实验数据 ---
        function exp_data = load_experimental_data(params)
            raw_data = OER_IO.read_numeric_file(params.data_path);
            if size(raw_data, 2) < 3
                error('OER_IO:BadExperimentalData', '实验数据列数不足: %s', params.data_path);
            end
            raw_data = raw_data(:, 1:3);

            if isfield(params, 'Eref') && params.Eref ~= 0
                raw_data(:, 1) = raw_data(:, 1) + params.Eref;
            end

            time_rel = raw_data(:, 3) - raw_data(1, 3);
            [time_rel_sorted, ord] = sort(time_rel);
            raw_data = raw_data(ord, :);

            [time_unique, ia] = unique(time_rel_sorted, 'stable');
            t_e_exp = linspace(0, params.total_time, params.n_points)';

            exp_data = struct();
            exp_data.raw = raw_data;
            exp_data.time = t_e_exp;
            exp_data.current = interp1(time_unique, raw_data(ia, 2), ...
                t_e_exp, 'pchip', 'extrap');

            dt = mean(diff(t_e_exp));
            exp_data.df = 1 / dt;
            exp_data.i_total = exp_data.current;

            % 预处理实验谐波
            [tdc, I_processed] = OER_Signal.process_data( ...
                exp_data.time, [], exp_data.current, params, []);
            exp_data.tdc = tdc;
            exp_data.I_processed = I_processed;
            exp_data.I_dc = I_processed(:, 1);
            exp_data.I_harmonics = I_processed(:, 2:8);
        end

        %% --- 读取数值文件 ---
        function data = read_numeric_file(file_path)
            if exist(file_path, 'file') ~= 2
                error('OER_IO:FileNotFound', '文件不存在: %s', file_path);
            end
            data = readmatrix(file_path, 'FileType', 'text');
            if isempty(data) || ~isnumeric(data)
                error('OER_IO:BadExperimentalData', '实验数据无法读取: %s', file_path);
            end
        end

        %% --- 加载 LSV 数据 ---
        function exp_data = load_lsv_data(params, file_path)
            if nargin < 2 || isempty(file_path)
                file_path = params.data_path;
            end

            rawAll = readmatrix(file_path, 'FileType', 'text');
            if size(rawAll, 2) < 3
                error('OER_IO:NoNumericData', '未解析到任何数值数据。');
            end

            potential = rawAll(:, 1);
            current = rawAll(:, 2);
            timeAbs = rawAll(:, 3);
            timeRel = timeAbs - timeAbs(1);

            if isfield(params, 'Eref') && params.Eref ~= 0
                potential = potential + params.Eref;
            end

            exp_data = struct();
            exp_data.raw = [potential, current, timeAbs];
            exp_data.potential_raw = potential;
            exp_data.current_raw = current;
            exp_data.time_raw = timeRel;

            [timeRel_sorted, ord] = sort(timeRel);
            potential_sorted = potential(ord);
            current_sorted = current(ord);

            [time_unique, ia] = unique(timeRel_sorted, 'stable');
            potential_u = potential_sorted(ia);
            current_u = current_sorted(ia);

            time_grid = linspace(0, params.total_time, params.n_points)';
            exp_data.time = time_grid;
            exp_data.current = interp1(time_unique, current_u, time_grid, 'pchip', 'extrap');
            exp_data.potential = interp1(time_unique, potential_u, time_grid, 'pchip', 'extrap');

            dt = mean(diff(exp_data.time));
            exp_data.df = 1 / dt;
            exp_data.i_total = exp_data.current;
        end

        %% --- 配置 LSV 模式参数 ---
        function params = configure_params_for_lsv(params, exp_data)
            t_end = exp_data.time_raw(end);
            params.dE = 0;
            params.total_time = t_end;
            params.n_points = length(exp_data.time_raw);
            params.t_span = linspace(0, params.total_time, params.n_points);
            params.E_start = exp_data.potential_raw(1);
            params.E_end = exp_data.potential_raw(end);
            params.omega = 2 * pi * params.f;
            params.v = (params.E_end - params.E_start) / params.total_time;
            params = OER_Physics.initialize_system(params);
        end

        %% --- 统一数据加载入口 ---
        function [params, exp_data] = load_data_for_objective(params, file_path, default_mode)
            if nargin >= 2 && ~isempty(file_path)
                params.data_path = file_path;
            end
            if nargin < 3 || isempty(default_mode)
                default_mode = "ftacv";
            end

            params.objective_mode = string(default_mode);

            if strcmpi(params.objective_mode, "lsv")
                exp_data = OER_IO.load_lsv_data(params);
                params.dE = 0;
                exp_data.potential = exp_data.potential_raw(:);
                exp_data.current = exp_data.current_raw(:);
                exp_data.time = exp_data.time_raw(:);
                params.total_time = exp_data.time_raw(end);
                params.n_points = length(exp_data.time_raw);
                params.t_span = linspace(0, params.total_time, params.n_points);
                params.omega = 2 * pi * params.f;
                params.v = (params.E_end - params.E_start) / params.total_time;
                params = OER_Physics.initialize_system(params);
            else
                exp_data = OER_IO.load_experimental_data(params);
                params = OER_Physics.initialize_system(params);
            end
        end

        %% --- 创建唯一保存文件夹 ---
        function save_folder = create_unique_folder(save_root, data_path, suffix)
            [filepath, filename, ~] = fileparts(data_path);
            [~, parent_folder, ~] = fileparts(filepath);

            if nargin > 2 && ~isempty(suffix)
                base_name = sprintf('%s_%s_%s', parent_folder, filename, suffix);
            else
                base_name = sprintf('%s_%s', parent_folder, filename);
            end

            main_folder_path = fullfile(save_root, base_name);
            if ~exist(main_folder_path, 'dir')
                [success, msg] = mkdir(main_folder_path);
                if ~success
                    error('无法创建主保存文件夹：%s\n错误信息: %s', main_folder_path, msg);
                end
            end

            i = 1;
            while true
                sub_folder_name = sprintf('%d', i);
                folder_name = fullfile(main_folder_path, sub_folder_name);
                if ~exist(folder_name, 'dir')
                    [success, msg] = mkdir(folder_name);
                    if ~success
                        error('无法创建子保存文件夹：%s\n错误信息: %s', folder_name, msg);
                    end
                    save_folder = folder_name;
                    break;
                end
                i = i + 1;
            end
        end

        %% --- 导出数据 ---
        function export_data(data, params, data_type)
            save_dir = fullfile(params.result_root, 'exported_simulation_data');
            if ~exist(save_dir, 'dir'), mkdir(save_dir); end

            [~, base_filename, ~] = fileparts(params.data_path);
            export_filename = fullfile(save_dir, ...
                sprintf('%s_%s_exported.txt', base_filename, data_type));
            writematrix(data, export_filename, 'Delimiter', 'tab');
            fprintf('数据已导出到: %s\n', export_filename);
        end

        function export_i_total(E_actual, i_total, t, params)
            data = [E_actual, i_total, t];
            OER_IO.export_data(data, params, 'i_total');
        end

        function export_I_sim(tdc, I_sim, params)
            data = [tdc, I_sim];
            OER_IO.export_data(data, params, 'I_sim');
        end

        function export_I_exp(tdc_exp, I_exp, params)
            data = [tdc_exp, I_exp];
            OER_IO.export_data(data, params, 'I_exp');
        end

    end
end
