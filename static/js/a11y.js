(function () {
  document.querySelectorAll("form[data-pref]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var kind = form.getAttribute("data-pref");
      if (kind === "lang") return;
      event.preventDefault();
      var root = document.documentElement;
      if (kind === "contrast") {
        var next = root.getAttribute("data-contrast") === "high" ? "night" : "high";
        root.setAttribute("data-contrast", next);
        var toggle = form.querySelector("button");
        if (toggle) toggle.setAttribute("aria-pressed", next === "high" ? "true" : "false");
      }
      if (kind === "font") {
        var value = form.getAttribute("data-value");
        root.setAttribute("data-font", value);
        document.querySelectorAll("form[data-pref='font'] button").forEach(function (button) {
          var pressed = button.form && button.form.getAttribute("data-value") === value;
          button.setAttribute("aria-pressed", pressed ? "true" : "false");
        });
      }
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Saan-Fetch": "1" },
      }).then(function (response) {
        if (!response.ok) form.submit();
      }).catch(function () {
        form.submit();
      });
    });
  });

  var readButton = document.getElementById("read-page");
  if (!readButton) return;
  var run = 0;
  var heard = false;
  var preparing = false;
  var flights = {};
  function setButton(mode) {
    var on = mode !== "idle";
    readButton.setAttribute("aria-pressed", on ? "true" : "false");
    if (mode === "wait") readButton.setAttribute("aria-busy", "true");
    else readButton.removeAttribute("aria-busy");
    var label = readButton.getAttribute("data-read");
    if (mode === "wait") label = readButton.getAttribute("data-busy");
    if (mode === "play") label = readButton.getAttribute("data-stop");
    readButton.textContent = label || "";
  }
  function stopReading() {
    run += 1;
    heard = false;
    preparing = false;
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    if (window.saanAudio) window.saanAudio.stop();
    setButton("idle");
  }
  function blockText(node) {
    return (node.innerText || node.textContent || "").replace(/[ \t]+/g, " ").replace(/\n+/g, " ").trim();
  }
  function pageSource(root) {
    var snippets = root.querySelectorAll("[data-snippet-text]");
    var lines = [];
    if (snippets.length) {
      snippets.forEach(function (node) {
        var text = blockText(node);
        if (text) lines.push(text);
      });
      return lines.join("\n");
    }
    root.querySelectorAll("h1, h2, h3, p, li").forEach(function (node) {
      if (node.closest("button, nav, form, .player, .a11y-bar, .danger-zone, .topbar, footer")) return;
      if (node.querySelector("h1, h2, h3, p, li")) return;
      var text = blockText(node);
      if (text) lines.push(text);
    });
    return lines.join("\n");
  }
  function pageParts(text, fallback) {
    if (!window.saanParts || !window.saanLead) return [];
    return window.saanLead(window.saanParts(text, 150, fallback)).filter(function (part) {
      return /[A-Za-z\u0E00-\u0E7F]/.test(part.text);
    });
  }
  function fetchAudio(part) {
    var key = part.lang + "\n1\n" + part.text;
    if (window.saanAudio) {
      var saved = window.saanAudio.recall(key);
      if (saved) return Promise.resolve(saved);
    }
    if (flights[key]) return flights[key];
    function once() {
      return fetch("/api/page-voice", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF": readButton.getAttribute("data-csrf") || "",
        },
        body: JSON.stringify({ text: part.text, lang: part.lang, rate: 1 }),
      }).then(function (response) {
        if (!response.ok) throw new Error("speak");
        return response.arrayBuffer();
      });
    }
    flights[key] = once().catch(function () { return once(); }).then(function (bytes) {
      if (window.saanAudio) window.saanAudio.remember(key, bytes);
      delete flights[key];
      return bytes;
    }, function (error) {
      delete flights[key];
      throw error;
    });
    return flights[key];
  }
  function announce(message) {
    var live = document.getElementById("live");
    if (!live || !message) return;
    live.textContent = "";
    window.setTimeout(function () { live.textContent = message; }, 40);
  }
  function readParts(parts) {
    var token = ++run;
    heard = false;
    preparing = true;
    if (window.saanAudio) window.saanAudio.arm();
    var live = document.getElementById("live");
    if (live) live.textContent = readButton.getAttribute("data-busy") || "";
    setButton("wait");
    if (!window.saanSequence) return;
    window.saanSequence({
      parts: parts,
      alive: function () { return token === run; },
      fetch: fetchAudio,
      onFirst: function () {
        heard = true;
        preparing = false;
        setButton("play");
      },
      onDone: function (played) {
        if (token !== run) return;
        heard = false;
        preparing = false;
        setButton("idle");
        if (!played) announce(readButton.getAttribute("data-failed") || "");
      }
    });
  }
  readButton.addEventListener("click", function () {
    if (heard) {
      stopReading();
      return;
    }
    if (preparing) {
      announce(readButton.getAttribute("data-busy") || "");
      return;
    }
    var main = document.getElementById("main");
    var text = main ? pageSource(main) : "";
    if (!text) return;
    var lang = document.documentElement.lang === "th" ? "th-TH" : "en-US";
    var parts = pageParts(text, lang);
    if (!parts.length) return;
    readParts(parts);
  });
})();
