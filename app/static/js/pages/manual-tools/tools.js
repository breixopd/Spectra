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
        return `<div class="tool-card rounded-lg p-3 cursor-pointer glass-panel ${sel}" data-action="selectManualTool" data-value="${escapeHtml(t.id)}">
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
        <button type="button" data-action="refreshWordlistOptions" class="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white text-xs" title="Refresh wordlists"><i data-lucide="rotate-ccw" class="w-3.5 h-3.5 inline-block"></i></button>
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
            actions += `<button data-action="lookupCVEsFor" data-value="${escapeAttr(product)}" class="px-1.5 py-0.5 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 rounded text-xs transition-colors" title="Search CVEs for ${escapeAttr(product)}"><i data-lucide="shield-alert" class="w-3.5 h-3.5 inline-block"></i></button>`;
            actions += `<button data-action="runToolOn" data-value="searchsploit" data-tool-target="${escapeAttr(product)}" class="px-1.5 py-0.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 rounded text-xs transition-colors" title="SearchSploit"><i data-lucide="search" class="w-3.5 h-3.5 inline-block"></i></button>`;
        }
        if (f.port || f.portid) {
            const host = f.ip || f.host || document.getElementById('global-target')?.value || '';
            const port = f.portid || f.port;
            const svc = (f.service || '').toLowerCase();
            const proto = (svc.includes('ssl') || svc.includes('https') || port == 443) ? 'https' : 'http';
            const url = `${proto}://${host}:${port}`;
            actions += `<button data-action="runToolOn" data-value="nuclei" data-tool-target="${escapeAttr(url)}" class="px-1.5 py-0.5 bg-violet-500/10 hover:bg-violet-500/20 text-violet-400 rounded text-xs transition-colors" title="Scan with Nuclei"><i data-lucide="bug" class="w-3.5 h-3.5 inline-block"></i></button>`;
            if (svc.includes('http')) {
                actions += `<button data-action="runToolOn" data-value="nikto" data-tool-target="${escapeAttr(url)}" class="px-1.5 py-0.5 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 rounded text-xs transition-colors" title="Scan with Nikto"><i data-lucide="globe" class="w-3.5 h-3.5 inline-block"></i></button>`;
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

function runToolOn(toolId, el) {
    const target = (typeof el === 'object' && el?.dataset?.toolTarget) ? el.dataset.toolTarget : (typeof el === 'string' ? el : '');
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
        return `<button data-action="chainToTool" data-value="${id}" class="px-3 py-1.5 bg-slate-800 hover:bg-violet-500/10 border border-white/5 rounded-lg text-xs text-slate-300 transition-colors flex items-center gap-1.5">
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

