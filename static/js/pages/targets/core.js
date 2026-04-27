let isImportMenuOpen = false;

function setImportMenuOpen(isOpen) {
    const trigger = document.getElementById('import-menu-trigger');
    const menu = document.getElementById('import-menu');
    if (!trigger || !menu) return;

    isImportMenuOpen = isOpen;
    trigger.setAttribute('aria-expanded', String(isOpen));
    menu.setAttribute('aria-hidden', String(!isOpen));

    if (isOpen) {
        menu.classList.remove('opacity-0', 'invisible');
        menu.classList.add('opacity-100', 'visible');
        return;
    }

    menu.classList.add('opacity-0', 'invisible');
    menu.classList.remove('opacity-100', 'visible');
}

function toggleImportMenu() {
    setImportMenuOpen(!isImportMenuOpen);
}

function closeImportMenu() {
    setImportMenuOpen(false);
}

function initImportMenu() {
    const wrapper = document.getElementById('import-menu-wrapper');
    const trigger = document.getElementById('import-menu-trigger');
    const menu = document.getElementById('import-menu');
    if (!wrapper || !trigger || !menu) return;

    trigger.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        toggleImportMenu();
    });

    menu.querySelectorAll('button').forEach((button) => {
        button.addEventListener('click', () => closeImportMenu());
    });

    document.addEventListener('click', (event) => {
        if (isImportMenuOpen && !wrapper.contains(event.target)) {
            closeImportMenu();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && isImportMenuOpen) {
            closeImportMenu();
            trigger.focus();
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initImportMenu();
});
