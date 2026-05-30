async function loadTZConfig() {
    try {
        const { data, error } = await spectraApi.get('/api/settings');
        if (error) throw new Error(error);
        const s = data || {};
        const el = (id) => document.getElementById(id);
        if (el('tz-gateway-url')) el('tz-gateway-url').value = s.tensorzero_gateway_url || s.TENSORZERO_GATEWAY_URL || '';
        if (el('llm-timeout')) el('llm-timeout').value = s.llm_timeout || s.LLM_TIMEOUT || 600;
        if (el('llm-embedding')) el('llm-embedding').value = s.embedding_model || s.EMBEDDING_MODEL || 'local/BAAI/bge-small-en-v1.5';
        const { data: tzData } = await spectraApi.get('/api/v1/admin/tensorzero/config');
        if (tzData?.models) {
            for (const tier of ['fast', 'balanced', 'capable']) {
                const m = tzData.models[tier] || {};
                const primary = typeof m === 'string' ? m : (m.model || m.primary || '');
                const fallback = typeof m === 'string' ? '' : (m.fallback || '');
                if (el(`tz-model-${tier}`)) el(`tz-model-${tier}`).value = primary;
                if (el(`tz-model-${tier}-fallback`)) el(`tz-model-${tier}-fallback`).value = fallback;
            }
        }
        if (tzData?.provider_type && el('tz-provider-type')) el('tz-provider-type').value = tzData.provider_type;
    } catch(e) { console.error('Load AI config error', e); }
}

async function saveTZConfig() {
    const payload = {
        tensorzero_gateway_url: document.getElementById('tz-gateway-url')?.value || '',
        llm_timeout: parseFloat(document.getElementById('llm-timeout')?.value) || 600,
        embedding_model: document.getElementById('llm-embedding')?.value || '',
        embedding_api_key: document.getElementById('embedding-api-key')?.value || undefined,
    };
    try {
        const { error } = await spectraApi.post('/api/settings', payload);
        if (error) throw new Error(error);
    } catch(e) { showToast('Failed to save settings: ' + e.message, 'error'); return; }

    const modelPayload = {
        models: {
            fast: {
                primary: document.getElementById('tz-model-fast')?.value || '',
                fallback: document.getElementById('tz-model-fast-fallback')?.value || '',
            },
            balanced: {
                primary: document.getElementById('tz-model-balanced')?.value || '',
                fallback: document.getElementById('tz-model-balanced-fallback')?.value || '',
            },
            capable: {
                primary: document.getElementById('tz-model-capable')?.value || '',
                fallback: document.getElementById('tz-model-capable-fallback')?.value || '',
            },
        },
        provider_type: document.getElementById('tz-provider-type')?.value || 'deepseek',
    };
    try {
        const { data: tzSave, error } = await spectraApi.put('/api/v1/admin/tensorzero/config', modelPayload);
        if (error) showToast('Settings saved. Note: TZ config update failed — ' + error, 'warning');
        else showToast(tzSave?.message || 'Configuration saved and gateway restarted when possible.', 'success');
    } catch(e) { showToast('Settings saved but TZ update failed: ' + e.message, 'warning'); }
}

async function testTZConnection() {
    const result = document.getElementById('llm-test-result');
    result.classList.remove('hidden');
    result.className = 'mt-3 p-3 rounded-lg text-sm bg-blue-600/10 text-blue-300 border border-blue-500/30';
    result.textContent = 'Testing gateway connection...';
    try {
        const { data, error } = await spectraApi.get('/api/v1/admin/tensorzero/status');
        if (error || !data?.online) {
            result.className = 'mt-3 p-3 rounded-lg text-sm bg-red-600/10 text-red-300 border border-red-500/30';
            result.innerHTML = '<i data-lucide="x-circle" class="w-4 h-4 inline-block mr-1"></i> Gateway unreachable: ' + escapeHtml(error || 'Connection failed');
            if (typeof lucide !== 'undefined') lucide.createIcons();
        } else {
            result.className = 'mt-3 p-3 rounded-lg text-sm bg-emerald-600/10 text-emerald-300 border border-emerald-500/30';
            result.innerHTML = '<i data-lucide="check-circle" class="w-4 h-4 inline-block mr-1"></i> Gateway online &mdash; ' +
                (data.functions_count || 0) + ' functions, ' + (data.models_count || 0) + ' models configured';
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    } catch(e) {
        result.className = 'mt-3 p-3 rounded-lg text-sm bg-red-600/10 text-red-300 border border-red-500/30';
        result.textContent = '\u2717 Error: ' + e.message;
    }
}
