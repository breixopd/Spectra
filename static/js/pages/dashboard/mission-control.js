let currentMissionId = null;

function launchFromForm() {
    const targetEl = document.getElementById('mission-target');
    const directiveEl = document.getElementById('mission-directive');
    const target = (targetEl?.value || '').trim();
    const directive = (directiveEl?.value || '').trim() || 'Perform a comprehensive security assessment';

    if (!target) {
        addTerminalLine('[ERROR] Enter a target IP or domain', 'error');
        targetEl?.focus();
        return;
    }

    const playbookId = document.getElementById('adversary-playbook')?.value || null;
    addTerminalLine(`[USER] ${target} ${directive}${playbookId ? ' [' + playbookId + ']' : ''}`, 'command');
    startMission(target, directive, playbookId);
}

// Enter key on either field launches
document.getElementById('mission-target')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') launchFromForm();
});
document.getElementById('mission-directive')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') launchFromForm();
});

function toggleRequirements() {
    const panel = document.getElementById('requirements-panel');
    if (panel) panel.classList.toggle('hidden');
}

// Load adversary playbooks into dropdown
(async function loadAdversaryPlaybooks() {
    const select = document.getElementById('adversary-playbook');
    if (!select) return;
    try {
        const { data: playbooks, error } = await spectraApi.get('/api/v1/missions/adversary-playbooks');
        if (error || !playbooks) return;
        for (const pb of playbooks) {
            const opt = document.createElement('option');
            opt.value = pb.id;
            const badge = pb.difficulty === 'hard' ? '\u26a0\ufe0f' : '\u2699\ufe0f';
            opt.textContent = `${badge} ${pb.name} (${pb.step_count} steps)`;
            opt.title = `${pb.threat_actor} \u2014 ${pb.description}`;
            select.appendChild(opt);
        }
    } catch { /* playbooks unavailable */ }
})();

// Load VPN configs into dropdown
(async function loadVPNConfigs() {
    const select = document.getElementById('vpn-config');
    if (!select) return;
    try {
        const { data: configs, error } = await spectraApi.get('/api/v1/vpn/configs');
        if (error || !configs) return;
        for (const cfg of configs) {
            const opt = document.createElement('option');
            opt.value = cfg.name;
            opt.textContent = `\uD83D\uDD12 ${cfg.name} (${cfg.type})`;
            select.appendChild(opt);
        }
    } catch { /* VPN configs unavailable */ }
})();

function startMission(target, directive, playbookId) {
    addTerminalLine(`Starting assessment against ${target}...`, 'info');
    
    const launchBtn = document.getElementById('launch-btn');
    if (launchBtn) { launchBtn.disabled = true; launchBtn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin"></i> Launching…'; }

    const reqEl = document.getElementById('mission-requirements');
    const requirements = reqEl && reqEl.value.trim() ? reqEl.value.trim() : null;
    if (requirements) addTerminalLine(`[SCOPE] Requirements attached (${requirements.length} chars)`, 'info');
    const authorizationConfirmed = Boolean(document.getElementById('mission-authorization-confirmed')?.checked);
    if (!authorizationConfirmed) {
        addTerminalLine('[ERROR] Confirm target ownership or written authorization before starting a mission.', 'error');
        if (launchBtn) {
            launchBtn.disabled = false;
            launchBtn.innerHTML = '<i data-lucide="rocket" class="w-4 h-4 inline-block"></i> Launch';
            if (window.lucide) window.lucide.createIcons();
        }
        return;
    }

    const payload = {
        target: target,
        directive: directive,
        requirements: requirements,
        authorization_confirmed: authorizationConfirmed
    };
    if (playbookId) payload.playbook_id = playbookId;
    const vpnConfig = document.getElementById('vpn-config')?.value || null;
    if (vpnConfig) payload.vpn_config = vpnConfig;

    // Remove empty state from activity log
    const emptyEl = document.getElementById('activity-empty');
    if (emptyEl) emptyEl.remove();

    spectraApi.post('/api/v1/missions', payload)
    .then(({ data, error }) => {
        if (error) {
            addTerminalLine(`[ERROR] Failed to start: ${error}`, 'error');
            return;
        }
        if (data && data.id) {
            currentMissionId = data.id;
            addTerminalLine(`[SUCCESS] Mission started: ${data.id}`, 'success');
            initGraphWithTarget(target);
        }
    })
    .finally(() => {
        if (launchBtn) { launchBtn.disabled = false; launchBtn.innerHTML = '<i data-lucide="rocket" class="w-4 h-4 inline-block"></i> Launch'; }
        if (typeof lucide !== 'undefined') lucide.createIcons();
    });
}

// Expose startMission for tasks.js launchPlaybook()
window.startMission = startMission;

// --- Scan Presets ---
async function launchPreset(presetId) {
    const target = document.getElementById('mission-target')?.value?.trim();
    if (!target) {
        addTerminalLine('[ERROR] Enter a target IP or domain first', 'error');
        document.getElementById('mission-target')?.focus();
        return;
    }

    try {
        const { data: presets, error: presetsError } = await spectraApi.get('/api/v1/missions/presets');
        if (presetsError || !presets) throw new Error(presetsError || 'Failed to load presets');
        const preset = presets[presetId];
        
        if (!preset) {
            addTerminalLine(`[ERROR] Unknown preset: ${presetId}`, 'error');
            return;
        }
        
        addTerminalLine(`[SYSTEM] Launching preset: ${preset.name} (~${preset.estimated_minutes} min)`, 'info');
        startMission(target, preset.directive);
    } catch (err) {
        addTerminalLine(`[ERROR] Failed to load preset: ${err}`, 'error');
    }
}

function pauseMission() {
    if (!currentMissionId) {
        addTerminalLine('[ERROR] No active mission to pause', 'error');
        return;
    }

    // Toggle state
    spectraApi.post(`/api/v1/missions/${currentMissionId}/pause`)
        .then(({ error }) => addTerminalLine(error ? `[ERROR] ${error}` : '[SYSTEM] Mission paused', error ? 'error' : 'warning'));
}

function resumeMission() {
    if (!currentMissionId) {
        addTerminalLine('[ERROR] No active mission to resume', 'error');
        return;
    }

    spectraApi.post(`/api/v1/missions/${currentMissionId}/resume`)
        .then(({ error }) => addTerminalLine(error ? `[ERROR] ${error}` : '[SYSTEM] Mission resumed', error ? 'error' : 'success'));
}

function stopMission() {
    if (!currentMissionId) {
        addTerminalLine('[ERROR] No active mission to stop', 'error');
        return;
    }

    _spectraConfirm('Are you sure you want to stop this mission? This action cannot be undone.', function() {
        spectraApi.post(`/api/v1/missions/${currentMissionId}/stop`)
            .then(({ error }) => addTerminalLine(error ? `[ERROR] ${error}` : '[SYSTEM] Aborting mission...', error ? 'error' : 'warning'));
    }, { title: 'Stop Mission', confirmLabel: 'Stop Mission' });
}

async function switchModel(modelId) {
    if (!modelId) {
        addTerminalLine('[ERROR] No AI model selected', 'error');
        return;
    }

    const currentModelEl = document.getElementById('current-model');
    const previousModelId = currentModelEl ? currentModelEl.textContent : '';
    if (currentModelEl) {
        currentModelEl.textContent = modelId;
    }
    addTerminalLine(`[SYSTEM] Switching AI model to ${modelId}...`, 'info');
    
    try {
        const { error } = await spectraApi.put('/api/v1/user/settings', {
            llm_model: modelId,
        });
        
        if (!error) {
            addTerminalLine(`[SUCCESS] Model switched to ${modelId}`, 'success');
            if (typeof _spectraToast === 'function') {
                _spectraToast(`Model switched to ${modelId}`, 'success');
            }
        } else {
            if (currentModelEl) {
                currentModelEl.textContent = previousModelId;
            }
            addTerminalLine(`[ERROR] Failed to switch model: ${error}`, 'error');
            if (typeof _spectraToast === 'function') {
                _spectraToast(`Failed to switch model: ${error}`, 'error');
            }
        }
    } catch (error) {
        if (currentModelEl) {
            currentModelEl.textContent = previousModelId;
        }
        addTerminalLine(`[ERROR] Connection failed: ${error}`, 'error');
        if (typeof _spectraToast === 'function') {
            _spectraToast(`Connection failed while switching model: ${error}`, 'error');
        }
    }
}

// Override handleFinding to track findings for click access
const origHandleFinding = handleFinding;
window.handleFinding = function(data) {
    origHandleFinding(data);
    // Store finding data for click access
    if (!window._dashboardFindings) window._dashboardFindings = [];
    window._dashboardFindings.push(data);
};

// --- Presets dropdown toggle (keyboard accessible) ---
function togglePresetsDropdown() {
    const trigger = document.getElementById('presets-trigger');
    const menu = document.getElementById('presets-menu');
    if (!trigger || !menu) return;
    const expanded = trigger.getAttribute('aria-expanded') === 'true';
    trigger.setAttribute('aria-expanded', String(!expanded));
    if (expanded) {
        menu.classList.add('opacity-0', 'invisible');
        menu.classList.remove('opacity-100', 'visible');
    } else {
        menu.classList.remove('opacity-0', 'invisible');
        menu.classList.add('opacity-100', 'visible');
    }
}

// Add info icon handler to adversary-playbook dropdown
(function setupPlaybookInfo() {
    const sel = document.getElementById('adversary-playbook');
    if (!sel) return;
    sel.addEventListener('dblclick', async () => {
        const val = sel.value;
        if (!val) return;
        try {
            const { data: playbooks, error } = await spectraApi.get('/api/v1/missions/adversary-playbooks');
            if (error) return;
            const pb = playbooks.find(p => p.id === val);
            if (pb) showPlaybookDetail(pb);
        } catch {}
    });
})();
