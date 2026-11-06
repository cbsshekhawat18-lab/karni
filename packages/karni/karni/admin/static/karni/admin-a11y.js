/*
 * Landmarks and names unfold's pages lack, so a screen reader can jump to the
 * main content and name each select. Runs on every admin page; touches only
 * attributes, never layout. Remove "karni.admin.theme.a11y_script" from
 * UNFOLD["SCRIPTS"] to turn it off.
 */
(function () {
  function landmarks() {
    var content = document.getElementById("content");
    var main = document.getElementById("main");
    if (!content || !main) return;
    var body = content.parentElement;
    if (body && !document.querySelector("main,[role=main]")) {
      body.setAttribute("role", "main");
    }
    Array.prototype.forEach.call(main.children, function (child) {
      if (child === body || child.getAttribute("role")) return;
      if (child.querySelector("[id=submit-row],#changelist-actions,.pagination,.karni-pagination") || child.tagName === "FOOTER") {
        child.setAttribute("role", "contentinfo");
      } else if (child === main.firstElementChild) {
        child.setAttribute("role", "banner");
      } else {
        child.setAttribute("role", "region");
        child.setAttribute("aria-label", "Messages");
      }
    });
  }
  function names() {
    Array.prototype.forEach.call(
      document.querySelectorAll(
        ".select2-selection[role=combobox]:not([aria-label]),.select2-selection__rendered[role=textbox]:not([aria-label])"
      ),
      function (box) {
        var container = box.closest(".select2-container");
        var select = container && container.previousElementSibling;
        var label = select && select.id && document.querySelector('label[for="' + select.id + '"]');
        box.setAttribute("aria-label", (label && label.textContent.trim()) || (select && select.name) || "Choose");
      }
    );
  }
  function sorting() {
    Array.prototype.forEach.call(document.querySelectorAll("#result_list thead th.sorted"), function (th) {
      th.setAttribute("aria-sort", th.classList.contains("descending") ? "descending" : "ascending");
    });
  }
  function run() { landmarks(); names(); sorting(); }
  document.addEventListener("DOMContentLoaded", run);
  window.addEventListener("load", run);
  new MutationObserver(names).observe(document.documentElement, { childList: true, subtree: true });
})();
