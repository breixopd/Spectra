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

    fetch('/api/sessions')
        .then(res => res.json())
        .then(sessions => {
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
                            <span class="text-xs text-slate-300 font-mono truncate" title="${session.id}">${session.target}</span>
                            <span class="text-[10px] text-slate-500">ID: ${session.id.substring(0, 8)}...</span>
                        </div>
                    </div>
                    <button onclick="connectShell('${session.id}')" class="px-2 py-1 bg-emerald-500/10 text-emerald-400 text-[10px] rounded hover:bg-emerald-500/20 transition-colors border border-emerald-500/20">
                        CONNECT
                    </button>
                `;
                container.appendChild(el);
            });
        })
        .catch(err => console.error('Failed to fetch sessions:', err));
}

function connectShell(sessionId) {
    window.open(`/shell/${sessionId}`, '_blank', 'width=800,height=600');
}

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
        const res = await fetch('/api/missions/adversary-playbooks');
        if (!res.ok) return;
        const playbooks = await res.json();
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
        const res = await fetch('/api/vpn/configs');
        if (!res.ok) return;
        const configs = await res.json();
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
    
    const reqEl = document.getElementById('mission-requirements');
    const requirements = reqEl && reqEl.value.trim() ? reqEl.value.trim() : null;
    if (requirements) addTerminalLine(`[SCOPE] Requirements attached (${requirements.length} chars)`, 'info');

    const payload = { target: target, directive: directive, requirements: requirements };
    if (playbookId) payload.playbook_id = playbookId;
    const vpnConfig = document.getElementById('vpn-config')?.value || null;
    if (vpnConfig) payload.vpn_config = vpnConfig;

    fetch('/api/missions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if (data.id) {
            currentMissionId = data.id;
            addTerminalLine(`[SUCCESS] Mission started: ${data.id}`, 'success');
            initGraphWithTarget(target);
        } else {
            addTerminalLine(`[ERROR] Failed to start: ${JSON.stringify(data)}`, 'error');
        }
    })
    .catch(err => addTerminalLine(`[ERROR] Connection failed: ${err}`, 'error'));
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
        const res = await fetch('/api/missions/presets');
        const presets = await res.json();
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
    fetch(`/api/missions/${currentMissionId}/pause`, { method: 'POST' })
        .then(() => addTerminalLine('[SYSTEM] Mission paused', 'warning'))
        .catch(err => addTerminalLine(`[ERROR] ${err}`, 'error'));
}

function resumeMission() {
    if (!currentMissionId) {
        addTerminalLine('[ERROR] No active mission to resume', 'error');
        return;
    }

    fetch(`/api/missions/${currentMissionId}/resume`, { method: 'POST' })
        .then(() => addTerminalLine('[SYSTEM] Mission resumed', 'success'))
        .catch(err => addTerminalLine(`[ERROR] ${err}`, 'error'));
}

function stopMission() {
    if (!currentMissionId) {
        addTerminalLine('[ERROR] No active mission to stop', 'error');
        return;
    }
    
    fetch(`/api/missions/${currentMissionId}/stop`, { method: 'POST' })
        .then(() => addTerminalLine('[SYSTEM] Aborting mission...', 'warning'))
        .catch(err => addTerminalLine(`[ERROR] ${err}`, 'error'));
}

async function switchModel(modelId) {
    document.getElementById('current-model').textContent = modelId;
    addTerminalLine(`[SYSTEM] Switching AI model to ${modelId}...`, 'info');
    
    try {
        // Determine provider based on model ID (heuristic)
        let provider = 'ollama';
        if (modelId.startsWith('gpt')) {
            provider = 'openai';
        }
        
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                ai_provider: provider,
                llm_model: provider === 'api' ? modelId : undefined,
                ollama_model: provider === 'ollama' ? modelId : undefined,
                log_level: 'INFO', // Default
                plugin_safe_mode: true // Default
            }),
        });
        
        if (response.ok) {
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
    container.innerHTML = '<div class="text-center text-slate-700"><i class="fa-solid fa-diagram-project text-3xl mb-2"></i><p class="text-xs">Discovered services and hosts appear here</p></div>';
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
    fetch('/api/missions?status=running&limit=1')
        .then(res => res.ok ? res.json() : [])
        .then(missions => {
            const mission = Array.isArray(missions) && missions.length > 0 ? missions[0] : null;
            if (mission && mission.id) {
                currentMissionId = mission.id;
                initGraph();
                initGraphWithTarget(mission.target || 'Target');
                addTerminalLine(`[SYSTEM] Resumed active mission: ${mission.id}`, 'info');

                // Load existing findings for this mission
                fetch(`/api/missions/${mission.id}/findings`)
                    .then(res => res.ok ? res.json() : [])
                    .then(findings => {
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
