// ---- Helpers ----
function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month:'short', day:'numeric', year:'numeric' });
}

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

// ---- Users ----
async function loadUsers() {
    const search = document.getElementById('user-search').value;
    const role = document.getElementById('user-role-filter').value;
    const statusVal = document.getElementById('user-status-filter').value;
    const params = new URLSearchParams({ page: usersPage, per_page: usersPerPage });
    if (search) params.set('search', search);
    if (role) params.set('role', role);
    if (statusVal) params.set('is_active', statusVal);

    try {
        const { data: d, error } = await spectraApi.get('/api/admin/users?' + params);
        if (error) throw new Error(error);
        const tbody = document.getElementById('users-tbody');
        currentUsers = Array.isArray(d.items) ? d.items : [];
        if (!currentUsers.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center py-8 text-slate-500">No users found</td></tr>';
        } else {
            tbody.innerHTML = currentUsers.map((u, index) => {
                const roleBadgeClass = getUserRoleBadgeClass(u.role);
                const roleLabel = getUserRoleLabel(u.role);
                return `
                <tr class="border-b border-white/5">
                    <td class="px-4 py-3"><span class="font-medium text-white">${escapeHtml(u.username)}</span></td>
                    <td class="px-4 py-3 text-slate-400">${escapeHtml(u.email)}</td>
                    <td class="px-4 py-3"><span class="badge ${roleBadgeClass}">${roleLabel}</span></td>
                    <td class="px-4 py-3"><span class="badge ${u.is_active ? 'badge-active' : 'badge-inactive'}">${u.is_active ? 'Active' : 'Inactive'}</span></td>
                    <td class="px-4 py-3 text-slate-500 text-xs">${formatDate(u.created_at)}</td>
                    <td class="px-4 py-3 text-right">
                        <button type="button" data-user-action="edit" data-user-index="${index}" class="text-slate-400 hover:text-violet-400 mr-2" title="Edit"><i data-lucide="edit" class="w-4 h-4 inline-block"></i></button>
                        <button type="button" data-user-action="reset" data-user-index="${index}" class="text-slate-400 hover:text-amber-400 mr-2" title="Reset password"><i data-lucide="key" class="w-4 h-4 inline-block"></i></button>
                        <button type="button" data-user-action="deactivate" data-user-index="${index}" class="text-slate-400 hover:text-red-400" title="Deactivate"><i data-lucide="user-x" class="w-4 h-4 inline-block"></i></button>
                    </td>
                </tr>`;
            }).join('');
        }

        const totalPages = Math.ceil(d.total / d.per_page) || 1;
        document.getElementById('users-info').textContent = `${d.total} user${d.total !== 1 ? 's' : ''}`;
        document.getElementById('users-page-num').textContent = d.page + ' / ' + totalPages;
        document.getElementById('users-prev').disabled = d.page <= 1;
        document.getElementById('users-next').disabled = d.page >= totalPages;
    } catch(e) { console.error(e); _spectraToast('Error loading users', 'error'); }
}

document.getElementById('users-prev').addEventListener('click', () => { usersPage--; loadUsers(); });
document.getElementById('users-next').addEventListener('click', () => { usersPage++; loadUsers(); });
document.getElementById('users-tbody').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-user-action][data-user-index]');
    if (!button) return;

    const index = Number.parseInt(button.dataset.userIndex, 10);
    const user = Number.isInteger(index) ? currentUsers[index] : null;
    if (!user) return;

    switch (button.dataset.userAction) {
        case 'edit':
            openEditUserModal(user);
            break;
        case 'reset':
            resetPassword(user.id, user.username);
            break;
        case 'deactivate':
            deactivateUser(user.id, user.username);
            break;
    }
});

let userSearchTimeout;
document.getElementById('user-search').addEventListener('input', () => {
    clearTimeout(userSearchTimeout);
    userSearchTimeout = setTimeout(() => { usersPage = 1; loadUsers(); }, 300);
});
document.getElementById('user-role-filter').addEventListener('change', () => { usersPage = 1; loadUsers(); });
document.getElementById('user-status-filter').addEventListener('change', () => { usersPage = 1; loadUsers(); });

// Create user modal
function openCreateUserModal() {
    document.getElementById('user-modal-title').textContent = 'Create User';
    document.getElementById('user-form').reset();
    document.getElementById('user-form-id').value = '';
    document.getElementById('user-form-username-group').style.display = '';
    document.getElementById('user-form-password-group').style.display = '';
    document.getElementById('user-form-password').required = true;
    document.getElementById('user-form-status-group').classList.add('hidden');
    populatePlanSelect();
    showModal('user-modal');
}

function openEditUserModal(u) {
    document.getElementById('user-modal-title').textContent = 'Edit User';
    document.getElementById('user-form-id').value = u.id;
    document.getElementById('user-form-username').value = u.username;
    document.getElementById('user-form-username-group').style.display = 'none';
    document.getElementById('user-form-email').value = u.email;
    document.getElementById('user-form-password-group').style.display = 'none';
    document.getElementById('user-form-password').required = false;
    document.getElementById('user-form-role').value = u.role;
    document.getElementById('user-form-status-group').classList.remove('hidden');
    document.getElementById('user-form-status').value = String(u.is_active);
    populatePlanSelect(u.plan_id);
    showModal('user-modal');
}

function populatePlanSelect(selectedId) {
    const sel = document.getElementById('user-form-plan');
    sel.innerHTML = '<option value="">None</option>';
    allPlans.filter(p => p.is_active).forEach(p => {
        sel.innerHTML += `<option value="${p.id}" ${p.id === selectedId ? 'selected' : ''}>${escapeHtml(p.display_name)}</option>`;
    });
}

document.getElementById('user-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    const id = document.getElementById('user-form-id').value;
    const isEdit = !!id;
    const body = {};

    if (!isEdit) {
        body.username = document.getElementById('user-form-username').value;
        body.password = document.getElementById('user-form-password').value;
    }
    body.email = document.getElementById('user-form-email').value;
    body.role = document.getElementById('user-form-role').value;
    body.plan_id = document.getElementById('user-form-plan').value || null;
    if (isEdit) {
        body.is_active = document.getElementById('user-form-status').value === 'true';
    }

    try {
        const url = isEdit ? `/api/admin/users/${id}` : '/api/admin/users';
        const { data, error } = isEdit ? await spectraApi.put(url, body) : await spectraApi.post(url, body);
        if (error) throw new Error(error);
        let successMessage = isEdit ? 'User updated' : 'User created';
        if (!isEdit && data?.activation_url) {
            successMessage = `User created. Share the activation link manually: ${data.activation_url}`;
        }
        _spectraToast(successMessage, 'success');
        closeModal('user-modal');
        loadUsers();
    } catch(e) { _spectraToast(e.message, 'error'); }
});

function resetPassword(userId, username) {
    showConfirm('Reset Password', `Send a password reset email to ${username}?`, async () => {
        try {
            const { data, error } = await spectraApi.post(`/api/admin/users/${userId}/reset-password`);
            if (error) throw new Error(error);
            _spectraToast(data?.detail || 'Password reset email sent', 'success');
        } catch(e) { _spectraToast(e.message || 'Password reset failed', 'error'); }
    });
}

function deactivateUser(userId, username) {
    showConfirm('Deactivate User', `Deactivate user "${username}"? They will lose access.`, async () => {
        try {
            const { error } = await spectraApi.delete(`/api/admin/users/${userId}`);
            if (error) throw new Error(error);
            _spectraToast('User deactivated', 'success');
            loadUsers();
        } catch(e) { _spectraToast(e.message, 'error'); }
    });
}

// ---- Plans ----
async function loadPlans() {
    try {
        const { data, error } = await spectraApi.get('/api/admin/plans');
        if (error) throw new Error(error);
        allPlans = data;
        renderPlans();
    } catch(e) { console.error(e); _spectraToast('Error loading plans', 'error'); }
}

function renderPlans() {
    const grid = document.getElementById('plans-grid');
    if (!allPlans.length) {
        grid.innerHTML = '<div class="col-span-full text-center py-12 text-slate-500"><i data-lucide="layers" class="w-5 h-5 inline-block mb-2 opacity-30"></i><p>No plans configured yet</p></div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }
    const tierColors = { light: 'bg-sky-500/20 text-sky-300', medium: 'bg-emerald-500/20 text-emerald-300', heavy: 'bg-orange-500/20 text-orange-300', extreme: 'bg-rose-500/20 text-rose-300' };
    grid.innerHTML = allPlans.map(p => {
        const tierBadge = p.sandbox_resource_tier ? `<span class="badge ${tierColors[p.sandbox_resource_tier] || 'bg-slate-500/20 text-slate-300'}">${escapeHtml(p.sandbox_resource_tier)}</span>` : '';
        const featureTags = p.features ? Object.entries(p.features).filter(([,v]) => v).map(([k]) => `<span class="inline-block px-1.5 py-0.5 text-xs rounded bg-slate-700/60 text-slate-300 mr-1 mb-1">${escapeHtml(k)}</span>`).join('') : '';
        return `
        <div class="glass-panel rounded-xl p-5 ${!p.is_active ? 'opacity-50' : ''}">
            <div class="flex items-start justify-between mb-3">
                <div>
                    <h3 class="text-base font-semibold text-white">${escapeHtml(p.display_name)}</h3>
                    <p class="text-xs text-slate-500 font-mono">${escapeHtml(p.name)}</p>
                </div>
                <div class="flex items-center gap-1 flex-wrap justify-end">
                    ${tierBadge}
                    ${p.is_default ? '<span class="badge bg-violet-500/20 text-violet-300">Default</span>' : ''}
                    <span class="badge ${p.is_active ? 'badge-active' : 'badge-inactive'}">${p.is_active ? 'Active' : 'Inactive'}</span>
                </div>
            </div>
            ${p.description ? `<p class="text-sm text-slate-400 mb-3">${escapeHtml(p.description)}</p>` : ''}
            ${featureTags ? `<div class="mb-3">${featureTags}</div>` : ''}
            <div class="grid grid-cols-2 gap-2 text-xs mb-3">
                <div class="flex justify-between"><span class="text-slate-500">Concurrent</span><span class="text-white">${p.max_concurrent_missions}</span></div>
                <div class="flex justify-between"><span class="text-slate-500">Monthly</span><span class="text-white">${p.max_missions_per_month ?? '∞'}</span></div>
                <div class="flex justify-between"><span class="text-slate-500">Targets</span><span class="text-white">${p.max_targets ?? '∞'}</span></div>
                <div class="flex justify-between"><span class="text-slate-500">Storage</span><span class="text-white">${p.max_storage_mb} MB</span></div>
                <div class="flex justify-between"><span class="text-slate-500">API/hr</span><span class="text-white">${p.max_api_requests_per_hour}</span></div>
                <div class="flex justify-between"><span class="text-slate-500">Sandboxes</span><span class="text-white">${p.sandbox_max_containers}</span></div>
            </div>
            <div class="flex justify-end gap-2 pt-2 border-t border-white/5">
                <button onclick='openEditPlanModal(${JSON.stringify(p).replace(/'/g,"&#39;")})' class="text-xs text-slate-400 hover:text-violet-400 transition-colors"><i data-lucide="edit" class="w-3.5 h-3.5 inline-block mr-1"></i>Edit</button>
                ${p.is_active ? `<button onclick="deactivatePlan('${p.id}','${escapeHtml(p.name)}')" class="text-xs text-slate-400 hover:text-red-400 transition-colors"><i data-lucide="ban" class="w-3.5 h-3.5 inline-block mr-1"></i>Deactivate</button>` : `<button onclick="activatePlan('${p.id}','${escapeHtml(p.name)}')" class="text-xs text-slate-400 hover:text-emerald-400 transition-colors"><i data-lucide="check-circle" class="w-3.5 h-3.5 inline-block mr-1"></i>Activate</button>`}
            </div>
        </div>`;
    }).join('');
}

function openCreatePlanModal() {
    document.getElementById('plan-modal-title').textContent = 'Create Plan';
    document.getElementById('plan-form').reset();
    document.getElementById('plan-form-id').value = '';
    document.getElementById('plan-form-name').disabled = false;
    document.querySelectorAll('.plan-feature-toggle').forEach(cb => { cb.checked = false; });
    showModal('plan-modal');
}

function openEditPlanModal(p) {
    document.getElementById('plan-modal-title').textContent = 'Edit Plan';
    document.getElementById('plan-form-id').value = p.id;
    document.getElementById('plan-form-name').value = p.name;
    document.getElementById('plan-form-name').disabled = true;
    document.getElementById('plan-form-display-name').value = p.display_name;
    document.getElementById('plan-form-description').value = p.description || '';
    document.getElementById('plan-form-concurrent').value = p.max_concurrent_missions;
    document.getElementById('plan-form-monthly').value = p.max_missions_per_month ?? '';
    document.getElementById('plan-form-targets').value = p.max_targets ?? '';
    document.getElementById('plan-form-api-hour').value = p.max_api_requests_per_hour;
    document.getElementById('plan-form-api-day').value = p.max_api_requests_per_day;
    document.getElementById('plan-form-sandboxes').value = p.sandbox_max_containers;
    document.getElementById('plan-form-storage').value = p.max_storage_mb;
    document.getElementById('plan-form-sort').value = p.sort_order;
    document.getElementById('plan-form-default').checked = p.is_default;
    document.getElementById('plan-form-active').checked = p.is_active;
    document.getElementById('plan-form-resource-tier').value = p.sandbox_resource_tier || 'medium';
    document.getElementById('plan-form-features').value = p.features ? JSON.stringify(p.features, null, 2) : '';
    // Set feature toggle checkboxes from features object
    const feats = p.features || {};
    document.querySelectorAll('.plan-feature-toggle').forEach(cb => {
        cb.checked = !!feats[cb.dataset.feature];
    });
    showModal('plan-modal');
}

document.getElementById('plan-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    const id = document.getElementById('plan-form-id').value;
    const isEdit = !!id;
    const body = {
        display_name: document.getElementById('plan-form-display-name').value,
        description: document.getElementById('plan-form-description').value || null,
        max_concurrent_missions: parseInt(document.getElementById('plan-form-concurrent').value) || 1,
        max_missions_per_month: parseInt(document.getElementById('plan-form-monthly').value) || null,
        max_targets: parseInt(document.getElementById('plan-form-targets').value) || null,
        max_api_requests_per_hour: parseInt(document.getElementById('plan-form-api-hour').value) || 100,
        max_api_requests_per_day: parseInt(document.getElementById('plan-form-api-day').value) || 1000,
        sandbox_max_containers: parseInt(document.getElementById('plan-form-sandboxes').value) || 1,
        max_storage_mb: parseInt(document.getElementById('plan-form-storage').value) || 500,
        sort_order: parseInt(document.getElementById('plan-form-sort').value) || 0,
        is_default: document.getElementById('plan-form-default').checked,
        sandbox_resource_tier: document.getElementById('plan-form-resource-tier').value,
    };
    if (isEdit) body.is_active = document.getElementById('plan-form-active').checked;
    // Merge feature toggles with JSON features
    const toggleFeatures = {};
    document.querySelectorAll('.plan-feature-toggle').forEach(cb => {
        toggleFeatures[cb.dataset.feature] = cb.checked;
    });
    const featuresRaw = document.getElementById('plan-form-features').value.trim();
    let extraFeatures = {};
    if (featuresRaw) {
        try { extraFeatures = JSON.parse(featuresRaw); } catch { _spectraToast('Invalid JSON in features field', 'error'); return; }
    }
    body.features = Object.assign({}, toggleFeatures, extraFeatures);
    if (!isEdit) body.name = document.getElementById('plan-form-name').value;

    try {
        const url = isEdit ? `/api/admin/plans/${id}` : '/api/admin/plans';
        const { error } = isEdit ? await spectraApi.put(url, body) : await spectraApi.post(url, body);
        if (error) throw new Error(error);
        _spectraToast(isEdit ? 'Plan updated' : 'Plan created', 'success');
        closeModal('plan-modal');
        loadPlans();
    } catch(e) { _spectraToast(e.message, 'error'); }
});

function deactivatePlan(planId, name) {
    showConfirm('Deactivate Plan', `Deactivate plan "${name}"?`, async () => {
        try {
            const { error } = await spectraApi.delete(`/api/admin/plans/${planId}`);
            if (error) throw new Error(error);
            _spectraToast('Plan deactivated', 'success');
            loadPlans();
        } catch(e) { _spectraToast('Failed', 'error'); }
    });
}

function activatePlan(planId, name) {
    showConfirm('Activate Plan', `Activate plan "${name}"?`, async () => {
        try {
            const { error } = await spectraApi.put(`/api/admin/plans/${planId}`, { is_active: true });
            if (error) throw new Error(error);
            _spectraToast('Plan activated', 'success');
            loadPlans();
        } catch(e) { _spectraToast('Failed', 'error'); }
    });
}

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

// ---- Services ----
const SERVICE_SETTINGS_MAP = {
    sandbox: { url: 'sandbox_orchestrator_url', timeout: 'sandbox_orchestrator_timeout', apiKey: 'sandbox_orchestrator_api_key', label: 'Sandbox Orchestrator', icon: 'box' },
};

let svcTopology = {};
let svcHealth = {};
let svcSettings = {};
let svcAutoRefreshTimer = null;

async function loadServices() {
    const grid = document.getElementById('svc-grid');
    grid.innerHTML = '<div class="col-span-full flex justify-center py-12"><span class="svc-spinner" style="width:24px;height:24px;"></span></div>';
    try {
        const [topoRes, healthRes, settingsRes] = await Promise.all([
            spectraApi.get('/api/v1/system/services/topology'),
            spectraApi.get('/api/v1/system/services/health'),
            spectraApi.get('/api/settings'),
        ]);
        if (!topoRes.error) svcTopology = topoRes.data;
        if (!healthRes.error) svcHealth = healthRes.data;
        if (!settingsRes.error) svcSettings = settingsRes.data;
        renderServiceCards();
    } catch(e) { console.error(e); _spectraToast('Error loading services', 'error'); grid.innerHTML = ''; }
    // Populate billing fields from settings
    loadBillingFields();
}

function loadBillingFields() {
    const prov = document.getElementById('billing-provider');
    const pk = document.getElementById('billing-stripe-pk');
    const sk = document.getElementById('billing-stripe-sk');
    const whs = document.getElementById('billing-stripe-whs');
    if (prov) prov.value = svcSettings.payment_provider || 'noop';
    if (pk) pk.value = svcSettings.stripe_publishable_key || '';
    // Secret fields show placeholder only
    if (sk) sk.value = '';
    if (whs) whs.value = '';
}

async function saveBillingSettings() {
    const body = { payment_provider: document.getElementById('billing-provider').value };
    const pk = document.getElementById('billing-stripe-pk').value;
    if (pk) body.stripe_publishable_key = pk;
    const sk = document.getElementById('billing-stripe-sk').value;
    if (sk) body.stripe_secret_key = sk;
    const whs = document.getElementById('billing-stripe-whs').value;
    if (whs) body.stripe_webhook_secret = whs;
    try {
        const r = await spectraApi.post('/api/settings', body);
        if (r.error) throw new Error(r.error);
        _spectraToast('Billing settings saved', 'success');
        loadServices();
    } catch(e) { _spectraToast(e.message, 'error'); }
}

function renderServiceCards() {
    const grid = document.getElementById('svc-grid');
    let localCount = 0, remoteCount = 0, disabledCount = 0;
    const cards = [];
    for (const [name, map] of Object.entries(SERVICE_SETTINGS_MAP)) {
        const topo = svcTopology[name] || {};
        const health = svcHealth[name] || topo.health || {};
        const mode = topo.mode || 'local';
        const url = topo.url || 'in-process';
        const status = health.status || 'unknown';
        const isDisabled = status === 'disabled';

        if (isDisabled) disabledCount++;
        else if (mode === 'remote') remoteCount++;
        else localCount++;

        const modeBadge = isDisabled ? 'disabled' : mode;
        const modeLabel = isDisabled ? 'DISABLED' : mode.toUpperCase();
        const statusLabels = { healthy: 'Healthy', unhealthy: 'Unhealthy', unknown: 'Unknown', no_health_check: 'No check', disabled: 'Disabled', error: 'Error' };

        cards.push(`
            <div class="service-card glass-panel rounded-xl p-5">
                <div class="flex items-start justify-between mb-3">
                    <div class="flex items-center gap-2">
                        <i data-lucide="${map.icon}" class="w-4 h-4 inline-block text-violet-400"></i>
                        <h3 class="text-sm font-semibold text-white">${escapeHtml(map.label)}</h3>
                    </div>
                    <span class="badge badge-${modeBadge}">${modeLabel}</span>
                </div>
                <div class="space-y-2 text-xs mb-4">
                    <div class="flex items-center justify-between">
                        <span class="text-slate-500">URL</span>
                        <span class="text-slate-300 truncate ml-2 max-w-[200px]" title="${escapeHtml(url)}">${escapeHtml(url === 'in-process' ? 'In-Process' : url)}</span>
                    </div>
                    <div class="flex items-center justify-between">
                        <span class="text-slate-500">Health</span>
                        <span class="flex items-center gap-1.5">
                            <span class="health-dot health-dot-${status}"></span>
                            <span class="text-slate-300">${statusLabels[status] || status}</span>
                        </span>
                    </div>
                    ${health.error ? `<div class="text-red-400 truncate" title="${escapeHtml(health.error)}">${escapeHtml(health.error)}</div>` : ''}
                    <div class="flex items-center justify-between">
                        <span class="text-slate-500">Last check</span>
                        <span class="text-slate-400">${health.checked_at ? formatDateTime(health.checked_at) : 'Never'}</span>
                    </div>
                </div>
                <div class="flex justify-end gap-3 pt-2 border-t border-white/5">
                    ${mode === 'remote' ? `<button onclick="deprovisionServer('${name}')" class="text-xs text-red-400 hover:text-red-300 transition-colors"><i data-lucide="trash-2" class="w-3.5 h-3.5 inline-block mr-1"></i>Remove Server</button>` : ''}
                    <button onclick="openServiceConfigModal('${name}')" class="text-xs text-slate-400 hover:text-violet-400 transition-colors">
                        <i data-lucide="settings" class="w-3.5 h-3.5 inline-block mr-1"></i>Configure
                    </button>
                </div>
            </div>`);
    }
    grid.innerHTML = cards.join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
    document.getElementById('svc-topology-summary').textContent =
        `${localCount} local · ${remoteCount} remote` + (disabledCount ? ` · ${disabledCount} disabled` : '');
}

async function checkAllHealth() {
    const btn = document.getElementById('svc-check-all-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="svc-spinner"></span> Checking…';
    try {
        const r = await spectraApi.get('/api/v1/system/services/health');
        if (r.error) throw new Error(r.error);
        svcHealth = r.data;
        renderServiceCards();
        _spectraToast('Health check complete', 'success');
    } catch(e) { _spectraToast(e.message, 'error'); }
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="heart-pulse" class="w-4 h-4 inline-block mr-1"></i> Check All Health';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function openServiceConfigModal(name) {
    const map = SERVICE_SETTINGS_MAP[name];
    if (!map) return;
    document.getElementById('service-form-name').value = name;
    document.getElementById('service-modal-title').textContent = 'Configure ' + map.label;

    // URL field
    const urlGroup = document.getElementById('svc-field-url-group');
    const urlInput = document.getElementById('svc-field-url');
    if (map.url) {
        urlGroup.style.display = '';
        urlInput.value = svcSettings[map.url] || '';
    } else { urlGroup.style.display = 'none'; }

    // Timeout field
    const timeoutGroup = document.getElementById('svc-field-timeout-group');
    const timeoutInput = document.getElementById('svc-field-timeout');
    if (map.timeout) {
        timeoutGroup.classList.remove('hidden');
        timeoutInput.value = svcSettings[map.timeout] || '';
    } else { timeoutGroup.classList.add('hidden'); }

    // API key field
    const apikeyGroup = document.getElementById('svc-field-apikey-group');
    const apikeyInput = document.getElementById('svc-field-apikey');
    if (map.apiKey) {
        apikeyGroup.classList.remove('hidden');
        apikeyInput.value = '';
    } else { apikeyGroup.classList.add('hidden'); }

    // Reset test result
    document.getElementById('svc-test-result').classList.add('hidden');
    showModal('service-modal');
}

async function testServiceConnection() {
    const resultEl = document.getElementById('svc-test-result');
    const btn = document.getElementById('svc-test-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="svc-spinner"></span> Testing…';
    resultEl.classList.add('hidden');
    try {
        const r = await spectraApi.get('/api/v1/system/services/health');
        if (r.error) throw new Error(r.error);
        const allHealth = r.data;
        const name = document.getElementById('service-form-name').value;
        const h = allHealth[name] || {};
        svcHealth = allHealth;
        if (h.status === 'healthy') {
            resultEl.className = 'text-xs p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400';
            resultEl.textContent = 'Connection successful — service is healthy';
        } else {
            resultEl.className = 'text-xs p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400';
            resultEl.textContent = 'Connection issue: ' + (h.error || h.status || 'unknown');
        }
        resultEl.classList.remove('hidden');
    } catch(e) {
        resultEl.className = 'text-xs p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400';
        resultEl.textContent = 'Test failed: ' + e.message;
        resultEl.classList.remove('hidden');
    }
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="plug" class="w-4 h-4 inline-block mr-1"></i> Test Connection';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

document.getElementById('service-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    const name = document.getElementById('service-form-name').value;
    const map = SERVICE_SETTINGS_MAP[name];
    if (!map) return;
    const body = {};
    if (map.url) body[map.url] = document.getElementById('svc-field-url').value || null;
    if (map.timeout) {
        const tv = document.getElementById('svc-field-timeout').value;
        if (tv) body[map.timeout] = parseInt(tv);
    }
    if (map.apiKey) {
        const kv = document.getElementById('svc-field-apikey').value;
        if (kv) body[map.apiKey] = kv;
    }
    try {
        const r = await spectraApi.post('/api/settings', body);
        if (r.error) throw new Error(r.error);
        _spectraToast(map.label + ' configuration saved', 'success');
        closeModal('service-modal');
        loadServices();
    } catch(e) { _spectraToast(e.message, 'error'); }
});

async function resetServiceToLocal() {
    const name = document.getElementById('service-form-name').value;
    const map = SERVICE_SETTINGS_MAP[name];
    if (!map) return;
    const body = {};
    if (map.url) body[map.url] = null;
    try {
        const r = await spectraApi.post('/api/settings', body);
        if (r.error) throw new Error(r.error);
        _spectraToast(map.label + ' reset to local', 'success');
        closeModal('service-modal');
        loadServices();
    } catch(e) { _spectraToast(e.message, 'error'); }
}

// Auto-refresh
document.getElementById('svc-auto-refresh').addEventListener('change', function() {
    if (this.checked) {
        svcAutoRefreshTimer = setInterval(async () => {
            try {
                const r = await spectraApi.get('/api/v1/system/services/health');
                if (!r.error) { svcHealth = r.data; renderServiceCards(); }
            } catch(e) { /* silent */ }
        }, 60000);
    } else {
        clearInterval(svcAutoRefreshTimer);
        svcAutoRefreshTimer = null;
    }
});

// ---- Server Provisioning ----
function openProvisionModal() {
    document.getElementById('provision-form').reset();
    document.getElementById('prov-test-result').classList.add('hidden');
    document.getElementById('prov-log-area').classList.add('hidden');
    document.getElementById('prov-logs').textContent = '';
    document.getElementById('prov-submit-btn').disabled = false;
    document.getElementById('prov-submit-btn').innerHTML = '<i data-lucide="rocket" class="w-4 h-4 inline-block mr-1"></i> Provision';
    toggleProvAuth();
    showModal('provision-modal');
}

function toggleProvAuth() {
    const method = document.querySelector('input[name="prov-auth"]:checked').value;
    document.getElementById('prov-password-group').style.display = method === 'password' ? '' : 'none';
    document.getElementById('prov-key-group').style.display = method === 'key' ? '' : 'none';
}

function updateProvisionDefaults() {
    const type = document.getElementById('prov-service-type').value;
    const portEl = document.getElementById('prov-service-port');
    const defaults = { sandbox_worker: 8080, app_worker: 5000, tools_worker: 5000, db_replica: 5432, db_backup: 22 };
    portEl.value = defaults[type] || 8080;
}

function getProvisionConfig() {
    const method = document.querySelector('input[name="prov-auth"]:checked').value;
    const cfg = {
        host: document.getElementById('prov-host').value.trim(),
        port: parseInt(document.getElementById('prov-port').value) || 22,
        username: document.getElementById('prov-username').value.trim() || 'root',
    };
    if (method === 'password') {
        cfg.password = document.getElementById('prov-password').value;
    } else {
        cfg.private_key = document.getElementById('prov-private-key').value;
    }
    return cfg;
}

async function testServerConnection() {
    const resultEl = document.getElementById('prov-test-result');
    const btn = document.getElementById('prov-test-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="svc-spinner"></span> Testing…';
    resultEl.classList.add('hidden');

    try {
        const cfg = getProvisionConfig();
        if (!cfg.host) throw new Error('Host is required');
        const r = await spectraApi.post('/api/admin/servers/verify', cfg);
        if (r.error) throw new Error(r.error);
        const d = r.data;
        if (d.connected) {
            resultEl.className = 'text-xs p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400';
            resultEl.textContent = `Connected — ${d.system_info || 'OK'}` + (d.docker_installed ? ' (Docker installed)' : ' (Docker NOT installed — will be auto-installed)');
        } else {
            resultEl.className = 'text-xs p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400';
            resultEl.textContent = 'Connection failed: ' + (d.error || 'unknown error');
        }
        resultEl.classList.remove('hidden');
    } catch(e) {
        resultEl.className = 'text-xs p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400';
        resultEl.textContent = 'Error: ' + e.message;
        resultEl.classList.remove('hidden');
    }
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="plug" class="w-4 h-4 inline-block mr-1"></i> Test Connection';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function provisionServer() {
    const cfg = getProvisionConfig();
    if (!cfg.host) { _spectraToast('Host is required', 'error'); return; }
    cfg.service_type = document.getElementById('prov-service-type').value;
    cfg.service_port = parseInt(document.getElementById('prov-service-port').value) || 8080;

    const btn = document.getElementById('prov-submit-btn');
    const logArea = document.getElementById('prov-log-area');
    const logPre = document.getElementById('prov-logs');
    btn.disabled = true;
    btn.innerHTML = '<span class="svc-spinner"></span> Provisioning…';
    logArea.classList.remove('hidden');
    logPre.textContent = 'Starting provisioning...\n';

    try {
        const r = await spectraApi.post('/api/admin/servers/provision', cfg);
        const d = r.data;
        logPre.textContent = (d.logs || []).join('\n');
        logPre.scrollTop = logPre.scrollHeight;

        if (d.success) {
            _spectraToast('Server provisioned successfully' + (d.health_check_passed ? ' (healthy)' : ' (health check pending)'), 'success');
            loadServices();
        } else {
            _spectraToast('Provisioning failed: ' + (d.error || 'unknown'), 'error');
        }
    } catch(e) {
        logPre.textContent += '\nError: ' + e.message;
        _spectraToast('Provisioning request failed', 'error');
    }
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="rocket" class="w-4 h-4 inline-block mr-1"></i> Provision';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function deprovisionServer(serviceType) {
    showConfirm('Remove Remote Server', `Remove the ${serviceType.replace('_',' ')} service from its remote server?`, async () => {
        _spectraPrompt('Enter the server host to deprovision:', (host) => {
            _spectraPrompt('Auth method (password/key):', (authMethod) => {
                authMethod = authMethod || 'password';
                const cfg = { host: host.trim(), service_type: serviceType };
                const finalize = (username) => {
                    cfg.username = username || 'root';
                    spectraApi.post('/api/admin/servers/deprovision', cfg)
                        .then(r => {
                            const d = r.data;
                            if (d.success) { _spectraToast('Server deprovisioned', 'success'); loadServices(); }
                            else { _spectraToast('Deprovision failed: ' + (d.error || 'unknown'), 'error'); }
                        })
                        .catch(() => _spectraToast('Deprovision request failed', 'error'));
                };
                if (authMethod === 'key') {
                    _spectraPrompt('Paste private key:', (key) => {
                        cfg.private_key = key;
                        _spectraPrompt('SSH username (default: root):', finalize, { placeholder: 'root' });
                    }, { title: 'Private Key' });
                } else {
                    _spectraPrompt('SSH password:', (pw) => {
                        cfg.password = pw;
                        _spectraPrompt('SSH username (default: root):', finalize, { placeholder: 'root' });
                    }, { title: 'SSH Password', inputType: 'password' });
                }
            }, { title: 'Auth Method', placeholder: 'password' });
        }, { title: 'Server Host', placeholder: 'hostname or IP' });
    });
}

// ---- Microservices Health Monitor ----
let svcHealthTimer = null;

async function pollMicroservicesHealth() {
    try {
        const r = await spectraApi.get('/api/admin/services');
        if (r.error) return;
        const data = r.data;
        const dotMap = { 'api': 'svc-api-dot', 'ai-svc': 'svc-ai-dot', 'scheduler': 'svc-scheduler-dot', 'worker': 'svc-worker-dot' };
        for (const svc of data.services || []) {
            const dot = document.getElementById(dotMap[svc.name]);
            if (!dot) continue;
            dot.className = 'health-dot health-dot-' + (svc.status === 'healthy' ? 'healthy' : svc.status === 'unhealthy' ? 'unhealthy' : 'unknown') + ' mx-auto';
        }
    } catch(e) { console.error('Microservices health poll error', e); }
}

function startSvcHealthPoll() {
    pollMicroservicesHealth();
    if (svcHealthTimer) clearInterval(svcHealthTimer);
    svcHealthTimer = setInterval(pollMicroservicesHealth, 15000);
}

// Start polling when services tab active
const origShowSection = window.showSection;
window.showSection = function(name) {
    if (typeof origShowSection === 'function') origShowSection(name);
    if (name === 'services') { startSvcHealthPoll(); refreshNodesList(); }
    else if (svcHealthTimer) { clearInterval(svcHealthTimer); svcHealthTimer = null; }
};

// ---- Server Nodes Management ----
async function refreshNodesList() {
    const container = document.getElementById('nodes-list');
    container.innerHTML = '<p class="text-xs text-slate-500">Loading...</p>';
    try {
        const r = await spectraApi.get('/api/admin/services/nodes');
        if (r.error) throw new Error(r.error);
        const data = r.data;
        if (!data.nodes || data.nodes.length === 0) {
            container.innerHTML = '<p class="text-xs text-slate-500">No server nodes registered. Use "Add Remote Server" above.</p>';
            return;
        }
        container.innerHTML = data.nodes.map(n => `
            <div class="flex items-center justify-between p-3 rounded-lg bg-slate-800/50 border border-white/5">
                <div class="flex items-center gap-3">
                    <span class="health-dot health-dot-${n.health_status || 'unknown'}"></span>
                    <div>
                        <div class="text-sm font-medium text-white">${escapeHtml(n.name)}</div>
                        <div class="text-xs text-slate-500">${escapeHtml(n.url)} · ${escapeHtml(n.service_type)} · SSH ${escapeHtml(n.ssh_user || 'root')}:${n.ssh_port || 22}</div>
                    </div>
                </div>
                <div class="flex items-center gap-2">
                    ${n.deployed_services ? `<span class="text-xs text-emerald-400">${(n.deployed_services.length || 0)} services</span>` : ''}
                    <button onclick="deployToNode(${n.id}, '${escapeHtml(n.name)}')" class="px-2 py-1 bg-violet-600 hover:bg-violet-500 text-white rounded text-xs transition-colors">
                        <i data-lucide="rocket" class="w-3.5 h-3.5 inline-block mr-1"></i>Deploy
                    </button>
                    <button onclick="viewNodeLogs(${n.id})" class="px-2 py-1 text-xs text-slate-400 hover:text-white transition-colors">
                        <i data-lucide="file-text" class="w-3.5 h-3.5 inline-block mr-1"></i>Logs
                    </button>
                </div>
            </div>
        `).join('');
    } catch(e) { container.innerHTML = '<p class="text-xs text-red-400">Error loading nodes</p>'; }
}

async function deployToNode(nodeId, nodeName) {
    showConfirm('Deploy Services', `Deploy Spectra services to ${nodeName}? This may take several minutes.`, async () => {
        _spectraToast('Starting deployment to ' + nodeName + '...', 'success');
    try {
        const r = await spectraApi.post(`/api/admin/services/nodes/${nodeId}/deploy`, { services: null, harden: true });
        const data = r.data;
        if (data.status === 'complete') {
            _spectraToast('Deployment successful!', 'success');
        } else {
            _spectraToast('Deployment failed: ' + (data.message || 'unknown'), 'error');
        }
        // Show logs
        document.getElementById('deploy-logs-content').textContent = (data.logs || []).join('\n');
        showModal('deploy-logs-modal');
        refreshNodesList();
    } catch(e) { _spectraToast('Deployment request failed', 'error'); }
    });
}

async function viewNodeLogs(nodeId) {
    try {
        const r = await spectraApi.get(`/api/admin/services/nodes/${nodeId}/logs`);
        const data = r.data;
        document.getElementById('deploy-logs-content').textContent = (data.logs || []).join('\n') || 'No logs available.';
        showModal('deploy-logs-modal');
    } catch(e) { _spectraToast('Failed to load logs', 'error'); }
}

// ---- Content Management ----
let currentContentType = 'review';

function switchContentType(type) {
    currentContentType = type;
    document.querySelectorAll('.content-type-btn').forEach(b => {
        b.classList.remove('active', 'bg-violet-600/20', 'text-violet-300', 'border-violet-500/30');
        b.classList.add('bg-white/5', 'text-slate-400', 'border-white/10');
    });
    event.target.classList.add('active', 'bg-violet-600/20', 'text-violet-300', 'border-violet-500/30');
    event.target.classList.remove('bg-white/5', 'text-slate-400', 'border-white/10');
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
                    <button onclick="editContent('${item.id}')" class="text-xs text-violet-400 hover:text-violet-300"><i data-lucide="edit" class="w-3.5 h-3.5 inline-block"></i></button>
                    <button onclick="deleteContent('${item.id}')" class="text-xs text-red-400 hover:text-red-300"><i data-lucide="trash-2" class="w-3.5 h-3.5 inline-block"></i></button>
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
                <td class="px-4 py-3 text-xs text-slate-400">${b.created_at ? new Date(b.created_at).toLocaleString() : '—'}</td>
                <td class="px-4 py-3 text-right">
                    <button onclick="restoreBackup('${b.path || b.filename}')" class="px-2.5 py-1 rounded bg-amber-600/20 text-amber-300 text-xs hover:bg-amber-600/30 transition-colors">
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
            container.innerHTML = '<p class="text-sm text-slate-500 text-center py-8">No revertible actions yet.</p>';
            return;
        }
        container.innerHTML = data.map(s => `
            <div class="flex items-center justify-between p-3 rounded-lg bg-black/20 border border-white/5">
                <div class="flex items-center gap-3 min-w-0">
                    <i data-lucide="undo-2" class="w-4 h-4 shrink-0 text-slate-400"></i>
                    <div class="min-w-0">
                        <p class="text-sm text-white truncate">${escapeHtml(s.action)}</p>
                        <p class="text-xs text-slate-500">${escapeHtml(s.entity_type)} &middot; ${new Date(s.created_at).toLocaleString()}</p>
                    </div>
                </div>
                <button onclick="performRollback('${s.id}')" class="ml-4 px-3 py-1.5 text-xs bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 rounded-lg border border-amber-500/30 transition-colors whitespace-nowrap flex items-center gap-1.5">
                    <i data-lucide="rotate-ccw" class="w-3 h-3 inline-block"></i> Revert
                </button>
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

// ---- Init ----
loadStats();
// Pre-load plans for user form plan select
spectraApi.get('/api/admin/plans').then(r => !r.error ? r.data : []).then(p => { allPlans = p; }).catch(() => {});

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
