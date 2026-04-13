// ---- Services ----
const SERVICE_SETTINGS_MAP = {
    sandbox: { url: 'sandbox_orchestrator_url', timeout: 'sandbox_orchestrator_timeout', apiKey: 'sandbox_orchestrator_api_key', label: 'Sandbox Orchestrator', icon: 'box' },
};

let svcTopology = {};
let svcHealth = {};
let svcSettings = {};
let svcAutoRefreshTimer = null;

async function loadServices() {
    const grid = document.getElementById('svc-grid');
    grid.innerHTML = '<div class="col-span-full flex justify-center py-12"><span class="svc-spinner" style="width:24px;height:24px;"></span></div>';
    try {
        const [topoRes, healthRes, settingsRes] = await Promise.all([
            spectraApi.get('/api/v1/system/services/topology'),
            spectraApi.get('/api/v1/system/services/health'),
            spectraApi.get('/api/settings'),
        ]);
        if (!topoRes.error) svcTopology = topoRes.data;
        if (!healthRes.error) svcHealth = healthRes.data;
        if (!settingsRes.error) svcSettings = settingsRes.data;
        renderServiceCards();
    } catch(e) { console.error(e); _spectraToast('Error loading services', 'error'); grid.innerHTML = ''; }
    // Populate billing fields from settings
    loadBillingFields();
}

function loadBillingFields() {
    const prov = document.getElementById('billing-provider');
    const pk = document.getElementById('billing-stripe-pk');
    const sk = document.getElementById('billing-stripe-sk');
    const whs = document.getElementById('billing-stripe-whs');
    if (prov) prov.value = svcSettings.payment_provider || 'manual';
    if (pk) pk.value = svcSettings.stripe_publishable_key || '';
    // Secret fields show placeholder only
    if (sk) sk.value = '';
    if (whs) whs.value = '';
}

async function saveBillingSettings() {
    const body = { payment_provider: document.getElementById('billing-provider').value };
    const pk = document.getElementById('billing-stripe-pk').value;
    if (pk) body.stripe_publishable_key = pk;
    const sk = document.getElementById('billing-stripe-sk').value;
    if (sk) body.stripe_secret_key = sk;
    const whs = document.getElementById('billing-stripe-whs').value;
    if (whs) body.stripe_webhook_secret = whs;
    try {
        const r = await spectraApi.post('/api/settings', body);
        if (r.error) throw new Error(r.error);
        _spectraToast('Billing settings saved', 'success');
        loadServices();
    } catch(e) { _spectraToast(e.message, 'error'); }
}

function renderServiceCards() {
    const grid = document.getElementById('svc-grid');
    let localCount = 0, remoteCount = 0, disabledCount = 0;
    const cards = [];
    for (const [name, map] of Object.entries(SERVICE_SETTINGS_MAP)) {
        const topo = svcTopology[name] || {};
        const health = svcHealth[name] || topo.health || {};
        const mode = topo.mode || 'local';
        const url = topo.url || 'in-process';
        const status = health.status || 'unknown';
        const isDisabled = status === 'disabled';

        if (isDisabled) disabledCount++;
        else if (mode === 'remote') remoteCount++;
        else localCount++;

        const modeBadge = isDisabled ? 'disabled' : mode;
        const modeLabel = isDisabled ? 'DISABLED' : mode.toUpperCase();
        const statusLabels = { healthy: 'Healthy', unhealthy: 'Unhealthy', unknown: 'Unknown', no_health_check: 'No check', disabled: 'Disabled', error: 'Error' };

        cards.push(`
            <div class="service-card glass-panel rounded-xl p-5">
                <div class="flex items-start justify-between mb-3">
                    <div class="flex items-center gap-2">
                        <i data-lucide="${map.icon}" class="w-4 h-4 inline-block text-violet-400"></i>
                        <h3 class="text-sm font-semibold text-white">${escapeHtml(map.label)}</h3>
                    </div>
                    <span class="badge badge-${modeBadge}">${modeLabel}</span>
                </div>
                <div class="space-y-2 text-xs mb-4">
                    <div class="flex items-center justify-between">
                        <span class="text-slate-500">URL</span>
                        <span class="text-slate-300 truncate ml-2 max-w-[200px]" title="${escapeHtml(url)}">${escapeHtml(url === 'in-process' ? 'In-Process' : url)}</span>
                    </div>
                    <div class="flex items-center justify-between">
                        <span class="text-slate-500">Health</span>
                        <span class="flex items-center gap-1.5">
                            <span class="health-dot health-dot-${status}"></span>
                            <span class="text-slate-300">${statusLabels[status] || status}</span>
                        </span>
                    </div>
                    ${health.error ? `<div class="text-red-400 truncate" title="${escapeHtml(health.error)}">${escapeHtml(health.error)}</div>` : ''}
                    <div class="flex items-center justify-between">
                        <span class="text-slate-500">Last check</span>
                        <span class="text-slate-400">${health.checked_at ? formatDateTime(health.checked_at) : 'Never'}</span>
                    </div>
                </div>
                <div class="flex justify-end gap-3 pt-2 border-t border-white/5">
                    ${mode === 'remote' ? `<button data-action="deprovisionServer" data-value="${name}" class="text-xs text-red-400 hover:text-red-300 transition-colors"><i data-lucide="trash-2" class="w-3.5 h-3.5 inline-block mr-1"></i>Remove Server</button>` : ''}
                    <button data-action="openServiceConfigModal" data-value="${name}" class="text-xs text-slate-400 hover:text-violet-400 transition-colors">
                        <i data-lucide="settings" class="w-3.5 h-3.5 inline-block mr-1"></i>Configure
                    </button>
                </div>
            </div>`);
    }
    grid.innerHTML = cards.join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
    document.getElementById('svc-topology-summary').textContent =
        `${localCount} local · ${remoteCount} remote` + (disabledCount ? ` · ${disabledCount} disabled` : '');
}

async function checkAllHealth() {
    const btn = document.getElementById('svc-check-all-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="svc-spinner"></span> Checking…';
    try {
        const r = await spectraApi.get('/api/v1/system/services/health');
        if (r.error) throw new Error(r.error);
        svcHealth = r.data;
        renderServiceCards();
        _spectraToast('Health check complete', 'success');
    } catch(e) { _spectraToast(e.message, 'error'); }
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="heart-pulse" class="w-4 h-4 inline-block mr-1"></i> Check All Health';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function openServiceConfigModal(name) {
    const map = SERVICE_SETTINGS_MAP[name];
    if (!map) return;
    document.getElementById('service-form-name').value = name;
    document.getElementById('service-modal-title').textContent = 'Configure ' + map.label;

    // URL field
    const urlGroup = document.getElementById('svc-field-url-group');
    const urlInput = document.getElementById('svc-field-url');
    if (map.url) {
        urlGroup.style.display = '';
        urlInput.value = svcSettings[map.url] || '';
    } else { urlGroup.style.display = 'none'; }

    // Timeout field
    const timeoutGroup = document.getElementById('svc-field-timeout-group');
    const timeoutInput = document.getElementById('svc-field-timeout');
    if (map.timeout) {
        timeoutGroup.classList.remove('hidden');
        timeoutInput.value = svcSettings[map.timeout] || '';
    } else { timeoutGroup.classList.add('hidden'); }

    // API key field
    const apikeyGroup = document.getElementById('svc-field-apikey-group');
    const apikeyInput = document.getElementById('svc-field-apikey');
    if (map.apiKey) {
        apikeyGroup.classList.remove('hidden');
        apikeyInput.value = '';
    } else { apikeyGroup.classList.add('hidden'); }

    // Reset test result
    document.getElementById('svc-test-result').classList.add('hidden');
    showModal('service-modal');
}

async function testServiceConnection() {
    const resultEl = document.getElementById('svc-test-result');
    const btn = document.getElementById('svc-test-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="svc-spinner"></span> Testing…';
    resultEl.classList.add('hidden');
    try {
        const r = await spectraApi.get('/api/v1/system/services/health');
        if (r.error) throw new Error(r.error);
        const allHealth = r.data;
        const name = document.getElementById('service-form-name').value;
        const h = allHealth[name] || {};
        svcHealth = allHealth;
        if (h.status === 'healthy') {
            resultEl.className = 'text-xs p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400';
            resultEl.textContent = 'Connection successful — service is healthy';
        } else {
            resultEl.className = 'text-xs p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400';
            resultEl.textContent = 'Connection issue: ' + (h.error || h.status || 'unknown');
        }
        resultEl.classList.remove('hidden');
    } catch(e) {
        resultEl.className = 'text-xs p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400';
        resultEl.textContent = 'Test failed: ' + e.message;
        resultEl.classList.remove('hidden');
    }
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="plug" class="w-4 h-4 inline-block mr-1"></i> Test Connection';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

document.getElementById('service-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    const name = document.getElementById('service-form-name').value;
    const map = SERVICE_SETTINGS_MAP[name];
    if (!map) return;
    const body = {};
    if (map.url) body[map.url] = document.getElementById('svc-field-url').value || null;
    if (map.timeout) {
        const tv = document.getElementById('svc-field-timeout').value;
        if (tv) body[map.timeout] = parseInt(tv);
    }
    if (map.apiKey) {
        const kv = document.getElementById('svc-field-apikey').value;
        if (kv) body[map.apiKey] = kv;
    }
    try {
        const r = await spectraApi.post('/api/settings', body);
        if (r.error) throw new Error(r.error);
        _spectraToast(map.label + ' configuration saved', 'success');
        closeModal('service-modal');
        loadServices();
    } catch(e) { _spectraToast(e.message, 'error'); }
});

async function resetServiceToLocal() {
    const name = document.getElementById('service-form-name').value;
    const map = SERVICE_SETTINGS_MAP[name];
    if (!map) return;
    const body = {};
    if (map.url) body[map.url] = null;
    try {
        const r = await spectraApi.post('/api/settings', body);
        if (r.error) throw new Error(r.error);
        _spectraToast(map.label + ' reset to local', 'success');
        closeModal('service-modal');
        loadServices();
    } catch(e) { _spectraToast(e.message, 'error'); }
}

// Auto-refresh
document.getElementById('svc-auto-refresh').addEventListener('change', function() {
    if (this.checked) {
        svcAutoRefreshTimer = setInterval(async () => {
            try {
                const r = await spectraApi.get('/api/v1/system/services/health');
                if (!r.error) { svcHealth = r.data; renderServiceCards(); }
            } catch(e) { /* silent */ }
        }, 60000);
    } else {
        clearInterval(svcAutoRefreshTimer);
        svcAutoRefreshTimer = null;
    }
});

// ---- Server Provisioning ----
document.getElementById('provision-form')?.addEventListener('submit', e => e.preventDefault());
function openProvisionModal() {
    document.getElementById('provision-form').reset();
    document.getElementById('prov-test-result').classList.add('hidden');
    document.getElementById('prov-log-area').classList.add('hidden');
    document.getElementById('prov-logs').textContent = '';
    document.getElementById('prov-submit-btn').disabled = false;
    document.getElementById('prov-submit-btn').innerHTML = '<i data-lucide="rocket" class="w-4 h-4 inline-block mr-1"></i> Provision';
    toggleProvAuth();
    showModal('provision-modal');
}

function toggleProvAuth() {
    const method = document.querySelector('input[name="prov-auth"]:checked').value;
    document.getElementById('prov-password-group').style.display = method === 'password' ? '' : 'none';
    document.getElementById('prov-key-group').style.display = method === 'key' ? '' : 'none';
}

function updateProvisionDefaults() {
    const type = document.getElementById('prov-service-type').value;
    const portEl = document.getElementById('prov-service-port');
    const defaults = { sandbox_worker: 8080, app_worker: 5000, tools_worker: 5000, db_replica: 5432, db_backup: 22 };
    portEl.value = defaults[type] || 8080;
}

function getProvisionConfig() {
    const method = document.querySelector('input[name="prov-auth"]:checked').value;
    const cfg = {
        host: document.getElementById('prov-host').value.trim(),
        port: parseInt(document.getElementById('prov-port').value) || 22,
        username: document.getElementById('prov-username').value.trim() || 'root',
    };
    if (method === 'password') {
        cfg.password = document.getElementById('prov-password').value;
    } else {
        cfg.private_key = document.getElementById('prov-private-key').value;
    }
    return cfg;
}

async function testServerConnection() {
    const resultEl = document.getElementById('prov-test-result');
    const btn = document.getElementById('prov-test-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="svc-spinner"></span> Testing…';
    resultEl.classList.add('hidden');

    try {
        const cfg = getProvisionConfig();
        if (!cfg.host) throw new Error('Host is required');
        const r = await spectraApi.post('/api/admin/servers/verify', cfg);
        if (r.error) throw new Error(r.error);
        const d = r.data;
        if (d.connected) {
            resultEl.className = 'text-xs p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400';
            resultEl.textContent = `Connected — ${d.system_info || 'OK'}` + (d.docker_installed ? ' (Docker installed)' : ' (Docker NOT installed — will be auto-installed)');
        } else {
            resultEl.className = 'text-xs p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400';
            resultEl.textContent = 'Connection failed: ' + (d.error || 'unknown error');
        }
        resultEl.classList.remove('hidden');
    } catch(e) {
        resultEl.className = 'text-xs p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400';
        resultEl.textContent = 'Error: ' + e.message;
        resultEl.classList.remove('hidden');
    }
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="plug" class="w-4 h-4 inline-block mr-1"></i> Test Connection';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function provisionServer() {
    const cfg = getProvisionConfig();
    if (!cfg.host) { _spectraToast('Host is required', 'error'); return; }
    cfg.service_type = document.getElementById('prov-service-type').value;
    cfg.service_port = parseInt(document.getElementById('prov-service-port').value) || 8080;

    const btn = document.getElementById('prov-submit-btn');
    const logArea = document.getElementById('prov-log-area');
    const logPre = document.getElementById('prov-logs');
    btn.disabled = true;
    btn.innerHTML = '<span class="svc-spinner"></span> Provisioning…';
    logArea.classList.remove('hidden');
    logPre.textContent = 'Starting provisioning...\n';

    try {
        const r = await spectraApi.post('/api/admin/servers/provision', cfg);
        const d = r.data;
        logPre.textContent = (d.logs || []).join('\n');
        logPre.scrollTop = logPre.scrollHeight;

        if (d.success) {
            _spectraToast('Server provisioned successfully' + (d.health_check_passed ? ' (healthy)' : ' (health check pending)'), 'success');
            loadServices();
        } else {
            _spectraToast('Provisioning failed: ' + (d.error || 'unknown'), 'error');
        }
    } catch(e) {
        logPre.textContent += '\nError: ' + e.message;
        _spectraToast('Provisioning request failed', 'error');
    }
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="rocket" class="w-4 h-4 inline-block mr-1"></i> Provision';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function deprovisionServer(serviceType) {
    showConfirm('Remove Remote Server', `Remove the ${serviceType.replace('_',' ')} service from its remote server?`, async () => {
        _spectraPrompt('Enter the server host to deprovision:', (host) => {
            _spectraPrompt('Auth method (password/key):', (authMethod) => {
                authMethod = authMethod || 'password';
                const cfg = { host: host.trim(), service_type: serviceType };
                const finalize = (username) => {
                    cfg.username = username || 'root';
                    spectraApi.post('/api/admin/servers/deprovision', cfg)
                        .then(r => {
                            const d = r.data;
                            if (d.success) { _spectraToast('Server deprovisioned', 'success'); loadServices(); }
                            else { _spectraToast('Deprovision failed: ' + (d.error || 'unknown'), 'error'); }
                        })
                        .catch(() => _spectraToast('Deprovision request failed', 'error'));
                };
                if (authMethod === 'key') {
                    _spectraPrompt('Paste private key:', (key) => {
                        cfg.private_key = key;
                        _spectraPrompt('SSH username (default: root):', finalize, { placeholder: 'root' });
                    }, { title: 'Private Key' });
                } else {
                    _spectraPrompt('SSH password:', (pw) => {
                        cfg.password = pw;
                        _spectraPrompt('SSH username (default: root):', finalize, { placeholder: 'root' });
                    }, { title: 'SSH Password', inputType: 'password' });
                }
            }, { title: 'Auth Method', placeholder: 'password' });
        }, { title: 'Server Host', placeholder: 'hostname or IP' });
    });
}

// ---- Microservices Health Monitor ----
let svcHealthTimer = null;

async function pollMicroservicesHealth() {
    try {
        const r = await spectraApi.get('/api/admin/services');
        if (r.error) return;
        const data = r.data;
        const dotMap = { 'api': 'svc-api-dot', 'ai-svc': 'svc-ai-dot', 'scheduler': 'svc-scheduler-dot', 'worker': 'svc-worker-dot' };
        for (const svc of data.services || []) {
            const dot = document.getElementById(dotMap[svc.name]);
            if (!dot) continue;
            dot.className = 'health-dot health-dot-' + (svc.status === 'healthy' ? 'healthy' : svc.status === 'unhealthy' ? 'unhealthy' : 'unknown') + ' mx-auto';
        }
    } catch(e) { console.error('Microservices health poll error', e); }
}

function startSvcHealthPoll() {
    pollMicroservicesHealth();
    if (svcHealthTimer) clearInterval(svcHealthTimer);
    svcHealthTimer = setInterval(pollMicroservicesHealth, 15000);
}

// Start polling when services tab active
const origShowSection = window.showSection;
window.showSection = function(name) {
    if (typeof origShowSection === 'function') origShowSection(name);
    if (name === 'services') { startSvcHealthPoll(); refreshNodesList(); }
    else if (svcHealthTimer) { clearInterval(svcHealthTimer); svcHealthTimer = null; }
};

// ---- Server Nodes Management ----
async function refreshNodesList() {
    const container = document.getElementById('nodes-list');
    container.innerHTML = '<p class="text-xs text-slate-500">Loading...</p>';
    try {
        const r = await spectraApi.get('/api/admin/services/nodes');
        if (r.error) throw new Error(r.error);
        const data = r.data;
        if (!data.nodes || data.nodes.length === 0) {
            container.innerHTML = '<p class="text-xs text-slate-500">No server nodes registered. Use "Add Remote Server" above.</p>';
            return;
        }
        container.innerHTML = data.nodes.map(n => `
            <div class="flex items-center justify-between p-3 rounded-lg bg-slate-800/50 border border-white/5">
                <div class="flex items-center gap-3">
                    <span class="health-dot health-dot-${n.health_status || 'unknown'}"></span>
                    <div>
                        <div class="text-sm font-medium text-white">${escapeHtml(n.name)}</div>
                        <div class="text-xs text-slate-500">${escapeHtml(n.url)} · ${escapeHtml(n.service_type)} · SSH ${escapeHtml(n.ssh_user || 'root')}:${n.ssh_port || 22}</div>
                    </div>
                </div>
                <div class="flex items-center gap-2">
                    ${n.deployed_services ? `<span class="text-xs text-emerald-400">${(n.deployed_services.length || 0)} services</span>` : ''}
                    <button data-action="deployToNode" data-value="${n.id}" data-node-name="${escapeHtml(n.name)}" class="px-2 py-1 bg-violet-600 hover:bg-violet-500 text-white rounded text-xs transition-colors">
                        <i data-lucide="rocket" class="w-3.5 h-3.5 inline-block mr-1"></i>Deploy
                    </button>
                    <button data-action="viewNodeLogs" data-value="${n.id}" class="px-2 py-1 text-xs text-slate-400 hover:text-white transition-colors">
                        <i data-lucide="file-text" class="w-3.5 h-3.5 inline-block mr-1"></i>Logs
                    </button>
                </div>
            </div>
        `).join('');
    } catch(e) { container.innerHTML = '<p class="text-xs text-red-400">Error loading nodes</p>'; }
}

async function deployToNode(nodeId, el) {
    const nodeName = (typeof el === 'object' && el?.dataset?.nodeName) ? el.dataset.nodeName : (el || 'node');
    nodeId = parseInt(nodeId, 10);
    showConfirm('Deploy Services', `Deploy Spectra services to ${nodeName}? This may take several minutes.`, async () => {
        _spectraToast('Starting deployment to ' + nodeName + '...', 'success');
    try {
        const r = await spectraApi.post(`/api/admin/services/nodes/${nodeId}/deploy`, { services: null, harden: true });
        const data = r.data;
        if (data.status === 'complete') {
            _spectraToast('Deployment successful!', 'success');
        } else {
            _spectraToast('Deployment failed: ' + (data.message || 'unknown'), 'error');
        }
        // Show logs
        document.getElementById('deploy-logs-content').textContent = (data.logs || []).join('\n');
        showModal('deploy-logs-modal');
        refreshNodesList();
    } catch(e) { _spectraToast('Deployment request failed', 'error'); }
    });
}

async function viewNodeLogs(nodeId) {
    try {
        const r = await spectraApi.get(`/api/admin/services/nodes/${nodeId}/logs`);
        const data = r.data;
        document.getElementById('deploy-logs-content').textContent = (data.logs || []).join('\n') || 'No logs available.';
        showModal('deploy-logs-modal');
    } catch(e) { _spectraToast('Failed to load logs', 'error'); }
}

