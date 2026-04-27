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
