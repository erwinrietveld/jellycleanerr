const dashboardView = document.getElementById('dashboardView');
const statsView = document.getElementById('statsView');
const settingsView = document.getElementById('settingsView');
const loginView = document.getElementById('loginView');
const topbar = document.getElementById('topbar');
const brandDashboardBtn = document.getElementById('brandDashboardBtn');
const navDashboardBtn = document.getElementById('navDashboardBtn');
const navStatsBtn = document.getElementById('navStatsBtn');
const navSettingsBtn = document.getElementById('navSettingsBtn');
const signInNavBtn = document.getElementById('signInNavBtn');
const signOutBtn = document.getElementById('signOutBtn');
const authUserBox = document.getElementById('authUserBox');
const authUserTrigger = document.getElementById('authUserTrigger');
const authUserDropdown = document.getElementById('authUserDropdown');
const authUserName = document.getElementById('authUserName');
const authUserDropdownName = document.getElementById('authUserDropdownName');
const authUserRole = document.getElementById('authUserRole');
const loginForm = document.getElementById('loginForm');
const loginUsername = document.getElementById('loginUsername');
const loginPassword = document.getElementById('loginPassword');
const loginRemember = document.getElementById('loginRemember');
const loginSubmitBtn = document.getElementById('loginSubmitBtn');
const loginMsg = document.getElementById('loginMsg');
const grid = document.getElementById('grid');
const statsOverview = document.getElementById('statsOverview');
const deletedDailyChart = document.getElementById('deletedDailyChart');
const deletedCumulativeChart = document.getElementById('deletedCumulativeChart');
const barChartMeta = document.getElementById('barChartMeta');
const lineChartMeta = document.getElementById('lineChartMeta');
const errorBox = document.getElementById('error');
const subtitle = document.getElementById('subtitle');
const refreshBtn = document.getElementById('refreshBtn');
const refreshStatsBtn = document.getElementById('refreshStatsBtn');
const statsRangePreset = document.getElementById('statsRangePreset');
const customRangeWrap = document.getElementById('customRangeWrap');
const statsRangeStart = document.getElementById('statsRangeStart');
const statsRangeEnd = document.getElementById('statsRangeEnd');
const filterButtons = [...document.querySelectorAll('.chip')];

const settingsForm = document.getElementById('settingsForm');
const refreshUsersBtn = document.getElementById('refreshUsersBtn');
const settingsMsg = document.getElementById('settingsMsg');
const jfUsers = document.getElementById('jfUsers');
const jfUsersWrap = document.getElementById('jfUsersWrap');
const jfLibraries = document.getElementById('jfLibraries');
const jfLibrariesWrap = document.getElementById('jfLibrariesWrap');
const monitorAllUsers = document.getElementById('monitorAllUsers');
const monitorAllLibraries = document.getElementById('monitorAllLibraries');
const removeWatchedEnabled = document.getElementById('removeWatchedEnabled');
const removeWatchedDays = document.getElementById('removeWatchedDays');
const removeUnwatchedEnabled = document.getElementById('removeUnwatchedEnabled');
const removeUnwatchedDays = document.getElementById('removeUnwatchedDays');
const dryRunEnabled = document.getElementById('dryRunEnabled');
const connTestButtons = [...document.querySelectorAll('.conn-test-btn')];
const saveSettingsBtn = document.getElementById('saveSettingsBtn');
const saveSettingsTopBtn = document.getElementById('saveSettingsTopBtn');
const saveButtons = [saveSettingsBtn, saveSettingsTopBtn].filter(Boolean);

const FALLBACK_POSTER = 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22160%22 height=%22240%22%3E%3Crect width=%22100%25%22 height=%22100%25%22 fill=%22%2313264a%22/%3E%3C/svg%3E';
const CATEGORY_META = [
  { key: 'movies', label: 'Movies' },
  { key: 'series', label: 'Series' },
  { key: 'formula1', label: 'Formula 1' },
];

let currentStatus = '';
let currentItems = [];
let currentSummary = null;
let currentStats = null;
let currentView = 'dashboard';
let availableUsers = [];
let availableLibraries = [];
let settingsDirty = false;
let settingsBaseline = '';
let authUser = null;
let formula1Enabled = true;
let statsRangeBaseline = '';

const expandedCategories = new Set(CATEGORY_META.map((x) => x.key));
const expandedSeries = new Set();
const expandedSeasons = new Set();

function esc(v) {
  return String(v ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function splitCsv(raw) {
  return String(raw || '').split(',').map((x) => x.trim()).filter(Boolean);
}

function toLabelCase(value) {
  return String(value || '')
    .replaceAll('_', ' ')
    .split(' ')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function fmtDate(v) {
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function fmtGb(bytes) {
  const b = Number(bytes || 0);
  if (b <= 0) return '0 GB';
  return `${(b / (1024 ** 3)).toFixed(1)} GB`;
}

function normalizeDetailsUrl(rawUrl) {
  try {
    const u = new URL(rawUrl);
    if (u.hostname === 'localhost' || u.hostname === '127.0.0.1') u.hostname = window.location.hostname;
    return u.toString();
  } catch {
    return rawUrl;
  }
}

function countdownLabel(item) {
  const countdown = String(item.countdown || '').trim();
  const reason = String(item.reasonLabel || '').trim();
  const dayMatch = countdown.match(/^(\d+)d$/i);
  const countdownText = dayMatch
    ? `${dayMatch[1]} day${dayMatch[1] === '1' ? '' : 's'}`
    : countdown;
  const isDueNow = item.status === 'due' || /^due now$/i.test(countdown);
  if (isDueNow) return 'Delete due now';
  if (!countdownText && !reason) return '';
  if (!countdownText) return reason;
  if (!reason) return `Deletes in ${countdownText}`;
  return `Deletes in ${countdownText} · ${reason}`;
}

function normalizeCategory(item) {
  if (item.category) return item.category;
  return item.type === 'movie' ? 'movies' : 'series';
}

function activeCategories() {
  return formula1Enabled ? CATEGORY_META : CATEGORY_META.filter((x) => x.key !== 'formula1');
}

function showSettingsMessage(text, isError = false) {
  settingsMsg.textContent = text;
  settingsMsg.style.color = isError ? 'var(--danger)' : 'var(--muted)';
}

function toggleUsersDisabledState() {
  const disabled = !!monitorAllUsers.checked;
  jfUsersWrap.classList.toggle('disabled-users', disabled);
}

function toggleLibrariesDisabledState() {
  const disabled = !!monitorAllLibraries.checked;
  jfLibrariesWrap.classList.toggle('disabled-libraries', disabled);
}

function toggleGeneralRetentionInputs() {
  removeWatchedDays.disabled = !removeWatchedEnabled.checked;
  removeUnwatchedDays.disabled = !removeUnwatchedEnabled.checked;
}

function hasPendingSettingsChanges() {
  return currentView === 'settings' && settingsDirty;
}

function confirmDiscardSettings() {
  if (!hasPendingSettingsChanges()) return true;
  return window.confirm('You have unsaved settings changes. Leave this page anyway?');
}

function setView(view) {
  currentView = view;
  const isDashboard = view === 'dashboard';
  const isStats = view === 'stats';
  const isSettings = view === 'settings';
  const isLogin = view === 'login';
  dashboardView.classList.toggle('hidden', !isDashboard);
  statsView.classList.toggle('hidden', !isStats);
  settingsView.classList.toggle('hidden', !isSettings);
  loginView.classList.toggle('hidden', !isLogin);
  topbar.classList.toggle('hidden', isLogin);
  authUserDropdown.classList.add('hidden');
  navDashboardBtn.classList.toggle('active', isDashboard);
  navStatsBtn.classList.toggle('active', isStats);
  navSettingsBtn.classList.toggle('active', isSettings);
}

function setAuthUi(user) {
  authUser = user;
  const loggedIn = !!user;
  signInNavBtn.classList.add('hidden');
  authUserBox.classList.toggle('hidden', !loggedIn);
  authUserDropdown.classList.add('hidden');
  if (loggedIn) {
    authUserName.textContent = user.name || 'User';
    authUserDropdownName.textContent = user.name || 'User';
    authUserRole.textContent = user.role || '';
  }
}

function showLoginView() {
  setView('login');
}

function movieCard(item) {
  const detailsUrl = normalizeDetailsUrl(item.detailsUrl);
  const keepText = item.keep ? 'Unkeep' : 'Keep';
  const keepClass = item.keep ? 'toggle' : 'toggle off';
  const countdown = (item.status === 'pending' || item.status === 'due')
    ? `<div class="count">${esc(countdownLabel(item))}</div>`
    : '';
  const statusNote = item.status === 'kept'
    ? '<div class="meta">Kept manually (excluded from deletion)</div>'
    : '';

  return `
    <article class="row-card">
      <img class="poster-sm" loading="lazy" src="${esc(item.posterUrl)}" data-fallback="${FALLBACK_POSTER}" alt="${esc(item.name)}">
      <div class="row-main">
        <div class="row top">
          <h3 class="name">${esc(item.name)}</h3>
          <span class="badge ${esc(item.status)}">${esc(toLabelCase(item.status))}</span>
        </div>
        <div class="meta">${esc(item.year || '')}${item.arrSource ? ` • ${esc(item.arrSource)}` : ''} • Movie • ${esc(fmtGb(item.sizeBytes))}</div>
        <div class="meta">Watched by: ${esc(item.watchedBy || 'nobody')}</div>
        <div class="meta">${esc(item.basisLabel || 'Basis')}: ${esc(fmtDate(item.basisAt || item.watchedAt))} • Delete at: ${esc(fmtDate(item.deleteAt))}</div>
        ${statusNote}
        <div class="row-footer">
          ${countdown || '<div></div>'}
          <div class="actions row-actions">
            <a class="link" target="_blank" href="${esc(detailsUrl)}">Open in Jellyfin</a>
            <button class="${keepClass}" data-key="${esc(item.key)}" data-keep="${!item.keep}">${keepText}</button>
            <button class="delete-now" data-key="${esc(item.key)}" data-title="${esc(item.name)}">Delete now</button>
          </div>
        </div>
      </div>
    </article>
  `;
}

function episodeRow(item) {
  const detailsUrl = normalizeDetailsUrl(item.detailsUrl);
  const keepText = item.keep ? 'Unkeep' : 'Keep';
  const keepClass = item.keep ? 'toggle' : 'toggle off';
  const season = String(item.season ?? 0).padStart(2, '0');
  const episode = String(item.episode ?? 0).padStart(2, '0');
  const title = `S${season}E${episode} • ${item.name || 'Episode'}`;
  const countdown = (item.status === 'pending' || item.status === 'due')
    ? `<div class="count">${esc(countdownLabel(item))}</div>`
    : '';
  const statusNote = item.status === 'kept'
    ? '<div class="meta">Kept manually (excluded from deletion)</div>'
    : '';

  return `
    <article class="row-card episode-card">
      <div class="row-main">
        <div class="row top">
          <h3 class="name episode-name">${esc(title)}</h3>
          <span class="badge ${esc(item.status)}">${esc(toLabelCase(item.status))}</span>
        </div>
        <div class="meta">${item.arrSource ? `${esc(item.arrSource)} • ` : ''}Episode • ${esc(fmtGb(item.sizeBytes))}</div>
        <div class="meta">Watched by: ${esc(item.watchedBy || 'nobody')}</div>
        <div class="meta">${esc(item.basisLabel || 'Basis')}: ${esc(fmtDate(item.basisAt || item.watchedAt))} • Delete at: ${esc(fmtDate(item.deleteAt))}</div>
        ${statusNote}
        <div class="row-footer">
          ${countdown || '<div></div>'}
          <div class="actions row-actions">
            <a class="link" target="_blank" href="${esc(detailsUrl)}">Open in Jellyfin</a>
            <button class="${keepClass}" data-key="${esc(item.key)}" data-keep="${!item.keep}">${keepText}</button>
            <button class="delete-now" data-key="${esc(item.key)}" data-title="${esc(title)}">Delete now</button>
          </div>
        </div>
      </div>
    </article>
  `;
}

function groupSeriesItems(items) {
  const map = new Map();
  items.forEach((item) => {
    const seriesName = item.groupName || item.seriesName || item.name || 'Unknown Series';
    const seriesKey = `${normalizeCategory(item)}::${seriesName.toLowerCase()}`;
    if (!map.has(seriesKey)) map.set(seriesKey, { key: seriesKey, name: seriesName, posterUrl: item.posterUrl, items: [] });
    map.get(seriesKey).items.push(item);
  });
  return [...map.values()].sort((a, b) => a.name.localeCompare(b.name));
}

function splitBySeason(episodes) {
  const seasons = new Map();
  episodes.forEach((ep) => {
    const season = Number(ep.season ?? 0);
    if (!seasons.has(season)) seasons.set(season, []);
    seasons.get(season).push(ep);
  });
  return [...seasons.entries()].sort((a, b) => a[0] - b[0]);
}

function renderCollapseButton(kind, key, label, meta) {
  const expandedSet = kind === 'category' ? expandedCategories : kind === 'series' ? expandedSeries : expandedSeasons;
  const expanded = expandedSet.has(key);
  return `
    <button class="collapse-toggle" data-kind="${esc(kind)}" data-key="${esc(key)}">
      <div>
        <div class="group-title-text">${esc(label)}</div>
        <div class="group-title-meta">${esc(meta)}</div>
      </div>
      <span class="chevron ${expanded ? 'open' : ''}" aria-hidden="true"></span>
    </button>
  `;
}

function renderSeason(scopeKey, displayName, seasonNumber, episodes) {
  const seasonKey = `${scopeKey}::season:${seasonNumber}`;
  const expanded = expandedSeasons.has(seasonKey);
  const allKept = episodes.length > 0 && episodes.every((ep) => ep.keep);
  const keepMode = allKept ? 'unkeep' : 'keep';
  const keepLabel = allKept ? 'Unkeep season' : 'Keep season';
  const keys = episodes.map((ep) => ep.key).join('|');
  const seasonLabel = seasonNumber > 0 ? `Season ${seasonNumber}` : 'Season Unknown';
  const unitLabel = scopeKey === 'formula1' ? 'event' : 'episode';
  const seasonBytes = episodes.reduce((sum, ep) => sum + Number(ep.sizeBytes || 0), 0);
  const body = expanded ? `<div class="season-body">${episodes.map(episodeRow).join('')}</div>` : '';

  return `
    <section class="season-group">
      <div class="season-header-row">
        ${renderCollapseButton('season', seasonKey, seasonLabel, `${episodes.length} ${unitLabel}${episodes.length === 1 ? '' : 's'} • ${fmtGb(seasonBytes)}`)}
        <div class="season-actions">
          <button class="toggle season-action" data-mode="${esc(keepMode)}" data-keys="${esc(keys)}">${esc(keepLabel)}</button>
          <button class="delete-now season-action" data-mode="delete" data-keys="${esc(keys)}" data-title="${esc(`${displayName} - ${seasonLabel}`)}">Delete season</button>
        </div>
      </div>
      ${body}
    </section>
  `;
}

function renderSeries(series) {
  const expanded = expandedSeries.has(series.key);
  const seasonBlocks = splitBySeason(series.items);
  const body = expanded
    ? `<div class="series-body">${seasonBlocks.map(([seasonNumber, episodes]) => renderSeason(series.key, series.name, seasonNumber, episodes)).join('')}</div>`
    : '';
  return `
    <section class="series-group">
      <div class="series-header">
        <img class="poster-sm poster-series" loading="lazy" src="${esc(series.posterUrl)}" data-fallback="${FALLBACK_POSTER}" alt="${esc(series.name)}">
        ${renderCollapseButton('series', series.key, series.name, `${seasonBlocks.length} season${seasonBlocks.length === 1 ? '' : 's'} • ${series.items.length} episode${series.items.length === 1 ? '' : 's'}`)}
      </div>
      ${body}
    </section>
  `;
}

function renderCategory(categoryKey, label, items) {
  const expanded = expandedCategories.has(categoryKey);
  const seasonCount = splitBySeason(items).length;
  const categoryMeta = categoryKey === 'formula1'
    ? `${seasonCount} season${seasonCount === 1 ? '' : 's'}`
    : `${items.length} item${items.length === 1 ? '' : 's'}`;
  let body = '';

  if (expanded) {
    if (!items.length) {
      body = '<article class="empty-state">No media in this category.</article>';
    } else if (categoryKey === 'movies') {
      body = `<div class="category-body">${items.map(movieCard).join('')}</div>`;
    } else if (categoryKey === 'formula1') {
      const seasonBlocks = splitBySeason(items);
      body = `<div class="category-body">${seasonBlocks.map(([seasonNumber, episodes]) => renderSeason('formula1', 'Formula 1', seasonNumber, episodes)).join('')}</div>`;
    } else {
      body = `<div class="category-body">${groupSeriesItems(items).map(renderSeries).join('')}</div>`;
    }
  }

  return `<section class="category-group">${renderCollapseButton('category', categoryKey, label, categoryMeta)}${body}</section>`;
}

function renderList(items) {
  if (!items.length) {
    grid.innerHTML = '<article class="empty-state">No media in this filter.</article>';
    return;
  }
  grid.innerHTML = activeCategories().map((cat) => renderCategory(cat.key, cat.label, items.filter((item) => normalizeCategory(item) === cat.key))).join('');
}

function statCard(primary, secondary) {
  return `<article class="stat"><div class="k">${esc(primary)}</div><div class="l">${esc(secondary)}</div></article>`;
}

function fmtItemsGb(count, sizeBytes) {
  return `${count} Items (${fmtGb(sizeBytes)})`;
}

function formatAxisDate(isoDate, granularity) {
  const d = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(d.getTime())) return isoDate;
  if (granularity === 'day') return isoDate;
  if (granularity === 'week') return isoDate;
  if (granularity === 'month') return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  return String(d.getFullYear());
}

function nowLinePercent(range) {
  if (!range || !range.start || !range.end) return null;
  const start = new Date(`${range.start}T00:00:00Z`).getTime();
  const end = new Date(`${range.end}T23:59:59Z`).getTime();
  const now = Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  if (now < start || now > end) return null;
  return ((now - start) / (end - start)) * 100;
}

let dailyChartInstance = null;
let cumulativeChartInstance = null;

function cssVar(name, fallback = '') {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function chartTheme() {
  return {
    muted: cssVar('--muted', '#94a3b8'),
    now: cssVar('--chart-now', '#f59e0b'),
    barBorder: cssVar('--chart-bar-border', '#60a5fa'),
    barFill: cssVar('--chart-bar-fill', 'rgba(96,165,250,0.35)'),
    lineBorder: cssVar('--chart-bar-border', '#60a5fa'),
    lineFill: cssVar('--chart-bar-fill', 'rgba(96,165,250,0.12)'),
    gridX: cssVar('--chart-grid-x', 'rgba(148,163,184,0.16)'),
    gridY: cssVar('--chart-grid-y', 'rgba(148,163,184,0.22)'),
  };
}

const chartOverlayPlugin = {
  id: 'chartOverlayPlugin',
  afterDraw(chart, _args, options) {
    const { ctx, chartArea, scales } = chart;
    if (!chartArea || !scales.x || !scales.y) return;
    const theme = chartTheme();

    if (options?.showNoData) {
      ctx.save();
      ctx.fillStyle = theme.muted;
      ctx.font = '14px Inter, system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('No data in range', (chartArea.left + chartArea.right) / 2, (chartArea.top + chartArea.bottom) / 2);
      ctx.restore();
    }

    if (typeof options?.nowIndex === 'number') {
      const x = scales.x.getPixelForValue(options.nowIndex);
      ctx.save();
      ctx.strokeStyle = theme.now;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.fillStyle = theme.now;
      ctx.font = '11px Inter, system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText('Now', x, Math.max(chartArea.top - 4, 10));
      ctx.restore();
    }
  },
};

function chartLabels(points, granularity) {
  return points.map((p) => formatAxisDate(p.bucketStart, granularity));
}

function nowIndexInPoints(points, range) {
  const pct = nowLinePercent(range);
  if (pct === null || points.length < 2) return null;
  return ((pct / 100) * (points.length - 1));
}

function chartTickLabel(value, index, ticks, axis) {
  const total = Array.isArray(ticks) ? ticks.length : 0;
  if (total <= 0) return '';
  const maxVisible = 9;
  const step = Math.max(1, Math.ceil(total / maxVisible));
  const isEdge = index === 0 || index === total - 1;
  const shouldShow = isEdge || index % step === 0;
  if (!shouldShow) return '';
  const raw = axis.getLabelForValue(value);
  return String(raw || '');
}

function ensureCharts() {
  if (!window.Chart) return;
  const theme = chartTheme();
  if (!dailyChartInstance) {
    dailyChartInstance = new window.Chart(deletedDailyChart.getContext('2d'), {
      type: 'bar',
      data: { labels: [], datasets: [{ data: [], borderColor: theme.barBorder, backgroundColor: theme.barFill, borderWidth: 1.5, barPercentage: 1, categoryPercentage: 1 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { top: 24, right: 8, bottom: 0, left: 0 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            intersect: false,
            mode: 'index',
            callbacks: {
              label(context) {
                const v = Number(context.parsed.y || 0);
                return `${v.toFixed(1)} GB`;
              },
            },
          },
          chartOverlayPlugin: {},
        },
        scales: {
          x: {
            offset: false,
            ticks: {
              autoSkip: true,
              maxTicksLimit: 9,
              maxRotation: 0,
              minRotation: 0,
              color: theme.muted,
              callback(value, index, ticks) {
                return chartTickLabel(value, index, ticks, this);
              },
            },
            grid: { color: theme.gridX },
          },
          y: {
            beginAtZero: true,
            afterFit(scale) {
              scale.width = 76;
            },
            ticks: {
              color: theme.muted,
              callback(value, idx) {
                if (idx > 0 && this.max === 0) return '';
                return fmtGb(Number(value) * (1024 ** 3));
              },
            },
            grid: { color: theme.gridY },
          },
        },
      },
      plugins: [chartOverlayPlugin],
    });
  }
  if (!cumulativeChartInstance) {
    cumulativeChartInstance = new window.Chart(deletedCumulativeChart.getContext('2d'), {
      type: 'line',
      data: { labels: [], datasets: [{ data: [], borderColor: theme.lineBorder, backgroundColor: theme.lineFill, fill: false, pointRadius: 0, borderWidth: 3, tension: 0 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { top: 24, right: 8, bottom: 0, left: 0 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            intersect: false,
            mode: 'index',
            callbacks: {
              label(context) {
                const v = Number(context.parsed.y || 0);
                return `${v.toFixed(1)} GB`;
              },
            },
          },
          chartOverlayPlugin: {},
        },
        scales: {
          x: {
            offset: false,
            ticks: {
              autoSkip: true,
              maxTicksLimit: 9,
              maxRotation: 0,
              minRotation: 0,
              color: theme.muted,
              callback(value, index, ticks) {
                return chartTickLabel(value, index, ticks, this);
              },
            },
            grid: { color: theme.gridX },
          },
          y: {
            beginAtZero: true,
            afterFit(scale) {
              scale.width = 76;
            },
            ticks: {
              color: theme.muted,
              callback(value, idx) {
                if (idx > 0 && this.max === 0) return '';
                return fmtGb(Number(value) * (1024 ** 3));
              },
            },
            grid: { color: theme.gridY },
          },
        },
      },
      plugins: [chartOverlayPlugin],
    });
  }
}

function renderDailyDeletedBars(points) {
  ensureCharts();
  if (!dailyChartInstance) return;
  const theme = chartTheme();
  const labels = chartLabels(points, (currentStats?.range || {}).granularity || 'day');
  const valuesGb = points.map((p) => Number(p.totalSizeBytes || 0) / (1024 ** 3));
  const hasData = valuesGb.some((v) => v > 0);
  const nowIndex = nowIndexInPoints(points, currentStats?.range);

  dailyChartInstance.data.labels = labels;
  dailyChartInstance.data.datasets[0].data = valuesGb;
  dailyChartInstance.data.datasets[0].borderColor = theme.barBorder;
  dailyChartInstance.data.datasets[0].backgroundColor = theme.barFill;
  dailyChartInstance.options.scales.x.ticks.color = theme.muted;
  dailyChartInstance.options.scales.x.grid.color = theme.gridX;
  dailyChartInstance.options.scales.y.ticks.color = theme.muted;
  dailyChartInstance.options.scales.y.grid.color = theme.gridY;
  dailyChartInstance.options.plugins.chartOverlayPlugin = { showNoData: !hasData, nowIndex };
  dailyChartInstance.update();
}

function renderDeletedCumulative(points) {
  ensureCharts();
  if (!cumulativeChartInstance) return;
  const theme = chartTheme();
  const labels = chartLabels(points, (currentStats?.range || {}).granularity || 'day');
  let running = 0;
  const cumulativeGb = points.map((p) => {
    running += Number(p.totalSizeBytes || 0);
    return running / (1024 ** 3);
  });
  const hasData = cumulativeGb.some((v) => v > 0);
  const nowIndex = nowIndexInPoints(points, currentStats?.range);

  cumulativeChartInstance.data.labels = labels;
  cumulativeChartInstance.data.datasets[0].data = cumulativeGb;
  cumulativeChartInstance.data.datasets[0].borderColor = theme.lineBorder;
  cumulativeChartInstance.data.datasets[0].backgroundColor = theme.lineFill;
  cumulativeChartInstance.options.scales.x.ticks.color = theme.muted;
  cumulativeChartInstance.options.scales.x.grid.color = theme.gridX;
  cumulativeChartInstance.options.scales.y.ticks.color = theme.muted;
  cumulativeChartInstance.options.scales.y.grid.color = theme.gridY;
  cumulativeChartInstance.options.plugins.chartOverlayPlugin = { showNoData: !hasData, nowIndex };
  cumulativeChartInstance.update();
}

function renderStatsView(statsData) {
  const current = statsData.current || {};
  const deleted = statsData.deleted || {};
  const pendingCount = Number(current.pendingCount || 0);
  const pendingSize = Number(current.pendingSizeBytes || 0);
  const pendingWatchedCount = Number(current.pendingWatchedCount || 0);
  const pendingWatchedSize = Number(current.pendingWatchedSizeBytes || 0);
  const pendingIdleCount = Number(current.pendingIdleCount || 0);
  const pendingIdleSize = Number(current.pendingIdleSizeBytes || 0);
  const dueCount = Number(current.dueCount || 0);
  const dueSize = Number(current.dueSizeBytes || 0);
  const keptCount = Number(current.keptCount || 0);
  const keptSize = Number(current.keptSizeBytes || 0);
  const deletedCount = Number(deleted.totalCount || 0);
  const deletedSize = Number(deleted.totalSizeBytes || 0);
  const deletedRecentCount = Number(deleted.recentCount || 0);
  const deletedRecentSize = Number(deleted.recentSizeBytes || 0);
  const trackedCount = pendingCount + keptCount;
  const trackedSize = pendingSize + keptSize;
  statsOverview.innerHTML = [
    statCard('Kept', fmtItemsGb(keptCount, keptSize)),
    statCard('Pending (Watched)', fmtItemsGb(pendingWatchedCount, pendingWatchedSize)),
    statCard('Pending (Idle)', fmtItemsGb(pendingIdleCount, pendingIdleSize)),
    statCard('Pending (Total)', fmtItemsGb(pendingCount, pendingSize)),
    statCard('Due', fmtItemsGb(dueCount, dueSize)),
    statCard('Deleted (Last 30 Days)', fmtItemsGb(deletedRecentCount, deletedRecentSize)),
    statCard('Total Deleted', fmtItemsGb(deletedCount, deletedSize)),
    statCard('Total Tracked', fmtItemsGb(trackedCount, trackedSize)),
  ].join('');
  const timeline = statsData.timeline || [];
  renderDailyDeletedBars(timeline);
  renderDeletedCumulative(timeline);
  const range = statsData.range || {};
  const granLabel = `Per ${String(range.granularity || 'day').replace(/^./, (c) => c.toUpperCase())}`;
  barChartMeta.textContent = `${granLabel} · ${range.start || ''} to ${range.end || ''}`;
  lineChartMeta.textContent = `${granLabel} · ${range.start || ''} to ${range.end || ''}`;
}

async function toggleKeep(key, keep) {
  const res = await fetch('/api/keep', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, keep }),
  });
  if (!res.ok) throw new Error('Failed to update keep');
}

async function bulkAction(mode, keys) {
  const res = await fetch('/api/bulk-action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, keys }),
  });
  const out = await res.json();
  if (!res.ok || !out.ok) throw new Error(out.error || 'Bulk action failed');
}

function rerender() {
  renderList(currentItems);
  wireButtons();
}

function parseKeys(raw) {
  return String(raw || '').split('|').map((k) => k.trim()).filter(Boolean);
}

function wireButtons() {
  document.querySelectorAll('.poster-sm').forEach((img) => {
    img.addEventListener('error', () => {
      if (img.src !== img.dataset.fallback) img.src = img.dataset.fallback;
    });
  });

  document.querySelectorAll('.collapse-toggle').forEach((btn) => {
    btn.addEventListener('click', () => {
      const kind = btn.dataset.kind;
      const key = btn.dataset.key;
      if (!kind || !key) return;
      const targetSet = kind === 'category' ? expandedCategories : kind === 'series' ? expandedSeries : expandedSeasons;
      if (targetSet.has(key)) targetSet.delete(key);
      else targetSet.add(key);
      rerender();
    });
  });

  document.querySelectorAll('.season-action').forEach((btn) => {
    btn.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      const mode = btn.dataset.mode;
      const keys = parseKeys(btn.dataset.keys);
      if (!keys.length) return;
      if (mode === 'delete') {
        const title = btn.dataset.title || 'this season';
        const confirmed = window.confirm(`Delete immediately for "${title}"?\n\nThis will try to remove all episodes from disk, Jellyfin, Sonarr, qBittorrent and Seerr.`);
        if (!confirmed) return;
      }
      btn.disabled = true;
      try {
        await bulkAction(mode, keys);
        await load(true);
      } catch (err) {
        errorBox.innerHTML = `<div class="error">${esc(err.message)}</div>`;
      } finally {
        btn.disabled = false;
      }
    });
  });

  document.querySelectorAll('.toggle:not(.season-action)').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        await toggleKeep(btn.dataset.key, btn.dataset.keep === 'true');
        await load(true);
      } catch (err) {
        errorBox.innerHTML = `<div class="error">${esc(err.message)}</div>`;
      } finally {
        btn.disabled = false;
      }
    });
  });

  document.querySelectorAll('.delete-now:not(.season-action)').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const key = btn.dataset.key;
      const title = btn.dataset.title || 'this item';
      const confirmed = window.confirm(`Delete immediately for "${title}"?\n\nThis will try to remove from disk, Jellyfin, Sonarr/Radarr, qBittorrent and Seerr.`);
      if (!confirmed) return;
      btn.disabled = true;
      try {
        const res = await fetch('/api/delete-now', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key }),
        });
        const out = await res.json();
        if (!res.ok || !out.ok) throw new Error(out.error || 'Delete now failed');
        await load(true);
      } catch (err) {
        errorBox.innerHTML = `<div class="error">${esc(err.message)}</div>`;
      } finally {
        btn.disabled = false;
      }
    });
  });
}

async function load(force = false) {
  errorBox.innerHTML = '';
  const query = new URLSearchParams();
  if (force) query.set('force', '1');
  if (currentStatus) query.set('status', currentStatus);
  const res = await fetch(`/api/data?${query.toString()}`);
  if (res.status === 401) {
    setAuthUi(null);
    showLoginView();
    return;
  }
  const data = await res.json();
  if (!res.ok || !data.ok) throw new Error(data.error || 'Failed to load');

  currentItems = data.items || [];
  currentSummary = data.summary;
  formula1Enabled = !!((data.settings || {}).formula1_enabled);
  subtitle.textContent = 'Automatically delete watched and idle media from your Jellyfin library';
  rerender();
}

function getStatsRangeParams() {
  const preset = String(statsRangePreset.value || 'last30');
  const today = new Date();
  const fmt = (d) => d.toISOString().slice(0, 10);
  const shift = (days) => {
    const d = new Date(today);
    d.setDate(d.getDate() + days);
    return d;
  };
  let start = '';
  let end = '';
  let all = false;
  if (preset === 'last7') {
    start = fmt(shift(-7));
    end = fmt(today);
  } else if (preset === 'next7') {
    start = fmt(today);
    end = fmt(shift(7));
  } else if (preset === 'last30') {
    start = fmt(shift(-30));
    end = fmt(today);
  } else if (preset === 'next30') {
    start = fmt(today);
    end = fmt(shift(30));
  } else if (preset === 'last90') {
    start = fmt(shift(-90));
    end = fmt(today);
  } else if (preset === 'next90') {
    start = fmt(today);
    end = fmt(shift(90));
  } else if (preset === 'lastYear') {
    start = fmt(shift(-365));
    end = fmt(today);
  } else if (preset === 'nextYear') {
    start = fmt(today);
    end = fmt(shift(365));
  } else if (preset === 'all') {
    all = true;
  } else {
    start = normalizeDateInput(statsRangeStart.value);
    end = normalizeDateInput(statsRangeEnd.value);
  }
  if (!all) {
    if (start) statsRangeStart.value = start;
    if (end) statsRangeEnd.value = end;
  }
  return {
    preset,
    start,
    end,
    all,
  };
}

function normalizeDateInput(rawValue) {
  const raw = String(rawValue || '').trim();
  if (!raw) return '';
  const m = raw.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/);
  if (!m) return raw;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return raw;
  const dt = new Date(Date.UTC(y, mo - 1, d));
  if (dt.getUTCFullYear() !== y || (dt.getUTCMonth() + 1) !== mo || dt.getUTCDate() !== d) return raw;
  return `${String(y).padStart(4, '0')}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

async function loadStats(force = false) {
  const query = new URLSearchParams();
  const range = getStatsRangeParams();
  query.set('days', '30');
  if (range.start) query.set('start', range.start);
  if (range.end) query.set('end', range.end);
  if (range.all) query.set('all', '1');
  if (force) query.set('force', '1');
  const res = await fetch(`/api/stats?${query.toString()}`);
  if (res.status === 401) {
    setAuthUi(null);
    showLoginView();
    return;
  }
  const data = await res.json();
  if (!res.ok || !data.ok) throw new Error(data.error || 'Failed to load stats');
  currentStats = data;
  if (data.range && data.range.start && data.range.end) {
    statsRangeStart.value = data.range.start;
    statsRangeEnd.value = data.range.end;
  }
  statsRangeBaseline = JSON.stringify(getStatsRangeParams());
  updateStatsApplyState();
  renderStatsView(data);
}

function userCheckboxesSelected() {
  return [...document.querySelectorAll('.jf-user')].filter((el) => el.checked).map((el) => el.value);
}

function renderUsers(users, selected) {
  if (!users.length) {
    jfUsers.innerHTML = '<div class="hint">No Jellyfin users loaded yet.</div>';
    return;
  }
  const selectedSet = new Set(selected || []);
  jfUsers.innerHTML = users.map((name) => `
    <label class="user-chip">
      <input type="checkbox" class="jf-user" value="${esc(name)}" ${selectedSet.has(name) ? 'checked' : ''}>
      <span>${esc(name)}</span>
    </label>
  `).join('');
}

function librariesSelected() {
  return [...document.querySelectorAll('.jf-library')].filter((el) => el.checked).map((el) => el.value);
}

function renderLibraries(libraries, selected) {
  if (!libraries.length) {
    jfLibraries.innerHTML = '<div class="hint">No Jellyfin libraries loaded yet.</div>';
    return;
  }
  const selectedSet = new Set(selected || []);
  jfLibraries.innerHTML = libraries.map((lib) => `
    <label class="user-chip">
      <input type="checkbox" class="jf-library" value="${esc(lib.id)}" ${selectedSet.has(lib.id) ? 'checked' : ''}>
      <span>${esc(lib.name)}</span>
    </label>
  `).join('');
}

function formValue(id) {
  const el = document.getElementById(id);
  return String(el?.value || '').trim();
}

function fillSettingsForm(cfg) {
  const general = cfg.general || {};
  document.getElementById('jellyfinBaseUrl').value = cfg.jellyfin.base_url || '';
  document.getElementById('jellyfinApiKey').value = cfg.jellyfin.api_key || '';
  removeWatchedEnabled.checked = general.remove_watched_enabled !== false;
  removeWatchedDays.value = Number(general.remove_watched_days || 60);
  removeUnwatchedEnabled.checked = !!general.remove_unwatched_enabled;
  removeUnwatchedDays.value = Number(general.remove_unwatched_days || 365);
  dryRunEnabled.checked = general.dry_run !== false;
  document.getElementById('radarrBaseUrl').value = cfg.radarr.base_url || '';
  document.getElementById('radarrApiKey').value = cfg.radarr.api_key || '';
  document.getElementById('radarrTags').value = (cfg.radarr.tags_to_keep || []).join(', ');
  document.getElementById('radarrUnmonitor').checked = !!cfg.radarr.unmonitor_watched;
  document.getElementById('sonarrBaseUrl').value = cfg.sonarr.base_url || '';
  document.getElementById('sonarrApiKey').value = cfg.sonarr.api_key || '';
  document.getElementById('sonarrTags').value = (cfg.sonarr.tags_to_keep || []).join(', ');
  document.getElementById('sonarrUnmonitor').checked = !!cfg.sonarr.unmonitor_watched;
  document.getElementById('qbtBaseUrl').value = cfg.download_clients.qbittorrent.base_url || '';
  document.getElementById('qbtUsername').value = cfg.download_clients.qbittorrent.username || '';
  document.getElementById('qbtPassword').value = cfg.download_clients.qbittorrent.password || '';
  document.getElementById('delugeBaseUrl').value = cfg.download_clients.deluge.base_url || '';
  document.getElementById('delugePassword').value = cfg.download_clients.deluge.password || '';
  monitorAllUsers.checked = !!cfg.monitor_all_users;
  monitorAllLibraries.checked = cfg.monitor_all_libraries !== false;
  renderUsers(availableUsers, cfg.usernames || []);
  renderLibraries(availableLibraries, (cfg.jellyfin && cfg.jellyfin.library_ids) || []);
  toggleUsersDisabledState();
  toggleLibrariesDisabledState();
  toggleGeneralRetentionInputs();
}

async function fetchSettings() {
  const res = await fetch('/api/settings');
  if (res.status === 401) throw new Error('authentication required');
  const out = await res.json();
  if (!res.ok || !out.ok) throw new Error(out.error || 'Failed to load settings');
  return out.settings;
}

async function fetchJellyfinUsers() {
  const res = await fetch('/api/jellyfin-users');
  if (res.status === 401) throw new Error('authentication required');
  const out = await res.json();
  if (!res.ok || !out.ok) throw new Error(out.error || 'Failed to load Jellyfin users');
  return out.users || [];
}

async function fetchJellyfinLibraries() {
  const res = await fetch('/api/jellyfin-libraries');
  if (res.status === 401) throw new Error('authentication required');
  const out = await res.json();
  if (!res.ok || !out.ok) throw new Error(out.error || 'Failed to load Jellyfin libraries');
  return out.libraries || [];
}

function collectSettingsPayload() {
  const selectedUsers = userCheckboxesSelected();
  const usernames = selectedUsers;
  return {
    monitor_all_users: !!monitorAllUsers.checked,
    monitor_all_libraries: !!monitorAllLibraries.checked,
    usernames,
    general: {
      remove_watched_enabled: !!removeWatchedEnabled.checked,
      remove_watched_days: Math.max(Number(removeWatchedDays.value || 60), 1),
      remove_unwatched_enabled: !!removeUnwatchedEnabled.checked,
      remove_unwatched_days: Math.max(Number(removeUnwatchedDays.value || 365), 1),
      dry_run: !!dryRunEnabled.checked,
    },
    jellyfin: {
      base_url: formValue('jellyfinBaseUrl'),
      api_key: formValue('jellyfinApiKey'),
      library_ids: monitorAllLibraries.checked ? [] : librariesSelected(),
    },
    radarr: {
      base_url: formValue('radarrBaseUrl'),
      api_key: formValue('radarrApiKey'),
      tags_to_keep: splitCsv(formValue('radarrTags')),
      unmonitor_watched: document.getElementById('radarrUnmonitor').checked,
    },
    sonarr: {
      base_url: formValue('sonarrBaseUrl'),
      api_key: formValue('sonarrApiKey'),
      tags_to_keep: splitCsv(formValue('sonarrTags')),
      unmonitor_watched: document.getElementById('sonarrUnmonitor').checked,
    },
    download_clients: {
      qbittorrent: {
        base_url: formValue('qbtBaseUrl'),
        username: formValue('qbtUsername'),
        password: formValue('qbtPassword'),
      },
      deluge: {
        base_url: formValue('delugeBaseUrl'),
        password: formValue('delugePassword'),
      },
    },
  };
}

function setSaveState(state, message = '') {
  saveButtons.forEach((btn) => {
    btn.classList.remove('clean', 'dirty', 'saving', 'saved', 'error');
    btn.classList.add(state);
    if (state === 'clean') {
      btn.textContent = 'Saved ✓';
      btn.disabled = true;
      return;
    }
    if (state === 'dirty') {
      btn.textContent = 'Save Settings';
      btn.disabled = false;
      return;
    }
    if (state === 'saving') {
      btn.textContent = 'Saving...';
      btn.disabled = true;
      return;
    }
    if (state === 'saved') {
      btn.textContent = 'Saved ✓';
      btn.disabled = true;
      return;
    }
    if (state === 'error') {
      btn.textContent = 'Save Failed ✕';
      btn.disabled = false;
      btn.title = message || '';
    }
  });
}

function captureSettingsBaseline() {
  settingsBaseline = JSON.stringify(collectSettingsPayload());
  settingsDirty = false;
  setSaveState('clean');
}

function recalcDirtyState() {
  const next = JSON.stringify(collectSettingsPayload());
  settingsDirty = next !== settingsBaseline;
  setSaveState(settingsDirty ? 'dirty' : 'clean');
}

function updateConnTestButton(button, state, detail = '') {
  button.classList.remove('ok', 'fail');
  button.title = detail || '';
  if (state === 'ok') {
    button.classList.add('ok');
    button.textContent = '✓ Connected';
    return;
  }
  if (state === 'fail') {
    button.classList.add('fail');
    button.textContent = '✕ Failed';
    return;
  }
  button.textContent = 'Test Connection';
}

async function testConnection(service, button) {
  const settings = collectSettingsPayload();
  button.disabled = true;
  button.textContent = 'Testing...';
  try {
    const res = await fetch('/api/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ service, settings }),
    });
    const out = await res.json();
    if (!res.ok || !out.ok) throw new Error(out.error || 'Connection test failed');
    updateConnTestButton(button, out.connected ? 'ok' : 'fail', out.detail || '');
  } catch (err) {
    updateConnTestButton(button, 'fail', err.message);
  } finally {
    button.disabled = false;
  }
}

async function testConnectionInitial(service, button) {
  const settings = collectSettingsPayload();
  try {
    const res = await fetch('/api/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ service, settings }),
    });
    const out = await res.json();
    if (res.ok && out.ok && out.connected) {
      updateConnTestButton(button, 'ok', out.detail || '');
    } else {
      updateConnTestButton(button, 'idle');
    }
  } catch {
    updateConnTestButton(button, 'idle');
  }
}

async function loadSettingsView() {
  showSettingsMessage('');
  const [cfg, users, libraries] = await Promise.all([fetchSettings(), fetchJellyfinUsers(), fetchJellyfinLibraries()]);
  availableUsers = users;
  availableLibraries = libraries;
  fillSettingsForm(cfg);
  captureSettingsBaseline();
  connTestButtons.forEach((btn) => updateConnTestButton(btn, 'idle'));
  await Promise.all(connTestButtons.map((btn) => testConnectionInitial(btn.dataset.service || '', btn)));
}

async function authStatus() {
  const res = await fetch('/api/auth/status');
  const out = await res.json();
  if (!res.ok || !out.ok) return { authenticated: false };
  return out;
}

async function loginWithJellyfin(username, password, remember) {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, remember }),
  });
  const out = await res.json();
  if (!res.ok || !out.ok) throw new Error(out.error || 'login failed');
  return out.user;
}

async function logoutJellyfin() {
  await fetch('/api/auth/logout', { method: 'POST' });
}

filterButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    filterButtons.forEach((x) => x.classList.remove('active'));
    btn.classList.add('active');
    currentStatus = btn.dataset.status;
    load();
  });
});

navDashboardBtn.addEventListener('click', () => {
  if (!authUser) return;
  if (!confirmDiscardSettings()) return;
  setView('dashboard');
  load();
});

brandDashboardBtn.addEventListener('click', () => {
  if (!authUser) return;
  if (!confirmDiscardSettings()) return;
  setView('dashboard');
  load();
});

navStatsBtn.addEventListener('click', async () => {
  if (!authUser) return;
  if (!confirmDiscardSettings()) return;
  setView('stats');
  try {
    await loadStats(true);
  } catch (err) {
    errorBox.innerHTML = `<div class="error">${esc(err.message)}</div>`;
  }
});

navSettingsBtn.addEventListener('click', async () => {
  if (!authUser) return;
  setView('settings');
  try {
    await loadSettingsView();
  } catch (err) {
    showSettingsMessage(err.message, true);
  }
});

refreshUsersBtn.addEventListener('click', async () => {
  const original = refreshUsersBtn.textContent;
  refreshUsersBtn.disabled = true;
  refreshUsersBtn.textContent = 'Refreshing...';
  try {
    availableUsers = await fetchJellyfinUsers();
    availableLibraries = await fetchJellyfinLibraries();
    renderUsers(availableUsers, userCheckboxesSelected());
    renderLibraries(availableLibraries, librariesSelected());
    recalcDirtyState();
    refreshUsersBtn.textContent = 'Refreshed ✓';
  } catch (err) {
    showSettingsMessage(err.message, true);
    refreshUsersBtn.textContent = 'Refresh Failed ✕';
  } finally {
    setTimeout(() => {
      refreshUsersBtn.textContent = original;
      refreshUsersBtn.disabled = false;
    }, 1000);
  }
});

connTestButtons.forEach((btn) => {
  btn.addEventListener('click', async () => {
    await testConnection(btn.dataset.service || '', btn);
  });
});

monitorAllUsers.addEventListener('change', () => {
  toggleUsersDisabledState();
  recalcDirtyState();
});

monitorAllLibraries.addEventListener('change', () => {
  toggleLibrariesDisabledState();
  recalcDirtyState();
});

removeWatchedEnabled.addEventListener('change', () => {
  toggleGeneralRetentionInputs();
  recalcDirtyState();
});

removeUnwatchedEnabled.addEventListener('change', () => {
  toggleGeneralRetentionInputs();
  recalcDirtyState();
});

settingsForm.addEventListener('input', () => {
  recalcDirtyState();
});

settingsForm.addEventListener('change', () => {
  recalcDirtyState();
});

settingsForm.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const payload = collectSettingsPayload();
  if (!payload.monitor_all_users && !payload.usernames.length) {
    showSettingsMessage('Select at least one monitored Jellyfin user.', true);
    setSaveState('error', 'Select at least one monitored Jellyfin user.');
    return;
  }
  setSaveState('saving');
  showSettingsMessage('Saving settings...');
  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const out = await res.json();
    if (!res.ok || !out.ok) throw new Error(out.error || 'Failed to save settings');
    showSettingsMessage('Settings saved. Reloading dashboard data...');
    settingsBaseline = JSON.stringify(payload);
    settingsDirty = false;
    setSaveState('saved');
    await load(true);
  } catch (err) {
    showSettingsMessage(err.message, true);
    setSaveState('error', err.message);
  }
});

saveButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    if (btn.disabled) return;
    settingsForm.requestSubmit();
  });
});

refreshBtn.addEventListener('click', async () => {
  if (!authUser) return;
  const original = refreshBtn.textContent;
  refreshBtn.disabled = true;
  refreshBtn.textContent = 'Refreshing...';
  try {
    await load(true);
    refreshBtn.textContent = 'Refreshed ✓';
  } catch (err) {
    refreshBtn.textContent = 'Refresh Failed ✕';
    errorBox.innerHTML = `<div class="error">${esc(err.message)}</div>`;
  } finally {
    setTimeout(() => {
      refreshBtn.textContent = original;
      refreshBtn.disabled = false;
    }, 1000);
  }
});

signInNavBtn.addEventListener('click', () => {
  if (!confirmDiscardSettings()) return;
  showLoginView();
});

signOutBtn.addEventListener('click', async () => {
  if (!confirmDiscardSettings()) return;
  await logoutJellyfin();
  setAuthUi(null);
  showLoginView();
});

authUserTrigger.addEventListener('click', () => {
  authUserDropdown.classList.toggle('hidden');
});

document.addEventListener('click', (ev) => {
  if (!authUserBox.contains(ev.target)) authUserDropdown.classList.add('hidden');
});

loginForm.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const username = String(loginUsername.value || '').trim();
  const password = String(loginPassword.value || '');
  const remember = !!(loginRemember && loginRemember.checked);
  if (!username || !password) {
    loginMsg.textContent = 'Enter username and password.';
    loginMsg.style.color = 'var(--danger)';
    return;
  }
  loginSubmitBtn.disabled = true;
  loginSubmitBtn.textContent = 'Signing in...';
  loginMsg.textContent = '';
  try {
    const user = await loginWithJellyfin(username, password, remember);
    setAuthUi(user);
    loginPassword.value = '';
    setView('dashboard');
    await load(true);
    await loadStats(true);
  } catch (err) {
    loginMsg.textContent = err.message;
    loginMsg.style.color = 'var(--danger)';
  } finally {
    loginSubmitBtn.disabled = false;
    loginSubmitBtn.textContent = 'Sign In with Jellyfin';
  }
});

async function boot() {
  const status = await authStatus();
  if (status.authenticated) {
    setAuthUi(status.user || null);
    setView('dashboard');
    await load(true);
    await loadStats(true);
    return;
  }
  setAuthUi(null);
  showLoginView();
}

window.addEventListener('beforeunload', (ev) => {
  if (!hasPendingSettingsChanges()) return;
  ev.preventDefault();
  ev.returnValue = '';
});

function updateStatsApplyState() {
  const current = JSON.stringify(getStatsRangeParams());
  refreshStatsBtn.disabled = current === statsRangeBaseline;
  refreshStatsBtn.classList.toggle('ready', !refreshStatsBtn.disabled);
}

function syncRangeUiMode() {
  const custom = statsRangePreset.value === 'custom';
  customRangeWrap.classList.toggle('custom-active', custom);
}

refreshStatsBtn.addEventListener('click', async () => {
  if (!authUser) return;
  if (refreshStatsBtn.disabled) return;
  refreshStatsBtn.disabled = true;
  try {
    await loadStats(true);
  } catch (err) {
    errorBox.innerHTML = `<div class="error">${esc(err.message)}</div>`;
    updateStatsApplyState();
  }
});

statsRangePreset.addEventListener('change', async () => {
  syncRangeUiMode();
  getStatsRangeParams();
  if (statsRangePreset.value !== 'custom') {
    refreshStatsBtn.disabled = true;
    refreshStatsBtn.classList.remove('ready');
    try {
      await loadStats(true);
    } catch (err) {
      errorBox.innerHTML = `<div class="error">${esc(err.message)}</div>`;
      updateStatsApplyState();
    }
    return;
  }
  updateStatsApplyState();
});

[statsRangeStart, statsRangeEnd].forEach((el) => {
  el.addEventListener('change', () => {
    el.value = normalizeDateInput(el.value);
    if (statsRangePreset.value !== 'custom') statsRangePreset.value = 'custom';
    syncRangeUiMode();
    updateStatsApplyState();
  });
});

syncRangeUiMode();

boot().catch((err) => {
  errorBox.innerHTML = `<div class="error">${esc(err.message)}</div>`;
});
