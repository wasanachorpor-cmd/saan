(function () {
  var live = document.getElementById("live");
  function say(message) {
    if (live && message) live.textContent = message;
  }

  var zone = document.getElementById("dropzone");
  var fileForm = document.getElementById("file-form");
  var cameraForm = document.getElementById("camera-form");

  function compressImage(file) {
    return new Promise(function (resolve) {
      if (!file || !/^image\//.test(file.type || "") || file.size < 700000 || typeof Image === "undefined") {
        resolve(file);
        return;
      }
      var url = URL.createObjectURL(file);
      var image = new Image();
      image.onload = function () {
        var maxSide = 1800;
        var scale = Math.min(1, maxSide / Math.max(image.width, image.height));
        var canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(image.width * scale));
        canvas.height = Math.max(1, Math.round(image.height * scale));
        var context = canvas.getContext("2d");
        if (!context) {
          URL.revokeObjectURL(url);
          resolve(file);
          return;
        }
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(function (blob) {
          URL.revokeObjectURL(url);
          if (!blob || blob.size >= file.size) {
            resolve(file);
            return;
          }
          resolve(new File([blob], "page.jpg", { type: "image/jpeg" }));
        }, "image/jpeg", 0.82);
      };
      image.onerror = function () {
        URL.revokeObjectURL(url);
        resolve(file);
      };
      image.src = url;
    });
  }

  function submitForm(form, fileOverride) {
    if (!form || !window.fetch) {
      form.submit();
      return;
    }
    var data = new FormData(form);
    if (fileOverride) data.set("image", fileOverride, fileOverride.name);
    var file = data.get("image");
    if (!file || !file.name) {
      say((zone && zone.getAttribute("data-need-file")) || "Choose an image first.");
      return;
    }
    if (zone) {
      zone.classList.add("is-busy");
      zone.setAttribute("aria-busy", "true");
    }
    say((zone && zone.getAttribute("data-uploading")) || "Uploading the page");
    compressImage(file).then(function (smaller) {
      if (smaller !== file) data.set("image", smaller, smaller.name);
      return fetch(form.action, {
      method: "POST",
      body: data,
      headers: { "X-Saan-Fetch": "1", Accept: "application/json" },
    }).then(function (response) {
      return response.json().then(function (body) {
        return { ok: response.ok, body: body };
      });
    }).then(function (result) {
      if (result.ok && result.body.location) {
        window.location.assign(result.body.location);
        return;
      }
      say((result.body && result.body.message) || "Upload failed");
      if (zone) zone.classList.remove("is-busy");
    }).catch(function () {
      form.submit();
    });
    });
  }

  if (fileForm) {
    fileForm.addEventListener("submit", function (event) {
      event.preventDefault();
      submitForm(fileForm);
    });
  }
  if (cameraForm) {
    var cameraInput = document.getElementById("camera-input");
    var openCamera = document.getElementById("open-camera");
    var cameraLive = document.getElementById("camera-live");
    var cameraVideo = document.getElementById("camera-video");
    var cameraSnap = document.getElementById("camera-snap");
    var cameraClose = document.getElementById("camera-close");
    var cameraNote = document.getElementById("camera-note");
    var cameraStream = null;

    function cameraMessage(text) {
      say(text);
      if (!cameraNote) return;
      cameraNote.hidden = !text;
      cameraNote.textContent = text || "";
    }

    function stopCamera() {
      if (cameraStream) {
        cameraStream.getTracks().forEach(function (track) { track.stop(); });
        cameraStream = null;
      }
      if (cameraVideo) cameraVideo.srcObject = null;
      if (cameraLive) {
        cameraLive.hidden = true;
        cameraLive.classList.remove("is-on");
      }
    }

    function openLiveCamera() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !cameraVideo) {
        cameraMessage((zone && zone.getAttribute("data-camera-denied")) || "");
        return;
      }
      cameraMessage("");
      var tries = [
        { audio: false, video: { facingMode: { ideal: "environment" } } },
        { audio: false, video: true }
      ];
      function attempt(index) {
        return navigator.mediaDevices.getUserMedia(tries[index]).catch(function (error) {
          if (index + 1 < tries.length) return attempt(index + 1);
          throw error;
        });
      }
      attempt(0).then(function (stream) {
        stopCamera();
        cameraStream = stream;
        cameraVideo.srcObject = stream;
        cameraLive.hidden = false;
        cameraLive.classList.add("is-on");
        cameraLive.scrollIntoView({ block: "nearest" });
        return cameraVideo.play();
      }).catch(function () {
        stopCamera();
        cameraMessage((zone && zone.getAttribute("data-camera-denied")) || "");
      });
    }

    if (cameraInput) {
      cameraInput.addEventListener("change", function () {
        if (cameraInput.files && cameraInput.files[0]) submitForm(cameraForm);
      });
    }
    if (openCamera) {
      openCamera.addEventListener("click", function () {
        var phone = window.matchMedia("(pointer: coarse)").matches;
        if (phone && cameraInput) {
          cameraInput.click();
          return;
        }
        openLiveCamera();
      });
    }
    if (cameraClose) cameraClose.addEventListener("click", stopCamera);
    if (cameraSnap && cameraVideo) {
      cameraSnap.addEventListener("click", function () {
        if (!cameraVideo.videoWidth) return;
        var canvas = document.createElement("canvas");
        canvas.width = cameraVideo.videoWidth;
        canvas.height = cameraVideo.videoHeight;
        var context = canvas.getContext("2d");
        if (!context) return;
        context.drawImage(cameraVideo, 0, 0);
        canvas.toBlob(function (blob) {
          if (!blob) return;
          var photo = new File([blob], "page.jpg", { type: "image/jpeg" });
          stopCamera();
          submitForm(cameraForm, photo);
        }, "image/jpeg", 0.9);
      });
    }
  }
  if (zone) {
    ["dragenter", "dragover"].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault();
        zone.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault();
        zone.classList.remove("is-dragover");
      });
    });
    zone.addEventListener("drop", function (event) {
      var file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      var input = document.getElementById("file-input");
      if (!file || !input || typeof DataTransfer === "undefined") return;
      var transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      if (fileForm) fileForm.requestSubmit ? fileForm.requestSubmit() : fileForm.submit();
    });
  }

  var reader = document.getElementById("reader");
  if (!reader) return;

  if (reader.getAttribute("data-status") === "processing") {
    var docId = reader.getAttribute("data-doc-id");
    function reloadWhenReady(payload) {
      if (payload && payload.status && payload.status !== "processing") {
        window.location.reload();
      }
    }
    if (window.EventSource) {
      var source = new EventSource("/api/documents/" + docId + "/events");
      source.onmessage = function (event) {
        var payload = JSON.parse(event.data);
        var label = reader.getAttribute("data-label-" + payload.status);
        if (label) say(label);
        if (payload.status && payload.status !== "processing") {
          source.close();
          window.location.reload();
        }
      };
    }
    window.setInterval(function () {
      fetch("/api/documents/" + docId, { credentials: "same-origin" })
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(reloadWhenReady)
        .catch(function () {});
    }, 3000);
  }

  document.querySelectorAll("[data-snippet-text]").forEach(wrapWords);

  var rate = document.getElementById("rate");
  var rateOut = document.getElementById("rate-out");
  var voice = document.getElementById("voice");
  var playAll = document.getElementById("play-all");
  var pauseBtn = document.getElementById("pause");
  var stopBtn = document.getElementById("stop");
  var chain = [];
  var stopped = true;
  var pending = false;
  var heardAny = false;
  var runToken = 0;
  var decodedAhead = {};
  var flights = {};
  var pressed = [];

  if (rate && window.localStorage) {
    var savedRate = window.localStorage.getItem("saan_rate");
    if (savedRate) rate.value = savedRate;
  }
  function showRate() {
    if (!rate || !rateOut) return;
    var value = Number(rate.value).toFixed(1);
    rateOut.textContent = value + "×";
    rate.setAttribute("aria-valuetext", value + "×");
  }
  showRate();
  if (rate) {
    rate.addEventListener("input", function () {
      showRate();
      decodedAhead = {};
      if (window.localStorage) window.localStorage.setItem("saan_rate", rate.value);
    });
  }

  function loadVoices() {
    if (!window.speechSynthesis || !voice) return;
    var voices = window.speechSynthesis.getVoices();
    if (voice) {
      var saved = window.localStorage ? window.localStorage.getItem("saan_voice") || "" : "";
      var autoLabel = voice.getAttribute("data-auto") || "Automatic";
      voice.replaceChildren();
      var auto = document.createElement("option");
      auto.value = "";
      auto.textContent = autoLabel;
      voice.appendChild(auto);
      voices.forEach(function (item) {
        var option = document.createElement("option");
        option.value = item.voiceURI;
        option.textContent = item.name + " (" + item.lang + ")";
        voice.appendChild(option);
      });
      if ([].some.call(voice.options, function (option) { return option.value === saved; })) {
        voice.value = saved;
      }
    }
  }
  if (window.speechSynthesis) {
    loadVoices();
    window.speechSynthesis.addEventListener("voiceschanged", loadVoices);
  }
  if (voice) {
    voice.addEventListener("change", function () {
      if (window.localStorage) window.localStorage.setItem("saan_voice", voice.value);
    });
  }

  function rateValue() {
    return rate ? Number(rate.value) : 1;
  }

  function clipKey(text, lang) {
    return lang + "\n" + rateValue() + "\n" + text;
  }

  function voiceFor(bcp47) {
    var voices = window.speechSynthesis.getVoices();
    var prefix = bcp47.toLowerCase().slice(0, 2);
    var manual = voice && voice.value;
    if (manual) {
      var chosen = voices.find(function (item) { return item.voiceURI === manual; }) || null;
      if (chosen && chosen.lang.toLowerCase().replace("_", "-").indexOf(prefix) === 0) return chosen;
    }
    var matches = voices.filter(function (item) {
      return item.localService && item.lang.toLowerCase().replace("_", "-").indexOf(prefix) === 0;
    });
    matches.sort(function (a, b) {
      var wanted = bcp47.toLowerCase();
      var aExact = a.lang.toLowerCase().replace("_", "-").indexOf(wanted) === 0 ? 0 : 1;
      var bExact = b.lang.toLowerCase().replace("_", "-").indexOf(wanted) === 0 ? 0 : 1;
      if (aExact !== bExact) return aExact - bExact;
      return (a.localService === b.localService) ? 0 : (a.localService ? -1 : 1);
    });
    return matches[0] || null;
  }

  function clearMarks() {
    document.querySelectorAll(".word.is-current").forEach(function (node) {
      node.classList.remove("is-current");
    });
  }

  function highlight(container, charIndex) {
    clearMarks();
    var current = null;
    container.querySelectorAll(".word").forEach(function (word) {
      if (Number(word.dataset.start) <= charIndex) current = word;
    });
    if (current) current.classList.add("is-current");
  }

  function showJob(job) {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    job.node.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  }

  function releaseButtons() {
    pressed.forEach(function (button) {
      if (button.dataset.label) button.textContent = button.dataset.label;
      button.removeAttribute("aria-busy");
    });
    pressed = [];
  }

  function armButton(button) {
    if (!button) return;
    button.dataset.label = button.dataset.label || button.textContent;
    button.textContent = reader.getAttribute("data-label-speaking") || button.dataset.label;
    button.setAttribute("aria-busy", "true");
    pressed.push(button);
  }

  function sayAgain(message) {
    if (!live || !message) return;
    live.textContent = "";
    window.setTimeout(function () { live.textContent = message; }, 40);
  }

  function requestClip(text, lang) {
    var key = clipKey(text, lang);
    if (window.saanAudio) {
      var saved = window.saanAudio.recall(key);
      if (saved) return Promise.resolve(saved);
    }
    if (flights[key]) return flights[key];
    function once() {
      return fetch("/api/speak", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "audio/mpeg",
          "X-CSRF": reader.getAttribute("data-csrf") || ""
        },
        body: JSON.stringify({ text: text, lang: lang, rate: rateValue() })
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

  function jobsFor(nodes) {
    var jobs = [];
    if (!window.saanParts || !window.saanLead) return jobs;
    nodes.forEach(function (node) {
      window.saanParts(node.textContent || "", 150, "th-TH").forEach(function (part) {
        if (!/[A-Za-z\u0E00-\u0E7F]/.test(part.text)) return;
        jobs.push({ node: node, text: part.text, lang: part.lang, start: part.start });
      });
    });
    return window.saanLead(jobs);
  }

  function playChain(jobs) {
    var token = runToken;
    var mark = 0;
    if (!window.saanSequence) return;
    window.saanSequence({
      parts: jobs,
      alive: function () { return !stopped && token === runToken; },
      fetch: function (part) { return requestClip(part.text, part.lang); },
      onFirst: function () {
        pending = false;
        heardAny = true;
      },
      onPlay: function (job) {
        showJob(job);
        window.cancelAnimationFrame(mark);
        function track() {
          if (stopped || token !== runToken || !window.saanAudio) return;
          var duration = window.saanAudio.duration();
          if (duration) {
            var at = Math.floor((window.saanAudio.position() / duration) * job.text.length);
            highlight(job.node, job.start + at);
          }
          mark = window.requestAnimationFrame(track);
        }
        track();
        return function () { window.cancelAnimationFrame(mark); };
      },
      onDone: function (heard) {
        window.cancelAnimationFrame(mark);
        if (stopped || token !== runToken) return;
        stopped = true;
        pending = false;
        releaseButtons();
        clearMarks();
        say(reader.getAttribute(heard ? "data-label-finished" : "data-speak-failed") || "");
      }
    });
  }

  function haltAudio() {
    runToken += 1;
    decodedAhead = {};
    if (window.saanAudio) window.saanAudio.stop();
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  function playNodes(nodes, button) {
    if (pending || (button && !stopped && pressed.indexOf(button) !== -1)) {
      sayAgain(reader.getAttribute("data-label-speaking"));
      return;
    }
    var jobs = jobsFor(nodes);
    if (!jobs.length) return;
    haltAudio();
    if (window.saanAudio) window.saanAudio.arm();
    releaseButtons();
    armButton(button);
    chain = jobs;
    stopped = false;
    pending = true;
    heardAny = false;
    clearMarks();
    say(reader.getAttribute("data-label-speaking"));
    playChain(chain);
  }

  function prime() {
    var jobs = jobsFor([].slice.call(document.querySelectorAll("[data-snippet-text]")));
    jobs.slice(0, 2).forEach(function (job) {
      requestClip(job.text, job.lang).catch(function () {});
    });
  }

  var status = reader.getAttribute("data-status");
  if (status && status !== "processing" && status !== "failed") {
    window.setTimeout(prime, 200);
  }

  if (playAll) {
    playAll.addEventListener("click", function () {
      if (window.saanAudio && window.saanAudio.paused()) {
        window.saanAudio.unlock();
        window.saanAudio.resume();
        say(reader.getAttribute("data-label-speaking"));
        return;
      }
      if (window.speechSynthesis && window.speechSynthesis.paused) {
        window.speechSynthesis.resume();
        say(reader.getAttribute("data-label-speaking"));
        return;
      }
      playNodes([].slice.call(document.querySelectorAll("[data-snippet-text]")), playAll);
    });
  }
  if (pauseBtn) {
    pauseBtn.addEventListener("click", function () {
      if (window.saanAudio && window.saanAudio.playing()) {
        window.saanAudio.pause();
        say(reader.getAttribute("data-label-paused"));
        return;
      }
      if (window.speechSynthesis && window.speechSynthesis.speaking && !window.speechSynthesis.paused) {
        window.speechSynthesis.pause();
        say(reader.getAttribute("data-label-paused"));
      }
    });
  }
  if (stopBtn) {
    stopBtn.addEventListener("click", function () {
      stopped = true;
      pending = false;
      haltAudio();
      releaseButtons();
      clearMarks();
      say(reader.getAttribute("data-label-stopped"));
    });
  }
  document.querySelectorAll("[data-play]").forEach(function (button) {
    button.addEventListener("click", function () {
      var node = document.getElementById(button.getAttribute("data-play"));
      if (node) playNodes([node], button);
    });
  });

  function wrapWords(el) {
    var text = el.textContent || "";
    el.textContent = "";
    var pattern = /\s+|[\u0E40-\u0E44]?[\u0E01-\u0E2E][\u0E31-\u0E3A\u0E47-\u0E4E]*|[^\s]+/g;
    var match;
    while ((match = pattern.exec(text))) {
      if (/^\s+$/.test(match[0])) {
        el.appendChild(document.createTextNode(match[0]));
      } else {
        var span = document.createElement("span");
        span.className = "word";
        span.dataset.start = String(match.index);
        span.textContent = match[0];
        el.appendChild(span);
      }
    }
  }
})();
