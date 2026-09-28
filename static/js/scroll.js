(function () {
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || !("IntersectionObserver" in window)) return;
  var cards = [].slice.call(document.querySelectorAll(".impact-card, .voice-card, .steps > li, .promises > li"));
  var titles = [].slice.call(document.querySelectorAll(".impact > .kicker, .impact > h2, .impact > .lead, .voices > .kicker, .voices > h2, .voices > .lead, .section > h2"));
  if (!cards.length && !titles.length) return;

  function place(list, className) {
    list.forEach(function (el) {
      el.classList.add(className);
      var siblings = [].filter.call(el.parentElement ? el.parentElement.children : [], function (item) {
        return item.classList && item.classList.contains(className);
      });
      var index = siblings.indexOf(el);
      if (index > 0) el.style.transitionDelay = (index * 90) + "ms";
    });
  }
  place(cards, "motion-card");
  place(titles, "motion-title");

  var seen = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-in");
      seen.unobserve(entry.target);
    });
  }, { threshold: 0.22, rootMargin: "0px 0px -8% 0px" });

  cards.concat(titles).forEach(function (el) {
    var box = el.getBoundingClientRect();
    if (box.top < window.innerHeight * 0.92 && box.bottom > 0) el.classList.add("is-in");
    else seen.observe(el);
  });
  document.documentElement.classList.add("motion-ready");
})();
