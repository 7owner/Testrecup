const splitSelect = document.getElementById("splitSelect");
const imageSelect = document.getElementById("imageSelect");
const categorySelect = document.getElementById("categorySelect");
const prevButton = document.getElementById("prevButton");
const nextButton = document.getElementById("nextButton");
const finishPolygonButton = document.getElementById("finishPolygonButton");
const undoPointButton = document.getElementById("undoPointButton");
const clearDraftButton = document.getElementById("clearDraftButton");
const saveButton = document.getElementById("saveButton");
const progress = document.getElementById("progress");
const annotationList = document.getElementById("annotationList");
const canvas = document.getElementById("annotCanvas");
const ctx = canvas.getContext("2d");

const state = {
  split: "train",
  images: [],
  categories: [],
  currentImageId: null,
  currentImage: null,
  currentImageElement: null,
  annotationsByImage: new Map(),
  draftPoints: [],
  scale: 1,
};

function categoryColor(categoryId) {
  const palette = ["#ef4444", "#2563eb", "#16a34a", "#d97706", "#9333ea", "#0891b2", "#be123c", "#4f46e5"];
  return palette[(categoryId - 1) % palette.length];
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function currentAnnotations() {
  return state.annotationsByImage.get(state.currentImageId) || [];
}

function setCurrentAnnotations(items) {
  state.annotationsByImage.set(state.currentImageId, items);
}

function renderProgress(meta) {
  progress.className = "item";
  progress.innerHTML = `
    <strong>${meta.split}</strong>
    <p>images: ${meta.image_count}</p>
    <p>images annotees: ${meta.annotated_images}</p>
    <p>annotations: ${meta.annotation_count}</p>
  `;
}

function renderCategorySelect(categories) {
  categorySelect.innerHTML = "";
  categories.forEach((category) => {
    const option = document.createElement("option");
    option.value = String(category.id);
    option.textContent = `${category.id} - ${category.name}`;
    categorySelect.appendChild(option);
  });
}

function renderImageSelect(images) {
  imageSelect.innerHTML = "";
  images.forEach((image) => {
    const option = document.createElement("option");
    option.value = String(image.id);
    option.textContent = `#${image.id} | ${image.file_name} | anns ${image.annotation_count}`;
    imageSelect.appendChild(option);
  });
}

function imageById(imageId) {
  return state.images.find((item) => item.id === imageId) || null;
}

function categoryName(categoryId) {
  const category = state.categories.find((item) => item.id === categoryId);
  return category ? category.name : `cat ${categoryId}`;
}

function renderAnnotationList() {
  annotationList.innerHTML = "";
  const annotations = currentAnnotations();
  if (!annotations.length) {
    annotationList.innerHTML = `<div class="empty">Aucune annotation sur cette image.</div>`;
    return;
  }
  annotations.forEach((annotation, index) => {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML = `
      <strong>#${index + 1} - ${categoryName(annotation.category_id)}</strong>
      <p>${annotation.segmentation.length} polygone(s)</p>
      <button class="button" type="button">Supprimer</button>
    `;
    item.querySelector("button").addEventListener("click", () => {
      const next = currentAnnotations().filter((_, itemIndex) => itemIndex !== index);
      setCurrentAnnotations(next);
      renderAnnotationList();
      drawCanvas();
    });
    annotationList.appendChild(item);
  });
}

function drawPolygon(points, color, fillAlpha = 0.15, lineWidth = 2) {
  if (!points.length) {
    return;
  }
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color + Math.round(fillAlpha * 255).toString(16).padStart(2, "0");
  ctx.lineWidth = lineWidth;
  ctx.beginPath();
  ctx.moveTo(points[0][0] * state.scale, points[0][1] * state.scale);
  for (let index = 1; index < points.length; index += 1) {
    ctx.lineTo(points[index][0] * state.scale, points[index][1] * state.scale);
  }
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

function drawDraft() {
  if (!state.draftPoints.length) {
    return;
  }
  ctx.save();
  ctx.strokeStyle = "#f97316";
  ctx.fillStyle = "#f97316";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(state.draftPoints[0][0] * state.scale, state.draftPoints[0][1] * state.scale);
  for (let index = 1; index < state.draftPoints.length; index += 1) {
    ctx.lineTo(state.draftPoints[index][0] * state.scale, state.draftPoints[index][1] * state.scale);
  }
  ctx.stroke();
  state.draftPoints.forEach(([x, y]) => {
    ctx.beginPath();
    ctx.arc(x * state.scale, y * state.scale, 4, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.restore();
}

function drawCanvas() {
  if (!state.currentImageElement) {
    return;
  }
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(state.currentImageElement, 0, 0, canvas.width, canvas.height);

  currentAnnotations().forEach((annotation) => {
    const color = categoryColor(annotation.category_id);
    annotation.segmentation.forEach((polygon) => {
      const points = [];
      for (let index = 0; index < polygon.length; index += 2) {
        points.push([polygon[index], polygon[index + 1]]);
      }
      drawPolygon(points, color);
    });
  });

  drawDraft();
}

async function loadCurrentImage() {
  state.currentImage = imageById(state.currentImageId);
  if (!state.currentImage) {
    return;
  }
  const image = new Image();
  image.src = state.currentImage.image_url;
  await new Promise((resolve, reject) => {
    image.onload = resolve;
    image.onerror = reject;
  });
  state.currentImageElement = image;

  const maxWidth = Math.min(window.innerWidth - 420, 1200);
  state.scale = Math.min(maxWidth / image.width, 1.0);
  canvas.width = Math.round(image.width * state.scale);
  canvas.height = Math.round(image.height * state.scale);
  state.draftPoints = [];
  renderAnnotationList();
  drawCanvas();
}

function canvasPoint(event) {
  const rect = canvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) / state.scale;
  const y = (event.clientY - rect.top) / state.scale;
  return [x, y];
}

function finishPolygon() {
  if (state.draftPoints.length < 3) {
    return;
  }
  const categoryId = Number(categorySelect.value);
  const polygon = [];
  state.draftPoints.forEach(([x, y]) => {
    polygon.push(Number(x.toFixed(2)), Number(y.toFixed(2)));
  });
  const next = currentAnnotations().slice();
  next.push({
    category_id: categoryId,
    segmentation: [polygon],
  });
  setCurrentAnnotations(next);
  state.draftPoints = [];
  renderAnnotationList();
  drawCanvas();
}

async function saveCurrentImage() {
  if (!state.currentImageId) {
    return;
  }
  saveButton.disabled = true;
  try {
    const payload = await fetchJson("/api/annotation-save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        split: state.split,
        image_id: state.currentImageId,
        annotations: currentAnnotations(),
      }),
    });
    hydrateState(payload);
    imageSelect.value = String(state.currentImageId);
    await loadCurrentImage();
  } finally {
    saveButton.disabled = false;
  }
}

function hydrateState(payload) {
  state.split = payload.split;
  state.images = payload.images || [];
  state.categories = payload.categories || [];
  state.annotationsByImage = new Map();
  state.images.forEach((image) => {
    state.annotationsByImage.set(image.id, (image.annotations || []).map((annotation) => ({
      category_id: annotation.category_id,
      segmentation: annotation.segmentation || [],
    })));
  });
  renderProgress(payload);
  renderCategorySelect(state.categories);
  renderImageSelect(state.images);
  if (!state.currentImageId || !imageById(state.currentImageId)) {
    state.currentImageId = state.images.length ? state.images[0].id : null;
  }
  if (state.currentImageId) {
    imageSelect.value = String(state.currentImageId);
  }
}

async function loadSplit(split) {
  const payload = await fetchJson(`/api/annotation-state?split=${encodeURIComponent(split)}`);
  hydrateState(payload);
  await loadCurrentImage();
}

function stepImage(delta) {
  const index = state.images.findIndex((image) => image.id === state.currentImageId);
  if (index < 0) {
    return;
  }
  const nextIndex = Math.max(0, Math.min(index + delta, state.images.length - 1));
  state.currentImageId = state.images[nextIndex].id;
  imageSelect.value = String(state.currentImageId);
  loadCurrentImage().catch(console.error);
}

canvas.addEventListener("click", (event) => {
  if (!state.currentImageElement) {
    return;
  }
  state.draftPoints.push(canvasPoint(event));
  drawCanvas();
});

finishPolygonButton.addEventListener("click", finishPolygon);
undoPointButton.addEventListener("click", () => {
  state.draftPoints.pop();
  drawCanvas();
});
clearDraftButton.addEventListener("click", () => {
  state.draftPoints = [];
  drawCanvas();
});
saveButton.addEventListener("click", () => {
  saveCurrentImage().catch((error) => {
    progress.className = "item";
    progress.innerHTML = `<strong>Erreur</strong><p>${error.message}</p>`;
  });
});
splitSelect.addEventListener("change", () => {
  loadSplit(splitSelect.value).catch(console.error);
});
imageSelect.addEventListener("change", () => {
  state.currentImageId = Number(imageSelect.value);
  loadCurrentImage().catch(console.error);
});
prevButton.addEventListener("click", () => stepImage(-1));
nextButton.addEventListener("click", () => stepImage(1));
canvas.addEventListener("dblclick", (event) => {
  event.preventDefault();
  finishPolygon();
});

loadSplit("train").catch((error) => {
  progress.className = "item";
  progress.innerHTML = `<strong>Erreur</strong><p>${error.message}</p>`;
});
