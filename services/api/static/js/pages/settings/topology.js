// Settings — External Services Topology
// Loaded before settings.js; depends on escapeHtml(), spectraApi

var svcTopologyTimer = null;

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
        refreshInfo.textContent = `${localCount} local, ${remoteCount} remote \u00b7 last checked ${new Date().toLocaleTimeString('en-US')}`;

        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch {
        container.innerHTML = '<div class="col-span-full text-center py-4 text-rose-400 text-sm"><i data-lucide="alert-circle" class="w-4 h-4 inline-block mr-1"></i> Failed to load service topology</div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadServiceTopology();
    svcTopologyTimer = setInterval(loadServiceTopology, 60000);

    window.addEventListener('pagehide', () => {
        clearInterval(svcTopologyTimer);
    });
});
