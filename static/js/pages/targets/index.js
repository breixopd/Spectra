import './core.js';
import './grid.js';
import './import.js';
import './shell.js';
import './attack-surface.js';

window.openAddTargetModal = openAddTargetModal;
window.closeAddTargetModal = closeAddTargetModal;
window.handleAddTarget = handleAddTarget;
window.closeShell = closeShell;
window.openImportModal = openImportModal;
window.closeImportModal = closeImportModal;
window.handleImportDrop = handleImportDrop;
window.handleImportFile = handleImportFile;
window.clearImportPreview = clearImportPreview;
window.executeImport = executeImport;
window.changeASLayout = changeASLayout;
window.fitASGraph = fitASGraph;
window.resetASGraph = resetASGraph;
window.exportASGraph = exportASGraph;

window.triggerImportFileInput = function() { document.getElementById('import-file-input').click(); };
window.navigateToTargets = function() { window.location.href = '/targets'; };

const _importUploadArea = document.getElementById('import-upload-area');
if (_importUploadArea) {
    _importUploadArea.addEventListener('drop', e => handleImportDrop(e));
    _importUploadArea.addEventListener('dragover', e => e.preventDefault());
}

document.getElementById('target-search')?.addEventListener('input', function() { filterTargets(this.value); });
