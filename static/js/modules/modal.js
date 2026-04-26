/**
 * Unified modal system.
 * Shows/hides modals, manages focus trapping, keyboard handling.
 */

let _activeModal = null;
let _previousFocus = null;

/**
 * Show a modal by ID.
 * @param {string} id - The modal element ID.
 */
export function showModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;

  _previousFocus = document.activeElement;
  _activeModal = modal;

  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';

  // Focus first focusable element
  requestAnimationFrame(() => {
    const focusable = _getFocusable(modal);
    if (focusable.length) focusable[0].focus();
  });
}

/**
 * Close a modal by ID.
 * @param {string} id - The modal element ID.
 */
export function closeModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;

  modal.classList.add('hidden');
  document.body.style.overflow = '';

  if (_activeModal === modal) _activeModal = null;
  if (_previousFocus) {
    _previousFocus.focus();
    _previousFocus = null;
  }
}

/**
 * Close the currently active modal.
 */
export function closeActiveModal() {
  if (_activeModal) {
    closeModal(_activeModal.id);
  }
}

function _getFocusable(container) {
  return Array.from(container.querySelectorAll(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  )).filter(el => el.offsetParent !== null);
}

function _handleKeydown(e) {
  if (!_activeModal) return;

  if (e.key === 'Escape') {
    e.preventDefault();
    closeActiveModal();
    return;
  }

  if (e.key === 'Tab') {
    const focusable = _getFocusable(_activeModal);
    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }
}

// Register keyboard handler
document.addEventListener('keydown', _handleKeydown);

// Expose globally for inline onclick handlers (until full ES module migration)
window.showModal = showModal;
window.closeModal = closeModal;
