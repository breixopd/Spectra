// Dashboard Logic for Spectra — initialization and coordination
// Sub-modules loaded via <script> tags: charts.js, findings.js, tasks.js

function showSharedModal(id) {
    if (typeof window.showModal === 'function') {
        window.showModal(id);
        return;
    }

    document.getElementById(id)?.classList.remove('hidden');
}

function closeSharedModal(id) {
    if (typeof window.closeModal === 'function') {
        window.closeModal(id);
        return;
    }

    document.getElementById(id)?.classList.add('hidden');
}

// --- Terminal Handling ---
const terminalOutput = document.getElementById('terminal-output');

function addTerminalLine(text, type = 'info') {
    const line = document.createElement('p');
    const colorClass = {
        'info': 'text-slate-500',
        'success': 'text-emerald-400',
        'warning': 'text-amber-400',
        'error': 'text-rose-400',
        'command': 'text-white'
    }[type] || 'text-slate-300';
    
    line.className = colorClass;
    line.textContent = text;
    terminalOutput.insertBefore(line, terminalOutput.lastElementChild);
    terminalOutput.scrollTop = terminalOutput.scrollHeight;
}

// Expose shared helpers for sub-module functions (called at runtime after module init)
window.showSharedModal = showSharedModal;
window.closeSharedModal = closeSharedModal;
window.addTerminalLine = addTerminalLine;

// --- WebSocket Event Handlers ---
function handleDashboardSocketMessage(data) {
    try {
        const msg = JSON.parse(data);
        
        if (msg.type === 'log') {
            addTerminalLine(msg.data, 'info');
        } else if (msg.type === 'finding') {
            handleFinding(msg.data);
        } else if (msg.type === 'task_update') {
            updateTaskList(msg.data);
        } else if (msg.type === 'geo') {
            handleGeo(msg.data);
        } else if (msg.type === 'attack_surface') {
            handleAttackSurface(msg.data);
        } else if (msg.type === 'exploit_success') {
            handleExploitSuccess(msg.data);
        } else if (msg.type === 'agent_state') {
            handleAgentState(msg.data);
        } else if (msg.type === 'consensus_vote_start') {
            addTerminalLine(`[CONSENSUS] Voting on ${msg.data.risk} risk action: ${msg.data.action}`, 'warning');
        } else if (msg.type === 'consensus_vote_result') {
            const status = msg.data.status === 'approved' ? 'Approved' : 'Rejected';
            addTerminalLine(`[CONSENSUS] ${status} (Confidence: ${msg.data.average_confidence.toFixed(2)})`, msg.data.status === 'approved' ? 'success' : 'error');
        }
    } catch (e) {
        // Fallback for plain text logs
        addTerminalLine(data, 'info');
    }
}

function handleDashboardSocketMessageEvent(event) {
    handleDashboardSocketMessage(event.detail);
}

document.addEventListener('spectra:ws-message', handleDashboardSocketMessageEvent);

function handleExploitSuccess(data) {
    addTerminalLine(`Exploit confirmed: ${data.vector}`, 'success');
    
    // Refresh shell list
    updateShellList();
}

function handleAgentState(data) {
    // Update status text based on agent state
    const statusText = document.getElementById('status-text');
    if (statusText && data.status === 'running') {
        statusText.textContent = `${data.agent_id.replace(/_/g, ' ')} running...`;
    }
}

// --- Shell Management ---
function updateShellList() {
    const container = document.getElementById('shell-list');
    if (!container) return;

    spectraApi.get('/api/v1/shell/sessions')
        .then(({ data: sessions, error }) => {
            if (error || !sessions) { sessions = []; }
            container.innerHTML = '';
            if (sessions.length === 0) {
                container.innerHTML = '<div class="text-center text-slate-600 text-xs py-4">No active sessions</div>';
                return;
            }

            sessions.forEach(session => {
                const el = document.createElement('div');
                el.className = 'bg-slate-800/50 border border-white/5 rounded p-2 flex items-center justify-between group hover:border-emerald-500/30 transition-colors';
                el.innerHTML = `
                    <div class="flex items-center space-x-2 overflow-hidden">
                        <div class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></div>
                        <div class="flex flex-col">
                            <span class="text-xs text-slate-300 font-mono truncate" title="${escapeHtml(session.id)}">${escapeHtml(session.target)}</span>
                            <span class="text-xs text-slate-500">ID: ${escapeHtml(session.id.substring(0, 8))}...</span>
                        </div>
                    </div>
                    <button data-shell-id="${escapeHtml(session.id)}" class="px-2 py-1 bg-emerald-500/10 text-emerald-400 text-xs rounded hover:bg-emerald-500/20 transition-colors border border-emerald-500/20">
                        CONNECT
                    </button>
                `;
                container.appendChild(el);
            });
        })
        .catch(() => {
            if (container) container.innerHTML = '<div class="text-center text-slate-600 text-xs py-4">No active sessions</div>';
        });

}

function connectShell(sessionId) {
    window.open(`/shell/${sessionId}`, '_blank', 'width=800,height=600');
}

// Delegated click handler for shell connect buttons
document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-shell-id]');
    if (btn) connectShell(btn.dataset.shellId);
});

// Poll for shell updates every 5 seconds — only when a mission is active
const shellListPollingInterval = window.setInterval(() => {
    if (currentMissionId) {
        updateShellList();
    }
}, 5000);

function cleanupDashboardPageState() {
    window.clearInterval(shellListPollingInterval);
    document.removeEventListener('spectra:ws-message', handleDashboardSocketMessageEvent);
}

window.addEventListener('pagehide', cleanupDashboardPageState, { once: true });
window.addEventListener('beforeunload', cleanupDashboardPageState, { once: true });


// --- Mission Control ---
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

    const payload = { target: target, directive: directive, requirements: requirements };
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

// Event delegation for task tree clicks (replaces inline onclick for XSS safety)
// Registered once at page load — not inside renderTaskTree() — to avoid duplicate handlers.
document.getElementById('task-tree-content')?.addEventListener('click', function(e) {
    const el = e.target.closest('[data-task-id]');
    if (el && window._taskTreeData) {
        const task = window._taskTreeData[el.dataset.taskId];
        if (task) openFindingDetail(task);
    }
});

// Listen for task/path updates via WebSocket
document.addEventListener('spectra:ws-message', (event) => {
    try {
        const msg = JSON.parse(event.detail);
        if (msg.type === 'task_tree') renderTaskTree(msg.data);
        if (msg.type === 'attack_paths') renderAttackPaths(msg.data);
        if (msg.type === 'task_update' && msg.data?.tasks) renderTaskTree(msg.data.tasks);
    } catch {}
});

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

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    initMap();
    updateShellList(); // Initial fetch
    addTerminalLine('Dashboard ready.', 'success');

    // Check for active mission and initialize graph with its data
    spectraApi.get('/api/v1/missions?status=running&page=1&per_page=1')
        .then(({ data }) => {
            const missions = data?.items || [];
            const mission = Array.isArray(missions) && missions.length > 0 ? missions[0] : null;
            if (mission && mission.id) {
                currentMissionId = mission.id;
                initGraph();
                initGraphWithTarget(mission.target || 'Target');
                addTerminalLine(`[SYSTEM] Resumed active mission: ${mission.id}`, 'info');

                // Load existing findings for this mission
                spectraApi.get(`/api/v1/missions/${mission.id}/findings`)
                    .then(({ data: findings }) => {
                        findings = findings || [];
                        if (Array.isArray(findings)) {
                            findings.forEach(f => {
                                // Update counts
                                const sev = (f.severity || 'info').toLowerCase();
                                const el = document.getElementById(`count-${sev}`);
                                if (el) el.textContent = parseInt(el.textContent) + 1;
                                // Add to graph
                                if (cy) addFindingNode(f);
                            });
                        }
                    })
                    .catch(() => {});
            } else {
                // No active mission — show placeholder, don't init graph yet
                showGraphPlaceholder();
            }
        })
        .catch(() => {
            showGraphPlaceholder();
        });

    // Load metrics
    loadMetrics();

    // Close presets dropdown on outside click
    document.addEventListener('click', (e) => {
        const wrapper = document.getElementById('presets-dropdown-wrapper');
        const trigger = document.getElementById('presets-trigger');
        const menu = document.getElementById('presets-menu');
        if (wrapper && trigger && menu && !wrapper.contains(e.target)) {
            trigger.setAttribute('aria-expanded', 'false');
            menu.classList.add('opacity-0', 'invisible');
            menu.classList.remove('opacity-100', 'visible');
        }
    });
});

// --- Expose functions used by HTML onclick/onchange handlers ---
window.toggleRequirements = toggleRequirements;
window.togglePresetsDropdown = togglePresetsDropdown;
window.launchFromForm = launchFromForm;
window.launchPreset = launchPreset;
window.pauseMission = pauseMission;
window.resumeMission = resumeMission;
window.stopMission = stopMission;
window.connectShell = connectShell;
window.switchModel = switchModel;
window.loadMetrics = loadMetrics;
