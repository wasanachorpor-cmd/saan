(function () {
  var play = document.getElementById("welcome-play");
  if (play) {
    var welcomeBytes = null;
    var welcomeFlight = null;
    var welcomeQueued = false;
    var lang = document.documentElement.lang === "th" ? "th" : "en";
    function loadWelcome() {
      if (welcomeBytes) return Promise.resolve(welcomeBytes);
      if (welcomeFlight) return welcomeFlight;
      function once() {
        return fetch("/api/welcome?lang=" + lang).then(function (response) {
          if (!response.ok) throw new Error("welcome");
          return response.arrayBuffer();
        });
      }
      welcomeFlight = once().catch(function () { return once(); }).then(function (bytes) {
        welcomeBytes = bytes;
        welcomeFlight = null;
        return bytes;
      }, function (error) {
        welcomeFlight = null;
        throw error;
      });
      return welcomeFlight;
    }
    loadWelcome().catch(function () {});
    play.addEventListener("click", function () {
      var live = document.getElementById("live");
      if (window.saanAudio) window.saanAudio.arm();
      if (welcomeQueued) {
        if (live) live.textContent = play.getAttribute("data-busy") || "";
        return;
      }
      if (window.saanAudio && window.saanAudio.playing() && welcomeBytes) {
        window.saanAudio.play(welcomeBytes);
        return;
      }
      welcomeQueued = true;
      play.setAttribute("aria-busy", "true");
      if (live) live.textContent = play.getAttribute("data-busy") || "";
      loadWelcome().then(function (bytes) {
        welcomeQueued = false;
        play.removeAttribute("aria-busy");
        if (window.saanAudio) return window.saanAudio.play(bytes);
        return new Audio(URL.createObjectURL(new Blob([bytes], { type: "audio/mpeg" }))).play();
      }).catch(function () {
        welcomeQueued = false;
        play.removeAttribute("aria-busy");
        if (live) live.textContent = play.getAttribute("data-busy") || play.textContent;
      });
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
