(function () {
  var ctx = null;
  var node = null;
  var buffer = null;
  var offset = 0;
  var started = 0;
  var playing = false;
  var generation = 0;
  var playId = 0;
  var endHandler = null;
  var clips = [];

  function context() {
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!ctx) ctx = new AC();
    if (ctx.state === "suspended") {
      var pending = ctx.resume();
      if (pending && pending.catch) pending.catch(function () {});
    }
    return ctx;
  }

  function clearNode() {
    generation += 1;
    if (!node) {
      playing = false;
      return;
    }
    node.onended = null;
    try { node.stop(); } catch (e) {}
    try { node.disconnect(); } catch (e) {}
    node = null;
    playing = false;
  }

  function begin(from, done) {
    var audio = context();
    if (!audio || !buffer) return;
    clearNode();
    var mine = generation;
    endHandler = done || null;
    node = audio.createBufferSource();
    node.buffer = buffer;
    node.connect(audio.destination);
    node.onended = function () {
      if (mine !== generation) return;
      playing = false;
      offset = 0;
      buffer = null;
      var cb = endHandler;
      endHandler = null;
      if (cb) cb();
    };
    var startAt = Math.min(Math.max(from, 0), Math.max(0, buffer.duration - 0.05));
    offset = startAt;
    started = audio.currentTime;
    playing = true;
    node.start(0, startAt);
  }

  window.saanAudio = {
    unlock: context,
    arm: function () {
      var audio = context();
      if (!audio) return;
      try {
        var silence = audio.createBuffer(1, 2205, 22050);
        var blip = audio.createBufferSource();
        blip.buffer = silence;
        blip.connect(audio.destination);
        blip.start(0);
      } catch (e) {}
    },
    playing: function () { return playing; },
    paused: function () { return !playing && !!buffer && offset > 0; },
    position: function () {
      if (!buffer) return 0;
      if (!playing || !ctx) return offset;
      return Math.min(buffer.duration, offset + (ctx.currentTime - started));
    },
    duration: function () { return buffer ? buffer.duration : 0; },
    stop: function () {
      playId += 1;
      endHandler = null;
      clearNode();
      buffer = null;
      offset = 0;
    },
    pause: function () {
      if (!playing || !ctx || !buffer) return;
      offset = Math.min(buffer.duration, offset + (ctx.currentTime - started));
      var keep = endHandler;
      endHandler = null;
      clearNode();
      endHandler = keep;
    },
    resume: function () {
      if (playing || !buffer) return false;
      begin(offset, endHandler);
      return true;
    },
    play: function (arrayBuffer, done) {
      var audio = context();
      if (!audio) return Promise.reject(new Error("no-audio"));
      var id = ++playId;
      endHandler = null;
      clearNode();
      buffer = null;
      offset = 0;
      return audio.decodeAudioData(arrayBuffer.slice(0)).then(function (decoded) {
        if (id !== playId) return;
        buffer = decoded;
        begin(0, done);
      });
    },
    decode: function (arrayBuffer) {
      var audio = context();
      if (!audio) return Promise.reject(new Error("no-audio"));
      return audio.decodeAudioData(arrayBuffer.slice(0));
    },
    playDecoded: function (decoded, done) {
      var audio = context();
      if (!audio || !decoded) return false;
      playId += 1;
      endHandler = null;
      clearNode();
      buffer = decoded;
      offset = 0;
      begin(0, done);
      return true;
    },
    remember: function (key, bytes) {
      for (var i = 0; i < clips.length; i++) {
        if (clips[i].key === key) {
          clips[i].bytes = bytes;
          return;
        }
      }
      clips.push({ key: key, bytes: bytes });
      if (clips.length > 48) clips.shift();
    },
    recall: function (key) {
      for (var i = 0; i < clips.length; i++) {
        if (clips[i].key === key) return clips[i].bytes;
      }
      return null;
    }
  };

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

  function acronymAt(text, index) {
    var match = /^S\s*\.?\s*A\s*\.?\s*A\s*\.?\s*N/i.exec(text.slice(index));
    return match ? match[0] : "";
  }

  function pushPieces(parts, value, lang, from, limit, fallback) {
    var trimmed = value.replace(/^\s+/, "");
    var core = trimmed.replace(/\s+$/, "");
    if (!core) return;
    var base = from + (value.length - trimmed.length);
    var rest = core;
    var offset = 0;
    while (rest.length > limit) {
      var window = rest.slice(0, limit);
      var cut = -1;
      [".", "?", "!", "\n", "。", "？", "！"].forEach(function (mark) {
        var at = window.lastIndexOf(mark);
        if (at >= 24) cut = Math.max(cut, at + 1);
      });
      if (cut < 0) {
        cut = window.lastIndexOf(" ");
        if (cut < Math.floor(limit * 0.4)) cut = limit;
      }
      var piece = rest.slice(0, cut).trim();
      if (!piece) break;
      var at = core.indexOf(piece, offset);
      if (at < 0) at = offset;
      parts.push({ text: piece, lang: lang || fallback || "th-TH", start: base + at });
      offset = at + piece.length;
      rest = rest.slice(cut).trim();
    }
    if (rest) {
      var tailAt = core.indexOf(rest, offset);
      if (tailAt < 0) tailAt = offset;
      parts.push({ text: rest, lang: lang || fallback || "th-TH", start: base + tailAt });
    }
  }

  window.saanParts = function (text, maxLen, fallback) {
    var limit = maxLen || 140;
    var parts = [];
    var buf = "";
    var kind = "";
    var start = 0;
    for (var i = 0; i < text.length; i++) {
      var next = scriptOf(text.charAt(i), kind);
      if (kind === "th-TH" && next === "en-US") {
        var acronym = acronymAt(text, i);
        if (acronym) {
          buf += acronym;
          i += acronym.length - 1;
          continue;
        }
      }
      if (!buf) start = i;
      if (!next || !kind || next === kind) {
        buf += text.charAt(i);
        if (next) kind = next;
      } else {
        pushPieces(parts, buf, kind, start, limit, fallback);
        buf = text.charAt(i);
        kind = next;
        start = i;
      }
    }
    pushPieces(parts, buf, kind, start, limit, fallback);
    return parts;
  };

  function leftPad(value) {
    var count = 0;
    while (count < value.length && /\s/.test(value.charAt(count))) count += 1;
    return count;
  }

  window.saanLead = function (parts) {
    if (!parts.length || parts[0].text.length <= 72) return parts;
    var first = parts[0];
    var sample = first.text.slice(0, 96);
    var cut = -1;
    [".", "?", "!", "\n", "。", "？", "！"].forEach(function (mark) {
      var at = sample.lastIndexOf(mark);
      if (at >= 16) cut = Math.max(cut, at + 1);
    });
    if (cut < 0) {
      var space = sample.lastIndexOf(" ");
      cut = space >= 20 ? space : 72;
    }
    if (cut >= first.text.length) return parts;
    var rawHead = first.text.slice(0, cut);
    var rawTail = first.text.slice(cut);
    var head = rawHead.replace(/^\s+|\s+$/g, "");
    var tail = rawTail.replace(/^\s+|\s+$/g, "");
    if (!head || !tail) return parts;
    return [
      Object.assign({}, first, { text: head, start: first.start + leftPad(rawHead) }),
      Object.assign({}, first, { text: tail, start: first.start + cut + leftPad(rawTail) })
    ].concat(parts.slice(1));
  };

  function clipHalves(part) {
    var text = part.text || "";
    if (text.length < 16) return null;
    var mid = Math.floor(text.length / 2);
    var cut = text.lastIndexOf(" ", mid + 10);
    if (cut < 10) cut = mid;
    var left = text.slice(0, cut).trim();
    var right = text.slice(cut).trim();
    if (!left || !right || left === text || right === text) return null;
    return [
      Object.assign({}, part, { text: left, tries: 0 }),
      Object.assign({}, part, { text: right, start: (part.start || 0) + (text.length - right.length), tries: 0 })
    ];
  }

  window.saanSequence = function (options) {
    var index = 0;
    var ahead = {};
    var heard = false;
    var announced = false;
    function alive() {
      return !options.alive || options.alive();
    }
    function load(i) {
      var part = options.parts[i];
      if (!part) return Promise.reject(new Error("missing"));
      if (!ahead[i]) {
        ahead[i] = Promise.resolve().then(function () {
          return options.fetch(part);
        }).then(function (bytes) {
          if (!window.saanAudio) throw new Error("no-audio");
          return window.saanAudio.decode(bytes);
        });
      }
      return ahead[i];
    }
    function warm(i) {
      for (var n = 0; n < 2; n++) {
        if (i + n < options.parts.length) load(i + n).catch(function () {});
      }
    }
    function step() {
      if (!alive()) return;
      if (index >= options.parts.length) {
        if (options.onDone) options.onDone(heard);
        return;
      }
      var current = index;
      var part = options.parts[current];
      warm(current);
      load(current).then(function (decoded) {
        if (!alive() || index !== current) return;
        if (!decoded) throw new Error("empty");
        var moved = false;
        var cleanup = null;
        function finish() {
          if (moved || !alive()) return;
          moved = true;
          if (cleanup) cleanup();
          index = current + 1;
          step();
        }
        var started = window.saanAudio.playDecoded(decoded, finish);
        if (!started) throw new Error("no-audio");
        heard = true;
        if (!announced) {
          announced = true;
          if (options.onFirst) options.onFirst();
        }
        try {
          cleanup = options.onPlay ? options.onPlay(part) : null;
        } catch (e) {}
        window.setTimeout(finish, Math.ceil(((decoded.duration || 1) + 1.4) * 1000));
      }).catch(function () {
        if (!alive() || index !== current) return;
        delete ahead[current];
        var tries = part.tries || 0;
        if (tries < 2) {
          part.tries = tries + 1;
          step();
          return;
        }
        var pieces = clipHalves(part);
        if (pieces) {
          options.parts.splice(current, 1, pieces[0], pieces[1]);
          ahead = {};
          step();
          return;
        }
        index = current + 1;
        step();
      });
    }
    step();
  };
})();
