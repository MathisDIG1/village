(function () {
  var target = new Date("2026-09-06T10:00:00+02:00").getTime();
  var nodes = {
    days: document.getElementById("days"),
    hours: document.getElementById("hours"),
    minutes: document.getElementById("minutes"),
    seconds: document.getElementById("seconds")
  };

  function padless(value) {
    return String(Math.max(0, Math.floor(value)));
  }

  function tick() {
    var now = Date.now();
    var distance = Math.max(0, target - now);
    var totalSeconds = Math.floor(distance / 1000);

    nodes.days.textContent = padless(totalSeconds / 86400);
    nodes.hours.textContent = padless((totalSeconds % 86400) / 3600);
    nodes.minutes.textContent = padless((totalSeconds % 3600) / 60);
    nodes.seconds.textContent = padless(totalSeconds % 60);
  }

  tick();
  window.setInterval(tick, 1000);

  function loadAcceptedRegistrations() {
    var list = document.getElementById("car-list");
    var count = document.getElementById("registration-count");
    if (!list || !count || !window.fetch) return;

    fetch("/api/registrations")
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (!data) return;
        count.textContent = String(data.count || 0);
        if (!data.registrations || data.registrations.length === 0) {
          list.innerHTML = '<p class="empty-state">No accepted registrations yet.</p>';
          return;
        }
        list.innerHTML = data.registrations.map(function (registration) {
          var photo = registration.photo_url || "";
          var label = [registration.car_year, registration.car_make, registration.car_model].filter(Boolean).join(" ");
          return '<a href="' + photo + '"><img src="' + photo + '" alt="' + label.replace(/"/g, "&quot;") + '"></a>';
        }).join("");
      })
      .catch(function () {});
  }

  loadAcceptedRegistrations();
})();
