(function () {
  var board = document.querySelector("[data-queue]");
  if (!board || !window.fetch) return;
  window.setInterval(function () {
    fetch("/api/queue", { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) return null;
        return response.json();
      })
      .then(function (data) {
        if (!data) return;
        if (String(data.count) === board.getAttribute("data-count")) return;
        var live = document.getElementById("live");
        var template = board.getAttribute("data-updated") || "";
        if (live) live.textContent = template.replace("{n}", String(data.count));
      })
      .catch(function () {});
  }, 12000);
})();
