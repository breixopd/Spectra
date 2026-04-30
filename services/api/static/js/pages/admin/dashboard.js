function resetDashboardStats(message) {
    ['stat-total-users', 'stat-active-users', 'stat-total-plans', 'stat-total-missions'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.textContent = '—';
    });

    const rb = document.getElementById('roles-breakdown');
    if (rb) {
        rb.innerHTML = `
            <div class="rounded-lg border border-rose-500/20 bg-rose-500/10 px-4 py-3">
                <p class="text-sm font-medium text-rose-300">Dashboard stats are unavailable.</p>
                <p class="mt-1 text-xs text-slate-400">${escapeHtml(message)}</p>
            </div>`;
    }
}

function clearDashboardStatsError() {
    statsErrorVisible = false;
}


// ---- Dashboard ----
async function loadStats() {
    try {
        const { data: d, error } = await spectraApi.get('/api/admin/stats');
        if (error) throw new Error(error);
        clearDashboardStatsError();
        document.getElementById('stat-total-users').textContent = d.total_users;
        document.getElementById('stat-active-users').textContent = d.active_users;
        document.getElementById('stat-total-plans').textContent = d.total_plans;
        document.getElementById('stat-total-missions').textContent = d.total_missions;

        const rb = document.getElementById('roles-breakdown');
        rb.innerHTML = '';
        const total = d.total_users || 1;
        for (const [role, count] of Object.entries(d.role_counts || {})) {
            const pct = Math.round(count / total * 100);
            const roleBadgeClass = getUserRoleBadgeClass(role);
            const roleLabel = getUserRoleLabel(role);
            rb.innerHTML += `
                <div class="flex items-center justify-between text-sm">
                    <span class="badge ${roleBadgeClass}">${roleLabel}</span>
                    <span class="text-slate-400">${count} (${pct}%)</span>
                </div>
                <div class="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div class="h-full rounded-full ${role === 'admin' ? 'bg-red-500' : role === 'operator' ? 'bg-blue-500' : 'bg-slate-500'}" style="width:${pct}%"></div>
                </div>`;
        }
        if (!Object.keys(d.role_counts || {}).length) {
            rb.innerHTML = '<p class="text-sm text-slate-500">No role distribution data available.</p>';
        }
        // Also refresh dashboard health widget
        loadDashboardHealth();
    } catch(e) {
        console.error(e);
        const message = e.message || 'Could not load dashboard stats.';
        resetDashboardStats(message);
        if (!statsErrorVisible && typeof _spectraToast === 'function') {
            _spectraToast(`Failed to load dashboard stats: ${message}`, 'error');
            statsErrorVisible = true;
        }
    }
}

async function loadDashboardHealth() {
    try {
        const { data, error } = await spectraApi.get('/api/admin/scaling/metrics');
        if (error) return;
        const services = data.services || {};
        const allHealthy = Object.values(services).every(s => s.healthy && s.failed_tasks === 0);
        const running = Object.values(services).reduce((a, s) => a + (s.running_tasks ?? s.replicas ?? 0), 0);
        const desired = Object.values(services).reduce((a, s) => a + (s.desired_replicas ?? 0), 0);
        const dot = document.getElementById('dash-health-dot');
        const label = document.getElementById('dash-health-label');
        const detail = document.getElementById('dash-health-detail');
        if (dot) dot.className = `inline-block w-3 h-3 rounded-full ${allHealthy ? 'bg-emerald-500' : 'bg-rose-500'}`;
        if (label) label.textContent = allHealthy ? 'All services healthy' : 'Issues detected';
        if (detail) detail.textContent = `${running}/${desired} tasks running · CPU ${data.system?.cpu_percent ?? '—'}% · Mem ${data.system?.memory_percent ?? '—'}%`;
    } catch (e) { /* silent */ }
}

