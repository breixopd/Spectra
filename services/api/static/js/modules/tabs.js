/**
 * Unified tab system.
 * Data-attribute driven: data-tab-group, data-tab, data-tab-panel.
 * Supports keyboard navigation (Arrow keys) and ARIA.
 */

/**
 * Activate a specific tab within a group.
 * @param {string} group - The tab group identifier.
 * @param {string} tabId - The tab to activate.
 */
function _getTabsForGroup(group) {
  return Array.from(document.querySelectorAll('[role="tab"][data-tab-group]'))
    .filter(tab => tab.dataset.tabGroup === group);
}

function _getPanelsForGroup(group) {
  return Array.from(document.querySelectorAll('[role="tabpanel"][data-tab-group]'))
    .filter(panel => panel.dataset.tabGroup === group);
}

function _isSafeTabToken(value) {
  return typeof value === 'string' && /^[a-zA-Z0-9_-]+$/.test(value);
}

let _baseDocumentTitle = null;

function _updateDocumentTitle(activeTab) {
  if (!activeTab) return;

  if (_baseDocumentTitle === null) {
    _baseDocumentTitle = document.title;
  }

  const tabLabel = (activeTab.dataset.tabTitle || activeTab.getAttribute('aria-label') || activeTab.textContent || '')
    .replace(/\s+/g, ' ')
    .trim();

  if (!tabLabel) return;

  document.title = `${_baseDocumentTitle} (${tabLabel})`;
}

export function activateTab(group, tabId) {
  const tabs = _getTabsForGroup(group);
  const panels = _getPanelsForGroup(group);
  const activeTab = tabs.find(tab => tab.dataset.tab === tabId) || null;

  tabs.forEach(tab => {
    const isActive = tab.dataset.tab === tabId;
    tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
    tab.tabIndex = isActive ? 0 : -1;

    // Visual styles
    if (isActive) {
      tab.classList.add('text-emerald-400', 'border-b-2', 'border-emerald-500');
      tab.classList.remove('text-slate-400', 'hover:text-white', 'hover:bg-white/5');
    } else {
      tab.classList.remove('text-emerald-400', 'border-b-2', 'border-emerald-500');
      tab.classList.add('text-slate-400', 'hover:text-white', 'hover:bg-white/5');
    }
  });

  panels.forEach(panel => {
    panel.hidden = panel.dataset.tabPanel !== tabId;
  });

  // Update URL hash (non-disruptive)
  if (history.replaceState) {
    history.replaceState(null, '', `#${group}-${tabId}`);
  }

  _updateDocumentTitle(activeTab);
}

function _handleTabClick(e) {
  const tab = e.target.closest('[role="tab"][data-tab-group]');
  if (!tab) return;

  e.preventDefault();
  activateTab(tab.dataset.tabGroup, tab.dataset.tab);
  tab.focus();
}

function _handleTabKeydown(e) {
  const tab = e.target.closest('[role="tab"][data-tab-group]');
  if (!tab) return;

  const group = tab.dataset.tabGroup;
  const tabs = _getTabsForGroup(group);
  const index = tabs.indexOf(tab);

  let newIndex = -1;

  switch (e.key) {
    case 'ArrowLeft':
    case 'ArrowUp':
      e.preventDefault();
      newIndex = index <= 0 ? tabs.length - 1 : index - 1;
      break;
    case 'ArrowRight':
    case 'ArrowDown':
      e.preventDefault();
      newIndex = index >= tabs.length - 1 ? 0 : index + 1;
      break;
    case 'Home':
      e.preventDefault();
      newIndex = 0;
      break;
    case 'End':
      e.preventDefault();
      newIndex = tabs.length - 1;
      break;
  }

  if (newIndex >= 0) {
    activateTab(group, tabs[newIndex].dataset.tab);
    tabs[newIndex].focus();
  }
}

/**
 * Initialize tab system — attach event listeners via delegation.
 */
export function initTabs() {
  document.addEventListener('click', _handleTabClick);
  document.addEventListener('keydown', _handleTabKeydown);

  // Restore from URL hash
  const hash = window.location.hash.slice(1);
  if (hash.includes('-')) {
    const sep = hash.indexOf('-');
    const group = hash.substring(0, sep);
    const tabId = hash.substring(sep + 1);
    if (_isSafeTabToken(group) && _isSafeTabToken(tabId)) {
      const tab = _getTabsForGroup(group).find(candidate => candidate.dataset.tab === tabId);
      if (tab) activateTab(group, tabId);
    }
  }
}

// Auto-init when loaded
initTabs();

// Expose globally for non-module usage
window.activateTab = activateTab;
