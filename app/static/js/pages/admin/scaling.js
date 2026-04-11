// ---- Scaling & Infrastructure ----
let scalingRefreshTimer = null;
let _healActionsLog = [];

async function loadScalingStatus() {
    try {
        const [statusRes, metricsRes] = await Promise.all([
            spectraApi.get('/api/admin/scaling/status'),
            spectraApi.get('/api/admin/scaling/metrics'),
        ]);
        if (statusRes.error) throw new Error(statusRes.error);
        const statusData = statusRes.data;
        const metricsData = metricsRes.error ? null : metricsRes.data;

        populateScalingForm(statusData.config || {});
        populateInfraStatus(statusData);
        if (metricsData) populateClusterMetrics(metricsData);
        startScalingAutoRefresh();
    } catch(e) { console.error('Load scaling status error', e); _spectraToast('Error loading scaling status', 'error'); }
}

// --- Cluster Metrics (from /api/admin/scaling/metrics) ---

function populateClusterMetrics(data) {
    const sys = data.system || {};
    const q = data.queue || {};
    const nodes = data.nodes || {};
    const services = data.services || {};

    // System gauges
    _setGauge('gauge-cpu', sys.cpu_percent);
    _setText('sys-cpu-pct', _fmtPct(sys.cpu_percent));
    _setText('sys-load-avg', `load ${sys.load_avg_1m ?? '—'}`);

    _setGauge('gauge-mem', sys.memory_percent);
    _setText('sys-mem-pct', _fmtPct(sys.memory_percent));
    _setText('sys-mem-avail', `${Math.round(sys.memory_available_mb ?? 0)} MB free`);

    _setGauge('gauge-disk', sys.disk_percent);
    _setText('sys-disk-pct', _fmtPct(sys.disk_percent));
    _setText('sys-disk-free', `${sys.disk_free_gb ?? '—'} GB free`);

    // Nodes
    _setText('nodes-healthy-count', nodes.healthy ?? '—');
    _setText('nodes-unhealthy-count', nodes.unhealthy ?? '0');
    _setText('nodes-total-count', nodes.total ?? '—');
    const unhDot = document.getElementById('nodes-unhealthy-dot');
    if (unhDot) unhDot.className = `inline-block w-2.5 h-2.5 rounded-full ${(nodes.unhealthy > 0) ? 'bg-rose-500' : 'bg-slate-600'}`;

    // Service table
    _populateServiceTable(services);

    // Queue
    _setText('queue-depth', q.depth ?? '—');
    _setText('queue-in-progress', q.in_progress ?? '—');
    _setText('queue-avg-wait', q.avg_wait_secs != null ? `${q.avg_wait_secs}s` : '—');
    _setText('queue-oldest-job', q.oldest_job_secs != null ? _fmtDuration(q.oldest_job_secs) : '—');

    // Queue pressure bar (heuristic: depth / threshold * 100, cap at 100)
    const threshold = parseInt(document.getElementById('scaling-queue-threshold')?.value) || 5;
    const pressure = Math.min(100, Math.round(((q.depth || 0) / threshold) * 100));
    _setGauge('queue-pressure-bar', pressure);
    const pressureLabel = document.getElementById('queue-pressure-label');
    if (pressureLabel) {
        const level = pressure < 30 ? 'Low' : pressure < 70 ? 'Moderate' : 'High';
        pressureLabel.textContent = `${level} (${pressure}%)`;
    }
    // Color the pressure bar based on level
    const pressureBar = document.getElementById('queue-pressure-bar');
    if (pressureBar) {
        pressureBar.className = pressureBar.className.replace(/bg-\S+/, pressure < 30 ? 'bg-emerald-500' : pressure < 70 ? 'bg-amber-500' : 'bg-rose-500');
    }
}

function _populateServiceTable(services) {
    const tbody = document.getElementById('service-status-tbody');
    if (!tbody) return;
    if (!services || Object.keys(services).length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-slate-500 text-xs">No service data available</td></tr>';
        return;
    }
    const rows = [];
    for (const [name, svc] of Object.entries(services)) {
        const healthDot = svc.healthy
            ? '<span class="inline-block w-2 h-2 rounded-full bg-emerald-500" title="Healthy"></span>'
            : '<span class="inline-block w-2 h-2 rounded-full bg-rose-500" title="Unhealthy"></span>';
        const failedBadge = svc.failed_tasks > 0
            ? `<span class="text-rose-400 font-medium">${svc.failed_tasks}</span>
               <button onclick="scalingAction('heal','${_escHtml(name)}')" class="ml-1 px-1.5 py-0.5 text-[10px] bg-rose-600/20 hover:bg-rose-600/40 text-rose-300 rounded transition-colors" title="Auto-heal">heal</button>`
            : '<span class="text-slate-500">0</span>';
        rows.push(`<tr class="text-slate-300">
            <td class="py-2 pr-4 text-xs font-medium text-white">${_escHtml(name)}</td>
            <td class="py-2 px-2 text-center text-xs">${svc.running_tasks ?? svc.replicas ?? 0}/${svc.desired_replicas ?? 0}</td>
            <td class="py-2 px-2 text-center text-xs">${svc.cpu_percent != null ? svc.cpu_percent + '%' : '—'}</td>
            <td class="py-2 px-2 text-center text-xs">${svc.memory_mb != null ? Math.round(svc.memory_mb) + ' MB' : '—'}</td>
            <td class="py-2 px-2 text-center">${healthDot}</td>
            <td class="py-2 px-2 text-center text-xs">${failedBadge}</td>
            <td class="py-2 px-2 text-center text-xs whitespace-nowrap">
                <button onclick="scalingAction('scale_down','${_escHtml(name)}')" class="px-1.5 py-0.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded text-[10px] transition-colors" title="Scale down">−</button>
                <button onclick="scalingAction('scale_up','${_escHtml(name)}')" class="px-1.5 py-0.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded text-[10px] transition-colors" title="Scale up">+</button>
                <button onclick="scalingAction('restart','${_escHtml(name)}')" class="px-1.5 py-0.5 bg-slate-700 hover:bg-amber-700/60 text-slate-300 rounded text-[10px] transition-colors" title="Force restart">↻</button>
            </td>
        </tr>`);
    }
    tbody.innerHTML = rows.join('');
}

// --- Infrastructure & policy status (from /api/admin/scaling/status) ---

function populateInfraStatus(data) {
    const scaler = data.scaler || {};
    const infra = scaler.infrastructure || {};
    const policies = scaler.policies || {};

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

// --- Scaling actions ---

async function scalingAction(action, service) {
    try {
        _spectraToast(`Executing ${action} on ${service}…`, 'info');
        const { data, error } = await spectraApi.post('/api/admin/scaling/action', { action, service });
        if (error) throw new Error(error);
        if (data.success) {
            _spectraToast(`${action} on ${service} succeeded`, 'success');
            if (action === 'heal' && data.actions) {
                data.actions.forEach(a => _addHealLogEntry(a));
            }
        } else {
            _spectraToast(`${action} on ${service} failed`, 'error');
        }
        // Refresh metrics after action
        setTimeout(() => loadScalingStatus(), 2000);
    } catch(e) { _spectraToast(`Scaling action failed: ${e.message}`, 'error'); }
}

function _addHealLogEntry(text) {
    _healActionsLog.unshift({ time: new Date().toLocaleTimeString(), text });
    if (_healActionsLog.length > 20) _healActionsLog.length = 20;
    _renderHealLog();
}

function _renderHealLog() {
    const container = document.getElementById('heal-actions-log');
    if (!container) return;
    if (_healActionsLog.length === 0) {
        container.innerHTML = '<p class="text-xs text-slate-500">No recent healing actions.</p>';
        return;
    }
    container.innerHTML = _healActionsLog.map(e =>
        `<div class="text-xs text-slate-400"><span class="text-slate-600">${_escHtml(e.time)}</span> ${_escHtml(e.text)}</div>`
    ).join('');
}

// --- Auto-heal toggle ---

const healToggle = document.getElementById('scaling-auto-heal-enabled');
if (healToggle) {
    healToggle.addEventListener('change', async () => {
        // No dedicated auto_heal_enabled config endpoint yet — piggyback on scaling config
        _spectraToast(healToggle.checked ? 'Auto-heal enabled' : 'Auto-heal disabled', 'info');
    });
}

// --- Refresh & auto-refresh ---

function refreshScalingStatus() {
    loadScalingStatus();
}

function startScalingAutoRefresh() {
    if (scalingRefreshTimer) clearInterval(scalingRefreshTimer);
    scalingRefreshTimer = setInterval(async () => {
        try {
            const { data, error } = await spectraApi.get('/api/admin/scaling/metrics');
            if (!error && data) populateClusterMetrics(data);
        } catch(e) { /* silent */ }
    }, 10000);
}

// --- Helpers ---

function _setGauge(id, pct) {
    const el = document.getElementById(id);
    if (el) {
        const clamped = Math.max(0, Math.min(100, pct ?? 0));
        el.style.width = clamped + '%';
        // Color shift: green < 60, amber 60-85, red > 85
        const base = el.className.replace(/bg-\S+/, '');
        const color = clamped < 60 ? 'bg-emerald-500' : clamped < 85 ? 'bg-amber-500' : 'bg-rose-500';
        el.className = base + ' ' + color;
    }
}

function _setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function _fmtPct(v) { return v != null ? v + '%' : '—%'; }

function _fmtDuration(secs) {
    if (secs == null) return '—';
    if (secs < 60) return Math.round(secs) + 's';
    if (secs < 3600) return Math.round(secs / 60) + 'm';
    return Math.round(secs / 3600) + 'h';
}

function _escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

const scalingForm = document.getElementById('scaling-config-form');
if (scalingForm) scalingForm.addEventListener('submit', saveScalingConfig);

window.scalingAction = scalingAction;

