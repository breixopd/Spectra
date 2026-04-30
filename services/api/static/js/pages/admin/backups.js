async function loadBackups() {
    const tbody = document.getElementById('backups-tbody');
    try {
        const r = await spectraApi.get('/api/admin/backups');
        if (r.error) throw new Error(r.error);
        const data = r.data;
        const backups = data.backups || data || [];
        if (!backups.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="px-4 py-8 text-center text-slate-600 text-sm">No backups yet. Click "Create Backup" to start.</td></tr>';
            return;
        }
        tbody.innerHTML = backups.map(b => `
            <tr class="border-b border-white/5 hover:bg-white/[0.02]">
                <td class="px-4 py-3 font-mono text-xs text-slate-300">${b.filename || b.path?.split('/').pop() || '—'}</td>
                <td class="px-4 py-3 text-xs text-slate-400">${b.size ? formatBytes(b.size) : '—'}</td>
                <td class="px-4 py-3 text-xs text-slate-400">${b.created_at ? new Date(b.created_at).toLocaleString('en-US') : '—'}</td>
                <td class="px-4 py-3 text-right">
                    <button data-action="restoreBackup" data-value="${b.path || b.filename}" class="px-2.5 py-1 rounded bg-amber-600/20 text-amber-300 text-xs hover:bg-amber-600/30 transition-colors">
                        <i data-lucide="rotate-ccw" class="w-3.5 h-3.5 inline-block mr-1"></i>Restore
                    </button>
                </td>
            </tr>
        `).join('');
    } catch(e) { tbody.innerHTML = '<tr><td colspan="4" class="px-4 py-8 text-center text-red-400 text-sm">Failed to load backups</td></tr>'; }
}

async function createBackup() {
    const btn = document.getElementById('backup-create-btn');
    btn.disabled = true; btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin mr-1.5"></i> Creating...';
    try {
        const r = await spectraApi.post('/api/admin/backups');
        if (r.error) throw new Error(r.error);
        showConfirm('Backup created successfully', null, {title:'Success', icon:'check', confirmText:'OK', hideCancel:true});
        loadBackups();
    } catch(e) { showConfirm(e.message, null, {title:'Backup Error', icon:'triangle-exclamation', confirmText:'OK', hideCancel:true}); }
    finally { btn.disabled = false; btn.innerHTML = '<i data-lucide="plus" class="w-4 h-4 inline-block mr-1.5"></i> Create Backup'; if (typeof lucide !== 'undefined') lucide.createIcons(); }
}

function restoreBackup(path) {
    showConfirm('Are you sure you want to restore from this backup? This will overwrite the current database.', async () => {
        try {
            const r = await spectraApi.post('/api/admin/backups/restore', {backup_path:path});
            if (r.error) throw new Error(r.error);
            showConfirm('Database restored. The app will restart.', ()=>window.location.reload(), {title:'Restored', icon:'check', confirmText:'OK', hideCancel:true});
        } catch(e) { showConfirm(e.message, null, {title:'Restore Error', icon:'triangle-exclamation', confirmText:'OK', hideCancel:true}); }
    }, {title:'Restore Backup', icon:'triangle-exclamation'});
}
