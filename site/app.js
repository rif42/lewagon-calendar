/* global FullCalendar */
(function () {
  "use strict";

  var DATA_URL = "./events.json"; // baked next to index.html by deploy.yml
  var allEvents = [];
  var calendar = null;

  var areaSelect = document.getElementById("filter-area");
  var categorySelect = document.getElementById("filter-category");
  var costSelect = document.getElementById("filter-cost");
  var dialog = document.getElementById("event-dialog");
  var isMobile = window.matchMedia("(max-width: 40rem)").matches;
  var filterDetails = document.getElementById("filter-details");
  if (filterDetails && !isMobile) filterDetails.open = true;

  function matchesFilters(fcEvent) {
    var p = fcEvent.extendedProps || {};
    if (areaSelect.value && p.area !== areaSelect.value) return false;
    if (categorySelect.value && p.category !== categorySelect.value) return false;
    if (costSelect.value === "free" && p.free !== true) return false;
    if (costSelect.value === "paid" && p.free !== false) return false;
    return true;
  }

  function catSlug(category) {
    return "cat-" + String(category || "other").toLowerCase().replace(/[^a-z]+/g, "-").replace(/^-|-$/g, "") || "cat-other";
  }

  function toFcEvent(ev) {
    return {
      id: ev.uid,
      title: ev.name,
      classNames: [catSlug(ev.category)],
      start: ev.start_utc,
      end: ev.finish_utc || undefined,
      extendedProps: {
        area: ev.area,
        category: ev.category,
        free: ev.free,
        cost: ev.cost,
        location: ev.location,
        description: ev.description,
        source_url: ev.source_url,
        source: ev.source,
      },
    };
  }

  function gcalDate(utcString) {
    // "2026-10-03T10:00:00Z" -> "20261003T100000Z"
    return utcString.replace(/[-:]/g, "").replace(/\.\d+/, "");
  }

  function gcalDay(utcString) {
    // "2026-10-14T00:00:00Z" -> "20261014"
    return gcalDate(utcString).slice(0, 8);
  }

  function isMidnightUtc(utcString) {
    return (/T00:00:00(\.\d+)?Z$/).test(utcString || "");
  }

  function isAllDay(ev) {
    if (!ev.start_utc || !isMidnightUtc(ev.start_utc)) return false;
    if (!ev.finish_utc) return true;
    if (!isMidnightUtc(ev.finish_utc)) return false;
    var ms = Date.parse(ev.finish_utc) - Date.parse(ev.start_utc);
    return ms > 0 && ms % 86400000 === 0;
  }

  function shiftUtc(utcString, ms) {
    return new Date(Date.parse(utcString) + ms).toISOString().replace((/\.\d+Z$/), "Z");
  }

  function buildGcalLink(ev) {
    var dates;
    if (isAllDay(ev)) {
      var startDay = gcalDay(ev.start_utc);
      var endDay = ev.finish_utc ? gcalDay(ev.finish_utc) : gcalDay(shiftUtc(ev.start_utc, 86400000));
      if (endDay <= startDay) endDay = gcalDay(shiftUtc(ev.start_utc, 86400000));
      dates = startDay + "/" + endDay;
    } else {
      var endUtc = ev.finish_utc || shiftUtc(ev.start_utc, 3600000);
      if (Date.parse(endUtc) <= Date.parse(ev.start_utc)) endUtc = shiftUtc(ev.start_utc, 3600000);
      dates = gcalDate(ev.start_utc) + "/" + gcalDate(endUtc);
    }
    var params = new URLSearchParams({
      action: "TEMPLATE",
      text: ev.name,
      dates: dates,
      details: (ev.description || "") + "\n\nSource: " + (ev.source_url || "") + "\nPlease verify with the organizer before attending.",
      location: ev.location || "",
    });
    return "https://calendar.google.com/calendar/render?" + params.toString();
  }

  function fmtRange(startUtc, finishUtc) {
    var opts = {
      weekday: "short",
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    };
    var out = new Date(startUtc).toLocaleString(undefined, opts);
    if (finishUtc) out += " – " + new Date(finishUtc).toLocaleString(undefined, opts);
    return out;
  }

  function openDialog(ev) {
    document.getElementById("event-title").textContent = ev.name;
    document.getElementById("event-time").textContent = fmtRange(ev.start_utc, ev.finish_utc);
    document.getElementById("event-location").textContent = ev.location || "—";
    document.getElementById("event-area").textContent = ev.area || "—";
    document.getElementById("event-category").textContent = ev.category || "—";
    document.getElementById("event-cost").textContent =
      ev.cost != null && ev.cost !== "" ? String(ev.cost) + (ev.free ? " (free)" : "") : ev.free ? "Free" : "—";
    document.getElementById("event-description").textContent = ev.description || "";
    var sourceLink = document.getElementById("event-source");
    sourceLink.href = ev.source_url || "https://example.com/";
    var gcalLink = document.getElementById("event-gcal");
    gcalLink.href = buildGcalLink(ev);
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  function visibleEvents() {
    return allEvents.map(toFcEvent).filter(matchesFilters);
  }

  function rerender() {
    if (!calendar) return;
    calendar.removeAllEvents();
    calendar.addEventSource(visibleEvents());
  }

  [areaSelect, categorySelect, costSelect].forEach(function (sel) {
    sel.addEventListener("change", rerender);
  });

  fetch(DATA_URL)
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (data) {
      allEvents = Array.isArray(data) ? data : [];
      var firstDate = allEvents.map(function (e) { return (e.start_utc || "").slice(0, 10); }).filter(Boolean).sort()[0];
      var el = document.getElementById("calendar");
      calendar = new FullCalendar.Calendar(el, {
        initialView: isMobile ? "listWeek" : "timeGridWeek",
        initialDate: firstDate,
        headerToolbar: {
          left: "prev,next today",
          center: "title",
          right: "timeGridWeek,listWeek,dayGridMonth",
        },
        buttonText: { week: "Week", month: "Month", list: "List" },
        views: { timeGridWeek: { buttonText: "Week" }, dayGridMonth: { buttonText: "Month" }, listWeek: { buttonText: "List" } },
        aspectRatio: isMobile ? 0.6 : 1.35,
        dayMaxEvents: isMobile ? 3 : true,
        nowIndicator: true,
        events: visibleEvents(),
        eventClick: function (info) {
          info.jsEvent.preventDefault();
          var uid = info.event.id;
          var raw = allEvents.find(function (e) { return e.uid === uid; });
          if (raw) openDialog(raw);
        },
      });
      calendar.render();
    })
    .catch(function (err) {
      var box = document.getElementById("load-error");
      box.hidden = false;
      box.textContent = "Could not load " + DATA_URL + ": " + err.message;
    });
})();
