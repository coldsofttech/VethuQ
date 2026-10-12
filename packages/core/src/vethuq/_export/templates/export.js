(function () {
  document.body.classList.add("js");
  var details = function () { return document.querySelectorAll("details.row"); };

  // A page filters as one block, or - with several tables - each `[data-scope]` on its own.
  function setup(root) {
    var items = Array.prototype.slice.call(root.querySelectorAll("[data-facets]"));
    var inputs = Array.prototype.slice.call(root.querySelectorAll("input[data-facet]"));
    var status = root.querySelector(".facet-status");
    var clear = root.querySelector("[data-clear]");

    items.forEach(function (item) { item.facets = JSON.parse(item.getAttribute("data-facets")); });

    function selected() {
      var chosen = {};
      inputs.forEach(function (input) {
        if (input.checked) { (chosen[input.getAttribute("data-facet")] ||= []).push(input.value); }
      });
      return chosen;
    }

    function apply() {
      var chosen = selected(), keys = Object.keys(chosen), shown = 0, band = false;
      items.forEach(function (item) {
        var ok = keys.every(function (key) {
          var have = item.facets[key] || [];
          return chosen[key].some(function (value) { return have.indexOf(value) >= 0; });
        });
        item.hidden = !ok;
        item.classList.remove("alt");
        if (ok) { shown += 1; if (band) { item.classList.add("alt"); } band = !band; }
      });
      root.querySelectorAll("details.facet").forEach(function (facet) {
        var n = facet.querySelectorAll("input:checked").length;
        facet.querySelector(".n").textContent = n ? n : "";
        facet.classList.toggle("active", n > 0);
      });
      if (status) { status.textContent = "Showing " + shown + " of " + items.length; }
      if (clear) { clear.hidden = keys.length === 0; }
    }

    inputs.forEach(function (input) { input.addEventListener("change", apply); });
    if (clear) {
      clear.addEventListener("click", function () {
        inputs.forEach(function (input) { input.checked = false; });
        apply();
      });
    }
    apply();
  }

  var scopes = document.querySelectorAll("[data-scope]");
  if (scopes.length) {
    scopes.forEach(setup);
  } else {
    setup(document);
  }
  document.addEventListener("click", function (event) {
    document.querySelectorAll("details.facet[open]").forEach(function (facet) {
      if (!facet.contains(event.target)) { facet.open = false; }
    });
  });
  document.querySelectorAll("[data-expand]").forEach(function (button) {
    button.addEventListener("click", function () {
      var open = button.getAttribute("data-expand") === "all";
      details().forEach(function (row) { row.open = open; });
    });
  });
  window.addEventListener("beforeprint", function () {
    details().forEach(function (row) { row.open = true; });
  });
})();
