/**
 * Confirmation dialog utilities.
 * Provides tiered confirmation: simple confirm, type-to-confirm for destructive actions.
 */

import { showModal, closeModal } from './modal.js';

// Ensure confirm modal exists in DOM
function _ensureConfirmModal() {
    if (document.getElementById('spectra-confirm-modal')) return;

    const div = document.createElement('div');
    div.innerHTML = `
    <div id="spectra-confirm-modal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="spectra-confirm-title" data-modal>
      <div class="fixed inset-0 bg-black/60 backdrop-filter backdrop-blur-sm" onclick="closeModal('spectra-confirm-modal')"></div>
      <div class="relative w-full max-w-md glass-panel rounded-2xl shadow-2xl animate-fade-in-up">
        <div class="p-6">
          <h3 id="spectra-confirm-title" class="text-lg font-semibold text-white mb-2"></h3>
          <p id="spectra-confirm-msg" class="text-sm text-slate-400 mb-4"></p>
          <div id="spectra-confirm-type-area" class="hidden mb-4">
            <label class="block text-sm text-slate-400 mb-1">Type <strong id="spectra-confirm-type-label" class="text-rose-400"></strong> to confirm</label>
            <input id="spectra-confirm-type-input" type="text" class="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2 text-white focus:border-rose-500 focus:outline-none" autocomplete="off">
          </div>
          <div class="flex gap-3 justify-end">
            <button id="spectra-confirm-cancel" class="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors">Cancel</button>
            <button id="spectra-confirm-ok" class="px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed">Confirm</button>
          </div>
        </div>
      </div>
    </div>`;
    document.body.appendChild(div.firstElementChild);
}

/**
 * Show a confirmation dialog.
 * @param {string} msg - The confirmation message.
 * @param {Function} onConfirm - Called when user confirms.
 * @param {{ title?: string, confirmLabel?: string }} options
 */
export function showConfirm(msg, onConfirm, options = {}) {
    _ensureConfirmModal();

    const title = document.getElementById('spectra-confirm-title');
    const msgEl = document.getElementById('spectra-confirm-msg');
    const typeArea = document.getElementById('spectra-confirm-type-area');
    const okBtn = document.getElementById('spectra-confirm-ok');
    const cancelBtn = document.getElementById('spectra-confirm-cancel');

    title.textContent = options.title || 'Confirm Action';
    msgEl.textContent = msg;
    typeArea.classList.add('hidden');
    okBtn.textContent = options.confirmLabel || 'Confirm';
    okBtn.disabled = false;

    function cleanup() {
        closeModal('spectra-confirm-modal');
        okBtn.removeEventListener('click', handleOk);
        cancelBtn.removeEventListener('click', handleCancel);
    }

    function handleOk() { cleanup(); onConfirm(); }
    function handleCancel() { cleanup(); }

    okBtn.addEventListener('click', handleOk);
    cancelBtn.addEventListener('click', handleCancel);

    showModal('spectra-confirm-modal');
}

/**
 * Show a type-to-confirm dialog for destructive actions.
 * @param {string} label - The text the user must type to confirm.
 * @param {Function} onConfirm - Called when user types correctly and confirms.
 * @param {{ title?: string, msg?: string }} options
 */
export function showTypeConfirm(label, onConfirm, options = {}) {
    _ensureConfirmModal();

    const title = document.getElementById('spectra-confirm-title');
    const msgEl = document.getElementById('spectra-confirm-msg');
    const typeArea = document.getElementById('spectra-confirm-type-area');
    const typeLabel = document.getElementById('spectra-confirm-type-label');
    const typeInput = document.getElementById('spectra-confirm-type-input');
    const okBtn = document.getElementById('spectra-confirm-ok');
    const cancelBtn = document.getElementById('spectra-confirm-cancel');

    title.textContent = options.title || 'Destructive Action';
    msgEl.textContent = options.msg || 'This action cannot be undone.';
    typeArea.classList.remove('hidden');
    typeLabel.textContent = label;
    typeInput.value = '';
    okBtn.textContent = 'Delete';
    okBtn.disabled = true;

    function handleInput() {
        okBtn.disabled = typeInput.value !== label;
    }

    function cleanup() {
        closeModal('spectra-confirm-modal');
        okBtn.removeEventListener('click', handleOk);
        cancelBtn.removeEventListener('click', handleCancel);
        typeInput.removeEventListener('input', handleInput);
    }

    function handleOk() { if (typeInput.value === label) { cleanup(); onConfirm(); } }
    function handleCancel() { cleanup(); }

    typeInput.addEventListener('input', handleInput);
    okBtn.addEventListener('click', handleOk);
    cancelBtn.addEventListener('click', handleCancel);

    showModal('spectra-confirm-modal');
    requestAnimationFrame(() => typeInput.focus());
}

// Expose globally
window.showConfirm = showConfirm;
window.showTypeConfirm = showTypeConfirm;
