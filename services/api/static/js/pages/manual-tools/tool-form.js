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
