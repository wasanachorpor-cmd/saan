(function () {
  try {
    var hasContrast = /(?:^|; )saan_contrast=/.test(document.cookie);
    if (!hasContrast && window.matchMedia("(prefers-contrast: more)").matches) {
      document.documentElement.setAttribute("data-contrast", "high");
      document.cookie = "saan_contrast=high; Path=/; Max-Age=31536000; SameSite=Lax";
    }
  } catch (err) {
    /* Preference detection is optional. */
  }
})();
