/**
 * CSP-safe event delegation module.
 *
 * Replaces inline event handlers (onclick, onchange, onsubmit) with
 * data-attribute-driven delegation so pages work under a strict
 * nonce-based Content-Security-Policy without 'unsafe-inline'.
 *
 * HTML patterns:
 *   <button data-action="doThing">             → click  → window.doThing(el, e)
 *   <button data-action="doThing" data-value="x"> → click → window.doThing('x', el, e)
 *   <select data-on-change="refresh">           → change → window.refresh(el, e)
 *   <form   data-on-submit="handle">            → submit → window.handle(e)  (preventDefault auto)
 */
(function () {
    // --- click ---------------------------------------------------------------
    document.addEventListener('click', function (e) {
        var el = e.target.closest('[data-action]');
        if (!el) return;

        var action = el.dataset.action;
        var fn = window[action];
        if (typeof fn !== 'function') return;

        // Prevent default for anchors (replaces "return false" in inline handlers)
        if (el.tagName === 'A') e.preventDefault();

        var value = el.dataset.value;
        if (value !== undefined) {
            fn(value, el, e);
        } else {
            fn(el, e);
        }
    });

    // --- change --------------------------------------------------------------
    document.addEventListener('change', function (e) {
        var el = e.target.closest('[data-on-change]');
        if (!el) return;

        var action = el.dataset.onChange;
        var fn = window[action];
        if (typeof fn === 'function') fn(el, e);
    });

    // --- submit --------------------------------------------------------------
    document.addEventListener('submit', function (e) {
        var form = e.target.closest('[data-on-submit]');
        if (!form) return;

        var action = form.dataset.onSubmit;
        var fn = window[action];
        if (typeof fn === 'function') {
            e.preventDefault();
            fn(e);
        }
    });

    // --- input ---------------------------------------------------------------
    document.addEventListener('input', function (e) {
        var el = e.target.closest('[data-on-input]');
        if (!el) return;

        var action = el.dataset.onInput;
        var fn = window[action];
        if (typeof fn === 'function') fn(el, e);
    });

    // --- global helper functions used by data-action -------------------------
    window.reloadPage = window.reloadPage || function () { window.location.reload(); };
    window.goBack = function () { history.back(); };
    window.clipCopy = function (value) {
        if (value) navigator.clipboard.writeText(value);
    };
    window.clipCopyStop = function (value, el, e) {
        if (e) e.stopPropagation();
        if (value) navigator.clipboard.writeText(value);
    };
    window.clipCopyCode = function (el) {
        var code = el.querySelector('code');
        if (code) navigator.clipboard.writeText(code.textContent);
    };
    window.clipCopyPayloadCode = function (el) {
        var row = el.closest('.payload-row');
        var code = row && row.querySelector('code');
        if (code) navigator.clipboard.writeText(code.textContent);
    };
    window.closeSpectraModal = function () {
        var m = document.getElementById('spectra-modal');
        if (m) m.remove();
    };
    window.removeEvidenceStop = function (idx, el, e) {
        if (e) e.stopPropagation();
        if (typeof window.removeEvidence === 'function') window.removeEvidence(parseInt(idx, 10));
    };
    window.jumpToToolStop = function (tool, el, e) {
        if (e) e.stopPropagation();
        if (typeof window.jumpToTool === 'function') window.jumpToTool(tool);
    };
})();
