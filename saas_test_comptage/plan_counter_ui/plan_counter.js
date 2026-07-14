const state = {
  image: null,
  imageUrl: null,
  imageName: "",
  scale: 1,
  labels: [],
  currentLabel: null,
  markers: [],
  detectionsByPage: [],
  selectedDetectionPage: 1,
  annotationQueue: [],
  queueIndex: -1,
  imageFilesByName: new Map(),
  sessionCache: new Map(),
};

const colorPalette = [
  "#e74c3c",
  "#2980b9",
  "#27ae60",
  "#8e44ad",
  "#f39c12",
  "#16a085",
  "#d35400",
  "#2c3e50",
  "#c0392b",
  "#7f8c8d",
];

const elements = {
  planImageInput: document.getElementById("planImageInput"),
  labelsFileInput: document.getElementById("labelsFileInput"),
  detectionsFileInput: document.getElementById("detectionsFileInput"),
  sessionFileInput: document.getElementById("sessionFileInput"),
  queueFileInput: document.getElementById("queueFileInput"),
  imageFolderInput: document.getElementById("imageFolderInput"),
  newLabelInput: document.getElementById("newLabelInput"),
  addLabelButton: document.getElementById("addLabelButton"),
  exportSessionButton: document.getElementById("exportSessionButton"),
  exportAndNextButton: document.getElementById("exportAndNextButton"),
  prevQueueButton: document.getElementById("prevQueueButton"),
  nextQueueButton: document.getElementById("nextQueueButton"),
  clearCurrentButton: document.getElementById("clearCurrentButton"),
  clearAllButton: document.getElementById("clearAllButton"),
  labelList: document.getElementById("labelList"),
  summaryList: document.getElementById("summaryList"),
  queueInfo: document.getElementById("queueInfo"),
  planCanvas: document.getElementById("planCanvas"),
  canvasContainer: document.getElementById("canvasContainer"),
  emptyState: document.getElementById("emptyState"),
  activeLabelName: document.getElementById("activeLabelName"),
  statusLine: document.getElementById("statusLine"),
  sourceLine: document.getElementById("sourceLine"),
  zoomRange: document.getElementById("zoomRange"),
  zoomValue: document.getElementById("zoomValue"),
};

const ctx = elements.planCanvas.getContext("2d");

function makeLabelId(name) {
  return name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || `label_${Date.now()}`;
}

function nextColor(index) {
  return colorPalette[index % colorPalette.length];
}

function stemFromFilename(filename) {
  return filename.replace(/\.[^.]+$/, "");
}

function currentQueueItem() {
  return state.annotationQueue[state.queueIndex] || null;
}

function getLabelById(labelId) {
  return state.labels.find((label) => label.id === labelId);
}

function ensureCurrentLabel() {
  if (!state.currentLabel && state.labels.length > 0) {
    state.currentLabel = state.labels[0].id;
  }
}

function updateStatus(message) {
  elements.statusLine.textContent = message;
}

function updateSourceLine() {
  const item = currentQueueItem();
  if (!item) {
    elements.sourceLine.textContent = state.imageName ? `Image: ${state.imageName}` : "";
    return;
  }
  elements.sourceLine.textContent = `${item.split || "n/a"} | ${item.source_pdf || "source inconnue"} | page ${item.source_page || "?"}`;
}

function renderQueueInfo() {
  const item = currentQueueItem();
  if (!state.annotationQueue.length) {
    elements.queueInfo.textContent = "Aucune queue chargee.";
    return;
  }

  const total = state.annotationQueue.length;
  const current = state.queueIndex + 1;
  const cached = state.sessionCache.has(item.image_filename) ? "session en memoire" : "non annotee";
  elements.queueInfo.textContent = `${current}/${total} | ${item.split} | ${item.image_filename} | ${cached}`;
}

function setActiveLabel(labelId) {
  state.currentLabel = labelId;
  const label = getLabelById(labelId);
  elements.activeLabelName.textContent = label ? `Etiquette active: ${label.name}` : "Aucune etiquette selectionnee";
  renderLabelList();
  drawCanvas();
}

function addLabel(name, preferredColor) {
  const trimmed = name.trim();
  if (!trimmed) {
    return;
  }

  const existing = state.labels.find((label) => label.name === trimmed);
  if (existing) {
    setActiveLabel(existing.id);
    return;
  }

  const label = {
    id: makeLabelId(trimmed),
    name: trimmed,
    color: preferredColor || nextColor(state.labels.length),
    visible: true,
  };
  state.labels.push(label);
  ensureCurrentLabel();
  setActiveLabel(label.id);
  renderSummary();
}

function removeLabel(labelId) {
  state.labels = state.labels.filter((label) => label.id !== labelId);
  state.markers = state.markers.filter((marker) => marker.labelId !== labelId);
  if (state.currentLabel === labelId) {
    state.currentLabel = state.labels[0]?.id || null;
  }
  renderLabelList();
  renderSummary();
  drawCanvas();
}

function countManualForLabel(labelId) {
  return state.markers.filter((marker) => marker.labelId === labelId).length;
}

function currentPageDetections() {
  return state.detectionsByPage.find((page) => page.page === state.selectedDetectionPage)?.detections || [];
}

function countDetectionsForLabel(labelName) {
  return currentPageDetections().filter((detection) => detection.label === labelName).length;
}

function renderLabelList() {
  elements.labelList.innerHTML = "";
  for (const label of state.labels) {
    const item = document.createElement("div");
    item.className = `label-item${state.currentLabel === label.id ? " active" : ""}`;

    const visibility = document.createElement("input");
    visibility.type = "checkbox";
    visibility.checked = label.visible;
    visibility.addEventListener("change", () => {
      label.visible = visibility.checked;
      drawCanvas();
      renderSummary();
    });

    const center = document.createElement("div");
    center.innerHTML = `<div><strong>${label.name}</strong></div><div class="muted">manuel ${countManualForLabel(label.id)} | auto ${countDetectionsForLabel(label.name)}</div>`;

    const actions = document.createElement("div");
    actions.className = "label-actions";

    const chip = document.createElement("span");
    chip.className = "color-chip";
    chip.style.background = label.color;
    chip.title = label.color;

    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "small-button";
    selectButton.textContent = "Activer";
    selectButton.addEventListener("click", () => setActiveLabel(label.id));

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "small-button";
    deleteButton.textContent = "X";
    deleteButton.addEventListener("click", () => removeLabel(label.id));

    actions.appendChild(chip);
    actions.appendChild(selectButton);
    actions.appendChild(deleteButton);

    item.appendChild(visibility);
    item.appendChild(center);
    item.appendChild(actions);
    elements.labelList.appendChild(item);
  }
}

function renderSummary() {
  elements.summaryList.innerHTML = "";
  for (const label of state.labels) {
    const item = document.createElement("div");
    item.className = "summary-item";

    const chip = document.createElement("span");
    chip.className = "color-chip";
    chip.style.background = label.color;

    const title = document.createElement("div");
    title.innerHTML = `<strong>${label.name}</strong><div class="muted">${label.visible ? "visible" : "masque"}</div>`;

    const counts = document.createElement("div");
    const manual = countManualForLabel(label.id);
    const automatic = countDetectionsForLabel(label.name);
    counts.className = "summary-counts";
    counts.innerHTML = `manuel: ${manual}<br>auto: ${automatic}<br>total: ${manual + automatic}`;

    item.appendChild(chip);
    item.appendChild(title);
    item.appendChild(counts);
    elements.summaryList.appendChild(item);
  }
}

function resizeCanvas() {
  if (!state.image) {
    return;
  }
  elements.planCanvas.width = state.image.width;
  elements.planCanvas.height = state.image.height;
  elements.planCanvas.style.width = `${Math.round(state.image.width * state.scale)}px`;
  elements.planCanvas.style.height = `${Math.round(state.image.height * state.scale)}px`;
}

function drawMarker(marker, label) {
  if (!label?.visible) {
    return;
  }
  ctx.beginPath();
  ctx.arc(marker.x, marker.y, 8, 0, Math.PI * 2);
  ctx.fillStyle = `${label.color}cc`;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#ffffff";
  ctx.stroke();

  ctx.fillStyle = label.color;
  ctx.font = "12px Arial";
  ctx.fillText(label.name, marker.x + 12, marker.y - 10);
}

function drawDetection(detection) {
  const label = state.labels.find((entry) => entry.name === detection.label);
  if (!label?.visible) {
    return;
  }
  ctx.lineWidth = 2;
  ctx.strokeStyle = label.color;
  ctx.strokeRect(detection.x1, detection.y1, detection.x2 - detection.x1, detection.y2 - detection.y1);
  ctx.fillStyle = `${label.color}22`;
  ctx.fillRect(detection.x1, detection.y1, detection.x2 - detection.x1, detection.y2 - detection.y1);
  ctx.fillStyle = label.color;
  ctx.font = "12px Arial";
  ctx.fillText(`${detection.label} ${Number(detection.score || 0).toFixed(2)}`, detection.x1 + 4, Math.max(14, detection.y1 - 4));
}

function drawCanvas() {
  ctx.clearRect(0, 0, elements.planCanvas.width, elements.planCanvas.height);
  if (!state.image) {
    elements.emptyState.style.display = "flex";
    return;
  }

  elements.emptyState.style.display = "none";
  ctx.drawImage(state.image, 0, 0);

  for (const detection of currentPageDetections()) {
    drawDetection(detection);
  }

  for (const marker of state.markers) {
    drawMarker(marker, getLabelById(marker.labelId));
  }
}

function canvasPointFromEvent(event) {
  const rect = elements.planCanvas.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) / state.scale,
    y: (event.clientY - rect.top) / state.scale,
  };
}

function cacheCurrentSession() {
  if (!state.imageName) {
    return;
  }
  state.sessionCache.set(state.imageName, {
    imageName: state.imageName,
    selectedDetectionPage: state.selectedDetectionPage,
    labels: state.labels.map((label) => ({ ...label })),
    markers: state.markers.map((marker) => ({ ...marker })),
    detectionsByPage: state.detectionsByPage.map((page) => ({
      ...page,
      detections: (page.detections || []).map((detection) => ({ ...detection })),
    })),
  });
  renderQueueInfo();
}

function applySessionData(data) {
  state.markers = Array.isArray(data.markers) ? data.markers.map((marker) => ({ ...marker })) : [];
  state.detectionsByPage = Array.isArray(data.detectionsByPage)
    ? data.detectionsByPage.map((page) => ({
      ...page,
      detections: (page.detections || []).map((detection) => ({ ...detection })),
    }))
    : [];
  state.selectedDetectionPage = data.selectedDetectionPage || 1;

  if (Array.isArray(data.labels) && data.labels.length) {
    state.labels = data.labels.map((label, index) => ({
      id: label.id || makeLabelId(label.name || `label_${index + 1}`),
      name: label.name || `label_${index + 1}`,
      color: label.color || nextColor(index),
      visible: label.visible !== false,
    }));
  }

  ensureCurrentLabel();
  setActiveLabel(state.currentLabel);
  renderSummary();
  drawCanvas();
}

function loadPlanImage(file, options = {}) {
  if (!file) {
    return;
  }

  cacheCurrentSession();

  if (state.imageUrl) {
    URL.revokeObjectURL(state.imageUrl);
  }

  state.imageUrl = URL.createObjectURL(file);
  state.imageName = file.name;
  const image = new Image();
  image.onload = () => {
    state.image = image;
    resizeCanvas();

    const cached = state.sessionCache.get(file.name);
    if (cached) {
      applySessionData(cached);
    } else {
      state.markers = [];
      state.detectionsByPage = [];
      state.selectedDetectionPage = 1;
      drawCanvas();
      renderSummary();
    }

    updateSourceLine();
    renderQueueInfo();
    const suffix = options.fromQueue ? "Queue active." : "Clique sur le plan pour compter l'etiquette active.";
    updateStatus(`Plan charge: ${file.name}. ${suffix}`);
  };
  image.src = state.imageUrl;
}

async function readJsonFile(file) {
  return JSON.parse(await file.text());
}

function importLabelsFromJson(data) {
  let names = [];
  if (Array.isArray(data)) {
    names = data.map((value) => String(value));
  } else if (Array.isArray(data.templates)) {
    names = data.templates.map((item) => item.label || item.id).filter(Boolean);
  } else if (Array.isArray(data.labels)) {
    names = data.labels.map((item) => typeof item === "string" ? item : item.name).filter(Boolean);
  }

  for (const name of names) {
    addLabel(name);
  }
  renderLabelList();
  renderSummary();
}

function importDetectionsFromJson(data) {
  state.detectionsByPage = Array.isArray(data.pages) ? data.pages : [];
  state.selectedDetectionPage = state.detectionsByPage[0]?.page || 1;
  const names = new Set();
  for (const page of state.detectionsByPage) {
    for (const detection of page.detections || []) {
      names.add(detection.label);
    }
  }
  for (const name of names) {
    addLabel(name);
  }
  renderLabelList();
  renderSummary();
  drawCanvas();
  cacheCurrentSession();
  updateStatus(`Detections chargees pour ${state.detectionsByPage.length} page(s).`);
}

function importSessionFromJson(data) {
  applySessionData(data);
  if (data.imageName) {
    state.imageName = data.imageName;
  }
  cacheCurrentSession();
  updateSourceLine();
  updateStatus("Session chargee.");
}

function indexImageFiles(files) {
  state.imageFilesByName = new Map();
  for (const file of files) {
    state.imageFilesByName.set(file.name, file);
  }
  const count = state.imageFilesByName.size;
  updateStatus(`${count} image(s) indexee(s) pour la navigation.`);
  renderQueueInfo();
}

function importQueueFromJson(data) {
  state.annotationQueue = Array.isArray(data) ? data : [];
  state.queueIndex = state.annotationQueue.length ? 0 : -1;
  renderQueueInfo();
  updateSourceLine();
  if (!state.annotationQueue.length) {
    updateStatus("Queue vide ou invalide.");
    return;
  }
  updateStatus(`Queue chargee: ${state.annotationQueue.length} image(s).`);
  if (state.imageFilesByName.size) {
    loadQueueItem(state.queueIndex);
  }
}

function loadQueueItem(index) {
  if (index < 0 || index >= state.annotationQueue.length) {
    return;
  }
  const item = state.annotationQueue[index];
  const file = state.imageFilesByName.get(item.image_filename);
  state.queueIndex = index;
  renderQueueInfo();
  updateSourceLine();

  if (!file) {
    updateStatus(`Image introuvable dans le dossier selectionne: ${item.image_filename}`);
    return;
  }

  loadPlanImage(file, { fromQueue: true });
}

function moveQueue(delta) {
  if (!state.annotationQueue.length) {
    return;
  }
  const nextIndex = state.queueIndex + delta;
  if (nextIndex < 0 || nextIndex >= state.annotationQueue.length) {
    updateStatus("Fin de queue atteinte.");
    return;
  }
  loadQueueItem(nextIndex);
}

function buildSessionPayload() {
  return {
    imageName: state.imageName,
    selectedDetectionPage: state.selectedDetectionPage,
    labels: state.labels,
    markers: state.markers,
    detectionsByPage: state.detectionsByPage,
  };
}

function exportSession() {
  cacheCurrentSession();
  const payload = buildSessionPayload();
  const stem = state.imageName ? stemFromFilename(state.imageName) : "plan_counter_session";
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${stem}.json`;
  link.click();
  URL.revokeObjectURL(url);
  updateStatus(`Session exportee: ${stem}.json`);
}

function exportSessionAndNext() {
  exportSession();
  if (state.annotationQueue.length) {
    moveQueue(1);
  }
}

function removeNearestMarker(point) {
  let bestIndex = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < state.markers.length; index += 1) {
    const marker = state.markers[index];
    const dx = marker.x - point.x;
    const dy = marker.y - point.y;
    const distance = Math.hypot(dx, dy);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  }

  if (bestIndex >= 0 && bestDistance <= 18 / state.scale) {
    state.markers.splice(bestIndex, 1);
    renderLabelList();
    renderSummary();
    drawCanvas();
    cacheCurrentSession();
  }
}

elements.planImageInput.addEventListener("change", (event) => {
  loadPlanImage(event.target.files[0]);
});

elements.labelsFileInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) {
    return;
  }
  importLabelsFromJson(await readJsonFile(file));
  updateStatus(`Labels charges depuis ${file.name}.`);
});

elements.detectionsFileInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) {
    return;
  }
  importDetectionsFromJson(await readJsonFile(file));
});

elements.sessionFileInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) {
    return;
  }
  importSessionFromJson(await readJsonFile(file));
});

elements.queueFileInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) {
    return;
  }
  importQueueFromJson(await readJsonFile(file));
});

elements.imageFolderInput.addEventListener("change", (event) => {
  const files = Array.from(event.target.files || []).filter((file) => /\.(png|jpe?g|webp)$/i.test(file.name));
  indexImageFiles(files);
  if (state.annotationQueue.length) {
    loadQueueItem(state.queueIndex >= 0 ? state.queueIndex : 0);
  }
});

elements.prevQueueButton.addEventListener("click", () => moveQueue(-1));
elements.nextQueueButton.addEventListener("click", () => moveQueue(1));

elements.addLabelButton.addEventListener("click", () => {
  addLabel(elements.newLabelInput.value);
  elements.newLabelInput.value = "";
  renderLabelList();
  renderSummary();
  cacheCurrentSession();
});

elements.exportSessionButton.addEventListener("click", exportSession);
elements.exportAndNextButton.addEventListener("click", exportSessionAndNext);

elements.clearCurrentButton.addEventListener("click", () => {
  if (!state.currentLabel) {
    return;
  }
  state.markers = state.markers.filter((marker) => marker.labelId !== state.currentLabel);
  renderLabelList();
  renderSummary();
  drawCanvas();
  cacheCurrentSession();
});

elements.clearAllButton.addEventListener("click", () => {
  state.markers = [];
  renderLabelList();
  renderSummary();
  drawCanvas();
  cacheCurrentSession();
});

elements.zoomRange.addEventListener("input", () => {
  state.scale = Number(elements.zoomRange.value) / 100;
  elements.zoomValue.textContent = `${elements.zoomRange.value}%`;
  resizeCanvas();
  drawCanvas();
});

elements.planCanvas.addEventListener("click", (event) => {
  if (!state.image || !state.currentLabel) {
    return;
  }
  const point = canvasPointFromEvent(event);
  state.markers.push({
    x: point.x,
    y: point.y,
    labelId: state.currentLabel,
  });
  renderLabelList();
  renderSummary();
  drawCanvas();
  cacheCurrentSession();
});

elements.planCanvas.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  if (!state.image) {
    return;
  }
  removeNearestMarker(canvasPointFromEvent(event));
});

document.addEventListener("keydown", (event) => {
  if (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA") {
    return;
  }
  if (event.key === "ArrowLeft") {
    moveQueue(-1);
  } else if (event.key === "ArrowRight") {
    moveQueue(1);
  }
});

renderLabelList();
renderSummary();
renderQueueInfo();
updateSourceLine();
updateStatus("Charge labels.json, annotation_queue.json, puis le dossier d'images pour annoter rapidement.");
