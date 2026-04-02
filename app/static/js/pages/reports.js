let allReports = [];
let currentPage = 1;
const pageSize = 12;

function showSharedModal(id) {
    if (typeof window.showModal === 'function') {
        window.showModal(id);
        return;
    }

    document.getElementById(id)?.classList.remove('hidden');
}

function closeSharedModal(id) {
    if (typeof window.closeModal === 'function') {
        window.closeModal(id);
        return;
    }

    document.getElementById(id)?.classList.add('hidden');
}

document.addEventListener('DOMContentLoaded', () => { loadReports(); });

async function loadReports() {
    try {
        const { data: summary, error } = await spectraApi.get('/api/v1/missions/summary');
        if (error) throw new Error('Failed');

        allReports = (summary.missions || []).map(m => ({
            ...m,
            counts: {
                critical: m.findings?.critical || 0,
                high: m.findings?.high || 0,
                medium: m.findings?.medium || 0,
                low: m.findings?.low || 0,
                info: m.findings?.info || 0,
            },
            totalFindings: m.findings?.total || 0,
        }));

        document.getElementById('reports-loading').classList.add('hidden');
        renderReports();
    } catch (e) {
        console.error('Error loading reports:', e);
        document.getElementById('reports-loading').classList.add('hidden');
        document.getElementById('reports-empty').classList.remove('hidden');
    }
}

function applyFilters() { currentPage = 1; renderReports(); }

function getFilteredReports() {
    const statusFilter = document.getElementById('filter-status').value;
    const severityFilter = document.getElementById('filter-severity').value;
    const search = document.getElementById('filter-search').value.toLowerCase();
    return allReports.filter(r => {
        if (statusFilter && r.status !== statusFilter) return false;
        if (severityFilter && (r.counts[severityFilter] || 0) === 0) return false;
        if (search) {
            const haystack = `${r.target || ''} ${r.directive || ''} ${r.id || ''}`.toLowerCase();
            if (!haystack.includes(search)) return false;
        }
        return true;
    });
}

function renderReports() {
    const filtered = getFilteredReports();
    const grid = document.getElementById('reports-grid');
    const empty = document.getElementById('reports-empty');
    if (filtered.length === 0) { grid.classList.add('hidden'); grid.innerHTML = ''; empty.classList.remove('hidden'); document.getElementById('pagination-controls').innerHTML = ''; return; }
    empty.classList.add('hidden');
    grid.classList.remove('hidden');
    const totalPages = Math.ceil(filtered.length / pageSize);
    const start = (currentPage - 1) * pageSize;
    const page = filtered.slice(start, start + pageSize);

    grid.innerHTML = page.map(r => {
        const date = r.created_at ? new Date(r.created_at).toLocaleDateString() : 'N/A';
        const statusKey = typeof r.status === 'string' ? r.status.toLowerCase() : '';
        const statusLabel = escapeHtml(String(r.status || 'unknown'));
        const sc = { completed: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20', running: 'bg-blue-500/10 text-blue-400 border-blue-500/20', failed: 'bg-rose-500/10 text-rose-400 border-rose-500/20', paused: 'bg-amber-500/10 text-amber-400 border-amber-500/20' }[statusKey] || 'bg-slate-500/10 text-slate-400 border-slate-500/20';
        const si = { completed: 'check', running: 'loader', failed: 'x', paused: 'pause' }[statusKey] || 'help-circle';
        const siClass = statusKey === 'running' ? 'w-3.5 h-3.5 inline-block animate-spin mr-1' : 'w-3.5 h-3.5 inline-block mr-1';
        return `<div class="glass-panel rounded-xl p-5 flex flex-col gap-3 group hover:border-violet-500/20 transition-all">
            <div class="flex items-start justify-between"><div class="flex-1 min-w-0"><h3 class="text-white font-medium truncate">${escapeHtml(r.target || 'Unknown Target')}</h3><p class="text-xs text-slate-500 truncate mt-0.5">${escapeHtml(r.directive || 'Security Assessment')}</p></div><span class="px-2 py-0.5 rounded text-xs font-mono border ${sc} ml-2 shrink-0"><i data-lucide="${si}" class="${siClass}"></i>${statusLabel}</span></div>
            <div class="flex items-center gap-4 text-xs text-slate-500"><span><i data-lucide="calendar" class="w-3.5 h-3.5 inline-block mr-1"></i>${date}</span><span><i data-lucide="bug" class="w-3.5 h-3.5 inline-block mr-1"></i>${r.totalFindings} findings</span></div>
            <div class="flex items-center gap-1.5 flex-wrap">
                ${r.counts.critical > 0 ? `<span class="px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-400 text-xs font-mono border border-rose-500/20">${r.counts.critical} Crit</span>` : ''}
                ${r.counts.high > 0 ? `<span class="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 text-xs font-mono border border-amber-500/20">${r.counts.high} High</span>` : ''}
                ${r.counts.medium > 0 ? `<span class="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 text-xs font-mono border border-blue-500/20">${r.counts.medium} Med</span>` : ''}
                ${r.counts.low > 0 ? `<span class="px-1.5 py-0.5 rounded bg-slate-500/10 text-slate-400 text-xs font-mono border border-slate-500/20">${r.counts.low} Low</span>` : ''}
                ${r.totalFindings === 0 ? '<span class="text-xs text-slate-600">No findings</span>' : ''}
            </div>
            <div class="flex items-center gap-2 mt-auto pt-2 border-t border-white/5">
                <button type="button" data-report-action="view" data-report-id="${escapeHtml(String(r.id || ''))}" class="flex-1 px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded text-xs text-white transition-colors text-center"><i data-lucide="eye" class="w-3.5 h-3.5 inline-block mr-1 text-violet-400"></i>View</button>
                <button type="button" data-report-action="html" data-report-id="${escapeHtml(String(r.id || ''))}" class="px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded text-xs text-white transition-colors" title="Download HTML"><i data-lucide="file-code" class="w-3.5 h-3.5 inline-block text-blue-400"></i></button>
                <button type="button" data-report-action="pdf" data-report-id="${escapeHtml(String(r.id || ''))}" class="px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded text-xs text-white transition-colors" title="Print / PDF"><i data-lucide="file-text" class="w-3.5 h-3.5 inline-block text-rose-400"></i></button>
                <button type="button" data-report-action="delete" data-report-id="${escapeHtml(String(r.id || ''))}" data-report-target="${escapeHtml(String(r.target || 'Unknown'))}" class="px-3 py-2 bg-slate-800 hover:bg-rose-900/50 rounded text-xs text-white transition-colors" title="Delete Mission"><i data-lucide="trash-2" class="w-3.5 h-3.5 inline-block text-rose-400"></i></button>
            </div>
        </div>`;
    }).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();

    const pagEl = document.getElementById('pagination-controls');
    if (totalPages <= 1) { pagEl.innerHTML = ''; return; }
    let h = `<button onclick="goToPage(${currentPage-1})" class="px-3 py-1.5 rounded text-xs ${currentPage===1?'text-slate-600 cursor-not-allowed':'text-slate-300 bg-slate-800 hover:bg-slate-700'}" ${currentPage===1?'disabled':''}>&laquo;</button>`;
    for (let i = 1; i <= totalPages; i++) h += `<button onclick="goToPage(${i})" class="px-3 py-1.5 rounded text-xs ${i===currentPage?'bg-violet-600 text-white':'text-slate-300 bg-slate-800 hover:bg-slate-700'}">${i}</button>`;
    h += `<button onclick="goToPage(${currentPage+1})" class="px-3 py-1.5 rounded text-xs ${currentPage===totalPages?'text-slate-600 cursor-not-allowed':'text-slate-300 bg-slate-800 hover:bg-slate-700'}" ${currentPage===totalPages?'disabled':''}>&raquo;</button>`;
    pagEl.innerHTML = h;
}

function goToPage(p) { const t = Math.ceil(getFilteredReports().length / pageSize); if (p < 1 || p > t) return; currentPage = p; renderReports(); }

function getReportById(missionId) {
    return allReports.find(m => String(m.id) === String(missionId));
}

function buildReportContent(report, findings) {
    const sevOrder = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
    const sortedFindings = [...findings].sort((a, b) => (sevOrder[a.severity] ?? 5) - (sevOrder[b.severity] ?? 5));
    const sevBadge = s => { const c = { critical:'bg-rose-500/20 text-rose-400', high:'bg-amber-500/20 text-amber-400', medium:'bg-blue-500/20 text-blue-400', low:'bg-slate-500/20 text-slate-400', info:'bg-slate-700/30 text-slate-500' }; return `<span class="px-2 py-0.5 rounded text-xs font-mono uppercase ${c[s]||c.info}">${s}</span>`; };
    return `<div class="max-w-4xl mx-auto space-y-6"><div class="border-b border-white/10 pb-4"><h2 class="text-xl font-bold text-white">${escapeHtml(report.target||'Unknown')}</h2><p class="text-sm text-slate-400 mt-1">${escapeHtml(report.directive||'Security Assessment')}</p><p class="text-xs text-slate-500 mt-2">Date: ${report.created_at?new Date(report.created_at).toLocaleString():'N/A'} | Status: ${escapeHtml(String(report.status || 'unknown'))} | Total: ${sortedFindings.length}</p></div><div><h3 class="text-lg font-semibold text-white mb-3">Findings (${sortedFindings.length})</h3>${sortedFindings.length===0?'<p class="text-slate-500 text-sm">No findings.</p>':''}<div class="space-y-3">${sortedFindings.map(f=>`<div class="glass-panel rounded-lg p-4 border-l-2 ${f.severity==='critical'?'border-rose-500':f.severity==='high'?'border-amber-500':f.severity==='medium'?'border-blue-500':'border-slate-600'}"><div class="flex items-center gap-2 mb-2">${sevBadge(f.severity)}<span class="text-white font-medium text-sm">${escapeHtml(f.title||'Untitled')}</span></div><p class="text-xs text-slate-400">${escapeHtml(f.description||'No description')}</p>${f.tool_source?`<p class="text-xs text-slate-500 mt-2">Tool: ${escapeHtml(f.tool_source)}</p>`:''}</div>`).join('')}</div></div></div>`;
}

async function getReportRenderData(missionId) {
    const report = getReportById(missionId);
    if (!report) return null;
    let findings = [];
    const { data: findingsData } = await spectraApi.get(`/api/v1/missions/${missionId}/findings`);
    if (findingsData) findings = findingsData;
    return {
        report,
        content: buildReportContent(report, findings),
    };
}

function buildReportDocument(title, content) {
    return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title><style>body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:2rem;color:#1e293b;background:#f8fafc}main{max-width:960px;margin:0 auto}h2{font-size:1.5rem;margin-bottom:0.5rem}h3{font-size:1.125rem;margin-top:1.5rem}.glass-panel{background:#ffffff;border:1px solid #e2e8f0;border-radius:0.75rem}.text-white{color:#0f172a}.text-slate-400,.text-slate-500{color:#475569}.border-white\/10{border-color:#e2e8f0}.border-rose-500{border-color:#e11d48}.border-amber-500{border-color:#f59e0b}.border-blue-500{border-color:#3b82f6}.border-slate-600{border-color:#475569}</style></head><body><main>${content}</main></body></html>`;
}

function getReportFilename(report, extension) {
    const safeTarget = String(report.target || 'report').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    const safeId = String(report.id || 'mission').replace(/[^a-zA-Z0-9_-]+/g, '-');
    return `${safeTarget || 'report'}-${safeId}.${extension}`;
}

function downloadTextFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

async function viewReport(missionId) {
    const reportData = await getReportRenderData(missionId);
    if (!reportData) return;
    document.getElementById('view-report-title').textContent = `Report: ${reportData.report.target || 'Unknown'}`;
    document.getElementById('view-report-content').innerHTML = reportData.content;
    showSharedModal('view-report-modal');
}

function closeViewReportModal() { closeSharedModal('view-report-modal'); }

function printReport() {
    const content = document.getElementById('view-report-content').innerHTML;
    const title = document.getElementById('view-report-title')?.textContent || 'Report';
    const w = window.open('', '_blank');
    if (!w) {
        _spectraToast('Allow pop-ups to print the report', 'warning');
        return;
    }
    w.document.write(buildReportDocument(title, content));
    w.document.close();
    w.print();
}

async function downloadReportHTML(id) {
    const reportData = await getReportRenderData(id);
    if (!reportData) {
        _spectraToast('Report not found', 'warning');
        return;
    }
    const title = `Report: ${reportData.report.target || 'Unknown'}`;
    downloadTextFile(
        buildReportDocument(title, reportData.content),
        getReportFilename(reportData.report, 'html'),
        'text/html;charset=utf-8',
    );
}

function downloadReportPDF(id) {
    if (!id) return;
    window.open(`/api/v1/missions/${encodeURIComponent(String(id))}/report/pdf`, '_blank');
}

async function openNewReportModal() {
    const sel = document.getElementById('report-mission-select');
    sel.innerHTML = '<option value="">Select a mission...</option>';
    const { data } = await spectraApi.get('/api/v1/missions');
    const missionsList = data?.items || [];
    if (missionsList) { missionsList.forEach(m => { const o = document.createElement('option'); o.value = m.id; o.textContent = `${m.target||'Unknown'} (${m.status})`; sel.appendChild(o); }); }
    showSharedModal('new-report-modal');
}
function closeNewReportModal() { closeSharedModal('new-report-modal'); }

async function generateReport() {
    const mid = document.getElementById('report-mission-select').value;
    if (!mid) { _spectraToast('Select a mission', 'warning'); return; }
    const tpl = document.getElementById('report-template-select').value;
    await spectraApi.post('/api/v1/helpers/reports/generate', {mission_id:mid,template:tpl});
    closeNewReportModal();
    viewReport(mid);
}

let deleteMissionId = null;
function showDeleteMissionModal(id, target) {
    deleteMissionId = id;
    const targetRow = document.getElementById('delete-mission-target-row');
    const targetEl = document.getElementById('delete-mission-target');
    if (targetEl) {
        targetEl.textContent = target;
    }
    if (targetRow) {
        targetRow.classList.remove('hidden');
    }
    document.getElementById('download-before-delete-btn').onclick = () => {
        window.open(`/api/v1/missions/${id}/report/pdf`, '_blank');
    };
    document.getElementById('delete-mission-modal').classList.remove('hidden');
}
function hideDeleteMissionModal() {
    document.getElementById('delete-mission-modal').classList.add('hidden');
}
async function confirmDeleteMission() {
    hideDeleteMissionModal();
    const { error } = await spectraApi.delete(`/api/v1/missions/${deleteMissionId}`);
    if (error) {
        _spectraToast(error.detail || 'Failed to delete mission', 'error');
        return;
    }
    allReports = allReports.filter(r => r.id !== deleteMissionId);
    renderReports();
}
const debouncedApplyFilters = debounce(applyFilters);

// Expose functions used by HTML onclick/onchange handlers
window.openNewReportModal = openNewReportModal;
window.applyFilters = applyFilters;
window.debouncedApplyFilters = debouncedApplyFilters;
window.closeNewReportModal = closeNewReportModal;
window.generateReport = generateReport;
window.closeViewReportModal = closeViewReportModal;
window.printReport = printReport;
window.viewReport = viewReport;
window.downloadReportHTML = downloadReportHTML;
window.downloadReportPDF = downloadReportPDF;
window.showDeleteMissionModal = showDeleteMissionModal;
window.handleDeleteMissionModalCancel = hideDeleteMissionModal;
window.handleDeleteMissionModalConfirm = confirmDeleteMission;
window.goToPage = goToPage;


document.getElementById('reports-grid')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-report-action][data-report-id]');
    if (!button) return;
    const reportId = button.dataset.reportId;
    switch (button.dataset.reportAction) {
        case 'view':
            viewReport(reportId);
            break;
        case 'html':
            downloadReportHTML(reportId);
            break;
        case 'pdf':
            downloadReportPDF(reportId);
            break;
        case 'delete':
            showDeleteMissionModal(reportId, button.dataset.reportTarget || 'Unknown');
            break;
        default:
            break;
    }
});
