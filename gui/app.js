const $ = (id) => document.getElementById(id);
const fields = {
  fast_start: $('fastStart'), cookie_relay: $('cookieRelay'),
  random_boost: $('randomBoost'), boost_index: $('boostIndex'),
  detect_relic: $('detectRelic'),
  hp_extension: $('hpExtension'), power_jelly_boost: $('powerJellyBoost'),
  double_xp: $('doubleXp'), auto_jump: $('autoJump'), auto_add_friend: $('autoAddFriend'),
};
const toggleDefaults = {
  fast_start: false, cookie_relay: false, random_boost: false, detect_relic: false,
  hp_extension: true, power_jelly_boost: true, double_xp: true, auto_jump: false, auto_add_friend: false,
};
const selectedKey = 'cookierun-gui-selected-device-v2';
const optionsKey = 'cookierun-gui-device-options-v2';
const migratedKey = 'cookierun-gui-options-migrated-v2';
const alertsKey = 'cookierun-gui-alert-history-v1';
const issuesKey = 'cookierun-gui-active-issues-v1';
const emptyLog = $('logList').firstElementChild.cloneNode(true);
let optionsByDevice;
try { optionsByDevice = JSON.parse(localStorage.getItem(optionsKey) || '{}'); }
catch { optionsByDevice = {}; }
let selectedId = localStorage.getItem(selectedKey);
let lastLogId = 0;
let eventCount = 0;
let startedAt = null;
let finishedAt = null;
let busy = false;
let polling = false;
let optionsLoaded = false;
let currentDevices = [];
let pendingRemovalId = null;
const deviceCardNodes = new Map();
let screenActive = false;
let screenDeviceId = null;
let screenGeneration = 0;
let screenTimer = null;
let screenRequest = null;
let overviewVisible = false;
let thumbnailBusy = false;
let thumbnailRequest = null;
const thumbnailLastAt = new Map();
const previousBotStatuses = new Map();
const intentionalStops = new Set();
let alertsInitialized = false;
let alertsDirty = false;
let alerts = [];
let activeIssues = {};
try {
  const savedAlerts = JSON.parse(localStorage.getItem(alertsKey) || '[]');
  if (Array.isArray(savedAlerts)) alerts = savedAlerts
    .filter((item) => item && typeof item.deviceId === 'string'
      && typeof item.message === 'string' && Number.isFinite(item.at))
    .slice(0, 40);
} catch { /* Ignore invalid browser history. */ }
try {
  const savedIssues = JSON.parse(localStorage.getItem(issuesKey) || '{}');
  if (savedIssues && typeof savedIssues === 'object' && !Array.isArray(savedIssues)) {
    activeIssues = Object.fromEntries(Object.entries(savedIssues)
      .filter(([, item]) => item && typeof item.deviceId === 'string'
        && typeof item.deviceName === 'string' && typeof item.label === 'string'));
  }
} catch { /* Ignore invalid browser issue state. */ }

function setBoostVisibility() {
  $('boostWrap').hidden = !fields.random_boost.checked;
}

function saveOptions() {
  if (!selectedId) return;
  optionsByDevice[selectedId] = {
    ...Object.fromEntries(Object.keys(toggleDefaults).map((key) => [key, fields[key].checked])),
    boost_index: Number(fields.boost_index.value),
  };
  localStorage.setItem(optionsKey, JSON.stringify(optionsByDevice));
}

function loadOptions(deviceId) {
  const saved = optionsByDevice[deviceId] || {};
  for (const [key, fallback] of Object.entries(toggleDefaults)) {
    fields[key].checked = saved[key] === undefined ? fallback : Boolean(saved[key]);
  }
  fields.boost_index.value = saved.boost_index || 1;
  setBoostVisibility();
}

function migrateOldOptions(state) {
  if (localStorage.getItem(migratedKey)) return;
  try {
    const old = JSON.parse(localStorage.getItem('cookierun-gui-settings-v1') || 'null');
    if (old) {
      const match = state.devices.find((device) => device.serial === `${old.ip}:${Number(old.port)}`);
      if (match && !optionsByDevice[match.id]) {
        optionsByDevice[match.id] = {
          fast_start: Boolean(old.fast_start), cookie_relay: Boolean(old.cookie_relay),
          random_boost: Boolean(old.random_boost), boost_index: Number(old.boost_index || 1),
          detect_relic: Boolean(old.detect_relic),
        };
        localStorage.setItem(optionsKey, JSON.stringify(optionsByDevice));
      }
    }
  } catch { /* Ignore invalid legacy browser settings. */ }
  localStorage.setItem(migratedKey, '1');
}

function showToast(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 5000);
}

async function fetchScreenBitmap(deviceId, signal) {
  const path = `/api/devices/screen?device=${encodeURIComponent(deviceId)}`;
  let response = await fetch(path, { cache: 'no-store', signal });
  if (response.status === 404 && location.port) {
    const sidecarUrl = `${location.protocol}//${location.hostname}:${Number(location.port) + 1}${path}`;
    response = await fetch(sidecarUrl, { cache: 'no-store', signal });
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || 'ไม่สามารถดึงภาพหน้าจอได้');
  }
  return createImageBitmap(await response.blob());
}

function drawThumbnail(deviceId, bitmap) {
  const nodes = deviceCardNodes.get(deviceId);
  if (!nodes) return;
  const canvas = nodes.thumbnail;
  canvas.width = 320;
  canvas.height = Math.max(1, Math.round(320 * bitmap.height / bitmap.width));
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  canvas.hidden = false;
  nodes.thumbnailPlaceholder.hidden = true;
  nodes.thumbnailTime.textContent = `ภาพล่าสุด ${new Date().toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
  thumbnailLastAt.set(deviceId, Date.now());
}

async function refreshThumbnails() {
  if (document.hidden || !overviewVisible || thumbnailBusy) return;
  const eligible = currentDevices
    .filter((device) => device.adb_state === 'device' && deviceCardNodes.has(device.id)
      && !(screenActive && screenDeviceId === device.id))
    .sort((a, b) => (thumbnailLastAt.get(a.id) || 0) - (thumbnailLastAt.get(b.id) || 0));
  const device = eligible.find((item) => Date.now() - (thumbnailLastAt.get(item.id) || 0) >= 5000);
  if (!device) return;
  thumbnailBusy = true;
  const controller = new AbortController();
  thumbnailRequest = { id: device.id, controller };
  try {
    const bitmap = await fetchScreenBitmap(device.id, controller.signal);
    try {
      if (!document.hidden && currentDevices.some((item) => item.id === device.id && item.adb_state === 'device')) {
        drawThumbnail(device.id, bitmap);
      }
    } finally { bitmap.close(); }
  } catch (error) {
    if (error.name !== 'AbortError') {
      const nodes = deviceCardNodes.get(device.id);
      if (nodes) nodes.thumbnailTime.textContent = 'ภาพไม่พร้อม';
      thumbnailLastAt.set(device.id, Date.now());
    }
  } finally {
    if (thumbnailRequest?.controller === controller) thumbnailRequest = null;
    thumbnailBusy = false;
  }
}

function cancelScreenCapture() {
  screenGeneration++;
  clearTimeout(screenTimer);
  screenTimer = null;
  if (screenRequest) screenRequest.abort();
  screenRequest = null;
}

function clearScreenFrame() {
  const canvas = $('screenImage');
  canvas.hidden = true;
  canvas.width = 0;
  canvas.height = 0;
  $('screenPlaceholder').hidden = false;
  $('screenIndicator').hidden = true;
}

function scheduleScreenFrame(delay = 0) {
  if (!screenActive || !screenDeviceId || document.hidden) return;
  const generation = screenGeneration;
  screenTimer = setTimeout(() => loadScreenFrame(generation), delay);
}

async function loadScreenFrame(generation) {
  if (!screenActive || generation !== screenGeneration || document.hidden) return;
  const startedAt = performance.now();
  const controller = new AbortController();
  screenRequest = controller;
  let succeeded = false;
  try {
    const bitmap = await fetchScreenBitmap(screenDeviceId, controller.signal);
    try {
      if (!screenActive || generation !== screenGeneration || document.hidden) return;
      const canvas = $('screenImage');
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      canvas.getContext('2d').drawImage(bitmap, 0, 0);
      canvas.hidden = false;
      $('screenPlaceholder').hidden = true;
      $('screenIndicator').hidden = false;
      $('screenStatus').textContent = `อัปเดตล่าสุด ${new Date().toLocaleTimeString('th-TH')}`;
      drawThumbnail(screenDeviceId, bitmap);
      succeeded = true;
    } finally { bitmap.close(); }
  } catch (error) {
    if (error.name !== 'AbortError' && screenActive && generation === screenGeneration) {
      $('screenIndicator').hidden = true;
      $('screenStatus').textContent = error.message;
      if ($('screenImage').hidden) $('screenMessage').textContent = 'ยังดึงภาพหน้าจอไม่ได้';
    }
  } finally {
    if (screenRequest === controller) screenRequest = null;
    if (screenActive && generation === screenGeneration) {
      scheduleScreenFrame(succeeded ? Math.max(100, 1000 - (performance.now() - startedAt)) : 2500);
    }
  }
}

function stopScreen() {
  screenActive = false;
  cancelScreenCapture();
  clearScreenFrame();
  $('screenToggle').textContent = '▶ ดูจอสด';
  $('screenToggle').classList.remove('active');
  $('screenStatus').textContent = 'ยังไม่ได้เปิดดูจอ';
}

function syncScreen(device) {
  const nextId = device?.id || null;
  if (screenActive && (!device || device.adb_state !== 'device')) stopScreen();
  $('screenDeviceName').textContent = device?.name || '—';
  if (screenDeviceId !== nextId) {
    cancelScreenCapture();
    clearScreenFrame();
    screenDeviceId = nextId;
    $('screenMessage').textContent = nextId ? 'กำลังรอภาพจากอุปกรณ์' : 'เลือกอุปกรณ์เพื่อดูจอสด';
    if (screenActive && nextId) {
      $('screenStatus').textContent = 'กำลังดึงภาพหน้าจอ…';
      scheduleScreenFrame();
    }
  }
  if (!nextId && screenActive) stopScreen();
  $('screenToggle').disabled = !nextId || (!screenActive && device.adb_state !== 'device');
  if (!screenActive && nextId && device.adb_state !== 'device') {
    $('screenStatus').textContent = 'เชื่อมต่อ ADB ก่อนเปิดดูจอ';
    $('screenMessage').textContent = 'อุปกรณ์ยังไม่เชื่อมต่อ ADB';
  } else if (!screenActive && nextId) {
    $('screenStatus').textContent = 'พร้อมเปิดดูจอ';
    $('screenMessage').textContent = 'กด “ดูจอสด” เพื่อเริ่ม';
  }
}

async function post(path, data = {}) {
  const response = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'เกิดข้อผิดพลาด');
  return body;
}

function addLog(entry) {
  const list = $('logList');
  if (list.querySelector('.empty-log')) list.replaceChildren();
  const line = document.createElement('div');
  line.className = 'log-entry';
  const time = document.createElement('span');
  time.className = 'log-time';
  const match = entry.text.match(/^\[(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)\]\s*/);
  time.textContent = match ? match[2] : new Date().toLocaleTimeString('en-GB', { hour12: false });
  const message = document.createElement('span');
  message.className = 'log-text';
  message.textContent = entry.text.replace(/^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\]\s*/, '');
  if (message.textContent.includes('Detected Stage:')) line.classList.add('event');
  if (message.textContent.includes('An error occurred:') || message.textContent.includes('Failed to connect')) line.classList.add('error');
  line.append(time, message);
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
  list.append(line);
  if (atBottom) list.scrollTop = list.scrollHeight;
  eventCount++;
  $('eventCount').textContent = `${eventCount} EVENTS`;
}

function resetLogs() {
  lastLogId = 0;
  eventCount = 0;
  $('eventCount').textContent = '0 EVENTS';
  $('logList').replaceChildren(emptyLog.cloneNode(true));
}

function deviceStateLabel(device) {
  if (device.adb_state === 'device') return ['เชื่อมต่อ ADB แล้ว', 'connected'];
  if (device.adb_state === 'offline') return ['ADB offline', 'offline'];
  if (device.adb_state === 'unauthorized') return ['รออนุญาต ADB', 'offline'];
  return ['ยังไม่เชื่อมต่อ', 'offline'];
}

function renderDevices(devices) {
  $('deviceCount').textContent = devices.length;
  $('deviceEmpty').hidden = devices.length > 0;
  const list = $('deviceList');
  const visible = new Set();
  for (const device of devices) {
    visible.add(device.id);
    let nodes = deviceCardNodes.get(device.id);
    if (!nodes) {
      const card = document.createElement('div');
      card.className = 'device-card';
      const select = document.createElement('button');
      select.type = 'button';
      select.className = 'device-select';
      const top = document.createElement('div');
      top.className = 'device-card-top';
      const icon = document.createElement('span');
      icon.className = 'device-card-icon';
      icon.textContent = '▣';
      const title = document.createElement('span');
      title.className = 'device-card-title';
      const name = document.createElement('strong');
      const serial = document.createElement('small');
      title.append(name, serial);
      top.append(icon, title);
      const preview = document.createElement('div');
      preview.className = 'device-thumb';
      const thumbnail = document.createElement('canvas');
      thumbnail.hidden = true;
      thumbnail.setAttribute('aria-hidden', 'true');
      const thumbnailPlaceholder = document.createElement('span');
      thumbnailPlaceholder.className = 'device-thumb-placeholder';
      thumbnailPlaceholder.textContent = 'กำลังรอภาพ';
      preview.append(thumbnail, thumbnailPlaceholder);
      const stageLine = document.createElement('div');
      stageLine.className = 'device-card-stage';
      const stage = document.createElement('strong');
      const thumbnailTime = document.createElement('small');
      thumbnailTime.textContent = 'ยังไม่มีภาพ';
      stageLine.append(stage, thumbnailTime);
      const bottom = document.createElement('div');
      bottom.className = 'device-card-bottom';
      const status = document.createElement('span');
      const dot = document.createElement('i');
      const statusText = document.createTextNode('');
      status.append(dot, statusText);
      const bot = document.createElement('span');
      bottom.append(status, bot);
      select.append(top, preview, stageLine, bottom);
      select.addEventListener('click', () => selectDevice(device.id));
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'device-card-remove';
      remove.textContent = '×';
      remove.addEventListener('click', () => openRemoveDialog(device.id));
      card.append(select, remove);
      nodes = { card, select, remove, name, serial, thumbnail, thumbnailPlaceholder,
        thumbnailTime, stage, status, statusText, bot };
      deviceCardNodes.set(device.id, nodes);
      list.append(card);
    }
    const { card, select, remove, name, serial, thumbnail, thumbnailPlaceholder,
      thumbnailTime, stage, status, statusText, bot } = nodes;
    card.className = `device-card${device.id === selectedId ? ' selected' : ''}`;
    select.setAttribute('aria-label', `เลือก ${device.name}, ${device.serial}, ${device.status}, ${device.stage || 'ยังไม่ทราบด่าน'}`);
    select.setAttribute('aria-pressed', String(device.id === selectedId));
    remove.setAttribute('aria-label', `ลบ ${device.name}, ${device.serial}`);
    remove.disabled = busy;
    name.textContent = device.name;
    serial.textContent = device.serial;
    stage.textContent = `ด่าน: ${device.stage ? device.stage.replaceAll('_', ' ') : '—'}`;
    if (device.adb_state !== 'device') {
      thumbnail.hidden = true;
      thumbnail.width = 0;
      thumbnail.height = 0;
      thumbnailPlaceholder.hidden = false;
      thumbnailPlaceholder.textContent = 'อุปกรณ์ยังไม่เชื่อมต่อ ADB';
      thumbnailTime.textContent = 'ไม่มีภาพสด';
      thumbnailLastAt.delete(device.id);
    } else if (thumbnail.hidden) {
      thumbnailPlaceholder.textContent = 'กำลังโหลดภาพย่อ…';
    }
    const [stateText, stateClass] = deviceStateLabel(device);
    status.className = `device-state ${stateClass}`;
    statusText.textContent = stateText;
    bot.className = `device-bot-state ${device.status}`;
    bot.textContent = device.status === 'running' ? 'BOT RUNNING' : device.status === 'stopping' ? 'STOPPING' : device.status === 'error' ? 'ERROR' : 'BOT IDLE';
  }
  for (const [id, nodes] of deviceCardNodes) {
    if (!visible.has(id)) {
      nodes.card.remove();
      deviceCardNodes.delete(id);
      thumbnailLastAt.delete(id);
    }
  }
}

function focusAlertDevice(deviceId) {
  const device = currentDevices.find((item) => item.id === deviceId);
  if (!device) {
    showToast('อุปกรณ์นี้ถูกลบออกจากรายการแล้ว');
    return;
  }
  selectDevice(deviceId);
  $('devices').scrollIntoView({ behavior: 'smooth', block: 'start' });
  location.hash = 'devices';
}

function renderAlerts() {
  const issues = Object.values(activeIssues);
  const count = issues.length;
  $('activeIssueCount').textContent = count;
  $('alertNavCount').textContent = count;
  $('alertNavCount').hidden = count === 0;
  document.title = count ? `(${count}) CookieRun Bot · Control Room` : 'CookieRun Bot · Control Room';
  const issueList = $('activeIssues');
  issueList.replaceChildren();
  for (const issue of issues) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = `issue-chip${issue.severity === 'critical' ? ' critical' : ''}`;
    const dot = document.createElement('i');
    const label = document.createElement('span');
    label.textContent = `${issue.deviceName} · ${issue.label}`;
    chip.append(dot, label);
    chip.addEventListener('click', () => focusAlertDevice(issue.deviceId));
    issueList.append(chip);
  }
  const list = $('alertList');
  list.replaceChildren();
  for (const alert of alerts.slice(0, 8)) {
    const item = document.createElement('div');
    item.className = `alert-entry${alert.severity === 'critical' ? ' critical' : ''}`;
    const symbol = document.createElement('span');
    symbol.className = 'alert-symbol';
    symbol.textContent = alert.severity === 'critical' ? '!' : '⌁';
    const copy = document.createElement('div');
    copy.className = 'alert-copy';
    const message = document.createElement('strong');
    message.textContent = alert.message;
    const time = document.createElement('small');
    time.textContent = new Date(alert.at).toLocaleString('th-TH');
    copy.append(message, time);
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'alert-open';
    open.textContent = 'ดูเครื่อง';
    open.addEventListener('click', () => focusAlertDevice(alert.deviceId));
    item.append(symbol, copy, open);
    list.append(item);
  }
  $('alertEmpty').hidden = alerts.length > 0 || count > 0;
  $('clearAlertsButton').disabled = alerts.length === 0;
}

function addAlert(device, code, message, severity = 'warning') {
  alerts.unshift({ id: `${Date.now()}-${Math.random()}`, deviceId: device.id,
    deviceName: device.name, code, message, severity, at: Date.now() });
  alerts = alerts.slice(0, 40);
  localStorage.setItem(alertsKey, JSON.stringify(alerts));
  alertsDirty = true;
  if (alertsInitialized || code === 'anti_bot') showToast(message);
}

function observeIssues(devices) {
  const nextIssues = {};
  const knownIds = new Set(devices.map((device) => device.id));
  for (const device of devices) {
    const issue = (code, label, message, severity = 'warning') => {
      const key = `${device.id}:${code}`;
      nextIssues[key] = { deviceId: device.id, deviceName: device.name, code, label, severity };
      if (!activeIssues[key]) addAlert(device, code, message, severity);
    };
    if (device.adb_state !== 'device') {
      const label = device.adb_state === 'unauthorized' ? 'รออนุญาต ADB'
        : device.adb_state === 'offline' ? 'ADB offline' : 'ADB ไม่เชื่อมต่อ';
      issue('adb', label, `${device.name}: ${label}`);
    }
    if (device.status === 'error') {
      issue('bot_error', 'Bot ผิดพลาด', `${device.name}: Bot เกิดข้อผิดพลาด`, 'critical');
    }
    if (device.status === 'running' && device.stage === 'ANTI_BOT') {
      issue('anti_bot', 'พบ ANTI_BOT', `${device.name}: พบ ANTI_BOT โปรดตรวจหน้าจอ`, 'critical');
    }
    const previous = previousBotStatuses.get(device.id);
    if ((previous === 'running' || previous === 'stopping') && device.status === 'idle') {
      if (!intentionalStops.has(device.id)) addAlert(device, 'bot_stopped', `${device.name}: Bot หยุดทำงาน`);
      intentionalStops.delete(device.id);
    }
    if (device.status === 'error') intentionalStops.delete(device.id);
    previousBotStatuses.set(device.id, device.status);
  }
  for (const id of previousBotStatuses.keys()) {
    if (!knownIds.has(id)) previousBotStatuses.delete(id);
  }
  const issuesChanged = JSON.stringify(nextIssues) !== JSON.stringify(activeIssues);
  if (issuesChanged) {
    activeIssues = nextIssues;
    localStorage.setItem(issuesKey, JSON.stringify(activeIssues));
  }
  if (issuesChanged || alertsDirty || !alertsInitialized) renderAlerts();
  alertsDirty = false;
  alertsInitialized = true;
}

function render(state) {
  const device = state.selected;
  currentDevices = state.devices;
  migrateOldOptions(state);
  observeIssues(state.devices);
  if (!device) {
    selectedId = null;
    localStorage.removeItem(selectedKey);
    optionsLoaded = false;
    renderDevices([]);
    syncScreen(null);
    resetLogs();
    $('startButton').disabled = true;
    $('stopButton').disabled = true;
    $('connectButton').disabled = true;
    $('removeButton').disabled = true;
    Object.values(fields).forEach((field) => { field.disabled = true; });
    $('deviceLabel').textContent = '—';
    $('selectedDeviceName').textContent = 'ยังไม่มีอุปกรณ์';
    $('selectedDeviceSerial').textContent = 'กดเพิ่มอุปกรณ์เพื่อเริ่มใช้งาน';
    $('selectedAdbStatus').textContent = '';
    $('stageLabel').textContent = '—';
    $('statusLabel').textContent = 'ยังไม่มีอุปกรณ์';
    $('statusDetail').lastChild.textContent = ' เพิ่มอุปกรณ์เพื่อเริ่ม';
    $('liveBadge').lastChild.textContent = ' STANDBY';
    $('liveBadge').className = 'live-badge';
    startedAt = null;
    finishedAt = null;
    updateRuntime();
    return;
  }
  if (selectedId !== device.id || !optionsLoaded) {
    selectedId = device.id;
    localStorage.setItem(selectedKey, selectedId);
    loadOptions(selectedId);
    resetLogs();
    optionsLoaded = true;
  }
  renderDevices(state.devices);
  syncScreen(device);
  const active = device.status === 'running' || device.status === 'stopping';
  $('startButton').disabled = active || busy;
  $('stopButton').disabled = !active || device.status === 'stopping' || busy;
  Object.values(fields).forEach((field) => { field.disabled = active || busy; });
  $('connectButton').disabled = busy || active || device.adb_state === 'device';
  $('removeButton').disabled = busy;
  $('deviceLabel').textContent = device.serial;
  $('selectedDeviceName').textContent = device.name;
  $('selectedDeviceSerial').textContent = device.serial;
  const [adbText, adbClass] = deviceStateLabel(device);
  $('selectedAdbStatus').textContent = adbText;
  $('selectedAdbStatus').className = `selected-adb-status ${adbClass}`;
  $('stageLabel').textContent = device.stage ? device.stage.replaceAll('_', ' ') : '—';
  startedAt = device.started_at;
  finishedAt = device.finished_at;
  const labels = {
    idle: ['พร้อมใช้งาน', 'รอเริ่มการทำงาน', 'STANDBY'],
    running: ['กำลังทำงาน', 'Bot กำลังรันบนอุปกรณ์นี้', 'LIVE'],
    stopping: ['กำลังหยุด', 'กำลังปิด process', 'STOPPING'],
    error: ['เกิดข้อผิดพลาด', 'ดูรายละเอียดใน Activity log', 'ERROR'],
  };
  const [title, detail, badgeText] = labels[device.status];
  $('statusLabel').textContent = title;
  $('statusDetail').lastChild.textContent = ` ${detail}`;
  const badge = $('liveBadge');
  badge.lastChild.textContent = ` ${badgeText}`;
  badge.className = `live-badge ${device.status === 'running' ? 'active' : device.status === 'error' ? 'error' : ''}`;
  for (const entry of device.logs) addLog(entry);
  lastLogId = device.latest_log_id;
  updateRuntime();
}

function updateRuntime() {
  const seconds = startedAt ? Math.max(0, Math.floor((finishedAt || Date.now() / 1000) - startedAt)) : 0;
  const h = String(Math.floor(seconds / 3600)).padStart(2, '0');
  const m = String(Math.floor(seconds % 3600 / 60)).padStart(2, '0');
  const s = String(seconds % 60).padStart(2, '0');
  $('runtimeLabel').textContent = `${h}:${m}:${s}`;
}

async function poll() {
  if (polling) return;
  polling = true;
  const requestedId = selectedId;
  try {
    const params = new URLSearchParams({ after: String(lastLogId) });
    if (requestedId) params.set('device', requestedId);
    const response = await fetch(`/api/state?${params}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('ไม่สามารถอ่านสถานะ Bot ได้');
    const state = await response.json();
    if (selectedId === requestedId) render(state);
  } catch (error) {
    $('statusLabel').textContent = 'ขาดการเชื่อมต่อ';
    $('statusDetail').lastChild.textContent = ' GUI server ไม่ตอบสนอง';
  } finally { polling = false; }
}

function selectDevice(deviceId) {
  if (busy || deviceId === selectedId) return;
  saveOptions();
  selectedId = deviceId;
  localStorage.setItem(selectedKey, selectedId);
  loadOptions(deviceId);
  resetLogs();
  syncScreen(currentDevices.find((device) => device.id === deviceId));
  poll();
}

$('screenToggle').addEventListener('click', () => {
  if (screenActive) {
    stopScreen();
    syncScreen(currentDevices.find((device) => device.id === selectedId));
    return;
  }
  const device = currentDevices.find((item) => item.id === selectedId);
  if (!device || device.adb_state !== 'device') return;
  screenActive = true;
  $('screenToggle').textContent = '■ หยุดดูจอ';
  $('screenToggle').classList.add('active');
  $('screenMessage').textContent = 'กำลังดึงภาพหน้าจอ…';
  $('screenStatus').textContent = 'กำลังดึงภาพหน้าจอ…';
  scheduleScreenFrame();
});

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    if (screenActive) {
      cancelScreenCapture();
      $('screenIndicator').hidden = true;
      $('screenStatus').textContent = 'พักภาพระหว่างซ่อนแท็บ';
    }
    thumbnailRequest?.controller.abort();
  } else if (screenActive) {
    $('screenStatus').textContent = 'กำลังดึงภาพหน้าจอ…';
    scheduleScreenFrame();
  }
  if (!document.hidden) refreshThumbnails();
});
window.addEventListener('beforeunload', () => {
  cancelScreenCapture();
  thumbnailRequest?.controller.abort();
});

function openRemoveDialog(deviceId) {
  if (busy) return;
  const device = currentDevices.find((item) => item.id === deviceId);
  if (!device) return;
  pendingRemovalId = deviceId;
  const running = device.status === 'running' || device.status === 'stopping';
  $('removeDialogText').textContent = `ลบ “${device.name}” (${device.serial}) ออกจากรายการ${running ? ' และหยุด Bot ของเครื่องนี้ก่อนลบ' : ''}`;
  $('removeDialog').hidden = false;
  $('cancelRemoveButton').focus();
}

function closeRemoveDialog() {
  $('removeDialog').hidden = true;
  pendingRemovalId = null;
}

$('startButton').addEventListener('click', async () => {
  if (!selectedId) return;
  busy = true;
  saveOptions();
  try {
    const state = await post('/api/start', { device_id: selectedId, ...optionsByDevice[selectedId] });
    resetLogs();
    render(state);
  } catch (error) { showToast(error.message); }
  finally { busy = false; await poll(); }
});

$('stopButton').addEventListener('click', async () => {
  if (!selectedId) return;
  const deviceId = selectedId;
  busy = true;
  intentionalStops.add(deviceId);
  try { render(await post('/api/stop', { device_id: deviceId })); }
  catch (error) { intentionalStops.delete(deviceId); showToast(error.message); }
  finally { busy = false; await poll(); }
});

$('connectButton').addEventListener('click', async () => {
  if (!selectedId) return;
  busy = true;
  try { render(await post('/api/devices/connect', { device_id: selectedId })); }
  catch (error) { showToast(error.message); }
  finally { busy = false; await poll(); }
});

$('showAddDevice').addEventListener('click', () => {
  $('addDeviceForm').hidden = false;
  $('newDeviceIp').focus();
});
$('cancelAddDevice').addEventListener('click', () => { $('addDeviceForm').hidden = true; });
$('addDeviceForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  busy = true;
  try {
    const state = await post('/api/devices/add', {
      name: $('newDeviceName').value.trim(),
      ip: $('newDeviceIp').value.trim(),
      port: $('newDevicePort').value,
    });
    $('addDeviceForm').reset();
    $('addDeviceForm').hidden = true;
    render(state);
  } catch (error) { showToast(error.message); }
  finally { busy = false; await poll(); }
});

$('removeButton').addEventListener('click', () => openRemoveDialog(selectedId));
$('cancelRemoveButton').addEventListener('click', closeRemoveDialog);
$('removeDialog').addEventListener('click', (event) => {
  if (event.target === $('removeDialog') && !busy) closeRemoveDialog();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !$('removeDialog').hidden && !busy) closeRemoveDialog();
});
$('confirmRemoveButton').addEventListener('click', async () => {
  if (!pendingRemovalId || busy) return;
  busy = true;
  $('confirmRemoveButton').disabled = true;
  try {
    const previous = pendingRemovalId;
    const state = await post('/api/devices/remove', { device_id: previous, selected_id: selectedId });
    delete optionsByDevice[previous];
    intentionalStops.delete(previous);
    if (thumbnailRequest?.id === previous) thumbnailRequest.controller.abort();
    localStorage.setItem(optionsKey, JSON.stringify(optionsByDevice));
    closeRemoveDialog();
    if (previous === selectedId) render(state);
  } catch (error) { showToast(error.message); }
  finally {
    busy = false;
    $('confirmRemoveButton').disabled = false;
    await poll();
  }
});

$('clearAlertsButton').addEventListener('click', () => {
  alerts = [];
  localStorage.setItem(alertsKey, '[]');
  renderAlerts();
});

const overviewObserver = new IntersectionObserver((entries) => {
  overviewVisible = entries.some((entry) => entry.isIntersecting);
  if (overviewVisible) refreshThumbnails();
  else thumbnailRequest?.controller.abort();
}, { rootMargin: '120px' });
overviewObserver.observe($('devices'));

fields.random_boost.addEventListener('change', setBoostVisibility);
for (const field of Object.values(fields)) field.addEventListener('change', saveOptions);
setInterval(() => {
  $('clock').textContent = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
  updateRuntime();
}, 1000);
setInterval(poll, 1100);
setInterval(refreshThumbnails, 1000);
renderAlerts();
poll();
