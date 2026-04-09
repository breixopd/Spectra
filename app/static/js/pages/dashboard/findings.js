// Dashboard Findings & Graph — Cytoscape, Leaflet, attack paths, finding detail
// Loaded before dashboard.js; depends on cytoscape, L (Leaflet), escapeHtml(), spectraApi
// Runtime deps (exposed by dashboard.js module): addTerminalLine, showSharedModal, closeSharedModal

var cy;
var graphPlaceholderVisible = true;
var map;
var markers = {};
var attackPathCy = null;
var currentFinding = null;

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
    const _mapResizeHandler = () => { if (map) map.invalidateSize(); };
    window.addEventListener('resize', _mapResizeHandler);
    // Observer for container visibility changes
    const observer = new ResizeObserver(() => { if (map) map.invalidateSize(); });
    observer.observe(mapContainer);

    window.addEventListener('pagehide', () => {
        window.removeEventListener('resize', _mapResizeHandler);
    });
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

// --- Finding graph nodes ---

function addFindingNode(finding) {
    if (!cy) return;

    // Simplified logic to add nodes based on finding
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

function handleGeo(data) {
    if (data.lat && data.lon) {
        addMapMarker(data.lat, data.lon, `${data.city}, ${data.country}`);
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

// --- Attack Paths Graph ---

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

// --- Finding Detail Modal ---

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
            <div class="flex items-center gap-2"><span class="text-xs text-slate-500 uppercase w-20">Found</span><span class="text-sm text-white">${finding.created_at ? new Date(finding.created_at).toLocaleString('en-US') : 'N/A'}</span></div>
            <div class="pt-2 border-t border-white/5"><span class="text-xs text-slate-500 uppercase block mb-1">Description</span><p class="text-sm text-slate-300">${escapeHtml(finding.description || 'No description available.')}</p></div>
        </div>`;
    document.getElementById('fd-tab-evidence').innerHTML = `<div class="text-sm text-slate-500">No evidence uploaded yet.</div>`;
    document.getElementById('fd-tab-remediation').innerHTML = `<div class="space-y-2 text-sm text-slate-300">${finding.remediation ? `<p>${escapeHtml(finding.remediation)}</p>` : '<p class="text-slate-500">No remediation steps available.</p>'}</div>`;
    document.getElementById('fd-tab-notes').innerHTML = `<textarea class="w-full bg-slate-900/50 border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:border-violet-500 outline-none resize-none" rows="4" placeholder="Add notes about this finding..."></textarea>`;

    switchFDTab('details');
    showSharedModal('finding-detail-modal');
}
function closeFindingDetail() { closeSharedModal('finding-detail-modal'); }

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
