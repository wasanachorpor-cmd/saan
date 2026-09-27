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
  var speaking = false;
  function setReading(on) {
    speaking = on;
    readButton.setAttribute("aria-pressed", on ? "true" : "false");
    readButton.textContent = on ? readButton.getAttribute("data-stop") : readButton.getAttribute("data-read");
  }
  readButton.addEventListener("click", function () {
    if (!window.speechSynthesis) return;
    if (speaking) {
      window.speechSynthesis.cancel();
      setReading(false);
      return;
    }
    var main = document.getElementById("main");
    var text = main ? main.innerText.replace(/\s+/g, " ").trim().slice(0, 1400) : "";
    if (!text) return;
    window.speechSynthesis.cancel();
    var utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = document.documentElement.lang === "th" ? "th-TH" : "en-US";
    utterance.onend = function () { setReading(false); };
    utterance.onerror = function () { setReading(false); };
    setReading(true);
    window.speechSynthesis.speak(utterance);
  });
})();
