const RANGE_DEFAULT = { hours: 24, label: "Last 24 hours" };
let currentRange = { ...RANGE_DEFAULT };
let tempChart = null;
let appConfig = null;
const fmtNumber = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const el = (id) => document.getElementById(id);

function roundTemp(value) {
  return Math.round(Number(value));
}

function formatTemp(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${roundTemp(value)}${unit || "°F"}`;
}

function formatDateTime(isoString) {
  if (!isoString) return "Waiting for reading";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function formatChartTick(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  if (currentRange.hours <= 72) return date.toLocaleString([], { hour: "numeric", minute: "2-digit" });
  if (currentRange.hours <= 2160) return date.toLocaleString([], { month: "short", day: "numeric" });
  return date.toLocaleString([], { month: "short", year: "2-digit" });
}

function setStatus(message) { el("statusText").textContent = message; }
function sensorByKey(key) { return appConfig?.sensors?.find((sensor) => sensor.key === key); }

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  return response.json();
}

async function loadConfig() {
  appConfig = await fetchJson("/api/config");
  const outside = sensorByKey("outside");
  const hallway = sensorByKey("hallway");
  if (outside) el("outsideEntity").textContent = outside.entity_id;
  if (hallway) el("hallwayEntity").textContent = hallway.entity_id;
}

async function loadLatest() {
  const data = await fetchJson("/api/latest");
  const readings = data.latest || [];
  const outside = readings.find((item) => item.sensor_key === "outside");
  const hallway = readings.find((item) => item.sensor_key === "hallway");
  if (outside) {
    el("outsideValue").textContent = formatTemp(outside.value, outside.unit);
    el("outsideUpdated").textContent = `Updated ${formatDateTime(outside.ts)}`;
  }
  if (hallway) {
    el("hallwayValue").textContent = formatTemp(hallway.value, hallway.unit);
    el("hallwayUpdated").textContent = `Updated ${formatDateTime(hallway.ts)}`;
  }
}

function buildDatasets(readings) {
  const outsidePoints = [];
  const hallwayPoints = [];
  for (const item of readings) {
    const point = { x: item.ts, y: roundTemp(item.value) };
    if (item.sensor_key === "outside") outsidePoints.push(point);
    if (item.sensor_key === "hallway") hallwayPoints.push(point);
  }
  return [
    { label: "Outside", data: outsidePoints, borderColor: "#38bdf8", backgroundColor: "rgba(56,189,248,.14)", pointRadius: 0, pointHoverRadius: 5, borderWidth: 3, tension: .34, fill: true },
    { label: "Hallway", data: hallwayPoints, borderColor: "#fb923c", backgroundColor: "rgba(251,146,60,.10)", pointRadius: 0, pointHoverRadius: 5, borderWidth: 3, tension: .34, fill: true },
  ];
}

function createOrUpdateChart(readings) {
  const config = {
    type: "line",
    data: { datasets: buildDatasets(readings) },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { labels: { color: "#cbd5e1", boxWidth: 10, boxHeight: 10, usePointStyle: true, font: { weight: "bold", size: 11 } } },
        tooltip: {
          backgroundColor: "rgba(2,6,23,.94)", borderColor: "rgba(148,163,184,.25)", borderWidth: 1, titleColor: "#f8fafc", bodyColor: "#cbd5e1", padding: 12,
          callbacks: { title: (items) => formatDateTime(items?.[0]?.raw?.x), label: (item) => `${item.dataset.label}: ${roundTemp(item.parsed.y)}°` }
        }
      },
      scales: {
        x: { type: "time", grid: { color: "rgba(148,163,184,.08)" }, ticks: { color: "#94a3b8", maxRotation: 0, autoSkip: true, maxTicksLimit: 6, callback: (value) => formatChartTick(value) } },
        y: { grid: { color: "rgba(148,163,184,.10)" }, ticks: { color: "#94a3b8", precision: 0, maxTicksLimit: 6, callback: (value) => `${Math.round(value)}°` } }
      }
    }
  };
  if (!tempChart) tempChart = new Chart(el("tempChart"), config);
  else { tempChart.data.datasets = config.data.datasets; tempChart.options = config.options; tempChart.update(); }
}

async function loadHistory() {
  el("rangeTitle").textContent = currentRange.label;
  el("chartMeta").textContent = "Loading chart data...";
  const data = await fetchJson(`/api/history?hours=${currentRange.hours}`);
  const readings = data.readings || [];
  createOrUpdateChart(readings);
  const sampleText = readings.length === 1 ? "point" : "points";
  const bucketMinutes = Math.round((data.bucket_seconds || 0) / 60);
  const bucketText = bucketMinutes >= 60 ? `${Math.round(bucketMinutes / 60)} hour average` : `${bucketMinutes} minute average`;
  el("chartMeta").textContent = `${readings.length} ${sampleText} shown · ${bucketText}`;
}

async function refreshAll() {
  try { await loadLatest(); await loadHistory(); setStatus(`Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`); }
  catch (error) { console.error(error); setStatus(`Error: ${error.message}`); }
}

async function pollNow() {
  const button = el("pollNowBtn");
  button.disabled = true; button.textContent = "Polling..."; setStatus("Polling Home Assistant...");
  try { await fetchJson("/api/poll", { method: "POST" }); await refreshAll(); setStatus("Manual poll complete"); }
  catch (error) { console.error(error); setStatus(`Poll failed: ${error.message}`); }
  finally { button.disabled = false; button.textContent = "Poll Now"; }
}

function setupRangeButtons() {
  document.querySelectorAll(".range-button").forEach((button) => {
    button.addEventListener("click", async () => {
      document.querySelectorAll(".range-button").forEach((btn) => btn.classList.remove("active"));
      button.classList.add("active");
      currentRange = { hours: Number(button.dataset.hours), label: button.dataset.label };
      await loadHistory();
    });
  });
}

async function init() {
  setupRangeButtons();
  el("refreshBtn").addEventListener("click", refreshAll);
  el("pollNowBtn").addEventListener("click", pollNow);
  try { await loadConfig(); await refreshAll(); } catch (error) { console.error(error); setStatus(`Startup error: ${error.message}`); }
  setInterval(loadLatest, 60000);
  setInterval(loadHistory, 300000);
}

init();
