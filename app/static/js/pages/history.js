let currentMissionId = null;
let missionCache = [];
let historyRefreshIntervalId = null;
let missionListRefreshErrorShown = false;
let missionDetailsRefreshErrorShown = false;

function getHistoryErrorMessage(error, fallback) {
    if (typeof error === 'string' && error.trim()) {
        return error;
    }
    return fallback;
}

function renderMissionListError(message) {
    const list = document.getElementById('mission-list');
    if (!list) return;
    list.innerHTML = `
        <div class="text-center text-rose-400 py-8 px-4 space-y-2">
            <p class="text-sm font-medium">Failed to load assessments</p>
            <p class="text-xs text-slate-500">${escapeHtml(message)}</p>
            <button type="button" onclick="window.location.reload()" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-slate-300 text-xs transition-colors">
                Retry
            </button>
        </div>
    `;
}

function showMissionDetailsLoading() {
    document.getElementById('mission-details-placeholder').classList.add('hidden');
    document.getElementById('mission-details-content').classList.remove('hidden');
    document.getElementById('detail-target').innerText = 'Loading...';
    document.getElementById('detail-id').innerText = '';
    document.getElementById('detail-directive').innerText = 'Loading mission details...';

    const statusEl = document.getElementById('detail-status');
    statusEl.innerText = 'Loading';
    statusEl.className = 'px-2 py-1 rounded text-xs font-medium bg-slate-700 text-slate-300';

    document.getElementById('tab-logs').innerHTML = '<div class="text-slate-500 italic">Loading mission logs...</div>';
    document.getElementById('tab-findings').innerHTML = '<div class="text-slate-500 italic">Loading findings...</div>';
    document.getElementById('detail-json').innerText = '{\n  "status": "loading"\n}';
}

function renderMissionDetailsError(message) {
    document.getElementById('mission-details-placeholder').classList.add('hidden');
    document.getElementById('mission-details-content').classList.remove('hidden');
    document.getElementById('detail-target').innerText = 'Unable to load mission';
    document.getElementById('detail-id').innerText = currentMissionId || '';
    document.getElementById('detail-directive').innerText = message;

    const statusEl = document.getElementById('detail-status');
    statusEl.innerText = 'Error';
    statusEl.className = 'px-2 py-1 rounded text-xs font-medium bg-rose-500/20 text-rose-400 border border-rose-500/30';

    document.getElementById('tab-logs').innerHTML = `<div class="text-rose-400 italic">${escapeHtml(message)}</div>`;
    document.getElementById('tab-findings').innerHTML = '<div class="text-slate-600 italic">Mission findings are unavailable right now.</div>';
    document.getElementById('detail-json').innerText = JSON.stringify({ error: message }, null, 2);
    document.getElementById('mission-feedback-section')?.classList.add('hidden');
}

async function loadMissionList(options = {}) {
    const { initial = false } = options;
    const { data, error } = await spectraApi.get('/api/v1/missions?page=1&per_page=100');

    if (error) {
        const message = getHistoryErrorMessage(error, 'Could not load assessment history.');
        if (initial) {
            renderMissionListError(message);
        }
        if (initial || !missionListRefreshErrorShown) {
            _spectraToast(message, 'error');
            missionListRefreshErrorShown = true;
        }
        return false;
    }

    missionListRefreshErrorShown = false;
    missionCache = data?.items || [];
    renderMissionList([...missionCache]);
    return true;
}

function renderMissionList(missions) {
    const list = document.getElementById('mission-list');
    list.innerHTML = '';

    if (missions.length === 0) {
        list.innerHTML = '<div class="empty-state"><i data-lucide="history" class="w-8 h-8 inline-block text-blue-400/40"></i><h3>No assessments yet</h3><p>Start an assessment from the Dashboard to see history here.</p></div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }

    missions.reverse().forEach(m => {
        const el = document.createElement('div');
        el.className = 'mission-list-item p-3 rounded-lg bg-white/5 hover:bg-white/10 cursor-pointer transition-colors border border-white/5';
        el.dataset.missionCard = 'true';
        el.onclick = () => loadMissionDetails(m.id);

        let statusColor = 'text-slate-400';
        if (m.status === 'completed' || m.status === 'exploitation_successful') statusColor = 'text-emerald-400';
        if (m.status === 'failed') statusColor = 'text-rose-400';
        if (m.status === 'running') statusColor = 'text-amber-400';

        el.innerHTML = `
            <div class="flex justify-between items-start mb-1">
                <span class="font-medium text-slate-200 truncate">${escapeHtml(m.target)}</span>
                <span class="text-xs ${statusColor} border border-current px-1 rounded uppercase">${escapeHtml(m.status)}</span>
            </div>
            <div class="text-xs text-slate-500 font-mono truncate">${escapeHtml(m.id)}</div>
        `;
        list.appendChild(el);
    });
}

function filterMissions(query) {
    const q = query.toLowerCase();
    document.querySelectorAll('[data-mission-card]').forEach(card => {
        const text = card.textContent.toLowerCase();
        card.style.display = text.includes(q) ? '' : 'none';
    });
}

// Load missions on start
(async () => {
    await loadMissionList({ initial: true });
})();

historyRefreshIntervalId = window.setInterval(async () => {
    const loaded = await loadMissionList();
    if (!loaded) return;
    const query = document.getElementById('mission-search')?.value;
    if (query) filterMissions(query);
    if (currentMissionId) {
        await loadMissionDetails(currentMissionId, { background: true });
    }
}, 30000);

function cleanupHistoryPageState() {
    if (historyRefreshIntervalId) {
        window.clearInterval(historyRefreshIntervalId);
        historyRefreshIntervalId = null;
    }
}

window.addEventListener('pagehide', cleanupHistoryPageState, { once: true });
window.addEventListener('beforeunload', cleanupHistoryPageState, { once: true });

async function loadMissionDetails(id, options = {}) {
    const { background = false } = options;
    currentMissionId = id;
    if (!background) {
        showMissionDetailsLoading();
    }

    const { data: mission, error } = await spectraApi.get(`/api/v1/missions/${id}`);
    if (error) {
        const message = getHistoryErrorMessage(error, 'Could not load mission details.');
        if (!background) {
            renderMissionDetailsError(message);
        }
        if (!missionDetailsRefreshErrorShown || !background) {
            _spectraToast(message, 'error');
            missionDetailsRefreshErrorShown = true;
        }
        return false;
    }

    missionDetailsRefreshErrorShown = false;
            // Header
            document.getElementById('detail-target').innerText = mission.target;
            document.getElementById('detail-id').innerText = mission.id;
            
            const statusEl = document.getElementById('detail-status');
            statusEl.innerText = mission.status;
            
            let statusClass = 'bg-slate-700 text-slate-300';
            if (mission.status === 'completed' || mission.status === 'exploitation_successful') statusClass = 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30';
            else if (mission.status === 'failed') statusClass = 'bg-rose-500/20 text-rose-400 border border-rose-500/30';
            else if (mission.status === 'running') statusClass = 'bg-amber-500/20 text-amber-400 border border-amber-500/30';
            
            statusEl.className = `px-2 py-1 rounded text-xs font-medium ${statusClass}`;

            // Directive (Need to fetch full details if not in list response, but API returns it)
            // The list response might not have directive, let's check schema. 
            // Actually the list response schema in missions.py doesn't include directive.
            // But get_mission endpoint does.
            // Wait, the schema MissionResponse in missions.py DOES NOT include directive?
            // Let's check schemas.py.
            
            // Assuming directive is available or we need to update schema.
            // For now, let's try to access it.
            if (mission.directive) {
                 document.getElementById('detail-directive').innerText = mission.directive;
            } else {
                 document.getElementById('detail-directive').innerText = "No directive available (check API schema)";
            }

            // Logs
            const logsContainer = document.getElementById('tab-logs');
            logsContainer.innerHTML = '';
            if (mission.logs && mission.logs.length > 0) {
                mission.logs.forEach(log => {
                    const div = document.createElement('div');
                    div.className = 'text-slate-400 border-l-2 border-white/5 pl-2 py-0.5 hover:bg-white/5';
                    
                    // Highlight key events
                    if (log.includes('[VALIDATE]')) div.className += ' text-amber-300 border-amber-500/50';
                    if (log.includes('[APPROVED]')) div.className += ' text-emerald-300 border-emerald-500/50';
                    if (log.includes('[REJECTED]')) div.className += ' text-rose-300 border-rose-500/50';
                    if (log.includes('[STEERING]')) div.className += ' text-violet-300 border-violet-500/50';
                    if (log.includes('[SUCCESS]')) div.className += ' text-emerald-400 font-bold border-emerald-500';
                    
                    div.innerText = log;
                    logsContainer.appendChild(div);
                });
            } else {
                logsContainer.innerHTML = '<div class="text-slate-600 italic">No logs available</div>';
            }

            // JSON
            document.getElementById('detail-json').innerText = JSON.stringify(mission, null, 2);
            
            // Findings
            const findingsContainer = document.getElementById('tab-findings');
            if (mission.findings && mission.findings.length > 0) {
                const severityColors = {
                    'critical': 'red', 'high': 'orange', 'medium': 'yellow', 'low': 'blue', 'info': 'slate'
                };
                findingsContainer.innerHTML = mission.findings.map(f => {
                    const sev = (f.severity || 'info').toLowerCase();
                    const color = severityColors[sev] || 'slate';
                    return `<div class="p-3 rounded-lg bg-white/5 border border-white/5 mb-2">
                        <div class="flex items-center justify-between mb-1">
                            <span class="font-medium text-slate-200">${escapeHtml(f.title || 'Untitled Finding')}</span>
                            <span class="px-2 py-0.5 text-xs rounded bg-${color}-500/20 text-${color}-400">${sev.toUpperCase()}</span>
                        </div>
                        ${f.description ? `<p class="text-sm text-slate-400 mt-1">${escapeHtml(f.description)}</p>` : ''}
                        ${f.tool_source ? `<span class="text-xs text-slate-500">Source: ${escapeHtml(f.tool_source)}</span>` : ''}
                        ${f.cve_id ? ` <span class="text-xs text-cyan-500">${escapeHtml(f.cve_id)}</span>` : ''}
                    </div>`;
                }).join('');
            } else {
                findingsContainer.innerHTML = '<div class="text-slate-600 italic">No findings recorded for this mission.</div>';
            }

    // Show feedback section for completed missions
    const feedbackSection = document.getElementById('mission-feedback-section');
    if (feedbackSection) {
        if (['completed', 'exploitation_successful', 'failed'].includes(mission.status)) {
            feedbackSection.classList.remove('hidden');
            loadFeedback(id);
        } else {
            feedbackSection.classList.add('hidden');
        }
    }

    return true;
}

function showDeleteModal() {
    if (!currentMissionId) return;
    const targetRow = document.getElementById('delete-mission-target-row');
    const targetEl = document.getElementById('delete-mission-target');
    if (targetEl) {
        targetEl.textContent = '';
    }
    if (targetRow) {
        targetRow.classList.add('hidden');
    }
    document.getElementById('download-before-delete-btn').onclick = () => {
        window.open(`/api/v1/missions/${currentMissionId}/report/pdf`, '_blank');
    };
    window.showModal('delete-mission-modal');
}

function hideDeleteModal() {
    window.closeModal('delete-mission-modal');
}

async function confirmDeleteMission() {
    hideDeleteModal();
    const { error } = await spectraApi.delete(`/api/v1/missions/${currentMissionId}`);
    if (error) {
        _spectraToast(error || 'Failed to delete mission', 'error');
        return;
    }
    window.location.reload();
}

function switchTab(tabName) {
    activateTab('history-tabs', tabName);
}

// Expose functions used by HTML onclick handlers
window.showDeleteModal = showDeleteModal;
window.handleDeleteMissionModalCancel = hideDeleteModal;
window.handleDeleteMissionModalConfirm = confirmDeleteMission;
window.switchTab = switchTab;
window.filterMissions = filterMissions;
window.submitFeedback = submitFeedback;

// ---- Mission Feedback ----
let selectedRating = 0;

document.getElementById('star-rating')?.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-star]');
    if (!btn) return;
    selectedRating = parseInt(btn.dataset.star);
    document.querySelectorAll('.star-btn').forEach(s => {
        const star = parseInt(s.dataset.star);
        s.className = star <= selectedRating
            ? 'star-btn text-2xl text-amber-400 transition-colors'
            : 'star-btn text-2xl text-slate-600 hover:text-amber-400 transition-colors';
    });
});

async function submitFeedback() {
    if (!currentMissionId || !selectedRating) return;
    const comment = document.getElementById('feedback-comment')?.value || '';
    const { error } = await spectraApi.post(`/api/v1/missions/${currentMissionId}/feedback`, {
        rating: selectedRating,
        comment: comment || null,
    });
    if (error) { _spectraToast('Failed to submit feedback', 'error'); return; }
    document.getElementById('feedback-saved-badge')?.classList.remove('hidden');
    document.getElementById('submit-feedback-btn').disabled = true;
    document.getElementById('submit-feedback-btn').textContent = 'Sent!';
    _spectraToast('Thanks for your feedback!', 'success');
}

async function loadFeedback(missionId) {
    const section = document.getElementById('mission-feedback-section');
    if (!section) return;
    const { data } = await spectraApi.get(`/api/v1/missions/${missionId}/feedback`);
    if (data?.has_feedback) {
        selectedRating = data.rating;
        document.querySelectorAll('.star-btn').forEach(s => {
            const star = parseInt(s.dataset.star);
            s.className = star <= selectedRating
                ? 'star-btn text-2xl text-amber-400 transition-colors'
                : 'star-btn text-2xl text-slate-600 hover:text-amber-400 transition-colors';
        });
        if (data.comment) document.getElementById('feedback-comment').value = data.comment;
        document.getElementById('feedback-saved-badge')?.classList.remove('hidden');
        document.getElementById('submit-feedback-btn').disabled = true;
        document.getElementById('submit-feedback-btn').textContent = 'Sent!';
    } else {
        selectedRating = 0;
        document.querySelectorAll('.star-btn').forEach(s => {
            s.className = 'star-btn text-2xl text-slate-600 hover:text-amber-400 transition-colors';
        });
        document.getElementById('feedback-comment').value = '';
        document.getElementById('feedback-saved-badge')?.classList.add('hidden');
        const btn = document.getElementById('submit-feedback-btn');
        if (btn) { btn.disabled = false; btn.textContent = 'Send Feedback'; }
    }
}
