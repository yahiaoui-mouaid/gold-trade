(function () {
  "use strict";

  function fire(el) { el.dispatchEvent(new Event("change", { bubbles: true })); }

  function addRow(button) {
    var template = document.getElementById(button.dataset.template);
    var target = document.getElementById(button.dataset.target);
    target.appendChild(template.content.cloneNode(true));
    fire(target);
  }

  function removeRow(button) {
    var row = button.closest("[data-row]");
    var list = row.parentElement;
    if (list.querySelectorAll("[data-row]").length > 1) {
      row.remove();
    } else {
      row.querySelectorAll("input").forEach(function (i) { i.value = ""; });
    }
    fire(list);
  }

  function recoveryText() { return document.getElementById("recovery-text").textContent; }

  function copyText(button) {
    navigator.clipboard.writeText(recoveryText()).then(function () {
      button.textContent = button.dataset.done;
    });
  }

  function downloadText() {
    var name = "gold-volt-recovery.txt";
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.save_text(name, recoveryText());
      return;
    }
    var url = URL.createObjectURL(new Blob([recoveryText()], { type: "text/plain" }));
    var link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function printPage(button) {
    document.body.classList.toggle("roll", button.dataset.size === "roll");
    window.print();
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-action]");
    if (!button) { return; }
    var action = button.dataset.action;
    if (action === "add-row") { addRow(button); }
    else if (action === "remove-row") { removeRow(button); }
    else if (action === "copy") { copyText(button); }
    else if (action === "download") { downloadText(); }
    else if (action === "print") { printPage(button); }
  });

  // Enter inside the search or new-person fields must not post the operation.
  document.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && event.target.matches("[data-no-submit]")) { event.preventDefault(); }
  });

  // Payment screen: show only the fields for the chosen type.
  function syncPayment() {
    var form = document.getElementById("payment-form");
    if (!form) { return; }
    var asset = (form.querySelector("[name=asset]:checked") || {}).value;
    var direction = (form.querySelector("[name=direction]:checked") || {}).value;
    form.querySelectorAll("[data-when]").forEach(function (el) {
      var rule = el.dataset.when;
      el.hidden = !(rule === asset || rule === asset + "-" + direction);
    });
  }
  document.addEventListener("change", syncPayment);
  document.addEventListener("DOMContentLoaded", syncPayment);

  // Idle lock: reload when the session has expired so the screen never stays open.
  var idle = Number(document.body && document.body.dataset.idleSeconds);
  if (idle) {
    var timer;
    var reset = function () {
      clearTimeout(timer);
      timer = setTimeout(function () { window.location.reload(); }, (idle + 2) * 1000);
    };
    reset();
    document.body.addEventListener("htmx:afterRequest", reset);
  }
})();
