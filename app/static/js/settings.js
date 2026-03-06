// Settings Logic

// Smooth scrolling for sidebar links
document.querySelectorAll('nav a').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const targetId = this.getAttribute('href').substring(1);
        // In a real app with sections, we'd scroll to the element
        console.log('Navigating to:', targetId);
        
        // Update active state
        document.querySelectorAll('nav a').forEach(a => {
            a.classList.remove('bg-white/5', 'text-white');
            a.classList.add('text-slate-400');
        });
        this.classList.remove('text-slate-400');
        this.classList.add('bg-white/5', 'text-white');
    });
});

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    
    const form = document.getElementById('settings-form');
    if (form) {
        form.addEventListener('submit', saveSettings);
    }

    const testApiBtn = document.getElementById('test-api-btn');
    if (testApiBtn) {
        testApiBtn.addEventListener('click', () => testConnection('api'));
    }

    const testOllamaBtn = document.getElementById('test-ollama-btn');
    if (testOllamaBtn) {
        testOllamaBtn.addEventListener('click', () => testConnection('ollama'));
    }
});

async function testConnection(provider) {
    const form = document.getElementById('settings-form');
    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());

    const payload = {
        provider: provider,
        api_key: data.llm_api_key,
        base_url: data.llm_api_base_url,
        model: provider === 'api' ? data.llm_model : data.ollama_model,
        host: data.ollama_host
    };

    const btnId = provider === 'api' ? 'test-api-btn' : 'test-ollama-btn';
    const btn = document.getElementById(btnId);
    const originalText = btn.innerText;
    btn.innerText = 'Testing...';
    btn.disabled = true;

    try {
        const response = await fetch('/test-llm', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
        });

        const result = await response.json();

        if (result.success) {
            alert('Success! LLM connection is working.');
        } else {
            alert(`Failed: ${result.error || 'Unknown error'}`);
        }
    } catch (error) {
        console.error('Test failed:', error);
        alert('Test failed due to network error.');
    } finally {
        btn.innerText = originalText;
        btn.disabled = false;
    }
}

async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const data = await response.json();
        
        // Populate form fields if they exist
        setFieldValue('ai_provider', data.ai_provider);
        setFieldValue('llm_model', data.llm_model);
        setFieldValue('llm_api_base_url', data.llm_api_base_url);
        setFieldValue('ollama_host', data.ollama_host);
        setFieldValue('ollama_model', data.ollama_model);
        setFieldValue('log_level', data.log_level);
        setCheckboxValue('plugin_safe_mode', data.plugin_safe_mode);
        setFieldValue('connect_back_host', data.connect_back_host);
        setFieldValue('tool_container_name', data.tool_container_name);
        setCheckboxValue('require_approval', data.require_approval);
        
    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

async function saveSettings(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const data = Object.fromEntries(formData.entries());
    
    // Handle checkbox manually as unchecked boxes aren't in FormData
    data.plugin_safe_mode = e.target.querySelector('[name="plugin_safe_mode"]').checked;
    data.require_approval = e.target.querySelector('[name="require_approval"]').checked;
    
    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data),
        });
        
        if (response.ok) {
            alert('Settings saved successfully!');
        } else {
            alert('Failed to save settings.');
        }
    } catch (error) {
        console.error('Error saving settings:', error);
        alert('Error saving settings.');
    }
}

function setFieldValue(name, value) {
    const field = document.querySelector(`[name="${name}"]`);
    if (field) {
        field.value = value || '';
    }
}

function setCheckboxValue(name, value) {
    const field = document.querySelector(`[name="${name}"]`);
    if (field) {
        field.checked = !!value;
    }
}

function checkSystemStatus() {
    console.log('Checking system status...');
}

// Provider preset quick-setup buttons
async function applyPreset(presetId) {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        const presets = data.provider_presets || {};
        const preset = presets[presetId];

        if (!preset) {
            alert('Preset not found: ' + presetId);
            return;
        }

        setFieldValue('llm_api_base_url', preset.base_url || '');
        setFieldValue('llm_model', preset.default_model || '');

        // Visual feedback
        const btn = event.target.closest('button');
        if (btn) {
            const orig = btn.innerHTML;
            btn.innerHTML = '<span class="text-emerald-400"><i class="fa-solid fa-check"></i> Applied</span>';
            setTimeout(() => { btn.innerHTML = orig; }, 1500);
        }
    } catch (e) {
        console.error('Failed to apply preset:', e);
    }
}
