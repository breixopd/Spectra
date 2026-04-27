let usersPage = 1, usersPerPage = 20;
let auditPage = 1, auditPerPage = 50;
let allPlans = [];
let currentUsers = [];

const USER_ROLE_BADGE_CLASSES = {
    admin: 'badge-admin',
    operator: 'badge-operator',
    staff: 'badge-operator',
    user: 'badge-viewer',
    viewer: 'badge-viewer'
};

function getUserRoleBadgeClass(role) {
    return USER_ROLE_BADGE_CLASSES[String(role || 'viewer').toLowerCase()] || USER_ROLE_BADGE_CLASSES.viewer;
}

function getUserRoleLabel(role) {
    return escapeHtml(String(role || 'viewer'));
}

let statsErrorVisible = false;

function quickCreateUser() { switchSection('users'); openCreateUserModal(); }
function quickCreatePlan() { switchSection('plans'); openCreatePlanModal(); }

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

const showModal = (id) => window.showModal(id);
const closeModal = (id) => window.closeModal(id);

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

function exposeAdminHandlers() {
    [
        'toggleMaintenance', 'switchSection', 'openCreateUserModal', 'openEditUserModal',
        'resetPassword', 'deactivateUser', 'openCreatePlanModal', 'openEditPlanModal',
        'activatePlan', 'deactivatePlan', 'checkAllHealth', 'openServiceConfigModal',
        'testServiceConnection', 'resetServiceToLocal', 'saveBillingSettings',
        'openProvisionModal', 'toggleProvAuth', 'updateProvisionDefaults',
        'testServerConnection', 'provisionServer', 'deprovisionServer', 'refreshNodesList',
        'deployToNode', 'viewNodeLogs', 'switchContentType', 'quickCreateUser',
        'quickCreatePlan', 'openContentModal', 'closeContentModal', 'editContent',
        'deleteContent', 'testTZConnection', 'saveTZConfig', 'loadTZConfig',
        'createBackup', 'restoreBackup', 'saveEmailTemplate', 'sendTestEmail',
        'loadTZStatus', 'loadTZInferences', 'loadTZFunctionStats', 'loadRollbackSnapshots',
        'performRollback', 'loadScalingStatus', 'refreshScalingStatus', 'saveScalingConfig',
        'scalingAction',
    ].forEach((name) => {
        if (typeof window[name] === 'function') {
            window[name] = window[name];
        }
    });
}

function initializeAdminPage() {
    exposeAdminHandlers();
    const hash = window.location.hash.slice(1);
    if (hash && document.getElementById('section-' + hash)) {
        switchSection(hash);
    } else {
        loadStats();
    }
    spectraApi.get('/api/admin/plans')
        .then(r => !r.error ? r.data : [])
        .then(p => { allPlans = Array.isArray(p) ? p : []; })
        .catch(() => {});
}

document.addEventListener('DOMContentLoaded', initializeAdminPage);
