// Dashboard Tasks — task tree, playbook detail
// Loaded before dashboard.js; depends on escapeHtml(), spectraApi
// Runtime deps (exposed by dashboard.js module): addTerminalLine, showSharedModal, closeSharedModal, startMission

var selectedPlaybookData = null;

function updateTaskList(data) {
    // Currently no dedicated task list UI, logging to terminal
    if (data && data.tasks) {
        const active = data.tasks.filter(t => t.status === 'running').length;
        const completed = data.tasks.filter(t => t.status === 'completed').length;
        const total = data.tasks.length;
        addTerminalLine(`[TASKS] Progress: ${completed}/${total} (${active} active)`, 'info');
    }
}

function renderTaskTree(tasks) {
    const panel = document.getElementById('task-tree-panel');
    const content = document.getElementById('task-tree-content');
    if (!tasks || tasks.length === 0) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');

    const icons = { completed: '☑', running: '●', pending: '○', failed: '✗' };
    const colors = { completed: 'text-emerald-400', running: 'text-amber-400 animate-pulse', pending: 'text-slate-500', failed: 'text-rose-400' };

    function renderNode(task, depth) {
        depth = depth || 0;
        const indent = depth * 20;
        const icon = icons[task.status] || '○';
        const color = colors[task.status] || 'text-slate-500';
        const taskId = task.id || Math.random().toString(36).slice(2);
        if (!window._taskTreeData) window._taskTreeData = {};
        window._taskTreeData[taskId] = task;
        let html = `<div class="flex items-center gap-2 py-0.5 hover:bg-white/5 rounded px-2 cursor-pointer" style="padding-left:${indent + 8}px" data-task-id="${escapeHtml(String(taskId))}">
            <span class="${color}">${icon}</span>
            <span class="text-slate-300">${escapeHtml(task.name || task.tool || 'Task')}</span>
            ${task.status === 'running' ? '<span class="text-xs text-amber-400 ml-auto">running...</span>' : ''}
        </div>`;
        if (task.children) task.children.forEach(c => { html += renderNode(c, depth + 1); });
        return html;
    }

    content.innerHTML = tasks.map(t => renderNode(t)).join('');
    const running = tasks.filter(t => t.status === 'running').length;
    const completed = tasks.filter(t => t.status === 'completed').length;
    document.getElementById('task-tree-status').textContent = `${completed}/${tasks.length} complete, ${running} active`;
}

// --- Playbook Detail Modal ---

function showPlaybookDetail(playbook) {
    selectedPlaybookData = playbook;
    document.getElementById('pb-detail-title').textContent = playbook.name || 'Playbook';
    document.getElementById('pb-detail-desc').textContent = playbook.description || '';
    const phasesEl = document.getElementById('pb-detail-phases');
    const steps = playbook.steps || playbook.phases || [];
    phasesEl.innerHTML = steps.map((s, i) => `<div class="flex items-center gap-2 text-xs"><span class="w-5 h-5 rounded-full bg-violet-500/20 text-violet-400 flex items-center justify-center text-xs font-mono shrink-0">${i + 1}</span><span class="text-slate-300">${escapeHtml(typeof s === 'string' ? s : s.name || s.description || JSON.stringify(s))}</span></div>`).join('');
    document.getElementById('pb-detail-stealth').textContent = playbook.stealth ? 'On' : 'Off';
    document.getElementById('pb-detail-autoexploit').textContent = playbook.auto_exploit !== false ? 'Yes' : 'No';
    showSharedModal('playbook-detail-modal');
}
function closePlaybookDetail() { closeSharedModal('playbook-detail-modal'); }
function launchPlaybook() {
    if (!selectedPlaybookData) return;
    const target = document.getElementById('mission-target')?.value?.trim();
    if (!target) { closePlaybookDetail(); document.getElementById('mission-target')?.focus(); return; }
    closePlaybookDetail();
    startMission(target, selectedPlaybookData.description || 'Playbook execution', selectedPlaybookData.id);
}
