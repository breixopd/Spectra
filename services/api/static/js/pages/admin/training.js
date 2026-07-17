// ---- Model Training ----
let trainingProviders = [];

function trainingBadge(status) {
    const key = String(status || 'unknown').toLowerCase();
    const classes = {
        completed: 'bg-emerald-500/20 text-emerald-300',
        prepared: 'bg-cyan-500/20 text-cyan-300',
        pending: 'bg-amber-500/20 text-amber-300',
        preparing: 'bg-blue-500/20 text-blue-300',
        failed: 'bg-rose-500/20 text-rose-300',
        cancelled: 'bg-slate-500/20 text-slate-300',
        configurable: 'bg-emerald-500/20 text-emerald-300',
        available: 'bg-emerald-500/20 text-emerald-300'
    }[key] || 'bg-slate-500/20 text-slate-300';
    return `<span class="badge ${classes}">${escapeHtml(key)}</span>`;
}

async function loadTraining() {
    await Promise.all([
        loadTrainingStats(),
        loadTrainingProviders(),
        loadTrainingSamples(),
        loadTrainingJobs()
    ]);
}

async function loadTrainingStats() {
    const { data, error } = await spectraApi.get('/api/v1/admin/training/stats');
    if (error) {
        showToast('Failed to load training stats', 'error');
        return;
    }
    const types = data.types || {};
    document.getElementById('training-total-samples').textContent = data.total || 0;
    document.getElementById('training-sample-types').textContent = Object.keys(types).length;
}

async function loadTrainingProviders() {
    const { data, error } = await spectraApi.get('/api/v1/admin/training/providers');
    if (error) {
        showToast('Failed to load training providers', 'error');
        return;
    }
    trainingProviders = data.providers || [];
    document.getElementById('training-provider-count').textContent = trainingProviders.length;
    const select = document.getElementById('training-provider');
    select.innerHTML = trainingProviders.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join('');
    document.getElementById('training-providers-list').innerHTML = trainingProviders.map(p => `
        <div class="rounded-lg border border-white/10 bg-black/20 p-3">
            <div class="flex items-start justify-between gap-2">
                <div>
                    <p class="text-sm font-semibold text-white">${escapeHtml(p.name)}</p>
                    <p class="text-xs text-slate-500 mt-1">${escapeHtml(p.description || '')}</p>
                </div>
                ${trainingBadge(p.status)}
            </div>
            <p class="text-[11px] text-slate-500 mt-2">Config: ${(p.config_fields || []).map(escapeHtml).join(', ') || 'none'}</p>
        </div>
    `).join('');
}

async function loadTrainingSamples() {
    const { data, error } = await spectraApi.get('/api/v1/admin/training/samples?per_page=25');
    if (error) {
        showToast('Failed to load training samples', 'error');
        return;
    }
    const samples = data.items || [];
    const tbody = document.getElementById('training-samples-tbody');
    if (!samples.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="px-4 py-6 text-center text-slate-500">No samples captured yet</td></tr>';
        return;
    }
    tbody.innerHTML = samples.map(s => `
        <tr class="border-b border-white/5">
            <td class="px-4 py-3 text-xs text-slate-300">${escapeHtml(s.sample_type)}</td>
            <td class="px-4 py-3 text-xs text-slate-500 max-w-xs truncate">${escapeHtml(s.input_preview || '')}</td>
            <td class="px-4 py-3 text-right text-xs text-slate-300">${s.quality_score ?? '—'}</td>
            <td class="px-4 py-3 text-right">
                ${s.is_approved ? trainingBadge('available') : `<button type="button" data-action="approveTrainingSample" data-value="${escapeHtml(s.id)}" class="text-xs text-emerald-400 hover:text-emerald-300">Approve</button>`}
            </td>
        </tr>
    `).join('');
}

async function loadTrainingJobs() {
    const { data, error } = await spectraApi.get('/api/v1/admin/training/jobs');
    if (error) {
        showToast('Failed to load training jobs', 'error');
        return;
    }
    const jobs = data.jobs || [];
    const tbody = document.getElementById('training-jobs-tbody');
    if (!jobs.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="px-4 py-6 text-center text-slate-500">No fine-tuning jobs yet</td></tr>';
        return;
    }
    tbody.innerHTML = jobs.map(j => `
        <tr class="border-b border-white/5" title="${escapeHtml(j.error_message || j.output_model_path || '')}">
            <td class="px-4 py-3">
                <p class="text-sm text-white">${escapeHtml(j.name)}</p>
                <p class="text-xs text-slate-500">${escapeHtml(j.base_model || 'base model not set')}</p>
            </td>
            <td class="px-4 py-3 text-xs text-slate-400">${escapeHtml(j.provider || 'local')}</td>
            <td class="px-4 py-3 text-right text-xs text-slate-300">${j.sample_count || 0}</td>
            <td class="px-4 py-3 text-right">${trainingBadge(j.status)}</td>
        </tr>
    `).join('');
}

async function approveTrainingSample(sampleId) {
    const { error } = await spectraApi.post(`/api/v1/admin/training/samples/${sampleId}/approve`, {});
    if (error) {
        showToast('Failed to approve sample', 'error');
        return;
    }
    showToast('Training sample approved', 'success');
    await loadTrainingSamples();
}

async function bulkApproveTrainingSamples() {
    const { data, error } = await spectraApi.post('/api/v1/admin/training/samples/bulk-approve', { min_quality: 0.7 });
    if (error) {
        showToast('Bulk approval failed', 'error');
        return;
    }
    showToast(`Approved ${data.approved_count || 0} samples`, 'success');
    await loadTraining();
}

async function createTrainingJob() {
    const sampleTypes = document.getElementById('training-sample-types-input').value
        .split(',')
        .map(v => v.trim())
        .filter(Boolean);
    const body = {
        name: document.getElementById('training-job-name').value || undefined,
        base_model: document.getElementById('training-base-model').value || 'local/base',
        provider: document.getElementById('training-provider').value || 'local',
        sample_types: sampleTypes,
        min_quality: parseFloat(document.getElementById('training-min-quality').value) || 0
    };
    const { error } = await spectraApi.post('/api/v1/admin/training/jobs', body);
    if (error) {
        showToast(`Failed to queue training job: ${error}`, 'error');
        return;
    }
    showToast('Training job queued', 'success');
    await loadTrainingJobs();
}
