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
export function activateTab(group, tabId) {
  const tabs = document.querySelectorAll(`[role="tab"][data-tab-group="${group}"]`);
  const panels = document.querySelectorAll(`[role="tabpanel"][data-tab-group="${group}"]`);

  tabs.forEach(tab => {
    const isActive = tab.dataset.tab === tabId;
    tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
    tab.tabIndex = isActive ? 0 : -1;

    // Visual styles
    if (isActive) {
      tab.classList.add('text-violet-400', 'border-b-2', 'border-violet-500');
      tab.classList.remove('text-slate-400', 'hover:text-white', 'hover:bg-white/5');
    } else {
      tab.classList.remove('text-violet-400', 'border-b-2', 'border-violet-500');
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
  const tabs = Array.from(document.querySelectorAll(`[role="tab"][data-tab-group="${group}"]`));
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
    const tab = document.querySelector(`[role="tab"][data-tab-group="${group}"][data-tab="${tabId}"]`);
    if (tab) activateTab(group, tabId);
  }
}

// Auto-init when loaded
initTabs();

// Expose globally for non-module usage
window.activateTab = activateTab;
