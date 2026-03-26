let currentMissionId = null;

// Load missions on start
(async () => {
    const { data: missions, error } = await spectraApi.get('/api/v1/missions');
    if (error) return;
        const list = document.getElementById('mission-list');
        list.innerHTML = '';
        
        if (missions.length === 0) {
            list.innerHTML = '<div class="empty-state"><i class="fa-solid fa-clock-rotate-left text-blue-400/40"></i><h3>No assessments yet</h3><p>Start an assessment from the Dashboard to see history here.</p></div>';
            return;
        }

        // Sort by ID (timestamp roughly) descending
        missions.reverse().forEach(m => {
            const el = document.createElement('div');
            el.className = 'p-3 rounded-lg bg-white/5 hover:bg-white/10 cursor-pointer transition-colors border border-white/5';
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
})();

async function loadMissionDetails(id) {
    currentMissionId = id;
    document.getElementById('mission-details-placeholder').classList.add('hidden');
    document.getElementById('mission-details-content').classList.remove('hidden');
    
    // Show loading state
    document.getElementById('detail-target').innerText = 'Loading...';

    const { data: mission, error } = await spectraApi.get(`/api/v1/missions/${id}`);
    if (error) return;
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
            
            // Findings (Need to parse from logs or add to API response)
            // The MissionResponse schema currently only has id, target, status, logs.
            // I should update the schema to include findings and directive.
            const findingsContainer = document.getElementById('tab-findings');
            findingsContainer.innerHTML = '<div class="text-slate-500 italic">Findings data not in API response yet.</div>';

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
}

function showDeleteModal() {
    if (!currentMissionId) return;
    document.getElementById('download-before-delete-btn').onclick = () => {
        window.open(`/api/v1/missions/${currentMissionId}/report/pdf`, '_blank');
    };
    document.getElementById('delete-mission-modal').classList.remove('hidden');
}

function hideDeleteModal() {
    document.getElementById('delete-mission-modal').classList.add('hidden');
}

async function confirmDeleteMission() {
    hideDeleteModal();
    const { error } = await spectraApi.delete(`/api/v1/missions/${currentMissionId}`);
    if (error) {
        _spectraToast(error.detail || 'Failed to delete mission', 'error');
        return;
    }
    window.location.reload();
}

function switchTab(tabName) {
    ['logs', 'findings', 'json'].forEach(t => {
        document.getElementById(`tab-${t}`).classList.add('hidden');
    });
    document.getElementById(`tab-${tabName}`).classList.remove('hidden');
    
    // Update buttons (simple version)
    // In a real app, I'd toggle classes on buttons too.
}

// Expose functions used by HTML onclick handlers
window.showDeleteModal = showDeleteModal;
window.hideDeleteModal = hideDeleteModal;
window.confirmDeleteMission = confirmDeleteMission;
window.switchTab = switchTab;
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
