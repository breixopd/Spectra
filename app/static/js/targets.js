// Targets Management Logic

function openAddTargetModal() {
    document.getElementById('add-target-modal').classList.remove('hidden');
}

function closeAddTargetModal() {
    document.getElementById('add-target-modal').classList.add('hidden');
}

async function handleAddTarget(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    const data = Object.fromEntries(formData.entries());
    
    try {
        const response = await fetch('/api/targets', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                address: data.address,
                description: data.description,
                status: 'pending',
                os: 'Unknown'
            }),
        });
        
        if (response.ok) {
            const target = await response.json();
            console.log('Target added:', target);
            
            // Add to grid
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
            const error = await response.json();
            alert(`Failed to add target: ${error.detail}`);
        }
    } catch (error) {
        console.error('Error adding target:', error);
        alert('Error adding target');
    }
}

function addTargetToGrid(target) {
    const grid = document.getElementById('targets-grid');
    const template = document.getElementById('target-card-template');
    const clone = template.content.cloneNode(true);
    
    clone.querySelector('.target-name').textContent = target.address;
    clone.querySelector('.target-desc').textContent = target.description || 'No description';
    
    grid.appendChild(clone);
}

// --- Shell Handler ---

function openShell(btn) {
    document.getElementById('shell-modal').classList.remove('hidden');
    // In a real app, we'd connect to a specific WebSocket channel for this shell
}

function closeShell() {
    document.getElementById('shell-modal').classList.add('hidden');
}

// Initialize with some dummy data
document.addEventListener('DOMContentLoaded', () => {
    addTargetToGrid({
        address: '10.10.10.5',
        description: 'Legacy Web Server',
        status: 'owned',
        os: 'Linux 5.4',
        ports: '22, 80, 443'
    });
    addTargetToGrid({
        address: '192.168.1.15',
        description: 'Domain Controller',
        status: 'scanned',
        os: 'Windows Server 2019',
        ports: '53, 88, 135, 139, 389, 445'
    });
});
