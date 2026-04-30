// ========== SCOPE MANAGEMENT ==========
let scopeTargets = JSON.parse(localStorage.getItem('spectra_scope_targets') || '[]');
let scopeExclusions = JSON.parse(localStorage.getItem('spectra_scope_exclusions') || '[]');

function toggleScopePanel() {
    document.getElementById('scope-panel').classList.toggle('open');
    renderScopeTargets();
    renderScopeExclusions();
}

function addScopeTarget() {
    const type = document.getElementById('scope-target-type').value;
    const value = document.getElementById('scope-target-value').value.trim();
    const notes = document.getElementById('scope-target-notes').value.trim();
    if (!value) return;
    scopeTargets.push({type, value, notes});
    localStorage.setItem('spectra_scope_targets', JSON.stringify(scopeTargets));
    syncManualStateToServer();
    document.getElementById('scope-target-value').value = '';
    document.getElementById('scope-target-notes').value = '';
    renderScopeTargets();
}

function removeScopeTarget(idx) {
    scopeTargets.splice(idx, 1);
    localStorage.setItem('spectra_scope_targets', JSON.stringify(scopeTargets));
    syncManualStateToServer();
    renderScopeTargets();
}

function renderScopeTargets() {
    const icons = {ip:'network', domain:'globe', url:'link'};
    document.getElementById('scope-targets-list').innerHTML = scopeTargets.map((t, i) =>
        `<div class="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-white/[0.02]">
            <i data-lucide="${icons[t.type] || 'circle'}" class="w-3.5 h-3.5 inline-block ${t.type === 'ip' ? 'text-blue-400' : t.type === 'domain' ? 'text-emerald-400' : t.type === 'url' ? 'text-violet-400' : 'text-slate-400'}"></i>
            <span class="text-xs text-slate-500 uppercase w-12">${t.type}</span>
            <span class="text-white font-mono flex-1 truncate">${escapeHtml(t.value)}</span>
            <span class="text-slate-500 text-xs truncate max-w-[100px]">${escapeHtml(t.notes)}</span>
            <button data-action="removeScopeTarget" data-value="${i}" class="text-slate-600 hover:text-rose-400 transition-colors"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>`
    ).join('') || '<div class="text-slate-500 text-xs py-1">No targets defined</div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function addScopeExclusion() {
    const type = document.getElementById('scope-excl-type').value;
    const value = document.getElementById('scope-excl-value').value.trim();
    const reason = document.getElementById('scope-excl-reason').value.trim();
    if (!value) return;
    scopeExclusions.push({type, value, reason});
    localStorage.setItem('spectra_scope_exclusions', JSON.stringify(scopeExclusions));
    syncManualStateToServer();
    document.getElementById('scope-excl-value').value = '';
    document.getElementById('scope-excl-reason').value = '';
    renderScopeExclusions();
}

function removeScopeExclusion(idx) {
    scopeExclusions.splice(idx, 1);
    localStorage.setItem('spectra_scope_exclusions', JSON.stringify(scopeExclusions));
    syncManualStateToServer();
    renderScopeExclusions();
}

function renderScopeExclusions() {
    document.getElementById('scope-exclusions-list').innerHTML = scopeExclusions.map((e, i) =>
        `<div class="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-rose-500/5">
            <i data-lucide="ban" class="w-3.5 h-3.5 inline-block text-rose-400"></i>
            <span class="text-xs text-slate-500 uppercase w-12">${e.type}</span>
            <span class="text-rose-300 font-mono flex-1 truncate">${escapeHtml(e.value)}</span>
            <span class="text-slate-500 text-xs truncate max-w-[100px]">${escapeHtml(e.reason)}</span>
            <button data-action="removeScopeExclusion" data-value="${i}" class="text-slate-600 hover:text-rose-400 transition-colors"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>`
    ).join('') || '<div class="text-slate-500 text-xs py-1">No exclusions defined</div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function saveScope() {
    localStorage.setItem('spectra_scope_roe', document.getElementById('scope-roe').value);
    syncManualStateToServer();
    _spectraToast('Scope saved to session', 'success');
}
