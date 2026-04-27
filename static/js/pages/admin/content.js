let currentContentType = 'review';

function switchContentType(type, el) {
    currentContentType = type;
    document.querySelectorAll('.content-type-btn').forEach(b => {
        b.classList.remove('active', 'bg-violet-600/20', 'text-violet-300', 'border-violet-500/30');
        b.classList.add('bg-white/5', 'text-slate-400', 'border-white/10');
    });
    if (el) {
        el.classList.add('active', 'bg-violet-600/20', 'text-violet-300', 'border-violet-500/30');
        el.classList.remove('bg-white/5', 'text-slate-400', 'border-white/10');
    }
    loadContent();
}

async function loadContent() {
    try {
        const { data: items, error } = await spectraApi.get(`/api/admin/content?content_type=${currentContentType}`);
        if (error) throw new Error(error);
        const list = document.getElementById('content-list');
        if (!items.length) { list.innerHTML = '<p class="text-sm text-slate-500">No items yet.</p>'; return; }
        list.innerHTML = items.map(item => `
            <div class="glass-panel rounded-lg p-4 flex justify-between items-start">
                <div>
                    <p class="text-sm font-medium text-white">${escapeHtml(item.title || item.content_type)}</p>
                    <p class="text-xs text-slate-500 mt-1">${escapeHtml(JSON.stringify(item.content).slice(0,100))}...</p>
                    <span class="text-xs ${item.is_active ? 'text-emerald-400' : 'text-slate-500'}">${item.is_active ? 'Active' : 'Inactive'}</span>
                </div>
                <div class="flex gap-2">
                    <button data-action="editContent" data-value="${item.id}" class="text-xs text-violet-400 hover:text-violet-300"><i data-lucide="edit" class="w-3.5 h-3.5 inline-block"></i></button>
                    <button data-action="deleteContent" data-value="${item.id}" class="text-xs text-red-400 hover:text-red-300"><i data-lucide="trash-2" class="w-3.5 h-3.5 inline-block"></i></button>
                </div>
            </div>
        `).join('');
    } catch(e) { console.error('Load content error', e); }
}

function openContentModal(existingData) {
    showModal('content-modal');
    document.getElementById('content-type-field').value = currentContentType;
    document.getElementById('review-fields').style.display = currentContentType === 'review' ? '' : 'none';
    document.getElementById('changelog-fields').style.display = currentContentType === 'changelog' ? '' : 'none';
    document.getElementById('legal-fields').style.display = currentContentType.startsWith('legal') ? '' : 'none';
    if (existingData) {
        document.getElementById('content-modal-title').textContent = 'Edit Content';
        document.getElementById('content-edit-id').value = existingData.id;
        document.getElementById('content-title').value = existingData.title || '';
        document.getElementById('content-active').checked = existingData.is_active;
        document.getElementById('content-sort').value = existingData.sort_order || 0;
        const c = existingData.content || {};
        if (currentContentType === 'review') {
            document.getElementById('content-quote').value = c.quote || '';
            document.getElementById('content-author').value = c.author_name || '';
            document.getElementById('content-role').value = c.author_role || '';
            document.getElementById('content-initials').value = c.initials || '';
        } else if (currentContentType === 'changelog') {
            document.getElementById('content-version').value = c.version || '';
            document.getElementById('content-changes').value = (c.changes || []).join('\n');
        } else {
            document.getElementById('content-html').value = c.html || '';
        }
    } else {
        document.getElementById('content-modal-title').textContent = 'Add Content';
    }
}

function closeContentModal() {
    closeModal('content-modal');
    document.getElementById('content-form').reset();
    document.getElementById('content-edit-id').value = '';
}

async function editContent(id) {
    const { data: items } = await spectraApi.get(`/api/admin/content?content_type=${currentContentType}`);
    const item = items.find(i => i.id === id);
    if (item) openContentModal(item);
}

async function deleteContent(id) {
    showConfirm('Delete Content', 'Delete this item?', async () => {
        await spectraApi.delete(`/api/admin/content/${id}`);
        loadContent();
        _spectraToast('Content deleted', 'success');
    });
}

document.getElementById('content-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const editId = document.getElementById('content-edit-id').value;
    let content = {};
    if (currentContentType === 'review') {
        content = {
            quote: document.getElementById('content-quote').value,
            author_name: document.getElementById('content-author').value,
            author_role: document.getElementById('content-role').value,
            initials: document.getElementById('content-initials').value,
        };
    } else if (currentContentType === 'changelog') {
        content = {
            version: document.getElementById('content-version').value,
            changes: document.getElementById('content-changes').value.split('\n').filter(Boolean),
        };
    } else {
        content = { html: document.getElementById('content-html').value };
    }
    const payload = {
        content_type: currentContentType,
        title: document.getElementById('content-title').value,
        content,
        is_active: document.getElementById('content-active').checked,
        sort_order: parseInt(document.getElementById('content-sort').value) || 0,
    };
    const url = editId ? `/api/admin/content/${editId}` : '/api/admin/content';
    const method = editId ? 'PUT' : 'POST';
    try {
        const r = editId ? await spectraApi.put(url, payload) : await spectraApi.post(url, payload);
        if (r.error) throw new Error(r.error);
        closeContentModal();
        loadContent();
        _spectraToast('Content saved', 'success');
    } catch(e) { _spectraToast(e.message, 'error'); }
});
