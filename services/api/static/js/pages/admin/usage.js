async function loadUsage() {
    try {
        const { data: d, error } = await spectraApi.get('/api/admin/usage');
        if (error) throw new Error(error);
        document.getElementById('usage-total-calls').textContent = d.total_calls.toLocaleString();
        document.getElementById('usage-total-tokens').textContent = d.total_tokens.toLocaleString();
        document.getElementById('usage-total-cost').textContent = '$' + d.total_cost_usd.toFixed(4);
        document.getElementById('usage-active-missions').textContent = d.active_missions;

        const tbody = document.getElementById('usage-tbody');
        if (!d.by_agent || !d.by_agent.length) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center py-8 text-slate-500">No LLM usage recorded yet</td></tr>';
        } else {
            tbody.innerHTML = d.by_agent.map(a => `
                <tr class="border-b border-white/5">
                    <td class="px-4 py-3 text-xs text-slate-400 font-mono">${escapeHtml(String(a.mission_id).substring(0, 8))}…</td>
                    <td class="px-4 py-3 text-sm text-white">${escapeHtml(a.agent_name)}</td>
                    <td class="px-4 py-3"><span class="badge bg-slate-700/50 text-slate-300">${escapeHtml(a.role)}</span></td>
                    <td class="px-4 py-3 text-right text-slate-300">${a.calls}</td>
                    <td class="px-4 py-3 text-right text-slate-300">${a.tokens.toLocaleString()}</td>
                    <td class="px-4 py-3 text-right text-amber-300">$${a.cost_usd.toFixed(4)}</td>
                    <td class="px-4 py-3 text-right text-slate-400">${a.avg_latency_ms.toFixed(0)} ms</td>
                    <td class="px-4 py-3 text-right ${a.errors > 0 ? 'text-red-400' : 'text-slate-500'}">${a.errors}</td>
                </tr>`).join('');
        }
    } catch(e) { console.error(e); _spectraToast('Error loading usage data', 'error'); }
}
