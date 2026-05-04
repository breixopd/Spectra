function openAddTargetModal() {
    showSharedModal('add-target-modal');
}

function closeAddTargetModal() {
    closeSharedModal('add-target-modal');
}

function addTargetToGrid(target) {
    const grid = document.getElementById('targets-grid');
    const template = document.getElementById('target-card-template');
    const clone = template.content.cloneNode(true);
    const card = clone.querySelector('[data-target-card]');

    clone.querySelector('.target-name').textContent = target.address;
    clone.querySelector('.target-desc').textContent = target.description || 'No description';

    const sessionId = target.session_id || null;
    const shellBtn = clone.querySelector('.shell-btn');
    if (shellBtn) {
        shellBtn.onclick = () => openShell(shellBtn, sessionId);
        if (!sessionId) {
            shellBtn.classList.add('opacity-50', 'cursor-not-allowed');
            shellBtn.title = "No active shell session";
        }
    }

    if (card && document.getElementById('target-search')?.value) {
        const q = document.getElementById('target-search').value.toLowerCase();
        const text = `${target.address} ${target.description || ''}`.toLowerCase();
        if (!text.includes(q)) card.style.display = 'none';
    }

    grid.appendChild(clone);
}

function filterTargets(query) {
    const q = query.toLowerCase();
    document.querySelectorAll('[data-target-card]').forEach(card => {
        const text = card.textContent.toLowerCase();
        card.style.display = text.includes(q) ? '' : 'none';
    });
}

window.filterTargets = filterTargets;
window.openAddTargetModal = openAddTargetModal;
window.closeAddTargetModal = closeAddTargetModal;
window.handleAddTarget = handleAddTarget;

async function handleAddTarget(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    const data = Object.fromEntries(formData.entries());

    try {
        const { data: target, error } = await spectraApi.post('/api/v1/targets', {
            address: data.address,
            description: data.description,
            status: 'pending',
            os: 'Unknown'
        });

        if (!error) {
            addTargetToGrid({
                address: target.address,
                description: target.description,
                status: target.status,
                os: target.os,
                ports: 'None'
            });

            closeAddTargetModal();
            event.target.reset();
        } else {
            showToast(`Failed to add target: ${error}`, 'error');
        }
    } catch (error) {
        console.error('Error adding target:', error);
        showToast('Error adding target', 'error');
    }
}
