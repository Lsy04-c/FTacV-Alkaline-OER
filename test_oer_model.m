%% test_oer_model.m — 碱性 OER AEM 模型测试脚本
%   验证预氧化步骤对模型行为的影响
clear; close all;

%% 1. 初始化参数
fprintf('===== 初始化 OER AEM 模型参数 =====\n');
params = initialize_oer_parameters();

%% 2. 运行模拟
fprintf('\n===== 运行 ODE 模拟 =====\n');
tic;
[t, y, E_actual, i_total] = OER_Physics.solve_ode_system(params);
toc;

%% 3. 可视化
figure('Position', [100 100 1400 900]);

% —— 覆盖度演化 ——
subplot(2,3,1);
plot(E_actual, y(:,1), 'LineWidth', 1.5); hold on;
plot(E_actual, y(:,2), 'LineWidth', 1.5);
plot(E_actual, y(:,3), 'LineWidth', 1.5);
plot(E_actual, y(:,4), 'LineWidth', 1.5);
plot(E_actual, y(:,5), 'LineWidth', 1.5);
xlabel('E (V vs RHE)'); ylabel('Coverage');
legend('\theta_* (inactive)', '\theta_{*ox} (active)', ...
    '\theta_{*ox-OH}', '\theta_{*ox-O}', '\theta_{*ox-OOH}', ...
    'Location', 'best');
title('Surface Coverage Evolution');
grid on;

% —— 预氧化 vs 催化分离 ——
subplot(2,3,2);
idx = OER_Physics.get_state_indices(2);
theta_total_ox = y(:,idx.theta_ox) + y(:,idx.theta_OH) + ...
    y(:,idx.theta_O) + y(:,idx.theta_OOH);
plot(E_actual, y(:,1), 'b', 'LineWidth', 1.5); hold on;
plot(E_actual, theta_total_ox, 'r', 'LineWidth', 1.5);
xlabel('E (V vs RHE)'); ylabel('Coverage');
legend('\theta_* (reduced)', '\theta_{total-ox} (all oxidized species)', ...
    'Location', 'best');
title('Pre-oxidation: Reduced vs Oxidized Co Sites');
grid on;

% —— CV 曲线 ——
subplot(2,3,3);
plot(E_actual, i_total*1e3, 'LineWidth', 1);
xlabel('E (V vs RHE)'); ylabel('i (mA)');
title('Total Current vs Potential');
grid on;

% —— 谐波（FFT） ——
subplot(2,3,4);
df = 1/mean(diff(t));
L = length(i_total);
Y = fft(i_total);
f_axis = df * (0:(L-1))' / L;
semilogy(f_axis(1:floor(L/2)), abs(Y(1:floor(L/2))), 'LineWidth', 1);
xlabel('Frequency (Hz)'); ylabel('|FFT|');
title('Current FFT Spectrum');
xlim([0 15*params.f]);
grid on;

% —— DC 分量 ——
subplot(2,3,5);
I_dc = abs(lowpass(i_total, params.band(1)/2, df, ...
    'ImpulseResponse', 'iir', 'Steepness', 0.8));
plot(E_actual, i_total*1e3, 'Color', [0.7 0.7 0.7]); hold on;
plot(E_actual, I_dc*1e3, 'r', 'LineWidth', 1.5);
xlabel('E (V vs RHE)'); ylabel('i (mA)');
legend('Total', 'DC', 'Location', 'best');
title('DC Component Extraction');
grid on;

% —— 参数摘要 ——
subplot(2,3,6);
axis off;
text(0, 0.9, sprintf('Model Parameters:'), 'FontWeight', 'bold', 'FontSize', 11);
text(0, 0.78, sprintf('E0_{pre} = %.2f V  (Co^{3+/4+} pre-oxidation)', params.E0_pre));
text(0, 0.66, sprintf('E0_1 = %.2f V  (*ox -> *ox-OH)', params.E01));
text(0, 0.54, sprintf('E0_2 = %.2f V  (*ox-OH -> *ox-O)', params.E02));
text(0, 0.42, sprintf('E0_3 = %.2f V  (*ox-O -> *ox-OOH)', params.E03));
text(0, 0.30, sprintf('E0_4 = %.2f V  (*ox-OOH -> *ox)', params.E04));
text(0, 0.18, sprintf('G_OH = %.2f eV, G_O = %.2f eV', params.G_OH, params.G_O));
text(0, 0.06, sprintf('scaling = %.2f eV, \\Sigma\\DeltaG = %.2f eV', ...
    params.scaling_OOH_OH, sum([params.E01, params.E02, params.E03, params.E04])));
title('Parameter Summary');

sgtitle('Alkaline OER AEM Model with Pre-oxidation (Co_3O_4 / CoO_x(OH)_y)');

%% 4. 检查
fprintf('\n===== 模型检查 =====\n');
fprintf('覆盖度总和: %.6f (应为 1)\n', mean(sum(y(:,1:5), 2)));
fprintf('预氧化占比: %.2f%% (扫描结束)\n', ...
    (y(end,2)+y(end,3)+y(end,4)+y(end,5))*100);
fprintf('计算理论过电位: %.3f V\n', ...
    max([params.E01, params.E02, params.E03, params.E04]) - 1.23);
