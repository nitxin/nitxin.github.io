// static/js/script.js

document.addEventListener("DOMContentLoaded", function () {
  const form = document.querySelector("form");

  if (form && form.action.includes("faculty")) {
    form.addEventListener("submit", function (e) {
      const confirmed = confirm("Are you sure you want to update student clearance status?");
      if (!confirmed) {
        e.preventDefault();
      }
    });
  }
});
