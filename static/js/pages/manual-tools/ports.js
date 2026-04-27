// === Port Reference ===
let activePortCategory = 'all';

function initPorts() {
    const filterContainer = document.getElementById('port-cat-filters');
    filterContainer.innerHTML = PORT_CATEGORIES.map(c =>
        `<button data-action="filterPortCat" data-value="${c.id}" class="port-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${
            c.id === 'all' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-emerald-500/10 border border-white/5'
        }" data-cat="${c.id}">${c.label}</button>`
    ).join('');
    renderPorts(PORT_REFERENCE);
}

function filterPortCat(cat) {
    activePortCategory = cat;
    document.querySelectorAll('.port-cat-btn').forEach(b => {
        const isActive = b.dataset.cat === cat;
        b.className = `port-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${isActive ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-emerald-500/10 border border-white/5'}`;
    });
    filterPorts();
}

function renderPorts(ports) {
    document.getElementById('port-count').textContent = ports.length + ' ports';
    document.getElementById('port-list').innerHTML = ports.map(p => {
        const vulnClass = p.common_vulns.includes('RCE') || p.common_vulns.includes('CVE') ? 'text-rose-400' : 'text-amber-400/80';
        const toolLinks = p.tools.split(', ').map(t => `<span class="text-violet-400 hover:text-violet-300 cursor-pointer" data-action="jumpToTool" data-value="${escapeAttr(t.trim())}">${escapeHtml(t.trim())}</span>`).join(', ');
        return `<tr class="border-b border-white/[0.03] hover:bg-white/[0.03]">
            <td class="px-2 py-1.5 text-violet-400 font-bold">${p.port}</td>
            <td class="px-2 py-1.5 text-emerald-400">${escapeHtml(p.service)}</td>
            <td class="px-2 py-1.5 text-slate-500">${p.protocol}</td>
            <td class="px-2 py-1.5 text-slate-400">${escapeHtml(p.default_creds)}</td>
            <td class="px-2 py-1.5 ${vulnClass}">${escapeHtml(p.common_vulns)}</td>
            <td class="px-2 py-1.5">${toolLinks}</td>
        </tr>`;
    }).join('');
}

function filterPorts() {
    const q = document.getElementById('port-search')?.value?.toLowerCase() || '';
    let ports = PORT_REFERENCE;
    if (activePortCategory !== 'all') ports = ports.filter(p => p.category === activePortCategory);
    if (q) {
        ports = ports.filter(p =>
            p.port.toString().includes(q) || p.service.toLowerCase().includes(q) ||
            p.common_vulns.toLowerCase().includes(q) || p.tools.toLowerCase().includes(q) ||
            p.default_creds.toLowerCase().includes(q) || p.protocol.toLowerCase().includes(q)
        );
    }
    renderPorts(ports);
}

function jumpToTool(toolName) {
    switchManualTab('execute');
    const searchInput = document.getElementById('tool-search');
    if (searchInput) { searchInput.value = toolName; filterTools(); }
    const match = allTools.find(t => t.name.toLowerCase() === toolName.toLowerCase() || t.id.toLowerCase() === toolName.toLowerCase());
    if (match) setTimeout(() => selectManualTool(match.id), 200);
}
