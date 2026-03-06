'use strict';

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { URL } = require('url');

function insecureTlsEnabled() {
  const raw = String(process.env.ALLOW_INSECURE_TLS || '').trim().toLowerCase();
  return raw === '1' || raw === 'true' || raw === 'yes' || raw === 'on';
}

function isPrivateHost(hostname) {
  const h = String(hostname || '').trim().toLowerCase();
  if (h === 'localhost' || h === '127.0.0.1' || h === '::1') {
    return true;
  }

  if (/^10\.\d+\.\d+\.\d+$/.test(h)) return true;
  if (/^192\.168\.\d+\.\d+$/.test(h)) return true;

  const m = h.match(/^172\.(\d+)\.\d+\.\d+$/);
  if (m) {
    const second = Number(m[1]);
    return second >= 16 && second <= 31;
  }

  return false;
}

if (insecureTlsEnabled()) {
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
}

const PORT = Number(process.env.PORT || 8080);
const HOST = String(process.env.HOST || '0.0.0.0');
const HTTPS_PORT = Number(process.env.HTTPS_PORT || 8443);
const HTTPS_CERT_FILE = process.env.HTTPS_CERT_FILE
  ? path.resolve(process.env.HTTPS_CERT_FILE)
  : path.join(__dirname, 'certs', 'localhost-cert.pem');
const HTTPS_KEY_FILE = process.env.HTTPS_KEY_FILE
  ? path.resolve(process.env.HTTPS_KEY_FILE)
  : path.join(__dirname, 'certs', 'localhost-key.pem');
const FORCE_HTTPS = String(process.env.FORCE_HTTPS || '').trim().toLowerCase() === '1'
  || String(process.env.FORCE_HTTPS || '').trim().toLowerCase() === 'true';
const PUBLIC_DIR = path.join(__dirname, 'public');
const AGENCY_INFO_FILE = path.join(__dirname, 'agency-info.json');
const MOTD_FILE = path.join(__dirname, 'motd.json');
const WEATHER_FILE = path.join(__dirname, 'weather.json');
const IRVE_FILE = path.join(__dirname, 'irve.json');
const IRVE_RS485_PORT = String(process.env.IRVE_RS485_PORT || 'COM11');
const IRVE_RS485_BAUD = Number(process.env.IRVE_RS485_BAUD || 19200);
const IRVE_RS485_UNIT_ID = Number(process.env.IRVE_RS485_UNIT_ID || 1);
const IRVE_RS485_ENERGY_REGISTER = parseRegisterAddress(process.env.IRVE_RS485_ENERGY_REGISTER || '0xB02B');

const session = {
  baseUrl: '',
  token: '',
  login: '',
};

let agencyInfo = loadAgencyInfo();
let motd = loadMotd();
let weather = loadWeather();
let irve = loadIrve();
let liveWeatherCache = {
  fetchedAt: 0,
  data: null,
};

function parseRegisterAddress(rawValue) {
  const s = String(rawValue || '').trim();
  if (!s) return 0;
  if (/^0x[0-9a-f]+$/i.test(s)) return parseInt(s, 16);
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
}

function getModbusSerial() {
  try {
    // Optional dependency.
    return require('modbus-serial');
  } catch {
    const err = new Error('Module "modbus-serial" manquant. Installez-le avec: npm i modbus-serial');
    err.status = 500;
    throw err;
  }
}

function sanitizeRs485Config(body) {
  const portPath = String(body?.portPath || '').trim();
  if (!portPath) {
    const err = new Error('portPath est requis (ex: COM3)');
    err.status = 400;
    throw err;
  }

  const baudRate = Number(body?.baudRate || 19200);
  const unitId = Number(body?.unitId || 5);
  const startAddress = Number(body?.startAddress || 0);
  const registerCount = Number(body?.registerCount || 10);
  const timeoutMs = Number(body?.timeoutMs || 2000);
  const registerType = String(body?.registerType || 'holding').toLowerCase() === 'input' ? 'input' : 'holding';

  return {
    portPath,
    baudRate: Number.isFinite(baudRate) ? baudRate : 19200,
    unitId: Number.isFinite(unitId) ? unitId : 5,
    startAddress: Number.isFinite(startAddress) ? startAddress : 0,
    registerCount: Number.isFinite(registerCount) ? Math.max(1, Math.min(125, registerCount)) : 10,
    timeoutMs: Number.isFinite(timeoutMs) ? Math.max(500, Math.min(15000, timeoutMs)) : 2000,
    registerType,
  };
}

function decodeIrveEnergyKwh(regA, regB) {
  const u32 = ((Number(regA || 0) & 0xffff) * 65536) + (Number(regB || 0) & 0xffff);
  const u32sw = ((Number(regB || 0) & 0xffff) * 65536) + (Number(regA || 0) & 0xffff);
  const candidates = [
    { codec: 'uint32_div10', value: u32 / 10 },
    { codec: 'uint32_sw_div10', value: u32sw / 10 },
    { codec: 'uint32_div100', value: u32 / 100 },
    { codec: 'uint32_sw_div100', value: u32sw / 100 },
    { codec: 'uint32_div1000', value: u32 / 1000 },
    { codec: 'uint32_sw_div1000', value: u32sw / 1000 },
    { codec: 'uint32', value: u32 },
    { codec: 'uint32_sw', value: u32sw },
  ];
  const valid = candidates.find((c) => Number.isFinite(c.value) && c.value >= 0 && c.value <= 1_000_000_000);
  return valid || { codec: 'unknown', value: 0 };
}

async function readIrveFromRs485Fixed() {
  const ModbusRTU = getModbusSerial();
  const client = new ModbusRTU();
  const addresses = [Math.max(0, IRVE_RS485_ENERGY_REGISTER - 1), IRVE_RS485_ENERGY_REGISTER];
  const types = ['holding', 'input'];
  try {
    await client.connectRTUBuffered(IRVE_RS485_PORT, {
      baudRate: Number.isFinite(IRVE_RS485_BAUD) ? IRVE_RS485_BAUD : 19200,
      dataBits: 8,
      stopBits: 1,
      parity: 'none',
    });
    client.setID(Number.isFinite(IRVE_RS485_UNIT_ID) ? IRVE_RS485_UNIT_ID : 1);
    client.setTimeout(1200);

    for (const type of types) {
      for (const address of addresses) {
        try {
          const result = type === 'input'
            ? await client.readInputRegisters(address, 2)
            : await client.readHoldingRegisters(address, 2);
          const regs = Array.isArray(result?.data) ? result.data : [];
          if (regs.length < 2) continue;
          const decoded = decodeIrveEnergyKwh(regs[0], regs[1]);
          return {
            pin: 17,
            pulses: Number(irve?.pulses || 0),
            dt_s: irve?.dt_s ?? null,
            power_kw: irve?.power_kw ?? null,
            ea_pulse_kwh: irve?.ea_pulse_kwh ?? null,
            ea_session_kwh: irve?.ea_session_kwh ?? null,
            ea_total_kwh: Number(decoded.value || 0),
            timestamp_iso: new Date().toISOString(),
            timestamp_unix: Math.floor(Date.now() / 1000),
            updatedAt: new Date().toISOString(),
            source: 'rs485-fixed',
            rs485: {
              portPath: IRVE_RS485_PORT,
              baudRate: IRVE_RS485_BAUD,
              unitId: IRVE_RS485_UNIT_ID,
              address,
              type,
              codec: decoded.codec,
              registers: regs,
            },
          };
        } catch {
          // try next combination
        }
      }
    }
    throw new Error('Aucune reponse RS485 exploitable sur l adresse energie configuree.');
  } finally {
    try {
      if (typeof client.close === 'function') await client.close();
    } catch {
      // ignore close errors
    }
  }
}

function sanitizeRs485ScanConfig(body) {
  const base = sanitizeRs485Config(body);
  const idStart = Number(body?.idStart || 1);
  const idEnd = Number(body?.idEnd || 20);
  const addressStart = Number(body?.addressStart || 0);
  const addressEnd = Number(body?.addressEnd || 30);
  const perReadCount = Number(body?.perReadCount || 1);
  const maxMatches = Number(body?.maxMatches || 25);

  return {
    ...base,
    idStart: Math.max(1, Math.min(247, idStart)),
    idEnd: Math.max(1, Math.min(247, idEnd)),
    addressStart: Math.max(0, Math.min(65535, addressStart)),
    addressEnd: Math.max(0, Math.min(65535, addressEnd)),
    perReadCount: Math.max(1, Math.min(10, perReadCount)),
    maxMatches: Math.max(1, Math.min(100, maxMatches)),
  };
}

async function readRs485Snapshot(body) {
  const ModbusRTU = getModbusSerial();
  const cfg = sanitizeRs485Config(body);
  const client = new ModbusRTU();

  try {
    await client.connectRTUBuffered(cfg.portPath, {
      baudRate: cfg.baudRate,
      dataBits: 8,
      stopBits: 1,
      parity: 'none',
    });
    client.setID(cfg.unitId);
    client.setTimeout(cfg.timeoutMs);

    const result = cfg.registerType === 'input'
      ? await client.readInputRegisters(cfg.startAddress, cfg.registerCount)
      : await client.readHoldingRegisters(cfg.startAddress, cfg.registerCount);

    const registers = Array.isArray(result?.data) ? result.data : [];
    return {
      ok: true,
      data: {
        ...cfg,
        timestamp: new Date().toISOString(),
        registers,
        registersHex: registers.map((value) => `0x${Number(value || 0).toString(16).padStart(4, '0')}`),
      },
    };
  } catch (error) {
    const err = new Error(`Lecture RS485 impossible: ${error.message}`);
    err.status = 502;
    throw err;
  } finally {
    try {
      if (typeof client.close === 'function') {
        await client.close();
      }
    } catch {
      // ignore close errors
    }
  }
}

async function scanRs485(body) {
  const ModbusRTU = getModbusSerial();
  const cfg = sanitizeRs485ScanConfig(body);
  const client = new ModbusRTU();
  const startedAt = Date.now();
  const matches = [];

  const idMin = Math.min(cfg.idStart, cfg.idEnd);
  const idMax = Math.max(cfg.idStart, cfg.idEnd);
  const addrMin = Math.min(cfg.addressStart, cfg.addressEnd);
  const addrMax = Math.max(cfg.addressStart, cfg.addressEnd);
  let tries = 0;

  try {
    await client.connectRTUBuffered(cfg.portPath, {
      baudRate: cfg.baudRate,
      dataBits: 8,
      stopBits: 1,
      parity: 'none',
    });
    client.setTimeout(Math.min(cfg.timeoutMs, 1200));

    for (let unitId = idMin; unitId <= idMax; unitId++) {
      client.setID(unitId);
      for (let address = addrMin; address <= addrMax; address++) {
        if (matches.length >= cfg.maxMatches) break;
        tries += 1;
        try {
          const result = cfg.registerType === 'input'
            ? await client.readInputRegisters(address, cfg.perReadCount)
            : await client.readHoldingRegisters(address, cfg.perReadCount);
          const regs = Array.isArray(result?.data) ? result.data : [];
          matches.push({
            unitId,
            address,
            registerType: cfg.registerType,
            values: regs,
            firstValue: regs.length ? Number(regs[0]) : null,
          });
        } catch {
          // no response / illegal address: continue scan
        }
      }
      if (matches.length >= cfg.maxMatches) break;
    }

    return {
      ok: true,
      data: {
        portPath: cfg.portPath,
        baudRate: cfg.baudRate,
        registerType: cfg.registerType,
        idRange: [idMin, idMax],
        addressRange: [addrMin, addrMax],
        tries,
        matches,
        durationMs: Date.now() - startedAt,
        timestamp: new Date().toISOString(),
      },
    };
  } catch (error) {
    const err = new Error(`Scan RS485 impossible: ${error.message}`);
    err.status = 502;
    throw err;
  } finally {
    try {
      if (typeof client.close === 'function') {
        await client.close();
      }
    } catch {
      // ignore close errors
    }
  }
}

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
  });
  res.end(body);
}

function sendFile(res, filePath) {
  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not found');
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = {
      '.html': 'text/html; charset=utf-8',
      '.css': 'text/css; charset=utf-8',
      '.js': 'application/javascript; charset=utf-8',
      '.json': 'application/json; charset=utf-8',
      '.svg': 'image/svg+xml',
      '.ico': 'image/x-icon',
    }[ext] || 'application/octet-stream';

    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
}

function httpJsonGet(urlString, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlString);
    const transport = url.protocol === 'https:' ? https : http;
    const req = transport.request({
      protocol: url.protocol,
      hostname: url.hostname,
      port: url.port || (url.protocol === 'https:' ? 443 : 80),
      method: 'GET',
      path: `${url.pathname}${url.search}`,
      timeout: timeoutMs,
      headers: {
        Accept: 'application/json',
      },
    }, (resApi) => {
      let raw = '';
      resApi.on('data', (chunk) => { raw += chunk; });
      resApi.on('end', () => {
        try {
          resolve(JSON.parse(raw));
        } catch {
          reject(new Error('Invalid JSON response'));
        }
      });
    });
    req.on('timeout', () => req.destroy(new Error('Request timeout')));
    req.on('error', reject);
    req.end();
  });
}

function weatherCodeToLabel(code) {
  const c = Number(code);
  if (c === 0) return { condition: 'Ensoleille', icon: 'sun' };
  if ([1, 2].includes(c)) return { condition: 'Partiellement nuageux', icon: 'cloud' };
  if (c === 3) return { condition: 'Nuageux', icon: 'cloud' };
  if ([45, 48].includes(c)) return { condition: 'Brouillard', icon: 'cloud' };
  if ([51, 53, 55, 56, 57].includes(c)) return { condition: 'Bruine', icon: 'rain' };
  if ([61, 63, 65, 66, 67, 80, 81, 82].includes(c)) return { condition: 'Pluie', icon: 'rain' };
  if ([71, 73, 75, 77, 85, 86].includes(c)) return { condition: 'Neige', icon: 'snow' };
  if ([95, 96, 99].includes(c)) return { condition: 'Orage', icon: 'storm' };
  return { condition: 'Meteo', icon: 'cloud' };
}

async function fetchAixWeatherLive() {
  const now = Date.now();
  if (liveWeatherCache.data && (now - liveWeatherCache.fetchedAt) < 5 * 60 * 1000) {
    return liveWeatherCache.data;
  }

  const url = 'https://api.open-meteo.com/v1/forecast?latitude=43.5297&longitude=5.4474&current=temperature_2m,weather_code&hourly=temperature_2m,weather_code&forecast_days=1&timezone=Europe%2FParis';
  const data = await httpJsonGet(url, 8000);
  const currentTemp = Number(data?.current?.temperature_2m);
  const currentCode = Number(data?.current?.weather_code);
  const mapped = weatherCodeToLabel(currentCode);

  const hourlyTime = Array.isArray(data?.hourly?.time) ? data.hourly.time : [];
  const hourlyTemp = Array.isArray(data?.hourly?.temperature_2m) ? data.hourly.temperature_2m : [];
  const hourlyCode = Array.isArray(data?.hourly?.weather_code) ? data.hourly.weather_code : [];
  const nowHour = new Date().getHours();
  const hourly = [];
  for (let i = 0; i < hourlyTime.length; i++) {
    const t = new Date(hourlyTime[i]);
    if (Number.isNaN(t.getTime())) continue;
    if (t.getHours() < nowHour) continue;
    const rowMapped = weatherCodeToLabel(hourlyCode[i]);
    hourly.push({
      time: `${String(t.getHours()).padStart(2, '0')}:00`,
      tempC: Number.isFinite(Number(hourlyTemp[i])) ? Number(hourlyTemp[i]) : null,
      icon: rowMapped.icon,
    });
    if (hourly.length >= 5) break;
  }

  const out = {
    location: 'Aix-en-Provence',
    tempC: Number.isFinite(currentTemp) ? currentTemp : null,
    condition: mapped.condition,
    icon: mapped.icon,
    hourly,
    updatedAt: new Date().toISOString(),
    source: 'open-meteo',
  };
  liveWeatherCache = { fetchedAt: now, data: out };
  return out;
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 1_000_000) {
        reject(new Error('Body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      if (!raw) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch {
        reject(new Error('Invalid JSON body'));
      }
    });
    req.on('error', reject);
  });
}

function loadAgencyInfo() {
  try {
    if (!fs.existsSync(AGENCY_INFO_FILE)) {
      return {
        name: '',
        address: '',
        contact: '',
        publicUrl: '',
        openTime: '07:00',
        closeTime: '20:00',
        welcomeMessage: '',
        eventsText: '',
        accidents: {
          cvc: 0,
          defense: 0,
          cfo: 0,
          cfa: 0,
        },
        notes: '',
        updatedAt: null,
      };
    }
    const raw = fs.readFileSync(AGENCY_INFO_FILE, 'utf-8');
    const parsed = JSON.parse(raw);
    return {
      name: String(parsed?.name || ''),
      address: String(parsed?.address || ''),
      contact: String(parsed?.contact || ''),
      publicUrl: String(parsed?.publicUrl || ''),
      openTime: String(parsed?.openTime || '07:00'),
      closeTime: String(parsed?.closeTime || '20:00'),
      welcomeMessage: String(parsed?.welcomeMessage || ''),
      eventsText: String(parsed?.eventsText || ''),
      accidents: {
        cvc: Number(parsed?.accidents?.cvc ?? parsed?.accidentCvc ?? 0) || 0,
        defense: Number(parsed?.accidents?.defense ?? parsed?.accidentDefense ?? 0) || 0,
        cfo: Number(parsed?.accidents?.cfo ?? parsed?.accidentCfo ?? 0) || 0,
        cfa: Number(parsed?.accidents?.cfa ?? parsed?.accidentCfa ?? 0) || 0,
      },
      notes: String(parsed?.notes || ''),
      updatedAt: parsed?.updatedAt || null,
    };
  } catch {
    return {
      name: '',
      address: '',
      contact: '',
      publicUrl: '',
      openTime: '07:00',
      closeTime: '20:00',
      welcomeMessage: '',
      eventsText: '',
      accidents: {
        cvc: 0,
        defense: 0,
        cfo: 0,
        cfa: 0,
      },
      notes: '',
      updatedAt: null,
    };
  }
}

function saveAgencyInfo() {
  fs.writeFileSync(AGENCY_INFO_FILE, JSON.stringify(agencyInfo, null, 2), 'utf-8');
}

function sanitizeAgencyInfo(body) {
  const accidents = body?.accidents && typeof body.accidents === 'object' ? body.accidents : body;
  const num = (v) => Math.max(0, Number.isFinite(Number(v)) ? Number(v) : 0);
  return {
    name: String(body?.name || '').trim(),
    address: String(body?.address || '').trim(),
    contact: String(body?.contact || '').trim(),
    publicUrl: String(body?.publicUrl || '').trim(),
    openTime: String(body?.openTime || '07:00').trim() || '07:00',
    closeTime: String(body?.closeTime || '20:00').trim() || '20:00',
    welcomeMessage: String(body?.welcomeMessage || '').trim(),
    eventsText: String(body?.eventsText || '').trim(),
    accidents: {
      cvc: num(accidents?.cvc ?? body?.accidentCvc),
      defense: num(accidents?.defense ?? body?.accidentDefense),
      cfo: num(accidents?.cfo ?? body?.accidentCfo),
      cfa: num(accidents?.cfa ?? body?.accidentCfa),
    },
    notes: String(body?.notes || '').trim(),
    updatedAt: new Date().toISOString(),
  };
}

function loadMotd() {
  try {
    if (!fs.existsSync(MOTD_FILE)) {
      return { title: '', message: '', updatedAt: null };
    }
    const raw = fs.readFileSync(MOTD_FILE, 'utf-8');
    const parsed = JSON.parse(raw);
    return {
      title: String(parsed?.title || ''),
      message: String(parsed?.message || ''),
      updatedAt: parsed?.updatedAt || null,
    };
  } catch {
    return { title: '', message: '', updatedAt: null };
  }
}

function saveMotd() {
  fs.writeFileSync(MOTD_FILE, JSON.stringify(motd, null, 2), 'utf-8');
}

function sanitizeMotd(body) {
  return {
    title: String(body?.title || '').trim(),
    message: String(body?.message || '').trim(),
    updatedAt: new Date().toISOString(),
  };
}

function loadWeather() {
  try {
    if (!fs.existsSync(WEATHER_FILE)) {
      return {
        location: '',
        tempC: null,
        condition: '',
        icon: 'sun',
        hourly: [],
        updatedAt: null,
      };
    }
    const raw = fs.readFileSync(WEATHER_FILE, 'utf-8');
    const parsed = JSON.parse(raw);
    return {
      location: String(parsed?.location || ''),
      tempC: typeof parsed?.tempC === 'number' ? parsed.tempC : null,
      condition: String(parsed?.condition || ''),
      icon: String(parsed?.icon || 'sun'),
      hourly: Array.isArray(parsed?.hourly) ? parsed.hourly : [],
      updatedAt: parsed?.updatedAt || null,
    };
  } catch {
    return {
      location: '',
      tempC: null,
      condition: '',
      icon: 'sun',
      hourly: [],
      updatedAt: null,
    };
  }
}

function saveWeather() {
  fs.writeFileSync(WEATHER_FILE, JSON.stringify(weather, null, 2), 'utf-8');
}

function sanitizeWeather(body) {
  const hourly = Array.isArray(body?.hourly) ? body.hourly : [];
  const normalizedHourly = hourly
    .slice(0, 8)
    .map((row) => ({
      time: String(row?.time || '').trim(),
      tempC: Number.isFinite(Number(row?.tempC)) ? Number(row.tempC) : null,
      icon: String(row?.icon || '').trim() || 'sun',
    }))
    .filter((row) => row.time);

  return {
    location: String(body?.location || '').trim(),
    tempC: Number.isFinite(Number(body?.tempC)) ? Number(body.tempC) : null,
    condition: String(body?.condition || '').trim(),
    icon: String(body?.icon || 'sun').trim() || 'sun',
    hourly: normalizedHourly,
    updatedAt: new Date().toISOString(),
  };
}

function loadIrve() {
  try {
    if (!fs.existsSync(IRVE_FILE)) {
      return {
        pin: 17,
        pulses: 0,
        dt_s: null,
        power_kw: null,
        ea_pulse_kwh: 0,
        ea_session_kwh: 0,
        ea_total_kwh: 0,
        timestamp_iso: null,
        timestamp_unix: null,
        updatedAt: null,
      };
    }
    const raw = fs.readFileSync(IRVE_FILE, 'utf-8');
    const parsed = JSON.parse(raw);
    return sanitizeIrve(parsed);
  } catch {
    return {
      pin: 17,
      pulses: 0,
      dt_s: null,
      power_kw: null,
      ea_pulse_kwh: 0,
      ea_session_kwh: 0,
      ea_total_kwh: 0,
      timestamp_iso: null,
      timestamp_unix: null,
      updatedAt: null,
    };
  }
}

function saveIrve() {
  fs.writeFileSync(IRVE_FILE, JSON.stringify(irve, null, 2), 'utf-8');
}

function sanitizeIrve(body) {
  const num = (v, fallback = 0) => (Number.isFinite(Number(v)) ? Number(v) : fallback);
  const nullableNum = (v) => (Number.isFinite(Number(v)) ? Number(v) : null);
  return {
    pin: num(body?.pin, 17),
    pulses: Math.max(0, num(body?.pulses, 0)),
    dt_s: nullableNum(body?.dt_s),
    power_kw: nullableNum(body?.power_kw),
    ea_pulse_kwh: Math.max(0, num(body?.ea_pulse_kwh, 0)),
    ea_session_kwh: Math.max(0, num(body?.ea_session_kwh, 0)),
    ea_total_kwh: Math.max(0, num(body?.ea_total_kwh, 0)),
    timestamp_iso: body?.timestamp_iso ? String(body.timestamp_iso) : null,
    timestamp_unix: nullableNum(body?.timestamp_unix),
    updatedAt: new Date().toISOString(),
  };
}

function normalizeBaseUrl(baseUrl) {
  if (!baseUrl || typeof baseUrl !== 'string') {
    throw new Error('baseUrl is required');
  }

  let trimmed = baseUrl.trim().replace(/\/$/, '');
  if (!/^https?:\/\//i.test(trimmed)) {
    trimmed = `https://${trimmed}`;
  }

  const parsed = new URL(trimmed);

  if (!/^https?:$/.test(parsed.protocol)) {
    throw new Error('baseUrl must be http or https');
  }

  let normalized = parsed.toString().replace(/\/$/, '');
  if (!/\/api\/v2$/i.test(normalized)) {
    normalized = `${normalized}/api/v2`;
  }

  return normalized;
}

function authHeaders() {
  if (!session.token) {
    return {};
  }

  return {
    Authorization: `Bearer ${session.token}`,
    'X-Auth-Token': session.token,
    token: session.token,
  };
}

async function apiRequest(endpoint, options = {}) {
  if (!session.baseUrl) {
    throw new Error('Not connected');
  }

  const url = new URL(`${session.baseUrl}${endpoint}`);
  const headers = {
    Accept: 'application/json',
    ...authHeaders(),
    ...(options.headers || {}),
  };

  const payload = options.body || null;
  if (payload && headers['Content-Length'] == null) {
    headers['Content-Length'] = Buffer.byteLength(payload);
  }

  const reqOptions = {
    protocol: url.protocol,
    hostname: url.hostname,
    port: url.port || (url.protocol === 'https:' ? 443 : 80),
    method: options.method || 'GET',
    path: `${url.pathname}${url.search}`,
    headers,
    timeout: 15000,
  };

  if (url.protocol === 'https:' && (insecureTlsEnabled() || isPrivateHost(url.hostname))) {
    reqOptions.rejectUnauthorized = false;
  }

  const transport = url.protocol === 'https:' ? https : http;

  return new Promise((resolve, reject) => {
    const req = transport.request(reqOptions, (resApi) => {
      let raw = '';
      resApi.on('data', (chunk) => {
        raw += chunk;
      });
      resApi.on('end', () => {
        let data = null;
        if (raw) {
          try {
            data = JSON.parse(raw);
          } catch {
            data = { raw };
          }
        }

        const statusCode = Number(resApi.statusCode || 0);
        if (statusCode < 200 || statusCode >= 300) {
          const err = new Error(`API ${endpoint} failed with ${statusCode}`);
          err.status = statusCode;
          err.details = data;
          reject(err);
          return;
        }

        resolve(data);
      });
    });

    req.on('timeout', () => {
      req.destroy(new Error('Request timeout'));
    });

    req.on('error', (error) => {
      const detail = error?.message || 'Unknown network error';
      const fetchError = new Error(`Cannot reach EVCE2 API at ${url.toString()}. ${detail}`);
      fetchError.status = 502;
      fetchError.details = {
        hint: 'Verify EVCE2 IP/reachability. For self-signed cert, use ALLOW_INSECURE_TLS=1.',
      };
      reject(fetchError);
    });

    if (payload) {
      req.write(payload);
    }
    req.end();
  });
}

async function connect(body) {
  const baseUrl = normalizeBaseUrl(body.baseUrl);
  const login = String(body.login || '').trim();
  const password = String(body.password || '').trim();
  const rawToken = String(body.token || '').trim();
  const directToken = rawToken.replace(/^Bearer\s+/i, '');

  if (!directToken && (!login || !password)) {
    throw new Error('Provide either token, or login and password.');
  }

  session.baseUrl = baseUrl;
  session.login = login;
  session.token = '';

  if (directToken) {
    session.token = directToken;
    try {
      await apiRequest('/stations/models');
    } catch (error) {
      session.token = '';
      if (error.status === 401 || error.status === 403) {
        const e = new Error(`Token authentication failed (${error.status}).`);
        e.status = error.status;
        e.details = error.details || null;
        throw e;
      }
      throw error;
    }

    return {
      connected: true,
      baseUrl: session.baseUrl,
      login: session.login || 'token-auth',
    };
  }

  let data;
  try {
    data = await apiRequest('/login/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ login, password }),
    });
  } catch (error) {
    if (error.status === 401) {
      const e = new Error('Authentication failed (401): invalid login/password.');
      e.status = 401;
      e.details = error.details || null;
      throw e;
    }
    if (error.status === 403) {
      const e = new Error('Authentication refused (403): account may be blocked after too many failed attempts, or user not allowed for API.');
      e.status = 403;
      e.details = error.details || null;
      throw e;
    }
    throw error;
  }

  const token = data?.token || data?.access_token || data?.jwt;
  if (!token) {
    throw new Error('Token not found in login response');
  }

  session.token = token;

  return {
    connected: true,
    baseUrl: session.baseUrl,
    login: session.login,
  };
}

async function disconnect() {
  if (session.baseUrl && session.token) {
    try {
      await apiRequest('/login/logout', { method: 'POST' });
    } catch {
      // Best effort logout.
    }
  }

  session.baseUrl = '';
  session.token = '';
  session.login = '';

  return { connected: false };
}

async function pollData() {
  const targets = [
    { key: 'stations', path: '/stations' },
    { key: 'statuses', path: '/stations/statuses' },
    { key: 'zones', path: '/em/zones' },
    { key: 'configEm', path: '/config/em' },
    { key: 'ongoingTransactions', path: '/transactions/ongoing' },
    { key: 'endedTransactions', path: '/transactions/ended' },
    { key: 'productStatus', path: '/maintenance/product_status' },
  ];

  const entries = await Promise.all(
    targets.map(async (target) => {
      try {
        const data = await apiRequest(target.path);
        return [target.key, { ok: true, data }];
      } catch (error) {
        return [
          target.key,
          {
            ok: false,
            error: error.message,
            status: error.status || null,
            details: error.details || null,
          },
        ];
      }
    })
  );

  const dataMap = Object.fromEntries(entries);
  const zoneStations = await fetchZoneStations(dataMap.zones);
  if (zoneStations) {
    dataMap.zoneStations = zoneStations;
  }
  dataMap.agencyInfo = { ok: true, data: agencyInfo };
  dataMap.motd = { ok: true, data: motd };
  try {
    const liveWeather = await fetchAixWeatherLive();
    weather = { ...weather, ...liveWeather };
    dataMap.weather = { ok: true, data: weather };
  } catch (error) {
    dataMap.weather = { ok: true, data: weather, liveError: error.message };
  }
  try {
    const liveIrve = await readIrveFromRs485Fixed();
    irve = { ...irve, ...liveIrve };
    dataMap.irve = { ok: true, data: irve };
  } catch (error) {
    dataMap.irve = { ok: true, data: irve, liveError: error.message };
  }

  return {
    timestamp: new Date().toISOString(),
    baseUrl: session.baseUrl,
    connected: Boolean(session.token),
    data: dataMap,
  };
}

function extractArray(input) {
  if (Array.isArray(input)) return input;
  if (!input || typeof input !== 'object') return [];

  for (const key of ['items', 'results', 'data', 'stations', 'transactions', 'list', 'zones']) {
    if (Array.isArray(input[key])) return input[key];
  }

  for (const value of Object.values(input)) {
    if (Array.isArray(value)) return value;
  }

  const objectValues = Object.values(input).filter((value) => value && typeof value === 'object' && !Array.isArray(value));
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

async function fetchZoneStations(zonesEntry) {
  if (!zonesEntry?.ok) {
    return null;
  }

  const zones = extractArray(zonesEntry.data);
  if (!zones.length) {
    return { ok: true, data: {} };
  }

  const requests = await Promise.all(
    zones.map(async (zone) => {
      const zoneId = pick(zone, ['id', 'zone_id']);
      const zoneName = String(
        pick(zone, ['name', 'zone_name', 'label']) ||
        zone?.desc?.name ||
        zoneId ||
        'Zone'
      );
      if (!zoneId) {
        return null;
      }

      try {
        const stationsData = await apiRequest(`/em/zones/${zoneId}/stations`);
        const stationList = extractArray(stationsData);
        return {
          zoneName,
          stationList,
        };
      } catch (error) {
        return {
          zoneName,
          stationList: [],
          error: error.message,
        };
      }
    })
  );

  const map = {};
  for (const result of requests) {
    if (!result) continue;
    for (const station of result.stationList) {
      const stationId = pick(station, ['id', 'station_id', 'evse_id']);
      if (!stationId) continue;
      map[String(stationId)] = result.zoneName;
    }
  }

  return { ok: true, data: map };
}

async function routeApi(req, res, pathname) {
  try {
    if (pathname === '/backend/connect' && req.method === 'POST') {
      const body = await parseBody(req);
      const result = await connect(body);
      sendJson(res, 200, result);
      return true;
    }

    if (pathname === '/backend/disconnect' && req.method === 'POST') {
      const result = await disconnect();
      sendJson(res, 200, result);
      return true;
    }

    if (pathname === '/backend/poll' && req.method === 'GET') {
      if (!session.baseUrl || !session.token) {
        sendJson(res, 401, { message: 'Not connected' });
        return true;
      }

      const result = await pollData();
      sendJson(res, 200, result);
      return true;
    }

    if (pathname === '/backend/session' && req.method === 'GET') {
      sendJson(res, 200, {
        connected: Boolean(session.token),
        baseUrl: session.baseUrl,
        login: session.login,
      });
      return true;
    }

    if (pathname === '/backend/agency' && req.method === 'GET') {
      sendJson(res, 200, { ok: true, data: agencyInfo });
      return true;
    }

    if (pathname === '/backend/agency' && req.method === 'POST') {
      const body = await parseBody(req);
      agencyInfo = sanitizeAgencyInfo(body);
      saveAgencyInfo();
      sendJson(res, 200, { ok: true, data: agencyInfo });
      return true;
    }

    if (pathname === '/backend/motd' && req.method === 'GET') {
      sendJson(res, 200, { ok: true, data: motd });
      return true;
    }

    if (pathname === '/backend/motd' && req.method === 'POST') {
      const body = await parseBody(req);
      motd = sanitizeMotd(body);
      saveMotd();
      sendJson(res, 200, { ok: true, data: motd });
      return true;
    }

    if (pathname === '/backend/weather' && req.method === 'GET') {
      try {
        const liveWeather = await fetchAixWeatherLive();
        weather = { ...weather, ...liveWeather };
        sendJson(res, 200, { ok: true, data: weather });
      } catch (error) {
        sendJson(res, 200, { ok: true, data: weather, liveError: error.message });
      }
      return true;
    }

    if (pathname === '/backend/weather' && req.method === 'POST') {
      const body = await parseBody(req);
      weather = sanitizeWeather(body);
      saveWeather();
      sendJson(res, 200, { ok: true, data: weather });
      return true;
    }

    if (pathname === '/backend/irve' && req.method === 'GET') {
      try {
        const liveIrve = await readIrveFromRs485Fixed();
        irve = { ...irve, ...liveIrve };
        sendJson(res, 200, { ok: true, data: irve });
      } catch (error) {
        sendJson(res, 200, { ok: true, data: irve, liveError: error.message });
      }
      return true;
    }

    if (pathname === '/backend/irve' && req.method === 'POST') {
      const body = await parseBody(req);
      irve = sanitizeIrve(body);
      saveIrve();
      sendJson(res, 200, { ok: true, data: irve });
      return true;
    }

    if (pathname === '/backend/rs485/read' && req.method === 'POST') {
      const body = await parseBody(req);
      const result = await readRs485Snapshot(body);
      sendJson(res, 200, result);
      return true;
    }

    if (pathname === '/backend/rs485/scan' && req.method === 'POST') {
      const body = await parseBody(req);
      const result = await scanRs485(body);
      sendJson(res, 200, result);
      return true;
    }
  } catch (error) {
    sendJson(res, error.status || 400, {
      message: error.message,
      details: error.details || null,
    });
    return true;
  }

  return false;
}

function tryLoadHttpsOptions() {
  try {
    if (!fs.existsSync(HTTPS_CERT_FILE) || !fs.existsSync(HTTPS_KEY_FILE)) {
      return null;
    }
    return {
      cert: fs.readFileSync(HTTPS_CERT_FILE),
      key: fs.readFileSync(HTTPS_KEY_FILE),
    };
  } catch {
    return null;
  }
}

async function handleRequest(req, res, options = {}) {
  const encrypted = Boolean(req.socket && req.socket.encrypted);
  const proto = encrypted ? 'https' : 'http';
  const hostHeader = req.headers.host || `${HOST}:${encrypted ? HTTPS_PORT : PORT}`;
  const url = new URL(req.url, `${proto}://${hostHeader}`);

  if (options.redirectToHttps && !encrypted) {
    const hostOnly = String(hostHeader).split(':')[0];
    const redirectHost = `${hostOnly}:${HTTPS_PORT}`;
    const location = `https://${redirectHost}${url.pathname}${url.search}`;
    res.writeHead(301, { Location: location });
    res.end();
    return;
  }

  if (url.pathname.startsWith('/backend/')) {
    const handled = await routeApi(req, res, url.pathname);
    if (!handled) {
      sendJson(res, 404, { message: 'API route not found' });
    }
    return;
  }

  let filePath = path.join(PUBLIC_DIR, url.pathname === '/' ? '/index.html' : url.pathname);

  if (!filePath.startsWith(PUBLIC_DIR)) {
    res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Forbidden');
    return;
  }

  if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
    filePath = path.join(filePath, 'index.html');
  }

  sendFile(res, filePath);
}

const server = http.createServer((req, res) => {
  handleRequest(req, res, { redirectToHttps: false }).catch(() => {
    res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Internal server error');
  });
});

function getLanIps() {
  const out = [];
  const nets = os.networkInterfaces();
  for (const ifName of Object.keys(nets)) {
    const rows = nets[ifName] || [];
    for (const row of rows) {
      if (!row) continue;
      if (row.family !== 'IPv4') continue;
      if (row.internal) continue;
      out.push(row.address);
    }
  }
  return [...new Set(out)];
}

server.listen(PORT, HOST, () => {
  console.log(`Dashboard server running on http://localhost:${PORT}`);
  const ips = getLanIps();
  if (ips.length) {
    for (const ip of ips) {
      console.log(`LAN access: http://${ip}:${PORT}`);
    }
  } else {
    console.log('LAN access: no IPv4 interface detected.');
  }
  if (insecureTlsEnabled()) {
    console.log('Insecure TLS mode is enabled (self-signed cert accepted).');
  } else {
    console.log('Insecure TLS mode is disabled (strict certificate validation).');
  }

  const httpsOptions = tryLoadHttpsOptions();
  if (!httpsOptions) {
    console.log(`HTTPS disabled: cert/key not found at ${HTTPS_CERT_FILE} and ${HTTPS_KEY_FILE}`);
    return;
  }

  const httpsServer = https.createServer(httpsOptions, (req, res) => {
    handleRequest(req, res, { redirectToHttps: false }).catch(() => {
      res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Internal server error');
    });
  });

  httpsServer.listen(HTTPS_PORT, HOST, () => {
    console.log(`HTTPS server running on https://localhost:${HTTPS_PORT}`);
    for (const ip of ips) {
      console.log(`LAN access TLS: https://${ip}:${HTTPS_PORT}`);
    }
    if (FORCE_HTTPS) {
      server.removeAllListeners('request');
      server.on('request', (req, res) => {
        handleRequest(req, res, { redirectToHttps: true }).catch(() => {
          res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
          res.end('Internal server error');
        });
      });
      console.log('HTTP -> HTTPS redirect is enabled.');
    }
  });
});
