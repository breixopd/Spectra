async function executeManualTool() {
    if (!selectedToolConfig) return;
    const target = document.getElementById('arg-target')?.value;
    if (!target) { showToast('Target is required', 'warning'); return; }

    const args = {};
    const schemaFields = getSchemaFields(selectedToolConfig.args_schema).filter(field => field.name !== 'target' && field.name !== 'output_file');
    if (schemaFields.length) {
        schemaFields.forEach(({ name, spec }) => {
            const input = document.getElementById('arg-' + name);
            if (!input) return;
            let val;
            if (spec.type === 'boolean') {
                val = input.checked;
                if (val || spec.default) args[name] = val;
                return;
            }
            val = input.value;
            if (val === '' || val === undefined || val === null) return;
            if (spec.type === 'integer') args[name] = parseInt(val, 10);
            else if (spec.type === 'number') args[name] = parseFloat(val);
            else if (spec.type === 'array') args[name] = String(val).split(',').map(v => v.trim()).filter(Boolean);
            else args[name] = val;
        });
    } else {
        (selectedToolConfig.placeholders || []).forEach(p => {
            if (p === 'target') return;
            const val = document.getElementById('arg-' + p)?.value;
            if (val) args[p] = val;
        });
    }
    const timeout = parseInt(document.getElementById('arg-timeout')?.value) || 300;

    const btn = document.getElementById('run-btn');
    const status = document.getElementById('exec-status');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin"></i> Running...';
    if (typeof lucide !== 'undefined') lucide.createIcons();
    status.textContent = 'Executing...';

    const outputArea = document.getElementById('output-area');
    outputArea.innerHTML = `<span class="text-violet-400">$ ${escapeHtml(selectedToolConfig.command)} ... ${escapeHtml(target)}</span>\n<span class="text-slate-500">Waiting for results...</span>\n`;
    document.getElementById('output-tool-label').textContent = selectedToolConfig.name;
    document.getElementById('output-duration').textContent = '';
    document.getElementById('findings-panel').classList.add('hidden');
    document.getElementById('output-findings-count').classList.add('hidden');

    const startTime = Date.now();
    const timer = setInterval(() => {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
        status.textContent = `Running... ${elapsed}s`;
    }, 1000);

    try {
        const res = await spectraApi.post(`/api/v1/tools/${selectedToolConfig.id}/test`, {target, args, timeout});
        const result = res.data;
        clearInterval(timer);

        const dur = result.duration_seconds?.toFixed(1) || '0';
        document.getElementById('output-duration').textContent = `${dur}s`;
        status.textContent = result.success ? 'Completed' : 'Failed';
        status.className = 'text-xs ml-auto font-mono ' + (result.success ? 'text-emerald-400' : 'text-rose-400');

        let out = `<span class="text-violet-400">$ ${escapeHtml(selectedToolConfig.command)} ${escapeHtml(selectedToolConfig.args_template)}</span>\n`;
        out += `<span class="text-slate-500">Target: ${escapeHtml(target)} | Exit: ${result.exit_code} | Duration: ${dur}s</span>\n\n`;

        if (result.stdout) {
            out += colorizeOutput(escapeHtml(result.stdout));
        }
        if (result.stderr) {
            out += `\n<span class="text-amber-500/70">${escapeHtml(result.stderr)}</span>`;
        }
        if (!result.stdout && !result.stderr) {
            out += '<span class="text-slate-500">(no output)</span>';
        }
        outputArea.innerHTML = out;

        if (result.parsed_findings?.length > 0) {
            document.getElementById('findings-panel').classList.remove('hidden');
            document.getElementById('output-findings-count').classList.remove('hidden');
            document.getElementById('output-findings-count').textContent = `${result.parsed_findings_count} findings`;
            renderFindings(result.parsed_findings);
        }

        lastToolOutput = result.stdout || '';
        addToHistory({
            time: new Date(), tool: selectedToolConfig.name, toolId: selectedToolConfig.id,
            target, status: result.success, duration: result.duration_seconds || 0,
            output: result.stdout || '', stderr: result.stderr || '', args
        });
        logToSession(
            `Ran ${selectedToolConfig.name} against ${target}`,
            selectedToolConfig.id,
            result.parsed_findings || []
        );
        showNextToolSuggestions(selectedToolConfig.id);
    } catch (e) {
        clearInterval(timer);
        outputArea.innerHTML += `\n<span class="text-red-400">Error: ${escapeHtml(e.message)}</span>`;
        status.textContent = 'Error';
        status.className = 'text-xs ml-auto font-mono text-rose-400';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="play" class="w-4 h-4 inline-block"></i> Run';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

function clearOutput() {
    document.getElementById('output-area').innerHTML = '<span class="text-slate-500">Select a tool and click Run to see output here.</span>';
    document.getElementById('findings-panel').classList.add('hidden');
    document.getElementById('output-findings-count').classList.add('hidden');
    document.getElementById('output-duration').textContent = '';
    document.getElementById('exec-status').textContent = '';
    document.getElementById('exec-status').className = 'text-xs text-slate-500 ml-auto font-mono';
}
