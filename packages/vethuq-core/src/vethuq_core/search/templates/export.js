(function () {
  var rows = function () { return document.querySelectorAll("details.row"); };
  document.querySelectorAll("[data-expand]").forEach(function (button) {
    button.addEventListener("click", function () {
      var open = button.getAttribute("data-expand") === "all";
      rows().forEach(function (row) { row.open = open; });
    });
  });
  window.addEventListener("beforeprint", function () {
    rows().forEach(function (row) { row.open = true; });
  });
})();
