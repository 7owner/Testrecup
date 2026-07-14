const runtimeCards = document.getElementById("runtimeCards");
const datasetCards = document.getElementById("datasetCards");
const improvements = document.getElementById("improvements");
const runs = document.getElementById("runs");
const outputs = document.getElementById("outputs");
const runA = document.getElementById("runA");
const runB = document.getElementById("runB");
const compareButton = document.getElementById("compareButton");
const compareResult = document.getElementById("compareResult");
const pdfSelect = document.getElementById("pdfSelect");
const pagesInput = document.getElementById("pagesInput");
const extractButton = document.getElementById("extractButton");
const statusNode = document.getElementById("status");
const legendPreview = document.getElementById("legendPreview");
const objectsGrid = document.getElementById("objectsGrid");
const matchResult = document.getElementById("matchResult");

const state = {
  pdfs: [],
  legendResult: null,
  selectedObjectId: null,
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function currentPages() {
  return pagesInput.value.trim() || "1";
}

function setStatus(message) {
  statusNode.className = "item";
  statusNode.textContent = message;
}

function renderPdfSelect(items) {
  pdfSelect.innerHTML = "";
  if (!items.length) {
    const option = document.createElement("option");
    option.textContent = "Aucun PDF";
    option.value = "";
    pdfSelect.appendChild(option);
    return;
  }
  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.relative_path;
    option.textContent = `${item.name} | ${item.folder}`;
    pdfSelect.appendChild(option);
  });
}

function renderRuntime(runtime) {
  runtimeCards.innerHTML = "";
  const items = [
    { label: "Torch", value: runtime.torch || "absent" },
    { label: "Torchvision", value: runtime.torchvision || "absent" },
    { label: "MaskRCNN", value: runtime.maskrcnn_ready ? "pret" : "indisponible" },
    { label: "Python", value: runtime.python || "n/a" },
  ];
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<strong>${item.label}</strong><span>${item.value}</span>`;
    runtimeCards.appendChild(card);
  });
}

function renderDataset(dataset) {
  datasetCards.innerHTML = "";
  const template = document.createElement("div");
  template.className = "card";
  template.innerHTML = `<strong>Categories template</strong><span>${dataset.categories_template_count}</span>`;
  datasetCards.appendChild(template);

  dataset.splits.forEach((split) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <strong>${split.name}</strong>
      <span>images: ${split.images}</span><br>
      <span>annotations: ${split.annotations}</span><br>
      <span>images annotees: ${split.annotated_images}</span><br>
      <span>categories: ${split.categories}</span>
    `;
    datasetCards.appendChild(card);
  });
}

function renderImprovements(items) {
  improvements.innerHTML = "";
  if (!items.length) {
    improvements.innerHTML = `<div class="empty">Aucune amelioration listee.</div>`;
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "item";
    row.innerHTML = `
      <span class="badge ${item.status}">${item.status}</span>
      <span class="badge">${item.area}</span>
      <strong class="impact-title">${item.title}</strong>
      <p><strong>Changement :</strong> ${item.change}</p>
      <p><strong>Impact :</strong> ${item.impact}</p>
      <p class="muted">${item.date}</p>
    `;
    improvements.appendChild(row);
  });
}

function renderRuns(items) {
  runs.innerHTML = "";
  runA.innerHTML = "";
  runB.innerHTML = "";

  if (!items.length) {
    runs.innerHTML = `<div class="empty">Aucun run trouve.</div>`;
    return;
  }

  items.forEach((item) => {
    [runA, runB].forEach((select) => {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = item.name;
      select.appendChild(option);
    });

    const row = document.createElement("div");
    row.className = "item";
    const curves = Object.entries(item.curve_urls || {})
      .map(([name, url]) => `<a href="${url}" target="_blank" rel="noreferrer">${name}</a>`)
      .join(" | ");
    row.innerHTML = `
      <strong>${item.name}</strong>
      <p><strong>Type :</strong> ${item.type}</p>
      <p><strong>best val loss :</strong> ${item.best_val_loss ?? "n/a"}</p>
      <p><strong>best val accuracy :</strong> ${item.best_val_accuracy ?? "n/a"}</p>
      <p><strong>classes :</strong> ${item.num_classes ?? "n/a"}</p>
      <p><strong>train/val samples :</strong> ${item.train_samples ?? "n/a"} / ${item.val_samples ?? "n/a"}</p>
      <p>${curves || "Pas de courbes."}</p>
    `;
    runs.appendChild(row);
  });

  if (items.length > 1) {
    runB.selectedIndex = 1;
  }
}

function renderOutputs(items) {
  outputs.innerHTML = "";
  if (!items.length) {
    outputs.innerHTML = `<div class="empty">Aucune sortie instance segmentation pour l'instant.</div>`;
    return;
  }

  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "item";
    const pages = item.pages.map((page) => `
      <div class="card">
        <strong>${page.name}</strong>
        <span>page ${page.page}</span><br>
        <span>instances: ${page.instance_count}</span><br>
        <span>${Object.entries(page.counts || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "aucun comptage"}</span>
        ${page.preview_url ? `<img class="preview" src="${page.preview_url}" alt="${page.name}">` : ""}
      </div>
    `).join("");
    row.innerHTML = `
      <strong>${item.name}</strong>
      <p><strong>pages :</strong> ${item.page_count}</p>
      <p><strong>instances :</strong> ${item.instance_count}</p>
      <div class="cards">${pages}</div>
    `;
    outputs.appendChild(row);
  });
}

function renderLegendResult(result) {
  state.legendResult = result;
  state.selectedObjectId = null;
  objectsGrid.innerHTML = "";
  matchResult.className = "empty";
  matchResult.textContent = "Selectionne un objet puis lance une recherche.";

  if (!result) {
    legendPreview.className = "preview-wrap empty";
    legendPreview.textContent = "Aucun apercu.";
    return;
  }

  legendPreview.className = "preview-wrap";
  legendPreview.innerHTML = `<img class="preview" src="${result.preview_url}" alt="Legend preview">`;

  result.objects.forEach((item) => {
    const card = document.createElement("div");
    card.className = `object-card${state.selectedObjectId === item.id ? " active" : ""}`;
    card.innerHTML = `
      <div class="object-images">
        <img src="${item.crop_url}" alt="${item.label}">
        <img src="${item.binary_crop_url}" alt="${item.label} binaire">
      </div>
      <div class="object-meta">
        <strong>${item.label}</strong>
        <span>${item.id}</span>
        <span>page ${item.page}</span>
        <span>score ${item.symbol_score ?? "n/a"}</span>
        <div class="actions">
          <button class="button primary direct-btn" type="button">Recherche directe</button>
          <button class="button kmeans-btn" type="button">KMeans strict</button>
        </div>
      </div>
    `;
    card.querySelector(".direct-btn").addEventListener("click", () => {
      state.selectedObjectId = item.id;
      runObjectMatch(item, "direct");
    });
    card.querySelector(".kmeans-btn").addEventListener("click", () => {
      state.selectedObjectId = item.id;
      runObjectMatch(item, "kmeans_strict");
    });
    objectsGrid.appendChild(card);
  });
}

function renderMatchPayload(result) {
  if (!result) {
    matchResult.className = "empty";
    matchResult.textContent = "Aucun resultat.";
    return;
  }

  const pages = result.pages.map((page) => `
    <div class="item">
      <strong>Page ${page.page}</strong>
      <p><strong>Correspondances :</strong> ${page.match_count}</p>
      ${page.candidate_count !== undefined ? `<p><strong>Composants extraits :</strong> ${page.candidate_count}</p>` : ""}
      ${page.counted_items_url ? `<p><a href="${page.counted_items_url}" target="_blank" rel="noreferrer">Voir tous les elements comptes</a></p>` : ""}
      ${page.preview_url ? `<img class="preview" src="${page.preview_url}" alt="resultat page ${page.page}">` : ""}
    </div>
  `).join("");

  matchResult.className = "stack";
  matchResult.innerHTML = `
    <div class="item">
      <strong>${result.label}</strong>
      <p><strong>Mode :</strong> ${result.mode === "kmeans_strict" ? "KMeans strict" : "direct"}</p>
      <p><strong>Total :</strong> ${result.total_matches}</p>
    </div>
    ${pages}
  `;
}

async function compareRuns() {
  if (!runA.value || !runB.value) {
    compareResult.textContent = "Choisis deux runs.";
    return;
  }
  const payload = await fetchJson(`/api/compare?a=${encodeURIComponent(runA.value)}&b=${encodeURIComponent(runB.value)}`);
  compareResult.className = "item";
  compareResult.innerHTML = `
    <strong>${payload.from} -> ${payload.to}</strong>
    <p><strong>Delta best val loss :</strong> ${payload.delta_best_val_loss ?? "n/a"}</p>
    <p><strong>Delta best val accuracy :</strong> ${payload.delta_best_val_accuracy ?? "n/a"}</p>
    <p><strong>Delta train samples :</strong> ${payload.delta_train_samples ?? "n/a"}</p>
    <p><strong>Delta val samples :</strong> ${payload.delta_val_samples ?? "n/a"}</p>
  `;
}

async function extractLegend() {
  if (!pdfSelect.value) {
    setStatus("Choisis un PDF.");
    return;
  }
  extractButton.disabled = true;
  setStatus(`Extraction de la legende sur page(s) ${currentPages()}...`);
  try {
    const payload = await fetchJson("/api/extract-legend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pdf_path: pdfSelect.value,
        pages: currentPages(),
      }),
    });
    renderLegendResult(payload.result);
    setStatus(`${payload.result.legend_object_count} objets detectes sur la page ${payload.result.legend_page}.`);
  } catch (error) {
    renderLegendResult(null);
    setStatus(error.message);
  } finally {
    extractButton.disabled = false;
  }
}

async function runObjectMatch(item, mode) {
  if (!pdfSelect.value || !state.legendResult) {
    return;
  }
  setStatus(`${mode === "kmeans_strict" ? "KMeans strict" : "Recherche directe"} de "${item.label}" en cours...`);
  matchResult.className = "empty";
  matchResult.textContent = "Calcul en cours...";
  try {
    const payload = await fetchJson("/api/match-object", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pdf_path: pdfSelect.value,
        pages: currentPages(),
        mode,
        object: {
          ...item,
          selected_pages: [state.legendResult.legend_page],
        },
      }),
    });
    renderMatchPayload(payload.result);
    setStatus(`${payload.result.total_matches} correspondances pour "${item.label}".`);
  } catch (error) {
    matchResult.className = "empty";
    matchResult.textContent = error.message;
    setStatus(error.message);
  }
}

async function boot() {
  const [statePayload, pdfPayload] = await Promise.all([fetchJson("/api/state"), fetchJson("/api/pdfs")]);
  state.pdfs = pdfPayload.pdfs || [];
  renderPdfSelect(state.pdfs);
  renderRuntime(statePayload.runtime);
  renderDataset(statePayload.dataset);
  renderImprovements(statePayload.improvements || []);
  renderRuns(statePayload.training_runs || []);
  renderOutputs(statePayload.instance_outputs || []);
}

compareButton.addEventListener("click", () => {
  compareRuns().catch((error) => {
    compareResult.className = "empty";
    compareResult.textContent = error.message;
  });
});

extractButton.addEventListener("click", () => {
  extractLegend().catch((error) => {
    setStatus(error.message);
  });
});

boot().catch((error) => {
  setStatus(error.message);
});
