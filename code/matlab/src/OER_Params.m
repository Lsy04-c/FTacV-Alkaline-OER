classdef OER_Params
    % OER_Params — 参数打包与默认值解析
    methods(Static)

        function list = get_param_list()
            list = OER_Physics.get_param_list();
        end

        function param_vec = pack_parameters(params)
            param_vec = OER_Physics.pack_parameters(params);
        end

        function params = resolve_defaults(params)
            if ~isfield(params, 'band'), params.band = ones(1,8)*0.01; end
            if ~isfield(params, 'harmonic_weights'), params.harmonic_weights = ones(1,8); end
            if ~isfield(params, 'use_steady_state'), params.use_steady_state = true; end
            if ~isfield(params, 'use_fft'), params.use_fft = true; end
            if ~isfield(params, 'use_mex'), params.use_mex = false; end
            if ~isfield(params, 'a'), params.a = 0.5; end
            if ~isfield(params, 'N'), params.N = 2; end
            if ~isfield(params, 'objective_mode'), params.objective_mode = 'ftacv'; end
        end
    end
end
