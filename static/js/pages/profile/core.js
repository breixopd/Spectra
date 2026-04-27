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

window.clearProfileLoadError = clearProfileLoadError;
window.showProfileLoadError = showProfileLoadError;
