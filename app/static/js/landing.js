/* ====== LANDING PAGE SCRIPTS ====== */

// Navbar scroll effect
const nav = document.getElementById('nav');
window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 40);
}, { passive: true });

// Mobile menu toggle
document.getElementById('mobileToggle').addEventListener('click', () => {
    document.getElementById('navLinks').classList.toggle('open');
});

// Close mobile menu on link click
document.querySelectorAll('.nav-links a').forEach(a => {
    a.addEventListener('click', () => {
        document.getElementById('navLinks').classList.remove('open');
    });
});

// Scroll reveal with stagger
const reveals = document.querySelectorAll('.reveal');
const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
            setTimeout(() => entry.target.classList.add('visible'), i * 60);
            observer.unobserve(entry.target);
        }
    });
}, { threshold: 0.1, rootMargin: '0px 0px -20px 0px' });
reveals.forEach(el => observer.observe(el));

// Trigger reveals for elements already in viewport on load
reveals.forEach(el => {
    const rect = el.getBoundingClientRect();
    if (rect.top < window.innerHeight && rect.bottom > 0) {
        el.classList.add('visible');
        observer.unobserve(el);
    }
});

// FAQ toggle — using event delegation (CSP-safe, no inline onclick)
document.querySelectorAll('.faq-question').forEach(btn => {
    btn.addEventListener('click', () => {
        const item = btn.parentElement;
        const expanded = btn.getAttribute('aria-expanded') === 'true';
        btn.setAttribute('aria-expanded', String(!expanded));
        item.classList.toggle('open');
    });
});
