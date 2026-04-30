// Dashboard Charts — Chart.js rendering functions
// Loaded before dashboard.js; depends on Chart.js, escapeHtml(), spectraApi

var chartInstances = {};

function destroyChart(id) { if (chartInstances[id]) { chartInstances[id].destroy(); delete chartInstances[id]; } }

async function loadMetrics() {
    const days = parseInt(document.getElementById('metrics-timerange').value) || 0;
    let missions = [], allFindings = [];
    const errEl = document.getElementById('dashboard-error');
    const findingsLoading = document.getElementById('findings-loading');
    const findingsData = document.getElementById('findings-data');

    try {
        const { data: missionsData, error: missionsError } = await spectraApi.get('/api/v1/missions');
        if (!missionsError) missions = missionsData.items || missionsData || [];
        if (errEl) errEl.classList.add('hidden');
    } catch {
        if (errEl) errEl.classList.remove('hidden');
    }

    const cutoff = days > 0 ? new Date(Date.now() - days * 86400000) : null;
    if (cutoff) missions = missions.filter(m => new Date(m.created_at) >= cutoff);

    // Toggle getting started card based on mission existence
    const gettingStarted = document.getElementById('getting-started');
    if (gettingStarted) {
        gettingStarted.classList.toggle('hidden', missions.length > 0);
    }

    // Show empty state for findings when none exist
    if (findingsLoading && findingsData && missions.length === 0) {
        findingsLoading.innerHTML = '<div class="col-span-4 dash-empty" style="padding:1rem 0.5rem;min-height:auto;"><i data-lucide="shield" class="w-5 h-5 inline-block"></i><p style="font-size:0.75rem;">No findings yet</p></div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    // Gather all findings
    for (const m of missions) {
        try {
            const { data: f, error: fErr } = await spectraApi.get(`/api/v1/missions/${m.id}/findings`);
            if (!fErr && f) { f.forEach(x => { x._mission = m; }); allFindings.push(...f); }
        } catch {}
    }

    // Swap skeleton for real data
    if (findingsLoading) findingsLoading.classList.add('hidden');
    if (findingsData) findingsData.classList.remove('hidden');

    // Show empty state for metrics when no data
    const metricsSection = document.getElementById('metrics-section');
    if (metricsSection && missions.length === 0 && allFindings.length === 0) {
        const metricsBody = metricsSection.querySelector('.p-5');
        if (metricsBody) {
            metricsBody.innerHTML = '<div class="dash-empty" style="padding:3rem 1rem;"><i data-lucide="bar-chart-3" class="w-5 h-5 inline-block"></i><h3>No data yet</h3><p>Complete your first assessment to see trends and metrics here.</p></div>';
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    } else {
        renderFindingsOverTime(allFindings, days);
        renderMissionsPerWeek(missions);
        renderSeverityBreakdown(allFindings);
        renderTopVulns(allFindings);
        renderTopTargets(allFindings, missions);
    }
}

function renderFindingsOverTime(findings, days) {
    destroyChart('findings-time');
    const grouped = {};
    findings.forEach(f => { const d = (f.created_at || '').split('T')[0]; if (d) grouped[d] = (grouped[d] || 0) + 1; });
    const labels = Object.keys(grouped).sort();
    const data = labels.map(l => grouped[l]);
    const ctx = document.getElementById('chart-findings-time');
    if (!ctx) return;
    chartInstances['findings-time'] = new Chart(ctx, {
        type: 'line', data: { labels, datasets: [{ label: 'Findings', data, borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.1)', fill: true, tension: 0.3, pointRadius: 2 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.03)' } }, y: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.03)' } } } }
    });
}

function renderMissionsPerWeek(missions) {
    destroyChart('missions-week');
    const grouped = {};
    missions.forEach(m => {
        const d = new Date(m.created_at);
        const weekStart = new Date(d); weekStart.setDate(d.getDate() - d.getDay());
        const key = weekStart.toISOString().split('T')[0];
        grouped[key] = (grouped[key] || 0) + 1;
    });
    const labels = Object.keys(grouped).sort();
    const data = labels.map(l => grouped[l]);
    const ctx = document.getElementById('chart-missions-week');
    if (!ctx) return;
    chartInstances['missions-week'] = new Chart(ctx, {
        type: 'bar', data: { labels, datasets: [{ label: 'Missions', data, backgroundColor: '#10b981', borderRadius: 4 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { display: false } }, y: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.03)' } } } }
    });
}

function renderSeverityBreakdown(findings) {
    destroyChart('severity');
    const counts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
    findings.forEach(f => { const s = (f.severity || 'info').toLowerCase(); if (s in counts) counts[s]++; });
    const ctx = document.getElementById('chart-severity');
    if (!ctx) return;
    chartInstances['severity'] = new Chart(ctx, {
        type: 'doughnut', data: { labels: Object.keys(counts), datasets: [{ data: Object.values(counts), backgroundColor: ['#f43f5e', '#f59e0b', '#3b82f6', '#64748b', '#475569'], borderWidth: 0 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { color: '#94a3b8', font: { size: 10, family: 'JetBrains Mono' }, padding: 8, usePointStyle: true, pointStyleWidth: 8 } } } }
    });
}

function renderTopVulns(findings) {
    const typeCounts = {};
    findings.forEach(f => { const t = f.title || 'Untitled Finding'; typeCounts[t] = (typeCounts[t] || 0) + 1; });
    const sorted = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]).slice(0, 10);
    const el = document.getElementById('top-vulns-list');
    if (!el) return;
    el.innerHTML = sorted.length === 0 ? '<div class="text-slate-600 text-center py-4">No findings</div>' :
        sorted.map(([name, count], i) => `<div class="flex items-center gap-2"><span class="text-xs text-slate-600 w-4">${i + 1}.</span><span class="flex-1 text-slate-300 truncate">${escapeHtml(name)}</span><span class="text-xs font-mono text-slate-500">${count}</span></div>`).join('');
}

function renderTopTargets(findings, missions) {
    destroyChart('top-targets');
    const targetCounts = {};
    findings.forEach(f => { const t = f._mission?.target || 'Target not specified'; targetCounts[t] = (targetCounts[t] || 0) + 1; });
    const sorted = Object.entries(targetCounts).sort((a, b) => b[1] - a[1]).slice(0, 8);
    const ctx = document.getElementById('chart-top-targets');
    if (!ctx) return;
    chartInstances['top-targets'] = new Chart(ctx, {
        type: 'bar', data: { labels: sorted.map(s => s[0]), datasets: [{ label: 'Findings', data: sorted.map(s => s[1]), backgroundColor: '#8b5cf6', borderRadius: 4 }] },
        options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.03)' } }, y: { ticks: { color: '#94a3b8', font: { size: 9, family: 'JetBrains Mono' } }, grid: { display: false } } } }
    });
}
