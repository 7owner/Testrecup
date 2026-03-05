const elements = {
  portPath: document.getElementById('portPath'),
  baudRate: document.getElementById('baudRate'),
  unitId: document.getElementById('unitId'),
  registerType: document.getElementById('registerType'),
  startAddress: document.getElementById('startAddress'),
  registerCount: document.getElementById('registerCount'),
  readBtn: document.getElementById('readBtn'),
  scanBtn: document.getElementById('scanBtn'),
  legrandBtn: document.getElementById('legrandBtn'),
  legrandProfile: document.getElementById('legrandProfile'),
  autoRefresh: document.getElementById('autoRefresh'),
  idStart: document.getElementById('idStart'),
  idEnd: document.getElementById('idEnd'),
  addressStart: document.getElementById('addressStart'),
  addressEnd: document.getElementById('addressEnd'),
  perReadCount: document.getElementById('perReadCount'),
  maxMatches: document.getElementById('maxMatches'),
  lastRead: document.getElementById('lastRead'),
  message: document.getElementById('message'),
  regsBody: document.getElementById('regsBody'),
  scanBody: document.getElementById('scanBody'),
  legrandBody: document.getElementById('legrandBody'),
};

let timer = null;

elements.readBtn?.addEventListener('click', () => readNow());
elements.scanBtn?.addEventListener('click', () => scanNow());
elements.legrandBtn?.addEventListener('click', () => readLegrandProfile(elements.legrandProfile?.value || '412040'));
elements.autoRefresh?.addEventListener('change', () => {
  if (elements.autoRefresh.checked) {
    timer = setInterval(readNow, 5000);
    readNow();
    return;
  }
  if (timer) clearInterval(timer);
  timer = null;
});

async function readNow() {
  setMessage('Lecture en cours...', '');
  const payload = {
    portPath: elements.portPath.value.trim(),
    baudRate: Number(elements.baudRate.value || 19200),
    unitId: Number(elements.unitId.value || 5),
    registerType: elements.registerType.value,
    startAddress: Number(elements.startAddress.value || 0),
    registerCount: Number(elements.registerCount.value || 10),
  };

  try {
    const res = await fetch('/backend/rs485/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data?.message || 'Erreur lecture RS485');
    }
    renderRegisters(data?.data?.registers || [], data?.data?.registersHex || []);
    elements.lastRead.textContent = new Date(data?.data?.timestamp || Date.now()).toLocaleTimeString();
    setMessage(`Lecture OK sur ${payload.portPath} (ID ${payload.unitId})`, 'ok');
  } catch (error) {
    setMessage(error.message, 'err');
  }
}

async function scanNow() {
  setMessage('Scan en cours... (peut prendre 10-60s)', '');
  const payload = {
    portPath: elements.portPath.value.trim(),
    baudRate: Number(elements.baudRate.value || 19200),
    registerType: elements.registerType.value,
    timeoutMs: 1000,
    idStart: Number(elements.idStart.value || 1),
    idEnd: Number(elements.idEnd.value || 20),
    addressStart: Number(elements.addressStart.value || 0),
    addressEnd: Number(elements.addressEnd.value || 30),
    perReadCount: Number(elements.perReadCount.value || 1),
    maxMatches: Number(elements.maxMatches.value || 20),
  };

  try {
    const res = await fetch('/backend/rs485/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.message || 'Erreur scan RS485');
    renderScanMatches(data?.data?.matches || []);
    const tries = Number(data?.data?.tries || 0);
    const ms = Number(data?.data?.durationMs || 0);
    setMessage(`Scan terminé: ${data?.data?.matches?.length || 0} réponse(s), ${tries} essais, ${ms} ms`, 'ok');
  } catch (error) {
    setMessage(error.message, 'err');
  }
}

function renderRegisters(registers, registersHex) {
  if (!elements.regsBody) return;
  elements.regsBody.innerHTML = registers
    .map((value, index) => `
      <tr>
        <td>${index}</td>
        <td>${Number(value)}</td>
        <td>${registersHex[index] || ''}</td>
      </tr>
    `)
    .join('');
}

function renderScanMatches(matches) {
  if (!elements.scanBody) return;
  elements.scanBody.innerHTML = matches
    .map((row) => `
      <tr>
        <td>${Number(row.unitId)}</td>
        <td>${Number(row.address)}</td>
        <td>${String(row.registerType || '')}</td>
        <td>${Array.isArray(row.values) ? row.values.join(', ') : ''}</td>
      </tr>
    `)
    .join('');
}

function setMessage(text, cls) {
  if (!elements.message) return;
  elements.message.textContent = text || '';
  elements.message.className = `msg ${cls || ''}`.trim();
}

async function readLegrandProfile(profileCode) {
  setMessage(`Lecture profil Legrand ${profileCode}...`, '');
  const base = {
    portPath: elements.portPath.value.trim(),
    baudRate: Number(elements.baudRate.value || 19200),
    unitId: Number(elements.unitId.value || 5),
    registerType: 'holding',
    registerCount: 2,
  };

  const probes = getLegrandProbes(profileCode);

  const rows = [];
  for (const p of probes) {
    try {
      const res = await fetch('/backend/rs485/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...base,
          startAddress: p.address,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        rows.push({ label: p.key, value: `Erreur (${data?.message || res.status})` });
        continue;
      }
      const regs = data?.data?.registers || [];
      const raw = toUint32(regs[0], regs[1]);
      const val = raw * p.scale;
      rows.push({ label: p.key, value: `${formatValue(val)} ${p.unit}` });
    } catch (error) {
      rows.push({ label: p.key, value: `Erreur (${error.message})` });
    }
  }

  renderLegrandRows(rows);
  const okCount = rows.filter((r) => !String(r.value).startsWith('Erreur')).length;
  if (okCount > 0) {
    setMessage(`Profil ${profileCode} lu (${okCount}/${rows.length})`, 'ok');
  } else {
    setMessage(`Aucune réponse sur le profil ${profileCode}. Vérifier ID/port/type de registres.`, 'err');
  }
}

function getLegrandProbes(profileCode) {
  // 412040 et 412041 partagent une base EMDX3 proche.
  // On utilise des adresses candidates adaptables.
  const common = [
    { key: 'Heures fonctionnement', address: 50512, scale: 1, unit: 'h' },
    { key: 'Tension U12', address: 50514, scale: 0.01, unit: 'V' },
    { key: 'Tension U23', address: 50516, scale: 0.01, unit: 'V' },
    { key: 'Tension U31', address: 50518, scale: 0.01, unit: 'V' },
    { key: 'Tension V1', address: 50520, scale: 0.01, unit: 'V' },
    { key: 'Tension V2', address: 50522, scale: 0.01, unit: 'V' },
    { key: 'Tension V3', address: 50524, scale: 0.01, unit: 'V' },
  ];

  if (String(profileCode) === '412040') {
    return [
      ...common,
      { key: 'Courant I1', address: 50526, scale: 0.001, unit: 'A' },
      { key: 'Courant I2', address: 50528, scale: 0.001, unit: 'A' },
      { key: 'Courant I3', address: 50530, scale: 0.001, unit: 'A' },
    ];
  }

  return common;
}

function toUint32(hi, lo) {
  const a = Number(hi || 0) & 0xffff;
  const b = Number(lo || 0) & 0xffff;
  return (a * 65536) + b;
}

function formatValue(v) {
  if (!Number.isFinite(v)) return '--';
  return Number(v).toLocaleString('fr-FR', { maximumFractionDigits: 2 });
}

function renderLegrandRows(rows) {
  if (!elements.legrandBody) return;
  elements.legrandBody.innerHTML = rows
    .map((r) => `
      <tr>
        <td>${escapeHtml(String(r.label || ''))}</td>
        <td>${escapeHtml(String(r.value || ''))}</td>
      </tr>
    `)
    .join('');
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
