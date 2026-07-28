const state = {
  pdf: null,
  preview: null,
  render: null,
  selectedTile: null,
  selectedGridCell: null,
  templateMode: false,
  template: null,
  templateDrag: null,
  selectedLegendSymbol: null,
  roi: { x: 0, y: 0, w: 1, h: 1 },
  drag: null,
};

const pdfInput = document.getElementById("pdfInput");
const uploadButton = document.getElementById("uploadButton");
const fileInfo = document.getElementById("fileInfo");
const pageInput = document.getElementById("pageInput");
const rowsInput = document.getElementById("rowsInput");
const colsInput = document.getElementById("colsInput");
const dpiInput = document.getElementById("dpiInput");
const dpiValue = document.getElementById("dpiValue");
const previewZoomInput = document.getElementById("previewZoomInput");
const previewZoomValue = document.getElementById("previewZoomValue");
const tileMarginInput = document.getElementById("tileMarginInput");
const tileMarginValue = document.getElementById("tileMarginValue");
const enhanceSelect = document.getElementById("enhanceSelect");
const previewButton = document.getElementById("previewButton");
const renderButton = document.getElementById("renderButton");
const resetGridButton = document.getElementById("resetGridButton");
const title = document.getElementById("title");
const statusEl = document.getElementById("status");
const gridMeta = document.getElementById("gridMeta");
const pagePreview = document.getElementById("pagePreview");
const tileMeta = document.getElementById("tileMeta");
const tileZoomSelect = document.getElementById("tileZoomSelect");
const pixelSharpInput = document.getElementById("pixelSharpInput");
const originalTile = document.getElementById("originalTile");
const enhancedTile = document.getElementById("enhancedTile");
const tilesMeta = document.getElementById("tilesMeta");
const tilesGrid = document.getElementById("tilesGrid");
const templateModeButton = document.getElementById("templateModeButton");
const detectThresholdInput = document.getElementById("detectThresholdInput");
const detectThresholdValue = document.getElementById("detectThresholdValue");
const detectRotationsInput = document.getElementById("detectRotationsInput");
const detectButton = document.getElementById("detectButton");
const detectRedButton = document.getElementById("detectRedButton");
const detectMeta = document.getElementById("detectMeta");
const templatePreview = document.getElementById("templatePreview");
const detectPreview = document.getElementById("detectPreview");
const segMeta = document.getElementById("segMeta");
const segCheckpointSelect = document.getElementById("segCheckpointSelect");
const segScoreInput = document.getElementById("segScoreInput");
const segScoreValue = document.getElementById("segScoreValue");
const refreshSegButton = document.getElementById("refreshSegButton");
const segmentTileButton = document.getElementById("segmentTileButton");
const segCounts = document.getElementById("segCounts");
const segPreview = document.getElementById("segPreview");
const cocoMeta = document.getElementById("cocoMeta");
const cocoDatasetSelect = document.getElementById("cocoDatasetSelect");
const cocoSplitSelect = document.getElementById("cocoSplitSelect");
const cocoIndexInput = document.getElementById("cocoIndexInput");
const loadCocoSampleButton = document.getElementById("loadCocoSampleButton");
const cocoCounts = document.getElementById("cocoCounts");
const cocoRawPreview = document.getElementById("cocoRawPreview");
const cocoOverlayPreview = document.getElementById("cocoOverlayPreview");
const classMeta = document.getElementById("classMeta");
const loadClassesButton = document.getElementById("loadClassesButton");
const classExampleSplitSelect = document.getElementById("classExampleSplitSelect");
const classList = document.getElementById("classList");
const classExampleTitle = document.getElementById("classExampleTitle");
const classExampleMeta = document.getElementById("classExampleMeta");
const classExamples = document.getElementById("classExamples");
const visualAtlasMeta = document.getElementById("visualAtlasMeta");
const loadLegendSymbolsButton = document.getElementById("loadLegendSymbolsButton");
const visualMatchSplitSelect = document.getElementById("visualMatchSplitSelect");
const visualMatchLimitInput = document.getElementById("visualMatchLimitInput");
const legendSymbolsGrid = document.getElementById("legendSymbolsGrid");
const visualMatchTitle = document.getElementById("visualMatchTitle");
const visualMatchMeta = document.getElementById("visualMatchMeta");
const visualMatchesGrid = document.getElementById("visualMatchesGrid");

function setBusy(isBusy, message) {
  uploadButton.disabled = isBusy;
  previewButton.disabled = isBusy || !state.pdf;
  renderButton.disabled = isBusy || !state.pdf;
  resetGridButton.disabled = isBusy || !state.pdf;
  if (message) {
    statusEl.textContent = message;
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function getConfig() {
  return {
    pdf_id: state.pdf?.pdf_id,
    page: Number(pageInput.value || 1),
    rows: Number(rowsInput.value || 5),
    cols: Number(colsInput.value || 5),
    dpi: Number(dpiInput.value || 300),
    enhance_mode: enhanceSelect.value,
    tile_margin: Number(tileMarginInput.value || 0) / 100,
    roi: state.roi,
  };
}

function getTileConfig(row, col) {
  return {
    ...getConfig(),
    tile_row: row,
    tile_col: col,
  };
}

function clampRoi(roi) {
  const x = Math.max(0, Math.min(0.98, roi.x));
  const y = Math.max(0, Math.min(0.98, roi.y));
  const w = Math.max(0.02, Math.min(1 - x, roi.w));
  const h = Math.max(0.02, Math.min(1 - y, roi.h));
  return { x, y, w, h };
}

async function uploadPdf() {
  const file = pdfInput.files[0];
  if (!file) {
    statusEl.textContent = "Choisis un PDF.";
    return;
  }
  const form = new FormData();
  form.append("file", file);
  setBusy(true, "Upload du PDF...");
  try {
    const payload = await fetchJson("/api/upload", {
      method: "POST",
      body: form,
    });
    state.pdf = payload;
    state.preview = null;
    state.render = null;
    state.selectedTile = null;
    state.selectedGridCell = null;
    state.template = null;
    state.roi = { x: 0, y: 0, w: 1, h: 1 };
    title.textContent = payload.name;
    fileInfo.textContent = `${payload.name} - ${payload.page_count} page(s)`;
    pageInput.max = payload.page_count;
    statusEl.textContent = "PDF charge. Lance la grille puis ajuste-la a la souris.";
    renderPreview();
    renderTiles();
    renderSelectedTile();
    renderDetectionState();
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function loadPreview() {
  if (!state.pdf) {
    return;
  }
  setBusy(true, "Generation de l'apercu de grille...");
  try {
    state.preview = await fetchJson("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(getConfig()),
    });
    statusEl.textContent = "Deplace la grille ou tire les coins, puis rends les cellules.";
    renderPreview();
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function renderOneTile(row, col) {
  if (!state.pdf) {
    return;
  }
  state.selectedGridCell = { row, col };
  applyGridBox();
  setBusy(true, `Rendu rapide de la cellule L${row} C${col}...`);
  try {
    const payload = await fetchJson("/api/render-tile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(getTileConfig(row, col)),
    });
    state.selectedTile = payload.tile;
    state.template = null;
    statusEl.textContent = `Cellule ${payload.tile.label} rendue. Ajuste la zone ou clique une autre cellule.`;
    renderSelectedTile();
    renderDetectionState();
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function renderGrid() {
  if (!state.pdf) {
    return;
  }
  const cfg = getConfig();
  if (cfg.rows * cfg.cols > 100) {
    statusEl.textContent = "Maximum 100 cellules par rendu.";
    return;
  }
  setBusy(true, `Rendu ${cfg.rows * cfg.cols} cellule(s) a ${cfg.dpi} DPI...`);
  try {
    state.render = await fetchJson("/api/render-grid", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    state.selectedTile = state.render.tiles[0] || null;
    state.template = null;
    statusEl.textContent = "Cellules rendues. Clique une cellule pour comparer original et ameliore.";
    renderTiles();
    renderSelectedTile();
    renderDetectionState();
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

function renderPreview() {
  if (!state.preview) {
    pagePreview.className = "page-preview empty-state";
    pagePreview.textContent = "La grille apparaitra ici.";
    gridMeta.textContent = "";
    return;
  }

  const zoom = Number(previewZoomInput.value || 100);
  pagePreview.className = "page-preview";
  pagePreview.innerHTML = `
    <div class="page-canvas" style="width:${zoom}%">
      <img src="${state.preview.preview_url}" alt="Apercu page">
      <div id="gridBox" class="grid-box">
        <div class="grid-inner"></div>
        <div class="move-pad" data-handle="move">deplacer</div>
        <button class="handle nw" data-handle="nw" type="button"></button>
        <button class="handle ne" data-handle="ne" type="button"></button>
        <button class="handle sw" data-handle="sw" type="button"></button>
        <button class="handle se" data-handle="se" type="button"></button>
      </div>
    </div>
  `;
  applyGridBox();
  bindGridBox();
  gridMeta.textContent = `${rowsInput.value} x ${colsInput.value} - zone ${Math.round(state.roi.w * 100)}% x ${Math.round(state.roi.h * 100)}%`;
}

function applyGridBox() {
  const box = document.getElementById("gridBox");
  if (!box) {
    return;
  }
  const rows = Math.max(1, Number(rowsInput.value || 1));
  const cols = Math.max(1, Number(colsInput.value || 1));
  box.style.left = `${state.roi.x * 100}%`;
  box.style.top = `${state.roi.y * 100}%`;
  box.style.width = `${state.roi.w * 100}%`;
  box.style.height = `${state.roi.h * 100}%`;
  box.style.setProperty("--rows", rows);
  box.style.setProperty("--cols", cols);
  box.querySelector(".grid-inner").style.gridTemplateRows = `repeat(${rows}, 1fr)`;
  box.querySelector(".grid-inner").style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  box.querySelector(".grid-inner").innerHTML = Array.from({ length: rows * cols }, (_, index) => {
    const row = Math.floor(index / cols) + 1;
    const col = (index % cols) + 1;
    const active = state.selectedGridCell?.row === row && state.selectedGridCell?.col === col;
    return `<button class="grid-tile${active ? " active" : ""}" data-row="${row}" data-col="${col}" type="button">${row}.${col}</button>`;
  }).join("");
}

function bindGridBox() {
  const box = document.getElementById("gridBox");
  const canvas = pagePreview.querySelector(".page-canvas");
  if (!box || !canvas) {
    return;
  }

  box.addEventListener("pointerdown", (event) => {
    const handle = event.target.dataset.handle;
    if (!handle) {
      return;
    }
    const rect = canvas.getBoundingClientRect();
    state.drag = {
      handle,
      startX: (event.clientX - rect.left) / rect.width,
      startY: (event.clientY - rect.top) / rect.height,
      roi: { ...state.roi },
    };
    box.setPointerCapture(event.pointerId);
  });

  box.addEventListener("pointermove", (event) => {
    if (!state.drag) {
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;
    const dx = x - state.drag.startX;
    const dy = y - state.drag.startY;
    const r = state.drag.roi;
    let next = { ...r };

    if (state.drag.handle === "move") {
      next.x = r.x + dx;
      next.y = r.y + dy;
    } else {
      if (state.drag.handle.includes("w")) {
        next.x = r.x + dx;
        next.w = r.w - dx;
      }
      if (state.drag.handle.includes("e")) {
        next.w = r.w + dx;
      }
      if (state.drag.handle.includes("n")) {
        next.y = r.y + dy;
        next.h = r.h - dy;
      }
      if (state.drag.handle.includes("s")) {
        next.h = r.h + dy;
      }
    }

    if (state.drag.handle === "move") {
      next.x = Math.max(0, Math.min(1 - r.w, next.x));
      next.y = Math.max(0, Math.min(1 - r.h, next.y));
      next.w = r.w;
      next.h = r.h;
    }

    state.roi = clampRoi(next);
    applyGridBox();
    gridMeta.textContent = `${rowsInput.value} x ${colsInput.value} - zone ${Math.round(state.roi.w * 100)}% x ${Math.round(state.roi.h * 100)}%`;
  });

  box.addEventListener("pointerup", () => {
    state.drag = null;
  });
  box.addEventListener("pointercancel", () => {
    state.drag = null;
  });

  box.querySelectorAll(".grid-tile").forEach((tileButton) => {
    tileButton.addEventListener("click", (event) => {
      event.stopPropagation();
      renderOneTile(Number(tileButton.dataset.row), Number(tileButton.dataset.col));
    });
  });
}

function renderTiles() {
  if (!state.render) {
    tilesGrid.className = "tiles-grid empty-state";
    tilesGrid.textContent = "Les cellules haute definition apparaitront ici.";
    tilesMeta.textContent = "";
    return;
  }

  tilesGrid.className = "tiles-grid";
  tilesMeta.textContent = `${state.render.tiles.length} cellules - ${state.render.dpi} DPI`;
  tilesGrid.innerHTML = "";
  state.render.tiles.forEach((tile) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `tile-button${state.selectedTile === tile ? " active" : ""}`;
    button.innerHTML = `
      <strong>${tile.label}</strong>
      <img src="${tile.enhanced_url}" alt="${tile.label}">
    `;
    button.addEventListener("click", () => {
      state.selectedTile = tile;
      renderTiles();
      renderSelectedTile();
    });
    tilesGrid.appendChild(button);
  });
}

function renderSelectedTile() {
  const tile = state.selectedTile;
  if (!tile) {
    tileMeta.textContent = "";
    originalTile.className = "tile-stage empty-state";
    enhancedTile.className = "tile-stage empty-state";
    originalTile.textContent = "Aucune cellule.";
    enhancedTile.textContent = "Aucune cellule.";
    return;
  }

  tileMeta.textContent = `${tile.label} - ${tile.width} x ${tile.height}px`;
  originalTile.className = "tile-stage";
  enhancedTile.className = "tile-stage";
  const zoom = tileZoomSelect.value;
  const sharp = pixelSharpInput.checked ? " sharp" : "";
  const className = zoom === "fit" ? `inspect-img${sharp} fit` : `inspect-img${sharp}`;
  const widthStyle = zoom === "fit" ? "" : ` style="width:${Math.round(tile.width * Number(zoom))}px"`;
  originalTile.innerHTML = `
    <div class="template-canvas">
      <img id="originalInspectImage" class="${className}"${widthStyle} src="${tile.url}" alt="${tile.label} original">
      <div id="templateBox" class="template-box hidden"></div>
    </div>
  `;
  enhancedTile.innerHTML = `<img class="${className}"${widthStyle} src="${tile.enhanced_url}" alt="${tile.label} ameliore">`;
  bindTemplateSelection();
  drawTemplateBox();
}

function pathFromFileUrl(url) {
  const parsed = new URL(url, window.location.origin);
  return parsed.searchParams.get("path");
}

function imagePointFromEvent(event, image) {
  const rect = image.getBoundingClientRect();
  const x = (event.clientX - rect.left) / rect.width * image.naturalWidth;
  const y = (event.clientY - rect.top) / rect.height * image.naturalHeight;
  return {
    x: Math.max(0, Math.min(image.naturalWidth, x)),
    y: Math.max(0, Math.min(image.naturalHeight, y)),
  };
}

function bindTemplateSelection() {
  const image = document.getElementById("originalInspectImage");
  if (!image) {
    return;
  }
  image.addEventListener("pointerdown", (event) => {
    if (!state.templateMode || !state.selectedTile) {
      return;
    }
    event.preventDefault();
    const point = imagePointFromEvent(event, image);
    state.templateDrag = { start: point, current: point };
    image.setPointerCapture(event.pointerId);
    drawTemplateBox();
  });
  image.addEventListener("pointermove", (event) => {
    if (!state.templateDrag) {
      return;
    }
    state.templateDrag.current = imagePointFromEvent(event, image);
    drawTemplateBox();
  });
  image.addEventListener("pointerup", () => {
    if (!state.templateDrag) {
      return;
    }
    const a = state.templateDrag.start;
    const b = state.templateDrag.current;
    const x = Math.min(a.x, b.x);
    const y = Math.min(a.y, b.y);
    const w = Math.abs(a.x - b.x);
    const h = Math.abs(a.y - b.y);
    state.templateDrag = null;
    if (w >= 6 && h >= 6) {
      state.template = {
        bbox: { x, y, w, h },
        template_path: pathFromFileUrl(state.selectedTile.url),
        target_path: pathFromFileUrl(state.selectedTile.url),
      };
      state.templateMode = false;
      templateModeButton.classList.remove("active");
      statusEl.textContent = "Gabarit selectionne. Lance la detection sur la cellule.";
    }
    drawTemplateBox();
    renderDetectionState();
  });
}

function drawTemplateBox() {
  const image = document.getElementById("originalInspectImage");
  const box = document.getElementById("templateBox");
  if (!image || !box) {
    return;
  }
  const source = state.templateDrag
    ? {
      x: Math.min(state.templateDrag.start.x, state.templateDrag.current.x),
      y: Math.min(state.templateDrag.start.y, state.templateDrag.current.y),
      w: Math.abs(state.templateDrag.start.x - state.templateDrag.current.x),
      h: Math.abs(state.templateDrag.start.y - state.templateDrag.current.y),
    }
    : state.template?.bbox;
  if (!source) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  box.style.left = `${source.x / image.naturalWidth * 100}%`;
  box.style.top = `${source.y / image.naturalHeight * 100}%`;
  box.style.width = `${source.w / image.naturalWidth * 100}%`;
  box.style.height = `${source.h / image.naturalHeight * 100}%`;
}

function renderDetectionState(result = null) {
  if (!state.template) {
    detectMeta.textContent = "Aucun gabarit selectionne.";
    templatePreview.className = "small-stage empty-state";
    templatePreview.textContent = "Selectionne un symbole dans Original.";
    detectPreview.className = "tile-stage empty-state";
    detectPreview.textContent = "L'overlay de detection apparaitra ici.";
    return;
  }
  const bbox = state.template.bbox;
  detectMeta.textContent = `Gabarit ${Math.round(bbox.w)} x ${Math.round(bbox.h)} px`;
  if (result?.template_url) {
    templatePreview.className = "small-stage";
    templatePreview.innerHTML = `<img src="${result.template_url}" alt="Gabarit">`;
  }
  if (result?.overlay_url) {
    detectMeta.textContent = `${result.count} detection(s) - seuil ${result.threshold}`;
    detectPreview.className = "tile-stage";
    detectPreview.innerHTML = `<img class="inspect-img fit" src="${result.overlay_url}" alt="Detections">`;
  }
}

async function detectCurrentTile() {
  if (!state.selectedTile) {
    statusEl.textContent = "Rends d'abord une cellule.";
    return;
  }
  if (!state.template) {
    statusEl.textContent = "Selectionne d'abord un symbole dans Original.";
    return;
  }
  setBusy(true, "Detection du symbole dans la cellule...");
  try {
    const rotations = detectRotationsInput.checked ? [0, 90, 180, 270] : [0];
    const result = await fetchJson("/api/detect-template", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...state.template,
        target_path: pathFromFileUrl(state.selectedTile.url),
        threshold: Number(detectThresholdInput.value || 0.72),
        rotations,
      }),
    });
    statusEl.textContent = `${result.count} detection(s) trouvee(s) dans ${state.selectedTile.label}.`;
    renderDetectionState(result);
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function detectRedSymbols() {
  if (!state.selectedTile) {
    statusEl.textContent = "Rends d'abord une cellule.";
    return;
  }
  setBusy(true, "Detection des symboles rouges dans la cellule...");
  try {
    const result = await fetchJson("/api/detect-red-symbols", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_path: pathFromFileUrl(state.selectedTile.url),
      }),
    });
    detectMeta.textContent = `${result.count} symbole(s) rouge(s) detecte(s)`;
    templatePreview.className = "small-stage";
    templatePreview.innerHTML = result.mask_url
      ? `<img src="${result.mask_url}" alt="Masque rouge">`
      : "Masque indisponible.";
    detectPreview.className = "tile-stage";
    detectPreview.innerHTML = `<img class="inspect-img fit" src="${result.overlay_url}" alt="Detections rouges">`;
    statusEl.textContent = `${result.count} symbole(s) rouge(s) trouve(s) dans ${state.selectedTile.label}.`;
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function loadSegCheckpoints() {
  try {
    const payload = await fetchJson("/api/seg-checkpoints");
    const checkpoints = payload.checkpoints || [];
    segCheckpointSelect.innerHTML = "";
    if (!checkpoints.length) {
      segCheckpointSelect.innerHTML = `<option value="">Aucun checkpoint .pth/.pt trouve</option>`;
      segMeta.textContent = payload.warning
        ? `Aucun modele charge: ${payload.warning}`
        : "Aucun modele entraine trouve.";
      return;
    }
    checkpoints.forEach((checkpoint) => {
      const option = document.createElement("option");
      option.value = checkpoint.path;
      option.textContent = checkpoint.path;
      segCheckpointSelect.appendChild(option);
    });
    segMeta.textContent = `${checkpoints.length} checkpoint(s) disponible(s).`;
  } catch (error) {
    segCheckpointSelect.innerHTML = `<option value="">Erreur chargement</option>`;
    segMeta.textContent = `Erreur checkpoints: ${error.message}`;
  }
}

function renderSegCounts(counts, instanceCount) {
  const entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    segCounts.className = "counts-grid empty-state";
    segCounts.textContent = `${instanceCount || 0} instance detectee. Aucun comptage par classe.`;
    return;
  }
  segCounts.className = "counts-grid";
  segCounts.innerHTML = entries.map(([name, count]) => `
    <div class="count-card">
      <span>${name}</span>
      <strong>${count}</strong>
    </div>
  `).join("");
}

function renderCounts(container, counts, emptyText) {
  const entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    container.className = "counts-grid empty-state";
    container.textContent = emptyText;
    return;
  }
  container.className = "counts-grid";
  container.innerHTML = entries.map(([name, count]) => `
    <div class="count-card">
      <span>${name}</span>
      <strong>${count}</strong>
    </div>
  `).join("");
}

async function segmentCurrentTile() {
  if (!state.selectedTile) {
    statusEl.textContent = "Rends d'abord une cellule.";
    return;
  }
  if (!segCheckpointSelect.value) {
    statusEl.textContent = "Aucun checkpoint disponible. Il faut entrainer/exporter le modele de segmentation.";
    return;
  }
  setBusy(true, "Segmentation d'instance sur la cellule...");
  try {
    const result = await fetchJson("/api/segment-tile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        checkpoint_path: segCheckpointSelect.value,
        target_path: pathFromFileUrl(state.selectedTile.url),
        score_threshold: Number(segScoreInput.value || 0.5),
        mask_threshold: 0.5,
        tile_size: 1024,
        overlap: 128,
      }),
    });
    segMeta.textContent = `${result.instance_count} instance(s) detectee(s).`;
    renderSegCounts(result.counts, result.instance_count);
    segPreview.className = "tile-stage";
    segPreview.innerHTML = result.preview_url
      ? `<img class="inspect-img fit" src="${result.preview_url}" alt="Segmentation instance">`
      : "Aucun overlay genere.";
    statusEl.textContent = `Segmentation terminee: ${result.instance_count} instance(s).`;
  } catch (error) {
    segMeta.textContent = "Segmentation echouee.";
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function loadCocoDatasets() {
  try {
    const payload = await fetchJson("/api/coco-datasets");
    const datasets = payload.datasets || [];
    cocoDatasetSelect.innerHTML = "";
    if (!datasets.length) {
      cocoDatasetSelect.innerHTML = `<option value="">Aucun dataset COCO trouve</option>`;
      cocoMeta.textContent = payload.warning ? `Aucun dataset: ${payload.warning}` : "Aucun dataset COCO trouve.";
      return;
    }
    datasets.forEach((dataset) => {
      const option = document.createElement("option");
      option.value = dataset.path;
      const summary = dataset.splits.map((split) => `${split.name}:${split.images}/${split.annotations}`).join(" ");
      option.textContent = `${dataset.path} - ${summary}`;
      cocoDatasetSelect.appendChild(option);
    });
    cocoMeta.textContent = `${datasets.length} dataset(s) COCO detecte(s).`;
  } catch (error) {
    cocoDatasetSelect.innerHTML = `<option value="">Erreur chargement</option>`;
    cocoMeta.textContent = `Erreur datasets: ${error.message}`;
  }
}

async function loadCocoSample() {
  if (!cocoDatasetSelect.value) {
    statusEl.textContent = "Aucun dataset COCO selectionne.";
    return;
  }
  setBusy(true, "Chargement d'une tuile annotee...");
  try {
    const result = await fetchJson("/api/coco-sample", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_path: cocoDatasetSelect.value,
        split: cocoSplitSelect.value,
        index: Number(cocoIndexInput.value || 0),
      }),
    });
    cocoIndexInput.max = Math.max(0, result.image_count - 1);
    cocoMeta.textContent = `${result.split} tuile ${result.index + 1}/${result.image_count} - ${result.annotation_count} annotation(s)`;
    renderCounts(cocoCounts, result.counts, "Aucune annotation sur cette tuile.");
    cocoRawPreview.className = "tile-stage";
    cocoRawPreview.innerHTML = `<img class="inspect-img fit" src="${result.raw_url}" alt="Tuile brute">`;
    cocoOverlayPreview.className = "tile-stage";
    cocoOverlayPreview.innerHTML = `<img class="inspect-img fit" src="${result.overlay_url}" alt="Annotations COCO">`;
    statusEl.textContent = `Dataset verifie: ${result.annotation_count} masque(s) affiche(s).`;
  } catch (error) {
    cocoMeta.textContent = "Verification dataset echouee.";
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function loadClassSummary() {
  if (!cocoDatasetSelect.value) {
    statusEl.textContent = "Selectionne d'abord un dataset COCO.";
    return;
  }
  setBusy(true, "Chargement des classes a entrainer...");
  try {
    const result = await fetchJson("/api/coco-class-summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataset_path: cocoDatasetSelect.value }),
    });
    const classes = result.classes || [];
    classMeta.textContent = `${classes.length} classe(s) - ${result.dataset_path}`;
    if (!classes.length) {
      classList.className = "class-list empty-state";
      classList.textContent = "Aucune classe trouvee.";
      return;
    }
    classList.className = "class-list";
    classList.innerHTML = classes.map((item) => {
      const total = (item.train || 0) + (item.val || 0) + (item.test || 0);
      return `
        <button class="class-row" type="button" data-class="${item.name}">
          <strong>${item.name}</strong>
          <span>train ${item.train || 0}</span>
          <span>val ${item.val || 0}</span>
          <span>total ${total}</span>
        </button>
      `;
    }).join("");
    classList.querySelectorAll(".class-row").forEach((button) => {
      button.addEventListener("click", () => loadClassExamples(button.dataset.class));
    });
    statusEl.textContent = "Classes chargees. Clique une classe pour voir ses exemples.";
  } catch (error) {
    classMeta.textContent = "Chargement classes echoue.";
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function loadClassExamples(className) {
  setBusy(true, `Chargement exemples ${className}...`);
  try {
    const result = await fetchJson("/api/coco-class-examples", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_path: cocoDatasetSelect.value,
        class_name: className,
        split: classExampleSplitSelect.value,
        limit: 12,
      }),
    });
    classExampleTitle.textContent = result.class_name;
    classExampleMeta.textContent = `${result.examples.length} exemple(s) ${result.split}`;
    if (!result.examples.length) {
      classExamples.className = "example-grid empty-state";
      classExamples.textContent = "Aucun exemple trouve pour cette classe.";
      return;
    }
    classExamples.className = "example-grid";
    classExamples.innerHTML = result.examples.map((example) => `
      <figure class="example-card">
        <img src="${example.url}" alt="${result.class_name}">
        <figcaption>${example.image_name}</figcaption>
      </figure>
    `).join("");
    statusEl.textContent = `Exemples charges pour ${result.class_name}.`;
  } catch (error) {
    classExampleMeta.textContent = "Erreur exemples.";
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function loadLegendSymbols() {
  setBusy(true, "Chargement des symboles de legende...");
  try {
    const result = await fetchJson("/api/legend-symbols");
    const symbols = result.symbols || [];
    if (!symbols.length) {
      legendSymbolsGrid.className = "legend-symbol-grid empty-state";
      legendSymbolsGrid.textContent = result.warning || "Aucun symbole de legende trouve.";
      visualAtlasMeta.textContent = "Aucun symbole.";
      return;
    }
    visualAtlasMeta.textContent = `${symbols.length} symbole(s) de legende.`;
    legendSymbolsGrid.className = "legend-symbol-grid";
    legendSymbolsGrid.innerHTML = symbols.map((symbol) => `
      <button class="legend-symbol-card" type="button" data-path="${symbol.path}" data-label="${symbol.label}">
        <img src="${symbol.url}" alt="${symbol.label}">
        <strong>${symbol.id.replace("symbol_", "Symbole ")}</strong>
      </button>
    `).join("");
    legendSymbolsGrid.querySelectorAll(".legend-symbol-card").forEach((button) => {
      button.addEventListener("click", () => {
        state.selectedLegendSymbol = {
          path: button.dataset.path,
          label: button.dataset.label,
        };
        legendSymbolsGrid.querySelectorAll(".legend-symbol-card").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        loadVisualMatches();
      });
    });
    statusEl.textContent = "Symboles de legende charges. Clique un symbole pour voir ses representations plan.";
  } catch (error) {
    visualAtlasMeta.textContent = "Chargement symboles echoue.";
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function loadVisualMatches() {
  if (!state.selectedLegendSymbol) {
    statusEl.textContent = "Selectionne un symbole de legende.";
    return;
  }
  if (!cocoDatasetSelect.value) {
    statusEl.textContent = "Selectionne d'abord le dataset COCO dans Verifier dataset segmentation.";
    return;
  }
  setBusy(true, "Recherche visuelle des representations dans le plan...");
  try {
    const result = await fetchJson("/api/symbol-matches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        legend_path: state.selectedLegendSymbol.path,
        dataset_path: cocoDatasetSelect.value,
        split: visualMatchSplitSelect.value,
        limit: Number(visualMatchLimitInput.value || 12),
        scan_limit: 3000,
      }),
    });
    visualMatchTitle.textContent = state.selectedLegendSymbol.label;
    visualMatchMeta.textContent = `${result.matches.length} exemple(s), ${result.scanned} annotations scannees`;
    if (!result.matches.length) {
      visualMatchesGrid.className = "example-grid empty-state";
      visualMatchesGrid.textContent = "Aucune representation proche trouvee.";
      return;
    }
    visualMatchesGrid.className = "example-grid";
    visualMatchesGrid.innerHTML = result.matches.map((match) => `
      <figure class="example-card visual-match-card">
        <img src="${match.url}" alt="Representation plan">
        <figcaption>
          <strong>score ${match.score.toFixed(2)}</strong>
          <span>${match.class_name}</span>
        </figcaption>
      </figure>
    `).join("");
    statusEl.textContent = "Representations visuelles chargees. Verifie si elles appartiennent vraiment au meme symbole.";
  } catch (error) {
    visualMatchMeta.textContent = "Recherche visuelle echouee.";
    statusEl.textContent = error.message;
  } finally {
    setBusy(false);
  }
}

dpiInput.addEventListener("input", () => {
  dpiValue.textContent = dpiInput.value;
});
previewZoomInput.addEventListener("input", () => {
  previewZoomValue.textContent = previewZoomInput.value;
  renderPreview();
});
tileMarginInput.addEventListener("input", () => {
  tileMarginValue.textContent = tileMarginInput.value;
});
[rowsInput, colsInput].forEach((input) => {
  input.addEventListener("input", () => {
    applyGridBox();
    if (state.preview) {
      gridMeta.textContent = `${rowsInput.value} x ${colsInput.value} - zone ${Math.round(state.roi.w * 100)}% x ${Math.round(state.roi.h * 100)}%`;
    }
  });
});
resetGridButton.addEventListener("click", () => {
  state.roi = { x: 0, y: 0, w: 1, h: 1 };
  state.selectedGridCell = null;
  renderPreview();
});
tileZoomSelect.addEventListener("change", renderSelectedTile);
pixelSharpInput.addEventListener("change", renderSelectedTile);
templateModeButton.addEventListener("click", () => {
  state.templateMode = !state.templateMode;
  templateModeButton.classList.toggle("active", state.templateMode);
  statusEl.textContent = state.templateMode
    ? "Tire un rectangle autour du symbole dans l'image Original."
    : "Selection de symbole desactivee.";
});
detectThresholdInput.addEventListener("input", () => {
  detectThresholdValue.textContent = Number(detectThresholdInput.value).toFixed(2);
});
segScoreInput.addEventListener("input", () => {
  segScoreValue.textContent = Number(segScoreInput.value).toFixed(2);
});
detectButton.addEventListener("click", detectCurrentTile);
detectRedButton.addEventListener("click", detectRedSymbols);
refreshSegButton.addEventListener("click", loadSegCheckpoints);
segmentTileButton.addEventListener("click", segmentCurrentTile);
loadCocoSampleButton.addEventListener("click", loadCocoSample);
loadClassesButton.addEventListener("click", loadClassSummary);
loadLegendSymbolsButton.addEventListener("click", loadLegendSymbols);
uploadButton.addEventListener("click", uploadPdf);
previewButton.addEventListener("click", loadPreview);
renderButton.addEventListener("click", renderGrid);

setBusy(false);
loadSegCheckpoints();
loadCocoDatasets();
