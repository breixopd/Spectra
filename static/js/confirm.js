// Spectra global confirm/prompt dialogs and auth bootstrap
// Extracted from base.html inline script

// Public paths constant (shared with api.js)
window.PUBLIC_PATHS = ['/login', '/setup', '/register', '/landing', '/forgot-password', '/reset-password', '/verify-email', '/status', '/legal/terms', '/legal/privacy', '/legal/cookies', '/security', '/changelog'];

// _spectraToast stub — real implementation loaded from toast.js module
function _spectraToast(msg, type) {
    // Queue until module loads
    (window._toastQueue = window._toastQueue || []).push({ msg, type });
}

function _spectraConfirm(msg, onConfirm, opts) {
    opts = opts || {};
    var modal = document.getElementById('spectra-gc-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'spectra-gc-modal';
        modal.className = 'hidden fixed inset-0 z-50 flex items-center justify-center p-4';
        modal.setAttribute('role', 'dialog');
        modal.innerHTML = '<div class="fixed inset-0 bg-black/60 backdrop-filter backdrop-blur-sm" data-gc-dismiss></div>'
            + '<div class="relative w-full max-w-md glass-panel rounded-2xl shadow-2xl">'
            + '<div class="p-6">'
            + '<h3 id="spectra-gc-title" class="text-lg font-semibold text-white mb-2"></h3>'
            + '<p id="spectra-gc-msg" class="text-sm text-slate-400 mb-4"></p>'
            + '<div id="spectra-gc-input-area" class="hidden mb-4"></div>'
            + '<div class="flex gap-3 justify-end">'
            + '<button id="spectra-gc-cancel" class="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors">Cancel</button>'
            + '<button id="spectra-gc-ok" class="px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-semibold transition-colors">Confirm</button>'
            + '</div></div></div>';
        document.body.appendChild(modal);
    }
    document.getElementById('spectra-gc-title').textContent = opts.title || 'Confirm';
    document.getElementById('spectra-gc-msg').textContent = msg;
    var inputArea = document.getElementById('spectra-gc-input-area');
    inputArea.classList.add('hidden');
    inputArea.innerHTML = '';
    var okBtn = document.getElementById('spectra-gc-ok');
    var cancelBtn = document.getElementById('spectra-gc-cancel');
    okBtn.textContent = opts.confirmLabel || 'Confirm';
    cancelBtn.style.display = opts.hideCancel ? 'none' : '';
    var newOk = okBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(newOk, okBtn);
    var newCancel = cancelBtn.cloneNode(true);
    cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);
    function dismiss() { modal.classList.add('hidden'); }
    modal.querySelector('[data-gc-dismiss]').onclick = dismiss;
    newCancel.addEventListener('click', dismiss);
    newOk.addEventListener('click', function() { dismiss(); if (onConfirm) onConfirm(); });
    modal.classList.remove('hidden');
}

function _spectraPrompt(msg, onSubmit, opts) {
    opts = opts || {};
    _spectraConfirm(msg, null, opts);
    var inputArea = document.getElementById('spectra-gc-input-area');
    inputArea.classList.remove('hidden');
    inputArea.textContent = ''; // Clear safely
    var inp = document.createElement('input');
    inp.id = 'spectra-gc-input';
    inp.type = opts.inputType || 'text';
    inp.className = 'w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2 text-white focus:border-violet-500 focus:outline-none';
    inp.placeholder = opts.placeholder || '';
    inp.autocomplete = 'off';
    inputArea.appendChild(inp);
    var okBtn = document.getElementById('spectra-gc-ok');
    var newOk = okBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(newOk, okBtn);
    newOk.addEventListener('click', function() {
        var val = inp.value;
        if (val) { document.getElementById('spectra-gc-modal').classList.add('hidden'); onSubmit(val); }
    });
    inp.focus();
}

// Plan-gate nav items (deferred to DOMContentLoaded — requires spectraApi + DOM)
document.addEventListener('DOMContentLoaded', function() {
    if (!window.PUBLIC_PATHS.includes(window.location.pathname)) {
        spectraApi.get('/api/v1/auth/me')
            .then(function(result) {
                if (result.error) {
                    // Check if setup is needed before redirecting
                    spectraApi.get('/api/v1/auth/setup/status')
                        .then(function(r2) {
                            if (r2.data && !r2.data.is_setup) {
                                window.location.href = '/setup';
                            } else {
                                window.location.href = '/login';
                            }
                        })
                        .catch(function() { window.location.href = '/login'; });
                    return;
                }

                var user = result.data;
                var sidebarUser = document.getElementById('sidebar-username');
                var adminNavLink = document.getElementById('admin-nav-link');
                if (sidebarUser) sidebarUser.textContent = (user && (user.username || user.email)) || 'User';
                if (adminNavLink) {
                    var isAdmin = user && (user.is_superuser || String(user.role || '').toLowerCase() === 'admin');
                    if (isAdmin) {
                        adminNavLink.classList.remove('hidden');
                    } else {
                        adminNavLink.classList.add('hidden');
                    }
                }
                var features = (user && user.plan && user.plan.features) || {};
                document.querySelectorAll('[data-entitlement-gate]').forEach(function(el) {
                    var feat = el.dataset.entitlementGate;
                    var allowed = isAdmin || features[feat] === true;
                    if (!allowed) {
                        el.classList.add('pointer-events-none', 'opacity-40');
                        el.removeAttribute('href');
                        el.setAttribute('aria-disabled', 'true');
                        el.setAttribute('title', 'Requires a plan with ' + feat.replace(/_/g, ' ') + '. Upgrade or contact your administrator.');
                        el.style.cursor = 'not-allowed';
                        // Add upgrade link after the gated element
                        if (el.parentNode && !el.parentNode.querySelector('[data-upgrade-link-for="' + feat + '"]')) {
                            var upgrade = document.createElement('span');
                            upgrade.className = 'text-xs text-violet-400 ml-1';
                            upgrade.dataset.upgradeLinkFor = feat;
                            upgrade.innerHTML = '<a href="/profile#plan" class="hover:text-violet-300 transition-colors pointer-events-auto">Upgrade</a>';
                            el.parentNode.appendChild(upgrade);
                        }
                    }
                });
            })
            .catch(function() {});
    }
});
