function updateShellList() {
    const container = document.getElementById('shell-list');
    if (!container) return;

    spectraApi.get('/api/v1/shell/sessions')
        .then(({ data: sessions, error }) => {
            if (error || !sessions) { sessions = []; }
            container.innerHTML = '';
            if (sessions.length === 0) {
                container.innerHTML = '<div class="text-center text-slate-600 text-xs py-4">No active sessions</div>';
                return;
            }

            sessions.forEach(session => {
                const el = document.createElement('div');
                el.className = 'bg-slate-800/50 border border-white/5 rounded p-2 flex items-center justify-between group hover:border-emerald-500/30 transition-colors';
                el.innerHTML = `
                    <div class="flex items-center space-x-2 overflow-hidden">
                        <div class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></div>
                        <div class="flex flex-col">
                            <span class="text-xs text-slate-300 font-mono truncate" title="${escapeHtml(session.id)}">${escapeHtml(session.target)}</span>
                            <span class="text-xs text-slate-500">ID: ${escapeHtml(session.id.substring(0, 8))}...</span>
                        </div>
                    </div>
                    <button data-shell-id="${escapeHtml(session.id)}" class="px-2 py-1 bg-emerald-500/10 text-emerald-400 text-xs rounded hover:bg-emerald-500/20 transition-colors border border-emerald-500/20">
                        CONNECT
                    </button>
                `;
                container.appendChild(el);
            });
        })
        .catch(() => {
            if (container) container.innerHTML = '<div class="text-center text-slate-600 text-xs py-4">No active sessions</div>';
        });

}

function connectShell(sessionId) {
    window.open(`/shell/${sessionId}`, '_blank', 'width=800,height=600');
}

// Delegated click handler for shell connect buttons
document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-shell-id]');
    if (btn) connectShell(btn.dataset.shellId);
});

// Poll for shell updates every 5 seconds — only when a mission is active
const shellListPollingInterval = window.setInterval(() => {
    if (currentMissionId) {
        updateShellList();
    }
}, 5000);

function cleanupDashboardPageState() {
    window.clearInterval(shellListPollingInterval);
    document.removeEventListener('spectra:ws-message', handleDashboardSocketMessageEvent);
}

window.addEventListener('pagehide', cleanupDashboardPageState, { once: true });
window.addEventListener('beforeunload', cleanupDashboardPageState, { once: true });
