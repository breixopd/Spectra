async function loadTZStatus() {
    const { data, error } = await spectraApi.get('/api/v1/admin/tensorzero/status');
    const badge = document.getElementById('tz-status-badge');
    if (error || !data) {
        badge.className = 'px-2 py-0.5 text-xs font-semibold rounded-full bg-rose-500/15 text-rose-400';
        badge.textContent = 'Offline';
        return;
    }
    badge.className = 'px-2 py-0.5 text-xs font-semibold rounded-full bg-emerald-500/15 text-emerald-400';
    badge.textContent = 'Online';

    document.getElementById('tz-endpoint').textContent = data.gateway_url || '—';
    document.getElementById('tz-functions-count').textContent = data.functions_count ?? '—';
    document.getElementById('tz-models-count').textContent = data.models_count ?? '—';
    document.getElementById('tz-metrics-count').textContent = data.metrics_count ?? '—';

    const dashLink = document.getElementById('tz-dashboard-link');
    if (data.dashboard_url) dashLink.href = data.dashboard_url;
}

async function loadTZInferences() {
    const { data, error } = await spectraApi.get('/api/v1/admin/tensorzero/inferences?limit=20');
    const container = document.getElementById('tz-inferences-list');
    if (error || !data?.inferences) {
        container.innerHTML = '<p class="text-sm text-slate-500">No recent inferences</p>';
        return;
    }
    container.innerHTML = data.inferences.map(inf => `
        <div class="flex items-center justify-between p-2 rounded-lg bg-black/20 border border-white/5 text-xs">
            <div class="flex items-center gap-2">
                <span class="text-violet-400 font-mono">${escapeHtml(inf.function_name)}</span>
                <span class="text-slate-500">${escapeHtml(inf.variant_name || '')}</span>
            </div>
            <div class="flex items-center gap-3">
                <span class="text-slate-400">${inf.input_tokens ?? 0}+${inf.output_tokens ?? 0} tok</span>
                <span class="text-slate-500">${inf.duration_ms ? inf.duration_ms.toFixed(0) + 'ms' : '—'}</span>
            </div>
        </div>
    `).join('');
}

async function loadTZFunctionStats() {
    const { data, error } = await spectraApi.get('/api/v1/admin/tensorzero/functions');
    const container = document.getElementById('tz-function-stats');
    if (error || !data?.functions) {
        container.innerHTML = '<p class="text-sm text-slate-500">Function stats unavailable</p>';
        return;
    }
    container.innerHTML = data.functions.map(fn => `
        <div class="flex items-center justify-between p-2 rounded-lg bg-black/20 border border-white/5 text-xs">
            <span class="text-white font-medium">${escapeHtml(fn.name)}</span>
            <div class="flex items-center gap-3">
                <span class="text-slate-400">${fn.variant_count ?? 0} variant${fn.variant_count !== 1 ? 's' : ''}</span>
                <span class="px-1.5 py-0.5 rounded text-xs ${fn.type === 'chat' ? 'bg-violet-500/15 text-violet-400' : 'bg-cyan-500/15 text-cyan-400'}">${escapeHtml(fn.type)}</span>
            </div>
        </div>
    `).join('');
}
