/**
 * Shared accordion toggle for consistent expand/collapse behavior.
 * Supports both inline maxHeight and .open class approaches.
 */
function toggleAccordion(button) {
    const content = button.nextElementSibling;
    const icon = button.querySelector('[data-lucide="chevron-down"], [data-lucide="chevron-right"], .accordion-icon, svg');
    const isOpen = content.style.maxHeight || content.classList.contains('open');
    if (isOpen) {
        content.style.maxHeight = null;
        content.classList.remove('open');
        if (icon) icon.style.transform = '';
    } else {
        content.style.maxHeight = content.scrollHeight + 'px';
        content.classList.add('open');
        if (icon) {
            // chevron-right rotates 90° to point down; chevron-down rotates 180° to point up
            var attr = icon.getAttribute && icon.getAttribute('data-lucide');
            icon.style.transform = attr === 'chevron-right' ? 'rotate(90deg)' : 'rotate(180deg)';
        }
    }
}
window.toggleAccordion = toggleAccordion;
