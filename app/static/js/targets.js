// Targets Management Logic

function openAddTargetModal() {
    document.getElementById('add-target-modal').classList.remove('hidden');
}

function closeAddTargetModal() {
    document.getElementById('add-target-modal').classList.add('hidden');
}

async function handleAddTarget(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    const data = Object.fromEntries(formData.entries());
    
    try {
        const { data: target, error } = await spectraApi.post('/api/v1/targets', {
            address: data.address,
            description: data.description,
            status: 'pending',
            os: 'Unknown'
        });
        
        if (!error) {
            
            // Add to grid
            addTargetToGrid({
                address: target.address,
                description: target.description,
                status: target.status,
                os: target.os,
                ports: 'None'
            });
            
            closeAddTargetModal();
            event.target.reset();
        } else {
            _spectraToast(`Failed to add target: ${error}`, 'error');
        }
    } catch (error) {
        console.error('Error adding target:', error);
        _spectraToast('Error adding target', 'error');
    }
}

function addTargetToGrid(target) {
    const grid = document.getElementById('targets-grid');
    const template = document.getElementById('target-card-template');
    const clone = template.content.cloneNode(true);
    
    clone.querySelector('.target-name').textContent = target.address;
    clone.querySelector('.target-desc').textContent = target.description || 'No description';
    
    // Pass session ID if available (assuming target object has session info)
    const sessionId = target.session_id || null;
    const shellBtn = clone.querySelector('.shell-btn');
    if (shellBtn) {
        shellBtn.onclick = () => openShell(shellBtn, sessionId);
        if (!sessionId) {
            shellBtn.classList.add('opacity-50', 'cursor-not-allowed');
            shellBtn.title = "No active shell session";
        }
    }

    grid.appendChild(clone);
}

// --- Shell Handler ---

let term = null;
let socket = null;
let fitAddon = null;

function openShell(btn, sessionId) {
    document.getElementById('shell-modal').classList.remove('hidden');
    document.getElementById('shell-title').textContent = sessionId ? `Session: ${sessionId}` : 'Connecting...';

    // Initialize xterm.js
    const container = document.getElementById('terminal-container');
    container.innerHTML = ''; // Clear previous

    term = new Terminal({
        cursorBlink: true,
        theme: {
            background: '#000000',
            foreground: '#d4d4d4'
        }
    });

    // Load Fit Addon if available (from CDN in HTML)
    if (typeof FitAddon !== 'undefined') {
        fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
    }

    term.open(container);
    if (fitAddon) fitAddon.fit();

    term.writeln('\x1b[33mConnecting to shell session...\x1b[0m');

    // Connect WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const shellToken = localStorage.getItem('token');
    const wsUrl = `${protocol}//${window.location.host}/api/v1/shell/${sessionId}${shellToken ? '?token=' + encodeURIComponent(shellToken) : ''}`;

    socket = new ReconnectingWebSocket(wsUrl, { maxRetries: 10 });

    socket.on('open', () => {
        term.writeln('\x1b[32mConnected!\x1b[0m');
        term.focus();
    });

    socket.on('message', (event) => {
        term.write(event.data);
    });

    socket.on('close', () => {
        term.writeln('\r\n\x1b[31mConnection closed. Reconnecting...\x1b[0m');
    });

    socket.on('error', (error) => {
        term.writeln('\r\n\x1b[31mConnection error.\x1b[0m');
    });

    // Send input to server
    term.onData(data => {
        socket.send(data);
    });

    // Handle resize
    window.addEventListener('resize', () => {
        if (fitAddon) fitAddon.fit();
    });
}

function closeShell() {
    document.getElementById('shell-modal').classList.add('hidden');
    if (socket) {
        socket.close();
        socket = null;
    }
    if (term) {
        term.dispose();
        term = null;
    }
}

// Initialize with some dummy data
document.addEventListener('DOMContentLoaded', () => {
    // These calls are placeholders. In a real scenario, fetch from API.
    // addTargetToGrid(...)
});

// --- Bulk Import ---
let importFormat = 'csv';
let parsedTargets = [];

function openImportModal(fmt) {
    importFormat = fmt;
    parsedTargets = [];
    document.getElementById('import-preview').classList.add('hidden');
    document.getElementById('import-btn').disabled = true;
    const pasteArea = document.getElementById('import-paste-area');
    const uploadArea = document.getElementById('import-upload-area');
    if (fmt === 'paste') { pasteArea.classList.remove('hidden'); uploadArea.classList.add('hidden'); }
    else { pasteArea.classList.add('hidden'); uploadArea.classList.remove('hidden'); }
    const hint = document.getElementById('import-format-hint');
    hint.textContent = fmt === 'csv' ? 'CSV: ip, hostname, notes' : fmt === 'nmap' ? 'Nmap XML output file' : '';
    document.getElementById('import-modal').classList.remove('hidden');
}
function closeImportModal() { document.getElementById('import-modal').classList.add('hidden'); }

function handleImportDrop(e) { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) parseFile(f); }
function handleImportFile(e) { const f = e.target.files[0]; if (f) parseFile(f); }

function parseFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        const text = e.target.result;
        if (importFormat === 'csv') parseCSV(text);
        else if (importFormat === 'nmap') parseNmapXML(text);
        else parsePasteList(text);
    };
    reader.readAsText(file);
}

function parseCSV(text) {
    const lines = text.trim().split('\n');
    const hasHeader = lines[0] && /ip|address|host/i.test(lines[0]);
    const data = hasHeader ? lines.slice(1) : lines;
    parsedTargets = data.filter(l => l.trim()).map(l => {
        const cols = l.split(',').map(c => c.trim());
        return { address: cols[0] || '', hostname: cols[1] || '', notes: cols[2] || '' };
    }).filter(t => t.address);
    showPreview();
}

function parseNmapXML(text) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(text, 'text/xml');
    const hosts = doc.querySelectorAll('host');
    parsedTargets = [];
    hosts.forEach(h => {
        const addrEl = h.querySelector('address');
        const addr = addrEl ? addrEl.getAttribute('addr') : null;
        if (!addr) return;
        const hostnameEl = h.querySelector('hostnames hostname');
        const hostname = hostnameEl ? hostnameEl.getAttribute('name') : '';
        const ports = [];
        h.querySelectorAll('ports port').forEach(p => {
            const state = p.querySelector('state');
            if (state && state.getAttribute('state') === 'open') ports.push(p.getAttribute('portid'));
        });
        parsedTargets.push({ address: addr, hostname, notes: ports.length ? `Ports: ${ports.join(', ')}` : '' });
    });
    showPreview();
}

function parsePasteList(text) {
    if (!text) text = document.getElementById('import-paste-text').value;
    parsedTargets = text.trim().split('\n').map(l => l.trim()).filter(Boolean).map(l => ({ address: l, hostname: '', notes: '' }));
    showPreview();
}

function showPreview() {
    if (parsedTargets.length === 0) return;
    const body = document.getElementById('import-preview-body');
    const esc = s => { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; };
    body.innerHTML = parsedTargets.slice(0, 50).map(t => `<tr><td class="px-3 py-1.5 font-mono">${esc(t.address)}</td><td class="px-3 py-1.5">${esc(t.hostname)}</td><td class="px-3 py-1.5">${esc(t.notes)}</td></tr>`).join('');
    document.getElementById('import-count').textContent = parsedTargets.length;
    document.getElementById('import-preview').classList.remove('hidden');
    document.getElementById('import-btn').disabled = false;
}

function clearImportPreview() { parsedTargets = []; document.getElementById('import-preview').classList.add('hidden'); document.getElementById('import-btn').disabled = true; }

// Listen for paste area changes
document.getElementById('import-paste-text')?.addEventListener('input', () => { if (importFormat === 'paste') parsePasteList(); });

async function executeImport() {
    if (parsedTargets.length === 0) return;
    document.getElementById('import-btn').disabled = true;
    document.getElementById('import-btn').innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-2"></i>Importing...';
    let success = 0;
    for (const t of parsedTargets) {
        try {
            const { data, error } = await spectraApi.post('/api/v1/targets', { address: t.address, description: t.hostname || t.notes || '', status:'pending', os:'Unknown' });
            if (!error && data) { success++; addTargetToGrid({ address: data.address, description: data.description, status: data.status, os: data.os }); }
        } catch {}
    }
    document.getElementById('import-btn').innerHTML = '<i class="fa-solid fa-file-import mr-2"></i>Import All';
    closeImportModal();
    if (success > 0) loadAttackSurface();
}

// --- Attack Surface Graph (Cytoscape.js) ---
let asCy = null;

function initASGraph() {
    const container = document.getElementById('as-graph');
    container.innerHTML = '';
    asCy = cytoscape({
        container,
        style: [
            { selector: 'node', style: { 'label': 'data(label)', 'color': '#94a3b8', 'font-size': '9px', 'font-family': 'JetBrains Mono', 'text-valign': 'bottom', 'text-margin-y': 4, 'background-color': '#64748b', 'width': 20, 'height': 20 } },
            { selector: 'node[type="host"]', style: { 'background-color': '#8b5cf6', 'width': 28, 'height': 28 } },
            { selector: 'node[type="service"]', style: { 'background-color': '#10b981', 'width': 18, 'height': 18 } },
            { selector: 'node[type="finding"]', style: { 'background-color': '#f43f5e', 'width': 14, 'height': 14 } },
            { selector: 'node[type="finding"][severity="high"]', style: { 'background-color': '#f59e0b' } },
            { selector: 'node[type="finding"][severity="medium"]', style: { 'background-color': '#3b82f6' } },
            { selector: 'edge', style: { 'width': 1, 'line-color': '#334155', 'curve-style': 'bezier' } }
        ],
        layout: { name: 'cose', animate: true }
    });
    asCy.on('tap', 'node', (e) => showASNodeDetails(e.target.data()));
}

async function loadAttackSurface() {
    try {
        const { data: targets, error } = await spectraApi.get('/api/v1/targets');
        if (error) return;
        if (targets.length === 0) return;
        if (!asCy) initASGraph();
        asCy.elements().remove();

        for (const t of targets) {
            const hostId = `host-${t.id}`;
            asCy.add({ group: 'nodes', data: { id: hostId, label: t.address, type: 'host', raw: t } });

            // Fetch findings for this target
            try {
                const { data: findings } = await spectraApi.get(`/api/v1/targets/${t.id}/findings`);
                if (findings) {
                    findings.forEach(f => {
                        const fId = `finding-${f.id}`;
                        asCy.add({ group: 'nodes', data: { id: fId, label: f.title || 'Finding', type: 'finding', severity: (f.severity||'info').toLowerCase(), raw: f } });
                        asCy.add({ group: 'edges', data: { source: hostId, target: fId } });
                    });
                }
            } catch {}
        }

        asCy.layout({ name: document.getElementById('as-layout').value || 'cose', animate: true }).run();
        document.getElementById('as-node-count').textContent = `${asCy.nodes().length} nodes`;
    } catch (e) { console.error('Attack surface load error:', e); }
}

function changeASLayout() { if (asCy) asCy.layout({ name: document.getElementById('as-layout').value, animate: true }).run(); }
function fitASGraph() { if (asCy) asCy.fit(); }
function resetASGraph() { if (asCy) { asCy.elements().remove(); loadAttackSurface(); } }
function exportASGraph() { if (!asCy) return; const png = asCy.png({ bg: '#0f172a', full: true }); const a = document.createElement('a'); a.href = png; a.download = 'attack-surface.png'; a.click(); }

function showASNodeDetails(data) {
    const panel = document.getElementById('as-side-panel');
    const title = document.getElementById('as-panel-title');
    const content = document.getElementById('as-panel-content');
    panel.classList.remove('hidden');

    if (data.type === 'host') {
        const t = data.raw || {};
        title.textContent = t.address || data.label;
        content.innerHTML = `
            <div><span class="text-slate-500">OS:</span> <span class="text-white">${escapeHtml(t.os || 'Unknown')}</span></div>
            <div><span class="text-slate-500">Status:</span> <span class="text-white">${escapeHtml(t.status || 'N/A')}</span></div>
            <div><span class="text-slate-500">Description:</span> <span class="text-white">${escapeHtml(t.description || 'None')}</span></div>
            <div class="pt-2 flex gap-2">
                <button onclick="window.location.href='/targets'" class="px-2 py-1 bg-violet-600 hover:bg-violet-500 rounded text-xs text-white transition-colors">View Findings</button>
            </div>`;
    } else if (data.type === 'finding') {
        const f = data.raw || {};
        title.textContent = f.title || 'Finding';
        const sevColors = { critical: 'text-rose-400', high: 'text-amber-400', medium: 'text-blue-400', low: 'text-slate-400' };
        content.innerHTML = `
            <div><span class="text-slate-500">Severity:</span> <span class="${sevColors[f.severity] || 'text-slate-400'} font-medium uppercase">${escapeHtml(f.severity || 'info')}</span></div>
            <div><span class="text-slate-500">Tool:</span> <span class="text-white">${escapeHtml(f.tool_source || 'N/A')}</span></div>
            <div class="mt-2"><span class="text-slate-500">Description:</span><p class="text-white mt-1">${escapeHtml(f.description || 'No description')}</p></div>`;
    }
}

document.addEventListener('DOMContentLoaded', () => { loadAttackSurface(); });

// --- Expose functions used by HTML onclick/onchange/onsubmit handlers ---
window.openAddTargetModal = openAddTargetModal;
window.closeAddTargetModal = closeAddTargetModal;
window.handleAddTarget = handleAddTarget;
window.closeShell = closeShell;
window.openImportModal = openImportModal;
window.closeImportModal = closeImportModal;
window.handleImportDrop = handleImportDrop;
window.handleImportFile = handleImportFile;
window.clearImportPreview = clearImportPreview;
window.executeImport = executeImport;
window.changeASLayout = changeASLayout;
window.fitASGraph = fitASGraph;
window.resetASGraph = resetASGraph;
window.exportASGraph = exportASGraph;
