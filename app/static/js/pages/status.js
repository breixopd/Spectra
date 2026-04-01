/**
 * Status page — fetches health endpoint and renders service status.
 */

async function loadStatus() {
    const { data, error } = await spectraApi.get('/api/v1/system/public-status');
    if (error) {
        document.getElementById('services-list').innerHTML = '<p class="text-sm text-rose-400">Failed to load status</p>';
        return;
    }

    const services = [
        { name: 'API Server', key: 'api', icon: 'server' },
        { name: 'Database', key: 'database', icon: 'database' },
        { name: 'AI Service', key: 'ai', icon: 'brain' },
        { name: 'Worker', key: 'worker', icon: 'cog' },
        { name: 'Scheduler', key: 'scheduler', icon: 'clock' },
    ];

    const list = document.getElementById('services-list');
    let allHealthy = true;

    list.innerHTML = services.map(svc => {
        const status = data[svc.key] || data.services?.[svc.key] || 'unknown';
        const isUp = status === 'healthy' || status === 'running' || status === true || status === 'ok';
        if (!isUp) allHealthy = false;
        const color = isUp ? 'text-emerald-400' : 'text-rose-400';
        const bg = isUp ? 'bg-emerald-500/15' : 'bg-rose-500/15';
        const label = isUp ? 'Operational' : 'Degraded';
        return `
        <div class="flex items-center justify-between p-3 rounded-lg bg-black/20 border border-white/5">
            <div class="flex items-center gap-3">
                <i data-lucide="${svc.icon}" class="w-5 h-5 ${color}"></i>
                <span class="text-sm text-white font-medium">${svc.name}</span>
            </div>
            <span class="px-2 py-0.5 rounded text-xs font-semibold ${color} ${bg}">${label}</span>
        </div>`;
    }).join('');

    if (typeof lucide !== 'undefined') lucide.createIcons();

    const overall = document.getElementById('overall-status');
    if (allHealthy) {
        overall.className = 'px-3 py-1 rounded-full text-sm font-medium bg-emerald-500/15 text-emerald-400';
        overall.textContent = 'All Systems Operational';
    } else {
        overall.className = 'px-3 py-1 rounded-full text-sm font-medium bg-amber-500/15 text-amber-400';
        overall.textContent = 'Partial Outage';
    }

    // System info
    const info = document.getElementById('system-info');
    const version = data.version || data.app_version || '—';
    const uptime = data.uptime || '—';
    info.innerHTML = `
        <div class="text-center p-3 rounded-lg bg-black/20">
            <p class="text-xs text-slate-500 mb-1">Version</p>
            <p class="text-sm text-white font-mono">${escapeHtml(String(version))}</p>
        </div>
        <div class="text-center p-3 rounded-lg bg-black/20">
            <p class="text-xs text-slate-500 mb-1">Uptime</p>
            <p class="text-sm text-white">${escapeHtml(String(uptime))}</p>
        </div>
    `;
}

loadStatus();
// Auto-refresh every 30 seconds
const statusRefreshIntervalId = window.setInterval(loadStatus, 30000);

function cleanupStatusPageState() {
    window.clearInterval(statusRefreshIntervalId);
}

window.addEventListener('pagehide', cleanupStatusPageState, { once: true });
window.addEventListener('beforeunload', cleanupStatusPageState, { once: true });
