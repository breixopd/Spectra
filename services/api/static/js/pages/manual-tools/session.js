// === Session Tracking ===
let currentSessionId = null;

// --- Server sync for manual mode state ---
let _manualSyncTimer = null;

function _collectManualState() {
    return {
        scope_targets: scopeTargets,
        scope_exclusions: scopeExclusions,
        scope_roe: document.getElementById('scope-roe')?.value || '',
        checklist: _collectAllChecklistState(),
        notes: notesData,
        command_history: commandHistory,
    };
}

function _collectAllChecklistState() {
    const all = {};
    for (const method of Object.keys(CHECKLIST_DATA)) {
        const raw = localStorage.getItem('spectra_checklist_' + method);
        if (raw) {
            try { all[method] = JSON.parse(raw); } catch (_) { /* skip */ }
        }
    }
    return all;
}

function syncManualStateToServer() {
    if (!currentSessionId) return;
    clearTimeout(_manualSyncTimer);
    _manualSyncTimer = setTimeout(async () => {
        try {
            await spectraApi.put(
                `/api/v1/pentest-sessions/${currentSessionId}/manual-state`,
                { state: _collectManualState() }
            );
        } catch (e) {
            console.debug('Server sync failed, localStorage is the fallback:', e);
        }
    }, 2000);
}

async function loadManualStateFromServer() {
    if (!currentSessionId) return false;
    try {
        const { data, error } = await spectraApi.get(
            `/api/v1/pentest-sessions/${currentSessionId}/manual-state`
        );
        if (error || !data || !Object.keys(data).length) return false;

        if (Array.isArray(data.scope_targets)) {
            scopeTargets = data.scope_targets;
            localStorage.setItem('spectra_scope_targets', JSON.stringify(scopeTargets));
        }
        if (Array.isArray(data.scope_exclusions)) {
            scopeExclusions = data.scope_exclusions;
            localStorage.setItem('spectra_scope_exclusions', JSON.stringify(scopeExclusions));
        }
        if (typeof data.scope_roe === 'string') {
            localStorage.setItem('spectra_scope_roe', data.scope_roe);
            const roeEl = document.getElementById('scope-roe');
            if (roeEl) roeEl.value = data.scope_roe;
        }
        if (data.checklist && typeof data.checklist === 'object') {
            for (const [method, state] of Object.entries(data.checklist)) {
                localStorage.setItem('spectra_checklist_' + method, JSON.stringify(state));
            }
        }
        if (Array.isArray(data.notes)) {
            notesData = data.notes;
            localStorage.setItem('spectra_notes', JSON.stringify(notesData));
        }
        if (Array.isArray(data.command_history)) {
            commandHistory = data.command_history;
            localStorage.setItem('spectra_cmd_history', JSON.stringify(commandHistory));
        }
        return true;
    } catch (e) {
        console.debug('Failed to load manual state from server:', e);
        return false;
    }
}

async function startSession() {
    const target = document.getElementById('global-target')?.value?.trim() || 'unknown';
    _spectraPrompt('Session name:', (name) => {
        spectraApi.post('/api/v1/pentest-sessions', {name, target, description: ''}).then(res => {
            const session = res.data;
            currentSessionId = session.id;
            document.getElementById('session-label').textContent = `${name} (${target})`;
            document.getElementById('session-start-btn').textContent = 'Active';
            document.getElementById('session-start-btn').disabled = true;
            document.getElementById('session-export-btn').classList.remove('hidden');
        }).catch(e => { _spectraToast('Failed to start session', 'error'); });
    }, { title: 'Start Session', placeholder: `Pentest ${new Date().toLocaleDateString('en-US')}` });
}

function logToSession(action, tool, findings) {
    if (!currentSessionId) return;
    spectraApi.post(`/api/v1/pentest-sessions/${currentSessionId}/log`, {action, tool, note: '', findings: findings || []})
        .catch(e => console.debug('Session log failed:', e));
}

async function exportSession() {
    if (!currentSessionId) return;
    try {
        const res = await spectraApi.get(`/api/v1/pentest-sessions/${currentSessionId}/export`);
        const data = res.data;
        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `session-${currentSessionId}.json`;
        a.click();
    } catch (e) {
        _spectraToast('Export failed: ' + e.message, 'error');
    }
}
