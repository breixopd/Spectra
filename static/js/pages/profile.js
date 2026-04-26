
// Section navigation
document.querySelectorAll('.profile-sidebar a').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        const section = link.dataset.section;
        document.querySelectorAll('.profile-sidebar a').forEach(l => {
            l.classList.remove('active');
            l.classList.add('text-slate-400');
        });
        link.classList.add('active');
        link.classList.remove('text-slate-400');
        document.querySelectorAll('.profile-section').forEach(s => s.classList.remove('active'));
        document.getElementById(`section-${section}`).classList.add('active');
        if (history.replaceState) history.replaceState(null, '', '#' + section);
    });
});

// Restore section from URL hash
(function() {
    const hash = window.location.hash.slice(1);
    if (hash) {
        const link = document.querySelector(`.profile-sidebar a[data-section="${hash}"]`);
        if (link) link.click();
    }
})();

let profileLoadErrorShown = false;

function ensureProfileLoadErrorElement() {
    const panel = document.querySelector('#section-profile .glass-panel');
    if (!panel) return null;

    let errorEl = document.getElementById('profile-load-error');
    if (!errorEl) {
        errorEl = document.createElement('div');
        errorEl.id = 'profile-load-error';
        errorEl.className = 'hidden mb-4 rounded-lg border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-300';
        const intro = panel.querySelector('p.text-sm.text-slate-400');
        if (intro) {
            intro.insertAdjacentElement('afterend', errorEl);
        } else {
            panel.prepend(errorEl);
        }
    }

    return errorEl;
}

function clearProfileLoadError() {
    const errorEl = document.getElementById('profile-load-error');
    if (errorEl) {
        errorEl.textContent = '';
        errorEl.classList.add('hidden');
    }
    profileLoadErrorShown = false;
}

function showProfileLoadError(message) {
    const errorEl = ensureProfileLoadErrorElement();
    if (errorEl) {
        errorEl.textContent = message;
        errorEl.classList.remove('hidden');
    }
    if (!profileLoadErrorShown && typeof _spectraToast === 'function') {
        _spectraToast(message, 'error');
        profileLoadErrorShown = true;
    }
}

// Load profile
async function loadProfile() {
    try {
        const { data: user, error } = await spectraApi.get('/api/v1/auth/me');
        if (error) throw new Error(error);
        clearProfileLoadError();
        document.getElementById('profile-username').value = user.username || '';
        document.getElementById('profile-email').value = user.email || '';
        document.getElementById('profile-role').value = (user.role || 'operator').charAt(0).toUpperCase() + (user.role || 'operator').slice(1);
    } catch (e) {
        console.error('Failed to load profile', e);
        showProfileLoadError(`Unable to load your profile right now. ${e.message || 'Please try again.'}`);
    }
}

async function saveProfile() {
    const email = document.getElementById('profile-email').value;
    try {
        const { error } = await spectraApi.put('/api/v1/auth/me', { email });
        if (!error) _spectraToast('Profile updated');
        else _spectraToast('Failed to update profile', 'error');
    } catch (e) { _spectraToast('Network error', 'error'); }
}

// Live password requirements checklist for profile change-password
(function() {
    const npw = document.getElementById('new-password');
    if (!npw) return;
    function _upd(id, pass) {
        const el = document.getElementById(id);
        if (!el) return;
        el.style.color = pass ? '#34d399' : '#94a3b8';
        el.querySelector('.pw-req-icon').innerHTML = pass ? '&#x2713;' : '&#x2717;';
    }
    npw.addEventListener('input', () => {
        const v = npw.value;
        _upd('profile-pw-len', v.length >= 8);
        _upd('profile-pw-upper', /[A-Z]/.test(v));
        _upd('profile-pw-lower', /[a-z]/.test(v));
        _upd('profile-pw-digit', /[0-9]/.test(v));
    });
})();

async function changePassword() {
    const current = document.getElementById('current-password').value;
    const newPw = document.getElementById('new-password').value;
    const confirm = document.getElementById('confirm-password').value;
    if (!current || !newPw) return _spectraToast('Please fill all fields', 'error');
    if (newPw !== confirm) return _spectraToast('Passwords do not match', 'error');
    if (newPw.length < 8 || !/[A-Z]/.test(newPw) || !/[a-z]/.test(newPw) || !/[0-9]/.test(newPw)) {
        return _spectraToast('Password must be at least 8 characters with uppercase, lowercase, and a digit', 'error');
    }
    try {
        const { error } = await spectraApi.post('/api/v1/auth/change-password', { current_password: current, new_password: newPw });
        if (!error) {
            _spectraToast('Password changed successfully');
            document.getElementById('current-password').value = '';
            document.getElementById('new-password').value = '';
            document.getElementById('confirm-password').value = '';
        } else {
            _spectraToast(error || 'Failed to change password', 'error');
        }
    } catch (e) { _spectraToast('Network error', 'error'); }
}

// API Keys
async function loadApiKeys() {
    const container = document.getElementById('api-keys-list');
    try {
        const { data: keys, error } = await spectraApi.get('/api/v1/auth/api-keys');
        if (error) { container.innerHTML = '<p class="text-sm text-slate-500 text-center py-4">API keys not available</p>'; return; }
        if (!keys.length) {
            container.innerHTML = '<p class="text-sm text-slate-500 text-center py-6">No API keys yet. Generate one to get started.</p>';
            return;
        }
        container.innerHTML = keys.map(k => `
            <div class="key-row">
                <div class="flex-1 min-w-0">
                    <div class="text-sm font-mono text-white truncate">${escapeHtml(k.prefix || k.key_prefix || '****')}...</div>
                    <div class="text-xs text-slate-500 mt-0.5">Created ${new Date(k.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</div>
                </div>
                <button data-action="revokeApiKey" data-value="${escapeHtml(k.id)}" class="px-2 py-1 text-xs text-rose-400 hover:bg-rose-500/10 rounded transition-colors">Revoke</button>
            </div>
        `).join('');
    } catch (e) { container.innerHTML = '<p class="text-sm text-slate-500 text-center py-4">Could not load API keys</p>'; }
}

async function generateApiKey() {
    _spectraConfirm('Generate a new API key? Your current key will be invalidated.', async () => {
    try {
        const { data, error } = await spectraApi.post('/api/v1/auth/api-keys');
        if (!error) {
            _spectraToast('API key generated — copy it now, it won\'t be shown again');
            if (data.key) {
                const container = document.getElementById('api-keys-list');
                container.insertAdjacentHTML('afterbegin', `
                    <div class="key-row" style="border-color:rgba(16,185,129,0.3);background:rgba(16,185,129,0.05);">
                        <div class="flex-1 min-w-0">
                            <div class="text-sm font-mono text-emerald-400 break-all select-all">${escapeHtml(data.key)}</div>
                            <div class="text-xs text-emerald-500/60 mt-0.5">New key — copy now</div>
                        </div>
                    </div>
                `);
            }
            setTimeout(loadApiKeys, 5000);
        } else _spectraToast('Failed to generate key', 'error');
    } catch (e) { _spectraToast('Network error', 'error'); }
    }, { title: 'Generate API Key' });
}

async function revokeApiKey(keyId) {
    _spectraConfirm('Revoke this API key? This cannot be undone.', async () => {
        try {
            const { error } = await spectraApi.delete(`/api/v1/auth/api-keys/${keyId}`);
            if (!error) { _spectraToast('API key revoked'); loadApiKeys(); }
            else _spectraToast('Failed to revoke key', 'error');
        } catch (e) { _spectraToast('Network error', 'error'); }
    }, { title: 'Revoke API Key' });
}

// Activity log
async function loadActivity() {
    const container = document.getElementById('activity-log');
    try {
        const { data: events, error } = await spectraApi.get('/api/v1/auth/activity?limit=20');
        if (error) { container.innerHTML = '<p class="text-sm text-slate-500 text-center py-4">Activity log not available</p>'; return; }
        if (!events.length) {
            container.innerHTML = '<p class="text-sm text-slate-500 text-center py-6">No recent activity</p>';
            return;
        }
        container.innerHTML = events.map(ev => `
            <div class="activity-row">
                <div class="w-8 h-8 rounded-lg bg-slate-800 flex items-center justify-center shrink-0 mt-0.5">
                    <i data-lucide="${ev.event_type === 'login' ? 'log-in' : ev.event_type === 'logout' ? 'log-out' : 'info'}" class="w-3.5 h-3.5 inline-block text-slate-400"></i>
                </div>
                <div class="flex-1">
                    <div class="text-sm text-white">${escapeHtml(ev.event_type || ev.action || 'Event')}</div>
                    <div class="text-xs text-slate-500 mt-0.5">${new Date(ev.created_at || ev.timestamp).toLocaleString('en-US')}</div>
                </div>
            </div>
        `).join('');
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) { container.innerHTML = '<p class="text-sm text-slate-500 text-center py-4">Could not load activity</p>'; }
}

// Plan info
async function loadPlan() {
    const container = document.getElementById('plan-info');
    try {
        const [meResult, settingsResult] = await Promise.all([
            spectraApi.get('/api/v1/auth/me'),
            spectraApi.get('/api/settings'),
        ]);
        if (meResult.error) return;
        const user = meResult.data;
        const siteSettings = !settingsResult.error ? settingsResult.data : {};
        const paymentProvider = siteSettings.payment_provider || 'manual';
        const hasEntitlement = !!user.plan;
        const subscription = user.subscription || {};
        const subscriptionStatus = subscription.status || '';
        const canManageBilling = !!subscription.can_manage_billing;
        const hasPaymentIssue = subscriptionStatus === 'past_due';
        const planName = hasEntitlement
            ? (user.plan_name || user.plan?.display_name || 'Unnamed plan')
            : (hasPaymentIssue ? 'Billing recovery required' : 'No active plan');
        const plan = user.plan || {};
        const currentPlanId = hasEntitlement ? (plan.id || user.plan_id || '') : '';
        const features = plan.features || {};
        const featureHtml = Object.entries(features)
            .filter(([k, v]) => v && v !== false)
            .map(([k]) => {
                const label = k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
                    .replace(/\bApi\b/, 'API').replace(/\bVpn\b/, 'VPN')
                    .replace(/\bCve\b/, 'CVE').replace(/\bByok\b/, 'BYOK')
                    .replace(/\bSso\b/, 'SSO').replace(/\bSla\b/, 'SLA');
                return `<span class="inline-block px-2 py-0.5 text-xs rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">${escapeHtml(label)}</span>`;
            }).join(' ');

        let actionsHtml = '';
        if (paymentProvider === 'stripe' && canManageBilling) {
            const billingButtonLabel = hasPaymentIssue ? 'Recover Subscription' : 'Manage Billing';
            const billingButtonClasses = hasPaymentIssue
                ? 'bg-amber-600 hover:bg-amber-500'
                : 'bg-slate-700 hover:bg-slate-600';
            actionsHtml = `
                <div class="flex gap-2 mt-4 pt-3 border-t border-white/5">
                    <button data-action="openBillingPortal" class="px-3 py-1.5 ${billingButtonClasses} text-white text-xs font-medium rounded-lg transition-colors">
                        <i data-lucide="credit-card" class="w-3.5 h-3.5 inline-block mr-1"></i> ${billingButtonLabel}
                    </button>
                </div>`;
        } else if (paymentProvider === 'stripe') {
            actionsHtml = `
                <div class="flex gap-2 mt-4 pt-3 border-t border-white/5">
                    <button data-action="showAvailablePlans" class="px-3 py-1.5 bg-violet-600 hover:bg-violet-500 text-white text-xs font-medium rounded-lg transition-colors">
                        <i data-lucide="credit-card" class="w-3.5 h-3.5 inline-block mr-1"></i> Choose Plan
                    </button>
                </div>`;
        } else if (paymentProvider === 'crypto' && hasEntitlement) {
            actionsHtml = `
                <div class="flex gap-2 mt-4 pt-3 border-t border-white/5">
                    <button data-action="showAvailablePlans" class="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium rounded-lg transition-colors">
                        <i data-lucide="bitcoin" class="w-3.5 h-3.5 inline-block mr-1"></i> Pay with Crypto
                    </button>
                </div>`;
        } else if (paymentProvider === 'crypto') {
            actionsHtml = `
                <div class="flex gap-2 mt-4 pt-3 border-t border-white/5">
                    <button data-action="showAvailablePlans" class="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium rounded-lg transition-colors">
                        <i data-lucide="bitcoin" class="w-3.5 h-3.5 inline-block mr-1"></i> Browse Plans
                    </button>
                </div>`;
        } else if (paymentProvider === 'manual') {
            actionsHtml = `
                <div class="mt-4 pt-3 border-t border-white/5">
                    <p class="text-xs text-slate-500"><i data-lucide="info" class="w-3.5 h-3.5 inline-block mr-1"></i> ${hasEntitlement ? 'Your plan is managed by your administrator.' : 'No plan is assigned yet. Your administrator manages access.'}</p>
                </div>`;
        } else {
            actionsHtml = `
                <div class="mt-4 pt-3 border-t border-white/5">
                    <p class="text-xs text-slate-500"><i data-lucide="info" class="w-3.5 h-3.5 inline-block mr-1"></i> Contact your administrator to change your plan.</p>
                </div>`;
        }

        const statusBadge = hasEntitlement
            ? '<span class="px-2 py-1 text-xs font-medium rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Active</span>'
            : hasPaymentIssue
                ? '<span class="px-2 py-1 text-xs font-medium rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">Past due</span>'
            : '<span class="px-2 py-1 text-xs font-medium rounded bg-slate-700/60 text-slate-300 border border-white/10">None</span>';
        const missionsLabel = hasEntitlement
            ? escapeHtml(String(plan.max_missions_per_month || user.max_missions_per_month || 'Unlimited'))
            : 'Not assigned';
        const targetsLabel = hasEntitlement
            ? escapeHtml(String(plan.max_targets || user.max_targets || 'Unlimited'))
            : 'Not assigned';
        const apiLabel = hasEntitlement
            ? escapeHtml(String(plan.max_api_requests_per_hour || user.max_api_requests_per_hour || '—'))
            : 'Not assigned';
        const storageLabel = hasEntitlement && (plan.max_storage_mb || user.max_storage_mb)
            ? `${escapeHtml(String(plan.max_storage_mb || user.max_storage_mb))} MB`
            : 'Not assigned';

        container.innerHTML = `
            <div class="glass-panel rounded-lg p-4 border border-white/5">
                <div class="flex items-center justify-between mb-3">
                    <div>
                        <div class="text-lg font-semibold text-white">${escapeHtml(planName)}</div>
                        <div class="text-xs text-slate-500 mt-0.5">${hasEntitlement ? 'Current plan' : hasPaymentIssue ? `Subscription recovery available${subscription.plan_display_name ? ` for ${escapeHtml(subscription.plan_display_name)}` : ''}` : 'No subscription-backed entitlement'}</div>
                    </div>
                    ${statusBadge}
                </div>
                <div class="grid grid-cols-2 gap-3 mt-4">
                    <div class="bg-slate-900/50 rounded p-3">
                        <div class="text-xs text-slate-500">Missions / month</div>
                        <div class="text-sm font-medium text-white mt-0.5">${missionsLabel}</div>
                    </div>
                    <div class="bg-slate-900/50 rounded p-3">
                        <div class="text-xs text-slate-500">Max targets</div>
                        <div class="text-sm font-medium text-white mt-0.5">${targetsLabel}</div>
                    </div>
                    <div class="bg-slate-900/50 rounded p-3">
                        <div class="text-xs text-slate-500">API req / hour</div>
                        <div class="text-sm font-medium text-white mt-0.5">${apiLabel}</div>
                    </div>
                    <div class="bg-slate-900/50 rounded p-3">
                        <div class="text-xs text-slate-500">Storage</div>
                        <div class="text-sm font-medium text-white mt-0.5">${storageLabel}</div>
                    </div>
                </div>
                ${featureHtml ? `<div class="flex flex-wrap gap-1.5 mt-4 pt-3 border-t border-white/5">${featureHtml}</div>` : ''}
                ${actionsHtml}
            </div>
            <div id="available-plans" class="hidden mt-4 space-y-3"></div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        // Store current plan id for comparison
        container.dataset.currentPlanId = currentPlanId;
    } catch (e) { container.innerHTML = '<p class="text-sm text-slate-500 text-center py-4">Could not load plan info</p>'; }
}

async function showAvailablePlans() {
    const target = document.getElementById('available-plans');
    if (!target) return;
    if (!target.classList.contains('hidden')) { target.classList.add('hidden'); return; }
    target.innerHTML = '<div class="text-sm text-slate-500 text-center py-4">Loading plans...</div>';
    target.classList.remove('hidden');
    try {
        const { data: plans, error } = await spectraApi.get('/api/v1/billing/plans');
        if (error) throw new Error('Failed to fetch plans');
        const currentId = document.getElementById('plan-info')?.dataset?.currentPlanId || '';
        target.innerHTML = plans.map(p => {
            const isCurrent = p.id === currentId;
            const checkoutAvailable = p.checkout_available === true;
            return `
                <div class="glass-panel rounded-lg p-4 border ${isCurrent ? 'border-violet-500/40' : 'border-white/5'}">
                    <div class="flex items-center justify-between">
                        <div>
                            <div class="text-sm font-semibold text-white">${escapeHtml(p.display_name)}</div>
                            ${p.description ? `<div class="text-xs text-slate-400 mt-0.5">${escapeHtml(p.description)}</div>` : ''}
                            <div class="flex gap-3 mt-2 text-xs text-slate-500">
                                <span>${escapeHtml(String(p.max_missions_per_month || '∞'))} missions/mo</span>
                                <span>${escapeHtml(String(p.max_targets || '∞'))} targets</span>
                                <span>${escapeHtml(String(p.max_storage_mb || 0))} MB</span>
                            </div>
                        </div>
                        <div>
                            ${isCurrent
                                ? '<span class="px-2 py-1 text-xs font-medium rounded bg-violet-500/10 text-violet-400 border border-violet-500/20">Current</span>'
                                : checkoutAvailable
                                    ? `<button data-action="startCheckout" data-value="${escapeHtml(String(p.id || ''))}" class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium rounded-lg transition-colors">Select</button>`
                                    : '<span class="px-2 py-1 text-xs text-slate-500">Not available</span>'}
                        </div>
                    </div>
                </div>`;
        }).join('');
    } catch (e) { target.innerHTML = '<p class="text-sm text-red-400 text-center py-4">Could not load plans</p>'; }
}

function getSafeExternalHttpsUrl(urlValue) {
    if (typeof urlValue !== 'string') return null;

    try {
        const parsedUrl = new URL(urlValue.trim());
        if (parsedUrl.protocol !== 'https:' || !parsedUrl.hostname || parsedUrl.username || parsedUrl.password) {
            return null;
        }
        return parsedUrl.toString();
    } catch {
        return null;
    }
}

async function startCheckout(planId) {
    try {
        const { data, error } = await spectraApi.post('/api/v1/billing/checkout?plan_id=' + encodeURIComponent(planId));
        if (error) throw new Error(error || 'Checkout failed');
        if (data.checkout_url) {
            const checkoutUrl = getSafeExternalHttpsUrl(data.checkout_url);
            if (!checkoutUrl) {
                _spectraToast('Invalid checkout URL returned', 'error');
                return;
            }
            window.location.assign(checkoutUrl);
        } else {
            _spectraToast('No checkout URL returned — payment provider may not be configured', 'error');
        }
    } catch (e) { _spectraToast(e.message, 'error'); }
}

async function openBillingPortal() {
    try {
        const { data, error } = await spectraApi.get('/api/v1/billing/portal');
        if (error) throw new Error(error || 'Could not open portal');
        if (data.portal_url) {
            const portalUrl = getSafeExternalHttpsUrl(data.portal_url);
            if (!portalUrl) {
                _spectraToast('Invalid billing portal URL returned', 'error');
                return;
            }
            const portalWindow = window.open(portalUrl, '_blank', 'noopener,noreferrer');
            if (portalWindow) portalWindow.opener = null;
        } else {
            _spectraToast('Billing portal not available', 'error');
        }
    } catch (e) { _spectraToast(e.message, 'error'); }
}

// ---- User Settings ----
let userPlanFeatures = {};

async function loadUserSettings() {
    try {
        // Load plan features first
        const { data: me, error: meError } = await spectraApi.get('/api/v1/auth/me');
        if (!meError) {
            userPlanFeatures = me.plan?.features || {};
            // Gate BYOK
            const byokAllowed = userPlanFeatures.byok === true;
            document.getElementById('byok-gate').classList.toggle('hidden', byokAllowed);
            document.getElementById('byok-fields').style.opacity = byokAllowed ? '1' : '0.4';
            document.getElementById('byok-fields').style.pointerEvents = byokAllowed ? 'auto' : 'none';
        }

        // Load current settings
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
        if (!error) { _spectraToast('BYOK settings saved'); loadUserSettings(); }
        else { _spectraToast(error || 'Failed to save BYOK', 'error'); }
    } catch (e) { _spectraToast('Network error', 'error'); }
}

async function clearByok() {
    _spectraConfirm('Clear all BYOK settings? Missions will use system defaults.', async () => {
        try {
            const { error } = await spectraApi.delete('/api/v1/user/settings/byok');
            if (!error) { _spectraToast('BYOK settings cleared'); loadUserSettings(); }
            else _spectraToast('Failed to clear BYOK', 'error');
        } catch (e) { _spectraToast('Network error', 'error'); }
    }, { title: 'Clear BYOK Settings' });
}

async function saveSettings() {
    const body = {
        email_notifications: document.getElementById('settings-email-notif').checked,
        notify_on_mission_complete: document.getElementById('settings-notif-complete').checked,
        notify_on_critical_finding: document.getElementById('settings-notif-critical').checked,
        webhook_url: document.getElementById('settings-webhook-url').value || null,
        default_scan_mode: document.getElementById('settings-scan-mode').value,
        default_report_format: document.getElementById('settings-report-format').value,
        timezone: document.getElementById('settings-timezone').value,
    };
    try {
        const { error } = await spectraApi.put('/api/v1/user/settings', body);
        if (!error) _spectraToast('Settings saved');
        else { _spectraToast(error || 'Failed to save settings', 'error'); }
    } catch (e) { _spectraToast('Network error', 'error'); }
}

// Initialize
loadProfile();
loadApiKeys();
loadActivity();
loadPlan();
loadMfaStatus();
loadUserSettings();
loadDataPrivacy();

async function deleteAccount() {
    _spectraPrompt('Type your password to confirm account deletion:', (pw) => {
        _spectraConfirm('Are you absolutely sure? This will permanently delete your account and ALL data.', async () => {
            try {
                const { data, error } = await spectraApi.request('/api/v1/auth/account', { method: 'DELETE', body: { password: pw } });
                if (!error) {
                    window.location.href = '/login?msg=account_deleted';
                } else {
                    _spectraToast(error || 'Failed to delete account', 'error');
                }
            } catch (e) { _spectraToast('Network error', 'error'); }
        }, { title: 'Delete Account', confirmLabel: 'Delete Permanently' });
    }, { title: 'Account Deletion', inputType: 'password', placeholder: 'Enter your password', confirmLabel: 'Continue' });
}

// MFA functions
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
        if (error) { _spectraToast(error || 'Failed to start MFA setup', 'error'); return; }
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
    } catch (e) { _spectraToast('Network error', 'error'); }
}

function cancelMfaSetup() {
    document.getElementById('mfa-setup-flow').classList.add('hidden');
    document.getElementById('mfa-status-area').classList.remove('hidden');
    document.getElementById('mfa-verify-code').value = '';
}

async function verifyMfaSetup() {
    const code = document.getElementById('mfa-verify-code').value.trim();
    if (!/^\d{6}$/.test(code)) return _spectraToast('Enter a valid 6-digit code', 'error');
    try {
        const { error } = await spectraApi.post('/api/v1/auth/mfa/verify-setup', { code });
        if (!error) {
            _spectraToast('MFA enabled successfully');
            document.getElementById('mfa-setup-flow').classList.add('hidden');
            document.getElementById('mfa-status-area').classList.remove('hidden');
            loadMfaStatus();
        } else {
            _spectraToast(error || 'Verification failed', 'error');
        }
    } catch (e) { _spectraToast('Network error', 'error'); }
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
    if (!password) return _spectraToast('Enter your password', 'error');
    if (!/^\d{6}$/.test(code)) return _spectraToast('Enter a valid 6-digit code', 'error');
    try {
        const { error } = await spectraApi.post('/api/v1/auth/mfa/disable', { password, code });
        if (!error) {
            _spectraToast('MFA disabled');
            document.getElementById('mfa-disable-flow').classList.add('hidden');
            document.getElementById('mfa-status-area').classList.remove('hidden');
            document.getElementById('mfa-disable-password').value = '';
            document.getElementById('mfa-disable-code').value = '';
            loadMfaStatus();
        } else {
            _spectraToast(error || 'Failed to disable MFA', 'error');
        }
    } catch (e) { _spectraToast('Network error', 'error'); }
}

// ---- Data & Privacy ----
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

// Expose functions used by HTML onclick handlers
window.downloadMyData = downloadMyData;
window.toggleRestrictProcessing = toggleRestrictProcessing;
window.toggleShareTraining = toggleShareTraining;
window.saveProfile = saveProfile;
window.deleteAccount = deleteAccount;
window.changePassword = changePassword;
window.verifyMfaSetup = verifyMfaSetup;
window.cancelMfaSetup = cancelMfaSetup;
window.confirmDisableMfa = confirmDisableMfa;
window.cancelDisableMfa = cancelDisableMfa;
window.generateApiKey = generateApiKey;
window.revokeApiKey = revokeApiKey;
window.saveByok = saveByok;
window.clearByok = clearByok;
window.saveSettings = saveSettings;
window.showAvailablePlans = showAvailablePlans;
window.openBillingPortal = openBillingPortal;
window.startCheckout = startCheckout;
window.startMfaSetup = startMfaSetup;
window.startDisableMfa = startDisableMfa;
