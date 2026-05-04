async function loadMfaStatus() {
    const area = document.getElementById('mfa-status-area');
    try {
        const { data: user, error } = await spectraApi.get('/api/v1/auth/me');
        if (error) return;
        const enabled = !!user.mfa_enabled;
        if (enabled) {
            area.innerHTML = `
                <div class="flex items-center justify-between p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                    <div class="flex items-center gap-2">
                        <i data-lucide="shield" class="w-4 h-4 inline-block text-emerald-400"></i>
                        <span class="text-sm font-medium text-emerald-400">MFA is enabled</span>
                    </div>
                    <button data-action="startDisableMfa" class="px-3 py-1.5 text-xs text-rose-400 hover:bg-rose-500/10 rounded-lg border border-rose-500/20 transition-colors">
                        Disable
                    </button>
                </div>`;
            if (typeof lucide !== 'undefined') lucide.createIcons();
        } else {
            area.innerHTML = `
                <div class="flex items-center justify-between p-3 rounded-lg bg-slate-800/50 border border-white/5">
                    <div class="flex items-center gap-2">
                        <i data-lucide="shield" class="w-4 h-4 inline-block text-slate-500"></i>
                        <span class="text-sm text-slate-400">MFA is not enabled</span>
                    </div>
                    <button data-action="startMfaSetup" class="px-3 py-1.5 text-xs bg-violet-600 hover:bg-violet-500 text-white rounded-lg transition-colors font-medium">
                        Enable MFA
                    </button>
                </div>`;
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    } catch (e) {
        area.innerHTML = '<p class="text-sm text-slate-500 text-center py-4">Could not load MFA status</p>';
    }
}

async function startMfaSetup() {
    try {
        const { data, error } = await spectraApi.post('/api/v1/auth/mfa/setup');
        if (error) { showToast(error || 'Failed to start MFA setup', 'error'); return; }
        document.getElementById('mfa-secret-display').textContent = data.secret;
        const qrArea = document.getElementById('mfa-qr-code');
        qrArea.innerHTML = '';
        if (typeof QRCode !== 'undefined') {
            new QRCode(qrArea, { text: data.provisioning_uri, width: 180, height: 180, colorDark: '#000', colorLight: '#fff' });
        } else {
            qrArea.innerHTML = '<p class="text-xs text-slate-500">QR library not loaded. Use the secret below.</p>';
        }
        document.getElementById('mfa-status-area').classList.add('hidden');
        document.getElementById('mfa-setup-flow').classList.remove('hidden');
    } catch (e) { showToast('Network error', 'error'); }
}

function cancelMfaSetup() {
    document.getElementById('mfa-setup-flow').classList.add('hidden');
    document.getElementById('mfa-status-area').classList.remove('hidden');
    document.getElementById('mfa-verify-code').value = '';
}

async function verifyMfaSetup() {
    const code = document.getElementById('mfa-verify-code').value.trim();
    if (!/^\d{6}$/.test(code)) return showToast('Enter a valid 6-digit code', 'error');
    try {
        const { error } = await spectraApi.post('/api/v1/auth/mfa/verify-setup', { code });
        if (!error) {
            showToast('MFA enabled successfully');
            document.getElementById('mfa-setup-flow').classList.add('hidden');
            document.getElementById('mfa-status-area').classList.remove('hidden');
            loadMfaStatus();
        } else {
            showToast(error || 'Verification failed', 'error');
        }
    } catch (e) { showToast('Network error', 'error'); }
}

function startDisableMfa() {
    document.getElementById('mfa-status-area').classList.add('hidden');
    document.getElementById('mfa-disable-flow').classList.remove('hidden');
}

function cancelDisableMfa() {
    document.getElementById('mfa-disable-flow').classList.add('hidden');
    document.getElementById('mfa-status-area').classList.remove('hidden');
    document.getElementById('mfa-disable-password').value = '';
    document.getElementById('mfa-disable-code').value = '';
}

async function confirmDisableMfa() {
    const password = document.getElementById('mfa-disable-password').value;
    const code = document.getElementById('mfa-disable-code').value.trim();
    if (!password) return showToast('Enter your password', 'error');
    if (!/^\d{6}$/.test(code)) return showToast('Enter a valid 6-digit code', 'error');
    try {
        const { error } = await spectraApi.post('/api/v1/auth/mfa/disable', { password, code });
        if (!error) {
            showToast('MFA disabled');
            document.getElementById('mfa-disable-flow').classList.add('hidden');
            document.getElementById('mfa-status-area').classList.remove('hidden');
            document.getElementById('mfa-disable-password').value = '';
            document.getElementById('mfa-disable-code').value = '';
            loadMfaStatus();
        } else {
            showToast(error || 'Failed to disable MFA', 'error');
        }
    } catch (e) { showToast('Network error', 'error'); }
}

loadMfaStatus();

window.verifyMfaSetup = verifyMfaSetup;
window.cancelMfaSetup = cancelMfaSetup;
window.confirmDisableMfa = confirmDisableMfa;
window.cancelDisableMfa = cancelDisableMfa;
window.startMfaSetup = startMfaSetup;
window.startDisableMfa = startDisableMfa;
