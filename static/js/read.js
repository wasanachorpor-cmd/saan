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

  function submitForm(form) {
    if (!form || !window.fetch) {
      form.submit();
      return;
    }
    var data = new FormData(form);
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
    cameraForm.addEventListener("submit", function (event) {
      event.preventDefault();
      submitForm(cameraForm);
    });
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
    if (window.EventSource) {
      var source = new EventSource("/api/documents/" + reader.getAttribute("data-doc-id") + "/events");
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
  }

  document.querySelectorAll("[data-snippet-text]").forEach(wrapWords);

  var rate = document.getElementById("rate");
  var rateOut = document.getElementById("rate-out");
  var voice = document.getElementById("voice");
  var playAll = document.getElementById("play-all");
  var pauseBtn = document.getElementById("pause");
  var stopBtn = document.getElementById("stop");
  var chain = [];
  var chainIndex = 0;
  var stopped = true;
  var announced = false;
  var currentAudio = null;
  var audioToken = 0;

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

  function scriptOf(ch, current) {
    var code = ch.charCodeAt(0);
    if (code >= 0x0e00 && code <= 0x0e7f) return "th-TH";
    if ((code >= 65 && code <= 90) || (code >= 97 && code <= 122)) return "en-US";
    if (code >= 0x0400 && code <= 0x04ff) return "ru-RU";
    if (code >= 0x0600 && code <= 0x06ff) return "ar-SA";
    if (code >= 0x0590 && code <= 0x05ff) return "he-IL";
    if (code >= 0x0900 && code <= 0x097f) return "hi-IN";
    if ((code >= 0x3040 && code <= 0x30ff) || (code >= 0x31f0 && code <= 0x31ff)) return "ja-JP";
    if (code >= 0xac00 && code <= 0xd7af) return "ko-KR";
    if (code >= 0x4e00 && code <= 0x9fff) return current === "ja-JP" ? "ja-JP" : "zh-CN";
    return "";
  }

  function segmentText(text) {
    var parts = [];
    var buf = "";
    var kind = "";
    var start = 0;
    function push(value, lang, from) {
      var trimmed = value.replace(/^\s+/, "");
      var core = trimmed.replace(/\s+$/, "");
      if (!core) return;
      parts.push({ text: core, lang: lang || "en-US", start: from + (value.length - trimmed.length) });
    }
    for (var i = 0; i < text.length; i++) {
      var next = scriptOf(text.charAt(i), kind);
      if (!buf) start = i;
      if (!next || !kind || next === kind) {
        buf += text.charAt(i);
        if (next) kind = next;
      } else {
        push(buf, kind, start);
        buf = text.charAt(i);
        kind = next;
        start = i;
      }
    }
    push(buf, kind, start);
    return parts;
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
      return item.lang.toLowerCase().replace("_", "-").indexOf(prefix) === 0;
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

  function speakNext() {
    if (stopped) return;
    if (chainIndex >= chain.length) {
      stopped = true;
      clearMarks();
      say(reader.getAttribute("data-label-finished"));
      return;
    }
    var job = chain[chainIndex++];
    var chosen = window.speechSynthesis ? voiceFor(job.lang) : null;
    if (chosen) speakLocal(job, chosen);
    else speakRemote(job);
  }

  function showJob(job) {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    job.node.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
    if (!announced) {
      announced = true;
      say(reader.getAttribute("data-label-speaking"));
    }
  }

  function speakLocal(job, chosen) {
    var utterance = new SpeechSynthesisUtterance(job.text);
    utterance.lang = job.lang;
    utterance.rate = rate ? Number(rate.value) : 1;
    utterance.voice = chosen;
    utterance.onstart = function () { showJob(job); };
    utterance.onboundary = function (event) {
      if (typeof event.charIndex === "number") highlight(job.node, job.start + event.charIndex);
    };
    utterance.onend = function () {
      if (!stopped) speakNext();
    };
    utterance.onerror = function (event) {
      if (event.error === "interrupted" || event.error === "canceled") return;
      speakRemote(job);
    };
    window.speechSynthesis.speak(utterance);
  }

  function speakRemote(job) {
    var token = ++audioToken;
    fetch("/api/speak", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "audio/mpeg",
        "X-CSRF": reader.getAttribute("data-csrf") || ""
      },
      body: JSON.stringify({
        text: job.text,
        lang: job.lang,
        rate: rate ? Number(rate.value) : 1
      })
    }).then(function (response) {
      if (!response.ok) throw new Error("speak");
      return response.blob();
    }).then(function (blob) {
      if (stopped || token !== audioToken) return;
      var url = URL.createObjectURL(blob);
      var audio = new Audio(url);
      currentAudio = audio;
      audio.onended = function () {
        URL.revokeObjectURL(url);
        if (currentAudio === audio) currentAudio = null;
        if (!stopped) speakNext();
      };
      audio.onerror = function () {
        URL.revokeObjectURL(url);
        if (!stopped) speakNext();
      };
      audio.ontimeupdate = function () {
        if (!audio.duration) return;
        var index = Math.floor((audio.currentTime / audio.duration) * job.text.length);
        highlight(job.node, job.start + index);
      };
      showJob(job);
      return audio.play();
    }).catch(function () {
      if (stopped || token !== audioToken) return;
      say(reader.getAttribute("data-speak-failed") || "");
      speakNext();
    });
  }

  function haltAudio() {
    audioToken += 1;
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  function jobsFor(nodes) {
    var jobs = [];
    nodes.forEach(function (node) {
      segmentText(node.textContent || "").forEach(function (part) {
        jobs.push({ node: node, text: part.text, lang: part.lang, start: part.start });
      });
    });
    return jobs;
  }

  function playNodes(nodes) {
    haltAudio();
    chain = jobsFor(nodes);
    chainIndex = 0;
    stopped = false;
    announced = false;
    clearMarks();
    speakNext();
  }

  if (playAll) {
    playAll.addEventListener("click", function () {
      if (currentAudio && currentAudio.paused) {
        currentAudio.play();
        say(reader.getAttribute("data-label-speaking"));
        return;
      }
      if (window.speechSynthesis && window.speechSynthesis.paused) {
        window.speechSynthesis.resume();
        say(reader.getAttribute("data-label-speaking"));
        return;
      }
      playNodes([].slice.call(document.querySelectorAll("[data-snippet-text]")));
    });
  }
  if (pauseBtn) {
    pauseBtn.addEventListener("click", function () {
      if (currentAudio && !currentAudio.paused) {
        currentAudio.pause();
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
      haltAudio();
      clearMarks();
      say(reader.getAttribute("data-label-stopped"));
    });
  }
  document.querySelectorAll("[data-play]").forEach(function (button) {
    button.addEventListener("click", function () {
      var node = document.getElementById(button.getAttribute("data-play"));
      if (node) playNodes([node]);
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
