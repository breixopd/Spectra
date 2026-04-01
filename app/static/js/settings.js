function authHeaders(extra = {}) {
    return {
        ...extra,
    };
}

function setFieldValue(name, value) {
    const field = document.querySelector(`[name="${name}"]`);
    if (field) {
        field.value = value || '';
    }
}

function setCheckboxValue(name, value) {
    const field = document.querySelector(`[name="${name}"]`);
    if (field) {
        field.checked = !!value;
    }
}

function activateNavLink(targetId) {
    document.querySelectorAll('[role="tablist"] [role="tab"]').forEach((link) => {
        const isActive = link.getAttribute('aria-controls') === targetId;
        link.classList.toggle('bg-white/5', isActive);
        link.classList.toggle('text-white', isActive);
        link.classList.toggle('text-slate-400', !isActive);
        link.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
}

function copyProfileValues(sourcePrefix, targetPrefix) {
    const provider = document.querySelector(`[name="${sourcePrefix}_provider"]`)?.value;
    const model = document.querySelector(`[name="${sourcePrefix}_model"]`)?.value;
    if (provider) {
        setFieldValue(`${targetPrefix}_provider`, provider);
    }
    if (model) {
        setFieldValue(`${targetPrefix}_model`, model);
    }

    const sourceApiBaseUrl = document.querySelector(`[name="${sourcePrefix}_api_base_url"]`)?.value;
    if (sourceApiBaseUrl !== undefined) {
        setFieldValue(`${targetPrefix}_api_base_url`, sourceApiBaseUrl);
    }
}

function toggleProfileFields(prefix) {
    const provider = document.querySelector(`[name="${prefix}_provider"]`)?.value;
    const apiFields = document.querySelector(`.profile-api-fields[data-profile="${prefix}"]`);
    if (apiFields) {
        apiFields.classList.toggle('hidden', !provider);
    }
}

function toggleTierFields(tier) {
    const enabled = document.querySelector(`.tier-toggle[data-tier="${tier}"]`)?.checked;
    const fields = document.querySelector(`[data-tier-fields="${tier}"]`);
    if (fields) {
        fields.classList.toggle('hidden', !enabled);
        if (enabled) {
            const modelField = document.querySelector(`[name="${tier}_model"]`);
            if (modelField && !modelField.value.trim()) {
                copyProfileValues('default', tier);
            }
            toggleProfileFields(tier);
        }
    }
}

function updateFallbackLabels() {
    const rows = Array.from(document.querySelectorAll('.fallback-row'));
    rows.forEach((row, index) => {
        row.querySelector('.fallback-order').textContent = `#${index + 1}`;
        row.querySelector('.fallback-profile-id').value = row.dataset.profileId || `fallback_${index + 1}`;
    });
}

function toggleFallbackFields(row) {
    const provider = row.querySelector('.fallback-provider').value;
    row.querySelector('.fallback-api-fields').classList.toggle('hidden', !provider);
}

function addFallbackRow(profile = null) {
    const template = document.getElementById('fallback-profile-template');
    const container = document.getElementById('fallback-profiles');
    const row = template.content.firstElementChild.cloneNode(true);
    if (profile) {
        row.dataset.profileId = profile.id || '';
        row.querySelector('.fallback-provider').value = profile.provider || 'litellm';
        row.querySelector('.fallback-model').value = profile.model || '';
        row.querySelector('.fallback-api-base-url').value = profile.base_url || '';
        row.querySelector('.fallback-api-key').value = profile.api_key || '';
    }
    row.querySelector('.fallback-provider').addEventListener('change', () => toggleFallbackFields(row));
    row.querySelector('.remove-fallback').addEventListener('click', () => {
        row.remove();
        updateFallbackLabels();
    });
    container.appendChild(row);
    toggleFallbackFields(row);
    updateFallbackLabels();
}

function collectProfile(prefix) {
    const provider = document.querySelector(`[name="${prefix}_provider"]`).value;
    const model = document.querySelector(`[name="${prefix}_model"]`).value.trim();
    if (!model) {
        throw new Error(`Model is required for ${prefix === 'default' ? 'the default profile' : prefix.toUpperCase()}`);
    }
    const profile = { provider, model };
    const baseUrl = document.querySelector(`[name="${prefix}_api_base_url"]`)?.value.trim();
    const apiKey = document.querySelector(`[name="${prefix}_api_key"]`)?.value.trim();
    if (baseUrl) profile.base_url = baseUrl;
    if (apiKey) profile.api_key = apiKey;
    return profile;
}

function collectFallbackProfiles() {
    const profiles = {};
    const chain = [];
    document.querySelectorAll('.fallback-row').forEach((row, index) => {
        const profileId = row.querySelector('.fallback-profile-id').value || `fallback_${index + 1}`;
        const provider = row.querySelector('.fallback-provider').value;
        const model = row.querySelector('.fallback-model').value.trim();
        if (!model) return;
        const profile = { provider, model };
        const baseUrl = row.querySelector('.fallback-api-base-url').value.trim();
        const apiKey = row.querySelector('.fallback-api-key').value.trim();
        if (baseUrl) profile.base_url = baseUrl;
        if (apiKey) profile.api_key = apiKey;
        profiles[profileId] = profile;
        chain.push(profileId);
    });
    return { profiles, chain };
}

function populateProfile(prefix, profile) {
    if (!profile) return;
    setFieldValue(`${prefix}_provider`, profile.provider);
    setFieldValue(`${prefix}_model`, profile.model);
    setFieldValue(`${prefix}_api_base_url`, profile.base_url);
    toggleProfileFields(prefix);
}

function renderResolvedSummary(resolvedAi) {
    const container = document.getElementById('resolved-ai-summary');
    if (!container || !resolvedAi) return;
    const fallbackChain = (resolvedAi.fallbacks?.default || []).join(' -> ') || 'None';
    const tierItems = ['tier1', 'tier2', 'tier3'].map((tier) => {
        const route = resolvedAi.tiers?.[tier] || {};
        return `
            <div class="rounded-lg bg-slate-950/40 border border-white/5 p-3">
                <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500">${escapeHtml(tier)}</div>
                <div class="text-sm text-white mt-1">${escapeHtml(route.profile || resolvedAi.default_profile)}</div>
                <div class="text-xs text-slate-400 mt-1">${escapeHtml(route.provider || '')} ${escapeHtml(route.model || '')}</div>
                <div class="text-[11px] text-slate-500 mt-1">${route.inherits_default ? 'inherits default' : 'custom override'}</div>
            </div>
        `;
    }).join('');
    container.innerHTML = `
        <p class="text-sm font-medium text-white">Resolved Runtime</p>
        <div class="rounded-lg bg-slate-950/40 border border-white/5 p-3">
            <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500">default</div>
            <div class="text-sm text-white mt-1">${escapeHtml(resolvedAi.default_profile)}</div>
            <div class="text-xs text-slate-400 mt-1">${escapeHtml(resolvedAi.default_route?.provider || '')} ${escapeHtml(resolvedAi.default_route?.model || '')}</div>
        </div>
        <div class="space-y-2">${tierItems}</div>
        <div class="rounded-lg bg-slate-950/40 border border-white/5 p-3">
            <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500">fallback chain</div>
            <div class="text-xs text-slate-300 mt-1">${escapeHtml(fallbackChain)}</div>
        </div>
    `;
}

function buildSettingsPayload() {
    const payload = {
        tensorzero_gateway_url: document.querySelector('[name="tensorzero_gateway_url"]')?.value.trim() || '',
        llm_timeout: parseFloat(document.querySelector('[name="llm_timeout"]')?.value) || 600,
        log_level: document.querySelector('[name="log_level"]').value,
        plugin_safe_mode: document.querySelector('[name="plugin_safe_mode"]').checked,
        connect_back_host: document.querySelector('[name="connect_back_host"]').value.trim(),
        require_approval: document.querySelector('[name="require_approval"]').checked,
        notification_webhook: document.querySelector('[name="notification_webhook"]').value.trim(),
        embedding_model: document.querySelector('[name="embedding_model"]')?.value.trim() || null,
        embedding_api_key: document.querySelector('[name="embedding_api_key"]')?.value.trim() || undefined,
    };

    const platformForm = document.getElementById('platform-form');
    payload.platform_domain = platformForm.querySelector('[name="platform_domain"]').value.trim();
    payload.platform_base_url = platformForm.querySelector('[name="platform_base_url"]').value.trim();
    payload.platform_exposed = platformForm.querySelector('[name="platform_exposed"]').checked;

    // Sandbox pool settings
    const sandboxForm = document.getElementById('sandbox-form');
    if (sandboxForm) {
        const maxContainers = sandboxForm.querySelector('[name="sandbox_max_containers"]').value;
        if (maxContainers) payload.sandbox_max_containers = parseInt(maxContainers, 10);
        payload.sandbox_memory_limit = sandboxForm.querySelector('[name="sandbox_memory_limit"]').value;
        const cpuShares = sandboxForm.querySelector('[name="sandbox_cpu_shares"]').value;
        if (cpuShares) payload.sandbox_cpu_shares = parseInt(cpuShares, 10);
        const maxLifetime = sandboxForm.querySelector('[name="sandbox_max_lifetime"]').value;
        if (maxLifetime) payload.sandbox_max_lifetime = parseInt(maxLifetime, 10);

        // Advanced sandbox settings
        const resourceTiers = sandboxForm.querySelector('[name="sandbox_resource_tiers"]');
        if (resourceTiers && resourceTiers.value.trim()) payload.sandbox_resource_tiers = resourceTiers.value.trim();

        const networkIsolation = sandboxForm.querySelector('[name="sandbox_network_isolation"]');
        if (networkIsolation) payload.sandbox_network_isolation = networkIsolation.checked;

        const oomEscalation = sandboxForm.querySelector('[name="sandbox_oom_escalation_enabled"]');
        if (oomEscalation) payload.sandbox_oom_escalation_enabled = oomEscalation.checked;

        const warmPoolEnabled = sandboxForm.querySelector('[name="sandbox_warm_pool_enabled"]');
        if (warmPoolEnabled) payload.sandbox_warm_pool_enabled = warmPoolEnabled.checked;

        const warmPoolSize = sandboxForm.querySelector('[name="sandbox_warm_pool_size"]');
        if (warmPoolSize && warmPoolSize.value) payload.sandbox_warm_pool_size = parseInt(warmPoolSize.value, 10);

        const idleTimeout = sandboxForm.querySelector('[name="sandbox_idle_timeout"]');
        if (idleTimeout && idleTimeout.value) payload.sandbox_idle_timeout = parseInt(idleTimeout.value, 10);

        const heartbeatInterval = sandboxForm.querySelector('[name="sandbox_heartbeat_interval"]');
        if (heartbeatInterval && heartbeatInterval.value) payload.sandbox_heartbeat_interval = parseInt(heartbeatInterval.value, 10);

        const autoBuild = sandboxForm.querySelector('[name="sandbox_auto_build_image"]');
        if (autoBuild) payload.sandbox_auto_build_image = autoBuild.checked;

        const scanEnabled = sandboxForm.querySelector('[name="sandbox_image_scan_enabled"]');
        if (scanEnabled) payload.sandbox_image_scan_enabled = scanEnabled.checked;

        const blockCritical = sandboxForm.querySelector('[name="sandbox_image_scan_block_critical"]');
        if (blockCritical) payload.sandbox_image_scan_block_critical = blockCritical.checked;

        const perUserLimit = sandboxForm.querySelector('[name="sandbox_per_user_limit"]');
        if (perUserLimit && perUserLimit.value) payload.sandbox_per_user_limit = parseInt(perUserLimit.value, 10);

        const defaultPriority = sandboxForm.querySelector('[name="sandbox_default_priority"]');
        if (defaultPriority && defaultPriority.value) payload.sandbox_default_priority = parseInt(defaultPriority.value, 10);
    }

    return payload;
}

async function loadSettings() {
    const { data, error: loadError } = await spectraApi.get('/api/settings');
    if (loadError) {
        throw new Error(loadError);
    }

    setFieldValue('tensorzero_gateway_url', data.tensorzero_gateway_url);
    setFieldValue('llm_timeout', data.llm_timeout || 600);
    setFieldValue('log_level', data.log_level);
    setCheckboxValue('plugin_safe_mode', data.plugin_safe_mode);
    setFieldValue('connect_back_host', data.connect_back_host);
    setCheckboxValue('require_approval', data.require_approval);
    setFieldValue('notification_webhook', data.notification_webhook);
    setFieldValue('embedding_model', data.embedding_model);
    setFieldValue('platform_domain', data.platform_domain);
    setFieldValue('platform_base_url', data.platform_base_url);
    setCheckboxValue('platform_exposed', data.platform_exposed);
    document.getElementById('platform-exposed-warning')?.classList.toggle('hidden', !data.platform_exposed);

    // Sandbox pool settings
    setFieldValue('sandbox_max_containers', data.sandbox_max_containers);
    setFieldValue('sandbox_memory_limit', data.sandbox_memory_limit);
    setFieldValue('sandbox_cpu_shares', String(data.sandbox_cpu_shares));
    setFieldValue('sandbox_max_lifetime', data.sandbox_max_lifetime);

    // Advanced sandbox settings
    setFieldValue('sandbox_resource_tiers', data.sandbox_resource_tiers);
    setCheckboxValue('sandbox_network_isolation', data.sandbox_network_isolation);
    setFieldValue('sandbox_idle_timeout', data.sandbox_idle_timeout);
    setFieldValue('sandbox_heartbeat_interval', data.sandbox_heartbeat_interval);
    setFieldValue('sandbox_per_user_limit', data.sandbox_per_user_limit);
    setFieldValue('sandbox_default_priority', data.sandbox_default_priority);
    setCheckboxValue('sandbox_oom_escalation_enabled', data.sandbox_oom_escalation_enabled);
    setCheckboxValue('sandbox_warm_pool_enabled', data.sandbox_warm_pool_enabled);
    setFieldValue('sandbox_warm_pool_size', data.sandbox_warm_pool_size);
    setCheckboxValue('sandbox_auto_build_image', data.sandbox_auto_build_image);
    setCheckboxValue('sandbox_image_scan_enabled', data.sandbox_image_scan_enabled);
    setCheckboxValue('sandbox_image_scan_block_critical', data.sandbox_image_scan_block_critical);

    // Update sandbox status indicator
    const statusDot = document.getElementById('sandbox-status-dot');
    const statusText = document.getElementById('sandbox-status-text');
    if (data.sandbox_available && statusDot && statusText) {
        if (data.sandbox_available.available) {
            statusDot.className = 'w-2 h-2 rounded-full bg-emerald-400';
            statusText.textContent = data.sandbox_available.message;
            statusText.className = 'text-xs text-emerald-400';
        } else {
            statusDot.className = 'w-2 h-2 rounded-full bg-amber-400';
            statusText.textContent = data.sandbox_available.message;
            statusText.className = 'text-xs text-amber-400';
        }
    }
}

async function saveSettings(event) {
    event.preventDefault();
    const submitButton = event.target.querySelector('button[type="submit"]');
    const originalText = submitButton.textContent;
    submitButton.disabled = true;
    submitButton.textContent = 'Saving...';
    try {
        const { error: saveError } = await spectraApi.post('/api/settings', buildSettingsPayload());
        if (saveError) {
            throw new Error(saveError);
        }
        await loadSettings();
        _spectraToast('Settings saved successfully.', 'success');
    } catch (error) {
        console.error('Error saving settings:', error);
        _spectraToast(error.message || 'Failed to save settings', 'error');
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = originalText;
    }
}

async function testDefaultProfile() {
    const button = document.getElementById('test-default-profile-btn');
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = 'Testing...';
    try {
        const { data: result, error: testError } = await spectraApi.get('/api/v1/admin/tensorzero/status');
        if (testError || !result?.online) {
            throw new Error(testError || result?.error || 'Gateway connection failed');
        }
        _spectraToast('Gateway online — ' + (result.functions_count || 0) + ' functions, ' + (result.models_count || 0) + ' models configured.', 'success');
    } catch (error) {
        console.error('Gateway test failed:', error);
        _spectraToast(error.message || 'Gateway connection failed', 'error');
    } finally {
        button.disabled = false;
        button.textContent = originalText;
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    document.querySelectorAll('[role="tablist"] [role="tab"]').forEach((anchor) => {
        anchor.addEventListener('click', function () {
            const targetId = this.getAttribute('aria-controls');
            const target = targetId ? document.getElementById(targetId) : null;
            if (target) {
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                activateNavLink(targetId);
                if (history.replaceState) history.replaceState(null, '', '#' + targetId);
            }
        });
    });

    const settingsHash = window.location.hash.slice(1);
    if (settingsHash && document.getElementById(settingsHash)) {
        const target = document.getElementById(settingsHash);
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        activateNavLink(settingsHash);
    } else {
        activateNavLink('general');
    }

    document.getElementById('test-default-profile-btn')?.addEventListener('click', testDefaultProfile);
    document.getElementById('settings-form')?.addEventListener('submit', saveSettings);

    const domainInput = document.getElementById('platform_domain');
    const baseUrlInput = document.getElementById('platform_base_url');
    if (domainInput && baseUrlInput) {
        domainInput.addEventListener('input', () => {
            if (domainInput.value.trim() && !baseUrlInput.value.trim()) {
                baseUrlInput.value = `https://${domainInput.value.trim()}`;
            }
        });
    }

    try {
        await loadSettings();
    } catch (error) {
        console.error('Failed to initialize settings page:', error);
        _spectraToast('Failed to load settings. Refresh the page after logging in again if the problem persists.', 'error');
    }
});

// === Data Management Functions ===
async function clearToolStats() {
    _spectraConfirm('Clear all tool statistics?', async () => {
        try {
            const { data, error } = await spectraApi.post('/api/v1/system/clear/tools');
            if (!error) {
                _spectraToast(`Cleared ${data.cleared_count || 0} tool stat entries`, 'success');
            } else {
                _spectraToast('Error: ' + (error.detail || 'Failed to clear'), 'error');
            }
        } catch (e) {
            _spectraToast('Error: ' + e.message, 'error');
        }
    }, { title: 'Clear Tool Statistics' });
}

function showClearMissionsConfirm() {
    document.getElementById('clear-missions-modal').classList.remove('hidden');
}

function hideClearMissionsConfirm() {
    document.getElementById('clear-missions-modal').classList.add('hidden');
}

async function confirmClearMissions() {
    hideClearMissionsConfirm();
    try {
        const { data, error } = await spectraApi.post('/api/v1/system/clear/missions', { confirm: true });
        if (!error) {
            _spectraToast(`Deleted ${data.cleared_count || 0} missions`, 'success');
        } else {
            _spectraToast('Error: ' + (error.detail || 'Failed to clear'), 'error');
        }
    } catch (e) {
        _spectraToast('Error: ' + e.message, 'error');
    }
}

async function clearCache() {
    _spectraConfirm('Clear application cache? This may affect performance temporarily.', async () => {
        try {
            const { data, error } = await spectraApi.post('/api/v1/system/clear/cache');
            if (!error) {
                _spectraToast(`Cleared ${data.cleared_count || 0} cache entries`, 'success');
            } else {
                _spectraToast('Error: ' + (error.detail || 'Failed to clear'), 'error');
            }
        } catch (e) {
            _spectraToast('Error: ' + e.message, 'error');
        }
    }, { title: 'Clear Cache' });
}

async function reinstallTools() {
    _spectraConfirm('Reinstall all tools? This may take several minutes.', async () => {
        try {
            const { data, error } = await spectraApi.post('/api/v1/tools/install-all');
            if (!error) {
                _spectraToast('Tool installation queued. Check system status for progress.', 'success');
            } else {
                _spectraToast('Error: ' + (error.detail || 'Failed to queue'), 'error');
            }
        } catch (e) {
            _spectraToast('Error: ' + e.message, 'error');
        }
    }, { title: 'Reinstall Tools' });
}

// Load system status on page load
async function loadSystemStatus() {
    const container = document.getElementById('system-status-content');
    try {
        const { data } = await spectraApi.get('/api/v1/system/status');
        
        const dbStatus = data.database?.status === 'healthy' ? 
            '<span class="text-emerald-400"><i data-lucide="check-circle" class="w-4 h-4 inline-block"></i> Connected</span>' :
            '<span class="text-rose-400"><i data-lucide="x-circle" class="w-4 h-4 inline-block"></i> Error</span>';

        const ts = data.tool_stats || {};
        
        container.innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="flex justify-between text-sm">
                    <span class="text-slate-400">Database</span>
                    ${dbStatus}
                </div>
                <div class="flex justify-between text-sm">
                    <span class="text-slate-400">Tools Ready</span>
                    <span class="text-white">${ts.ready || 0} / ${ts.total || 0}</span>
                </div>
                <div class="flex justify-between text-sm">
                    <span class="text-slate-400">Tools Installing</span>
                    <span class="${ts.installing > 0 ? 'text-amber-400' : 'text-slate-500'}">${ts.installing || 0}</span>
                </div>
            </div>
            <div class="mt-4 pt-3 border-t border-white/5">
                <div class="flex items-center gap-2">
                    <div class="w-2 h-2 rounded-full ${data.status === 'ready' ? 'bg-emerald-500' : 'bg-amber-500 animate-pulse'}"></div>
                    <span class="text-sm ${data.status === 'ready' ? 'text-emerald-400' : 'text-amber-400'}">${escapeHtml(data.message)}</span>
                </div>
            </div>
        `;
    } catch (e) {
        container.innerHTML = '<span class="text-rose-400">Failed to load status</span>';
    }
}

loadSystemStatus();
setInterval(loadSystemStatus, 10000);

// === Data Sources ===
async function loadDataSourceStatus() {
    const container = document.getElementById('data-sources-status');
    try {
        const { data } = await spectraApi.get('/api/v1/system/data-sources');
        const sources = data.sources || [];

        if (sources.length === 0) {
            container.innerHTML = '<span class="text-slate-500 text-sm">No data sources configured</span>';
            return;
        }

        container.innerHTML = sources.map(s => {
            const ready = s.status === 'ready';
            const stale = s.status === 'stale';
            const dot = ready ? 'bg-emerald-500' : stale ? 'bg-amber-500' : 'bg-slate-600';
            let statusHtml;
            if (ready || stale) {
                const size = s.size_bytes ? (s.size_bytes / 1024 / 1024).toFixed(1) + ' MB' : '';
                const label = stale ? '<span class="text-amber-400">Stale</span>' : '<span class="text-emerald-400">Ready</span>';
                const timeStr = s.last_updated ? new Date(s.last_updated * 1000).toLocaleDateString() : '';
                statusHtml = `${label} <span class="text-slate-600 ml-1">${size}${timeStr ? ' · ' + timeStr : ''}</span>`;
            } else if (s.status === 'on_demand') {
                statusHtml = '<span class="text-sky-400">On-demand</span>';
            } else {
                statusHtml = '<span class="text-slate-500">Not downloaded</span>';
            }
            return `<div class="flex items-center justify-between py-2 border-b border-white/5">
                <div class="flex items-center gap-2">
                    <div class="w-2 h-2 rounded-full ${dot}"></div>
                    <span class="text-sm text-white">${escapeHtml(s.name)}</span>
                </div>
                <div class="text-xs">${statusHtml}</div>
            </div>`;
        }).join('');
    } catch {
        container.innerHTML = '<span class="text-rose-400 text-sm">Failed to load data source status</span>';
    }
}

async function downloadDataSources() {
    const btn = document.getElementById('download-sources-btn');
    const status = document.getElementById('download-sources-status');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin mr-1"></i> Downloading...';
    status.textContent = 'This may take a minute...';
    try {
        const { data, error } = await spectraApi.post('/api/v1/system/data-sources/download');
        if (!error) {
            status.textContent = `Updated: ${data.stats?.cve_kb_entries || 0} CVEs, ${data.stats?.metasploit || 0} MSF modules`;
            status.className = 'text-xs text-emerald-400';
            loadDataSourceStatus();
        } else {
            status.textContent = 'Error: ' + (error.detail || 'Download failed');
            status.className = 'text-xs text-rose-400';
        }
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
        status.className = 'text-xs text-rose-400';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="download" class="w-4 h-4 inline-block mr-1"></i> Download / Update All Sources';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

loadDataSourceStatus();

// === VPN Management ===
async function loadVpnConfigs() {
    const container = document.getElementById('vpn-configs-list');
    try {
        const { data: configs, error } = await spectraApi.get('/api/v1/vpn/configs');
        if (error) { container.innerHTML = '<span class="text-slate-500 text-sm">No configs found</span>'; return; }
        if (!configs.length) { container.innerHTML = '<span class="text-slate-500 text-sm">No configs uploaded yet</span>'; return; }
        container.innerHTML = configs.map(c => `
            <div class="flex items-center justify-between p-3 rounded-lg bg-slate-900/50 border border-white/5">
                <div>
                    <span class="text-sm font-medium text-white">${escapeHtml(c.name)}</span>
                    <span class="ml-2 px-1.5 py-0.5 text-xs rounded bg-slate-700 text-slate-300">${escapeHtml(c.type)}</span>
                    <span class="ml-2 text-xs text-slate-500">${(c.size / 1024).toFixed(1)} KB</span>
                </div>
                <div class="flex gap-2">
                    <button data-vpn-name="${escapeHtml(c.name)}" onclick="vpnConnect(this.dataset.vpnName)" class="px-2 py-1 bg-emerald-700 hover:bg-emerald-600 text-white rounded text-xs transition-colors">Connect</button>
                    <button data-vpn-name="${escapeHtml(c.name)}" onclick="vpnDisconnect(this.dataset.vpnName)" class="px-2 py-1 bg-amber-700 hover:bg-amber-600 text-white rounded text-xs transition-colors">Disconnect</button>
                    <button data-vpn-name="${escapeHtml(c.name)}" onclick="vpnDelete(this.dataset.vpnName)" class="px-2 py-1 bg-rose-700 hover:bg-rose-600 text-white rounded text-xs transition-colors">Delete</button>
                </div>
            </div>
        `).join('');
    } catch (e) { container.innerHTML = '<span class="text-rose-400 text-sm">Failed to load</span>'; }
}

async function vpnConnect(name) {
    try {
        const { data, error } = await spectraApi.post(`/api/v1/vpn/connect/${encodeURIComponent(name)}`);
        if (!error) _spectraToast('VPN connect job queued: ' + data.job_id, 'success');
        else _spectraToast('Error: ' + (error.detail || 'Failed'), 'error');
    } catch (e) { _spectraToast('Error: ' + e.message, 'error'); }
}

async function vpnDisconnect(name) {
    try {
        const { data, error } = await spectraApi.post(`/api/v1/vpn/disconnect/${encodeURIComponent(name)}`);
        if (!error) _spectraToast('VPN disconnect job queued: ' + data.job_id, 'success');
        else _spectraToast('Error: ' + (error.detail || 'Failed'), 'error');
    } catch (e) { _spectraToast('Error: ' + e.message, 'error'); }
}

async function vpnDelete(name) {
    _spectraConfirm(`Delete VPN config "${name}"?`, async () => {
        try {
            const { error } = await spectraApi.delete(`/api/v1/vpn/configs/${encodeURIComponent(name)}`);
            if (!error) { loadVpnConfigs(); } else { _spectraToast('Error: ' + (error.detail || 'Failed'), 'error'); }
        } catch (e) { _spectraToast('Error: ' + e.message, 'error'); }
    }, { title: 'Delete VPN Config' });
}

async function testVpnConnection() {
    try {
        const { data, error } = await spectraApi.post('/api/v1/vpn/test');
        if (!error) _spectraToast('VPN test job queued: ' + data.job_id, 'success');
        else _spectraToast('Error: ' + (error.detail || 'Failed'), 'error');
    } catch (e) { _spectraToast('Error: ' + e.message, 'error'); }
}

document.getElementById('vpn-upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const fd = new FormData();
    fd.append('name', form.vpn_name.value);
    fd.append('vpn_type', form.vpn_type.value);
    fd.append('file', form.vpn_file.files[0]);
    try {
        const { data, error } = await spectraApi.post('/api/v1/vpn/configs', fd);
        if (!error) { _spectraToast('Config uploaded: ' + data.name, 'success'); form.reset(); loadVpnConfigs(); }
        else _spectraToast('Error: ' + (error.detail || 'Upload failed'), 'error');
    } catch (e) { _spectraToast('Error: ' + e.message, 'error'); }
});

async function loadVpnStatus() {
    const dot = document.getElementById('vpn-status-dot');
    const text = document.getElementById('vpn-status-text');
    try {
        const { error } = await spectraApi.get('/api/v1/vpn/status');
        if (!error) {
            text.textContent = 'Status check queued (runs in tools container)';
            dot.className = 'w-3 h-3 rounded-full bg-slate-500';
        } else {
            text.textContent = 'VPN status unavailable';
            dot.className = 'w-3 h-3 rounded-full bg-rose-500';
        }
    } catch {
        text.textContent = 'Could not reach API';
        dot.className = 'w-3 h-3 rounded-full bg-rose-500';
    }
}

loadVpnConfigs();
loadVpnStatus();

// === External Services Topology ===
let svcTopologyTimer = null;

async function loadServiceTopology() {
    const container = document.getElementById('svc-topology-cards');
    const refreshInfo = document.getElementById('svc-topology-refresh-info');
    try {
        const { data: topology, error } = await spectraApi.get('/api/v1/system/services/topology');
        if (error) throw new Error('Failed to fetch topology');
        const entries = Object.entries(topology);

        if (!entries.length) {
            container.innerHTML = '<div class="col-span-full text-center py-6 text-slate-500 text-sm">No services configured</div>';
            return;
        }

        const modeColors = { local: 'text-emerald-400', remote: 'text-sky-400' };
        const modeBg = { local: 'bg-emerald-500/10 border-emerald-500/20', remote: 'bg-sky-500/10 border-sky-500/20' };
        const modeIcon = { local: 'home', remote: 'cloud' };

        container.innerHTML = entries.map(([name, info]) => {
            const mode = info.mode || 'local';
            const url = info.url || '';
            const healthy = info.healthy;
            const dotClass = healthy === true ? 'bg-emerald-500' : healthy === false ? 'bg-rose-500' : 'bg-slate-500';
            const displayName = name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            return `<div class="rounded-xl border ${modeBg[mode] || 'bg-slate-900/50 border-white/10'} p-3">
                <div class="flex items-center justify-between mb-1.5">
                    <div class="flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full ${dotClass}"></span>
                        <span class="text-sm font-medium text-white">${escapeHtml(displayName)}</span>
                    </div>
                    <span class="text-xs uppercase tracking-wider font-semibold ${modeColors[mode] || 'text-slate-400'}">
                        <i data-lucide="${modeIcon[mode] || 'circle-help'}" class="w-3.5 h-3.5 inline-block mr-0.5"></i> ${escapeHtml(mode)}
                    </span>
                </div>
                ${url ? `<p class="text-[11px] text-slate-500 font-mono truncate" title="${escapeHtml(url)}">${escapeHtml(url)}</p>` : '<p class="text-[11px] text-slate-600">In-process</p>'}
            </div>`;
        }).join('');

        const localCount = entries.filter(([, i]) => i.mode === 'local').length;
        const remoteCount = entries.length - localCount;
        refreshInfo.textContent = `${localCount} local, ${remoteCount} remote \u00b7 last checked ${new Date().toLocaleTimeString()}`;
    } catch {
        container.innerHTML = '<div class="col-span-full text-center py-4 text-rose-400 text-sm"><i data-lucide="alert-circle" class="w-4 h-4 inline-block mr-1"></i> Failed to load service topology</div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

loadServiceTopology();
svcTopologyTimer = setInterval(loadServiceTopology, 60000);

// Expose functions used by HTML onclick handlers
window.clearToolStats = clearToolStats;
window.showClearMissionsConfirm = showClearMissionsConfirm;
window.hideClearMissionsConfirm = hideClearMissionsConfirm;
window.confirmClearMissions = confirmClearMissions;
window.clearCache = clearCache;
window.reinstallTools = reinstallTools;
window.downloadDataSources = downloadDataSources;
window.testVpnConnection = testVpnConnection;
window.vpnConnect = vpnConnect;
window.vpnDisconnect = vpnDisconnect;
window.vpnDelete = vpnDelete;
