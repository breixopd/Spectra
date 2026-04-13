// ---- Helpers ----
function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month:'short', day:'numeric', year:'numeric' });
}

// Quick-action wrappers for data-action delegation
function quickCreateUser() { switchSection('users'); openCreateUserModal(); }
function quickCreatePlan() { switchSection('plans'); openCreatePlanModal(); }

function formatDateTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString('en-US', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' });
}

// ---- State ----
let usersPage = 1, usersPerPage = 20;
let auditPage = 1, auditPerPage = 50;
let allPlans = [];
let currentUsers = [];

const USER_ROLE_BADGE_CLASSES = {
    admin: 'badge-admin',
    operator: 'badge-operator',
    viewer: 'badge-viewer'
};

function getUserRoleBadgeClass(role) {
    return USER_ROLE_BADGE_CLASSES[String(role || 'viewer').toLowerCase()] || USER_ROLE_BADGE_CLASSES.viewer;
}

function getUserRoleLabel(role) {
    return escapeHtml(String(role || 'viewer'));
}

let statsErrorVisible = false;

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

// ---- Maintenance Mode Toggle ----
async function toggleMaintenance() {
    const btn = document.getElementById('maintenance-toggle-btn');
    const msg = document.getElementById('maintenance-msg-input').value.trim();
    const currentlyActive = btn.dataset.active === 'true';
    const newState = !currentlyActive;
    try {
        const payload = { MAINTENANCE_MODE: newState };
        if (msg) payload.MAINTENANCE_MESSAGE = msg;
        const { error } = await spectraApi.put('/api/admin/settings', payload);
        if (error) throw new Error(error);
        location.reload();
    } catch (e) {
        _spectraToast('Failed to toggle maintenance mode: ' + e.message, 'error');
    }
}

// ---- Modals ----
// showModal / closeModal are provided globally by modal.js (loaded in base.html)
const showModal = (id) => window.showModal(id);
const closeModal = (id) => window.closeModal(id);

// close modal on backdrop click
document.querySelectorAll('.modal-backdrop').forEach(m => {
    m.addEventListener('click', e => { if (e.target === m) closeModal(m.id); });
});

let confirmCallback = null;
function showConfirm(title, message, action) {
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-message').textContent = message;
    confirmCallback = action;
    showModal('confirm-modal');
}
document.getElementById('confirm-action-btn').addEventListener('click', function() {
    closeModal('confirm-modal');
    if (confirmCallback) confirmCallback();
});

// ---- Section Switching ----
function switchSection(name) {
    document.querySelectorAll('.section-panel').forEach(p => p.classList.remove('active'));
    const target = document.getElementById('section-' + name);
    if (target) target.classList.add('active');
    document.querySelectorAll('.admin-sidebar [data-section]').forEach(a => {
        a.classList.remove('active');
        a.classList.add('text-slate-400');
        a.setAttribute('aria-selected', 'false');
    });
    const link = document.querySelector(`.admin-sidebar [data-section="${name}"]`);
    if (link) { link.classList.add('active'); link.classList.remove('text-slate-400'); link.setAttribute('aria-selected', 'true'); }

    if (history.replaceState) history.replaceState(null, '', '#' + name);

    if (name === 'dashboard') loadStats();
    if (name === 'users') loadUsers();
    if (name === 'plans') loadPlans();
    if (name === 'audit') loadAuditLogs();
    if (name === 'usage') loadUsage();
    if (name === 'services') loadServices();
    if (name === 'scaling') loadScalingStatus();
    if (name === 'content') loadContent();
    if (name === 'llm') loadTZConfig();
    if (name === 'email') loadEmailConfig();
    if (name === 'backups') loadBackups();
    if (name === 'rollback') loadRollbackSnapshots();
    if (name === 'tensorzero') { loadTZStatus(); loadTZInferences(); loadTZFunctionStats(); }
}

document.querySelectorAll('.admin-sidebar [data-section]').forEach(a => {
    a.addEventListener('click', e => { e.preventDefault(); switchSection(a.dataset.section); });
});

// Restore section from URL hash
(function() {
    const hash = window.location.hash.slice(1);
    if (hash && document.getElementById('section-' + hash)) {
        switchSection(hash);
    }
})();


// ---- Dashboard (loaded from admin/dashboard.js) ----
// ---- Users (loaded from admin/users.js) ----
// ---- Plans (loaded from admin/plans.js) ----

// ---- Audit Logs ----
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
    } catch(e) { console.error(e); _spectraToast('Error loading audit logs', 'error'); }
}

document.getElementById('audit-prev').addEventListener('click', () => { auditPage--; loadAuditLogs(); });
document.getElementById('audit-next').addEventListener('click', () => { auditPage++; loadAuditLogs(); });
document.getElementById('audit-event-filter').addEventListener('change', () => { auditPage = 1; loadAuditLogs(); });
document.getElementById('audit-date-from').addEventListener('change', () => { auditPage = 1; loadAuditLogs(); });
document.getElementById('audit-date-to').addEventListener('change', () => { auditPage = 1; loadAuditLogs(); });


// ---- Usage ----
async function loadUsage() {
    try {
        const { data: d, error } = await spectraApi.get('/api/admin/usage');
        if (error) throw new Error(error);
        document.getElementById('usage-total-calls').textContent = d.total_calls.toLocaleString();
        document.getElementById('usage-total-tokens').textContent = d.total_tokens.toLocaleString();
        document.getElementById('usage-total-cost').textContent = '$' + d.total_cost_usd.toFixed(4);
        document.getElementById('usage-active-missions').textContent = d.active_missions;

        const tbody = document.getElementById('usage-tbody');
        if (!d.by_agent || !d.by_agent.length) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center py-8 text-slate-500">No LLM usage recorded yet</td></tr>';
        } else {
            tbody.innerHTML = d.by_agent.map(a => `
                <tr class="border-b border-white/5">
                    <td class="px-4 py-3 text-xs text-slate-400 font-mono">${escapeHtml(String(a.mission_id).substring(0, 8))}…</td>
                    <td class="px-4 py-3 text-sm text-white">${escapeHtml(a.agent_name)}</td>
                    <td class="px-4 py-3"><span class="badge bg-slate-700/50 text-slate-300">${escapeHtml(a.role)}</span></td>
                    <td class="px-4 py-3 text-right text-slate-300">${a.calls}</td>
                    <td class="px-4 py-3 text-right text-slate-300">${a.tokens.toLocaleString()}</td>
                    <td class="px-4 py-3 text-right text-amber-300">$${a.cost_usd.toFixed(4)}</td>
                    <td class="px-4 py-3 text-right text-slate-400">${a.avg_latency_ms.toFixed(0)} ms</td>
                    <td class="px-4 py-3 text-right ${a.errors > 0 ? 'text-red-400' : 'text-slate-500'}">${a.errors}</td>
                </tr>`).join('');
        }
    } catch(e) { console.error(e); _spectraToast('Error loading usage data', 'error'); }
}


// ---- Services (loaded from admin/services.js) ----

// ---- Content Management ----
let currentContentType = 'review';

function switchContentType(type, el) {
    currentContentType = type;
    document.querySelectorAll('.content-type-btn').forEach(b => {
        b.classList.remove('active', 'bg-violet-600/20', 'text-violet-300', 'border-violet-500/30');
        b.classList.add('bg-white/5', 'text-slate-400', 'border-white/10');
    });
    if (el) {
        el.classList.add('active', 'bg-violet-600/20', 'text-violet-300', 'border-violet-500/30');
        el.classList.remove('bg-white/5', 'text-slate-400', 'border-white/10');
    }
    loadContent();
}

async function loadContent() {
    try {
        const { data: items, error } = await spectraApi.get(`/api/admin/content?content_type=${currentContentType}`);
        if (error) throw new Error(error);
        const list = document.getElementById('content-list');
        if (!items.length) { list.innerHTML = '<p class="text-sm text-slate-500">No items yet.</p>'; return; }
        list.innerHTML = items.map(item => `
            <div class="glass-panel rounded-lg p-4 flex justify-between items-start">
                <div>
                    <p class="text-sm font-medium text-white">${escapeHtml(item.title || item.content_type)}</p>
                    <p class="text-xs text-slate-500 mt-1">${escapeHtml(JSON.stringify(item.content).slice(0,100))}...</p>
                    <span class="text-xs ${item.is_active ? 'text-emerald-400' : 'text-slate-500'}">${item.is_active ? 'Active' : 'Inactive'}</span>
                </div>
                <div class="flex gap-2">
                    <button data-action="editContent" data-value="${item.id}" class="text-xs text-violet-400 hover:text-violet-300"><i data-lucide="edit" class="w-3.5 h-3.5 inline-block"></i></button>
                    <button data-action="deleteContent" data-value="${item.id}" class="text-xs text-red-400 hover:text-red-300"><i data-lucide="trash-2" class="w-3.5 h-3.5 inline-block"></i></button>
                </div>
            </div>
        `).join('');
    } catch(e) { console.error('Load content error', e); }
}

function openContentModal(existingData) {
    showModal('content-modal');
    document.getElementById('content-type-field').value = currentContentType;
    document.getElementById('review-fields').style.display = currentContentType === 'review' ? '' : 'none';
    document.getElementById('changelog-fields').style.display = currentContentType === 'changelog' ? '' : 'none';
    document.getElementById('legal-fields').style.display = currentContentType.startsWith('legal') ? '' : 'none';
    if (existingData) {
        document.getElementById('content-modal-title').textContent = 'Edit Content';
        document.getElementById('content-edit-id').value = existingData.id;
        document.getElementById('content-title').value = existingData.title || '';
        document.getElementById('content-active').checked = existingData.is_active;
        document.getElementById('content-sort').value = existingData.sort_order || 0;
        const c = existingData.content || {};
        if (currentContentType === 'review') {
            document.getElementById('content-quote').value = c.quote || '';
            document.getElementById('content-author').value = c.author_name || '';
            document.getElementById('content-role').value = c.author_role || '';
            document.getElementById('content-initials').value = c.initials || '';
        } else if (currentContentType === 'changelog') {
            document.getElementById('content-version').value = c.version || '';
            document.getElementById('content-changes').value = (c.changes || []).join('\n');
        } else {
            document.getElementById('content-html').value = c.html || '';
        }
    } else {
        document.getElementById('content-modal-title').textContent = 'Add Content';
    }
}

function closeContentModal() {
    closeModal('content-modal');
    document.getElementById('content-form').reset();
    document.getElementById('content-edit-id').value = '';
}

async function editContent(id) {
    const { data: items } = await spectraApi.get(`/api/admin/content?content_type=${currentContentType}`);
    const item = items.find(i => i.id === id);
    if (item) openContentModal(item);
}

async function deleteContent(id) {
    showConfirm('Delete Content', 'Delete this item?', async () => {
        await spectraApi.delete(`/api/admin/content/${id}`);
        loadContent();
        _spectraToast('Content deleted', 'success');
    });
}

document.getElementById('content-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const editId = document.getElementById('content-edit-id').value;
    let content = {};
    if (currentContentType === 'review') {
        content = {
            quote: document.getElementById('content-quote').value,
            author_name: document.getElementById('content-author').value,
            author_role: document.getElementById('content-role').value,
            initials: document.getElementById('content-initials').value,
        };
    } else if (currentContentType === 'changelog') {
        content = {
            version: document.getElementById('content-version').value,
            changes: document.getElementById('content-changes').value.split('\n').filter(Boolean),
        };
    } else {
        content = { html: document.getElementById('content-html').value };
    }
    const payload = {
        content_type: currentContentType,
        title: document.getElementById('content-title').value,
        content,
        is_active: document.getElementById('content-active').checked,
        sort_order: parseInt(document.getElementById('content-sort').value) || 0,
    };
    const url = editId ? `/api/admin/content/${editId}` : '/api/admin/content';
    const method = editId ? 'PUT' : 'POST';
    try {
        const r = editId ? await spectraApi.put(url, payload) : await spectraApi.post(url, payload);
        if (r.error) throw new Error(r.error);
        closeContentModal();
        loadContent();
        _spectraToast('Content saved', 'success');
    } catch(e) { _spectraToast(e.message, 'error'); }
});


// ---- AI Gateway Config ----
async function loadTZConfig() {
    try {
        const { data, error } = await spectraApi.get('/api/settings');
        if (error) throw new Error(error);
        const s = data || {};
        const el = (id) => document.getElementById(id);
        if (el('tz-gateway-url')) el('tz-gateway-url').value = s.tensorzero_gateway_url || s.TENSORZERO_GATEWAY_URL || '';
        if (el('llm-timeout')) el('llm-timeout').value = s.llm_timeout || s.LLM_TIMEOUT || 600;
        if (el('llm-embedding')) el('llm-embedding').value = s.embedding_model || s.EMBEDDING_MODEL || 'local/BAAI/bge-small-en-v1.5';
        // Load model config from TZ gateway
        const { data: tzData } = await spectraApi.get('/api/v1/admin/tensorzero/config');
        if (tzData?.models) {
            for (const tier of ['fast', 'balanced', 'capable']) {
                const m = tzData.models[tier] || {};
                const primary = typeof m === 'string' ? m : (m.primary || '');
                const fallback = typeof m === 'string' ? '' : (m.fallback || '');
                if (el(`tz-model-${tier}`)) el(`tz-model-${tier}`).value = primary;
                if (el(`tz-model-${tier}-fallback`)) el(`tz-model-${tier}-fallback`).value = fallback;
            }
        }
        if (tzData?.provider_type && el('tz-provider-type')) el('tz-provider-type').value = tzData.provider_type;
    } catch(e) { console.error('Load AI config error', e); }
}

async function saveTZConfig() {
    const payload = {
        tensorzero_gateway_url: document.getElementById('tz-gateway-url')?.value || '',
        llm_timeout: parseFloat(document.getElementById('llm-timeout')?.value) || 600,
        embedding_model: document.getElementById('llm-embedding')?.value || '',
        embedding_api_key: document.getElementById('embedding-api-key')?.value || undefined,
    };
    try {
        const { error } = await spectraApi.post('/api/settings', payload);
        if (error) throw new Error(error);
    } catch(e) { _spectraToast('Failed to save settings: ' + e.message, 'error'); return; }

    // Update TZ model config
    const modelPayload = {
        models: {
            fast: {
                primary: document.getElementById('tz-model-fast')?.value || '',
                fallback: document.getElementById('tz-model-fast-fallback')?.value || '',
            },
            balanced: {
                primary: document.getElementById('tz-model-balanced')?.value || '',
                fallback: document.getElementById('tz-model-balanced-fallback')?.value || '',
            },
            capable: {
                primary: document.getElementById('tz-model-capable')?.value || '',
                fallback: document.getElementById('tz-model-capable-fallback')?.value || '',
            },
        },
        provider_type: document.getElementById('tz-provider-type')?.value || 'openai',
    };
    try {
        const { error } = await spectraApi.put('/api/v1/admin/tensorzero/config', modelPayload);
        if (error) _spectraToast('Settings saved. Note: TZ config update failed — ' + error, 'warning');
        else _spectraToast('Configuration saved. Restart TensorZero container to apply model changes.', 'success');
    } catch(e) { _spectraToast('Settings saved but TZ update failed: ' + e.message, 'warning'); }
}

async function testTZConnection() {
    const result = document.getElementById('llm-test-result');
    result.classList.remove('hidden');
    result.className = 'mt-3 p-3 rounded-lg text-sm bg-blue-600/10 text-blue-300 border border-blue-500/30';
    result.textContent = 'Testing gateway connection...';
    try {
        const { data, error } = await spectraApi.get('/api/v1/admin/tensorzero/status');
        if (error || !data?.online) {
            result.className = 'mt-3 p-3 rounded-lg text-sm bg-red-600/10 text-red-300 border border-red-500/30';
            result.innerHTML = '<i data-lucide="x-circle" class="w-4 h-4 inline-block mr-1"></i> Gateway unreachable: ' + escapeHtml(error || 'Connection failed');
            if (typeof lucide !== 'undefined') lucide.createIcons();
        } else {
            result.className = 'mt-3 p-3 rounded-lg text-sm bg-emerald-600/10 text-emerald-300 border border-emerald-500/30';
            result.innerHTML = '<i data-lucide="check-circle" class="w-4 h-4 inline-block mr-1"></i> Gateway online &mdash; ' +
                (data.functions_count || 0) + ' functions, ' + (data.models_count || 0) + ' models configured';
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    } catch(e) {
        result.className = 'mt-3 p-3 rounded-lg text-sm bg-red-600/10 text-red-300 border border-red-500/30';
        result.textContent = '\u2717 Error: ' + e.message;
    }
}


// ---- Backups ----
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
function formatBytes(b) { if(!b) return '0 B'; const k=1024,s=['B','KB','MB','GB']; const i=Math.floor(Math.log(b)/Math.log(k)); return (b/Math.pow(k,i)).toFixed(1)+' '+s[i]; }
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


// ---- Email ----
let _emailTemplates = {};
let _emailActiveTemplate = '';

async function loadEmailConfig() {
    const statusEl = document.getElementById('email-smtp-status');
    try {
        const r = await spectraApi.get('/api/admin/stats');
        const d = !r.error ? r.data : {};
        const smtpConfigured = Boolean(d.smtp_configured);
        statusEl.innerHTML = smtpConfigured
            ? '<span class="text-emerald-400"><i data-lucide="check-circle" class="w-4 h-4 inline-block mr-1"></i> SMTP configured</span>'
            : '<span class="text-amber-400"><i data-lucide="alert-triangle" class="w-4 h-4 inline-block mr-1"></i> SMTP not configured — using console fallback</span>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch { statusEl.textContent = 'Unable to load status'; }

    try {
        const r = await spectraApi.get('/api/admin/email/templates');
        if (r.error) throw new Error();
        _emailTemplates = r.data;
        const tabs = document.getElementById('email-template-tabs');
        tabs.innerHTML = '';
        for (const name of Object.keys(_emailTemplates)) {
            const btn = document.createElement('button');
            btn.className = 'px-3 py-1 rounded-lg text-xs font-medium transition-colors ' +
                (name === _emailActiveTemplate ? 'bg-violet-600 text-white' : 'bg-white/5 text-slate-400 hover:bg-white/10');
            btn.textContent = name;
            btn.onclick = () => selectEmailTemplate(name);
            tabs.appendChild(btn);
        }
        if (!_emailActiveTemplate && Object.keys(_emailTemplates).length) {
            selectEmailTemplate(Object.keys(_emailTemplates)[0]);
        } else if (_emailActiveTemplate) {
            document.getElementById('email-template-editor').value = _emailTemplates[_emailActiveTemplate] || '';
        }
    } catch { /* ignore */ }
}

function selectEmailTemplate(name) {
    _emailActiveTemplate = name;
    document.getElementById('email-template-editor').value = _emailTemplates[name] || '';
    document.querySelectorAll('#email-template-tabs button').forEach(b => {
        b.className = b.textContent === name
            ? 'px-3 py-1 rounded-lg text-xs font-medium transition-colors bg-violet-600 text-white'
            : 'px-3 py-1 rounded-lg text-xs font-medium transition-colors bg-white/5 text-slate-400 hover:bg-white/10';
    });
}

async function saveEmailTemplate() {
    if (!_emailActiveTemplate) return;
    const content = document.getElementById('email-template-editor').value;
    try {
        const r = await spectraApi.put(`/api/admin/email/templates/${_emailActiveTemplate}`, {content});
        if (r.error) throw new Error(r.error);
        _emailTemplates[_emailActiveTemplate] = content;
        showConfirm('Template saved.', null, {title:'Saved', icon:'check', confirmText:'OK', hideCancel:true});
    } catch(e) { showConfirm(e.message, null, {title:'Error', icon:'triangle-exclamation', confirmText:'OK', hideCancel:true}); }
}

async function sendTestEmail(e) {
    e.preventDefault();
    const to = document.getElementById('test-email-to').value;
    const btn = document.getElementById('test-email-btn');
    const result = document.getElementById('test-email-result');
    btn.disabled = true; btn.textContent = 'Sending...';
    try {
        const r = await spectraApi.post('/api/admin/email/test', {to});
        const d = r.data;
        result.className = !r.error
            ? 'mt-3 p-3 rounded-lg text-sm bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
            : 'mt-3 p-3 rounded-lg text-sm bg-red-500/10 text-red-400 border border-red-500/20';
        result.textContent = !r.error ? `Test email sent to ${d.to}` : (r.error || 'Failed');
        result.classList.remove('hidden');
    } catch(err) {
        result.className = 'mt-3 p-3 rounded-lg text-sm bg-red-500/10 text-red-400 border border-red-500/20';
        result.textContent = err.message;
        result.classList.remove('hidden');
    } finally {
        btn.disabled = false; btn.innerHTML = '<i data-lucide="send" class="w-4 h-4 inline-block mr-1.5"></i> Send Test';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}


// ---- TensorZero Gateway ----
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


// ---- Rollback ----
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
    } catch(e) { console.error(e); _spectraToast('Error loading rollback snapshots', 'error'); }
}

async function performRollback(snapshotId) {
    showConfirm(
        'Confirm Rollback',
        'This will revert the action. The entity will be restored to its previous state. Are you sure?',
        async () => {
            try {
                const { data, error } = await spectraApi.post(`/api/admin/rollback/snapshots/${snapshotId}/rollback`, {});
                if (error) throw new Error(error);
                _spectraToast('Action reverted successfully', 'success');
                loadRollbackSnapshots();
            } catch(e) { _spectraToast('Rollback failed: ' + e.message, 'error'); }
        }
    );
}


// ---- Scaling (loaded from admin/scaling.js) ----

// ---- Init ----
loadStats();
// Pre-load plans for user form plan select
spectraApi.get('/api/admin/plans').then(r => !r.error ? r.data : []).then(p => { allPlans = Array.isArray(p) ? p : []; }).catch(() => {});

// ---- Expose functions used by HTML onclick/onchange/onsubmit handlers ----
window.toggleMaintenance = toggleMaintenance;
window.switchSection = switchSection;
window.openCreateUserModal = openCreateUserModal;
window.openEditUserModal = openEditUserModal;
window.resetPassword = resetPassword;
window.deactivateUser = deactivateUser;
window.openCreatePlanModal = openCreatePlanModal;
window.openEditPlanModal = openEditPlanModal;
window.deactivatePlan = deactivatePlan;
window.checkAllHealth = checkAllHealth;
window.openServiceConfigModal = openServiceConfigModal;
window.testServiceConnection = testServiceConnection;
window.resetServiceToLocal = resetServiceToLocal;
window.saveBillingSettings = saveBillingSettings;
window.openProvisionModal = openProvisionModal;
window.toggleProvAuth = toggleProvAuth;
window.updateProvisionDefaults = updateProvisionDefaults;
window.testServerConnection = testServerConnection;
window.provisionServer = provisionServer;
window.deprovisionServer = deprovisionServer;
window.refreshNodesList = refreshNodesList;
window.deployToNode = deployToNode;
window.viewNodeLogs = viewNodeLogs;
window.switchContentType = switchContentType;
window.quickCreateUser = quickCreateUser;
window.quickCreatePlan = quickCreatePlan;
window.openContentModal = openContentModal;
window.closeContentModal = closeContentModal;
window.editContent = editContent;
window.deleteContent = deleteContent;
window.testTZConnection = testTZConnection;
window.saveTZConfig = saveTZConfig;
window.loadTZConfig = loadTZConfig;
window.createBackup = createBackup;
window.restoreBackup = restoreBackup;
window.saveEmailTemplate = saveEmailTemplate;
window.sendTestEmail = sendTestEmail;
window.loadTZStatus = loadTZStatus;
window.loadTZInferences = loadTZInferences;
window.loadTZFunctionStats = loadTZFunctionStats;
window.loadRollbackSnapshots = loadRollbackSnapshots;
window.performRollback = performRollback;
window.loadScalingStatus = loadScalingStatus;
window.refreshScalingStatus = refreshScalingStatus;
window.saveScalingConfig = saveScalingConfig;
window.scalingAction = scalingAction;

function exportAuditLogsCSV() {
    const rows = document.querySelectorAll('#audit-tbody tr');
    if (!rows.length) { _spectraToast('No audit log entries to export', 'error'); return; }
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
    _spectraToast('Audit logs exported');
}
window.exportAuditLogsCSV = exportAuditLogsCSV;
