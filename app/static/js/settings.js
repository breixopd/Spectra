function authHeaders(extra = {}) {
    const token = localStorage.getItem('token');
    return {
        ...extra,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
}

function defaultModelFor(provider) {
    if (provider === 'litellm') return 'gpt-4o-mini';
    return 'qwen2.5:3b';
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
    document.querySelectorAll('nav a').forEach((link) => {
        const isActive = link.getAttribute('href') === `#${targetId}`;
        link.classList.toggle('bg-white/5', isActive);
        link.classList.toggle('text-white', isActive);
        link.classList.toggle('text-slate-400', !isActive);
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
    const sourceOllamaHost = document.querySelector(`[name="${sourcePrefix}_ollama_host"]`)?.value;
    if (sourceApiBaseUrl !== undefined) {
        setFieldValue(`${targetPrefix}_api_base_url`, sourceApiBaseUrl);
    }
    if (sourceOllamaHost !== undefined) {
        setFieldValue(`${targetPrefix}_ollama_host`, sourceOllamaHost);
    }
}

function toggleProfileFields(prefix) {
    const provider = document.querySelector(`[name="${prefix}_provider"]`)?.value;
    const apiFields = document.querySelector(`.profile-api-fields[data-profile="${prefix}"]`);
    const ollamaFields = document.querySelector(`.profile-ollama-fields[data-profile="${prefix}"]`);
    if (apiFields) {
        apiFields.classList.toggle('hidden', provider !== 'litellm');
    }
    if (ollamaFields) {
        ollamaFields.classList.toggle('hidden', provider !== 'ollama');
    }
    const modelField = document.querySelector(`[name="${prefix}_model"]`);
    if (modelField && !modelField.value.trim()) {
        modelField.value = defaultModelFor(provider);
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
    row.querySelector('.fallback-api-fields').classList.toggle('hidden', provider !== 'litellm');
    row.querySelector('.fallback-ollama-fields').classList.toggle('hidden', provider !== 'ollama');
    const modelField = row.querySelector('.fallback-model');
    if (!modelField.value.trim()) {
        modelField.value = defaultModelFor(provider);
    }
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
        row.querySelector('.fallback-ollama-host').value = profile.base_url || '';
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
    if (provider === 'ollama') {
        const host = document.querySelector(`[name="${prefix}_ollama_host"]`)?.value.trim();
        if (host) profile.base_url = host;
    }
    if (provider === 'litellm') {
        const baseUrl = document.querySelector(`[name="${prefix}_api_base_url"]`)?.value.trim();
        const apiKey = document.querySelector(`[name="${prefix}_api_key"]`)?.value.trim();
        if (baseUrl) profile.base_url = baseUrl;
        if (apiKey) profile.api_key = apiKey;
    }
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
        if (provider === 'ollama') {
            const host = row.querySelector('.fallback-ollama-host').value.trim();
            if (host) profile.base_url = host;
        }
        if (provider === 'litellm') {
            const baseUrl = row.querySelector('.fallback-api-base-url').value.trim();
            const apiKey = row.querySelector('.fallback-api-key').value.trim();
            if (baseUrl) profile.base_url = baseUrl;
            if (apiKey) profile.api_key = apiKey;
        }
        profiles[profileId] = profile;
        chain.push(profileId);
    });
    return { profiles, chain };
}

function populateProfile(prefix, profile) {
    if (!profile) return;
    setFieldValue(`${prefix}_provider`, profile.provider);
    setFieldValue(`${prefix}_model`, profile.model);
    if (profile.provider === 'ollama') {
        setFieldValue(`${prefix}_ollama_host`, profile.base_url);
    } else {
        setFieldValue(`${prefix}_api_base_url`, profile.base_url);
    }
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
        provider_profiles: { default: collectProfile('default') },
        provider_routing: { default: 'default' },
        log_level: document.querySelector('[name="log_level"]').value,
        plugin_safe_mode: document.querySelector('[name="plugin_safe_mode"]').checked,
        connect_back_host: document.querySelector('[name="connect_back_host"]').value.trim(),
        require_approval: document.querySelector('[name="require_approval"]').checked,
        notification_webhook: document.querySelector('[name="notification_webhook"]').value.trim(),
        embedding_model: document.querySelector('[name="embedding_model"]').value.trim() || null,
    };

    ['tier1', 'tier2', 'tier3'].forEach((tier) => {
        if (!document.querySelector(`.tier-toggle[data-tier="${tier}"]`).checked) {
            return;
        }
        const profileId = document.querySelector(`[name="${tier}_profile_id"]`).value || tier;
        payload.provider_profiles[profileId] = collectProfile(tier);
        payload.provider_routing[tier] = profileId;
    });

    const fallbackData = collectFallbackProfiles();
    Object.assign(payload.provider_profiles, fallbackData.profiles);
    payload.provider_fallbacks = { default: fallbackData.chain };

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
    const profiles = data.provider_profiles || {};
    const routing = data.provider_routing || {};
    const fallbacks = data.provider_fallbacks || {};
    const defaultProfileId = routing.default || data.resolved_ai?.default_profile || 'default';
    const defaultProfile = profiles[defaultProfileId] || profiles.default;

    populateProfile('default', defaultProfile);
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

    ['tier1', 'tier2', 'tier3'].forEach((tier) => {
        const routeId = routing[tier];
        const enabled = !!routeId && routeId !== defaultProfileId;
        document.querySelector(`.tier-toggle[data-tier="${tier}"]`).checked = enabled;
        toggleTierFields(tier);
        if (enabled) {
            document.querySelector(`[name="${tier}_profile_id"]`).value = routeId;
            populateProfile(tier, profiles[routeId]);
        }
    });

    const fallbackContainer = document.getElementById('fallback-profiles');
    fallbackContainer.innerHTML = '';
    (fallbacks.default || []).forEach((profileId) => {
        addFallbackRow({ id: profileId, ...(profiles[profileId] || {}) });
    });
    renderResolvedSummary(data.resolved_ai);
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
        alert('Settings saved successfully.');
    } catch (error) {
        console.error('Error saving settings:', error);
        alert(error.message || 'Failed to save settings');
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
        const profile = collectProfile('default');
        const { data: result, error: testError } = await spectraApi.post('/test-llm', {
            provider: profile.provider,
            model: profile.model,
            api_key: profile.api_key || null,
            base_url: profile.base_url || null,
            ollama_host: profile.base_url || null,
        });
        if (testError || !result?.success) {
            throw new Error(testError || result?.error || 'Connection test failed');
        }
        alert('Default profile is reachable.');
    } catch (error) {
        console.error('Default profile test failed:', error);
        alert(error.message || 'Connection test failed');
    } finally {
        button.disabled = false;
        button.textContent = originalText;
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    document.querySelectorAll('nav a').forEach((anchor) => {
        anchor.addEventListener('click', function (event) {
            event.preventDefault();
            const targetId = this.getAttribute('href')?.replace('#', '');
            const target = targetId ? document.getElementById(targetId) : null;
            if (target) {
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                activateNavLink(targetId);
            }
        });
    });
    activateNavLink('general');

    document.querySelectorAll('.profile-provider').forEach((select) => {
        select.addEventListener('change', () => toggleProfileFields(select.dataset.profilePrefix));
        toggleProfileFields(select.dataset.profilePrefix);
    });
    document.querySelectorAll('.tier-toggle').forEach((checkbox) => {
        checkbox.addEventListener('change', () => toggleTierFields(checkbox.dataset.tier));
    });
    document.getElementById('toggle-advanced-routing')?.addEventListener('click', () => {
        const section = document.getElementById('advanced-routing-section');
        const chevron = document.getElementById('advanced-routing-chevron');
        section.classList.toggle('hidden');
        chevron.classList.toggle('rotate-90');
    });
    document.getElementById('add-fallback-profile')?.addEventListener('click', () => addFallbackRow());
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
        alert('Failed to load settings. Refresh the page after logging in again if the problem persists.');
    }
});
