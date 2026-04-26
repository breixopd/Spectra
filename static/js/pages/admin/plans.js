// ---- Plans ----
async function loadPlans() {
    try {
        const { data, error } = await spectraApi.get('/api/admin/plans');
        if (error) throw new Error(error);
        allPlans = Array.isArray(data) ? data : [];
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
                    ${p.allow_self_service_registration ? '<span class="badge bg-emerald-500/20 text-emerald-300">Self-service signup</span>' : ''}
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
                <button data-action="openEditPlanModal" data-value='${JSON.stringify(p).replace(/'/g,"&#39;")}' class="text-xs text-slate-400 hover:text-violet-400 transition-colors"><i data-lucide="edit" class="w-3.5 h-3.5 inline-block mr-1"></i>Edit</button>
                ${p.is_active ? `<button data-action="deactivatePlan" data-value="${p.id}" data-plan-name="${escapeHtml(p.name)}" class="text-xs text-slate-400 hover:text-red-400 transition-colors"><i data-lucide="ban" class="w-3.5 h-3.5 inline-block mr-1"></i>Deactivate</button>` : `<button data-action="activatePlan" data-value="${p.id}" data-plan-name="${escapeHtml(p.name)}" class="text-xs text-slate-400 hover:text-emerald-400 transition-colors"><i data-lucide="check-circle" class="w-3.5 h-3.5 inline-block mr-1"></i>Activate</button>`}
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
    if (typeof p === 'string') { try { p = JSON.parse(p); } catch(_) { return; } }
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
    document.getElementById('plan-form-self-service').checked = !!p.allow_self_service_registration;
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
        allow_self_service_registration: document.getElementById('plan-form-self-service').checked,
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

function deactivatePlan(planId, el) {
    const name = (typeof el === 'object' && el?.dataset?.planName) ? el.dataset.planName : '';
    showConfirm('Deactivate Plan', `Deactivate plan "${name}"?`, async () => {
        try {
            const { error } = await spectraApi.delete(`/api/admin/plans/${planId}`);
            if (error) throw new Error(error);
            _spectraToast('Plan deactivated', 'success');
            loadPlans();
        } catch(e) { _spectraToast('Failed', 'error'); }
    });
}

function activatePlan(planId, el) {
    const name = (typeof el === 'object' && el?.dataset?.planName) ? el.dataset.planName : '';
    showConfirm('Activate Plan', `Activate plan "${name}"?`, async () => {
        try {
            const { error } = await spectraApi.put(`/api/admin/plans/${planId}`, { is_active: true });
            if (error) throw new Error(error);
            _spectraToast('Plan activated', 'success');
            loadPlans();
        } catch(e) { _spectraToast('Failed', 'error'); }
    });
}

