// Reports Management Logic

function addReportToTable(report) {
    const tbody = document.getElementById('reports-list');
    const template = document.getElementById('report-row-template');
    const clone = template.content.cloneNode(true);
    
    clone.querySelector('.report-name').textContent = report.name;
    clone.querySelector('.report-target').textContent = report.target;
    clone.querySelector('.report-date').textContent = report.date;
    
    clone.querySelector('.report-critical').textContent = report.findings.critical;
    clone.querySelector('.report-high').textContent = report.findings.high;
    clone.querySelector('.report-medium').textContent = report.findings.medium;
    
    tbody.appendChild(clone);
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadReports();
});

async function loadReports() {
    try {
        const response = await fetch('/api/v1/missions');
        if (!response.ok) throw new Error('Failed to fetch reports');

        const missions = await response.json();
        const tbody = document.getElementById('reports-list');
        tbody.innerHTML = ''; // Clear existing

        missions.forEach(mission => {
            // Count findings by severity
            const counts = { critical: 0, high: 0, medium: 0, low: 0 };
            if (mission.findings) {
                mission.findings.forEach(f => {
                    if (counts.hasOwnProperty(f.severity)) {
                        counts[f.severity]++;
                    }
                });
            }

            addReportToTable({
                id: mission.id,
                name: `Mission: ${mission.target}`,
                target: mission.target,
                date: new Date(mission.created_at).toLocaleDateString(),
                status: mission.status,
                findings: counts
            });
        });

    } catch (error) {
        console.error('Error loading reports:', error);
    }
}

function addReportToTable(report) {
    const tbody = document.getElementById('reports-list');
    const template = document.getElementById('report-row-template');
    const clone = template.content.cloneNode(true);

    clone.querySelector('.report-name').textContent = report.name;
    clone.querySelector('.report-target').textContent = report.target;
    clone.querySelector('.report-date').textContent = report.date;

    clone.querySelector('.report-critical').textContent = report.findings.critical;
    clone.querySelector('.report-high').textContent = report.findings.high;
    clone.querySelector('.report-medium').textContent = report.findings.medium;

    // Optional: Add link to detail view
    // clone.querySelector('tr').onclick = () => window.location.href = `/reports/${report.id}`;

    tbody.appendChild(clone);
}
