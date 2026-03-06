function cssVar(name, fallback) {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  } catch {
    return fallback;
  }
}

const colors = {
  primary: cssVar('--primary', '#00ff88'),
  secondary: cssVar('--secondary', '#0099ff'),
  accent: cssVar('--accent', '#ff1493'),
  text: 'rgba(255,255,255,0.72)',
  grid: 'rgba(255,255,255,0.08)',
};

function commonOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        enabled: true,
        backgroundColor: 'rgba(10,14,39,0.92)',
        titleColor: 'rgba(255,255,255,0.92)',
        bodyColor: 'rgba(255,255,255,0.86)',
        borderColor: 'rgba(0,255,136,0.18)',
        borderWidth: 1,
      },
    },
    scales: {
      x: {
        grid: { color: colors.grid, drawBorder: false },
        ticks: { color: colors.text, font: { family: "'JetBrains Mono', monospace", size: 11 } },
      },
      y: {
        grid: { color: colors.grid, drawBorder: false },
        ticks: { color: colors.text, font: { family: "'JetBrains Mono', monospace", size: 11 } },
      },
    },
  };
}

const monthPieLabelPlugin = {
  id: 'monthPieLabelPlugin',
  afterDatasetsDraw(chart) {
    if (chart.canvas?.id !== 'monthPieChart') return;
    const dataset = chart.data?.datasets?.[0];
    const labels = chart.data?.labels || [];
    const values = Array.isArray(dataset?.data) ? dataset.data.map((v) => Number(v) || 0) : [];
    const total = values.reduce((a, b) => a + b, 0);
    if (!total) return;

    const meta = chart.getDatasetMeta(0);
    const ctx = chart.ctx;
    ctx.save();
    ctx.font = "700 10px 'JetBrains Mono', monospace";
    ctx.fillStyle = 'rgba(236,247,255,0.96)';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    meta.data.forEach((arc, i) => {
      const v = values[i];
      if (!v) return;
      const p = Math.round((v / total) * 100);
      if (p < 6) return;
      const angle = (arc.startAngle + arc.endAngle) / 2;
      const r = (arc.innerRadius + arc.outerRadius) / 2;
      const x = arc.x + Math.cos(angle) * r;
      const y = arc.y + Math.sin(angle) * r;
      const txt = `${String(labels[i] || '').slice(0, 4)} ${p}%`;
      ctx.fillText(txt, x, y);
    });
    ctx.restore();
  },
};

export function createCharts() {
  const currentEl = document.getElementById('currentChart');
  const monthPieEl = document.getElementById('monthPieChart');
  const yearEl = document.getElementById('yearChart');
  const stationEl = document.getElementById('stationChart');
  const zonesEl = document.getElementById('zonesChart');
  const accidentsEl = document.getElementById('accidentsChart');

  const currentChart = currentEl ? new Chart(currentEl, {
    type: 'bar',
    data: {
      labels: [],
      datasets: [
        {
          type: 'bar',
          label: 'Energie',
          data: [],
          backgroundColor: 'rgba(0,255,136,0.86)',
          borderColor: 'rgba(255,255,255,0.14)',
          borderWidth: 1,
          borderRadius: 10,
          maxBarThickness: 30,
        },
      ],
    },
    options: {
      ...commonOptions(),
      scales: {
        ...commonOptions().scales,
        x: { ...commonOptions().scales.x, grid: { display: false } },
        y: { ...commonOptions().scales.y, beginAtZero: true, ticks: { ...commonOptions().scales.y.ticks, precision: 2 } },
      },
    },
  }) : null;

  const stationChart = stationEl ? new Chart(stationEl, {
    type: 'bar',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Amperage (A)',
          data: [],
          backgroundColor: 'rgba(0,255,136,0.86)',
          borderColor: 'rgba(0,255,136,0.20)',
          borderWidth: 1,
          borderRadius: 10,
          maxBarThickness: 22,
        },
      ],
    },
    options: {
      ...commonOptions(),
      indexAxis: 'y',
      scales: {
        ...commonOptions().scales,
        x: {
          ...commonOptions().scales.x,
          beginAtZero: true,
          ticks: {
            ...commonOptions().scales.x.ticks,
            precision: 0,
            callback: (value) => `${value}A`,
          },
        },
        y: { ...commonOptions().scales.y, grid: { display: false } },
      },
    },
  }) : null;

  const monthPieChart = monthPieEl ? new Chart(monthPieEl, {
    type: 'doughnut',
    data: {
      labels: ['IRVE', 'CVC', 'Eclairage', 'Courant', 'Etage', 'Divers'],
      datasets: [
        {
          label: 'Repartition conso mois',
          data: [0, 0, 0, 0, 0, 0],
          backgroundColor: [
            'rgba(0,255,136,0.92)',
            'rgba(163,175,194,0.86)',
            'rgba(140,153,173,0.86)',
            'rgba(121,134,155,0.86)',
            'rgba(103,116,138,0.86)',
            'rgba(84,98,121,0.86)',
          ],
          borderColor: 'rgba(10,14,39,0.55)',
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false,
          position: 'bottom',
          labels: {
            color: colors.text,
            font: { family: "'JetBrains Mono', monospace", size: 11 },
            boxWidth: 10,
            padding: 10,
          },
        },
        tooltip: commonOptions().plugins.tooltip,
      },
      cutout: '58%',
    },
    plugins: [monthPieLabelPlugin],
  }) : null;

  const yearChart = yearEl ? new Chart(yearEl, {
    type: 'bar',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Energie annuelle (kWh)',
          data: [],
          backgroundColor: 'rgba(0,255,136,0.86)',
          borderColor: 'rgba(255,255,255,0.14)',
          borderWidth: 1,
          borderRadius: 8,
          maxBarThickness: 30,
        },
      ],
    },
    options: {
      ...commonOptions(),
      scales: {
        ...commonOptions().scales,
        x: { ...commonOptions().scales.x, grid: { display: false } },
        y: { ...commonOptions().scales.y, beginAtZero: true, ticks: { ...commonOptions().scales.y.ticks, precision: 0 } },
      },
    },
  }) : null;

  const zonesChart = zonesEl ? new Chart(zonesEl, {
    type: 'doughnut',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Zones',
          data: [],
          backgroundColor: [
            'rgba(0,255,136,0.86)',
            'rgba(0,153,255,0.86)',
            'rgba(255,20,147,0.78)',
            'rgba(255,170,0,0.80)',
            'rgba(255,255,255,0.30)',
          ],
          borderColor: 'rgba(10,14,39,0.55)',
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          position: 'bottom',
          labels: {
            color: colors.text,
            font: { family: "'JetBrains Mono', monospace", size: 11 },
            boxWidth: 10,
            padding: 12,
          },
        },
        tooltip: commonOptions().plugins.tooltip,
      },
      cutout: '62%',
    },
  }) : null;

  const accidentsChart = accidentsEl ? new Chart(accidentsEl, {
    type: 'doughnut',
    data: {
      labels: ['CVC', 'Defense', 'CFO', 'CFA'],
      datasets: [
        {
          label: 'Accidents',
          data: [0, 0, 0, 0],
          backgroundColor: [
            'rgba(255, 99, 132, 0.85)',
            'rgba(255, 170, 0, 0.85)',
            'rgba(0, 153, 255, 0.85)',
            'rgba(0, 255, 136, 0.85)',
          ],
          borderColor: 'rgba(10,14,39,0.65)',
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          position: 'bottom',
          labels: {
            color: colors.text,
            font: { family: "'JetBrains Mono', monospace", size: 11 },
            boxWidth: 10,
            padding: 10,
          },
        },
        tooltip: commonOptions().plugins.tooltip,
      },
      cutout: '55%',
    },
  }) : null;

  return { currentChart, monthPieChart, yearChart, stationChart, zonesChart, accidentsChart };
}

export function updateCurrentChart(chart, currentData) {
  if (!chart) return;
  const values = [
    Number.isFinite(Number(currentData?.cvc)) ? Number(currentData.cvc) : 0,
    Number.isFinite(Number(currentData?.eclairage)) ? Number(currentData.eclairage) : 0,
    Number.isFinite(Number(currentData?.courant)) ? Number(currentData.courant) : 0,
    Number.isFinite(Number(currentData?.etage)) ? Number(currentData.etage) : 0,
    Number.isFinite(Number(currentData?.divers)) ? Number(currentData.divers) : 0,
  ];
  updateEnergyChart(chart, {
    labels: ['CVC', 'Eclairage', 'Courant', 'Etage', 'Divers'],
    values,
    seriesLabel: 'Puissance instantanee (kW)',
    unit: 'kW',
    type: 'bar',
    palette: [
      colors.secondary,
      colors.primary,
      'rgba(255,170,0,0.9)',
      'rgba(255,20,147,0.78)',
      'rgba(160,196,255,0.85)',
    ],
  });
}

export function updateEnergyChart(chart, view) {
  if (!chart) return;
  const labels = Array.isArray(view?.labels) ? view.labels : [];
  const values = Array.isArray(view?.values) ? view.values.map((v) => Number(v) || 0) : [];
  const unit = String(view?.unit || '');
  const type = view?.type === 'line' ? 'line' : 'bar';

  chart.data.labels = labels;
  chart.data.datasets = [
    {
      type,
      label: String(view?.seriesLabel || 'Energie'),
      data: values,
      borderColor: type === 'line' ? colors.secondary : 'rgba(255,255,255,0.14)',
      backgroundColor: Array.isArray(view?.palette) && view.palette.length
        ? view.palette
        : (type === 'line' ? 'rgba(0,153,255,0.22)' : 'rgba(0,255,136,0.86)'),
      borderWidth: type === 'line' ? 2 : 1,
      borderRadius: type === 'bar' ? 10 : 0,
      maxBarThickness: type === 'bar' ? 34 : undefined,
      fill: type === 'line',
      tension: type === 'line' ? 0.3 : 0,
      pointRadius: type === 'line' ? 2 : 0,
      pointHoverRadius: type === 'line' ? 4 : 0,
    },
  ];

  const maxValue = Math.max(...values, 1);
  chart.options.scales.y.suggestedMax = Math.ceil(maxValue * 1.2);
  chart.options.scales.y.ticks.callback = (value) => `${value}${unit}`;
  chart.update();
}

export function updateMonthPieChart(chart, monthData) {
  if (!chart) return;
  const values = Array.isArray(monthData?.values) ? monthData.values.map((v) => Number(v) || 0) : [0, 0, 0, 0, 0, 0];
  chart.data.labels = Array.isArray(monthData?.labels) ? monthData.labels : ['IRVE', 'CVC', 'Eclairage', 'Courant', 'Etage', 'Divers'];
  chart.data.datasets[0].data = values;
  if (Array.isArray(monthData?.colors) && monthData.colors.length === values.length) {
    chart.data.datasets[0].backgroundColor = monthData.colors;
  }
  chart.update();
}

export function updateAnnualEnergyChart(chart, annualView) {
  if (!chart) return;
  chart.data.labels = Array.isArray(annualView?.labels) ? annualView.labels : [];
  chart.data.datasets[0].data = Array.isArray(annualView?.values) ? annualView.values.map((v) => Number(v) || 0) : [];
  chart.data.datasets[0].label = String(annualView?.seriesLabel || 'Energie annuelle (kWh)');
  const maxV = Math.max(...chart.data.datasets[0].data, 1);
  chart.options.scales.y.suggestedMax = Math.ceil(maxV * 1.15);
  chart.update();
}

export function updateStationChart(chart, stationRows) {
  if (!chart) return;
  const sorted = [...stationRows].sort((a, b) => (b.amperage || 0) - (a.amperage || 0)).slice(0, 6);
  chart.data.labels = sorted.map((s) => s.name);
  chart.data.datasets[0].data = sorted.map((s) => Number(s.amperage || 0));
  const maxAmp = Math.max(...chart.data.datasets[0].data, 1);
  chart.options.scales.x.suggestedMax = Math.ceil(maxAmp * 1.15);
  chart.update();
}

export function updateZonesChart(chart, stationRows) {
  if (!chart) return;
  const counts = new Map();
  for (const s of stationRows) {
    const zone = String(s.zone || 'Sans zone');
    counts.set(zone, (counts.get(zone) || 0) + 1);
  }
  const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  chart.data.labels = sorted.map(([k]) => k);
  chart.data.datasets[0].data = sorted.map(([, v]) => v);
  chart.update();
}

export function updateAccidentsChart(chart, accidents) {
  if (!chart) return;
  const values = [
    Number(accidents?.cvc || 0),
    Number(accidents?.defense || 0),
    Number(accidents?.cfo || 0),
    Number(accidents?.cfa || 0),
  ].map((v) => (Number.isFinite(v) && v >= 0 ? v : 0));
  chart.data.datasets[0].data = values;
  chart.update();
}
