async function loadTools() {
    try {
        const { data, error } = await spectraApi.get('/api/v1/tools');
        allTools = data?.tools || data || [];
        renderToolPicker(allTools);
    } catch (e) {
        document.getElementById('tool-picker').innerHTML = '<div class="text-red-400 text-sm p-2">Failed to load tools</div>';
    }
}

function filterTools() {
    const q = document.getElementById('tool-search').value.toLowerCase();
    const filtered = allTools.filter(t =>
        t.name.toLowerCase().includes(q) || t.id.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q) || (t.category || '').toLowerCase().includes(q)
    );
    renderToolPicker(filtered);
}

function renderToolPicker(tools) {
    const container = document.getElementById('tool-picker');
    if (!tools.length) {
        container.innerHTML = '<div class="empty-state py-6"><i data-lucide="search" class="w-6 h-6 inline-block text-slate-600"></i><p class="text-slate-500 text-xs mt-2">No tools found</p></div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }
    container.innerHTML = tools.map(t => {
        const statusDot = t.status === 'ready' ? 'bg-emerald-500' : t.status === 'installing' ? 'bg-blue-400 animate-pulse' : 'bg-amber-500';
        const sel = selectedToolId === t.id ? 'selected' : '';
        return `<div class="tool-card rounded-lg p-3 cursor-pointer glass-panel ${sel}" data-action="selectManualTool" data-value="${escapeHtml(t.id)}">
            <div class="flex items-center gap-2.5">
                <div class="w-2 h-2 rounded-full ${statusDot} shrink-0"></div>
                <div class="min-w-0">
                    <div class="text-sm font-medium text-white truncate">${escapeHtml(t.name)}</div>
                    <div class="text-xs text-slate-500 truncate">${escapeHtml(t.category)} · ${escapeHtml(t.description.slice(0, 40))}...</div>
                </div>
            </div>
        </div>`;
    }).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}
