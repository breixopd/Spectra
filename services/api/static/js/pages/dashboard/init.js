// Render framework phase timeline for active missions
function renderPhaseTimeline(mission) {
    const container = document.getElementById('phase-timeline-container');
    const labelEl = document.getElementById('phase-timeline-label');
    const timelineEl = document.getElementById('phase-timeline');
    if (!container || !labelEl || !timelineEl) return;

    const tl = mission.framework_phase_timeline;
    if (!Array.isArray(tl) || !tl.length) {
        container.classList.add('hidden');
        return;
    }
    container.classList.remove('hidden');
    labelEl.textContent = mission.framework_label || mission.pentest_framework || '';
    timelineEl.innerHTML = '';
    for (const step of tl) {
        const span = document.createElement('span');
        let cls = 'px-2 py-0.5 rounded border border-white/10 text-slate-500 text-xs';
        if (step.done) cls = 'px-2 py-0.5 rounded border border-emerald-500/40 text-emerald-300 bg-emerald-500/10 text-xs';
        if (step.current) cls = 'px-2 py-0.5 rounded border border-amber-400/50 text-amber-200 bg-amber-500/10 text-xs';
        span.className = cls;
        span.textContent = step.label || step.id;
        span.title = String(step.id || '');
        timelineEl.appendChild(span);
    }
}

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
        if (msg.type === 'task_tree') {
            const tasks = Array.isArray(msg.data) ? msg.data : (msg.data && msg.data.tasks) || [];
            if (tasks.length) renderTaskTree(tasks);
        }
        if (msg.type === 'attack_paths') renderAttackPaths(msg.data);
        if (msg.type === 'task_update' && msg.data?.tasks) renderTaskTree(msg.data.tasks);
    } catch {}
});

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
                renderPhaseTimeline(mission);

                spectraApi.get(`/api/v1/missions/${mission.id}/task-tree`)
                    .then(({ data: treePayload }) => {
                        const tasks = treePayload && treePayload.tasks;
                        if (Array.isArray(tasks) && tasks.length) renderTaskTree(tasks);
                    })
                    .catch(() => {});

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

// --- Error handling ---
function showError(message) {
    const container = document.getElementById('error-container');
    const msgEl = document.getElementById('error-message');
    if (container && msgEl) {
        msgEl.textContent = message;
        container.classList.remove('hidden');
        container.setAttribute('aria-live', 'polite');
    }
}

function dismissError() {
    const container = document.getElementById('error-container');
    if (container) {
        container.classList.add('hidden');
    }
}

window.showError = showError;
window.dismissError = dismissError;

// Dismiss error on button click
document.addEventListener('click', (e) => {
    if (e.target.closest('[data-action="dismissError"]')) {
        dismissError();
    }
});
