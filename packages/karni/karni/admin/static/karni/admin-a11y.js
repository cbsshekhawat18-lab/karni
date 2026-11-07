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
  function fields() {
    // select2's search box inside a multiple select has no label of its own.
    Array.prototype.forEach.call(
      document.querySelectorAll(".select2-search__field:not([aria-label]):not([aria-labelledby])"),
      function (box) {
        var container = box.closest(".select2-container");
        var select = container && container.previousElementSibling;
        var label = select && select.id && document.querySelector('label[for="' + select.id + '"]');
        box.setAttribute("aria-label", (label && label.textContent.trim()) || (select && select.name) || "Search");
      }
    );
    // the (?) icons beside a label carry a text through aria-label, which needs a role to be allowed.
    Array.prototype.forEach.call(document.querySelectorAll(".help-tooltip[aria-label]:not([role])"), function (tip) {
      tip.setAttribute("role", "img");
    });
    // a tabular inline's blank heading cells (the delete column).
    Array.prototype.forEach.call(document.querySelectorAll("table th:not([data-karni-named])"), function (th) {
      th.setAttribute("data-karni-named", "1");
      if (th.textContent.trim() || th.querySelector("input,select,button,img,svg")) return;
      var text = document.createElement("span");
      text.className = "sr-only";
      text.style.cssText = "position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap";
      text.textContent = "Actions";
      th.appendChild(text);
    });
    // a many-to-many widget's list of chosen values: say what it holds
    Array.prototype.forEach.call(document.querySelectorAll("ul.select2-selection__rendered:not([aria-label])"), function (list) {
      var li = list.querySelector(":scope > :not(li)");
      if (li) list.setAttribute("role", "presentation");
    });
  }
  function sorting() {
    Array.prototype.forEach.call(document.querySelectorAll("#result_list thead th.sorted"), function (th) {
      th.setAttribute("aria-sort", th.classList.contains("descending") ? "descending" : "ascending");
    });
  }
  function run() { landmarks(); names(); fields(); sorting(); }
  document.addEventListener("DOMContentLoaded", run);
  window.addEventListener("load", run);
  new MutationObserver(function () { names(); fields(); }).observe(document.documentElement, { childList: true, subtree: true });
})();
