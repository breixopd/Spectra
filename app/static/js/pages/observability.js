let currentData = {};

// Tab switching
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => {
            b.classList.remove('active');
            b.setAttribute('aria-selected', 'false');
            b.tabIndex = -1;
        });
        document.querySelectorAll('.tab-content').forEach(c => {
            c.classList.remove('active');
            c.hidden = true;
        });

        btn.classList.add('active');
        btn.setAttribute('aria-selected', 'true');
        btn.tabIndex = 0;
        const panel = document.getElementById(`tab-${btn.dataset.tab}`);
        panel.classList.add('active');
        panel.hidden = false;
    });
});

async function refreshData() {
    const btns = document.querySelectorAll('.refresh-btn');
    btns.forEach(btn => btn.classList.add('loading'));
    
    try {
        const { data, error } = await spectraApi.get('/api/v1/observability/stats');
        if (error) throw error;
        currentData = data;
        updateUI(currentData);
    } catch (error) {
        console.error('Failed to fetch stats:', error);
    } finally {
        btns.forEach(btn => btn.classList.remove('loading'));
    }
}

function updateUI(data) {
    // Overview stats
    document.getElementById('total-requests').textContent = data.overview?.total_requests || 0;
    document.getElementById('error-rate').textContent = `${data.overview?.error_rate_percent || 0}%`;
    document.getElementById('avg-latency').textContent = `${data.overview?.avg_latency_ms || 0}ms`;
    document.getElementById('healthy-services').textContent = 
        `${data.overview?.healthy_services || 0}/${data.overview?.active_services || 0}`;
    
    // Latency percentiles
    const latency = data.overview?.latency_percentiles || {};
    const maxLatency = Math.max(latency.p99_ms || 100, 100);
    
    document.getElementById('p50-value').textContent = `${latency.p50_ms || 0}ms`;
    document.getElementById('p90-value').textContent = `${latency.p90_ms || 0}ms`;
    document.getElementById('p99-value').textContent = `${latency.p99_ms || 0}ms`;
    
    document.getElementById('p50-bar').style.width = `${((latency.p50_ms || 0) / maxLatency) * 100}%`;
    document.getElementById('p90-bar').style.width = `${((latency.p90_ms || 0) / maxLatency) * 100}%`;
    document.getElementById('p99-bar').style.width = `${((latency.p99_ms || 0) / maxLatency) * 100}%`;
    
    // Services
    updateServices(data.services || {});
    
    // Traces
    updateTraces(data.traces || []);
    
    // Circuit breakers
    updateCircuitBreakers(data.circuit_breakers || {});
    
    // Events
    updateEvents(data.events || []);
    
    // Cache
    updateCache(data.cache || {});
}

function updateServices(services) {
    const grid = document.getElementById('services-grid');
    
    if (Object.keys(services).length === 0) {
        grid.innerHTML = '<p style="color: #94a3b8">No services reporting</p>';
        return;
    }
    
    grid.innerHTML = Object.entries(services).map(([name, info]) => `
        <div class="service-card">
            <div class="service-header">
                <span class="service-name">${escapeHtml(name)}</span>
                <div class="service-status">
                    <span class="status-dot ${info.healthy ? 'healthy' : 'unhealthy'}"></span>
                    ${info.healthy ? 'Healthy' : 'Unhealthy'}
                </div>
            </div>
            <div class="service-metrics">
                ${info.latency_ms ? `<span>Latency: ${escapeHtml(info.latency_ms)}ms</span>` : ''}
                ${info.last_check ? `<span>Last check: ${escapeHtml(new Date(info.last_check).toLocaleTimeString())}</span>` : ''}
            </div>
            ${info.error ? `<div style="color: #f43f5e; font-size: 0.875rem; margin-top: 0.25rem;">${escapeHtml(info.error)}</div>` : ''}
        </div>
    `).join('');
}

function updateTraces(traces) {
    const tbody = document.getElementById('traces-body');
    
    if (traces.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #94a3b8">No traces recorded</td></tr>';
        return;
    }
    
    tbody.innerHTML = traces.slice(-50).reverse().map(trace => {
        const durationClass = trace.duration_ms > 5000 ? 'very-slow' : trace.duration_ms > 1000 ? 'slow' : '';
        return `
            <tr>
                <td>${escapeHtml(new Date(trace.start_time).toLocaleTimeString())}</td>
                <td class="trace-name">${escapeHtml(trace.name)}</td>
                <td class="trace-duration ${durationClass}">${escapeHtml(trace.duration_ms.toFixed(2))}ms</td>
                <td><span class="trace-status ${trace.status === 'ok' ? 'ok' : 'error'}">${escapeHtml(trace.status)}</span></td>
                <td>
                    ${trace.attributes?.error?.message ? `<span style="color: #f43f5e">${escapeHtml(trace.attributes.error.message)}</span>` : '-'}
                </td>
            </tr>
        `;
    }).join('');
}

function updateCircuitBreakers(breakers) {
    const container = document.getElementById('circuit-breakers-list');
    
    if (Object.keys(breakers).length === 0) {
        container.innerHTML = '<p style="color: #94a3b8">No circuit breakers configured</p>';
        return;
    }
    
    container.innerHTML = Object.entries(breakers).map(([name, info]) => `
        <div class="circuit-breaker-card">
            <div class="cb-header">
                <span class="cb-name">${escapeHtml(name)}</span>
                <span class="cb-state ${info.state === 'closed' ? 'closed' : info.state === 'open' ? 'open' : 'half-open'}">${escapeHtml(info.state)}</span>
            </div>
            <div class="cb-stats">
                <span>Calls: ${escapeHtml(info.total_calls)}</span>
                <span>Failures: ${escapeHtml(info.total_failures)}</span>
                <span>Failure Rate: ${escapeHtml(info.failure_rate.toFixed(1))}%</span>
                <span>Times Opened: ${escapeHtml(info.times_opened)}</span>
            </div>
        </div>
    `).join('');
}

function updateEvents(events) {
    const container = document.getElementById('events-list');
    
    if (events.length === 0) {
        container.innerHTML = '<p style="color: #94a3b8; padding: 1rem;">No events recorded</p>';
        return;
    }
    
    container.innerHTML = events.slice(-100).reverse().map(event => `
        <div class="event-item">
            <span class="event-time">${escapeHtml(new Date(event.timestamp).toLocaleTimeString())}</span>
            <span class="event-type">${escapeHtml(event.type)}</span>
            <span>${escapeHtml(event.source)}</span>
        </div>
    `).join('');
}

function updateCache(cache) {
    const container = document.getElementById('cache-stats');
    
    const hitRate = cache.hit_rate_percent || 0;
    
    container.innerHTML = `
        <div class="stat-card">
            <div class="stat-value">${cache.hits || 0}</div>
            <div class="stat-label">Cache Hits</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${cache.misses || 0}</div>
            <div class="stat-label">Cache Misses</div>
        </div>
        <div class="stat-card">
            <div class="stat-value success">${hitRate}%</div>
            <div class="stat-label">Hit Rate</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${cache.sets || 0}</div>
            <div class="stat-label">Cache Sets</div>
        </div>
    `;
}

function filterTraces() {
    const filter = document.getElementById('trace-filter').value;
    let filtered = currentData.traces || [];
    
    if (filter === 'error') {
        filtered = filtered.filter(t => t.status === 'error');
    } else if (filter === 'slow') {
        filtered = filtered.filter(t => t.duration_ms > 1000);
    }
    
    updateTraces(filtered);
}

// Initial load
refreshData();
refreshTrends();

// --- Trend Charts (Canvas API) ---
function drawLineChart(canvasId, points, color, fillColor) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !points.length) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width, H = rect.height;
    const pad = {top: 10, right: 10, bottom: 24, left: 48};
    const cw = W - pad.left - pad.right, ch = H - pad.top - pad.bottom;

    ctx.clearRect(0, 0, W, H);

    const vals = points.map(p => p.v);
    let minV = Math.min(...vals), maxV = Math.max(...vals);
    if (minV === maxV) { minV -= 1; maxV += 1; }
    const range = maxV - minV;

    // Grid lines
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = pad.top + ch - (ch * i / 4);
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + cw, y); ctx.stroke();
        ctx.fillStyle = '#64748b'; ctx.font = '10px JetBrains Mono, monospace'; ctx.textAlign = 'right';
        const label = (minV + range * i / 4);
        ctx.fillText(label >= 1000 ? (label/1000).toFixed(1)+'k' : label.toFixed(1), pad.left - 4, y + 3);
    }

    // Time labels
    ctx.fillStyle = '#64748b'; ctx.font = '10px JetBrains Mono, monospace'; ctx.textAlign = 'center';
    const labelCount = Math.min(points.length, 6);
    for (let i = 0; i < labelCount; i++) {
        const idx = Math.floor(i * (points.length - 1) / Math.max(labelCount - 1, 1));
        const x = pad.left + (idx / Math.max(points.length - 1, 1)) * cw;
        const d = new Date(points[idx].t * 1000);
        ctx.fillText(d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0'), x, H - 4);
    }

    if (points.length < 2) return;

    // Fill
    ctx.beginPath();
    ctx.moveTo(pad.left, pad.top + ch);
    for (let i = 0; i < points.length; i++) {
        const x = pad.left + (i / (points.length - 1)) * cw;
        const y = pad.top + ch - ((points[i].v - minV) / range) * ch;
        ctx.lineTo(x, y);
    }
    ctx.lineTo(pad.left + cw, pad.top + ch);
    ctx.closePath();
    ctx.fillStyle = fillColor;
    ctx.fill();

    // Line
    ctx.beginPath();
    for (let i = 0; i < points.length; i++) {
        const x = pad.left + (i / (points.length - 1)) * cw;
        const y = pad.top + ch - ((points[i].v - minV) / range) * ch;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();
}

function drawMultiLineChart(canvasId, series) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !series.length || !series[0].points.length) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width, H = rect.height;
    const pad = {top: 10, right: 10, bottom: 24, left: 48};
    const cw = W - pad.left - pad.right, ch = H - pad.top - pad.bottom;
    ctx.clearRect(0, 0, W, H);

    const allVals = series.flatMap(s => s.points.map(p => p.v));
    let minV = Math.min(...allVals), maxV = Math.max(...allVals);
    if (minV === maxV) { minV -= 1; maxV += 1; }
    const range = maxV - minV;
    const n = series[0].points.length;

    // Grid
    ctx.strokeStyle = 'rgba(255,255,255,0.06)'; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = pad.top + ch - (ch * i / 4);
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + cw, y); ctx.stroke();
        ctx.fillStyle = '#64748b'; ctx.font = '10px JetBrains Mono, monospace'; ctx.textAlign = 'right';
        ctx.fillText((minV + range * i / 4).toFixed(1), pad.left - 4, y + 3);
    }

    // Time labels
    ctx.fillStyle = '#64748b'; ctx.font = '10px JetBrains Mono, monospace'; ctx.textAlign = 'center';
    const pts = series[0].points;
    const lc = Math.min(n, 6);
    for (let i = 0; i < lc; i++) {
        const idx = Math.floor(i * (n - 1) / Math.max(lc - 1, 1));
        const x = pad.left + (idx / Math.max(n - 1, 1)) * cw;
        const d = new Date(pts[idx].t * 1000);
        ctx.fillText(d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0'), x, H - 4);
    }

    // Lines + legend
    let legendX = pad.left + 4;
    for (const s of series) {
        if (s.points.length < 2) continue;
        ctx.beginPath();
        for (let i = 0; i < s.points.length; i++) {
            const x = pad.left + (i / (s.points.length - 1)) * cw;
            const y = pad.top + ch - ((s.points[i].v - minV) / range) * ch;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.stroke();
        // Legend
        ctx.fillStyle = s.color; ctx.font = '10px sans-serif'; ctx.textAlign = 'left';
        ctx.fillRect(legendX, pad.top, 10, 3);
        ctx.fillText(s.label, legendX + 14, pad.top + 4);
        legendX += ctx.measureText(s.label).width + 28;
    }
}

async function refreshTrends() {
    const minutes = parseInt(document.getElementById('trend-range').value, 10);
    try {
        const { data, error } = await spectraApi.get(`/api/v1/observability/metrics/history?minutes=${minutes}`);
        if (error) throw error;
        renderTrends(data);
    } catch (e) {
        console.error('Failed to fetch trends:', e);
    }
}

function renderTrends(snapshots) {
    if (!snapshots || !snapshots.length) {
        ['chart-requests','chart-errors','chart-latency','chart-percentiles'].forEach(id => {
            const c = document.getElementById(id);
            if (c) { const ctx = c.getContext('2d'); ctx.clearRect(0,0,c.width,c.height);
                ctx.fillStyle='#64748b'; ctx.font='13px sans-serif'; ctx.textAlign='center';
                ctx.fillText('No data yet — snapshots arrive every 60s', c.getBoundingClientRect().width/2, c.getBoundingClientRect().height/2);
            }
        });
        return;
    }

    drawLineChart('chart-requests',
        snapshots.map(s => ({t: s._timestamp, v: s.request_count})),
        '#8b5cf6', 'rgba(139,92,246,0.10)');

    drawLineChart('chart-errors',
        snapshots.map(s => ({t: s._timestamp, v: s.error_rate})),
        '#f43f5e', 'rgba(244,63,94,0.10)');

    drawLineChart('chart-latency',
        snapshots.map(s => ({t: s._timestamp, v: s.avg_latency_ms})),
        '#3b82f6', 'rgba(59,130,246,0.10)');

    drawMultiLineChart('chart-percentiles', [
        {label: 'P50', color: '#10b981', points: snapshots.map(s => ({t: s._timestamp, v: s.p50_ms}))},
        {label: 'P90', color: '#f59e0b', points: snapshots.map(s => ({t: s._timestamp, v: s.p90_ms}))},
        {label: 'P99', color: '#f43f5e', points: snapshots.map(s => ({t: s._timestamp, v: s.p99_ms}))},
    ]);
}

async function refreshSaasMetrics() {
    try {
        const { data, error } = await spectraApi.get('/api/v1/observability/saas-metrics');
        if (error) throw error;
        updateSaasMetrics(data);
    } catch (error) {
        console.error('Failed to fetch SaaS metrics:', error);
    }
}

function updateSaasMetrics(data) {
    const container = document.getElementById('saas-stats');
    container.innerHTML = `
        <div class="stat-card">
            <div class="stat-value">${data.active_users || 0}</div>
            <div class="stat-label">Active Users</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${data.missions?.started || 0}</div>
            <div class="stat-label">Missions Started</div>
        </div>
        <div class="stat-card">
            <div class="stat-value success">${data.missions?.completed || 0}</div>
            <div class="stat-label">Missions Completed</div>
        </div>
    `;

    const errContainer = document.getElementById('saas-error-rates');
    const errEntries = Object.entries(data.api_error_rates || {});
    if (errEntries.length) {
        errContainer.innerHTML = errEntries.map(([path, count]) =>
            `<div style="display:flex;justify-content:space-between;padding:0.25rem 0;border-bottom:1px solid rgba(255,255,255,0.05)"><span>${escapeHtml(path)}</span><span class="font-mono" style="color:#f43f5e">${escapeHtml(count)}</span></div>`
        ).join('');
    } else {
        errContainer.textContent = 'No errors recorded';
    }

    const latContainer = document.getElementById('saas-latency');
    const latEntries = Object.entries(data.latency_by_endpoint || {});
    if (latEntries.length) {
        latContainer.innerHTML = '<table class="traces-table"><thead><tr><th>Endpoint</th><th>P50</th><th>P90</th><th>P99</th><th>Count</th></tr></thead><tbody>' +
            latEntries.map(([path, s]) =>
                `<tr><td>${escapeHtml(path)}</td><td>${escapeHtml(s.p50)}ms</td><td>${escapeHtml(s.p90)}ms</td><td>${escapeHtml(s.p99)}ms</td><td>${escapeHtml(s.count)}</td></tr>`
            ).join('') + '</tbody></table>';
    } else {
        latContainer.textContent = 'No latency data';
    }
}

// Auto-refresh every 10 seconds
setInterval(() => { refreshData(); refreshTrends(); }, 10000);

// Lucide icons are initialized globally in base.html

// Expose functions used by HTML onclick/onchange handlers
window.refreshData = refreshData;
window.refreshTrends = refreshTrends;
window.refreshSaasMetrics = refreshSaasMetrics;
window.filterTraces = filterTraces;
