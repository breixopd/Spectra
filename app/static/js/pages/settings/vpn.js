// Settings — VPN Management
// Loaded before settings.js; depends on escapeHtml(), spectraApi, _spectraToast, _spectraConfirm

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
        else _spectraToast('Error: ' + (error || 'Failed'), 'error');
    } catch (e) { _spectraToast('Error: ' + e.message, 'error'); }
}

async function vpnDisconnect(name) {
    try {
        const { data, error } = await spectraApi.post(`/api/v1/vpn/disconnect/${encodeURIComponent(name)}`);
        if (!error) _spectraToast('VPN disconnect job queued: ' + data.job_id, 'success');
        else _spectraToast('Error: ' + (error || 'Failed'), 'error');
    } catch (e) { _spectraToast('Error: ' + e.message, 'error'); }
}

async function vpnDelete(name) {
    _spectraConfirm(`Delete VPN config "${name}"?`, async () => {
        try {
            const { error } = await spectraApi.delete(`/api/v1/vpn/configs/${encodeURIComponent(name)}`);
            if (!error) { loadVpnConfigs(); } else { _spectraToast('Error: ' + (error || 'Failed'), 'error'); }
        } catch (e) { _spectraToast('Error: ' + e.message, 'error'); }
    }, { title: 'Delete VPN Config' });
}

async function testVpnConnection() {
    try {
        const { data, error } = await spectraApi.post('/api/v1/vpn/test');
        if (!error) _spectraToast('VPN test job queued: ' + data.job_id, 'success');
        else _spectraToast('Error: ' + (error || 'Failed'), 'error');
    } catch (e) { _spectraToast('Error: ' + e.message, 'error'); }
}

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

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('vpn-upload-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const fd = new FormData();
        fd.append('name', form.vpn_name.value);
        fd.append('vpn_type', form.vpn_type.value);
        fd.append('file', form.vpn_file.files[0]);
        try {
            const { data, error } = await spectraApi.post('/api/v1/vpn/configs', fd);
            if (!error) { _spectraToast('Config uploaded: ' + data.name, 'success'); form.reset(); loadVpnConfigs(); }
            else _spectraToast('Error: ' + (error || 'Upload failed'), 'error');
        } catch (e) { _spectraToast('Error: ' + e.message, 'error'); }
    });

    loadVpnConfigs();
    loadVpnStatus();
});
