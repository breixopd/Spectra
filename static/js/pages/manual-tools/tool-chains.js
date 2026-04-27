function showNextToolSuggestions(toolId) {
    const suggestions = TOOL_CHAINS[toolId] || [];
    const panel = document.getElementById('next-tool-suggestions');
    const list = document.getElementById('suggestions-list');
    if (!suggestions.length) { panel.classList.add('hidden'); return; }

    const available = suggestions.filter(id => allTools.some(t => t.id === id));
    if (!available.length) { panel.classList.add('hidden'); return; }

    panel.classList.remove('hidden');
    list.innerHTML = available.map(id => {
        const tool = allTools.find(t => t.id === id);
        const name = tool ? tool.name : id;
        return `<button data-action="chainToTool" data-value="${id}" class="px-3 py-1.5 bg-slate-800 hover:bg-violet-500/10 border border-white/5 rounded-lg text-xs text-slate-300 transition-colors flex items-center gap-1.5">
            <i data-lucide="arrow-right" class="w-3.5 h-3.5 inline-block text-violet-400"></i> ${escapeHtml(name)}
        </button>`;
    }).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function chainToTool(toolId) {
    const smartTarget = buildSmartTarget(toolId, lastParsedFindings, lastToolOutput);
    selectManualTool(toolId);
    setTimeout(() => {
        const targetInput = document.getElementById('arg-target');
        if (targetInput && smartTarget) targetInput.value = smartTarget;
    }, 300);
}

function loadPipelineTemplate(templateId) {
    const globalTarget = document.getElementById('global-target')?.value || '';
    const templates = {
        recon: ['nmap', 'nikto', 'gobuster'],
        vuln: ['nmap', 'nuclei', 'searchsploit'],
        web: ['whatweb', 'nikto', 'sqlmap'],
    };
    const chain = templates[templateId];
    if (!chain) return;

    pipelineSteps = [];
    pipelineStepId = 0;
    const canvas = document.getElementById('pipeline-canvas');
    canvas.innerHTML = '';

    chain.forEach((toolId, i) => {
        addPipelineStep();
        const step = pipelineSteps[pipelineSteps.length - 1];
        const node = document.getElementById('pipeline-node-' + step.id);
        if (node) {
            node.querySelector('select').value = toolId;
            step.toolId = toolId;
            const targetInput = document.getElementById('pipeline-target-' + step.id);
            if (i === 0 && globalTarget && targetInput) {
                targetInput.value = globalTarget;
            }
        }
    });
}

document.getElementById('global-target')?.addEventListener('change', function() {
    const val = this.value;
    const firstTarget = document.getElementById('pipeline-target-1');
    if (firstTarget && !firstTarget.value) firstTarget.value = val;
});
