const state = {
  pdfs: [],
  selectedPdf: null,
  result: null,
  selectedObjectId: null,
  selectedMatchMode: null,
  matchResult: null,
  matchJobId: null,
  matchJobStatus: null,
};

const pdfList = document.getElementById("pdfList");
const uploadInput = document.getElementById("uploadInput");
const uploadButton = document.getElementById("uploadButton");
const searchInput = document.getElementById("searchInput");
const title = document.getElementById("title");
const meta = document.getElementById("meta");
const pagesInput = document.getElementById("pagesInput");
const extractButton = document.getElementById("extractButton");
const vectorButton = document.getElementById("vectorButton");
const summary = document.getElementById("summary");
const status = document.getElementById("status");
const previewWrap = document.getElementById("previewWrap");
const objectsGrid = document.getElementById("objectsGrid");
const jsonLink = document.getElementById("jsonLink");
const matchContent = document.getElementById("matchContent");

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function renderPdfList() {
  const query = searchInput.value.trim().toLowerCase();
  const items = state.pdfs.filter((item) => {
    if (!query) {
      return true;
    }
    return `${item.folder} ${item.name}`.toLowerCase().includes(query);
  });

  pdfList.innerHTML = "";
  if (!items.length) {
    pdfList.innerHTML = `<div class="empty-list">Aucun PDF</div>`;
    return;
  }

  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `list-item${state.selectedPdf?.relative_path === item.relative_path ? " active" : ""}`;
    button.innerHTML = `
      <strong>${item.title}</strong>
      <span>${item.folder || "."}</span>
      <span>${item.source === "upload" ? "upload" : "depot"}</span>
    `;
    button.addEventListener("click", () => {
      state.selectedPdf = item;
      state.result = null;
      state.selectedMatchMode = null;
      renderPdfList();
      renderSelectedPdf();
      renderResult();
    });
    pdfList.appendChild(button);
  });
}

function renderSelectedPdf() {
  if (!state.selectedPdf) {
    title.textContent = "Aucun PDF selectionne";
    meta.textContent = "Choisis un PDF puis lance l'extraction de legende.";
    return;
  }
  title.textContent = state.selectedPdf.title;
  meta.textContent = `${state.selectedPdf.relative_path} | ${state.selectedPdf.source === "upload" ? "upload" : "depot"}`;
}

function selectedPagesValue() {
  const value = pagesInput.value.trim();
  return value || "1";
}

function renderSummaryCards(result) {
  const values = [
    result ? result.pdf_path : "0",
    result ? String(result.legend_page) : "0",
    result ? String(result.legend_object_count) : "0",
  ];
  summary.querySelectorAll(".summary-card strong").forEach((node, index) => {
    node.textContent = values[index];
  });
}

function renderResult() {
  const result = state.result;
  renderSummaryCards(result);
  objectsGrid.innerHTML = "";
  previewWrap.innerHTML = "";
  jsonLink.classList.add("hidden");
  renderMatchResult();

  if (!result) {
    previewWrap.className = "preview-wrap empty";
    previewWrap.textContent = "Aucun apercu";
    status.textContent = "Aucune extraction lancee.";
    return;
  }

  const anchorText = result.legend_anchor_text ? ` sous la zone "${result.legend_anchor_text}"` : "";
  status.textContent = `${result.legend_object_count} objets detectes sur la page ${result.legend_page}${anchorText}.`;
  previewWrap.className = "preview-wrap";
  previewWrap.innerHTML = `<img src="${result.preview_url}" alt="Apercu legende">`;

  const jsonBlob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
  jsonLink.href = URL.createObjectURL(jsonBlob);
  jsonLink.classList.remove("hidden");

  result.objects.forEach((item) => {
    const card = document.createElement("article");
    card.className = `object-card${state.selectedObjectId === item.id ? " active" : ""}`;
    const color = Array.isArray(item.dominant_color) ? `rgb(${item.dominant_color.join(",")})` : "#cbd5e1";
    card.innerHTML = `
      <div class="object-images">
        <img src="${item.crop_url}" alt="${item.label}">
        <img src="${item.binary_crop_url}" alt="${item.label} binaire">
      </div>
      <div class="object-meta">
        <strong>${item.label}</strong>
        <span>${item.id}</span>
        <span>page ${item.page}</span>
        <span>${item.symbol_side || "?"} | score ${item.symbol_score ?? "n/a"}</span>
        <span>${item.symbol_size.width} x ${item.symbol_size.height}</span>
        <span>binaire ${item.binary_foreground_ratio ?? "n/a"}</span>
        <div class="color-chip">
          <span style="background:${color};"></span>
          ${Array.isArray(item.dominant_color) ? item.dominant_color.join(", ") : "n/a"}
        </div>
        <button class="button primary match-kmeans-button" type="button">${state.selectedObjectId === item.id && state.selectedMatchMode === "kmeans_strict" && (state.matchJobStatus === "queued" || state.matchJobStatus === "running") ? "KMeans..." : "KMeans strict"}</button>
        <button class="button match-button" type="button">${state.selectedObjectId === item.id && state.selectedMatchMode === "direct" && (state.matchJobStatus === "queued" || state.matchJobStatus === "running") ? "Recherche..." : "Comparer direct"}</button>
      </div>
    `;
    card.querySelector(".match-kmeans-button").addEventListener("click", () => {
      state.selectedObjectId = item.id;
      state.selectedMatchMode = "kmeans_strict";
      renderResult();
      runObjectMatch(item, "kmeans_strict");
    });
    card.querySelector(".match-button").addEventListener("click", () => {
      state.selectedObjectId = item.id;
      state.selectedMatchMode = "direct";
      renderResult();
      runObjectMatch(item, "direct");
    });
    card.addEventListener("click", () => {
      state.selectedObjectId = item.id;
      renderResult();
    });
    objectsGrid.appendChild(card);
  });
}

function renderMatchResult() {
  if (state.matchJobStatus === "queued" || state.matchJobStatus === "running") {
    matchContent.className = "match-content";
    matchContent.innerHTML = `
      <div class="match-summary">
        <strong>Recherche en cours</strong>
        <span>${state.matchJobStatus === "queued" ? "Job en attente..." : "Calcul en cours..."}</span>
      </div>
      <div class="match-progress"></div>
    `;
    return;
  }

  if (!state.matchResult) {
    matchContent.className = "match-content empty";
    matchContent.textContent = "Selectionne un objet puis lance sa recherche.";
    return;
  }

  matchContent.className = "match-content";
  const countedLinks = state.matchResult.pages
    .filter((page) => page.match_count > 0 && page.counted_items_url)
    .map((page) => `
      <a class="button primary small" href="${page.counted_items_url}" target="_blank" rel="noreferrer">
        Voir les ${page.match_count} elements comptes page ${page.page}
      </a>
    `)
    .join("");

  const pagesHtml = state.matchResult.pages
    .filter((page) => page.match_count > 0)
    .map((page) => `
      <article class="match-page">
        <div class="match-page-head">
          <strong>Page ${page.page}</strong>
          <span>${page.match_count} correspondances</span>
          ${page.candidate_count !== undefined ? `<span>${page.candidate_count} composants extraits</span>` : ""}
          ${page.counted_items_url ? `<a class="button ghost small" href="${page.counted_items_url}" target="_blank" rel="noreferrer">Voir tout ce qui a ete compte</a>` : `<span class="muted">Relance la recherche pour generer le detail.</span>`}
        </div>
        <img src="${page.preview_url}" alt="Page ${page.page}">
      </article>
    `)
    .join("");

  matchContent.innerHTML = `
    <div class="match-summary">
      <strong>${state.matchResult.label}</strong>
      <span>mode ${state.matchResult.mode === "kmeans_strict" ? "KMeans strict" : "direct"}</span>
      <span>${state.matchResult.total_matches} correspondances totales</span>
      <span>${state.matchResult.page_count} pages analysees</span>
    </div>
    ${countedLinks ? `<div class="counted-links">${countedLinks}</div>` : ""}
    <div class="match-pages">
      ${pagesHtml || `<div class="empty-list">Aucune correspondance trouvee.</div>`}
    </div>
  `;
}

async function loadPdfs() {
  const payload = await fetchJson("/api/pdfs");
  state.pdfs = payload.pdfs || [];
  if (state.selectedPdf) {
    const stillExists = state.pdfs.find((item) => item.relative_path === state.selectedPdf.relative_path);
    state.selectedPdf = stillExists || null;
  }
  renderPdfList();
  renderSelectedPdf();
}

async function runExtraction() {
  if (!state.selectedPdf) {
    status.textContent = "Choisis d'abord un PDF.";
    return;
  }
  extractButton.disabled = true;
  status.textContent = `Extraction en cours sur page(s) ${selectedPagesValue()}...`;
  try {
    const payload = await fetchJson("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pdf_path: state.selectedPdf.relative_path,
        pages: selectedPagesValue(),
      }),
    });
    state.result = payload.result;
    state.selectedObjectId = null;
    state.selectedMatchMode = null;
    state.matchResult = null;
    state.matchJobId = null;
    state.matchJobStatus = null;
    renderResult();
  } catch (error) {
    state.result = null;
    state.matchResult = null;
    state.matchJobId = null;
    state.matchJobStatus = null;
    renderResult();
    status.textContent = error.message;
  } finally {
    extractButton.disabled = false;
  }
}

function renderVectorInspection(result) {
  matchContent.className = "match-content";
  const pagesHtml = result.pages.map((page) => {
    const colors = Object.entries(page.color_counts || {})
      .map(([color, count]) => `<span>${color}: ${count}</span>`)
      .join("");
    const kinds = Object.entries(page.kind_counts || {})
      .map(([kind, count]) => `<span>${kind}: ${count}</span>`)
      .join("");
    return `
      <article class="match-page">
        <div class="match-page-head">
          <strong>Page ${page.page}</strong>
          <span>${page.primitive_count} primitives vectorielles</span>
          <span>separateur x: ${page.separator_x ?? "n/a"}</span>
        </div>
        <div class="vector-stats">
          <strong>Types</strong>
          <div>${kinds || "n/a"}</div>
          <strong>Couleurs</strong>
          <div>${colors || "n/a"}</div>
        </div>
        <img src="${page.preview_url}" alt="Inspection vecteurs page ${page.page}">
      </article>
    `;
  }).join("");
  matchContent.innerHTML = `
    <div class="match-summary">
      <strong>Inspection vectorielle PDF</strong>
      <span>${result.page_count} page(s) inspectee(s)</span>
    </div>
    <div class="match-pages">${pagesHtml}</div>
  `;
}

async function runVectorInspection() {
  if (!state.selectedPdf) {
    status.textContent = "Choisis d'abord un PDF.";
    return;
  }
  vectorButton.disabled = true;
  status.textContent = "Inspection vectorielle en cours...";
  try {
    const payload = await fetchJson("/api/vector-inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pdf_path: state.selectedPdf.relative_path,
        pages: selectedPagesValue(),
      }),
    });
    renderVectorInspection(payload.result);
    status.textContent = "Inspection vectorielle terminee.";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    vectorButton.disabled = false;
  }
}

async function runObjectMatch(item, mode = "direct") {
  if (!state.selectedPdf || !state.result) {
    return;
  }
  state.matchResult = null;
  state.matchJobId = null;
  state.matchJobStatus = "queued";
  renderMatchResult();
  status.textContent = mode === "kmeans_strict"
    ? `KMeans strict de "${item.label}" en cours...`
    : `Recherche directe de "${item.label}" en cours...`;
  try {
    const payload = await fetchJson("/api/match-object", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pdf_path: state.selectedPdf.relative_path,
        pages: selectedPagesValue(),
        mode,
        object: {
          ...item,
          selected_pages: [state.result.legend_page],
        },
      }),
    });
    state.matchJobId = payload.job_id;
    state.matchJobStatus = payload.status;
    renderResult();
    pollMatchJob(item.label);
  } catch (error) {
    state.matchResult = null;
    state.matchJobId = null;
    state.matchJobStatus = null;
    renderMatchResult();
    status.textContent = error.message;
  }
}

async function pollMatchJob(label) {
  if (!state.matchJobId) {
    return;
  }
  try {
    const payload = await fetchJson(`/api/job-status?id=${encodeURIComponent(state.matchJobId)}`);
    state.matchJobStatus = payload.status;
    if (payload.status === "done") {
      state.matchResult = payload.result;
      state.matchJobId = null;
      state.matchJobStatus = null;
      renderMatchResult();
      status.textContent = `${payload.result.total_matches} correspondances pour "${label}" (${payload.result.mode === "kmeans_strict" ? "KMeans strict" : "direct"}).`;
      renderResult();
      return;
    }
    if (payload.status === "error") {
      state.matchResult = null;
      state.matchJobId = null;
      state.matchJobStatus = null;
      renderMatchResult();
      status.textContent = payload.error || payload.message || "Erreur de recherche.";
      renderResult();
      return;
    }
    renderResult();
    window.setTimeout(() => pollMatchJob(label), 1000);
  } catch (error) {
    state.matchResult = null;
    state.matchJobId = null;
    state.matchJobStatus = null;
    renderMatchResult();
    status.textContent = error.message;
  }
}

async function uploadSelectedPdfs() {
  const files = Array.from(uploadInput.files || []);
  if (!files.length) {
    status.textContent = "Choisis un ou plusieurs PDF a uploader.";
    return;
  }
  uploadButton.disabled = true;
  status.textContent = `Upload de ${files.length} PDF...`;
  try {
    for (const file of files) {
      await fetchJson(`/api/upload?name=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/pdf" },
        body: await file.arrayBuffer(),
      });
    }
    uploadInput.value = "";
    await loadPdfs();
    status.textContent = `${files.length} PDF ajoutes.`;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    uploadButton.disabled = false;
  }
}

searchInput.addEventListener("input", renderPdfList);
extractButton.addEventListener("click", runExtraction);
vectorButton.addEventListener("click", runVectorInspection);
uploadButton.addEventListener("click", uploadSelectedPdfs);

loadPdfs().catch((error) => {
  status.textContent = error.message;
});
