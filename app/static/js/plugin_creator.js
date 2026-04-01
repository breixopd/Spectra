/**
 * Plugin Creator Logic
 * Handles form processing, preview generation, validation, and submission.
 */

function renderActionStatus(container, message, tone = 'info') {
    if (!container) return;
    const color = {
        info: 'text-slate-300',
        success: 'text-green-400',
        error: 'text-red-400',
    }[tone] || 'text-slate-300';
    container.classList.remove('hidden');
    container.textContent = '';
    const span = document.createElement('span');
    span.className = color;
    span.textContent = String(message || 'Unknown status');
    container.appendChild(span);
}

function addInstallCmd() {
    const container = document.getElementById('install-cmds-container');
    const div = document.createElement('div');
    div.className = 'flex gap-2';
    div.innerHTML = `
        <input type="text" class="install-cmd w-full bg-slate-900/50 border border-white/10 rounded-lg px-3 py-2 text-white focus:border-blue-500 focus:outline-none font-mono text-sm" placeholder="Command">
        <button onclick="this.parentElement.remove()" class="px-3 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400"><i data-lucide="trash-2" class="w-4 h-4 inline-block"></i></button>
    `;
    container.appendChild(div);
}

function buildConfig() {
    const cmds = Array.from(document.querySelectorAll('.install-cmd')).map(i => i.value).filter(v => v);
    
    return {
        id: document.getElementById('tool-id').value,
        name: document.getElementById('tool-name').value,
        version: document.getElementById('tool-version').value,
        description: document.getElementById('tool-desc').value,
        category: document.getElementById('tool-category').value,
        execution: {
            command: document.getElementById('exec-command').value,
            args_template: document.getElementById('exec-args').value,
            timeout: parseInt(document.getElementById('exec-timeout').value) || 300
        },
        installation: {
            method: document.getElementById('install-method').value,
            commands: cmds,
            verification_command: document.getElementById('verify-cmd').value || null
        },
        metadata: {
            risk_level: document.getElementById('meta-risk').value,
            capabilities: [],
            ai_description: document.getElementById('tool-desc').value
        },
        ui: {
            icon: document.getElementById('ui-icon').value,
            color: document.getElementById('ui-color').value
        }
    };
}

function updatePreview() {
    const config = buildConfig();
    document.getElementById('json-preview').value = JSON.stringify(config, null, 2);
}

function loadExample() {
    document.getElementById('tool-id').value = 'example-tool';
    document.getElementById('tool-name').value = 'Example Tool';
    document.getElementById('tool-version').value = '1.0.0';
    document.getElementById('tool-desc').value = 'An example security tool plugin.';
    document.getElementById('tool-author').value = 'Spectra Team';
    document.getElementById('exec-command').value = 'echo';
    document.getElementById('exec-args').value = '"Hello {target}"';
    document.getElementById('ui-icon').value = 'terminal';
    updatePreview();
}

async function validatePlugin() {
    const status = document.getElementById('action-status');
    status.classList.remove('hidden');
    status.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin"></i> Validating...';
    
    try {
        const config = buildConfig();
        const { error } = await spectraApi.post('/api/v1/tools/validate', config);
        if (error) throw new Error(error);
        
        renderActionStatus(status, 'Validation passed!', 'success');
    } catch (e) {
        renderActionStatus(status, e.message || 'Operation failed', 'error');
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function getPrivateKeyPem() {
    const useCustom = document.getElementById('sign-custom')?.checked;
    if (!useCustom) return null;

    const fileInput = document.getElementById('private-key-file');
    if (!fileInput || !fileInput.files[0]) {
        throw new Error('Please select a private key file');
    }

    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error('Failed to read key file'));
        reader.readAsText(fileInput.files[0]);
    });
}

async function signAndSave() {
    const status = document.getElementById('action-status');
    status.classList.remove('hidden');
    status.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin"></i> Signing & Saving...';
    
    try {
        const config = buildConfig();
        
        // Get custom key if selected
        let privateKeyPem = null;
        try {
            privateKeyPem = await getPrivateKeyPem();
        } catch (e) {
            renderActionStatus(status, e.message || 'Failed to read key file', 'error');
            return;
        }

        // 1. Sign
        const signBody = { config };
        if (privateKeyPem) {
            signBody.private_key_pem = privateKeyPem;
        }

        const { data: signedConfig, error: signError } = await spectraApi.post('/api/v1/tools/sign', signBody);
        if (signError) {
            throw new Error(signError);
        }
        
        // 2. Save (Upload)
        const blob = new Blob([JSON.stringify(signedConfig)], { type: 'application/json' });
        const formData = new FormData();
        formData.append('file', blob, `${config.id}.json`);
        
        const { error: uploadError } = await spectraApi.request('/api/v1/tools/upload', {
            method: 'POST',
            body: formData
        });
        if (uploadError) throw new Error(uploadError);
        
        renderActionStatus(status, 'Plugin signed and saved. Redirecting...', 'success');

        setTimeout(() => {
            window.location.href = '/toolbox';
        }, 1500);

    } catch (e) {
        renderActionStatus(status, e.message || 'Operation failed', 'error');
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function saveWithoutSigning() {
    const status = document.getElementById('action-status');
    status.classList.remove('hidden');
    status.innerHTML = '<i data-lucide="loader" class="w-4 h-4 inline-block animate-spin"></i> Saving (unsigned)...';

    try {
        const config = buildConfig();

        const { error } = await spectraApi.post('/api/v1/tools/save-unsigned', config);
        if (error) throw new Error(error);

        renderActionStatus(status, 'Plugin saved without signing. Redirecting...', 'success');
        
        setTimeout(() => {
            window.location.href = '/toolbox';
        }, 1500);
        
    } catch (e) {
        renderActionStatus(status, e.message || 'Operation failed', 'error');
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Auto-update preview on change
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('input, select, textarea').forEach(el => {
        el.addEventListener('input', updatePreview);
    });
    
    // Initial preview
    updatePreview();
});
