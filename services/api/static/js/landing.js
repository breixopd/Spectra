/* Landing page behavior: nav state, mobile menu, scroll reveals.
   No scroll listeners; IntersectionObserver only. */

(function () {
  "use strict";

  // Mark the progressive-enhancement path only once JavaScript is available.
  // The stylesheet keeps the page fully readable without this class.
  document.documentElement.classList.add("js");

  var nav = document.getElementById("nav");
  var toggle = document.getElementById("navToggle");
  var links = document.getElementById("navLinks");

  if (!nav || !toggle || !links) {
    return;
  }

  // Nav background once the hero top leaves the viewport (sentinel-based).
  var sentinel = document.createElement("div");
  sentinel.style.cssText = "position:absolute;top:0;left:0;height:48px;width:1px;pointer-events:none;";
  document.body.prepend(sentinel);
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(
      function (entries) {
        nav.classList.toggle("scrolled", !entries[0].isIntersecting);
      },
      { threshold: 0 },
    ).observe(sentinel);
  } else {
    nav.classList.add("scrolled");
  }

  toggle.addEventListener("click", function () {
    var open = links.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
  });

  links.addEventListener("click", function (event) {
    if (event.target.closest("a")) {
      links.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && links.classList.contains("open")) {
      links.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
    }
  });

  // Scroll reveals, disabled under reduced motion (CSS also neutralizes).
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var reveals = document.querySelectorAll(".reveal");
  if (reduceMotion) {
    reveals.forEach(function (el) {
      el.classList.add("visible");
    });
    return;
  }

  if (!("IntersectionObserver" in window)) {
    reveals.forEach(function (el) {
      el.classList.add("visible");
    });
    return;
  }

  var revealObserver = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          revealObserver.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.12, rootMargin: "0px 0px -24px 0px" },
  );
  reveals.forEach(function (el) {
    revealObserver.observe(el);
  });
})();
