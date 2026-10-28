"use strict";
const $ = (s) => document.querySelector(s);
let config = null;
let currentId = null;
let currentJob = null;
let built = false;
let timer = null;
let edits = {};

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}

const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function statusText(j) {
  if (j.status === "analyzing") return `Analysing: ${j.stage} ${Math.round(j.progress * 100)}%`;
  if (j.status === "rendering") return `Rendering: ${j.stage} ${Math.round(j.progress * 100)}%`;
  if (j.status === "error") return `Error: ${j.error}`;
  return "Ready";
}

async function showList() {
  stopPoll();
  currentId = null;
  $("#view-job").hidden = true;
  $("#view-list").hidden = false;
  const jobs = await api("/api/jobs");
  const body = $("#jobs tbody");
  body.innerHTML = "";
  for (const j of jobs) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(j.name)}</td><td class="${j.status === "error" ? "error" : ""}">${esc(statusText(j))}</td>` +
      `<td><a href="#/job/${j.id}">Open</a></td>`;
    body.appendChild(tr);
  }
  $("#empty").hidden = jobs.length > 0;
  $("#jobs").hidden = jobs.length === 0;
  if (jobs.some((j) => j.status === "analyzing" || j.status === "rendering")) timer = setTimeout(showList, 1500);
}

async function upload(f) {
  if (!f) return;
  const msg = $("#upload-msg");
  msg.className = "muted";
  if (!f.type.startsWith("video/")) { msg.textContent = "That does not look like a video file."; msg.className = "error"; return; }
  const fd = new FormData();
  fd.append("file", f);
  fd.append("language", $("#language").value);
  msg.textContent = `Uploading ${f.name}...`;
  try {
    const j = await api("/api/jobs", { method: "POST", body: fd });
    msg.textContent = "";
    $("#file").value = "";
    location.hash = `#/job/${j.id}`;
  } catch (err) {
    msg.textContent = err.message;
    msg.className = "error";
  }
}

$("#file").addEventListener("change", (e) => upload(e.target.files[0]));
$("#drop").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#file").click(); } });
let dragDepth = 0;
const dropOn = (on) => $("#drop").classList.toggle("over", on);
window.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; if ($("#view-list").hidden === false) dropOn(true); });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; dropOn(false); } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  dropOn(false);
  if ($("#view-list").hidden === false) upload(e.dataTransfer.files[0]);
});

function stopPoll() { if (timer) { clearTimeout(timer); timer = null; } }

async function openJob(id) {
  stopPoll();
  currentId = id;
  built = false;
  $("#view-list").hidden = true;
  $("#view-job").hidden = false;
  $("#work").hidden = true;
  $("#results").hidden = true;
  await refreshJob();
}

async function refreshJob() {
  if (!currentId) return;
  let j;
  try { j = await api(`/api/jobs/${currentId}`); } catch (e) { location.hash = "#"; return; }
  currentJob = j;
  $("#job-name").textContent = j.name;
  const st = $("#job-status");
  st.textContent = statusText(j);
  st.className = j.status === "error" ? "error" : "muted";
  $("#render").disabled = j.status === "rendering";
  $("#delete").disabled = j.status === "analyzing" || j.status === "rendering";

  if (j.analysis && !built) buildWork(j);
  if (j.analysis) $("#work").hidden = false;
  renderResults(j);
  if (j.status === "analyzing" || j.status === "rendering") timer = setTimeout(refreshJob, 1000);
}

function buildWork(j) {
  built = true;
  edits = {};
  $("#preview").src = `/api/jobs/${j.id}/source`;
  const ol = $("#sentences");
  ol.innerHTML = "";
  const words = j.analysis.words;
  for (const s of j.analysis.sentences) {
    const li = document.createElement("li");
    let text = "";
    for (let k = s.a; k <= s.b; k++) text += `<button type="button" class="word" data-k="${k}">${esc(words[k])}</button> `;
    li.innerHTML = `<input type="checkbox" data-i="${s.i}" checked aria-label="Keep sentence ${s.i + 1}">` +
      `<button type="button" class="time" data-t="${s.start}">${fmt(s.start)}</button>` +
      `<span class="text">${text}</span>`;
    ol.appendChild(li);
  }
  updateSummary();
}

function selected() {
  return [...document.querySelectorAll("#sentences input:checked")].map((c) => Number(c.dataset.i));
}

function updateSummary() {
  if (!currentJob || !currentJob.analysis) return;
  const sel = new Set(selected());
  let sec = 0;
  for (const s of currentJob.analysis.sentences) if (sel.has(s.i)) sec += s.end - s.start;
  const n = Object.keys(edits).length;
  $("#summary").textContent = `${sel.size} of ${currentJob.analysis.sentences.length} selected, about ${Math.round(sec)} s` +
    (n ? `, ${n} word${n > 1 ? "s" : ""} changed` : "");
  $("#render").disabled = sel.size === 0 || (currentJob.status === "rendering");
}

function editWord(btn) {
  const k = Number(btn.dataset.k);
  const orig = currentJob.analysis.words[k];
  const core = orig.replace(/[,.?!"')]+$/, "");
  const input = document.createElement("input");
  input.type = "text";
  input.className = "word-edit";
  input.value = edits[k] ?? core;
  input.size = Math.max(4, input.value.length + 1);
  btn.replaceWith(input);
  input.focus();
  input.select();
  const done = (save) => {
    const v = input.value.trim();
    if (save && v && v !== core) edits[k] = v; else if (save) delete edits[k];
    const b = document.createElement("button");
    b.type = "button";
    b.className = "word";
    b.dataset.k = k;
    const tail = orig.slice(core.length);
    b.textContent = (edits[k] ?? core) + tail;
    b.classList.toggle("edited", k in edits);
    b.title = k in edits ? `was: ${orig}` : "";
    input.replaceWith(b);
    updateSummary();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); input.onblur = null; done(true); }
    if (e.key === "Escape") { input.onblur = null; done(false); }
  });
  input.onblur = () => done(true);
}

$("#sentences").addEventListener("change", updateSummary);
$("#sentences").addEventListener("click", (e) => {
  const w = e.target.closest(".word");
  if (w) { editWord(w); return; }
  const b = e.target.closest(".time");
  if (b) {
    e.preventDefault();
    const v = $("#preview");
    v.currentTime = Number(b.dataset.t);
    v.play();
  }
});
$("#all").addEventListener("click", () => { document.querySelectorAll("#sentences input").forEach((c) => (c.checked = true)); updateSummary(); });
$("#none").addEventListener("click", () => { document.querySelectorAll("#sentences input").forEach((c) => (c.checked = false)); updateSummary(); });

function applyPreset(name) {
  const p = config.presets[name];
  $("#font").value = p.font;
  $("#size").value = p.size;
  $("#margin").value = p.margin_bottom;
  $("#caps").value = String(p.caps);
  $("#accent").checked = p.accent;
  $("#accent-color").value = "#" + p.accent_color;
}

function readStyle() {
  return {
    font: $("#font").value,
    size: Number($("#size").value),
    margin_bottom: Number($("#margin").value),
    caps: $("#caps").value === "true",
    accent: $("#accent").checked,
    accent_color: $("#accent-color").value.replace("#", ""),
  };
}

function readHook() {
  return {
    text: $("#hook-text").value,
    look: $("#hook-look").value,
    font: $("#hook-font").value,
    size: Number($("#hook-size").value),
    top: Number($("#hook-top").value),
    seconds: Number($("#hook-seconds").value),
    color: $("#hook-color").value.replace("#", ""),
    box_color: $("#hook-box-color").value.replace("#", ""),
  };
}

$("#hook-look").addEventListener("change", () => {
  const boxed = $("#hook-look").value !== "outline";
  $("#hook-box-wrap").hidden = !boxed;
  if (boxed && $("#hook-color").value === "#ffffff") $("#hook-color").value = "#ffd400";
});

const splitList = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);

$("#preset").addEventListener("change", (e) => applyPreset(e.target.value));

$("#render").addEventListener("click", async () => {
  const keep = selected();
  if (!keep.length) return;
  try {
    await api(`/api/jobs/${currentId}/render`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        keep, preset: $("#preset").value, overrides: readStyle(),
        brand: splitList($("#brand").value), edits, hook: readHook(),
      }),
    });
    stopPoll();
    await refreshJob();
  } catch (err) {
    $("#job-status").textContent = err.message;
    $("#job-status").className = "error";
  }
});

$("#delete").addEventListener("click", async () => {
  if (!confirm("Delete this video and its results?")) return;
  await api(`/api/jobs/${currentId}`, { method: "DELETE" });
  location.hash = "#";
});

function renderResults(j) {
  const box = $("#result-list");
  $("#results").hidden = j.outputs.length === 0;
  const have = new Set([...box.children].map((c) => c.dataset.f));
  for (const o of [...j.outputs].reverse()) {
    if (have.has(o.file)) continue;
    const d = document.createElement("div");
    d.className = "result";
    d.dataset.f = o.file;
    const url = `/api/jobs/${j.id}/outputs/${o.file}`;
    d.innerHTML = `<video controls preload="metadata" src="${url}"></video>` +
      `<p>${esc(o.label)}, ${o.duration} s<br><a href="${url}" download>Download</a></p>`;
    box.prepend(d);
  }
}

function route() {
  const m = location.hash.match(/^#\/job\/([a-z0-9]+)$/);
  if (m) openJob(m[1]); else showList();
}
window.addEventListener("hashchange", route);
$("#home").addEventListener("click", () => { if (!location.hash) route(); });

(async function init() {
  config = await api("/api/config");
  const preset = $("#preset");
  for (const name of Object.keys(config.presets)) preset.add(new Option(name, name));
  const lang = $("#language");
  for (const l of config.languages) lang.add(new Option(l.label, l.id));
  const font = $("#font");
  for (const f of config.fonts) font.add(new Option(f.label + (f.installed ? "" : " (not installed)"), f.id));
  const hookFont = $("#hook-font");
  for (const f of config.fonts) hookFont.add(new Option(f.label + (f.installed ? "" : " (not installed)"), f.id));
  hookFont.value = "inter-bold";
  $("#hook-box-wrap").hidden = true;
  applyPreset("plain");
  if (!config.whisper_ready) {
    for (const o of lang.options) if (o.value !== "en") o.text += " (needs Whisper)";
  }
  if (!config.model_ready) {
    $("#upload-msg").textContent = "English speech model missing (other languages do not need it). Run: opencaptions models fetch";
    $("#upload-msg").className = "error";
  }
  route();
})();
