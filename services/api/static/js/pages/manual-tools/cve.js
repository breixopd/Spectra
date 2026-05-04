// === CVE Lookup ===
async function searchCVEs() {
    const product = document.getElementById('cve-product')?.value?.trim();
    const version = document.getElementById('cve-version')?.value?.trim();
    const service = document.getElementById('cve-service')?.value?.trim();
    const results = document.getElementById('cve-results');
    const countEl = document.getElementById('cve-count');
    const btn = document.getElementById('cve-search-btn');

    if (!product && !service) {
        results.innerHTML = '<div class="text-amber-400 text-sm text-center py-4">Enter a product or service name.</div>';
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin mr-1"></i> Searching...';
    results.innerHTML = '<div class="text-slate-500 text-sm text-center py-8">Searching CVE databases...</div>';

    try {
        const params = new URLSearchParams();
        if (product) params.set('product', product);
        if (version) params.set('version', version);
        if (service) params.set('service', service);

        const res = await spectraApi.get('/api/v1/cve/lookup?' + params.toString());
        const data = res.data;
        const cves = data?.cves || [];
        countEl.textContent = `${data.total || cves.length} found`;

        if (!cves.length) {
            results.innerHTML = '<div class="text-slate-500 text-sm text-center py-8">No CVEs found for this query.</div>';
            return;
        }

        results.innerHTML = cves.map(c => {
            const sevColor = {critical:'text-rose-400 bg-rose-500/10',high:'text-amber-400 bg-amber-500/10',medium:'text-blue-400 bg-blue-500/10',low:'text-slate-400 bg-slate-500/10'}[(c.severity||'').toLowerCase()] || 'text-slate-400 bg-slate-500/10';
            const cveId = c.cve_id || c.cve || c.id || 'N/A';

            let msfHtml = '';
            if (c.metasploit_modules && c.metasploit_modules.length > 0) {
                msfHtml = `<div class="mt-2 pt-2 border-t border-white/5">
                    <div class="flex items-center gap-2 mb-1.5">
                        <i data-lucide="skull" class="w-3.5 h-3.5 inline-block text-rose-400"></i>
                        <span class="text-xs font-bold text-rose-400 uppercase">Metasploit Modules</span>
                    </div>
                    <div class="space-y-1">
                        ${c.metasploit_modules.map(m => `
                            <div class="flex items-center gap-2 text-[11px] px-2 py-1 bg-black/30 rounded group">
                                <span class="px-1 py-0.5 rounded text-xs font-mono uppercase ${m.type === 'exploit' ? 'bg-rose-500/20 text-rose-400' : 'bg-blue-500/20 text-blue-400'}">${escapeHtml(m.type)}</span>
                                <code class="text-slate-300 font-mono truncate flex-1">${escapeHtml(m.module)}</code>
                                <span class="text-xs text-slate-500 font-mono">${escapeHtml(m.rank || '')}</span>
                                <button data-action="clipCopy" data-value="${escapeAttr(m.module)}" class="opacity-0 group-hover:opacity-100 px-1.5 py-0.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded text-xs transition-all" title="Copy module path">
                                    <i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i>
                                </button>
                                <button data-action="launchMetasploit" data-value="${escapeAttr(m.module)}" data-cve="${escapeAttr(cveId)}" class="opacity-0 group-hover:opacity-100 px-1.5 py-0.5 bg-rose-600/80 hover:bg-rose-500 text-white rounded text-xs transition-all" title="Use in Metasploit">
                                    <i data-lucide="rocket" class="w-3.5 h-3.5 inline-block"></i>
                                </button>
                            </div>
                        `).join('')}
                    </div>
                </div>`;
            }

            let exploitBadge = c.exploit_available
                ? `<span class="px-1.5 py-0.5 rounded text-xs font-mono bg-rose-500/20 text-rose-400"><i data-lucide="skull" class="w-3 h-3 inline-block mr-0.5"></i> ${c.exploit_count} exploit${c.exploit_count > 1 ? 's' : ''}</span>`
                : '';

            return `<div class="p-3 rounded-lg bg-black/20 border border-white/5 hover:border-white/10 transition-colors">
                <div class="flex items-center gap-3 mb-1">
                    <code class="text-violet-300 font-mono text-sm font-medium">${escapeHtml(cveId)}</code>
                    <span class="px-1.5 py-0.5 rounded text-xs font-mono uppercase ${sevColor}">${escapeHtml(c.severity || 'unknown')}</span>
                    ${exploitBadge}
                    ${c.type ? `<span class="text-xs text-slate-500 font-mono">${escapeHtml(c.type)}</span>` : ''}
                    ${c.version_match ? '<span class="text-xs text-emerald-400 font-mono">version match</span>' : ''}
                </div>
                <p class="text-sm text-slate-300 line-clamp-2">${escapeHtml(c.description || '')}</p>
                ${c.product ? `<div class="text-xs text-slate-500 mt-1">${escapeHtml(c.product)} ${c.versions || ''}</div>` : ''}
                ${msfHtml}
            </div>`;
        }).join('');
    } catch (e) {
        results.innerHTML = `<div class="text-red-400 text-sm text-center py-4">Error: ${escapeHtml(e.message)}</div>`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="search" class="w-3.5 h-3.5 inline-block mr-1"></i> Search';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

function quickRun(toolId) {
    const target = document.getElementById('global-target')?.value?.trim();
    if (!target) {
        showToast('Enter a target first', 'warning');
        document.getElementById('global-target')?.focus();
        return;
    }
    switchManualTab('execute');
    selectManualTool(toolId);
    setTimeout(() => {
        const targetInput = document.getElementById('arg-target');
        if (targetInput) targetInput.value = target;
        executeManualTool();
    }, 400);
}

// === Launch Metasploit from CVE ===
function launchMetasploit(modulePath, el) {
    const cveId = (typeof el === 'object' && el?.dataset?.cve) ? el.dataset.cve : (typeof el === 'string' ? el : '');
    switchManualTab('execute');
    selectManualTool('metasploit');
    setTimeout(() => {
        const target = document.getElementById('global-target')?.value || '';
        const targetInput = document.getElementById('arg-target');
        if (targetInput && target) targetInput.value = target;
        const moduleInput = document.getElementById('arg-module') || document.getElementById('arg-resource');
        if (moduleInput) moduleInput.value = modulePath;
    }, 400);
}
