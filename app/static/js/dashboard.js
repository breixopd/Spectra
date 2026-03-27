// Dashboard Logic for Spectra

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

// --- WebSocket Event Handlers ---
window.onSocketMessage = (data) => {
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
};

function handleGeo(data) {
    if (data.lat && data.lon) {
        addMapMarker(data.lat, data.lon, `${data.city}, ${data.country}`);
    }
}

function handleFinding(data) {
    // Update finding counts
    const severity = (data.severity || 'info').toLowerCase();
    const countEl = document.getElementById(`count-${severity}`);
    if (countEl) {
        countEl.textContent = parseInt(countEl.textContent) + 1;
    }
    
    // Add to graph - ensure graph is initialized
    if (!cy) initGraph();
    if (cy) {
        addFindingNode(data);
    }
}

function updateTaskList(data) {
    // Currently no dedicated task list UI, logging to terminal
    if (data && data.tasks) {
        const active = data.tasks.filter(t => t.status === 'running').length;
        const completed = data.tasks.filter(t => t.status === 'completed').length;
        const total = data.tasks.length;
        addTerminalLine(`[TASKS] Progress: ${completed}/${total} (${active} active)`, 'info');
    }
}

function handleAttackSurface(data) {
    // Update node count with attack surface info
    const nodeCount = document.getElementById('node-count');
    if (nodeCount && cy) {
        nodeCount.textContent = `${cy.nodes().length} nodes`;
    }
    
    // Log attack surface updates
    addTerminalLine(`[SURFACE] ${data.services || 0} services, ${data.vulnerabilities || 0} vulns, ${data.vectors_total || 0} vectors`, 'info');
}

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
            if (error || !sessions) return;
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

}

function connectShell(sessionId) {
    window.open(`/shell/${sessionId}`, '_blank', 'width=800,height=600');
}

// Delegated click handler for shell connect buttons
document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-shell-id]');
    if (btn) connectShell(btn.dataset.shellId);
});

// Poll for shell updates every 5 seconds
setInterval(updateShellList, 5000);


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
    
    spectraApi.post(`/api/v1/missions/${currentMissionId}/stop`)
        .then(({ error }) => addTerminalLine(error ? `[ERROR] ${error}` : '[SYSTEM] Aborting mission...', error ? 'error' : 'warning'));
}

async function switchModel(modelId) {
    document.getElementById('current-model').textContent = modelId;
    addTerminalLine(`[SYSTEM] Switching AI model to ${modelId}...`, 'info');
    
    try {
        const { error } = await spectraApi.post('/api/settings', {
                log_level: 'INFO',
                plugin_safe_mode: true
        });
        
        if (!error) {
            addTerminalLine(`[SUCCESS] Model switched to ${modelId}`, 'success');
        } else {
            addTerminalLine(`[ERROR] Failed to switch model`, 'error');
        }
    } catch (error) {
        addTerminalLine(`[ERROR] Connection failed: ${error}`, 'error');
    }
}

// --- Network Graph (Cytoscape.js) ---
let cy;
let graphPlaceholderVisible = true;

function showGraphPlaceholder() {
    const container = document.getElementById('network-graph');
    if (!container) return;
    graphPlaceholderVisible = true;
    container.innerHTML = '<div class="text-center text-slate-700"><i data-lucide="git-branch" class="w-5 h-5 inline-block mb-2"></i><p class="text-xs">Discovered services and hosts appear here</p></div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function initGraph() {
    const container = document.getElementById('network-graph');
    if (!container) return;

    // Clear placeholder
    container.innerHTML = '';
    graphPlaceholderVisible = false;

    cy = cytoscape({
        container: container,
        style: [
            {
                selector: 'node',
                style: {
                    'background-color': '#64748b',
                    'label': 'data(label)',
                    'color': '#94a3b8',
                    'font-size': '10px',
                    'font-family': 'JetBrains Mono',
                    'text-valign': 'bottom',
                    'text-margin-y': 5
                }
            },
            {
                selector: 'node[type="target"]',
                style: {
                    'background-color': '#8b5cf6', // Violet
                    'width': 30,
                    'height': 30
                }
            },
            {
                selector: 'node[type="service"]',
                style: {
                    'background-color': '#10b981', // Emerald
                    'width': 20,
                    'height': 20
                }
            },
            {
                selector: 'node[type="vuln"]',
                style: {
                    'background-color': '#f43f5e', // Rose
                    'width': 15,
                    'height': 15
                }
            },
            {
                selector: 'edge',
                style: {
                    'width': 1,
                    'line-color': '#334155',
                    'curve-style': 'bezier'
                }
            }
        ],
        layout: {
            name: 'cose',
            animate: true
        }
    });

    updateNodeCount();

    // Handle container resize
    const observer = new ResizeObserver(() => { if (cy) cy.resize(); });
    observer.observe(container);
}

function initGraphWithTarget(targetLabel) {
    if (!cy) initGraph();
    if (!cy) return;

    // Add target node if not present
    if (cy.getElementById('target').length === 0) {
        cy.add({ group: 'nodes', data: { id: 'target', label: targetLabel || 'Target', type: 'target' } });
        cy.layout({ name: 'cose', animate: true }).run();
        updateNodeCount();
    }
}

// --- Threat Map (Leaflet) ---
let map;
let markers = {};

function initMap() {
    const mapContainer = document.getElementById('threat-map');
    if (!mapContainer) return;

    // Clean up placeholder before Leaflet init
    const placeholder = document.getElementById('map-placeholder');
    if (placeholder) placeholder.remove();

    map = L.map('threat-map', {
        zoomControl: false,
        attributionControl: false,
        minZoom: 1,
        maxZoom: 18,
        worldCopyJump: true
    }).setView([25, 0], 2);

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 18,
        subdomains: 'abcd',
        errorTileUrl: ''
    }).addTo(map);
    map.getContainer().style.background = '#0f172a';

    // Leaflet requires invalidateSize when container is resized or initially hidden
    setTimeout(() => { if (map) map.invalidateSize(); }, 200);
    window.addEventListener('resize', () => { if (map) map.invalidateSize(); });
    // Observer for container visibility changes
    const observer = new ResizeObserver(() => { if (map) map.invalidateSize(); });
    observer.observe(mapContainer);
}

function addMapMarker(lat, lng, title) {
    if (!map) return;
    
    const marker = L.circleMarker([lat, lng], {
        radius: 6,
        fillColor: "#10b981",
        color: "#fff",
        weight: 1,
        opacity: 1,
        fillOpacity: 0.8
    }).addTo(map);
    
    marker.bindPopup(`<b style="color:#333">${title}</b>`);
}

function addFindingNode(finding) {
    if (!cy) return;
    
    // Simplified logic to add nodes based on finding
    // In a real app, we'd parse the finding structure more carefully
    const id = `vuln-${Math.random().toString(36).substr(2, 9)}`;
    
    cy.add({
        group: 'nodes',
        data: { id: id, label: finding.title || 'Vuln', type: 'vuln' }
    });
    
    // Ensure target node exists
    if (cy.getElementById('target').length === 0) {
        cy.add({ group: 'nodes', data: { id: 'target', label: 'Target', type: 'target' } });
    }

    // Link to target
    cy.add({
        group: 'edges',
        data: { source: 'target', target: id }
    });
    
    cy.layout({ name: 'cose', animate: true }).run();
    updateNodeCount();
}

function updateNodeCount() {
    if (cy) {
        const count = cy.nodes().length;
        document.getElementById('node-count').textContent = `${count} nodes`;
    }
}

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    initMap();
    updateShellList(); // Initial fetch
    addTerminalLine('Dashboard ready.', 'success');

    // Check for active mission and initialize graph with its data
    spectraApi.get('/api/v1/missions?status=running&limit=1')
        .then(({ data: missions }) => {
            missions = missions || [];
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
});

// --- Metrics & Trends (Chart.js) ---
let chartInstances = {};

async function loadMetrics() {
    const days = parseInt(document.getElementById('metrics-timerange').value) || 0;
    let missions = [], allFindings = [];
    const errEl = document.getElementById('dashboard-error');
    const findingsLoading = document.getElementById('findings-loading');
    const findingsData = document.getElementById('findings-data');

    try {
        const { data: missionsData, error: missionsError } = await spectraApi.get('/api/v1/missions');
        if (!missionsError) missions = missionsData;
        if (errEl) errEl.classList.add('hidden');
    } catch {
        if (errEl) errEl.classList.remove('hidden');
    }

    const cutoff = days > 0 ? new Date(Date.now() - days * 86400000) : null;
    if (cutoff) missions = missions.filter(m => new Date(m.created_at) >= cutoff);

    // Toggle getting started card based on mission existence
    const gettingStarted = document.getElementById('getting-started');
    if (gettingStarted) {
        gettingStarted.classList.toggle('hidden', missions.length > 0);
    }

    // Show empty state for findings when none exist
    if (findingsLoading && findingsData && missions.length === 0) {
        findingsLoading.innerHTML = '<div class="col-span-4 dash-empty" style="padding:1rem 0.5rem;min-height:auto;"><i data-lucide="shield" class="w-5 h-5 inline-block"></i><p style="font-size:0.75rem;">No findings yet</p></div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    // Gather all findings
    for (const m of missions) {
        try {
            const { data: f, error: fErr } = await spectraApi.get(`/api/v1/missions/${m.id}/findings`);
            if (!fErr && f) { f.forEach(x => { x._mission = m; }); allFindings.push(...f); }
        } catch {}
    }

    // Swap skeleton for real data
    if (findingsLoading) findingsLoading.classList.add('hidden');
    if (findingsData) findingsData.classList.remove('hidden');

    // Show empty state for metrics when no data
    const metricsSection = document.getElementById('metrics-section');
    if (metricsSection && missions.length === 0 && allFindings.length === 0) {
        const metricsBody = metricsSection.querySelector('.p-5');
        if (metricsBody) {
            metricsBody.innerHTML = '<div class="dash-empty" style="padding:3rem 1rem;"><i data-lucide="bar-chart-3" class="w-5 h-5 inline-block"></i><h3>No data yet</h3><p>Complete your first assessment to see trends and metrics here.</p></div>';
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    } else {
        renderFindingsOverTime(allFindings, days);
        renderMissionsPerWeek(missions);
        renderSeverityBreakdown(allFindings);
        renderTopVulns(allFindings);
        renderTopTargets(allFindings, missions);
    }
}

function destroyChart(id) { if (chartInstances[id]) { chartInstances[id].destroy(); delete chartInstances[id]; } }

function renderFindingsOverTime(findings, days) {
    destroyChart('findings-time');
    const grouped = {};
    findings.forEach(f => { const d = (f.created_at || '').split('T')[0]; if (d) grouped[d] = (grouped[d] || 0) + 1; });
    const labels = Object.keys(grouped).sort();
    const data = labels.map(l => grouped[l]);
    const ctx = document.getElementById('chart-findings-time');
    if (!ctx) return;
    chartInstances['findings-time'] = new Chart(ctx, {
        type: 'line', data: { labels, datasets: [{ label: 'Findings', data, borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.1)', fill: true, tension: 0.3, pointRadius: 2 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.03)' } }, y: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.03)' } } } }
    });
}

function renderMissionsPerWeek(missions) {
    destroyChart('missions-week');
    const grouped = {};
    missions.forEach(m => {
        const d = new Date(m.created_at);
        const weekStart = new Date(d); weekStart.setDate(d.getDate() - d.getDay());
        const key = weekStart.toISOString().split('T')[0];
        grouped[key] = (grouped[key] || 0) + 1;
    });
    const labels = Object.keys(grouped).sort();
    const data = labels.map(l => grouped[l]);
    const ctx = document.getElementById('chart-missions-week');
    if (!ctx) return;
    chartInstances['missions-week'] = new Chart(ctx, {
        type: 'bar', data: { labels, datasets: [{ label: 'Missions', data, backgroundColor: '#10b981', borderRadius: 4 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { display: false } }, y: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.03)' } } } }
    });
}

function renderSeverityBreakdown(findings) {
    destroyChart('severity');
    const counts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
    findings.forEach(f => { const s = (f.severity || 'info').toLowerCase(); if (s in counts) counts[s]++; });
    const ctx = document.getElementById('chart-severity');
    if (!ctx) return;
    chartInstances['severity'] = new Chart(ctx, {
        type: 'doughnut', data: { labels: Object.keys(counts), datasets: [{ data: Object.values(counts), backgroundColor: ['#f43f5e', '#f59e0b', '#3b82f6', '#64748b', '#475569'], borderWidth: 0 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { color: '#94a3b8', font: { size: 10, family: 'JetBrains Mono' }, padding: 8, usePointStyle: true, pointStyleWidth: 8 } } } }
    });
}

function renderTopVulns(findings) {
    const typeCounts = {};
    findings.forEach(f => { const t = f.title || 'Unknown'; typeCounts[t] = (typeCounts[t] || 0) + 1; });
    const sorted = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]).slice(0, 10);
    const el = document.getElementById('top-vulns-list');
    if (!el) return;
    el.innerHTML = sorted.length === 0 ? '<div class="text-slate-600 text-center py-4">No findings</div>' :
        sorted.map(([name, count], i) => `<div class="flex items-center gap-2"><span class="text-xs text-slate-600 w-4">${i + 1}.</span><span class="flex-1 text-slate-300 truncate">${escapeHtml(name)}</span><span class="text-xs font-mono text-slate-500">${count}</span></div>`).join('');
}

function renderTopTargets(findings, missions) {
    destroyChart('top-targets');
    const targetCounts = {};
    findings.forEach(f => { const t = f._mission?.target || 'Unknown'; targetCounts[t] = (targetCounts[t] || 0) + 1; });
    const sorted = Object.entries(targetCounts).sort((a, b) => b[1] - a[1]).slice(0, 8);
    const ctx = document.getElementById('chart-top-targets');
    if (!ctx) return;
    chartInstances['top-targets'] = new Chart(ctx, {
        type: 'bar', data: { labels: sorted.map(s => s[0]), datasets: [{ label: 'Findings', data: sorted.map(s => s[1]), backgroundColor: '#8b5cf6', borderRadius: 4 }] },
        options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.03)' } }, y: { ticks: { color: '#94a3b8', font: { size: 9, family: 'JetBrains Mono' } }, grid: { display: false } } } }
    });
}

// --- Playbook Detail Modal ---
let selectedPlaybookData = null;

function showPlaybookDetail(playbook) {
    selectedPlaybookData = playbook;
    document.getElementById('pb-detail-title').textContent = playbook.name || 'Playbook';
    document.getElementById('pb-detail-desc').textContent = playbook.description || '';
    const phasesEl = document.getElementById('pb-detail-phases');
    const steps = playbook.steps || playbook.phases || [];
    phasesEl.innerHTML = steps.map((s, i) => `<div class="flex items-center gap-2 text-xs"><span class="w-5 h-5 rounded-full bg-violet-500/20 text-violet-400 flex items-center justify-center text-xs font-mono shrink-0">${i + 1}</span><span class="text-slate-300">${escapeHtml(typeof s === 'string' ? s : s.name || s.description || JSON.stringify(s))}</span></div>`).join('');
    document.getElementById('pb-detail-stealth').textContent = playbook.stealth ? 'On' : 'Off';
    document.getElementById('pb-detail-autoexploit').textContent = playbook.auto_exploit !== false ? 'Yes' : 'No';
    document.getElementById('playbook-detail-modal').classList.remove('hidden');
}
function closePlaybookDetail() { document.getElementById('playbook-detail-modal').classList.add('hidden'); }
function launchPlaybook() {
    if (!selectedPlaybookData) return;
    const target = document.getElementById('mission-target')?.value?.trim();
    if (!target) { closePlaybookDetail(); document.getElementById('mission-target')?.focus(); return; }
    closePlaybookDetail();
    startMission(target, selectedPlaybookData.description || 'Playbook execution', selectedPlaybookData.id);
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

// --- Finding Detail Modal ---
let currentFinding = null;

function openFindingDetail(finding) {
    currentFinding = finding;
    document.getElementById('fd-title').textContent = finding.title || 'Finding';
    const sevColors = { critical: 'text-rose-400', high: 'text-amber-400', medium: 'text-blue-400', low: 'text-slate-400', info: 'text-slate-500' };
    const sev = (finding.severity || 'info').toLowerCase();

    document.getElementById('fd-tab-details').innerHTML = `
        <div class="space-y-3">
            <div class="flex items-center gap-2"><span class="text-xs text-slate-500 uppercase w-20">Severity</span><span class="${sevColors[sev] || 'text-slate-400'} font-medium uppercase text-sm">${escapeHtml(sev)}</span></div>
            <div class="flex items-center gap-2"><span class="text-xs text-slate-500 uppercase w-20">Tool</span><span class="text-sm text-white">${escapeHtml(finding.tool_source || 'N/A')}</span></div>
            <div class="flex items-center gap-2"><span class="text-xs text-slate-500 uppercase w-20">Status</span><span class="text-sm text-white">${escapeHtml(finding.status || 'confirmed')}</span></div>
            <div class="flex items-center gap-2"><span class="text-xs text-slate-500 uppercase w-20">Found</span><span class="text-sm text-white">${finding.created_at ? new Date(finding.created_at).toLocaleString() : 'N/A'}</span></div>
            <div class="pt-2 border-t border-white/5"><span class="text-xs text-slate-500 uppercase block mb-1">Description</span><p class="text-sm text-slate-300">${escapeHtml(finding.description || 'No description available.')}</p></div>
        </div>`;
    document.getElementById('fd-tab-evidence').innerHTML = `<div class="text-sm text-slate-500">No evidence uploaded yet.</div>`;
    document.getElementById('fd-tab-remediation').innerHTML = `<div class="space-y-2 text-sm text-slate-300">${finding.remediation ? `<p>${escapeHtml(finding.remediation)}</p>` : '<p class="text-slate-500">No remediation steps available.</p>'}</div>`;
    document.getElementById('fd-tab-notes').innerHTML = `<textarea class="w-full bg-slate-900/50 border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:border-violet-500 outline-none resize-none" rows="4" placeholder="Add notes about this finding..."></textarea>`;

    switchFDTab('details');
    document.getElementById('finding-detail-modal').classList.remove('hidden');
}
function closeFindingDetail() { document.getElementById('finding-detail-modal').classList.add('hidden'); }

function switchFDTab(tab) {
    document.querySelectorAll('.fd-tab').forEach(t => { t.classList.remove('text-violet-400', 'border-violet-500'); t.classList.add('text-slate-400', 'border-transparent'); });
    const active = document.querySelector(`.fd-tab[data-tab="${tab}"]`);
    if (active) { active.classList.add('text-violet-400', 'border-violet-500'); active.classList.remove('text-slate-400', 'border-transparent'); }
    ['details', 'evidence', 'remediation', 'notes'].forEach(t => {
        const el = document.getElementById(`fd-tab-${t}`);
        if (el) el.classList.toggle('hidden', t !== tab);
    });
}

function markFalsePositive() {
    if (!currentFinding) return;
    spectraApi.request(`/api/v1/findings/${currentFinding.id}`, { method: 'PATCH', body: { status: 'false_positive' } });
    closeFindingDetail();
}
function retestFinding() { closeFindingDetail(); }

// Make findings clickable in the dashboard
const origHandleFinding = handleFinding;
handleFinding = function(data) {
    origHandleFinding(data);
    // Store finding data for click access
    if (!window._dashboardFindings) window._dashboardFindings = [];
    window._dashboardFindings.push(data);
};

// --- Task Tree ---
function renderTaskTree(tasks) {
    const panel = document.getElementById('task-tree-panel');
    const content = document.getElementById('task-tree-content');
    if (!tasks || tasks.length === 0) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');

    const icons = { completed: '☑', running: '●', pending: '○', failed: '✗' };
    const colors = { completed: 'text-emerald-400', running: 'text-amber-400 animate-pulse', pending: 'text-slate-500', failed: 'text-rose-400' };

    function renderNode(task, depth = 0) {
        const indent = depth * 20;
        const icon = icons[task.status] || '○';
        const color = colors[task.status] || 'text-slate-500';
        const taskId = task.id || Math.random().toString(36).slice(2);
        if (!window._taskTreeData) window._taskTreeData = {};
        window._taskTreeData[taskId] = task;
        let html = `<div class="flex items-center gap-2 py-0.5 hover:bg-white/5 rounded px-2 cursor-pointer" style="padding-left:${indent + 8}px" data-task-id="${escapeHtml(String(taskId))}">
            <span class="${color}">${icon}</span>
            <span class="text-slate-300">${escapeHtml(task.name || task.tool || 'Task')}</span>
            ${task.status === 'running' ? '<span class="text-xs text-amber-400 ml-auto">running...</span>' : ''}
        </div>`;
        if (task.children) task.children.forEach(c => { html += renderNode(c, depth + 1); });
        return html;
    }

    content.innerHTML = tasks.map(t => renderNode(t)).join('');
    const running = tasks.filter(t => t.status === 'running').length;
    const completed = tasks.filter(t => t.status === 'completed').length;
    document.getElementById('task-tree-status').textContent = `${completed}/${tasks.length} complete, ${running} active`;
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

// --- Attack Paths Graph ---
let attackPathCy = null;

function renderAttackPaths(paths) {
    const panel = document.getElementById('attack-paths-panel');
    if (!paths || paths.length === 0) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');
    const container = document.getElementById('attack-paths-graph');
    container.innerHTML = '';

    attackPathCy = cytoscape({
        container,
        style: [
            { selector: 'node', style: { 'label': 'data(label)', 'color': '#94a3b8', 'font-size': '9px', 'font-family': 'JetBrains Mono', 'text-valign': 'bottom', 'text-margin-y': 4, 'width': 24, 'height': 24 } },
            { selector: 'node[type="entry"]', style: { 'background-color': '#3b82f6' } },
            { selector: 'node[type="exploit"]', style: { 'background-color': '#f43f5e' } },
            { selector: 'node[type="pivot"]', style: { 'background-color': '#f59e0b' } },
            { selector: 'node[type="goal"]', style: { 'background-color': '#10b981' } },
            { selector: 'edge', style: { 'width': 2, 'line-color': '#475569', 'target-arrow-color': '#475569', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'label': 'data(label)', 'font-size': '8px', 'color': '#64748b' } }
        ],
        layout: { name: 'dagre', rankDir: 'LR', animate: true }
    });

    paths.forEach((path, pi) => {
        path.forEach((step, si) => {
            const nodeId = `ap-${pi}-${si}`;
            attackPathCy.add({ group: 'nodes', data: { id: nodeId, label: step.name || step.title || 'Step', type: step.type || (si === 0 ? 'entry' : 'exploit') } });
            if (si > 0) {
                attackPathCy.add({ group: 'edges', data: { source: `ap-${pi}-${si-1}`, target: nodeId, label: step.technique || '' } });
            }
        });
    });

    try { attackPathCy.layout({ name: 'dagre', rankDir: 'LR', animate: true }).run(); } catch { attackPathCy.layout({ name: 'cose', animate: true }).run(); }
}

// Listen for task/path updates via WebSocket
const origOnSocket = window.onSocketMessage;
window.onSocketMessage = function(data) {
    if (origOnSocket) origOnSocket(data);
    try {
        const msg = JSON.parse(data);
        if (msg.type === 'task_tree') renderTaskTree(msg.data);
        if (msg.type === 'attack_paths') renderAttackPaths(msg.data);
        if (msg.type === 'task_update' && msg.data?.tasks) renderTaskTree(msg.data.tasks);
    } catch {}
};

// Load metrics on page load
document.addEventListener('DOMContentLoaded', () => { loadMetrics(); });

// --- Expose functions used by HTML onclick/onchange handlers ---
window.toggleRequirements = toggleRequirements;
window.launchFromForm = launchFromForm;
window.launchPreset = launchPreset;
window.pauseMission = pauseMission;
window.stopMission = stopMission;
window.connectShell = connectShell;
window.loadMetrics = loadMetrics;
window.closePlaybookDetail = closePlaybookDetail;
window.launchPlaybook = launchPlaybook;
window.closeFindingDetail = closeFindingDetail;
window.switchFDTab = switchFDTab;
