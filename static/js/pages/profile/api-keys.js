async function loadApiKeys() {
    const container = document.getElementById('api-keys-list');
    try {
        const { data: keys, error } = await spectraApi.get('/api/v1/auth/api-keys');
        if (error) { container.innerHTML = '<p class="text-sm text-slate-500 text-center py-4">API keys not available</p>'; return; }
        if (!keys.length) {
            container.innerHTML = '<p class="text-sm text-slate-500 text-center py-6">No API keys yet. Generate one to get started.</p>';
            return;
        }
        container.innerHTML = keys.map(k => `
            <div class="key-row">
                <div class="flex-1 min-w-0">
                    <div class="text-sm font-mono text-white truncate">${escapeHtml(k.prefix || k.key_prefix || '****')}...</div>
                    <div class="text-xs text-slate-500 mt-0.5">Created ${new Date(k.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</div>
                </div>
                <button data-action="revokeApiKey" data-value="${escapeHtml(k.id)}" class="px-2 py-1 text-xs text-rose-400 hover:bg-rose-500/10 rounded transition-colors">Revoke</button>
            </div>
        `).join('');
    } catch (e) { container.innerHTML = '<p class="text-sm text-slate-500 text-center py-4">Could not load API keys</p>'; }
}

async function generateApiKey() {
    _spectraConfirm('Generate a new API key? Your current key will be invalidated.', async () => {
    try {
        const { data, error } = await spectraApi.post('/api/v1/auth/api-keys');
        if (!error) {
            _spectraToast('API key generated — copy it now, it won\'t be shown again');
            if (data.key) {
                const container = document.getElementById('api-keys-list');
                container.insertAdjacentHTML('afterbegin', `
                    <div class="key-row" style="border-color:rgba(16,185,129,0.3);background:rgba(16,185,129,0.05);">
                        <div class="flex-1 min-w-0">
                            <div class="text-sm font-mono text-emerald-400 break-all select-all">${escapeHtml(data.key)}</div>
                            <div class="text-xs text-emerald-500/60 mt-0.5">New key — copy now</div>
                        </div>
                    </div>
                `);
            }
            setTimeout(loadApiKeys, 5000);
        } else _spectraToast('Failed to generate key', 'error');
    } catch (e) { _spectraToast('Network error', 'error'); }
    }, { title: 'Generate API Key' });
}

async function revokeApiKey(keyId) {
    _spectraConfirm('Revoke this API key? This cannot be undone.', async () => {
        try {
            const { error } = await spectraApi.delete(`/api/v1/auth/api-keys/${keyId}`);
            if (!error) { _spectraToast('API key revoked'); loadApiKeys(); }
            else _spectraToast('Failed to revoke key', 'error');
        } catch (e) { _spectraToast('Network error', 'error'); }
    }, { title: 'Revoke API Key' });
}

loadApiKeys();

window.generateApiKey = generateApiKey;
window.revokeApiKey = revokeApiKey;
