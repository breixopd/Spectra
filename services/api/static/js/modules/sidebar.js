(function() {
    'use strict';

    function toggleSidebar() {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebar-overlay');
        if (sidebar && overlay) {
            sidebar.classList.toggle('open');
            overlay.classList.toggle('active');
        }
    }

    function initSidebar() {
        document.querySelectorAll('.sidebar nav a').forEach(function(link) {
            link.addEventListener('click', function() {
                if (window.innerWidth < 768) toggleSidebar();
            });
        });

        window.addEventListener('resize', function() {
            if (window.innerWidth >= 768) {
                const sidebar = document.getElementById('sidebar');
                const overlay = document.getElementById('sidebar-overlay');
                if (sidebar) sidebar.classList.remove('open');
                if (overlay) overlay.classList.remove('active');
            }
        });

        document.querySelectorAll('[data-action="toggleSidebar"]').forEach(function(btn) {
            btn.addEventListener('click', toggleSidebar);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSidebar);
    } else {
        initSidebar();
    }

    window.toggleSidebar = toggleSidebar;
})();