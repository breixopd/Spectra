let userPlanFeatures = {};

async function loadUserSettings() {
    try {
        const { data: me, error: meError } = await spectraApi.get('/api/v1/auth/me');
        if (!meError) {
            userPlanFeatures = me.plan?.features || {};
            const byokAllowed = userPlanFeatures.byok === true;
            document.getElementById('byok-gate').classList.toggle('hidden', byokAllowed);
            document.getElementById('byok-fields').style.opacity = byokAllowed ? '1' : '0.4';
            document.getElementById('byok-fields').style.pointerEvents = byokAllowed ? 'auto' : 'none';
        }

        const { data: s, error: sError } = await spectraApi.get('/api/v1/user/settings');
        if (sError) return;
        if (s.llm_api_key_configured) document.getElementById('settings-llm-key').placeholder = '••••••••  (configured)';
        document.getElementById('settings-llm-url').value = s.llm_api_base_url || '';
        document.getElementById('settings-llm-model').value = s.llm_model || '';
        if (s.embedding_api_key_configured) document.getElementById('settings-emb-key').placeholder = '••••••••  (configured)';
        document.getElementById('settings-emb-url').value = s.embedding_api_base_url || '';
        document.getElementById('settings-emb-model').value = s.embedding_model || '';
        document.getElementById('settings-email-notif').checked = s.email_notifications !== false;
        document.getElementById('settings-notif-complete').checked = s.notify_on_mission_complete !== false;
        document.getElementById('settings-notif-critical').checked = s.notify_on_critical_finding !== false;
        document.getElementById('settings-webhook-url').value = s.webhook_url || '';
        document.getElementById('settings-scan-mode').value = s.default_scan_mode || 'autonomous';
        document.getElementById('settings-report-format').value = s.default_report_format || 'pdf';
        document.getElementById('settings-prefer-approval').checked = s.prefer_mission_approval === true;
        document.getElementById('settings-timezone').value = s.timezone || 'UTC';
    } catch (e) { console.error('Failed to load settings', e); }
}

async function saveByok() {
    const body = {};
    const key = document.getElementById('settings-llm-key').value;
    if (key) body.llm_api_key = key;
    const url = document.getElementById('settings-llm-url').value;
    if (url) body.llm_api_base_url = url;
    const model = document.getElementById('settings-llm-model').value;
    if (model) body.llm_model = model;
    const ek = document.getElementById('settings-emb-key').value;
    if (ek) body.embedding_api_key = ek;
    const eu = document.getElementById('settings-emb-url').value;
    if (eu) body.embedding_api_base_url = eu;
    const em = document.getElementById('settings-emb-model').value;
    if (em) body.embedding_model = em;
    try {
        const { error } = await spectraApi.put('/api/v1/user/settings', body);
        if (!error) { showToast('BYOK settings saved'); loadUserSettings(); }
        else { showToast(error || 'Failed to save BYOK', 'error'); }
    } catch (e) { showToast('Network error', 'error'); }
}

async function clearByok() {
    _spectraConfirm('Clear all BYOK settings? Missions will use system defaults.', async () => {
        try {
            const { error } = await spectraApi.delete('/api/v1/user/settings/byok');
            if (!error) { showToast('BYOK settings cleared'); loadUserSettings(); }
            else showToast('Failed to clear BYOK', 'error');
        } catch (e) { showToast('Network error', 'error'); }
    }, { title: 'Clear BYOK Settings' });
}

async function saveSettings() {
    const body = {
        email_notifications: document.getElementById('settings-email-notif').checked,
        notify_on_mission_complete: document.getElementById('settings-notif-complete').checked,
        notify_on_critical_finding: document.getElementById('settings-notif-critical').checked,
        webhook_url: document.getElementById('settings-webhook-url').value || null,
        default_scan_mode: document.getElementById('settings-scan-mode').value,
        prefer_mission_approval: document.getElementById('settings-prefer-approval').checked,
        default_report_format: document.getElementById('settings-report-format').value,
        timezone: document.getElementById('settings-timezone').value,
    };
    try {
        const { error } = await spectraApi.put('/api/v1/user/settings', body);
        if (!error) showToast('Settings saved');
        else { showToast(error || 'Failed to save settings', 'error'); }
    } catch (e) { showToast('Network error', 'error'); }
}

loadUserSettings();

window.saveByok = saveByok;
window.clearByok = clearByok;
window.saveSettings = saveSettings;
