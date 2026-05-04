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
    } catch(e) { console.error(e); showToast('Error loading users', 'error'); }
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
    document.getElementById('user-form-plan').dataset.initialValue = '';
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
    document.getElementById('user-form-plan').dataset.initialValue = u.plan_id || '';
    showModal('user-modal');
}

function populatePlanSelect(selectedId) {
    const sel = document.getElementById('user-form-plan');
    sel.innerHTML = '<option value="">None</option>';
    (Array.isArray(allPlans) ? allPlans : []).filter(p => p.is_active).forEach(p => {
        sel.innerHTML += `<option value="${escapeHtml(String(p.id || ''))}" ${p.id === selectedId ? 'selected' : ''}>${escapeHtml(p.display_name)}</option>`;
    });
}

document.getElementById('user-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    const id = document.getElementById('user-form-id').value;
    const isEdit = !!id;
    const body = {};
    const planField = document.getElementById('user-form-plan');
    const selectedPlanId = planField.value || null;

    if (!isEdit) {
        body.username = document.getElementById('user-form-username').value;
        body.password = document.getElementById('user-form-password').value;
        body.plan_id = selectedPlanId;
    }
    body.email = document.getElementById('user-form-email').value;
    body.role = document.getElementById('user-form-role').value;
    if (isEdit) {
        body.is_active = document.getElementById('user-form-status').value === 'true';
        if ((planField.dataset.initialValue || '') !== (selectedPlanId || '')) {
            body.plan_id = selectedPlanId;
        }
    }

    try {
        const url = isEdit ? `/api/admin/users/${id}` : '/api/admin/users';
        const { data, error } = isEdit ? await spectraApi.put(url, body) : await spectraApi.post(url, body);
        if (error) throw new Error(error);
        let successMessage = isEdit ? 'User updated' : 'User created';
        if (!isEdit && data?.activation_url) {
            successMessage = `User created. Share the activation link manually: ${data.activation_url}`;
        }
        showToast(successMessage, 'success');
        closeModal('user-modal');
        loadUsers();
    } catch(e) { showToast(e.message, 'error'); }
});

function resetPassword(userId, username) {
    showConfirm('Reset Password', `Send a password reset email to ${username}?`, async () => {
        try {
            const { data, error } = await spectraApi.post(`/api/admin/users/${userId}/reset-password`);
            if (error) throw new Error(error);
            showToast(data?.detail || 'Password reset email sent', 'success');
        } catch(e) { showToast(e.message || 'Password reset failed', 'error'); }
    });
}

function deactivateUser(userId, username) {
    showConfirm('Deactivate User', `Deactivate user "${username}"? They will lose access.`, async () => {
        try {
            const { error } = await spectraApi.delete(`/api/admin/users/${userId}`);
            if (error) throw new Error(error);
            showToast('User deactivated', 'success');
            loadUsers();
        } catch(e) { showToast(e.message, 'error'); }
    });
}

