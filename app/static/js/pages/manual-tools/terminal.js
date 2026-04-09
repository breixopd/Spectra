// === Pipeline ===
function addPipelineStep() {
    document.getElementById('pipeline-empty')?.remove();
    const canvas = document.getElementById('pipeline-canvas');
    const stepNum = pipelineSteps.length;
    const id = ++pipelineStepId;

    if (stepNum > 0) {
        const conn = document.createElement('div');
        conn.className = 'pipeline-connector shrink-0';
        conn.innerHTML = '<i data-lucide="arrow-right" class="w-3.5 h-3.5 inline-block"></i>';
        canvas.appendChild(conn);
    }

    const node = document.createElement('div');
    node.className = 'pipeline-node shrink-0 animate-fade-in-up';
    node.id = 'pipeline-node-' + id;
    node.innerHTML = `
        <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-mono text-slate-500">Step ${stepNum + 1}</span>
            <button data-action="removePipelineStep" data-value="${id}" class="text-slate-600 hover:text-rose-400 text-xs transition-colors" aria-label="Remove step"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>
        <select data-on-change="updatePipelineStepFromEl" data-step-id="${id}" class="w-full px-2 py-1.5 bg-black/30 border border-white/10 rounded text-sm text-white mb-2 focus:outline-none focus:border-violet-500">
            <option value="">Select tool...</option>
            ${allTools.map(t => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)}</option>`).join('')}
        </select>
        <input type="text" placeholder="Target / Args" id="pipeline-target-${id}"
            class="w-full px-2 py-1.5 bg-black/30 border border-white/10 rounded text-xs text-white placeholder-slate-600 focus:outline-none focus:border-violet-500">
        <div class="text-xs text-slate-600 mt-1.5">Use <code class="text-violet-400">{prev}</code> for previous output</div>
    `;
    canvas.appendChild(node);
    pipelineSteps.push({id, toolId: '', target: ''});
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function removePipelineStep(id) {
    const idx = pipelineSteps.findIndex(s => s.id === id);
    if (idx === -1) return;
    pipelineSteps.splice(idx, 1);
    // Rebuild pipeline canvas
    rebuildPipelineCanvas();
}

function updatePipelineStepFromEl(el) {
    const id = parseInt(el.dataset.stepId, 10);
    updatePipelineStep(id, el.value);
}
function updatePipelineStep(id, toolId) {
    const step = pipelineSteps.find(s => s.id === id);
    if (step) step.toolId = toolId;
}

function rebuildPipelineCanvas() {
    const canvas = document.getElementById('pipeline-canvas');
    canvas.innerHTML = '';
    if (pipelineSteps.length === 0) {
        canvas.innerHTML = '<div class="empty-state" id="pipeline-empty"><i data-lucide="git-branch" class="w-5 h-5 inline-block text-violet-400/40"></i><h3>Build your pipeline</h3><p>Click "Add Step" to chain tools together.</p></div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }
    const saved = [...pipelineSteps];
    pipelineSteps = [];
    pipelineStepId = 0;
    saved.forEach(s => {
        addPipelineStep();
        const last = pipelineSteps[pipelineSteps.length - 1];
        const node = document.getElementById('pipeline-node-' + last.id);
        if (node && s.toolId) {
            node.querySelector('select').value = s.toolId;
            last.toolId = s.toolId;
        }
    });
}

async function runPipeline() {
    const output = document.getElementById('pipeline-output');
    const btn = document.getElementById('pipeline-run-btn');

    if (pipelineSteps.length === 0) { _spectraToast('Add at least one step', 'warning'); return; }

    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin mr-1"></i> Running...';
    output.innerHTML = '';

    let previousOutput = '';
    let previousFindings = [];

    for (let i = 0; i < pipelineSteps.length; i++) {
        const step = pipelineSteps[i];
        if (!step.toolId) {
            output.innerHTML += `<span class="text-amber-400">Step ${i+1}: No tool selected, skipping\n</span>`;
            continue;
        }

        const node = document.getElementById('pipeline-node-' + step.id);
        node?.classList.add('active');
        let target = document.getElementById('pipeline-target-' + step.id)?.value || '';

        if (target.includes('{prev}') && previousOutput) {
            target = target.replace('{prev}', previousOutput.trim().split('\n')[0]);
        } else if (!target && i > 0) {
            target = buildSmartTarget(step.toolId, previousFindings, previousOutput);
        }

        if (!target) {
            output.innerHTML += `<span class="text-amber-400">Step ${i+1} (${escapeHtml(step.toolId)}): No target, skipping\n</span>`;
            node?.classList.remove('active');
            continue;
        }

        output.innerHTML += `<span class="text-violet-400">━━━ Step ${i+1}: ${escapeHtml(step.toolId)} → ${escapeHtml(target)} ━━━</span>\n`;
        output.innerHTML += `<span class="text-slate-500">Executing...</span>\n`;
        output.scrollTop = output.scrollHeight;

        try {
            const res = await spectraApi.post(`/api/v1/tools/${step.toolId}/test`, {target, args: {}, timeout: 300});
            const result = res.data;
            const statusIcon = result.success ? '<span class="text-emerald-400">✓</span>' : '<span class="text-rose-400">✗</span>';
            output.innerHTML += `${statusIcon} Exit: ${result.exit_code} | Duration: ${result.duration_seconds?.toFixed(1) || 0}s | Findings: ${result.parsed_findings_count || 0}\n`;

            if (result.stdout) {
                const preview = result.stdout.slice(0, 1500);
                output.innerHTML += escapeHtml(preview) + (result.stdout.length > 1500 ? '\n...(truncated)' : '') + '\n';
                previousOutput = result.stdout;
                previousFindings = result.parsed_findings || [];
            }
            if (result.stderr) {
                output.innerHTML += `<span class="text-amber-500/60">${escapeHtml(result.stderr.slice(0, 500))}</span>\n`;
            }
        } catch (e) {
            output.innerHTML += `<span class="text-rose-400">Error: ${escapeHtml(e.message)}</span>\n`;
        }

        node?.classList.remove('active');
        output.innerHTML += '\n';
        output.scrollTop = output.scrollHeight;
    }

    output.innerHTML += `<span class="text-emerald-400">━━━ Pipeline complete ━━━</span>\n`;
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="play" class="w-4 h-4 inline-block mr-1"></i> Run Pipeline';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Smart pipeline data passing: extract the right input for the next tool from previous findings
function buildSmartTarget(nextToolId, findings, rawOutput) {
    const globalTarget = document.getElementById('global-target')?.value || '';

    if (!findings.length) {
        return rawOutput ? rawOutput.trim().split('\n')[0] : globalTarget;
    }

    // searchsploit needs "product version" queries
    if (nextToolId === 'searchsploit') {
        const queries = findings
            .filter(f => f.product || f.service)
            .map(f => [f.product, f.version].filter(Boolean).join(' '))
            .filter(Boolean);
        return queries[0] || globalTarget;
    }

    // nuclei/nikto/gobuster/ffuf/dirsearch need URLs
    if (['nuclei', 'nikto', 'gobuster', 'ffuf', 'dirsearch', 'feroxbuster'].includes(nextToolId)) {
        const urls = findings
            .filter(f => f.portid || f.port)
            .map(f => {
                const host = f.ip || f.host || globalTarget;
                const port = f.portid || f.port;
                const svc = (f.service || '').toLowerCase();
                const proto = (svc.includes('ssl') || svc.includes('https') || port == 443) ? 'https' : 'http';
                return `${proto}://${host}:${port}`;
            });
        return urls[0] || globalTarget;
    }

    // sqlmap needs a URL
    if (nextToolId === 'sqlmap') {
        const webFindings = findings.filter(f => {
            const port = f.portid || f.port;
            const svc = (f.service || '').toLowerCase();
            return svc.includes('http') || port == 80 || port == 443 || port == 8080;
        });
        if (webFindings.length) {
            const f = webFindings[0];
            const host = f.ip || f.host || globalTarget;
            const port = f.portid || f.port;
            return `http://${host}:${port}/`;
        }
        return globalTarget;
    }

    // hydra needs host
    if (nextToolId === 'hydra') {
        const sshFindings = findings.filter(f => (f.service || '').toLowerCase().includes('ssh'));
        if (sshFindings.length) {
            return sshFindings[0].ip || sshFindings[0].host || globalTarget;
        }
        return globalTarget;
    }

    // Default: use first finding's host or global target
    const first = findings[0];
    return first?.ip || first?.host || first?.['matched-at'] || globalTarget;
}

// === CVE Lookup ===
async function searchCVEs() {
    const product = document.getElementById('cve-product')?.value?.trim();
    const version = document.getElementById('cve-version')?.value?.trim();
    const service = document.getElementById('cve-service')?.value?.trim();
    const results = document.getElementById('cve-results');
    const countEl = document.getElementById('cve-count');
    const btn = document.getElementById('cve-search-btn');

    if (!product && !service) {
        results.innerHTML = '<div class="text-amber-400 text-sm text-center py-4">Enter a product or service name.</div>';
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin mr-1"></i> Searching...';
    results.innerHTML = '<div class="text-slate-500 text-sm text-center py-8">Searching CVE databases...</div>';

    try {
        const params = new URLSearchParams();
        if (product) params.set('product', product);
        if (version) params.set('version', version);
        if (service) params.set('service', service);

        const res = await spectraApi.get('/api/v1/cve/lookup?' + params.toString());
        const data = res.data;
        const cves = data?.cves || [];
        countEl.textContent = `${data.total || cves.length} found`;

        if (!cves.length) {
            results.innerHTML = '<div class="text-slate-500 text-sm text-center py-8">No CVEs found for this query.</div>';
            return;
        }

        results.innerHTML = cves.map(c => {
            const sevColor = {critical:'text-rose-400 bg-rose-500/10',high:'text-amber-400 bg-amber-500/10',medium:'text-blue-400 bg-blue-500/10',low:'text-slate-400 bg-slate-500/10'}[(c.severity||'').toLowerCase()] || 'text-slate-400 bg-slate-500/10';
            const cveId = c.cve_id || c.cve || c.id || 'N/A';

            let msfHtml = '';
            if (c.metasploit_modules && c.metasploit_modules.length > 0) {
                msfHtml = `<div class="mt-2 pt-2 border-t border-white/5">
                    <div class="flex items-center gap-2 mb-1.5">
                        <i data-lucide="skull" class="w-3.5 h-3.5 inline-block text-rose-400"></i>
                        <span class="text-xs font-bold text-rose-400 uppercase">Metasploit Modules</span>
                    </div>
                    <div class="space-y-1">
                        ${c.metasploit_modules.map(m => `
                            <div class="flex items-center gap-2 text-[11px] px-2 py-1 bg-black/30 rounded group">
                                <span class="px-1 py-0.5 rounded text-xs font-mono uppercase ${m.type === 'exploit' ? 'bg-rose-500/20 text-rose-400' : 'bg-blue-500/20 text-blue-400'}">${escapeHtml(m.type)}</span>
                                <code class="text-slate-300 font-mono truncate flex-1">${escapeHtml(m.module)}</code>
                                <span class="text-xs text-slate-500 font-mono">${escapeHtml(m.rank || '')}</span>
                                <button data-action="clipCopy" data-value="${escapeAttr(m.module)}" class="opacity-0 group-hover:opacity-100 px-1.5 py-0.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded text-xs transition-all" title="Copy module path">
                                    <i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i>
                                </button>
                                <button data-action="launchMetasploit" data-value="${escapeAttr(m.module)}" data-cve="${escapeAttr(cveId)}" class="opacity-0 group-hover:opacity-100 px-1.5 py-0.5 bg-rose-600/80 hover:bg-rose-500 text-white rounded text-xs transition-all" title="Use in Metasploit">
                                    <i data-lucide="rocket" class="w-3.5 h-3.5 inline-block"></i>
                                </button>
                            </div>
                        `).join('')}
                    </div>
                </div>`;
            }

            let exploitBadge = c.exploit_available
                ? `<span class="px-1.5 py-0.5 rounded text-xs font-mono bg-rose-500/20 text-rose-400"><i data-lucide="skull" class="w-3 h-3 inline-block mr-0.5"></i> ${c.exploit_count} exploit${c.exploit_count > 1 ? 's' : ''}</span>`
                : '';

            return `<div class="p-3 rounded-lg bg-black/20 border border-white/5 hover:border-white/10 transition-colors">
                <div class="flex items-center gap-3 mb-1">
                    <code class="text-violet-300 font-mono text-sm font-medium">${escapeHtml(cveId)}</code>
                    <span class="px-1.5 py-0.5 rounded text-xs font-mono uppercase ${sevColor}">${escapeHtml(c.severity || 'unknown')}</span>
                    ${exploitBadge}
                    ${c.type ? `<span class="text-xs text-slate-500 font-mono">${escapeHtml(c.type)}</span>` : ''}
                    ${c.version_match ? '<span class="text-xs text-emerald-400 font-mono">version match</span>' : ''}
                </div>
                <p class="text-sm text-slate-300 line-clamp-2">${escapeHtml(c.description || '')}</p>
                ${c.product ? `<div class="text-xs text-slate-500 mt-1">${escapeHtml(c.product)} ${c.versions || ''}</div>` : ''}
                ${msfHtml}
            </div>`;
        }).join('');
    } catch (e) {
        results.innerHTML = `<div class="text-red-400 text-sm text-center py-4">Error: ${escapeHtml(e.message)}</div>`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="search" class="w-3.5 h-3.5 inline-block mr-1"></i> Search';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

function quickRun(toolId) {
    const target = document.getElementById('global-target')?.value?.trim();
    if (!target) {
        _spectraToast('Enter a target first', 'warning');
        document.getElementById('global-target')?.focus();
        return;
    }
    switchManualTab('execute');
    selectManualTool(toolId);
    setTimeout(() => {
        const targetInput = document.getElementById('arg-target');
        if (targetInput) targetInput.value = target;
        executeManualTool();
    }, 400);
}


// === Session Tracking ===
let currentSessionId = null;

// --- Server sync for manual mode state ---
let _manualSyncTimer = null;

function _collectManualState() {
    return {
        scope_targets: scopeTargets,
        scope_exclusions: scopeExclusions,
        scope_roe: document.getElementById('scope-roe')?.value || '',
        checklist: _collectAllChecklistState(),
        notes: notesData,
        command_history: commandHistory,
    };
}

function _collectAllChecklistState() {
    const all = {};
    for (const method of Object.keys(CHECKLIST_DATA)) {
        const raw = localStorage.getItem('spectra_checklist_' + method);
        if (raw) {
            try { all[method] = JSON.parse(raw); } catch (_) { /* skip */ }
        }
    }
    return all;
}

function syncManualStateToServer() {
    if (!currentSessionId) return;
    clearTimeout(_manualSyncTimer);
    _manualSyncTimer = setTimeout(async () => {
        try {
            await spectraApi.put(
                `/api/v1/pentest-sessions/${currentSessionId}/manual-state`,
                { state: _collectManualState() }
            );
        } catch (e) {
            console.debug('Server sync failed, localStorage is the fallback:', e);
        }
    }, 2000);
}

async function loadManualStateFromServer() {
    if (!currentSessionId) return false;
    try {
        const { data, error } = await spectraApi.get(
            `/api/v1/pentest-sessions/${currentSessionId}/manual-state`
        );
        if (error || !data || !Object.keys(data).length) return false;

        if (Array.isArray(data.scope_targets)) {
            scopeTargets = data.scope_targets;
            localStorage.setItem('spectra_scope_targets', JSON.stringify(scopeTargets));
        }
        if (Array.isArray(data.scope_exclusions)) {
            scopeExclusions = data.scope_exclusions;
            localStorage.setItem('spectra_scope_exclusions', JSON.stringify(scopeExclusions));
        }
        if (typeof data.scope_roe === 'string') {
            localStorage.setItem('spectra_scope_roe', data.scope_roe);
            const roeEl = document.getElementById('scope-roe');
            if (roeEl) roeEl.value = data.scope_roe;
        }
        if (data.checklist && typeof data.checklist === 'object') {
            for (const [method, state] of Object.entries(data.checklist)) {
                localStorage.setItem('spectra_checklist_' + method, JSON.stringify(state));
            }
        }
        if (Array.isArray(data.notes)) {
            notesData = data.notes;
            localStorage.setItem('spectra_notes', JSON.stringify(notesData));
        }
        if (Array.isArray(data.command_history)) {
            commandHistory = data.command_history;
            localStorage.setItem('spectra_cmd_history', JSON.stringify(commandHistory));
        }
        return true;
    } catch (e) {
        console.debug('Failed to load manual state from server:', e);
        return false;
    }
}

async function startSession() {
    const target = document.getElementById('global-target')?.value?.trim() || 'unknown';
    _spectraPrompt('Session name:', (name) => {
        spectraApi.post('/api/v1/pentest-sessions', {name, target, description: ''}).then(res => {
            const session = res.data;
            currentSessionId = session.id;
            document.getElementById('session-label').textContent = `${name} (${target})`;
            document.getElementById('session-start-btn').textContent = 'Active';
            document.getElementById('session-start-btn').disabled = true;
            document.getElementById('session-export-btn').classList.remove('hidden');
        }).catch(e => { _spectraToast('Failed to start session', 'error'); });
    }, { title: 'Start Session', placeholder: `Pentest ${new Date().toLocaleDateString('en-US')}` });
}

function logToSession(action, tool, findings) {
    if (!currentSessionId) return;
    spectraApi.post(`/api/v1/pentest-sessions/${currentSessionId}/log`, {action, tool, note: '', findings: findings || []})
        .catch(e => console.debug('Session log failed:', e));
}

async function exportSession() {
    if (!currentSessionId) return;
    try {
        const res = await spectraApi.get(`/api/v1/pentest-sessions/${currentSessionId}/export`);
        const data = res.data;
        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `session-${currentSessionId}.json`;
        a.click();
    } catch (e) {
        _spectraToast('Export failed: ' + e.message, 'error');
    }
}

// === Launch Metasploit from CVE ===
function launchMetasploit(modulePath, el) {
    const cveId = (typeof el === 'object' && el?.dataset?.cve) ? el.dataset.cve : (typeof el === 'string' ? el : '');
    switchManualTab('execute');
    selectManualTool('metasploit');
    setTimeout(() => {
        const target = document.getElementById('global-target')?.value || '';
        const targetInput = document.getElementById('arg-target');
        if (targetInput && target) targetInput.value = target;
        const moduleInput = document.getElementById('arg-module') || document.getElementById('arg-resource');
        if (moduleInput) moduleInput.value = modulePath;
    }, 400);
}


// ========== COMMAND HISTORY ==========
let commandHistory = JSON.parse(localStorage.getItem('spectra_cmd_history') || '[]');
let historySortKey = 'time';
let historySortAsc = false;

function addToHistory(entry) {
    commandHistory.unshift(entry);
    if (commandHistory.length > 200) commandHistory.pop();
    localStorage.setItem('spectra_cmd_history', JSON.stringify(commandHistory));
    syncManualStateToServer();
    renderHistory();
}

function renderHistory() {
    const search = (document.getElementById('history-search')?.value || '').toLowerCase();
    const toolFilter = document.getElementById('history-tool-filter')?.value || '';

    // Populate tool filter dropdown
    const toolSelect = document.getElementById('history-tool-filter');
    const tools = [...new Set(commandHistory.map(h => h.tool))];
    const currentVal = toolSelect.value;
    toolSelect.innerHTML = '<option value="">All tools</option>' + tools.map(t => `<option value="${escapeAttr(t)}">${escapeHtml(t)}</option>`).join('');
    toolSelect.value = currentVal;

    let filtered = commandHistory.filter(h => {
        if (toolFilter && h.tool !== toolFilter) return false;
        if (search && !h.tool.toLowerCase().includes(search) && !h.target.toLowerCase().includes(search) && !(h.output||'').toLowerCase().includes(search)) return false;
        return true;
    });

    // Sort
    filtered.sort((a, b) => {
        let va, vb;
        if (historySortKey === 'time') { va = new Date(a.time); vb = new Date(b.time); }
        else if (historySortKey === 'tool') { va = a.tool; vb = b.tool; }
        else if (historySortKey === 'status') { va = a.status ? 1 : 0; vb = b.status ? 1 : 0; }
        else if (historySortKey === 'duration') { va = a.duration; vb = b.duration; }
        else { va = a[historySortKey]; vb = b[historySortKey]; }
        if (va < vb) return historySortAsc ? -1 : 1;
        if (va > vb) return historySortAsc ? 1 : -1;
        return 0;
    });

    document.getElementById('history-list').innerHTML = filtered.slice(0, 50).map((h, i) => {
        const t = new Date(h.time);
        const timeStr = t.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
        const statusIcon = h.status ? '<span class="text-emerald-400">&#10003;</span>' : '<span class="text-rose-400">&#10007;</span>';
        const dur = h.duration ? h.duration.toFixed(1) + 's' : '-';
        return `<tr class="border-b border-white/[0.03] hover:bg-white/[0.03] text-xs">
            <td class="px-3 py-1.5 text-slate-400 font-mono">${timeStr}</td>
            <td class="px-3 py-1.5 text-violet-400">${escapeHtml(h.tool)}</td>
            <td class="px-3 py-1.5 text-white font-mono truncate max-w-[150px]">${escapeHtml(h.target)}</td>
            <td class="px-3 py-1.5">${statusIcon}</td>
            <td class="px-3 py-1.5 text-slate-400 font-mono">${dur}</td>
            <td class="px-3 py-1.5 text-right">
                <button data-action="viewHistoryOutput" data-value="${i}" class="px-1.5 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs transition-colors mr-1">View</button>
                <button data-action="rerunFromHistory" data-value="${i}" class="px-1.5 py-0.5 bg-violet-600/60 hover:bg-violet-500 text-white rounded text-xs transition-colors">Re-run</button>
            </td>
        </tr>`;
    }).join('') || '<tr><td colspan="6" class="px-3 py-4 text-center text-slate-500 text-xs">No history yet</td></tr>';
}

function sortHistory(key) {
    if (historySortKey === key) historySortAsc = !historySortAsc;
    else { historySortKey = key; historySortAsc = true; }
    renderHistory();
}

function filterHistory() { renderHistory(); }

function toggleHistoryPanel() {
    const panel = document.getElementById('history-panel');
    const chevron = document.getElementById('history-chevron');
    panel.classList.toggle('hidden');
    chevron.classList.toggle('rotate-180');
    if (!panel.classList.contains('hidden')) renderHistory();
}

function viewHistoryOutput(idx) {
    const h = commandHistory[idx];
    if (!h) return;
    showModal('Output: ' + h.tool + ' → ' + h.target, `<pre class="text-xs text-slate-300 font-mono whitespace-pre-wrap p-4 max-h-[60vh] overflow-y-auto">${colorizeOutput(escapeHtml(h.output || '(no output)'))}</pre>` +
        (h.stderr ? `<pre class="text-xs text-amber-500/70 font-mono whitespace-pre-wrap p-4 border-t border-white/5">${escapeHtml(h.stderr)}</pre>` : ''));
}

function rerunFromHistory(idx) {
    const h = commandHistory[idx];
    if (!h) return;
    switchManualTab('execute');
    selectManualTool(h.toolId || h.tool.toLowerCase());
    setTimeout(() => {
        const targetInput = document.getElementById('arg-target');
        if (targetInput) targetInput.value = h.target;
        executeManualTool();
    }, 400);
}

// ========== DIFF MODAL ==========
function openDiffModal() {
    if (commandHistory.length < 2) { _spectraToast('Need at least 2 command runs to compare', 'warning'); return; }
    const options = commandHistory.slice(0, 50).map((h, i) => {
        const t = new Date(h.time).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
        return `<option value="${i}">${t} - ${h.tool} → ${h.target}</option>`;
    }).join('');

    showModal('Compare Outputs', `
        <div class="p-4">
            <div class="flex gap-4 mb-4">
                <div class="flex-1"><label class="text-xs text-slate-500 uppercase font-bold">Left</label>
                    <select id="diff-left" class="w-full px-2 py-1.5 bg-slate-900/60 border border-white/10 rounded text-xs text-white focus:outline-none">${options}</select></div>
                <div class="flex-1"><label class="text-xs text-slate-500 uppercase font-bold">Right</label>
                    <select id="diff-right" class="w-full px-2 py-1.5 bg-slate-900/60 border border-white/10 rounded text-xs text-white focus:outline-none"><option value="1" selected>${commandHistory.length > 1 ? '' : ''}</option>${options}</select></div>
            </div>
            <button data-action="runDiff" class="px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded text-xs mb-3">Compare</button>
            <div id="diff-output" class="flex gap-2 max-h-[50vh] overflow-y-auto"></div>
        </div>`, 'max-w-5xl');
    if (commandHistory.length > 1) document.getElementById('diff-right').value = '1';
}

function runDiff() {
    const leftIdx = parseInt(document.getElementById('diff-left').value);
    const rightIdx = parseInt(document.getElementById('diff-right').value);
    const left = (commandHistory[leftIdx]?.output || '').split('\n');
    const right = (commandHistory[rightIdx]?.output || '').split('\n');

    const maxLen = Math.max(left.length, right.length);
    let leftHtml = '', rightHtml = '';
    for (let i = 0; i < maxLen; i++) {
        const l = left[i] || '';
        const r = right[i] || '';
        if (l === r) {
            leftHtml += `<div class="diff-unchanged px-2">${escapeHtml(l)}</div>`;
            rightHtml += `<div class="diff-unchanged px-2">${escapeHtml(r)}</div>`;
        } else {
            leftHtml += `<div class="diff-del px-2">${l ? '-' + escapeHtml(l) : '&nbsp;'}</div>`;
            rightHtml += `<div class="diff-add px-2">${r ? '+' + escapeHtml(r) : '&nbsp;'}</div>`;
        }
    }
    document.getElementById('diff-output').innerHTML = `
        <div class="flex-1 bg-black rounded-lg overflow-auto font-mono text-[11px] leading-5 p-2">${leftHtml}</div>
        <div class="flex-1 bg-black rounded-lg overflow-auto font-mono text-[11px] leading-5 p-2">${rightHtml}</div>`;
}

// ========== MODAL SYSTEM ==========
function showModal(title, content, widthClass) {
    const existing = document.getElementById('spectra-modal');
    if (existing) existing.remove();
    const modal = document.createElement('div');
    modal.id = 'spectra-modal';
    modal.className = 'modal-overlay';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    modal.innerHTML = `<div class="modal-content ${widthClass || 'max-w-3xl'} w-full">
        <div class="flex items-center justify-between px-4 py-3 border-b border-white/10">
            <h3 class="text-sm font-bold text-white">${escapeHtml(title)}</h3>
            <button  data-action="closeSpectraModal" class="text-slate-400 hover:text-white"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>
        <div>${content}</div>
    </div>`;
    document.body.appendChild(modal);
}

// ========== SCOPE MANAGEMENT ==========
let scopeTargets = JSON.parse(localStorage.getItem('spectra_scope_targets') || '[]');
let scopeExclusions = JSON.parse(localStorage.getItem('spectra_scope_exclusions') || '[]');

function toggleScopePanel() {
    document.getElementById('scope-panel').classList.toggle('open');
    renderScopeTargets();
    renderScopeExclusions();
}

function addScopeTarget() {
    const type = document.getElementById('scope-target-type').value;
    const value = document.getElementById('scope-target-value').value.trim();
    const notes = document.getElementById('scope-target-notes').value.trim();
    if (!value) return;
    scopeTargets.push({type, value, notes});
    localStorage.setItem('spectra_scope_targets', JSON.stringify(scopeTargets));
    syncManualStateToServer();
    document.getElementById('scope-target-value').value = '';
    document.getElementById('scope-target-notes').value = '';
    renderScopeTargets();
}

function removeScopeTarget(idx) {
    scopeTargets.splice(idx, 1);
    localStorage.setItem('spectra_scope_targets', JSON.stringify(scopeTargets));
    syncManualStateToServer();
    renderScopeTargets();
}

function renderScopeTargets() {
    const icons = {ip:'network', domain:'globe', url:'link'};
    document.getElementById('scope-targets-list').innerHTML = scopeTargets.map((t, i) =>
        `<div class="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-white/[0.02]">
            <i data-lucide="${icons[t.type] || 'circle'}" class="w-3.5 h-3.5 inline-block ${t.type === 'ip' ? 'text-blue-400' : t.type === 'domain' ? 'text-emerald-400' : t.type === 'url' ? 'text-violet-400' : 'text-slate-400'}"></i>
            <span class="text-xs text-slate-500 uppercase w-12">${t.type}</span>
            <span class="text-white font-mono flex-1 truncate">${escapeHtml(t.value)}</span>
            <span class="text-slate-500 text-xs truncate max-w-[100px]">${escapeHtml(t.notes)}</span>
            <button data-action="removeScopeTarget" data-value="${i}" class="text-slate-600 hover:text-rose-400 transition-colors"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>`
    ).join('') || '<div class="text-slate-500 text-xs py-1">No targets defined</div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function addScopeExclusion() {
    const type = document.getElementById('scope-excl-type').value;
    const value = document.getElementById('scope-excl-value').value.trim();
    const reason = document.getElementById('scope-excl-reason').value.trim();
    if (!value) return;
    scopeExclusions.push({type, value, reason});
    localStorage.setItem('spectra_scope_exclusions', JSON.stringify(scopeExclusions));
    syncManualStateToServer();
    document.getElementById('scope-excl-value').value = '';
    document.getElementById('scope-excl-reason').value = '';
    renderScopeExclusions();
}

function removeScopeExclusion(idx) {
    scopeExclusions.splice(idx, 1);
    localStorage.setItem('spectra_scope_exclusions', JSON.stringify(scopeExclusions));
    syncManualStateToServer();
    renderScopeExclusions();
}

function renderScopeExclusions() {
    document.getElementById('scope-exclusions-list').innerHTML = scopeExclusions.map((e, i) =>
        `<div class="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-rose-500/5">
            <i data-lucide="ban" class="w-3.5 h-3.5 inline-block text-rose-400"></i>
            <span class="text-xs text-slate-500 uppercase w-12">${e.type}</span>
            <span class="text-rose-300 font-mono flex-1 truncate">${escapeHtml(e.value)}</span>
            <span class="text-slate-500 text-xs truncate max-w-[100px]">${escapeHtml(e.reason)}</span>
            <button data-action="removeScopeExclusion" data-value="${i}" class="text-slate-600 hover:text-rose-400 transition-colors"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>`
    ).join('') || '<div class="text-slate-500 text-xs py-1">No exclusions defined</div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function saveScope() {
    localStorage.setItem('spectra_scope_roe', document.getElementById('scope-roe').value);
    syncManualStateToServer();
    _spectraToast('Scope saved to session', 'success');
}


// ========== MODAL SYSTEM ==========
function showModal(title, content, widthClass) {
    const existing = document.getElementById('spectra-modal');
    if (existing) existing.remove();
    const modal = document.createElement('div');
    modal.id = 'spectra-modal';
    modal.className = 'modal-overlay';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    modal.innerHTML = `<div class="modal-content ${widthClass || 'max-w-3xl'} w-full">
        <div class="flex items-center justify-between px-4 py-3 border-b border-white/10">
            <h3 class="text-sm font-bold text-white">${escapeHtml(title)}</h3>
            <button  data-action="closeSpectraModal" class="text-slate-400 hover:text-white"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>
        <div>${content}</div>
    </div>`;
    document.body.appendChild(modal);
}

