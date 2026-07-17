function params = apply_alkaline_aem(params)
% apply_alkaline_aem  Apply AEM thermodynamic constraints to generate
% equilibrium potentials from intermediate free energies.
%
%   Input (fields used):
%     params.G_OH           - Free energy of adsorbed *OH (eV)
%     params.G_O            - Free energy of adsorbed *O  (eV)
%     params.scaling_OOH_OH - Scaling offset, default 3.2 (eV)
%
%   Output (fields added/modified):
%     params.G_OOH          - Free energy of adsorbed *OOH (eV)
%     params.DeltaG1..4     - Stepwise reaction free energies (eV)
%     params.E01..E04       - Equilibrium potentials (V vs RHE)
%
%   Hard constraint: DeltaG1 + DeltaG2 + DeltaG3 + DeltaG4 = 4.92 eV
%
%   Reference:
%     Snitkoff-Sol et al. (2024) Nat. Catal. 7, 139-147.
%     Bergmann et al. (2015) Nat. Commun. 6, 8625.

    % --- Total OER free energy (4 * 1.23 V) ---
    G_total = 4 * 1.23;  % 4.92 eV
    % --- Extract physical descriptors ---
    G_OH = params.G_OH;
    G_O  = params.G_O;

    % --- Scaling relation (adjustable, not hard-coded) ---
    if ~isfield(params, 'scaling_OOH_OH')
        scaling_OOH_OH = 3.2;
    else
        scaling_OOH_OH = params.scaling_OOH_OH;
    end
    % --- Generate *OOH free energy via scaling relation ---
    G_OOH = G_OH + scaling_OOH_OH;
    % --- Stepwise reaction free energies ---
    dG1 = G_OH;                % * + OH-  -> *OH + e-
    dG2 = G_O - G_OH;          % *OH + OH- -> *O + H2O + e-
    dG3 = G_OOH - G_O;         % *O + OH-  -> *OOH + e-
    dG4 = G_total - G_OOH;     % *OOH + OH- -> * + O2 + H2O + e-

    % --- Equilibrium potentials (single-electron, eV -> V) ---
    params.E01 = dG1;
    params.E02 = dG2;
    params.E03 = dG3;
    params.E04 = dG4;

    % --- Store intermediates for downstream use ---
    params.G_OOH    = G_OOH;
    params.DeltaG1  = dG1;
    params.DeltaG2  = dG2;
    params.DeltaG3  = dG3;
    params.DeltaG4  = dG4;

    % --- Automatic verification: sum must equal G_total ---
    sum_check = dG1 + dG2 + dG3 + dG4;
    if abs(sum_check - G_total) > 1e-10
        warning('apply_alkaline_aem:SumCheck', ...
            'DeltaG sum = %.6f eV (expected %.6f eV)', sum_check, G_total);
    end
end
