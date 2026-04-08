// Settings — Data Management (clear tools/missions/cache, reinstall, data sources)
// Loaded before settings.js; depends on escapeHtml(), spectraApi, _spectraToast, _spectraConfirm, showSharedModal, closeSharedModal

async function clearToolStats() {
    _spectraConfirm('Clear all tool statistics?', async () => {
        try {
            const { data, error } = await spectraApi.post('/api/v1/system/clear/tools');
            if (!error) {
                _spectraToast(`Cleared ${data.cleared_count || 0} tool stat entries`, 'success');
            } else {
                _spectraToast('Error: ' + (error || 'Failed to clear'), 'error');
            }
        } catch (e) {
            _spectraToast('Error: ' + e.message, 'error');
        }
    }, { title: 'Clear Tool Statistics' });
}

function showClearMissionsConfirm() {
    showSharedModal('clear-missions-modal');
}

function hideClearMissionsConfirm() {
    closeSharedModal('clear-missions-modal');
}

async function confirmClearMissions() {
    hideClearMissionsConfirm();
    try {
        const { data, error } = await spectraApi.post('/api/v1/system/clear/missions', { confirm: true });
        if (!error) {
            _spectraToast(`Deleted ${data.cleared_count || 0} missions`, 'success');
        } else {
            _spectraToast('Error: ' + (error || 'Failed to clear'), 'error');
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
                _spectraToast('Error: ' + (error || 'Failed to clear'), 'error');
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
                _spectraToast('Error: ' + (error || 'Failed to queue'), 'error');
            }
        } catch (e) {
            _spectraToast('Error: ' + e.message, 'error');
        }
    }, { title: 'Reinstall Tools' });
}

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
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        container.innerHTML = '<span class="text-rose-400">Failed to load status</span>';
    }
}

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
            status.textContent = 'Error: ' + (error || 'Download failed');
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

document.addEventListener('DOMContentLoaded', () => {
    loadSystemStatus();
    const dataStatusInterval = setInterval(loadSystemStatus, 10000);
    loadDataSourceStatus();

    window.addEventListener('pagehide', () => {
        clearInterval(dataStatusInterval);
    });
});
