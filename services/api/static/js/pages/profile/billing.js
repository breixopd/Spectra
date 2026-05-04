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
                showToast('Invalid checkout URL returned', 'error');
                return;
            }
            window.location.assign(checkoutUrl);
        } else {
            showToast('No checkout URL returned — payment provider may not be configured', 'error');
        }
    } catch (e) { showToast(e.message, 'error'); }
}

async function openBillingPortal() {
    try {
        const { data, error } = await spectraApi.get('/api/v1/billing/portal');
        if (error) throw new Error(error || 'Could not open portal');
        if (data.portal_url) {
            const portalUrl = getSafeExternalHttpsUrl(data.portal_url);
            if (!portalUrl) {
                showToast('Invalid billing portal URL returned', 'error');
                return;
            }
            const portalWindow = window.open(portalUrl, '_blank', 'noopener,noreferrer');
            if (portalWindow) portalWindow.opener = null;
        } else {
            showToast('Billing portal not available', 'error');
        }
    } catch (e) { showToast(e.message, 'error'); }
}

loadPlan();

window.showAvailablePlans = showAvailablePlans;
window.openBillingPortal = openBillingPortal;
window.startCheckout = startCheckout;
