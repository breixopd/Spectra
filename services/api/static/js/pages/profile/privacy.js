async function downloadMyData() {
    try {
        const res = await fetch('/api/v1/auth/export-data', {
            credentials: 'include',
            headers: { 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || '' },
        });
        if (!res.ok) throw new Error('Export failed');
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'spectra-data-export.json';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        _spectraToast('Data export downloaded');
    } catch (e) { _spectraToast(e.message || 'Failed to export data', 'error'); }
}

async function loadDataPrivacy() {
    try {
        const { data: me, error: meError } = await spectraApi.get('/api/v1/auth/me');
        if (!meError) {
            const toggle = document.getElementById('restrict-processing-toggle');
            if (toggle) toggle.checked = !!me.processing_restricted;
        }
        const { data: s, error: sError } = await spectraApi.get('/api/v1/user/settings');
        if (!sError) {
            const st = document.getElementById('share-training-toggle');
            if (st) st.checked = !!s.share_training_data;
        }
    } catch (e) { console.error('Failed to load data privacy settings', e); }
}

async function toggleRestrictProcessing() {
    const checked = document.getElementById('restrict-processing-toggle').checked;
    try {
        const { error } = await spectraApi.post('/api/v1/auth/restrict-processing', { restricted: checked });
        if (!error) _spectraToast(checked ? 'Processing restricted' : 'Processing restriction removed');
        else { _spectraToast(error || 'Failed to update', 'error'); document.getElementById('restrict-processing-toggle').checked = !checked; }
    } catch (e) { _spectraToast('Network error', 'error'); document.getElementById('restrict-processing-toggle').checked = !checked; }
}

async function toggleShareTraining() {
    const checked = document.getElementById('share-training-toggle').checked;
    try {
        const { error } = await spectraApi.put('/api/v1/user/settings', { share_training_data: checked });
        if (!error) _spectraToast(checked ? 'Training data sharing enabled' : 'Training data sharing disabled');
        else { _spectraToast(error || 'Failed to update', 'error'); document.getElementById('share-training-toggle').checked = !checked; }
    } catch (e) { _spectraToast('Network error', 'error'); document.getElementById('share-training-toggle').checked = !checked; }
}

loadDataPrivacy();

window.downloadMyData = downloadMyData;
window.toggleRestrictProcessing = toggleRestrictProcessing;
window.toggleShareTraining = toggleShareTraining;
