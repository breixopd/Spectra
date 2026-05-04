async function loadRollbackSnapshots() {
    const container = document.getElementById('rollback-list');
    if (!container) return;
    try {
        const { data, error } = await spectraApi.get('/api/admin/rollback/snapshots');
        if (error) throw new Error(error);
        if (!data || data.length === 0) {
            container.innerHTML = '<p class="text-sm text-slate-500 text-center py-8">No reversible actions yet.</p>';
            return;
        }
        container.innerHTML = data.map(s => `
            <div class="flex items-center justify-between p-3 rounded-lg bg-black/20 border border-white/5">
                <div class="flex items-center gap-3 min-w-0">
                    <i data-lucide="undo-2" class="w-4 h-4 shrink-0 text-slate-400"></i>
                    <div class="min-w-0">
                        <p class="text-sm text-white truncate">${escapeHtml(s.action)}</p>
                        <p class="text-xs text-slate-500">${escapeHtml(s.entity_type)} &middot; ${new Date(s.created_at).toLocaleString('en-US')}</p>
                        ${s.restorable === false ? `<p class="text-xs text-amber-300 mt-1">${escapeHtml(s.restore_error || 'This snapshot cannot be restored automatically.')}</p>` : ''}
                    </div>
                </div>
                ${s.restorable === false
                    ? `<span class="ml-4 px-3 py-1.5 text-xs bg-slate-800/80 text-slate-400 rounded-lg border border-white/10 whitespace-nowrap">Not restorable</span>`
                    : `<button data-action="performRollback" data-value="${s.id}" class="ml-4 px-3 py-1.5 text-xs bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 rounded-lg border border-amber-500/30 transition-colors whitespace-nowrap flex items-center gap-1.5">
                        <i data-lucide="rotate-ccw" class="w-3 h-3 inline-block"></i> Revert
                    </button>`}
            </div>
        `).join('');
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch(e) { console.error(e); showToast('Error loading rollback snapshots', 'error'); }
}

async function performRollback(snapshotId) {
    showConfirm(
        'Confirm Rollback',
        'This will revert the action. The entity will be restored to its previous state. Are you sure?',
        async () => {
            try {
                const { data, error } = await spectraApi.post(`/api/admin/rollback/snapshots/${snapshotId}/rollback`, {});
                if (error) throw new Error(error);
                showToast('Action reverted successfully', 'success');
                loadRollbackSnapshots();
            } catch(e) { showToast('Rollback failed: ' + e.message, 'error'); }
        }
    );
}
