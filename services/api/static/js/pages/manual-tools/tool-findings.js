function renderFindings(findings) {
    lastParsedFindings = findings;
    findings.forEach(f => {
        f._source = selectedToolConfig?.id || 'unknown';
        if (!allFindings.some(e => findingKey(e) === findingKey(f))) allFindings.push(f);
    });
    updateFindingsCount();

    const list = document.getElementById('findings-list');
    list.innerHTML = findings.slice(0, 30).map((f, i) => {
        const sev = f.severity || f.state || 'info';
        const title = f.name || f.service || f.title || f.template_id || `Finding ${i+1}`;
        const detail = f.port ? `Port ${f.port}` : f.host || f.url || '';
        const product = [f.product, f.version].filter(Boolean).join(' ');
        const sevColor = {critical:'text-rose-400',high:'text-amber-400',medium:'text-blue-400',low:'text-slate-400',open:'text-emerald-400',info:'text-slate-500'}[sev.toLowerCase()] || 'text-slate-400';

        let actions = '';
        if (product) {
            actions += `<button data-action="lookupCVEsFor" data-value="${escapeAttr(product)}" class="px-1.5 py-0.5 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 rounded text-xs transition-colors" title="Search CVEs for ${escapeAttr(product)}"><i data-lucide="shield-alert" class="w-3.5 h-3.5 inline-block"></i></button>`;
            actions += `<button data-action="runToolOn" data-value="searchsploit" data-tool-target="${escapeAttr(product)}" class="px-1.5 py-0.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 rounded text-xs transition-colors" title="SearchSploit"><i data-lucide="search" class="w-3.5 h-3.5 inline-block"></i></button>`;
        }
        if (f.port || f.portid) {
            const host = f.ip || f.host || document.getElementById('global-target')?.value || '';
            const port = f.portid || f.port;
            const svc = (f.service || '').toLowerCase();
            const proto = (svc.includes('ssl') || svc.includes('https') || port == 443) ? 'https' : 'http';
            const url = `${proto}://${host}:${port}`;
            actions += `<button data-action="runToolOn" data-value="nuclei" data-tool-target="${escapeAttr(url)}" class="px-1.5 py-0.5 bg-violet-500/10 hover:bg-violet-500/20 text-violet-400 rounded text-xs transition-colors" title="Scan with Nuclei"><i data-lucide="bug" class="w-3.5 h-3.5 inline-block"></i></button>`;
            if (svc.includes('http')) {
                actions += `<button data-action="runToolOn" data-value="nikto" data-tool-target="${escapeAttr(url)}" class="px-1.5 py-0.5 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 rounded text-xs transition-colors" title="Scan with Nikto"><i data-lucide="globe" class="w-3.5 h-3.5 inline-block"></i></button>`;
            }
        }

        return `<div class="flex items-center gap-2 text-xs p-2 rounded bg-white/[0.02] hover:bg-white/[0.04] group">
            <span class="font-mono ${sevColor} uppercase w-14 text-xs shrink-0">${sev}</span>
            <span class="text-white truncate flex-1">${escapeHtml(title)}</span>
            <span class="text-slate-500 shrink-0 text-xs">${escapeHtml(detail)}</span>
            <div class="flex gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">${actions}</div>
        </div>`;
    }).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function findingKey(f) {
    return [f.name||f.service||'', f.host||f.ip||'', f.port||f.portid||'', f.severity||''].join('|');
}

function updateFindingsCount() {
    const badge = document.getElementById('all-findings-count');
    if (badge) badge.textContent = allFindings.length;
}

function lookupCVEsFor(product) {
    switchManualTab('cve');
    const parts = product.split(' ');
    document.getElementById('cve-product').value = parts[0] || '';
    document.getElementById('cve-version').value = parts.slice(1).join(' ') || '';
    searchCVEs();
}

function runToolOn(toolId, el) {
    const target = (typeof el === 'object' && el?.dataset?.toolTarget) ? el.dataset.toolTarget : (typeof el === 'string' ? el : '');
    selectManualTool(toolId);
    setTimeout(() => {
        const targetInput = document.getElementById('arg-target');
        if (targetInput) targetInput.value = target;
    }, 300);
}
