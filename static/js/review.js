(function () {
  var image = document.getElementById("page-image");
  var form = document.getElementById("correct-form");
  var field = document.getElementById("corrected");
  if (image) {
    var levels = ["1", "2", "3", "4"];
    function setZoom(level) {
      image.setAttribute("data-zoom", level);
    }
    var zoomIn = document.getElementById("zoom-in");
    var zoomOut = document.getElementById("zoom-out");
    var zoomReset = document.getElementById("zoom-reset");
    if (zoomIn) {
      zoomIn.addEventListener("click", function () {
        var index = levels.indexOf(image.getAttribute("data-zoom") || "1");
        setZoom(levels[Math.min(levels.length - 1, index + 1)]);
      });
    }
    if (zoomOut) {
      zoomOut.addEventListener("click", function () {
        var index = levels.indexOf(image.getAttribute("data-zoom") || "1");
        setZoom(levels[Math.max(0, index - 1)]);
      });
    }
    if (zoomReset) zoomReset.addEventListener("click", function () { setZoom("1"); });
  }
  if (form && field) {
    field.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        if (form.requestSubmit) form.requestSubmit();
        else form.submit();
      }
    });
  }
})();
