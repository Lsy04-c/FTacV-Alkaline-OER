"""碱性 OER 模型统一入口（对应 MATLAB OER_Core.m）。"""

from .physics import (
    OERPhysics,
    get_state_indices,
    get_param_list,
    initialize_system,
    apply_default_E0,
)
from .signal import OERSignal
from .objective import OERObjective
from .io import OERIO


class OERCore:
    """统一入口封装，委托各子模块。"""

    # Physics
    @staticmethod
    def get_param_list():
        return get_param_list()

    @staticmethod
    def get_state_indices(N=2):
        return get_state_indices(N)

    @staticmethod
    def pack_parameters(params):
        return OERPhysics.pack_parameters(params)

    @staticmethod
    def initialize_system(params):
        return OERPhysics.initialize_system(params)

    @staticmethod
    def solve_ode_system(params):
        return OERPhysics.solve_ode_system(params)

    @staticmethod
    def oer_model(t, y, params):
        return OERPhysics.oer_model(t, y, params)

    @staticmethod
    def calculate_steady_state(params):
        return OERPhysics.calculate_steady_state(params)

    # Signal
    @staticmethod
    def initialize_filters(params):
        return OERSignal.initialize_filters(params)

    @staticmethod
    def process_data(t, y, i_total, params, exp_data):
        return OERSignal.process_data(t, y, i_total, params, exp_data)

    @staticmethod
    def extract_dc_fft(signal, df, params):
        return OERSignal.extract_dc_fft(signal, df, params)

    @staticmethod
    def extract_harmonics(signal, df, params):
        return OERSignal.extract_harmonics(signal, df, params)

    @staticmethod
    def align_data(tdc, I_sim, tdc_exp):
        return OERSignal.align_data(tdc, I_sim, tdc_exp)

    # IO
    @staticmethod
    def load_experimental_data(params):
        return OERIO.load_experimental_data(params)

    @staticmethod
    def read_numeric_file(file_path):
        return OERIO.read_numeric_file(file_path)

    @staticmethod
    def load_lsv_data(params, file_path=None):
        return OERIO.load_lsv_data(params, file_path)

    @staticmethod
    def configure_params_for_lsv(params, exp_data):
        return OERIO.configure_params_for_lsv(params, exp_data)

    @staticmethod
    def load_data_for_objective(params, file_path=None, default_mode='ftacv'):
        return OERIO.load_data_for_objective(params, file_path, default_mode)

    @staticmethod
    def create_unique_folder(save_root, data_path, suffix=None):
        return OERIO.create_unique_folder(save_root, data_path, suffix)

    # Objective
    @staticmethod
    def calculate_objective(I_sim, I_exp, harmonic_weights):
        return OERObjective.calculate_objective(I_sim, I_exp, harmonic_weights)

    @staticmethod
    def calculate_objective_from_simulation(t, y, E_actual, i_total, params, exp_data):
        return OERObjective.calculate_objective_from_simulation(
            t, y, E_actual, i_total, params, exp_data)

    @staticmethod
    def decode_params(x_vals, params, param_names):
        return OERObjective.decode_params(x_vals, params, param_names)

    @staticmethod
    def get_optim_config(params):
        return OERObjective.get_optim_config(params)

    # Thermodynamics
    @staticmethod
    def apply_aem_thermodynamics(params):
        return OERPhysics.apply_alkaline_aem_embedded(params)

    @staticmethod
    def apply_default_E0(params):
        return apply_default_E0(params)
