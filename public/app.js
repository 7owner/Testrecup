import { connect, disconnect, poll, getSession } from './api.js';
import { createCharts, updateMonthPieChart, updateAnnualEnergyChart, updateStationChart, updateZonesChart, updateAccidentsChart } from './charts.js';

const elements = {
  form: document.getElementById('connect-form'),
  disconnectBtn: document.getElementById('disconnect-btn'),
  simulateBtn: document.getElementById('simulate-btn'),
  message: document.getElementById('api-message'),
  badge: document.getElementById('connection-badge'),
  weatherMini: document.getElementById('weather-mini'),
  wmLoc: document.getElementById('wm-loc'),
  wmCond: document.getElementById('wm-cond'),
  wmIcon: document.getElementById('wm-icon'),
  wmTemp: document.getElementById('wm-temp'),
  wmHours: document.getElementById('wm-hours'),
  weatherForm: document.getElementById('weather-form'),
  weatherClearBtn: document.getElementById('weather-clear-btn'),
  weatherSampleBtn: document.getElementById('weather-sample-btn'),
  weatherAdminMsg: document.getElementById('weather-admin-msg'),
  weatherLocation: document.getElementById('weatherLocation'),
  weatherTempC: document.getElementById('weatherTempC'),
  weatherCondition: document.getElementById('weatherCondition'),
  weatherIcon: document.getElementById('weatherIcon'),
  weatherHourly: document.getElementById('weatherHourly'),
  irvePulses: document.getElementById('irve-pulses'),
  irvePower: document.getElementById('irve-power'),
  irveEaPulse: document.getElementById('irve-ea-pulse'),
  irveEaSession: document.getElementById('irve-ea-session'),
  irveEaTotal: document.getElementById('irve-ea-total'),
  irveDt: document.getElementById('irve-dt'),
  irveTs: document.getElementById('irve-ts'),
  irveDayKwh: document.getElementById('irve-day-kwh'),
  irveMonthKwh: document.getElementById('irve-month-kwh'),
  irveYearKwh: document.getElementById('irve-year-kwh'),
  irveYearBase: document.getElementById('irve-year-base'),
  energyPrev3mSplit: document.getElementById('energy-prev3m-split'),
  energyPrev3mTotal: document.getElementById('energy-prev3m-total'),
  energyPrev3mRange: document.getElementById('energy-prev3m-range'),

  agencyDisplay: document.getElementById('agency-display'),
  accidentCvc: document.getElementById('accident-cvc'),
  accidentDefense: document.getElementById('accident-defense'),
  accidentCfo: document.getElementById('accident-cfo'),
  accidentCfa: document.getElementById('accident-cfa'),
  agencyOpen: document.getElementById('agency-open'),
  agencyClose: document.getElementById('agency-close'),
  agencyLiveState: document.getElementById('agency-live-state'),
  qrImage: document.getElementById('agency-qr'),
  qrLabel: document.getElementById('qr-label'),

  ssiOrbit: document.getElementById('ssi-orbit'),
  ssiDays: document.getElementById('ssi-days'),
  ssiSummary: document.getElementById('ssi-summary'),
  ssiIntrusionDays: document.getElementById('ssi-intrusion-days'),
  ssiIntrusionsCount: document.getElementById('ssi-intrusions-count'),
  ssiDetailNote: document.getElementById('ssi-detail-note'),
  headerIntrusions: document.getElementById('header-intrusions'),
  headerAlerts: document.getElementById('header-alerts'),

  meterCvc: document.getElementById('meter-cvc'),
  meterEclairage: document.getElementById('meter-eclairage'),
  meterCourant: document.getElementById('meter-courant'),
  meterEtage: document.getElementById('meter-etage'),
  meterDivers: document.getElementById('meter-divers'),
  meterUpdated: document.getElementById('meter-updated'),

  tvUrl: document.getElementById('tv-url'),
  tvRefresh: document.getElementById('tv-refresh'),
  lastUpdate: document.getElementById('last-update'),

  tableBody: document.getElementById('stations-table-body'),

  stationsActive: document.getElementById('stations-active'),
  stationsAvailable: document.getElementById('stations-available'),
  stationsTotal: document.getElementById('stations-total'),
  stationsTotal2: document.getElementById('stations-total-2'),
  stationLayout: document.getElementById('station-layout'),
  panelStations: document.getElementById('panel-stations'),
  panelAgency: document.getElementById('panel-agency'),

  adminPanel: document.getElementById('admin-panel'),
};

const charts = createCharts();
let pollTimer = null;
let agencyInfoState = null;
let weatherState = null;
let irveState = null;
const IRVE_YEAR_BASE_KWH = 5100;
const IRVE_COMBINED_BASE_3DAYS_AGO_KWH = 9777;
const IRVE_DAY_BASE_KEY = 'irve_day_base';
const IRVE_MONTH_BASE_KEY = 'irve_month_base';
const savedSimulationPref = localStorage.getItem('evce2_simulation_mode');
let simulationMode = savedSimulationPref == null ? true : savedSimulationPref === '1';
let stationSimulationTick = 0;
let meterSimulationBucket = null;
let panelSwitchTimer = null;
const LAST_INTRUSION_KEY = 'evce2_last_intrusion_at';
const DEFAULT_DAYS_WITHOUT_INTRUSION = 137;
const INTRUSION_TOTAL_KEY = 'evce2_intrusion_total';
const INTRUSION_DAYS_KEY = 'evce2_intrusion_days';
const LAST_INTRUSION_NOTE_KEY = 'evce2_last_intrusion_note';
let lastEnergySampleAt = null;
let latestMetersData = null;
let lastIntrusionActiveState = false;
const energyHistory = {
  dailyKwh: new Map(),
  monthlyKwh: new Map(),
  yearlyKwh: new Map(),
};

init();

async function init() {
  bindEvents();
  startPanelSwitcher();
  updateSimulationUi();
  loadConfig();
  await loadAgencyInfoFromBackend();
  await loadWeatherFromBackend();
  await loadIrveFromBackend();
  renderAgencyInfo(agencyInfoState);
  renderWeather(weatherState);
  renderIrve(irveState);
  renderWeatherAdmin(weatherState);
  setWeatherAdminMsgFromState(weatherState);
  seedEnergyHistoryIfEmpty();
  renderMeters(null, null);
  renderSsiState(false, []);
  renderStationMap([]);

  if (simulationMode) {
    setConnected(true);
    setMessage('Mode simulation actif (demarrage auto).');
    startPolling(Number(elements.form?.refreshSeconds?.value || 10));
    await refreshNow();
    return;
  }

  try {
    const session = await getSession();
    if (session.connected) {
      setConnected(true);
      startPolling();
      await refreshNow();
      return;
    }
  } catch {
    // ignore
  }

  await tryAutoReconnectWithSavedToken();
}

function startPanelSwitcher() {
  if (!elements.panelStations || !elements.panelAgency) return;
  if (panelSwitchTimer) clearInterval(panelSwitchTimer);
  let showStations = true;
  panelSwitchTimer = setInterval(() => {
    showStations = !showStations;
    elements.panelStations.classList.toggle('panel-switched-out', !showStations);
    elements.panelAgency.classList.toggle('panel-switched-out', showStations);
  }, 3000);
}

function bindEvents() {
  if (elements.form) {
    elements.form.addEventListener('submit', onConnect);
  }
  if (elements.disconnectBtn) {
    elements.disconnectBtn.addEventListener('click', onDisconnect);
  }
  if (elements.simulateBtn) {
    elements.simulateBtn.addEventListener('click', onToggleSimulation);
  }
  if (elements.weatherForm) {
    elements.weatherForm.addEventListener('submit', onWeatherSave);
  }
  if (elements.weatherClearBtn) {
    elements.weatherClearBtn.addEventListener('click', onWeatherClear);
  }
  if (elements.weatherSampleBtn) {
    elements.weatherSampleBtn.addEventListener('click', onWeatherSample);
  }
  // Toggle admin panel with keyboard shortcut (Ctrl+Shift+A)
  document.addEventListener('keydown', (e) => {
    if (!elements.adminPanel) return;
    if (e.ctrlKey && e.shiftKey && (e.key === 'A' || e.key === 'a')) {
      elements.adminPanel.classList.toggle('visible');
    }
  });
}

async function onConnect(event) {
  event.preventDefault();

  const payload = {
    baseUrl: elements.form.baseUrl.value.trim(),
    login: elements.form.login.value.trim(),
    password: elements.form.password.value,
    token: elements.form.token.value.trim(),
  };

  const refreshSeconds = Number(elements.form.refreshSeconds.value || 10);
  localStorage.setItem('evce2_config', JSON.stringify({
    baseUrl: payload.baseUrl,
    login: payload.login,
    refreshSeconds,
  }));

  try {
    await connect(payload);
    simulationMode = false;
    localStorage.setItem('evce2_simulation_mode', '0');
    updateSimulationUi();
    rememberSession(payload, refreshSeconds);
    setConnected(true);
    setMessage(payload.token ? 'Connecte par token.' : 'Connexion API reussie.');
    startPolling(refreshSeconds);
    await refreshNow();
  } catch (error) {
    setConnected(false);
    setMessage(`Erreur connexion: ${error.message}`);
  }
}

async function onDisconnect() {
  try {
    await disconnect();
  } finally {
    simulationMode = false;
    localStorage.setItem('evce2_simulation_mode', '0');
    updateSimulationUi();
    stopPolling();
    clearRememberedSession();
    setConnected(false);
    setMessage('Deconnecte.');
    renderMeters(null, null);
    renderSsiState(false, []);
  }
}

function startPolling(seconds) {
  stopPolling();
  const refresh = Number(seconds || elements.form.refreshSeconds.value || 10);
  if (elements.tvRefresh) {
    elements.tvRefresh.textContent = `${Math.max(3, refresh)}s`;
  }
  pollTimer = setInterval(refreshNow, Math.max(3, refresh) * 1000);
}

function stopPolling() {
  if (!pollTimer) return;
  clearInterval(pollTimer);
  pollTimer = null;
}

async function refreshNow() {
  if (simulationMode) {
    await loadWeatherFromBackend();
    await loadIrveFromBackend();
    const snapshot = buildSimulationSnapshot();
    renderSnapshot(snapshot);
    setConnected(true);
    setMessage('Mode simulation actif.');
    return;
  }

  try {
    const snapshot = await poll();
    renderSnapshot(snapshot);
  } catch (error) {
    setConnected(false);
    setMessage(`Erreur poll: ${error.message}`);
    renderSsiState(false, []);
    stopPolling();
  }
}

function onToggleSimulation() {
  simulationMode = !simulationMode;
  localStorage.setItem('evce2_simulation_mode', simulationMode ? '1' : '0');
  stationSimulationTick = 0;
  meterSimulationBucket = null;
  clearRememberedSession();
  updateSimulationUi();

  if (simulationMode) {
    setConnected(true);
    setMessage('Mode simulation actif (donnees simulees).');
    startPolling(Number(elements.form?.refreshSeconds?.value || 10));
    refreshNow();
    return;
  }

  stopPolling();
  setConnected(false);
  setMessage('Mode simulation desactive.');
}

function updateSimulationUi() {
  if (!elements.simulateBtn) return;
  elements.simulateBtn.textContent = simulationMode ? 'Stop simulation' : 'Mode simulation';
}

function renderSnapshot(snapshot) {
  const statusesRaw = snapshot.data?.statuses?.data;
  const stationsRaw = snapshot.data?.stations?.data;
  const zoneAssignments = snapshot.data?.zoneStations?.data || {};
  const stations = normalizeStations(stationsRaw, statusesRaw, zoneAssignments);

  const metersData = extractRs485Meters(snapshot.data?.productStatus?.data, snapshot.data?.configEm?.data);
  latestMetersData = metersData;
  updateEnergyHistory(metersData, snapshot.timestamp);
  agencyInfoState = snapshot.data?.agencyInfo?.data || agencyInfoState;
  weatherState = snapshot.data?.weather?.data || weatherState;
  irveState = snapshot.data?.irve?.data || irveState;
  renderEnergyCharts(metersData);
  updateStationChart(charts.stationChart, stations);
  updateZonesChart(charts.zonesChart, stations);

  renderMeters(metersData, snapshot.timestamp);
  renderSsiState(true, stations, snapshot.data?.productStatus?.data);
  renderTable(stations);
  renderAgencyInfo(agencyInfoState);
  renderWeather(weatherState);
  renderIrve(irveState);
  renderWeatherAdmin(weatherState);
  renderStationCounters(stations);
  renderStationMap(stations);

  const irveTsRaw = snapshot.data?.irve?.data?.timestamp_iso || snapshot.data?.irve?.data?.updatedAt || null;
  const lastTs = irveTsRaw ? new Date(irveTsRaw) : new Date(snapshot.timestamp);
  if (elements.lastUpdate) {
    elements.lastUpdate.textContent = Number.isNaN(lastTs.getTime())
      ? '--'
      : `${lastTs.toLocaleDateString()} ${lastTs.toLocaleTimeString()}`;
  }
  if (elements.meterUpdated) elements.meterUpdated.textContent = new Date(snapshot.timestamp).toLocaleTimeString();
  if (!simulationMode) {
    setMessage('Dashboard actualise.');
    setConnected(true);
  }
}

function buildSimulationSnapshot() {
  stationSimulationTick += 1;
  const now = new Date();
  const meters = getSimulatedMeters(now);
  const intrusionNow = stationSimulationTick % 6 === 0;

  const stations = [
    { id: 1, name: 'Borne_1', zone: 'zonetest', connectors_count: 2 },
    { id: 2, name: 'Borne_2', zone: 'zonetest', connectors_count: 1 },
    { id: 3, name: 'Borne_3', zone: 'zonetest', connectors_count: 2 },
    { id: 4, name: 'Borne_4', zone: 'Zonetest2', connectors_count: 2 },
    { id: 5, name: 'Borne_5', zone: 'Zonetest2', connectors_count: 1 },
    { id: 6, name: 'Borne_6', zone: 'Zonetest2', connectors_count: 2 },
    { id: 7, name: 'Borne_7', zone: 'Divers', connectors_count: 1 },
    { id: 8, name: 'Borne_8', zone: 'Divers', connectors_count: 1 },
  ];

  const statuses = stations.map((s, idx) => {
    const cycle = (stationSimulationTick + idx) % 10;
    let status = 'available';
    let active_connectors = 0;
    let amperage = 0;
    if (cycle >= 2 && cycle <= 6) {
      status = 'charging';
      active_connectors = 1;
      const baseAmp = 12 + ((idx % 3) * 8);
      amperage = round2(baseAmp + Math.sin(stationSimulationTick * 0.45 + idx) * 3);
    } else if (cycle === 8) {
      status = 'offline';
    } else if (cycle === 9 && idx % 4 === 0) {
      status = 'faulted';
    }
    return {
      station_id: s.id,
      status,
      connectors_count: s.connectors_count,
      active_connectors,
      current_a: Math.max(0, amperage),
      zone_name: s.zone,
    };
  });

  const zoneMap = {};
  for (const s of stations) {
    zoneMap[String(s.id)] = s.zone;
  }

  const weather = weatherState || buildSimulationWeather(now);

  return {
    timestamp: now.toISOString(),
    connected: true,
    data: {
      stations: { ok: true, data: stations },
      statuses: { ok: true, data: statuses },
      zoneStations: { ok: true, data: zoneMap },
      configEm: { ok: true, data: meters },
      productStatus: {
        ok: true,
        data: {
          intrusion_state: intrusionNow ? 'active' : 'none',
          intrusion_alarm: intrusionNow,
          intrusion_source: intrusionNow ? `zone-${1 + (stationSimulationTick % 3)}` : '',
          meter_cvc_kw: meters.cvc,
          meter_eclairage_kw: meters.eclairage,
          meter_courant_kw: meters.courant,
          meter_etage_kw: meters.etage,
          meter_divers_kw: meters.divers,
        },
      },
      agencyInfo: { ok: true, data: agencyInfoState || null },
      weather: { ok: true, data: weather },
      irve: { ok: true, data: irveState || null },
    },
  };
}

function getSimulatedMeters(now) {
  const bucket = Math.floor(now.getTime() / 30000);
  if (bucket !== meterSimulationBucket) {
    meterSimulationBucket = bucket;
  }
  return {
    cvc: computeMeterValue(bucket, 38, 8, 0),
    eclairage: computeMeterValue(bucket, 12, 4, 7),
    courant: computeMeterValue(bucket, 22, 6, 13),
    etage: computeMeterValue(bucket, 16, 5, 19),
    divers: computeMeterValue(bucket, 8, 3, 23),
  };
}

function computeMeterValue(bucket, base, amp, phase) {
  const v = base
    + amp * Math.sin((bucket + phase) * 0.21)
    + (amp * 0.35) * Math.cos((bucket + phase) * 0.11);
  return round2(Math.max(0, v));
}

function buildSimulationWeather(now) {
  const hour = now.getHours();
  const isDay = hour >= 7 && hour <= 20;
  const icon = isDay ? 'sun' : 'cloud';
  const tempC = round2(15 + 5 * Math.sin((hour / 24) * Math.PI * 2));
  const condition = isDay ? 'Eclaircies' : 'Nuit nuageuse';
  const hourly = [];
  for (let i = 0; i < 5; i++) {
    const h = (hour + i * 2) % 24;
    hourly.push({
      time: `${String(h).padStart(2, '0')}:00`,
      tempC: round2(tempC + Math.sin(i * 0.7) * 2),
      icon,
    });
  }
  return {
    location: 'Agence',
    tempC,
    condition,
    icon,
    hourly,
    updatedAt: now.toISOString(),
  };
}

function round2(value) {
  return Math.round(Number(value) * 100) / 100;
}

function renderEnergyCharts(metersData) {
  const monthPieView = buildMonthPieView(metersData);
  updateMonthPieChart(charts.monthPieChart, monthPieView);
  const yearView = buildYearEnergyView();
  updateAnnualEnergyChart(charts.yearChart, yearView);
  renderPrevious3MonthsTotal();
}

function buildMonthPieView(metersData) {
  const labels = ['IRVE', 'CVC', 'Eclairage', 'Courant', 'Etage', 'Divers'];
  const irveScenario = getIrveScenario();
  const irveTotal = irveScenario.currentYear;
  const powerValues = [
    Number(metersData?.cvc) || 0,
    Number(metersData?.eclairage) || 0,
    Number(metersData?.courant) || 0,
    Number(metersData?.etage) || 0,
    Number(metersData?.divers) || 0,
  ];
  const values = [round2(irveTotal), ...powerValues.map((v) => round2(Math.max(0, v)))];
  const colors = [
    'rgba(0,255,136,0.92)', // IRVE vert
    'rgba(163,175,194,0.86)',
    'rgba(140,153,173,0.86)',
    'rgba(121,134,155,0.86)',
    'rgba(103,116,138,0.86)',
    'rgba(84,98,121,0.86)',
  ];
  return { labels, values, colors };
}

function renderPrevious3MonthsTotal() {
  if (!elements.energyPrev3mSplit || !elements.energyPrev3mTotal || !elements.energyPrev3mRange) return;
  const irveScenario = getIrveScenario();
  const monthEntries = [
    { label: 'janv.', value: irveScenario.jan },
    { label: 'fevr.', value: irveScenario.fev },
    { label: 'mars', value: irveScenario.mars },
    { label: 'annee', value: irveScenario.currentYear },
    { label: 'cumule', value: irveScenario.combinedNow },
  ];

  elements.energyPrev3mSplit.innerHTML = monthEntries
    .map((entry) => `
      <div class="month-split-row">
        <span class="month-split-name">${entry.label}</span>
        <span class="month-split-kwh">${Math.round(entry.value).toLocaleString('fr-FR')} kWh</span>
      </div>
    `)
    .join('');
  elements.energyPrev3mTotal.textContent = `${Math.round(irveScenario.combinedNow).toLocaleString('fr-FR')} kWh`;
  elements.energyPrev3mRange.textContent = `Annee: ${Math.round(irveScenario.currentYear).toLocaleString('fr-FR')} kWh | Cumule: ${Math.round(irveScenario.combinedNow).toLocaleString('fr-FR')} kWh`;
}

function getIrveScenario() {
  // 9 777 = index cumule (annee precedente + annee courante) il y a 3 jours.
  // EA+ actuelle est l'increment depuis ce point de reference.
  const mars = Math.max(0, Number(irveState?.ea_total_kwh || 0));
  const combinedNow = IRVE_COMBINED_BASE_3DAYS_AGO_KWH + mars; // ex: 10 819
  const currentYear = Math.max(0, combinedNow - IRVE_YEAR_BASE_KWH); // ex: 10 819 - 5 100
  const janFevTotal = Math.max(0, currentYear - mars);
  const jan = janFevTotal / 2;
  const fev = janFevTotal / 2;
  return {
    jan,
    fev,
    mars,
    currentYear,
    combinedNow,
  };
}

function getPrevious3MonthsTotal(refDate) {
  let total = 0;
  for (let i = 3; i >= 1; i--) {
    const d = new Date(refDate.getFullYear(), refDate.getMonth() - i, 1);
    total += getMonthKwhWithOverrides(d);
  }
  return total;
}

function getMonthKwhWithOverrides(date) {
  const key = toMonthKey(date);
  const raw = Number(energyHistory.monthlyKwh.get(key) || 0);
  const now = new Date();
  // Jeu de donnees cible: Dec + Jan + Fev = 9777 kWh
  // Contrainte utilisateur: Decembre = 5100
  if (date.getFullYear() === now.getFullYear() - 1 && date.getMonth() === 11) return 5100; // Decembre
  if (date.getFullYear() === now.getFullYear() && date.getMonth() === 0) return 2300; // Janvier
  if (date.getFullYear() === now.getFullYear() && date.getMonth() === 1) return 2377; // Fevrier
  if (date.getFullYear() === now.getFullYear()) {
    // autres mois de l'annee courante: valeurs simulees de base
    return raw;
  }
  return raw;
}

function updateEnergyHistory(metersData, timestamp) {
  const ts = new Date(timestamp);
  if (Number.isNaN(ts.getTime())) return;
  const totalKw = ['cvc', 'eclairage', 'courant', 'etage', 'divers']
    .map((key) => Number(metersData?.[key]) || 0)
    .reduce((a, b) => a + b, 0);

  if (!lastEnergySampleAt) {
    lastEnergySampleAt = ts;
    return;
  }

  const deltaHours = Math.max(0, Math.min((ts.getTime() - lastEnergySampleAt.getTime()) / 3600000, 1));
  lastEnergySampleAt = ts;
  if (deltaHours <= 0) return;

  const kwh = totalKw * deltaHours;
  const dayKey = toDayKey(ts);
  const monthKey = toMonthKey(ts);
  const yearKey = toYearKey(ts);
  energyHistory.dailyKwh.set(dayKey, (energyHistory.dailyKwh.get(dayKey) || 0) + kwh);
  energyHistory.monthlyKwh.set(monthKey, (energyHistory.monthlyKwh.get(monthKey) || 0) + kwh);
  energyHistory.yearlyKwh.set(yearKey, (energyHistory.yearlyKwh.get(yearKey) || 0) + kwh);
}

function buildMonthEnergyView() {
  const labels = [];
  const values = [];
  const now = new Date();
  for (let i = 11; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const key = toMonthKey(d);
    labels.push(d.toLocaleString('fr-FR', { month: 'short', year: '2-digit' }));
    values.push(round2(energyHistory.monthlyKwh.get(key) || 0));
  }
  return {
    labels,
    values,
    seriesLabel: 'Energie mensuelle (kWh)',
    unit: 'kWh',
    type: 'bar',
  };
}

function buildYearEnergyView() {
  const labels = [];
  const values = [];
  const now = new Date();
  // Pas de donnees fictives: seulement N-1 et N.
  const startYear = now.getFullYear() - 1;
  for (let y = startYear; y <= now.getFullYear(); y++) {
    labels.push(String(y));
    values.push(round2(getYearKwhWithOverrides(y, now)));
  }
  return {
    labels,
    values,
    seriesLabel: 'Energie annuelle (kWh)',
    unit: 'kWh',
    type: 'line',
  };
}

function getYearKwhWithOverrides(year, nowDate = new Date()) {
  // Contrainte metier: l'annee derniere est fixe a 5100 kWh.
  if (year === nowDate.getFullYear() - 1) return 5100;
  if (year === nowDate.getFullYear()) {
    return round2(getIrveScenario().currentYear);
  }
  return 0;
}

function seedEnergyHistoryIfEmpty() {
  if (energyHistory.monthlyKwh.size > 0 || energyHistory.yearlyKwh.size > 0) return;
  const now = new Date();

  // Seed 6 years of monthly values with seasonal profile.
  for (let y = now.getFullYear() - 5; y <= now.getFullYear(); y++) {
    for (let m = 0; m < 12; m++) {
      const date = new Date(y, m, 1);
      const monthKey = toMonthKey(date);
      if (energyHistory.monthlyKwh.has(monthKey)) continue;
      const seasonal = 1200 + 260 * Math.sin(((m + 1) / 12) * Math.PI * 2);
      const yearTrend = (y - (now.getFullYear() - 5)) * 38;
      const pseudoNoise = ((y * 37 + m * 13) % 90) - 45;
      const value = Math.max(600, seasonal + yearTrend + pseudoNoise);
      energyHistory.monthlyKwh.set(monthKey, round2(value));
      const yearKey = String(y);
      energyHistory.yearlyKwh.set(yearKey, (energyHistory.yearlyKwh.get(yearKey) || 0) + value);
    }
  }

  // Seed 365 days for day-level continuity (used by live accumulation/reporting).
  for (let i = 364; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(now.getDate() - i);
    const dayKey = toDayKey(d);
    if (energyHistory.dailyKwh.has(dayKey)) continue;
    const daySeasonal = 34 + 9 * Math.sin((d.getMonth() / 12) * Math.PI * 2);
    const weekdayBias = [1.08, 1.04, 1.06, 1.03, 1.00, 0.84, 0.80][d.getDay()];
    const pseudoNoise = ((d.getDate() * 11 + d.getMonth() * 7) % 12) - 6;
    const value = Math.max(12, (daySeasonal + pseudoNoise) * weekdayBias);
    energyHistory.dailyKwh.set(dayKey, round2(value));
  }

  // Round seeded yearly totals once at the end.
  for (const [k, v] of energyHistory.yearlyKwh.entries()) {
    energyHistory.yearlyKwh.set(k, round2(v));
  }
}

function toDayKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function toMonthKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

function toYearKey(date) {
  return String(date.getFullYear());
}

function normalizeStations(stationsData, statusesData, zoneAssignments) {
  const stations = extractArray(stationsData).map((raw) => {
    const id = pick(raw, ['id', 'station_id', 'evse_id']) || 'n/a';
    return {
      id,
      name: pick(raw, ['name', 'station_name', 'label']) || String(id),
      zone: pick(raw, ['zone', 'zone_name', 'zone_id']) || raw?.desc?.zone_name || String(zoneAssignments[String(id)] || 'Sans zone'),
      status: 'unknown',
      connectors: Number(pick(raw, ['connectors_count', 'connector_count']) || 0),
      activity: 0,
      amperage: numberOrNull(pick(raw, ['current_a', 'amperage', 'ampere', 'current'])) || 0,
      isAvailable: null,
    };
  });

  const statuses = extractArray(statusesData);
  const map = new Map();

  for (const row of statuses) {
    const id = pick(row, ['station_id', 'id', 'evse_id']);
    if (!id) continue;
    const status = String(
      pick(row, ['status', 'station_status', 'ocpp_status', 'evse_status']) ||
      pickDeepString(row, ['status', 'state', 'evse_status']) ||
      extractStatusText(row)
    ).toLowerCase();

    map.set(String(id), {
      status,
      connectors: Number(pick(row, ['connectors_count', 'connector_count']) || pickDeepNumber(row, ['connectors_count', 'connector_count']) || 0),
      activity: Number(pick(row, ['active_connectors', 'active_sessions', 'charging_connectors']) || pickDeepNumber(row, ['active_connectors', 'active_sessions', 'charging_connectors']) || 0),
      amperage: Number(
        pick(row, ['current_a', 'amperage', 'ampere', 'charging_current', 'output_current']) ||
        pickDeepNumber(row, ['current_a', 'amperage', 'ampere', 'charging_current', 'output_current']) ||
        0
      ),
      isAvailable: isAvailableStatus(status),
      zone: pick(row, ['zone', 'zone_name', 'zone_id']) || row?.desc?.zone_name || String(zoneAssignments[String(id)] || ''),
    });
  }

  return stations.map((station) => {
    const ext = map.get(String(station.id));
    if (!ext) return station;
    return {
      ...station,
      status: ext.status || station.status,
      connectors: ext.connectors || station.connectors,
      activity: ext.activity,
      amperage: Number.isFinite(Number(ext.amperage)) ? Number(ext.amperage) : station.amperage,
      isAvailable: ext.isAvailable,
      zone: ext.zone || station.zone,
    };
  });
}

function renderTable(stations) {
  if (!elements.tableBody) return;
  if (!stations.length) {
    elements.tableBody.innerHTML = '<tr><td colspan="6">Aucune borne.</td></tr>';
    return;
  }

  elements.tableBody.innerHTML = stations
    .map((s) => `
      <tr>
        <td>${escapeHtml(String(s.id))}</td>
        <td>${escapeHtml(String(s.name))}</td>
        <td>${escapeHtml(String(s.zone || 'Sans zone'))}</td>
        <td><span class="badge ${statusClass(s.status)}">${escapeHtml(String(s.status))}</span></td>
        <td>${Number(s.connectors || 0)}</td>
        <td>${Number(s.amperage || 0).toFixed(1)} A</td>
      </tr>
    `)
    .join('');
}

function renderStationMap(stations) {
  if (!elements.stationLayout) return;
  if (!Array.isArray(stations) || stations.length === 0) {
    elements.stationLayout.innerHTML = '';
    return;
  }

  const displayNameBySource = {
    Borne_1: 'Borne_6',
    Borne_2: 'Borne_5',
    Borne_3: 'Borne_4',
    Borne_4: 'Borne_1',
    Borne_5: null, // n'existe pas sur le plan
    Borne_6: 'Borne_10',
  };

  // Plan fixe: barre #1 (x64) pour 10/7/8, barre #2 (x28) pour 1..6
  const slotsByDisplayName = {
    Borne_6: { x: 28, y: 18 },
    Borne_5: { x: 28, y: 30 },
    Borne_4: { x: 28, y: 42 },
    Borne_3: { x: 28, y: 54 },
    Borne_2: { x: 28, y: 66 },
    Borne_1: { x: 28, y: 78 },
    Borne_7: { x: 64, y: 44 },
    Borne_8: { x: 64, y: 58 },
    Borne_10: { x: 64, y: 30 },
  };

  const rows = [...stations]
    .sort((a, b) => Number(a.id || 0) - Number(b.id || 0));

  elements.stationLayout.innerHTML = rows
    .map((s, idx) => {
      const sourceName = String(s.name || `Borne_${idx + 1}`);
      const mappedName = Object.prototype.hasOwnProperty.call(displayNameBySource, sourceName)
        ? displayNameBySource[sourceName]
        : sourceName;
      if (!mappedName) return '';
      const pos = slotsByDisplayName[mappedName];
      if (!pos) return '';
      const state = { className: 'busy', label: 'non connecte' };
      return `
        <div class="station-pin ${state.className}" style="left:${pos.x}%;top:${pos.y}%;">
          <span class="pin-dot"></span>
          <div class="pin-card">
            <div class="pin-name">${escapeHtml(mappedName)}</div>
            <div class="pin-meta">${escapeHtml(state.label)}</div>
          </div>
        </div>
      `;
    })
    .join('');
}

function stationMapState(station) {
  const status = String(station?.status || '').toLowerCase();
  const activity = Number(station?.activity || 0);
  const isAvailable = station?.isAvailable === true || status.includes('available') || status.includes('idle') || status.includes('libre');
  const isBusy = activity > 0 || status.includes('charging') || status.includes('occupied') || status.includes('busy') || status.includes('in_use');
  const isOffline = status.includes('offline') || status.includes('fault') || status.includes('error') || status.includes('unavailable');

  if (isOffline) return { className: 'offline', label: 'hors ligne' };
  if (isBusy) return { className: 'busy', label: 'occupe' };
  if (isAvailable) return { className: 'available', label: 'disponible' };
  return { className: 'unknown', label: 'indetermine' };
}

function renderSsiState(connected, stations, productStatusData = null) {
  if (!elements.ssiOrbit || !elements.ssiSummary || !elements.ssiDays) return;
  if (elements.headerIntrusions) elements.headerIntrusions.textContent = 'Bientot disponible';
  if (elements.headerAlerts) elements.headerAlerts.textContent = 'Deconnecte';
  elements.ssiSummary.classList.remove('intrusion-camo');
  if (elements.ssiIntrusionDays) elements.ssiIntrusionDays.textContent = 'Bientot disponible';
  if (elements.ssiIntrusionsCount) elements.ssiIntrusionsCount.textContent = 'Bientot disponible';
  if (elements.ssiDetailNote) elements.ssiDetailNote.textContent = 'Informations bientot disponibles';

  // Mode temporaire demande: toujours afficher supervision securisee.
  elements.ssiOrbit.className = 'ssi-orbit safe';
  elements.ssiDays.textContent = '0';
  elements.ssiSummary.textContent = 'Supervision securisee';
  return;

  if (!connected) {
    elements.ssiOrbit.className = 'ssi-orbit alert';
    elements.ssiDays.textContent = '--';
    if (elements.ssiIntrusionDays) elements.ssiIntrusionDays.textContent = '--';
    if (elements.ssiIntrusionsCount) elements.ssiIntrusionsCount.textContent = '--';
    if (elements.ssiDetailNote) elements.ssiDetailNote.textContent = 'Supervision non disponible';
    elements.ssiSummary.textContent = 'Supervision non disponible';
    return;
  }

  const faultCount = stations.filter((s) => {
    const v = String(s.status || '').toLowerCase();
    return v.includes('fault') || v.includes('offline') || v.includes('error');
  }).length;

  const intrusion = detectIntrusionState(productStatusData);
  const daysWithoutIntrusion = updateNoIntrusionCounter(intrusion);
  const intrusionStats = updateIntrusionStats(intrusion, productStatusData);
  elements.ssiDays.textContent = String(daysWithoutIntrusion);
  if (elements.ssiIntrusionDays) elements.ssiIntrusionDays.textContent = String(intrusionStats.daysWithIntrusion);
  if (elements.ssiIntrusionsCount) elements.ssiIntrusionsCount.textContent = String(intrusionStats.totalIntrusions);
  if (elements.ssiDetailNote) elements.ssiDetailNote.textContent = intrusionStats.lastNote;
  if (elements.headerIntrusions) elements.headerIntrusions.textContent = 'Bientot disponible';
  if (elements.headerAlerts) elements.headerAlerts.textContent = 'Deconnecte';

  if (intrusion || faultCount > 0) {
    elements.ssiOrbit.className = 'ssi-orbit alert';
    if (intrusion) {
      elements.ssiDays.textContent = '0';
      elements.ssiSummary.textContent = 'Intrusion detectee: compteur remis a 0 jour';
      elements.ssiSummary.classList.add('intrusion-camo');
      return;
    }
    elements.ssiSummary.textContent = '';
    return;
  }

  elements.ssiOrbit.className = 'ssi-orbit safe';
  elements.ssiSummary.textContent = 'Supervision securisee';
}

function updateIntrusionStats(intrusionDetected, productStatusData) {
  const today = toDayKey(new Date());
  const note = intrusionDetected
    ? buildIntrusionNote(productStatusData)
    : (localStorage.getItem(LAST_INTRUSION_NOTE_KEY) || 'Aucune intrusion enregistree.');

  let total = Number(localStorage.getItem(INTRUSION_TOTAL_KEY) || 0);
  let days = [];
  try {
    const raw = localStorage.getItem(INTRUSION_DAYS_KEY);
    days = raw ? JSON.parse(raw) : [];
  } catch {
    days = [];
  }
  if (!Array.isArray(days)) days = [];

  const isNewEvent = intrusionDetected && !lastIntrusionActiveState;
  if (isNewEvent) {
    total += 1;
    if (!days.includes(today)) {
      days.push(today);
    }
    localStorage.setItem(INTRUSION_TOTAL_KEY, String(total));
    localStorage.setItem(INTRUSION_DAYS_KEY, JSON.stringify(days));
    localStorage.setItem(LAST_INTRUSION_NOTE_KEY, note);
  }
  lastIntrusionActiveState = intrusionDetected;

  return {
    totalIntrusions: total,
    daysWithIntrusion: days.length,
    lastNote: localStorage.getItem(LAST_INTRUSION_NOTE_KEY) || note,
  };
}

function detectIntrusionState(productStatusData) {
  if (!productStatusData || typeof productStatusData !== 'object') return false;
  const queue = [productStatusData];
  while (queue.length) {
    const node = queue.pop();
    if (!node || typeof node !== 'object') continue;
    for (const [key, value] of Object.entries(node)) {
      if (value && typeof value === 'object') {
        queue.push(value);
        continue;
      }
      const k = String(key || '').toLowerCase();
      const watched = k.includes('intrusion') || k.includes('tamper') || k.includes('alarm');
      if (!watched) continue;

      if (typeof value === 'boolean') {
        if (value) return true;
        continue;
      }
      if (typeof value === 'number') {
        if (value > 0) return true;
        continue;
      }
      if (typeof value === 'string') {
        const v = value.trim().toLowerCase();
        if (!v) continue;
        if (['none', 'normal', 'ok', 'inactive', 'off', 'false', '0'].includes(v)) continue;
        return true;
      }
    }
  }
  return false;
}

function buildIntrusionNote(productStatusData) {
  if (!productStatusData || typeof productStatusData !== 'object') {
    return `Intrusion detectee (${new Date().toLocaleString()})`;
  }
  const tokens = [];
  const text = JSON.stringify(productStatusData);
  const patterns = ['intrusion', 'tamper', 'alarm', 'door', 'unauthorized', 'security'];
  for (const p of patterns) {
    if (text.toLowerCase().includes(p)) tokens.push(p);
  }
  const uniq = [...new Set(tokens)].slice(0, 3).join(', ');
  const suffix = uniq ? ` | details: ${uniq}` : '';
  return `Intrusion detectee (${new Date().toLocaleString()})${suffix}`;
}

function updateNoIntrusionCounter(intrusionDetected) {
  const now = new Date();
  const nowIso = now.toISOString();
  let raw = localStorage.getItem(LAST_INTRUSION_KEY);

  if (!raw) {
    const fallback = new Date(now.getTime() - DEFAULT_DAYS_WITHOUT_INTRUSION * 24 * 60 * 60 * 1000);
    raw = fallback.toISOString();
    localStorage.setItem(LAST_INTRUSION_KEY, raw);
  }

  if (intrusionDetected) {
    localStorage.setItem(LAST_INTRUSION_KEY, nowIso);
    return 0;
  }

  const last = new Date(raw);
  if (Number.isNaN(last.getTime())) {
    localStorage.setItem(LAST_INTRUSION_KEY, nowIso);
    return 0;
  }

  const diffMs = now.getTime() - last.getTime();
  return Math.max(0, Math.floor(diffMs / (24 * 60 * 60 * 1000)));
}

function renderMeters(metersData, timestamp) {
  if (!elements.meterCvc || !elements.meterEclairage || !elements.meterCourant || !elements.meterEtage || !elements.meterDivers) return;
  const cvc = numberOrNull(metersData?.cvc);
  const eclairage = numberOrNull(metersData?.eclairage);
  const courant = numberOrNull(metersData?.courant);
  const etage = numberOrNull(metersData?.etage);
  const divers = numberOrNull(metersData?.divers);

  elements.meterCvc.textContent = cvc === null ? 'En attente RS485' : `${cvc.toFixed(2)} kW`;
  elements.meterEclairage.textContent = eclairage === null ? 'En attente RS485' : `${eclairage.toFixed(2)} kW`;
  elements.meterCourant.textContent = courant === null ? 'En attente RS485' : `${courant.toFixed(2)} kW`;
  elements.meterEtage.textContent = etage === null ? 'En attente RS485' : `${etage.toFixed(2)} kW`;
  elements.meterDivers.textContent = divers === null ? 'En attente RS485' : `${divers.toFixed(2)} kW`;
  if (elements.meterUpdated) {
    elements.meterUpdated.textContent = timestamp ? new Date(timestamp).toLocaleTimeString() : '-';
  }
}

function extractRs485Meters(productStatusData, configEmData) {
  const source = [productStatusData, configEmData];
  let cvc = firstNumber(source, [
    'cvc_kw',
    'meter_cvc_kw',
    'compteur_cvc_kw',
    'hvac_kw',
    'cvc',
  ]);
  let eclairage = firstNumber(source, [
    'eclairage_kw',
    'meter_eclairage_kw',
    'compteur_eclairage_kw',
    'lighting_kw',
    'eclairage',
  ]);
  let courant = firstNumber(source, [
    'courant_kw',
    'meter_courant_kw',
    'compteur_courant_kw',
    'current_kw',
    'courant',
  ]);
  let etage = firstNumber(source, [
    'etage_kw',
    'meter_etage_kw',
    'compteur_etage_kw',
    'floor_kw',
    'etage',
  ]);
  let divers = firstNumber(source, [
    'divers_kw',
    'meter_divers_kw',
    'compteur_divers_kw',
    'misc_kw',
    'divers',
  ]);

  // Fallback: if API keys differ, map first discovered numeric channels.
  if ([cvc, eclairage, courant, etage, divers].every((v) => v === null)) {
    const inferred = inferMeterChannels(source);
    cvc = inferred[0] ?? null;
    eclairage = inferred[1] ?? null;
    courant = inferred[2] ?? null;
    etage = inferred[3] ?? null;
    divers = inferred[4] ?? null;
  }

  return {
    cvc,
    eclairage,
    courant,
    etage,
    divers,
  };
}

function inferMeterChannels(sources) {
  const out = [];
  const seen = new Set();
  const queue = [...sources];
  while (queue.length && out.length < 5) {
    const node = queue.pop();
    if (!node || typeof node !== 'object') continue;

    for (const [key, value] of Object.entries(node)) {
      if (value && typeof value === 'object') {
        queue.push(value);
        continue;
      }
      const k = String(key).toLowerCase();
      const isMeterLike = k.includes('kw') || k.includes('power') || k.includes('current') || k.includes('meter');
      if (!isMeterLike) continue;
      const n = numberOrNull(value);
      if (n === null) continue;
      const marker = `${k}:${n}`;
      if (seen.has(marker)) continue;
      seen.add(marker);
      out.push(n);
      if (out.length >= 5) break;
    }
  }
  return out;
}

function firstNumber(sources, keys) {
  for (const src of sources) {
    const n = numberOrNull(pickDeepNumber(src, keys));
    if (n !== null) return n;
  }
  return null;
}

async function loadAgencyInfoFromBackend() {
  try {
    const response = await fetch('/backend/agency');
    if (!response.ok) return;
    const data = await response.json();
    if (data?.ok && data?.data) {
      agencyInfoState = data.data;
    }
  } catch {
    // ignore
  }
}

function renderAgencyInfo(info) {
  if (!elements.agencyDisplay) return;
  const welcomeMessage = String(info?.welcomeMessage || '').trim() || 'Bonjour et bienvenue chez nous.';
  const eventsTextRaw = String(info?.eventsText || '').trim();
  const notes = String(info?.notes || '').trim();
  const publicUrl = String(info?.publicUrl || '').trim() || window.location.origin;
  const openTime = String(info?.openTime || '07:00');
  const closeTime = String(info?.closeTime || '20:00');
  const events = parseAgencyEvents(eventsTextRaw, notes);
  const eventLines = events.length ? events : ['Aucun evenement renseigne pour le moment.'];
  const lines = [welcomeMessage, ...eventLines];
  const linesHtml = lines
    .map((line, i) => `<li class="agency-line" style="--line-order:${i}">${escapeHtml(line)}</li>`)
    .join('');

  elements.agencyDisplay.innerHTML = `
    <div class="agency-cinematic">
      <ul class="agency-lines">${linesHtml}</ul>
    </div>
  `;

  const accidents = info?.accidents || {};
  const normalizedAccidents = {
    cvc: Math.max(0, Number(accidents.cvc || 0)),
    defense: Math.max(0, Number(accidents.defense || 0)),
    cfo: Math.max(0, Number(accidents.cfo || 0)),
    cfa: Math.max(0, Number(accidents.cfa || 0)),
  };
  if (elements.accidentCvc) elements.accidentCvc.textContent = String(normalizedAccidents.cvc);
  if (elements.accidentDefense) elements.accidentDefense.textContent = String(normalizedAccidents.defense);
  if (elements.accidentCfo) elements.accidentCfo.textContent = String(normalizedAccidents.cfo);
  if (elements.accidentCfa) elements.accidentCfa.textContent = String(normalizedAccidents.cfa);
  updateAccidentsChart(charts.accidentsChart, normalizedAccidents);

  if (elements.agencyOpen) elements.agencyOpen.textContent = openTime;
  if (elements.agencyClose) elements.agencyClose.textContent = closeTime;
  if (elements.agencyLiveState) {
    elements.agencyLiveState.textContent = computeAgencyState(openTime, closeTime);
  }

  if (elements.tvUrl) elements.tvUrl.textContent = publicUrl;
  const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=256x256&data=${encodeURIComponent(publicUrl)}`;
  if (elements.qrImage) elements.qrImage.src = qrUrl;
  if (elements.qrLabel) elements.qrLabel.textContent = publicUrl;
}

function parseAgencyEvents(eventsTextRaw, notes) {
  const source = eventsTextRaw || notes || '';
  return source
    .split(/[\n;|]+/g)
    .map((x) => x.trim())
    .filter(Boolean)
    .slice(0, 6);
}

function computeAgencyState(open, close) {
  const now = new Date();
  const mins = now.getHours() * 60 + now.getMinutes();
  const [oh, om] = String(open || '07:00').split(':').map(Number);
  const [ch, cm] = String(close || '20:00').split(':').map(Number);
  const o = (Number.isFinite(oh) ? oh : 7) * 60 + (Number.isFinite(om) ? om : 0);
  const c = (Number.isFinite(ch) ? ch : 20) * 60 + (Number.isFinite(cm) ? cm : 0);
  return mins >= o && mins <= c ? 'Ouvert' : 'Ferme';
}

async function loadWeatherFromBackend() {
  try {
    const response = await fetch('/backend/weather');
    if (!response.ok) return;
    const data = await response.json();
    if (data?.ok && data?.data) {
      weatherState = data.data;
    }
  } catch {
    // ignore
  }
}

async function loadIrveFromBackend() {
  try {
    const response = await fetch('/backend/irve');
    if (!response.ok) return;
    const data = await response.json();
    if (data?.ok && data?.data) {
      irveState = data.data;
    }
  } catch {
    // ignore
  }
}

function renderIrve(info) {
  if (!elements.irvePulses) return;
  const n = (v, d = '--') => (Number.isFinite(Number(v)) ? String(v) : d);
  const totalKwh = Number(info?.ea_total_kwh);
  elements.irvePulses.textContent = n(Math.round(Number(info?.pulses || 0)), '0');
  elements.irvePower.textContent = Number.isFinite(Number(info?.power_kw))
    ? `${Number(info.power_kw).toFixed(3)} kW`
    : '--';
  elements.irveEaPulse.textContent = Number.isFinite(Number(info?.ea_pulse_kwh))
    ? `${Number(info.ea_pulse_kwh).toFixed(3)} kWh`
    : '--';
  elements.irveEaSession.textContent = Number.isFinite(Number(info?.ea_session_kwh))
    ? `${Number(info.ea_session_kwh).toFixed(3)} kWh`
    : '--';
  elements.irveEaTotal.textContent = Number.isFinite(totalKwh)
    ? `${totalKwh.toFixed(3)} kWh`
    : '--';
  elements.irveDt.textContent = Number.isFinite(Number(info?.dt_s))
    ? `${Number(info.dt_s).toFixed(2)} s`
    : '--';
  const ts = info?.timestamp_iso || info?.updatedAt || null;
  elements.irveTs.textContent = ts ? new Date(ts).toLocaleTimeString() : '--';

  const conso = computeIrveConsumptions(totalKwh);
  if (elements.irveDayKwh) {
    elements.irveDayKwh.textContent = Number.isFinite(conso.day)
      ? `${conso.day.toFixed(3)} kWh`
      : '--';
  }
  if (elements.irveMonthKwh) {
    elements.irveMonthKwh.textContent = Number.isFinite(conso.month)
      ? `${conso.month.toFixed(3)} kWh`
      : '--';
  }
  if (elements.irveYearKwh) {
    elements.irveYearKwh.textContent = Number.isFinite(conso.year)
      ? `${conso.year.toFixed(3)} kWh`
      : '--';
  }
  if (elements.irveYearBase) {
    elements.irveYearBase.textContent = `${IRVE_YEAR_BASE_KWH.toFixed(3)} kWh`;
  }
}

function computeIrveConsumptions(totalKwh) {
  if (!Number.isFinite(totalKwh)) {
    return { day: NaN, month: NaN, year: NaN };
  }
  const now = new Date();
  const dayKey = now.toISOString().slice(0, 10);
  const monthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

  const dayRaw = localStorage.getItem(IRVE_DAY_BASE_KEY);
  let dayBase = null;
  try {
    dayBase = dayRaw ? JSON.parse(dayRaw) : null;
  } catch {
    dayBase = null;
  }
  if (!dayBase || dayBase.key !== dayKey || !Number.isFinite(Number(dayBase.value))) {
    dayBase = { key: dayKey, value: totalKwh };
    localStorage.setItem(IRVE_DAY_BASE_KEY, JSON.stringify(dayBase));
  }

  const monthRaw = localStorage.getItem(IRVE_MONTH_BASE_KEY);
  let monthBase = null;
  try {
    monthBase = monthRaw ? JSON.parse(monthRaw) : null;
  } catch {
    monthBase = null;
  }
  if (!monthBase || monthBase.key !== monthKey || !Number.isFinite(Number(monthBase.value))) {
    monthBase = { key: monthKey, value: totalKwh };
    localStorage.setItem(IRVE_MONTH_BASE_KEY, JSON.stringify(monthBase));
  }

  return {
    day: Math.max(0, totalKwh - Number(dayBase.value)),
    month: Math.max(0, totalKwh - Number(monthBase.value)),
    year: Math.max(0, totalKwh - IRVE_YEAR_BASE_KWH),
  };
}

function renderWeather(info) {
  if (!elements.wmLoc || !elements.wmCond || !elements.wmTemp || !elements.wmIcon || !elements.wmHours) return;
  const location = String(info?.location || '').trim() || 'Meteo';
  const rawCondition = String(info?.condition || '').trim();
  const temp = typeof info?.tempC === 'number' ? `${Math.round(info.tempC)}°C` : '--';
  const iconSvg = renderWeatherIconSvg(String(info?.icon || 'sun'));

  const condition =
    rawCondition ||
    (temp === '--' ? 'Configurer meteo (admin)' : '--');

  elements.wmLoc.textContent = location;
  elements.wmCond.textContent = condition;
  elements.wmTemp.textContent = temp;
  elements.wmIcon.innerHTML = iconSvg;

  const hours = Array.isArray(info?.hourly) ? info.hourly.slice(0, 5) : [];
  elements.wmHours.innerHTML = hours.length
    ? hours.map((h) => {
      const t = String(h?.time || '').trim();
      const v = typeof h?.tempC === 'number' ? `${Math.round(h.tempC)}°` : '--';
      return `<div class=\"wm-hour\">${escapeHtml(t)}<b>${escapeHtml(v)}</b></div>`;
    }).join('')
    : '<div class=\"wm-hour\">--<b>--</b></div>';
}

function renderWeatherIconSvg(name) {
  const n = String(name || '').toLowerCase();
  if (n.includes('rain')) return svgRain();
  if (n.includes('cloud')) return svgCloud();
  if (n.includes('storm')) return svgStorm();
  if (n.includes('snow')) return svgSnow();
  return svgSun();
}

function svgSun() {
  return `<svg viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\">\n    <path d=\"M12 18a6 6 0 1 0 0-12 6 6 0 0 0 0 12Z\" fill=\"rgba(255,255,255,0.92)\"/>\n    <path d=\"M12 1v3M12 20v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M1 12h3M20 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12\" stroke=\"rgba(255,255,255,0.85)\" stroke-width=\"1.6\" stroke-linecap=\"round\"/>\n  </svg>`;
}

function svgCloud() {
  return `<svg viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\">\n    <path d=\"M7.5 19h10.2a4.3 4.3 0 0 0 0-8.6 6.2 6.2 0 0 0-12.1 1.7A3.7 3.7 0 0 0 7.5 19Z\" fill=\"rgba(255,255,255,0.92)\"/>\n  </svg>`;
}

function svgRain() {
  return `<svg viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\">\n    <path d=\"M7.5 14.5h10.2a4.3 4.3 0 0 0 0-8.6 6.2 6.2 0 0 0-12.1 1.7A3.7 3.7 0 0 0 7.5 14.5Z\" fill=\"rgba(255,255,255,0.92)\"/>\n    <path d=\"M8 17l-1 2M12 17l-1 2M16 17l-1 2\" stroke=\"rgba(255,255,255,0.85)\" stroke-width=\"1.6\" stroke-linecap=\"round\"/>\n  </svg>`;
}

function svgStorm() {
  return `<svg viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\">\n    <path d=\"M7.5 14.2h10.2a4.3 4.3 0 0 0 0-8.6 6.2 6.2 0 0 0-12.1 1.7A3.7 3.7 0 0 0 7.5 14.2Z\" fill=\"rgba(255,255,255,0.92)\"/>\n    <path d=\"M12.2 14.8 10 19h3l-1.2 4.2L16 18.2h-3l1.2-3.4Z\" fill=\"rgba(255,255,255,0.85)\"/>\n  </svg>`;
}

function svgSnow() {
  return `<svg viewBox=\"0 0 24 24\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\">\n    <path d=\"M7.5 14.5h10.2a4.3 4.3 0 0 0 0-8.6 6.2 6.2 0 0 0-12.1 1.7A3.7 3.7 0 0 0 7.5 14.5Z\" fill=\"rgba(255,255,255,0.92)\"/>\n    <path d=\"M9 17h.01M12 17h.01M15 17h.01M10.5 19h.01M13.5 19h.01\" stroke=\"rgba(255,255,255,0.85)\" stroke-width=\"2.2\" stroke-linecap=\"round\"/>\n  </svg>`;
}

function renderWeatherAdmin(info) {
  if (!elements.weatherLocation) return;
  elements.weatherLocation.value = String(info?.location || '');
  elements.weatherTempC.value = (typeof info?.tempC === 'number') ? String(info.tempC) : '';
  elements.weatherCondition.value = String(info?.condition || '');
  elements.weatherIcon.value = String(info?.icon || 'sun');
  elements.weatherHourly.value = Array.isArray(info?.hourly)
    ? info.hourly.map((h) => `${h.time}=${h.tempC ?? ''}`).join(';')
    : '';
}

function setWeatherAdminMsgFromState(info) {
  if (!elements.weatherAdminMsg) return;
  const updatedAt = info?.updatedAt ? new Date(info.updatedAt).toLocaleString() : null;
  if (updatedAt) {
    elements.weatherAdminMsg.textContent = `Meteo chargee (maj: ${updatedAt}).`;
    return;
  }
  elements.weatherAdminMsg.textContent = 'Aucune meteo enregistree. Renseigner puis Enregistrer.';
}

function parseHourly(text) {
  const raw = String(text || '').split(';').map((s) => s.trim()).filter(Boolean);
  return raw.map((part) => {
    const [time, temp] = part.split('=').map((s) => s.trim());
    const n = Number(temp);
    return { time, tempC: Number.isFinite(n) ? n : null, icon: 'sun' };
  }).filter((x) => x.time);
}

async function onWeatherSave(e) {
  e.preventDefault();
  const payload = {
    location: elements.weatherLocation.value.trim(),
    tempC: elements.weatherTempC.value === '' ? null : Number(elements.weatherTempC.value),
    condition: elements.weatherCondition.value.trim(),
    icon: elements.weatherIcon.value,
    hourly: parseHourly(elements.weatherHourly.value),
  };

  try {
    const res = await fetch('/backend/weather', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json?.message || ('HTTP ' + res.status));
    weatherState = json.data;
    setWeatherAdminMsgFromState(weatherState);
    renderWeather(weatherState);
    renderWeatherAdmin(weatherState);
  } catch (err) {
    elements.weatherAdminMsg.textContent = 'Erreur meteo: ' + err.message;
  }
}

async function onWeatherClear() {
  elements.weatherLocation.value = '';
  elements.weatherTempC.value = '';
  elements.weatherCondition.value = '';
  elements.weatherIcon.value = 'sun';
  elements.weatherHourly.value = '';
  await onWeatherSave(new Event('submit'));
}

async function onWeatherSample() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const baseHour = Number(hh);
  elements.weatherLocation.value = 'Agence';
  elements.weatherTempC.value = '14';
  elements.weatherCondition.value = 'Legere pluie';
  elements.weatherIcon.value = 'rain';

  const hours = [];
  for (let i = 0; i < 5; i++) {
    const h = String((baseHour + i * 2) % 24).padStart(2, '0');
    const t = 14 + i;
    hours.push(`${h}:00=${t}`);
  }
  elements.weatherHourly.value = hours.join(';');

  await onWeatherSave(new Event('submit'));
}

function loadConfig() {
  try {
    const raw = localStorage.getItem('evce2_config');
    if (!raw) return;
    const cfg = JSON.parse(raw);
    if (elements.form) {
      if (cfg.baseUrl) elements.form.baseUrl.value = cfg.baseUrl;
      if (cfg.login) elements.form.login.value = cfg.login;
      if (cfg.refreshSeconds) elements.form.refreshSeconds.value = cfg.refreshSeconds;
    }
    if (elements.tvRefresh) elements.tvRefresh.textContent = `${cfg.refreshSeconds || 10}s`;
  } catch {
    // ignore
  }
}

function rememberSession(payload, refreshSeconds) {
  sessionStorage.setItem('evce2_runtime_session', JSON.stringify({
    baseUrl: payload.baseUrl || '',
    login: payload.login || '',
    token: payload.token || '',
    refreshSeconds,
  }));
}

function clearRememberedSession() {
  sessionStorage.removeItem('evce2_runtime_session');
}

async function tryAutoReconnectWithSavedToken() {
  try {
    const raw = sessionStorage.getItem('evce2_runtime_session');
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (!saved?.token || !saved?.baseUrl) return;

    await connect({
      baseUrl: String(saved.baseUrl),
      login: String(saved.login || ''),
      password: '',
      token: String(saved.token),
    });

    setConnected(true);
    setMessage('Session restauree automatiquement.');
    startPolling(Number(saved.refreshSeconds || 10));
    await refreshNow();
  } catch {
    clearRememberedSession();
  }
}

function setConnected(connected) {
  if (!elements.badge) return;
  elements.badge.className = connected ? 'chip' : 'chip chip-off';
  elements.badge.textContent = connected ? 'API connectee' : 'API hors ligne';
}

function setMessage(text) {
  if (!elements.message) return;
  elements.message.textContent = text;
}

function renderStationCounters(stations) {
  if (!elements.stationsTotal || !elements.stationsActive || !elements.stationsAvailable) return;
  const total = stations.length;
  const active = stations.filter((s) => {
    const st = String(s.status || '').toLowerCase();
    return (Number(s.amperage || 0) > 0) || st.includes('charging') || st.includes('occupied');
  }).length;
  const available = stations.filter((s) => s.isAvailable === true).length;

  elements.stationsTotal.textContent = String(total);
  if (elements.stationsTotal2) elements.stationsTotal2.textContent = String(total);
  elements.stationsActive.textContent = String(active);
  elements.stationsAvailable.textContent = String(available);
}

function extractStatusText(row) {
  const txt = JSON.stringify(row).toLowerCase();
  if (txt.includes('charging')) return 'charging';
  if (txt.includes('available')) return 'available';
  if (txt.includes('fault')) return 'faulted';
  if (txt.includes('offline')) return 'offline';
  return 'unknown';
}

function isAvailableStatus(status) {
  const s = String(status || '').toLowerCase();
  if (s.includes('available') || s.includes('ready') || s === 'idle') return true;
  if (s.includes('charging') || s.includes('occupied') || s.includes('fault') || s.includes('offline')) return false;
  return null;
}

function extractArray(input) {
  if (Array.isArray(input)) return input;
  if (!input || typeof input !== 'object') return [];

  for (const key of ['items', 'results', 'data', 'stations', 'transactions', 'list']) {
    if (Array.isArray(input[key])) return input[key];
  }

  for (const value of Object.values(input)) {
    if (Array.isArray(value)) return value;
  }

  const objectValues = Object.values(input).filter((v) => v && typeof v === 'object' && !Array.isArray(v));
  if (objectValues.length >= 2) return objectValues;

  return [];
}

function pick(obj, keys) {
  if (!obj || typeof obj !== 'object') return null;
  for (const key of keys) {
    if (obj[key] !== undefined && obj[key] !== null) return obj[key];
  }
  return null;
}

function numberOrNull(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function pickDeepNumber(input, keys) {
  if (!input) return null;
  const queue = [input];
  while (queue.length) {
    const node = queue.pop();
    if (!node || typeof node !== 'object') continue;
    for (const key of keys) {
      if (node[key] !== undefined && node[key] !== null) {
        const n = Number(node[key]);
        if (Number.isFinite(n)) return n;
      }
    }
    for (const val of Object.values(node)) {
      if (val && typeof val === 'object') queue.push(val);
    }
  }
  return null;
}

function pickDeepString(input, keys) {
  if (!input) return null;
  const queue = [input];
  while (queue.length) {
    const node = queue.pop();
    if (!node || typeof node !== 'object') continue;
    for (const key of keys) {
      const val = node[key];
      if (typeof val === 'string' && val.trim()) return val.trim();
    }
    for (const v of Object.values(node)) {
      if (v && typeof v === 'object') queue.push(v);
    }
  }
  return null;
}

function extractAllItems(input) {
  const out = [];
  const queue = [input];
  while (queue.length) {
    const node = queue.pop();
    if (Array.isArray(node)) {
      for (const item of node) queue.push(item);
      continue;
    }
    if (!node || typeof node !== 'object') continue;
    out.push(node);
    for (const v of Object.values(node)) {
      if (v && (Array.isArray(v) || typeof v === 'object')) queue.push(v);
    }
  }
  return out;
}

function statusClass(status) {
  const value = String(status || '').toLowerCase();
  if (value.includes('available') || value.includes('ready') || value.includes('idle')) return 'ok';
  if (value.includes('charging') || value.includes('occupied')) return 'warn';
  return 'err';
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
