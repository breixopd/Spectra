// === Pipeline ===
function addPipelineStep() {
    document.getElementById('pipeline-empty')?.remove();
    const canvas = document.getElementById('pipeline-canvas');
    const stepNum = pipelineSteps.length;
    const id = ++pipelineStepId;

    if (stepNum > 0) {
        const conn = document.createElement('div');
        conn.className = 'pipeline-connector shrink-0';
        conn.innerHTML = '<i data-lucide="arrow-right" class="w-3.5 h-3.5 inline-block"></i>';
        canvas.appendChild(conn);
    }

    const node = document.createElement('div');
    node.className = 'pipeline-node shrink-0 animate-fade-in-up';
    node.id = 'pipeline-node-' + id;
    node.innerHTML = `
        <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-mono text-slate-500">Step ${stepNum + 1}</span>
            <button data-action="removePipelineStep" data-value="${id}" class="text-slate-600 hover:text-rose-400 text-xs transition-colors" aria-label="Remove step"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>
        <select data-on-change="updatePipelineStepFromEl" data-step-id="${id}" class="w-full px-2 py-1.5 bg-black/30 border border-white/10 rounded text-sm text-white mb-2 focus:outline-none focus:border-violet-500">
            <option value="">Select tool...</option>
            ${allTools.map(t => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)}</option>`).join('')}
        </select>
        <input type="text" placeholder="Target / Args" id="pipeline-target-${id}"
            class="w-full px-2 py-1.5 bg-black/30 border border-white/10 rounded text-xs text-white placeholder-slate-600 focus:outline-none focus:border-violet-500">
        <div class="text-xs text-slate-600 mt-1.5">Use <code class="text-violet-400">{prev}</code> for previous output</div>
    `;
    canvas.appendChild(node);
    pipelineSteps.push({id, toolId: '', target: ''});
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function removePipelineStep(id) {
    const idx = pipelineSteps.findIndex(s => s.id === id);
    if (idx === -1) return;
    pipelineSteps.splice(idx, 1);
    // Rebuild pipeline canvas
    rebuildPipelineCanvas();
}

function updatePipelineStepFromEl(el) {
    const id = parseInt(el.dataset.stepId, 10);
    updatePipelineStep(id, el.value);
}
function updatePipelineStep(id, toolId) {
    const step = pipelineSteps.find(s => s.id === id);
    if (step) step.toolId = toolId;
}

function rebuildPipelineCanvas() {
    const canvas = document.getElementById('pipeline-canvas');
    canvas.innerHTML = '';
    if (pipelineSteps.length === 0) {
        canvas.innerHTML = '<div class="empty-state" id="pipeline-empty"><i data-lucide="git-branch" class="w-5 h-5 inline-block text-violet-400/40"></i><h3>Build your pipeline</h3><p>Click "Add Step" to chain tools together.</p></div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }
    const saved = [...pipelineSteps];
    pipelineSteps = [];
    pipelineStepId = 0;
    saved.forEach(s => {
        addPipelineStep();
        const last = pipelineSteps[pipelineSteps.length - 1];
        const node = document.getElementById('pipeline-node-' + last.id);
        if (node && s.toolId) {
            node.querySelector('select').value = s.toolId;
            last.toolId = s.toolId;
        }
    });
}

async function runPipeline() {
    const output = document.getElementById('pipeline-output');
    const btn = document.getElementById('pipeline-run-btn');

    if (pipelineSteps.length === 0) { showToast('Add at least one step', 'warning'); return; }

    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin mr-1"></i> Running...';
    output.innerHTML = '';

    let previousOutput = '';
    let previousFindings = [];

    for (let i = 0; i < pipelineSteps.length; i++) {
        const step = pipelineSteps[i];
        if (!step.toolId) {
            output.innerHTML += `<span class="text-amber-400">Step ${i+1}: No tool selected, skipping\n</span>`;
            continue;
        }

        const node = document.getElementById('pipeline-node-' + step.id);
        node?.classList.add('active');
        let target = document.getElementById('pipeline-target-' + step.id)?.value || '';

        if (target.includes('{prev}') && previousOutput) {
            target = target.replace('{prev}', previousOutput.trim().split('\n')[0]);
        } else if (!target && i > 0) {
            target = buildSmartTarget(step.toolId, previousFindings, previousOutput);
        }

        if (!target) {
            output.innerHTML += `<span class="text-amber-400">Step ${i+1} (${escapeHtml(step.toolId)}): No target, skipping\n</span>`;
            node?.classList.remove('active');
            continue;
        }

        output.innerHTML += `<span class="text-violet-400">━━━ Step ${i+1}: ${escapeHtml(step.toolId)} → ${escapeHtml(target)} ━━━</span>\n`;
        output.innerHTML += `<span class="text-slate-500">Executing...</span>\n`;
        output.scrollTop = output.scrollHeight;

        try {
            const res = await spectraApi.post(`/api/v1/tools/${step.toolId}/test`, {target, args: {}, timeout: 300});
            const result = res.data;
            const statusIcon = result.success ? '<span class="text-emerald-400">✓</span>' : '<span class="text-rose-400">✗</span>';
            output.innerHTML += `${statusIcon} Exit: ${result.exit_code} | Duration: ${result.duration_seconds?.toFixed(1) || 0}s | Findings: ${result.parsed_findings_count || 0}\n`;

            if (result.stdout) {
                const preview = result.stdout.slice(0, 1500);
                output.innerHTML += escapeHtml(preview) + (result.stdout.length > 1500 ? '\n...(truncated)' : '') + '\n';
                previousOutput = result.stdout;
                previousFindings = result.parsed_findings || [];
            }
            if (result.stderr) {
                output.innerHTML += `<span class="text-amber-500/60">${escapeHtml(result.stderr.slice(0, 500))}</span>\n`;
            }
        } catch (e) {
            output.innerHTML += `<span class="text-rose-400">Error: ${escapeHtml(e.message)}</span>\n`;
        }

        node?.classList.remove('active');
        output.innerHTML += '\n';
        output.scrollTop = output.scrollHeight;
    }

    output.innerHTML += `<span class="text-emerald-400">━━━ Pipeline complete ━━━</span>\n`;
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="play" class="w-4 h-4 inline-block mr-1"></i> Run Pipeline';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Smart pipeline data passing: extract the right input for the next tool from previous findings
function buildSmartTarget(nextToolId, findings, rawOutput) {
    const globalTarget = document.getElementById('global-target')?.value || '';

    if (!findings.length) {
        return rawOutput ? rawOutput.trim().split('\n')[0] : globalTarget;
    }

    // searchsploit needs "product version" queries
    if (nextToolId === 'searchsploit') {
        const queries = findings
            .filter(f => f.product || f.service)
            .map(f => [f.product, f.version].filter(Boolean).join(' '))
            .filter(Boolean);
        return queries[0] || globalTarget;
    }

    // nuclei/nikto/gobuster/ffuf/dirsearch need URLs
    if (['nuclei', 'nikto', 'gobuster', 'ffuf', 'dirsearch', 'feroxbuster'].includes(nextToolId)) {
        const urls = findings
            .filter(f => f.portid || f.port)
            .map(f => {
                const host = f.ip || f.host || globalTarget;
                const port = f.portid || f.port;
                const svc = (f.service || '').toLowerCase();
                const proto = (svc.includes('ssl') || svc.includes('https') || port == 443) ? 'https' : 'http';
                return `${proto}://${host}:${port}`;
            });
        return urls[0] || globalTarget;
    }

    // sqlmap needs a URL
    if (nextToolId === 'sqlmap') {
        const webFindings = findings.filter(f => {
            const port = f.portid || f.port;
            const svc = (f.service || '').toLowerCase();
            return svc.includes('http') || port == 80 || port == 443 || port == 8080;
        });
        if (webFindings.length) {
            const f = webFindings[0];
            const host = f.ip || f.host || globalTarget;
            const port = f.portid || f.port;
            return `http://${host}:${port}/`;
        }
        return globalTarget;
    }

    // hydra needs host
    if (nextToolId === 'hydra') {
        const sshFindings = findings.filter(f => (f.service || '').toLowerCase().includes('ssh'));
        if (sshFindings.length) {
            return sshFindings[0].ip || sshFindings[0].host || globalTarget;
        }
        return globalTarget;
    }

    // Default: use first finding's host or global target
    const first = findings[0];
    return first?.ip || first?.host || first?.['matched-at'] || globalTarget;
}
