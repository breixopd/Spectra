// ---- Scaling & Infrastructure ----
let scalingRefreshTimer = null;

async function loadScalingStatus() {
    try {
        const { data, error } = await spectraApi.get('/api/admin/scaling/status');
        if (error) throw new Error(error);
        populateScalingStatus(data);
        populateScalingForm(data.config || {});
        startScalingAutoRefresh();
    } catch(e) { console.error('Load scaling status error', e); _spectraToast('Error loading scaling status', 'error'); }
}

function populateScalingStatus(data) {
    const scaler = data.scaler || {};
    const policies = scaler.policies || {};
    const infra = scaler.infrastructure || {};
    const queue = data.queue || {};

    // Replica min/max display
    const workerP = policies.worker || {};
    const apiP = policies.api || {};
    const aiP = policies.ai || {};
    document.getElementById('scaling-worker-replicas').textContent = workerP.min_replicas != null ? `${workerP.min_replicas}–${workerP.max_replicas}` : '—';
    document.getElementById('scaling-api-replicas').textContent = apiP.min_replicas != null ? `${apiP.min_replicas}–${apiP.max_replicas}` : '—';
    document.getElementById('scaling-ai-replicas').textContent = aiP.max_replicas != null ? `1–${aiP.max_replicas}` : '—';

    // Queue
    document.getElementById('scaling-queue-depth').textContent = queue.pending ?? queue.queue_depth ?? '—';

    // Infrastructure indicators
    for (const [name, dotId, statusId] of [['postgres', 'scaling-pg-dot', 'scaling-pg-status'], ['redis', 'scaling-redis-dot', 'scaling-redis-status'], ['garage', 'scaling-storage-dot', 'scaling-storage-status']]) {
        const mon = infra[name] || {};
        const dot = document.getElementById(dotId);
        const statusEl = document.getElementById(statusId);
        if (mon.enabled) {
            dot.className = 'health-dot health-dot-healthy';
            statusEl.textContent = `Monitoring (threshold: ${mon.alert_threshold_pct}%)`;
        } else {
            dot.className = 'health-dot health-dot-unknown';
            statusEl.textContent = 'Disabled';
        }
    }

    // Last action (from cooldown remaining)
    const lastActionParts = [];
    for (const [role, p] of Object.entries(policies)) {
        if (p.cooldown_remaining_secs > 0) {
            lastActionParts.push(`${role}: cooldown ${Math.round(p.cooldown_remaining_secs)}s remaining`);
        }
    }
    document.getElementById('scaling-last-action').textContent = lastActionParts.length
        ? 'Recent scaling: ' + lastActionParts.join(' · ')
        : 'Last scaling action: none recently';
}

function populateScalingForm(cfg) {
    const el = (id) => document.getElementById(id);
    if (el('scaling-enabled')) el('scaling-enabled').checked = cfg.autoscale_enabled ?? false;
    if (el('scaling-worker-min')) el('scaling-worker-min').value = cfg.autoscale_worker_min ?? 1;
    if (el('scaling-worker-max')) el('scaling-worker-max').value = cfg.autoscale_worker_max ?? 10;
    if (el('scaling-api-min')) el('scaling-api-min').value = cfg.autoscale_api_min ?? 2;
    if (el('scaling-api-max')) el('scaling-api-max').value = cfg.autoscale_api_max ?? 8;
    if (el('scaling-ai-max')) el('scaling-ai-max').value = cfg.autoscale_ai_max ?? 4;
    if (el('scaling-queue-threshold')) el('scaling-queue-threshold').value = cfg.autoscale_queue_threshold ?? 5;
    if (el('scaling-cooldown')) el('scaling-cooldown').value = cfg.autoscale_cooldown_secs ?? 300;
    if (el('scaling-cpu-up')) el('scaling-cpu-up').value = cfg.autoscale_cpu_up_threshold ?? 75;
    if (el('scaling-cpu-down')) el('scaling-cpu-down').value = cfg.autoscale_cpu_down_threshold ?? 25;
    if (el('scaling-infra-enabled')) el('scaling-infra-enabled').checked = cfg.infra_monitor_enabled ?? true;
    if (el('scaling-pg-threshold')) el('scaling-pg-threshold').value = cfg.infra_monitor_pg_threshold ?? 80;
    if (el('scaling-redis-threshold')) el('scaling-redis-threshold').value = cfg.infra_monitor_redis_threshold ?? 85;
    if (el('scaling-storage-threshold')) el('scaling-storage-threshold').value = cfg.infra_monitor_storage_threshold ?? 90;
}

async function saveScalingConfig(e) {
    e.preventDefault();
    const payload = {
        autoscale_enabled: document.getElementById('scaling-enabled').checked,
        autoscale_worker_min: parseInt(document.getElementById('scaling-worker-min').value),
        autoscale_worker_max: parseInt(document.getElementById('scaling-worker-max').value),
        autoscale_api_min: parseInt(document.getElementById('scaling-api-min').value),
        autoscale_api_max: parseInt(document.getElementById('scaling-api-max').value),
        autoscale_ai_max: parseInt(document.getElementById('scaling-ai-max').value),
        autoscale_queue_threshold: parseInt(document.getElementById('scaling-queue-threshold').value),
        autoscale_cooldown_secs: parseInt(document.getElementById('scaling-cooldown').value),
        autoscale_cpu_up_threshold: parseInt(document.getElementById('scaling-cpu-up').value),
        autoscale_cpu_down_threshold: parseInt(document.getElementById('scaling-cpu-down').value),
        infra_monitor_enabled: document.getElementById('scaling-infra-enabled').checked,
        infra_monitor_pg_threshold: parseInt(document.getElementById('scaling-pg-threshold').value),
        infra_monitor_redis_threshold: parseInt(document.getElementById('scaling-redis-threshold').value),
        infra_monitor_storage_threshold: parseInt(document.getElementById('scaling-storage-threshold').value),
    };
    try {
        const { error } = await spectraApi.put('/api/admin/scaling/config', payload);
        if (error) throw new Error(error);
        _spectraToast('Scaling configuration saved', 'success');
        loadScalingStatus();
    } catch(e) { _spectraToast('Failed to save scaling config: ' + e.message, 'error'); }
}

function refreshScalingStatus() {
    loadScalingStatus();
}

function startScalingAutoRefresh() {
    if (scalingRefreshTimer) clearInterval(scalingRefreshTimer);
    scalingRefreshTimer = setInterval(async () => {
        try {
            const { data, error } = await spectraApi.get('/api/admin/scaling/status');
            if (!error && data) populateScalingStatus(data);
        } catch(e) { /* silent */ }
    }, 30000);
}

const scalingForm = document.getElementById('scaling-config-form');
if (scalingForm) scalingForm.addEventListener('submit', saveScalingConfig);

