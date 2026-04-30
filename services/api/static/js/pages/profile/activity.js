async function loadActivity() {
    const container = document.getElementById('activity-log');
    try {
        const { data: events, error } = await spectraApi.get('/api/v1/auth/activity?limit=20');
        if (error) { container.innerHTML = '<p class="text-sm text-slate-500 text-center py-4">Activity log not available</p>'; return; }
        if (!events.length) {
            container.innerHTML = '<p class="text-sm text-slate-500 text-center py-6">No recent activity</p>';
            return;
        }
        container.innerHTML = events.map(ev => `
            <div class="activity-row">
                <div class="w-8 h-8 rounded-lg bg-slate-800 flex items-center justify-center shrink-0 mt-0.5">
                    <i data-lucide="${ev.event_type === 'login' ? 'log-in' : ev.event_type === 'logout' ? 'log-out' : 'info'}" class="w-3.5 h-3.5 inline-block text-slate-400"></i>
                </div>
                <div class="flex-1">
                    <div class="text-sm text-white">${escapeHtml(ev.event_type || ev.action || 'Event')}</div>
                    <div class="text-xs text-slate-500 mt-0.5">${new Date(ev.created_at || ev.timestamp).toLocaleString('en-US')}</div>
                </div>
            </div>
        `).join('');
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) { container.innerHTML = '<p class="text-sm text-slate-500 text-center py-4">Could not load activity</p>'; }
}

loadActivity();
