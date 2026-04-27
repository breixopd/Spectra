// === Wordlist Management ===
async function loadWordlists() {
    try {
        const { data, error } = await spectraApi.get('/api/v1/wordlists');
        const wordlists = data?.wordlists || data?.local || [];
        const presets = data?.presets || [];

        let html = '';
        if (wordlists.length) {
            html += wordlists.map(w => `
                <div class="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-white/[0.02] hover:bg-white/[0.05] group">
                    <i data-lucide="file-text" class="w-4 h-4 inline-block text-amber-400/60 shrink-0"></i>
                    <span class="text-white truncate flex-1 font-mono">${escapeHtml(w.name || w)}</span>
                    ${w.size ? `<span class="text-slate-500 text-xs shrink-0">${w.size}</span>` : ''}
                    <button || w.name || w)}')" class="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-white transition-all" title="Copy path"><i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i></button>
                </div>
            `).join('');
        }

        if (presets.length) {
            html += '<div class="text-xs text-slate-500 uppercase font-bold mt-3 mb-1">Available for Download</div>';
            html += presets.map(p => `
                <div class="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-white/[0.02] ${p.downloaded ? 'opacity-50' : 'hover:bg-white/[0.05]'}">
                    <i data-lucide="download" class="w-4 h-4 inline-block text-blue-400/60 shrink-0"></i>
                    <span class="text-slate-300 truncate flex-1">${escapeHtml(p.name)} <span class="text-slate-500">(${p.entries} entries)</span></span>
                    ${!p.downloaded ? `<button data-action="downloadPreset" data-value="${escapeAttr(p.id)}" class="px-1.5 py-0.5 bg-blue-600/80 hover:bg-blue-500 text-white rounded text-xs transition-colors">Get</button>` : '<span class="text-emerald-400 text-xs">\u2713</span>'}
                </div>
            `).join('');
        }

        document.getElementById('wordlist-list').innerHTML = html || '<div class="text-slate-500 text-xs">No wordlists found</div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch(e) {
        document.getElementById('wordlist-list').innerHTML = '<div class="text-rose-400 text-xs">Failed to load</div>';
    }
}

async function downloadPreset(presetId) {
    try {
        await spectraApi.post(`/api/v1/wordlists/download-preset/${encodeURIComponent(presetId)}`);
        loadWordlists();
    } catch(e) { console.error(e); }
}

async function uploadWordlist(input) {
    const file = input.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
        await spectraApi.post('/api/v1/wordlists/upload', form);
        loadWordlists();
    } catch(e) { console.error(e); }
    input.value = '';
}

async function refreshWordlistOptions() {
    try {
        const { data } = await spectraApi.get('/api/v1/wordlists');
        const wordlists = data?.wordlists || data?.local || [];
        const dl = document.getElementById('wordlist-options');
        if (dl) {
            dl.innerHTML = wordlists.map(w => `<option value="${escapeAttr(w.path || w.name || w)}">`).join('');
        }
    } catch(e) { /* ignore */ }
}
