const elements = {
  portPath: document.getElementById('portPath'),
  baudRate: document.getElementById('baudRate'),
  unitId: document.getElementById('unitId'),
  registerType: document.getElementById('registerType'),
  startAddress: document.getElementById('startAddress'),
  registerCount: document.getElementById('registerCount'),
  powerAddress: document.getElementById('powerAddress'),
  energyAddress: document.getElementById('energyAddress'),
  totalEnergyAddress: document.getElementById('totalEnergyAddress'),
  readBtn: document.getElementById('readBtn'),
  scanBtn: document.getElementById('scanBtn'),
  iem3250Btn: document.getElementById('iem3250Btn'),
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
  iem3250Body: document.getElementById('iem3250Body'),
};

let timer = null;

elements.readBtn?.addEventListener('click', () => readNow());
elements.scanBtn?.addEventListener('click', () => scanNow());
elements.iem3250Btn?.addEventListener('click', () => readIem3250Profile());
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
  const parsedStartAddress = parseRegisterAddress(elements.startAddress.value);
  if (!Number.isFinite(parsedStartAddress) || parsedStartAddress < 0) {
    setMessage('Adresse de depart invalide (ex: 3060 ou 0x0BF4).', 'err');
    return;
  }
  const payload = {
    portPath: elements.portPath.value.trim(),
    baudRate: Number(elements.baudRate.value || 19200),
    unitId: Number(elements.unitId.value || 1),
    registerType: elements.registerType.value,
    startAddress: parsedStartAddress,
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
    // Toujours enrichir avec les mesures iEM3250 (puissance/energie/etc.)
    await readIem3250Profile({ silent: true });
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

async function readIem3250Profile(options = {}) {
  const silent = Boolean(options?.silent);
  if (!silent) setMessage('Lecture profil Schneider iEM3250...', '');
  const powerRegister = parseRegisterAddress(elements.powerAddress?.value);
  const energyRegister = parseRegisterAddress(elements.energyAddress?.value);
  const totalEnergyRegisterRaw = parseRegisterAddress(elements.totalEnergyAddress?.value);
  const totalEnergyRegister = Number.isFinite(totalEnergyRegisterRaw) ? totalEnergyRegisterRaw : energyRegister;
  if (!Number.isFinite(powerRegister) || !Number.isFinite(energyRegister)) {
    if (!silent) setMessage('Adresses puissance/energie invalides (ex: 0x0BF4, 0x0C56).', 'err');
    return;
  }
  const basePayload = {
    portPath: elements.portPath.value.trim(),
    baudRate: Number(elements.baudRate.value || 19200),
    unitId: Number(elements.unitId.value || 5),
    registerCount: 2,
  };

  // Source: Schneider DOCA0005EN-15 (iEM3200/iEM3250), valeurs float32.
  // Le "register" visible dans la table peut necessiter un offset -1 en trame Modbus.
  const probes = [
    { key: 'Courant L1', unit: 'A', register: 3000, min: 0, max: 2500 },
    { key: 'Courant L2', unit: 'A', register: 3002, min: 0, max: 2500 },
    { key: 'Courant L3', unit: 'A', register: 3004, min: 0, max: 2500 },
    { key: 'Tension L1-N', unit: 'V', register: 3028, min: 80, max: 300 },
    { key: 'Tension L2-N', unit: 'V', register: 3030, min: 80, max: 300 },
    { key: 'Tension L3-N', unit: 'V', register: 3032, min: 80, max: 300 },
    { key: 'Puissance active totale', unit: 'kW', register: powerRegister, min: -10000, max: 10000, kind: 'power' },
    { key: 'Frequence', unit: 'Hz', register: 3110, min: 40, max: 70 },
    { key: 'Energie active importee', unit: 'kWh', register: energyRegister, min: 0, max: 1_000_000_000, kind: 'energy' },
    { key: 'Energie active totale', unit: 'kWh', register: totalEnergyRegister, min: 0, max: 1_000_000_000, kind: 'energy' },
  ];

  // Profil: toujours tester les 2 fonctions Modbus (0x03 puis 0x04 ou inverse)
  // car certains iEM3250 n'exposent pas les memes blocs selon firmware/config.
  const selectedType = String(elements.registerType.value || '').toLowerCase() === 'input' ? 'input' : 'holding';
  const typeOrder = selectedType === 'holding'
    ? ['holding', 'input']
    : ['input', 'holding'];

  const rows = [];
  for (const probe of probes) {
    const result = await readMetricWithFallback(basePayload, probe, typeOrder);
    rows.push({
      label: probe.key,
      metricKey: probe.key,
      unit: probe.unit,
      numericValue: result.ok ? Number(result.value) : null,
      value: result.ok ? `${formatValue(result.value)} ${probe.unit}` : 'Non trouve',
      details: result.ok
        ? `${result.registerType}@${result.address} [0x${result.address.toString(16).toUpperCase()}] (${result.codec})`
        : (result.error || '--'),
    });
  }

  const importRow = rows.find((r) => r.metricKey === 'Energie active importee');
  const totalRow = rows.find((r) => r.metricKey === 'Energie active totale');
  let totalConso = null;
  let source = 'import';
  if (totalRow && Number.isFinite(totalRow.numericValue) && totalRow.numericValue >= 0) {
    totalConso = totalRow.numericValue;
    source = 'totale';
  }
  if (
    importRow &&
    Number.isFinite(importRow.numericValue) &&
    importRow.numericValue >= 0 &&
    (!Number.isFinite(totalConso) || totalConso > importRow.numericValue * 100)
  ) {
    totalConso = importRow.numericValue;
    source = 'import';
  }
  if (Number.isFinite(totalConso)) {
    rows.push({
      label: 'Consommation totale',
      value: `${formatValue(totalConso)} kWh`,
      details: source === 'totale' ? 'source: energie active totale' : 'source: energie active importee',
    });
  }

  renderIem3250Rows(rows);
  const okCount = rows.filter((x) => x.value !== 'Non trouve').length;
  if (!silent) {
    if (okCount > 0) {
      setMessage(`Profil iEM3250 lu: ${okCount}/${rows.length} mesure(s) detectee(s).`, 'ok');
    } else {
      setMessage('Aucune mesure iEM3250 detectee. Teste ID, type (Input/Holding), et adresses.', 'err');
    }
  }
}

async function readMetricWithFallback(basePayload, probe, typeOrder) {
  const addresses = [probe.register - 1, probe.register];
  const attempts = [];
  for (const registerType of typeOrder) {
    for (const address of addresses) {
      try {
        const res = await fetch('/backend/rs485/read', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...basePayload,
            registerType,
            startAddress: address,
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          attempts.push(`${registerType}@${address}: HTTP ${res.status}`);
          continue;
        }
        const regs = data?.data?.registers || [];
        if (regs.length < 2) {
          attempts.push(`${registerType}@${address}: registre<2`);
          continue;
        }
        const decoded = decodeMetricCandidates(regs[0], regs[1], probe);
        if (!decoded.ok) {
          const rawU32 = toUint32(regs[0], regs[1]);
          // fallback brut si la lecture répond mais sans décodage exploitable
          return {
            ok: true,
            value: rawU32,
            codec: 'raw_u32',
            registerType,
            address,
          };
        }
        return {
          ok: true,
          value: decoded.value,
          codec: decoded.codec,
          registerType,
          address,
        };
      } catch (error) {
        attempts.push(`${registerType}@${address}: ${error.message || 'error'}`);
      }
    }
  }
  return { ok: false, error: attempts[attempts.length - 1] || 'aucune reponse' };
}

function decodeFloat32Candidates(r0, r1, min, max) {
  return decodeMetricCandidates(r0, r1, { min, max, kind: 'generic' });
}

function decodeMetricCandidates(r0, r1, probe) {
  const min = Number(probe?.min ?? 0);
  const max = Number(probe?.max ?? 1e12);
  const kind = String(probe?.kind || 'generic');
  const u32 = toUint32(r0, r1);
  const u32sw = toUint32(r1, r0);
  const f32 = toFloat32FromWords(r0, r1);
  const f32sw = toFloat32FromWords(r1, r0);
  const allCandidates = [
    { codec: 'float32_be', value: f32 },
    { codec: 'float32_sw', value: f32sw },
    { codec: 'uint32', value: u32 },
    { codec: 'uint32_div10', value: u32 / 10 },
    { codec: 'uint32_div100', value: u32 / 100 },
    { codec: 'uint32_div1000', value: u32 / 1000 },
    { codec: 'uint32_sw', value: u32sw },
    { codec: 'uint32_sw_div10', value: u32sw / 10 },
    { codec: 'uint32_sw_div100', value: u32sw / 100 },
    { codec: 'uint32_sw_div1000', value: u32sw / 1000 },
  ];

  // Priorite par type de mesure pour eviter les faux zero float.
  const priorityByKind = {
    energy: ['uint32_div10', 'uint32_div100', 'uint32_div1000', 'uint32_sw_div10', 'uint32_sw_div100', 'uint32_sw_div1000', 'uint32', 'uint32_sw', 'float32_be', 'float32_sw'],
    power: ['float32_be', 'float32_sw', 'uint32_div10', 'uint32_div100', 'uint32_sw_div10', 'uint32_sw_div100', 'uint32', 'uint32_sw'],
    generic: ['float32_be', 'float32_sw', 'uint32_div10', 'uint32_div100', 'uint32_div1000', 'uint32_sw_div10', 'uint32_sw_div100', 'uint32_sw_div1000', 'uint32', 'uint32_sw'],
  };
  const order = priorityByKind[kind] || priorityByKind.generic;
  const candidates = order
    .map((codec) => allCandidates.find((x) => x.codec === codec))
    .filter(Boolean);

  const inRange = candidates.find((c) => {
    if (!Number.isFinite(c.value)) return false;
    if (c.value < min || c.value > max) return false;
    // Evite les denormals float32 (~1e-45) qui s'affichent en 0.00
    if (Math.abs(c.value) > 0 && Math.abs(c.value) < 1e-6) return false;
    return true;
  });
  if (inRange) return { ok: true, ...inRange };
  const fallback = candidates.find((c) => Number.isFinite(c.value) && Math.abs(c.value) < 1e12);
  if (fallback) return { ok: true, ...fallback, codec: `${fallback.codec}_fallback` };
  return { ok: false };
}

function toUint32(hi, lo) {
  const a = Number(hi || 0) & 0xffff;
  const b = Number(lo || 0) & 0xffff;
  return (a * 65536) + b;
}

function toFloat32FromWords(hi, lo) {
  const a = Number(hi || 0) & 0xffff;
  const b = Number(lo || 0) & 0xffff;
  const buf = new ArrayBuffer(4);
  const view = new DataView(buf);
  view.setUint16(0, a, false);
  view.setUint16(2, b, false);
  return view.getFloat32(0, false);
}

function formatValue(v) {
  if (!Number.isFinite(v)) return '--';
  return Number(v).toLocaleString('fr-FR', { maximumFractionDigits: 2 });
}

function parseRegisterAddress(rawValue) {
  const s = String(rawValue || '').trim();
  if (!s) return NaN;
  if (/^0x[0-9a-f]+$/i.test(s)) return parseInt(s, 16);
  return Number(s);
}

function renderIem3250Rows(rows) {
  if (!elements.iem3250Body) return;
  elements.iem3250Body.innerHTML = rows
    .map((r) => `
      <tr>
        <td>${escapeHtml(String(r.label || ''))}</td>
        <td>${escapeHtml(String(r.value || ''))} <span style="opacity:.7">(${escapeHtml(String(r.details || '--'))})</span></td>
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
