(function () {
  var play = document.getElementById("welcome-play");
  var welcomeAudio = null;
  if (play) {
    play.addEventListener("click", function () {
      var lang = document.documentElement.lang === "th" ? "th" : "en";
      if (welcomeAudio) {
        welcomeAudio.pause();
        welcomeAudio = null;
      }
      welcomeAudio = new Audio("/api/welcome?lang=" + lang);
      var live = document.getElementById("live");
      welcomeAudio.addEventListener("error", function () {
        if (live) live.textContent = play.textContent;
      });
      welcomeAudio.play();
    });
  }

  var tabs = [].slice.call(document.querySelectorAll(".preview-tabs [role='tab']"));
  if (!tabs.length) return;
  var timer = 0;
  function show(index) {
    tabs.forEach(function (tab, item) {
      var on = item === index;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      var panel = document.getElementById(tab.getAttribute("aria-controls"));
      if (panel) panel.hidden = !on;
    });
  }
  tabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () {
      show(index);
      window.clearInterval(timer);
      timer = 0;
    });
  });
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduce) {
    var step = 0;
    timer = window.setInterval(function () {
      step = (step + 1) % tabs.length;
      show(step);
    }, 3600);
  }
})();
