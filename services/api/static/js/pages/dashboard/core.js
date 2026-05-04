const terminalOutput = document.getElementById('terminal-output');

function addTerminalLine(text, type = 'info') {
    const line = document.createElement('p');
    const colorClass = {
        'info': 'text-slate-500',
        'success': 'text-emerald-400',
        'warning': 'text-amber-400',
        'error': 'text-rose-400',
        'command': 'text-white'
    }[type] || 'text-slate-300';
    
    line.className = colorClass;
    line.textContent = text;
    terminalOutput.insertBefore(line, terminalOutput.lastElementChild);
    terminalOutput.scrollTop = terminalOutput.scrollHeight;
}

window.addTerminalLine = addTerminalLine;
