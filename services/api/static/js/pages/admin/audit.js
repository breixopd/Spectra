async function loadAuditLogs() {
    const evtType = document.getElementById('audit-event-filter').value;
    const dateFrom = document.getElementById('audit-date-from').value;
    const dateTo = document.getElementById('audit-date-to').value;
    const params = new URLSearchParams({ page: auditPage, per_page: auditPerPage });
    if (evtType) params.set('event_type', evtType);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);

    try {
        const { data: d, error } = await spectraApi.get('/api/admin/audit-logs?' + params);
        if (error) throw new Error(error);
        const tbody = document.getElementById('audit-tbody');
        if (!d.items.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center py-8 text-slate-500">No audit events</td></tr>';
        } else {
            tbody.innerHTML = d.items.map(e => {
                let details = e.details || '';
                try { details = typeof details === 'string' ? details : JSON.stringify(details); } catch(ex) {}
                if (details.length > 100) details = details.substring(0, 100) + '…';
                return `
                <tr class="border-b border-white/5">
                    <td class="px-4 py-3 text-xs text-slate-400 whitespace-nowrap">${formatDateTime(e.created_at)}</td>
                    <td class="px-4 py-3"><span class="badge bg-slate-700/50 text-slate-300">${escapeHtml(e.event_type)}</span></td>
                    <td class="px-4 py-3 text-sm text-slate-400 max-w-xs truncate">${escapeHtml(details)}</td>
                    <td class="px-4 py-3 text-xs text-slate-500 font-mono">${escapeHtml(e.ip_address) || '—'}</td>
                </tr>`;
            }).join('');
        }

        const totalPages = Math.ceil(d.total / d.per_page) || 1;
        document.getElementById('audit-info').textContent = `${d.total} event${d.total !== 1 ? 's' : ''}`;
        document.getElementById('audit-page-num').textContent = d.page + ' / ' + totalPages;
        document.getElementById('audit-prev').disabled = d.page <= 1;
        document.getElementById('audit-next').disabled = d.page >= totalPages;
    } catch(e) { console.error(e); showToast('Error loading audit logs', 'error'); }
}

document.getElementById('audit-prev').addEventListener('click', () => { auditPage--; loadAuditLogs(); });
document.getElementById('audit-next').addEventListener('click', () => { auditPage++; loadAuditLogs(); });
document.getElementById('audit-event-filter').addEventListener('change', () => { auditPage = 1; loadAuditLogs(); });
document.getElementById('audit-date-from').addEventListener('change', () => { auditPage = 1; loadAuditLogs(); });
document.getElementById('audit-date-to').addEventListener('change', () => { auditPage = 1; loadAuditLogs(); });

function exportAuditLogsCSV() {
    const rows = document.querySelectorAll('#audit-tbody tr');
    if (!rows.length) { showToast('No audit log entries to export', 'error'); return; }
    const csvLines = ['Time,Event,Details,IP'];
    rows.forEach(row => {
        const cells = row.querySelectorAll('td');
        if (cells.length >= 4) {
            const line = Array.from(cells).map(c => '"' + (c.textContent || '').trim().replace(/"/g, '""') + '"').join(',');
            csvLines.push(line);
        }
    });
    const blob = new Blob([csvLines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'audit-logs-' + new Date().toISOString().slice(0, 10) + '.csv';
    a.click();
    URL.revokeObjectURL(url);
    showToast('Audit logs exported');
}
window.exportAuditLogsCSV = exportAuditLogsCSV;
