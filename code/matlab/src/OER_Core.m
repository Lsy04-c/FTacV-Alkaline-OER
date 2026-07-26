classdef OER_Core
    % OER_Core — 碱性 OER 模型统一入口
    % 参照 HER_Core.m 结构，委托各子模块

    methods(Static)

        function list = get_param_list()
            list = OER_Physics.get_param_list();
        end

        function idx = get_state_indices(N)
            idx = OER_Physics.get_state_indices(N);
        end

        function param_vec = pack_parameters(params)
            param_vec = OER_Physics.pack_parameters(params);
        end

        function params = initialize_system(params)
            params = OER_Physics.initialize_system(params);
        end

        function params = initialize_filters(params)
            params = OER_Signal.initialize_filters(params);
        end

        function [t, y, E_actual, i_total] = solve_ode_system(params)
            [t, y, E_actual, i_total] = OER_Physics.solve_ode_system(params);
        end

        function dydt = oer_model(t, y, params)
            dydt = OER_Physics.oer_model(t, y, params);
        end

        function y0 = calculate_steady_state(params)
            y0 = OER_Physics.calculate_steady_state(params);
        end

        function [tdc, I_sim, tdc_exp, I_exp] = process_data(t, y, i_total, params, exp_data)
            [tdc, I_sim, tdc_exp, I_exp] = OER_Signal.process_data(t, y, i_total, params, exp_data);
        end

        function I_dc = extract_dc_fft(signal, df, params)
            I_dc = OER_Signal.extract_dc_fft(signal, df, params);
        end

        function harmonics = extract_harmonics(signal, df, params)
            harmonics = OER_Signal.extract_harmonics(signal, df, params);
        end

        function exp_data = load_experimental_data(params)
            exp_data = OER_IO.load_experimental_data(params);
        end

        function data = read_numeric_file(file_path)
            data = OER_IO.read_numeric_file(file_path);
        end

        function exp_data = load_lsv_data(params, file_path)
            exp_data = OER_IO.load_lsv_data(params, file_path);
        end

        function params = configure_params_for_lsv(params, exp_data)
            params = OER_IO.configure_params_for_lsv(params, exp_data);
        end

        function [params, exp_data] = load_data_for_objective(params, file_path, default_mode)
            [params, exp_data] = OER_IO.load_data_for_objective(params, file_path, default_mode);
        end

        function I_sim_aligned = align_data(tdc, I_sim, tdc_exp)
            I_sim_aligned = OER_Signal.align_data(tdc, I_sim, tdc_exp);
        end

        function objective = calculate_objective(I_sim, I_exp, harmonic_weights)
            objective = OER_Objective.calculate_objective(I_sim, I_exp, harmonic_weights);
        end

        function objective = calculate_objective_lsv_total_current(varargin)
            objective = OER_Objective.calculate_objective_lsv_total_current(varargin{:});
        end

        function objective = calculate_objective_from_simulation(t, y, E_actual, i_total, params, exp_data)
            objective = OER_Objective.calculate_objective_from_simulation(t, y, E_actual, i_total, params, exp_data);
        end

        function current_p = decode_params(x_vals, params, param_names)
            current_p = OER_Objective.decode_params(x_vals, params, param_names);
        end

        function [x, lb, ub, names] = get_optim_config(params)
            [x, lb, ub, names] = OER_Objective.get_optim_config(params);
        end

        function params = apply_aem_thermodynamics(params)
            params = OER_Physics.apply_alkaline_aem_embedded(params);
        end

        function params = apply_default_E0(params)
            params = OER_Physics.apply_default_E0(params);
        end

        function save_folder = create_unique_folder(save_root, data_path, suffix)
            save_folder = OER_IO.create_unique_folder(save_root, data_path, suffix);
        end

    end
end
