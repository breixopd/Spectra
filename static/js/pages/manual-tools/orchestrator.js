// Init
document.addEventListener('DOMContentLoaded', async () => {
    // Activate the initial tab via tabs.js so ARIA state is correct from the start
    if (window.activateTab) window.activateTab('manual-tabs', 'execute');
    loadTools();
    showTip();
    initRevShells();
    initEncoder();
    initPorts();
    loadWordlists();

    // Try loading manual state from server before falling back to localStorage
    const serverLoaded = await loadManualStateFromServer();
    if (serverLoaded) {
        console.debug('Manual mode state loaded from server');
    }

    loadChecklist();
    loadNotes();
    loadEvidence();
    initLFI();
    initSQLi();
    initPrivEsc();
    renderADCommands();
    initEvidenceDragDrop();
    initClipboardPaste();
});


const debouncedFilterTools = debounce(filterTools);
const debouncedFilterHistory = debounce(filterHistory);
const debouncedFilterPorts = debounce(filterPorts);
const debouncedFilterLFI = debounce(filterLFI);
const debouncedFilterSQLi = debounce(filterSQLi);
const debouncedFilterPrivEsc = debounce(filterPrivEsc);

// Expose functions to global scope for HTML event handlers
window.switchManualTab = switchManualTab;
window.nextTip = nextTip;
window.startSession = startSession;
window.exportSession = exportSession;
window.toggleScopePanel = toggleScopePanel;
window.addScopeTarget = addScopeTarget;
window.addScopeExclusion = addScopeExclusion;
window.saveScope = saveScope;
window.quickRun = quickRun;
window.debouncedFilterTools = debouncedFilterTools;
window.executeManualTool = executeManualTool;
window.clearOutput = clearOutput;
window.openDiffModal = openDiffModal;
window.toggleHistoryPanel = toggleHistoryPanel;
window.debouncedFilterHistory = debouncedFilterHistory;
window.filterHistory = filterHistory;
window.sortHistory = sortHistory;
window.addPipelineStep = addPipelineStep;
window.runPipeline = runPipeline;
window.loadPipelineTemplate = loadPipelineTemplate;
window.searchCVEs = searchCVEs;
window.loadChecklist = loadChecklist;
window.resetChecklist = resetChecklist;
window.filterNotes = filterNotes;
window.createNote = createNote;
window.wrapNoteText = wrapNoteText;
window.toggleNotePreview = toggleNotePreview;
window.onNoteEdit = onNoteEdit;
window.deleteNote = deleteNote;
window.saveCurrentNote = saveCurrentNote;
window.uploadEvidence = uploadEvidence;
window.pasteEvidence = pasteEvidence;
window.filterEvidence = filterEvidence;
window.dismissTipsBanner = function() { document.getElementById('tips-banner')?.classList.add('hidden'); };
window.switchHelperTab = switchHelperTab;
window.copyToClipboard = copyToClipboard;
window.copyListenerCmd = copyListenerCmd;
window.debouncedFilterPorts = debouncedFilterPorts;
window.loadWordlists = loadWordlists;
window.uploadWordlist = uploadWordlist;
window.setCVSS = setCVSS;
window.parseCVSSVector = parseCVSSVector;
window.copyCVSSVector = copyCVSSVector;
window.debouncedFilterLFI = debouncedFilterLFI;
window.filterLFIOS = filterLFIOS;
window.debouncedFilterSQLi = debouncedFilterSQLi;
window.debouncedFilterPrivEsc = debouncedFilterPrivEsc;
window.renderADCommands = renderADCommands;
window.selectManualTool = selectManualTool;
window.lookupCVEsFor = lookupCVEsFor;
window.runToolOn = runToolOn;
window.chainToTool = chainToTool;
window.removePipelineStep = removePipelineStep;
window.updatePipelineStep = updatePipelineStep;
window.viewHistoryOutput = viewHistoryOutput;
window.rerunFromHistory = rerunFromHistory;
window.runDiff = runDiff;
window.launchMetasploit = launchMetasploit;
window.filterShells = filterShells;
window.selectShell = selectShell;
window.filterEncoder = filterEncoder;
window.runEncoder = runEncoder;
window.filterPortCat = filterPortCat;
window.jumpToTool = jumpToTool;
window.downloadPreset = downloadPreset;
window.removeScopeTarget = removeScopeTarget;
window.removeScopeExclusion = removeScopeExclusion;
window.toggleAccordion = toggleAccordion;
window.toggleChecklistItem = toggleChecklistItem;
window.toggleChecklistNotes = toggleChecklistNotes;
window.saveChecklistNote = saveChecklistNote;
window.openNote = openNote;
window.previewEvidence = previewEvidence;
window.removeEvidence = removeEvidence;
window.filterSQLiCat = filterSQLiCat;
window.filterPrivEscFn = filterPrivEscFn;
window.refreshWordlistOptions = refreshWordlistOptions;
window.showSpectraModal = showSpectraModal;
window.updatePipelineStepFromEl = updatePipelineStepFromEl;
window.toggleChecklistItemFromEl = toggleChecklistItemFromEl;
window.saveChecklistNoteFromEl = saveChecklistNoteFromEl;
