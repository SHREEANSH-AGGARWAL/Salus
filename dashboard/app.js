/* ═══════════════════════════════════════════════════════════════════════════
   SALUS — Delhi Command dashboard
   ───────────────────────────────────────────────────────────────────────────
   All state comes from the FastAPI backend at /api/v1/*. Nothing is faked:
   the sample scenario is written through the real consensus API like any
   other change.
   ═══════════════════════════════════════════════════════════════════════════ */

'use strict';

const state = {
  cluster: null,
  peers: null,
  health: null,
  resources: [],
  zones: [],
  pending: [],
  audit: [],
  ws: null,
  commander: null,
  activeTab: 'ops',
  railView: 'units',
  unitFilter: 'all',
  zoneFilter: 'all',
  search: '',
  selection: null,        // { type:'resource'|'zone', id }
  isPartitioned: false,
  pickTarget: null,       // 'unit' | 'zone'
  pipelineRunning: false,
};

let radar = null;

const API = '/api/v1';

/* ═══════════════════════════════════════════════════════════════════════════
   API + small helpers
   ═══════════════════════════════════════════════════════════════════════════ */

async function api(path, opts = {}) {
  const config = { headers: { 'Content-Type': 'application/json' }, ...opts };
  if (config.body && typeof config.body === 'object') config.body = JSON.stringify(config.body);
  const res = await fetch(API + path, config);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 409 && data.detail?.leader_id) {
      showToast(`This command post is not the leader right now — try ${data.detail.leader_id}.`, 'warning');
    }
    throw { status: res.status, detail: data.detail ?? data };
  }
  return data;
}

/** Turn an API error into something a human can act on. */
function errText(e) {
  const d = e?.detail;
  if (typeof d === 'string') return d;
  if (d?.message) return d.message;
  if (Array.isArray(d)) return d.map(x => x.msg || JSON.stringify(x)).join('; ');
  if (d) return JSON.stringify(d);
  return 'Unknown error';
}

const $ = (id) => document.getElementById(id);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function esc(str) {
  if (str == null) return '';
  return String(str).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const num = (n) => (n ?? 0).toLocaleString('en-IN');

function showToast(msg, type = 'info', duration = 4500) {
  const el = document.createElement('div');
  el.className = `toast toast--${type}`;
  el.textContent = msg;
  $('toast-container').appendChild(el);
  setTimeout(() => {
    el.classList.add('leaving');
    el.addEventListener('animationend', () => el.remove());
  }, duration);
}

function openModal(id) { $(id).classList.add('active'); }
function closeModal(id) { $(id).classList.remove('active'); }
window.closeModal = closeModal;

/* ═══════════════════════════════════════════════════════════════════════════
   Reference tables
   ═══════════════════════════════════════════════════════════════════════════ */

const PRIORITY_LABELS = {
  1: 'P1 · Critical', 2: 'P2 · High', 3: 'P3 · Moderate',
  4: 'P4 · Low', 5: 'P5 · Minimal',
};

const ACCESS_LABELS = {
  open: 'Roads clear', restricted: 'Some routes blocked', air_only: 'Air access only',
  water_only: 'Boat access only', cut_off: 'No known route in', unknown: 'Access unknown',
};

const DAMAGE_LABELS = {
  catastrophic: 'Catastrophic damage', severe: 'Severe damage', moderate: 'Moderate damage',
  light: 'Light damage', none: 'No damage', unknown: 'Damage not assessed',
};

const ACTION_LABELS = {
  ai_damage_assessment: 'AI assessed the damage',
  ai_resource_match: 'AI matched a unit',
  ai_route_plan: 'AI planned a route',
  ai_protocol_lookup: 'AI checked the protocol',
  ai_decision: 'AI recommended a dispatch',
  ai_fallback: 'Fell back to rule-based planning',
  ic_confirm: 'Commander approved',
  ic_reject: 'Commander rejected',
  ic_override: 'Commander sent a different unit',
  ic_timeout: 'Expired with no decision',
  resource_dispatched: 'Unit dispatched',
  resource_arrived: 'Unit arrived on scene',
  resource_returned: 'Unit returned to base',
  resource_resupply: 'Unit resupplied',
  partition_detected: 'Lost contact with the network',
  partition_healed: 'Network contact restored',
  system_error: 'System error',
};

const TYPE_LABELS = {
  ambulance: 'Ambulance', ambulance_als: 'Ambulance (advanced life support)',
  fire_engine: 'Fire engine', hazmat_team: 'HAZMAT team',
  helicopter_transport: 'Transport helicopter', helicopter_medical: 'Medical helicopter',
  helicopter_heavy_lift: 'Heavy-lift helicopter', sar_team_urban: 'Urban rescue team',
  sar_team_water: 'Water rescue team', sar_team_mountain: 'Rough-terrain rescue team',
  evacuation_bus: 'Evacuation bus', supply_truck: 'Supply truck', water_tanker: 'Water tanker',
  generator: 'Generator', field_hospital: 'Field hospital', k9_unit: 'K9 unit',
  drone_team: 'Drone team', engineering_unit: 'Engineering unit',
};

/** Sensible capability defaults so the add-unit form fills itself in. */
const TYPE_DEFAULTS = {
  ambulance:            { caps: ['medical'], personnel: 3, range: 80, fuel: 8 },
  ambulance_als:        { caps: ['medical'], personnel: 4, range: 100, fuel: 8 },
  fire_engine:          { caps: ['firefighting'], personnel: 8, range: 120, fuel: 9 },
  hazmat_team:          { caps: ['hazmat'], personnel: 6, range: 90, fuel: 6 },
  helicopter_transport: { caps: ['air', 'sar'], personnel: 4, range: 450, fuel: 5 },
  helicopter_medical:   { caps: ['air', 'medical'], personnel: 4, range: 400, fuel: 5 },
  helicopter_heavy_lift:{ caps: ['air'], personnel: 5, range: 400, fuel: 4 },
  sar_team_urban:       { caps: ['sar', 'thermal', 'listening'], personnel: 16, range: 300, fuel: 12 },
  sar_team_water:       { caps: ['sar', 'water-rescue'], personnel: 8, range: 60, fuel: 6 },
  sar_team_mountain:    { caps: ['sar'], personnel: 10, range: 200, fuel: 10 },
  evacuation_bus:       { caps: [], personnel: 2, range: 150, fuel: 8 },
  supply_truck:         { caps: [], personnel: 2, range: 200, fuel: 10 },
  water_tanker:         { caps: [], personnel: 2, range: 100, fuel: 8 },
  generator:            { caps: [], personnel: 2, range: 60, fuel: 24 },
  field_hospital:       { caps: ['medical'], personnel: 25, range: 50, fuel: 24 },
  k9_unit:              { caps: ['sar'], personnel: 4, range: 80, fuel: 8 },
  drone_team:           { caps: ['air', 'thermal'], personnel: 3, range: 35, fuel: 4 },
  engineering_unit:     { caps: [], personnel: 10, range: 120, fuel: 10 },
};

const PIPELINE_EXAMPLES = {
  collapse: 'Multi-storey commercial building has collapsed next to the metro interchange. Around 40 people are believed trapped under slab debris. Access on the east side is blocked by fallen scaffolding and there is a suspected gas leak.',
  flood:    'The Yamuna has breached the embankment overnight. Low-lying settlements are under 1.5 m of water, roads are impassable and roughly 300 families are stranded on rooftops awaiting evacuation.',
  fire:     'Major fire spreading through a scrapyard and adjoining chemical godowns. Thick toxic smoke drifting over nearby housing. Several workers unaccounted for and the water supply on site has failed.',
  chemical: 'Chlorine cylinder rupture at an industrial storage unit. Visible gas cloud drifting north-east over a residential colony. Dozens reporting breathing difficulty; the area needs decontamination and evacuation upwind.',
};

/* ═══════════════════════════════════════════════════════════════════════════
   ONBOARDING
   ═══════════════════════════════════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {
  initTooltips();
  initStartup();
  initHelp();
});

function initStartup() {
  const preset = $('input-agency-id-preset');
  const custom = $('input-agency-id');
  preset.addEventListener('change', () => {
    const isCustom = preset.value === '__custom';
    custom.classList.toggle('hidden', !isCustom);
    if (isCustom) custom.focus();
  });

  $('btn-continue-step1').addEventListener('click', onIdentityContinue);
  $('input-commander-id').addEventListener('keydown', e => { if (e.key === 'Enter') onIdentityContinue(); });
  $('btn-load-demo').addEventListener('click', () => loadSampleScenario({ thenLaunch: true }));
  $('btn-start-empty').addEventListener('click', () => launchDashboard());
}

function currentAgency() {
  const preset = $('input-agency-id-preset');
  return preset.value === '__custom' ? $('input-agency-id').value.trim() : preset.value;
}

async function onIdentityContinue() {
  const id = $('input-commander-id').value.trim();
  const agency = currentAgency();
  if (!id) { showToast('Enter a commander ID so your decisions can be attributed.', 'error'); return; }
  if (!agency) { showToast('Enter your agency name.', 'error'); return; }
  state.commander = { id, agency_id: agency };

  const [rData, zData] = await Promise.all([
    api('/resources').catch(() => ({ resources: [] })),
    api('/zones').catch(() => ({ zones: [] })),
  ]);

  if ((rData.resources || []).length || (zData.zones || []).length) {
    // The backend already holds state from an earlier session — go straight in.
    state.resources = rData.resources || [];
    state.zones = zData.zones || [];
    state.isPartitioned = rData.partitioned || false;
    launchDashboard();
  } else {
    $('startup-step-1').classList.add('hidden');
    $('startup-step-2').classList.remove('hidden');
  }
}

/* ── Sample scenario ──────────────────────────────────────────────────────
   Written through POST /resources and POST /zones — the same path a real
   registration takes, so everything lands in the replicated log.           */

const SAMPLE_UNITS = [
  { name: 'CATS ALS Ambulance 102', callsign: 'CATS-102', resource_type: 'ambulance_als', owning_agency_id: 'CATS Ambulance Service',
    home_base: { latitude: 28.5672, longitude: 77.2100 },
    capabilities: { can_perform_medical: true, has_medical_personnel: true, personnel_count: 4, max_range_km: 100, fuel_hours_remaining: 8 } },
  { name: 'CATS Ambulance 118', callsign: 'CATS-118', resource_type: 'ambulance', owning_agency_id: 'CATS Ambulance Service',
    home_base: { latitude: 28.6395, longitude: 77.2400 },
    capabilities: { can_perform_medical: true, has_medical_personnel: true, personnel_count: 3, max_range_km: 80, fuel_hours_remaining: 7 } },
  { name: 'DFS Heavy Fire Tender 01', callsign: 'DFS-ENG-01', resource_type: 'fire_engine', owning_agency_id: 'Delhi Fire Service (DFS)',
    home_base: { latitude: 28.6304, longitude: 77.2200 },
    capabilities: { can_perform_firefighting: true, personnel_count: 8, max_range_km: 120, fuel_hours_remaining: 9 } },
  { name: 'DFS Fire Tender 07 (Rohini)', callsign: 'DFS-ENG-07', resource_type: 'fire_engine', owning_agency_id: 'Delhi Fire Service (DFS)',
    home_base: { latitude: 28.7360, longitude: 77.1100 },
    capabilities: { can_perform_firefighting: true, personnel_count: 7, max_range_km: 120, fuel_hours_remaining: 8 } },
  { name: 'DFS HAZMAT Decontamination Unit', callsign: 'DFS-HAZ-02', resource_type: 'hazmat_team', owning_agency_id: 'Delhi Fire Service (DFS)',
    home_base: { latitude: 28.6320, longitude: 77.1350 },
    capabilities: { can_perform_hazmat: true, personnel_count: 6, max_range_km: 90, fuel_hours_remaining: 6 } },
  { name: 'NDRF 8th Bn USAR Team Alpha', callsign: 'NDRF-SAR-01', resource_type: 'sar_team_urban', owning_agency_id: 'NDRF Delhi-NCR',
    home_base: { latitude: 28.6480, longitude: 77.3050 },
    capabilities: { can_perform_sar: true, has_listening_devices: true, has_thermal_imaging: true, can_access_rough_terrain: true, personnel_count: 16, max_range_km: 300, fuel_hours_remaining: 12 } },
  { name: 'NDRF USAR Team Bravo', callsign: 'NDRF-SAR-02', resource_type: 'sar_team_urban', owning_agency_id: 'NDRF Delhi-NCR',
    home_base: { latitude: 28.5921, longitude: 77.0460 },
    capabilities: { can_perform_sar: true, has_thermal_imaging: true, can_access_rough_terrain: true, personnel_count: 14, max_range_km: 300, fuel_hours_remaining: 11 } },
  { name: 'IAF Mi-17 Rescue Chopper', callsign: 'IAF-PALAM-01', resource_type: 'helicopter_transport', owning_agency_id: 'Western Air Command',
    home_base: { latitude: 28.5820, longitude: 77.1250 },
    capabilities: { can_access_air: true, can_perform_sar: true, passenger_capacity: 18, personnel_count: 4, max_range_km: 450, fuel_hours_remaining: 5 } },
  { name: 'Yamuna Flood Rescue Boat Section', callsign: 'DDMA-BOAT-01', resource_type: 'sar_team_water', owning_agency_id: 'DDMA / Flood Control',
    home_base: { latitude: 28.6680, longitude: 77.2340 },
    capabilities: { can_perform_water_rescue: true, can_access_water: true, can_perform_sar: true, personnel_count: 8, max_range_km: 60, fuel_hours_remaining: 6 } },
  { name: 'Delhi Police K9 Tracker Unit', callsign: 'DP-K9-01', resource_type: 'k9_unit', owning_agency_id: 'Delhi Police',
    home_base: { latitude: 28.5980, longitude: 77.1920 },
    capabilities: { can_perform_sar: true, personnel_count: 4, max_range_km: 80, fuel_hours_remaining: 8 } },
  { name: 'Delhi Police Recon Drone Team', callsign: 'DP-DRN-01', resource_type: 'drone_team', owning_agency_id: 'Delhi Police',
    home_base: { latitude: 28.6250, longitude: 77.2150 },
    capabilities: { can_access_air: true, has_thermal_imaging: true, personnel_count: 3, max_range_km: 35, fuel_hours_remaining: 4 } },
  { name: 'PWD Debris Clearing Unit', callsign: 'PWD-ENG-03', resource_type: 'engineering_unit', owning_agency_id: 'PWD Delhi',
    home_base: { latitude: 28.6700, longitude: 77.2900 },
    capabilities: { can_clear_debris: true, can_access_rough_terrain: true, personnel_count: 10, max_range_km: 120, fuel_hours_remaining: 10 } },
];

const SAMPLE_ZONES = [
  { name: 'Connaught Place & Rajiv Chowk', zone_code: 'DEL-CP', priority: 1, damage_level: 'catastrophic', access_status: 'restricted',
    address_description: 'Inner and Outer Circle, Rajiv Chowk metro interchange, Barakhamba corridor',
    boundary: { center: { latitude: 28.6315, longitude: 77.2167 }, radius_km: 2.0 },
    needs: { needs_sar: true, needs_medical: true, needs_firefighting: true, estimated_trapped: 55, estimated_injured: 180, estimated_displaced: 3500, estimated_population: 25000 } },
  { name: 'Chandni Chowk Old City', zone_code: 'DEL-CCK', priority: 1, damage_level: 'severe', access_status: 'restricted',
    address_description: 'Dense market lanes between Red Fort and Fatehpuri Masjid — narrow access, heavy footfall',
    boundary: { center: { latitude: 28.6562, longitude: 77.2301 }, radius_km: 1.4 },
    needs: { needs_sar: true, needs_medical: true, needs_firefighting: true, needs_engineering: true, estimated_trapped: 30, estimated_injured: 140, estimated_displaced: 2200, estimated_population: 18000 } },
  { name: 'Yamuna Floodplain (Kashmere Gate)', zone_code: 'DEL-YMN', priority: 2, damage_level: 'severe', access_status: 'water_only',
    address_description: 'Old Iron Bridge to ITO barrage — low-lying riverside settlements',
    boundary: { center: { latitude: 28.6650, longitude: 77.2380 }, radius_km: 2.8 },
    needs: { needs_sar: true, needs_evacuation: true, needs_water: true, needs_shelter: true, estimated_trapped: 25, estimated_injured: 70, estimated_displaced: 1500, estimated_population: 8000 } },
  { name: 'Mayapuri–Kirti Nagar Industrial', zone_code: 'DEL-MYP', priority: 2, damage_level: 'moderate', access_status: 'open',
    address_description: 'Mayapuri Phase 1 & 2 scrapyards and chemical storage',
    boundary: { center: { latitude: 28.6380, longitude: 77.1320 }, radius_km: 2.2 },
    needs: { needs_hazmat: true, needs_firefighting: true, needs_engineering: true, estimated_injured: 40, estimated_displaced: 450, estimated_population: 6000 } },
  { name: 'Rohini Sector 18 Residential', zone_code: 'DEL-ROH', priority: 3, damage_level: 'moderate', access_status: 'open',
    address_description: 'Mid-rise housing blocks with reported structural cracking after the tremor',
    boundary: { center: { latitude: 28.7360, longitude: 77.1100 }, radius_km: 2.0 },
    needs: { needs_engineering: true, needs_shelter: true, needs_power: true, estimated_displaced: 900, estimated_population: 14000 } },
  { name: 'Lajpat Nagar & South Extension', zone_code: 'DEL-LJP', priority: 4, damage_level: 'light', access_status: 'open',
    address_description: 'Central Market Lajpat Nagar II and the Ring Road South Extension corridor',
    boundary: { center: { latitude: 28.5680, longitude: 77.2430 }, radius_km: 2.2 },
    needs: { needs_shelter: true, needs_food: true, needs_water: true, estimated_displaced: 1800, estimated_population: 32000 } },
];

async function loadSampleScenario({ thenLaunch = false } = {}) {
  const progress = $('startup-progress');
  const log = $('demo-progress-log');
  const inStartup = thenLaunch;

  if (inStartup) {
    $('btn-load-demo').disabled = true;
    $('btn-start-empty').disabled = true;
    progress.classList.remove('hidden');
    log.innerHTML = '';
  } else {
    showToast('Loading the Delhi sample scenario…', 'info');
  }

  const addLog = (msg, cls = '') => {
    if (!inStartup) return;
    const span = document.createElement('span');
    span.className = `log-entry ${cls}`;
    span.textContent = msg;
    log.appendChild(span);
    log.scrollTop = log.scrollHeight;
  };

  let ok = 0, failed = 0;

  for (const r of SAMPLE_UNITS) {
    try {
      const res = await api('/resources', { method: 'POST', body: { resource: r } });
      addLog(`✓ ${r.name} — recorded as change #${res.log_index}`, 'success');
      ok++;
    } catch (e) {
      addLog(`✗ ${r.name} — ${errText(e)}`, 'error');
      failed++;
    }
  }

  for (const z of SAMPLE_ZONES) {
    try {
      const res = await api('/zones', { method: 'POST', body: { zone: z } });
      addLog(`✓ Zone ${z.name} — recorded as change #${res.log_index}`, 'success');
      ok++;
    } catch (e) {
      addLog(`✗ Zone ${z.name} — ${errText(e)}`, 'error');
      failed++;
    }
  }

  addLog(`\nDone. ${ok} entries agreed by the network${failed ? `, ${failed} failed` : ''}.`, 'info');

  await Promise.all([fetchResources(), fetchZones()]);

  if (thenLaunch) {
    setTimeout(() => launchDashboard(), 900);
  } else {
    showToast(`Sample scenario loaded — ${SAMPLE_UNITS.length} units, ${SAMPLE_ZONES.length} zones.`, 'success');
    radar?.fitData();
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   LAUNCH
   ═══════════════════════════════════════════════════════════════════════════ */

function launchDashboard() {
  $('startup-overlay').classList.add('hidden');
  $('app-shell').classList.add('active');

  $('hdr-commander').textContent = `${state.commander.id} · ${state.commander.agency_id}`;

  initTabs();
  initRail();
  initRadar();
  initForms();
  initPipeline();
  initHistory();
  initKeyboard();
  initHeaderActions();

  fetchCluster(); fetchPeers(); fetchHealth();
  fetchPending(); fetchAudit();

  // Frame the map around whatever is actually on the board, once it arrives.
  Promise.all([fetchResources(), fetchZones()]).then(() => {
    if (state.resources.length || state.zones.length) radar.fitData(false);
  });

  setInterval(() => { fetchCluster(); fetchPeers(); fetchHealth(); }, 3000);
  setInterval(() => { if (state.pending.length) renderPending(); }, 1000);

  connectWebSocket();
  renderAll();
}

function renderAll() {
  renderHeader();
  renderRailLists();
  renderDetailRail();
  renderPending();
  renderNetwork();
  renderGuidance();
  radar?.setData(state.resources, state.zones);
  updateMapEmpty();
}

function initHeaderActions() {
  $('btn-header-demo').addEventListener('click', () => loadSampleScenario());
  $('btn-header-help').addEventListener('click', () => $('help-overlay').classList.add('active'));
  $('btn-empty-demo').addEventListener('click', () => loadSampleScenario());
}

function initHelp() {
  $('help-close').addEventListener('click', () => $('help-overlay').classList.remove('active'));
  $('help-overlay').addEventListener('click', (e) => {
    if (e.target === $('help-overlay')) $('help-overlay').classList.remove('active');
  });
}

/* ═══════════════════════════════════════════════════════════════════════════
   TABS + KEYBOARD
   ═══════════════════════════════════════════════════════════════════════════ */

function switchTab(tab) {
  state.activeTab = tab;
  $$('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $$('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `tab-${tab}`));
  if (tab === 'ops') requestAnimationFrame(() => radar?.resize());
  if (tab === 'history') fetchAudit();
}

function initTabs() {
  $$('.tab-btn').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
}

function initKeyboard() {
  document.addEventListener('keydown', (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
    if (e.key === 'Escape') {
      if ($('help-overlay').classList.contains('active')) return $('help-overlay').classList.remove('active');
      const openM = document.querySelector('.modal-backdrop.active');
      if (openM) return closeModal(openM.id);
      if (state.pickTarget) return cancelPick();
      if (state.selection) return selectEntity(null);
      return;
    }
    if (typing) return;

    switch (e.key) {
      case '1': switchTab('ops'); break;
      case '2': switchTab('approvals'); break;
      case '3': switchTab('network'); break;
      case '4': switchTab('history'); break;
      case '/': e.preventDefault(); switchTab('ops'); $('rail-search').focus(); break;
      case '?': $('help-overlay').classList.add('active'); break;
      case 'p': case 'P': openPipelineModal(); break;
      case 'm': case 'M': openManualModal(); break;
      case 'f': case 'F': radar?.fitData(); break;
      case 'r': case 'R': radar?.fitDelhi(); break;
      case '+': case '=': radar?.zoomBy(1.4); break;
      case '-': case '_': radar?.zoomBy(1 / 1.4); break;
    }
  });
}

/* ═══════════════════════════════════════════════════════════════════════════
   DATA FETCHERS
   ═══════════════════════════════════════════════════════════════════════════ */

async function fetchCluster() {
  try {
    state.cluster = await api('/cluster/status');
    state.isPartitioned = !!state.cluster.is_partitioned;
    renderHeader(); renderNetwork(); renderDegraded();
  } catch (_) { updateWSDependentHealth(); }
}

async function fetchPeers() {
  try { state.peers = await api('/cluster/peers'); renderNetwork(); } catch (_) {}
}

async function fetchHealth() {
  try { state.health = await api('/cluster/health'); renderNetwork(); } catch (_) {}
}

async function fetchResources() {
  try {
    const data = await api('/resources');
    state.resources = data.resources || [];
    state.isPartitioned = data.partitioned || false;
    radar?.setData(state.resources, state.zones);
    renderRailLists(); renderDetailRail(); renderGuidance(); renderDegraded();
    renderNetwork(); updateMapEmpty();
  } catch (_) {}
}

async function fetchZones() {
  try {
    const data = await api('/zones');
    state.zones = data.zones || [];
    radar?.setData(state.resources, state.zones);
    renderRailLists(); renderDetailRail(); renderGuidance();
    renderNetwork(); updateMapEmpty();
  } catch (_) {}
}

async function fetchPending() {
  try {
    const data = await api('/dispatch/pending');
    state.pending = data.pending || [];
    renderPending(); renderGuidance(); renderDetailRail();
  } catch (_) {}
}

async function fetchAudit() {
  try {
    const action = $('audit-filter-action')?.value || '';
    const resource = $('audit-filter-resource')?.value.trim() || '';
    const zone = $('audit-filter-zone')?.value.trim() || '';
    let params = '?limit=150';
    if (action) params += `&action=${encodeURIComponent(action)}`;
    if (resource) params += `&resource_id=${encodeURIComponent(resource)}`;
    if (zone) params += `&zone_id=${encodeURIComponent(zone)}`;
    const data = await api('/audit' + params);
    state.audit = data.entries || [];
    renderAudit();
  } catch (_) {}
}

/* ═══════════════════════════════════════════════════════════════════════════
   HEADER + GUIDANCE
   ═══════════════════════════════════════════════════════════════════════════ */

function renderHeader() {
  const c = state.cluster;
  if (!c) return;
  const role = (c.state || '—').toString();
  $('hdr-node').textContent = `${(c.node_id || '—')} · ${role === 'leader' ? 'leading' : role}`;
  $('hdr-commit').textContent = num(c.commit_index ?? 0);
  $('hdr-term').textContent = c.current_term ?? '—';

  const dot = $('hdr-state-dot');
  dot.className = 'dot ' + (state.isPartitioned ? 'dot--red'
    : role === 'leader' ? 'dot--green' : role === 'candidate' ? 'dot--amber' : 'dot--blue');
}

function renderDegraded() {
  $('degraded-banner').classList.toggle('active', state.isPartitioned);
}

function renderGuidance() {
  const bar = $('guidance-bar');
  const icon = $('guidance-icon');
  const text = $('guidance-text');
  const action = $('guidance-action');

  const set = (tone, glyph, msg, label, fn) => {
    bar.className = 'guidance-bar guidance-bar--' + tone;
    icon.textContent = glyph;
    text.innerHTML = msg;
    if (label) {
      action.textContent = label;
      action.classList.remove('hidden');
      action.onclick = fn;
    } else {
      action.classList.add('hidden');
      action.onclick = null;
    }
  };

  if (state.isPartitioned) {
    return set('danger', '⚠',
      'This post is cut off from the network. <strong>Do not act on unit status</strong> until contact is restored.',
      'Check the network', () => switchTab('network'));
  }

  if (!state.resources.length && !state.zones.length) {
    return set('info', '◆',
      'Nothing is on the map yet. Load the Delhi sample scenario to see how this works.',
      'Load sample data', () => loadSampleScenario());
  }

  if (state.pending.length) {
    const n = state.pending.length;
    return set('action', '▶',
      `<strong>${n} dispatch ${n === 1 ? 'recommendation is' : 'recommendations are'} waiting for you.</strong> Nothing moves until you decide.`,
      'Review now', () => switchTab('approvals'));
  }

  const unserved = state.zones.filter(z => z.priority <= 2 && !(z.assigned_resource_ids || []).length);
  if (unserved.length) {
    const z = unserved[0];
    return set('warn', '!',
      `<strong>${esc(z.name)}</strong> is ${PRIORITY_LABELS[z.priority].split(' · ')[1].toLowerCase()} priority with no units sent yet.`,
      'Plan a dispatch', () => openPipelineModal(z.id));
  }

  if (!state.zones.length) {
    return set('info', '◆',
      'You have units but no disaster zones. Add a zone to start planning dispatches.',
      'Add a zone', () => { switchTab('ops'); setRailView('zones'); openZoneModal(); });
  }

  const enRoute = state.resources.filter(r => r.status === 'dispatched').length;
  set('ok', '✓',
    enRoute
      ? `All urgent zones have units assigned. <strong>${enRoute} ${enRoute === 1 ? 'unit is' : 'units are'} en route.</strong>`
      : 'All urgent zones have units assigned. Nothing needs your attention right now.',
    'Plan a dispatch', () => openPipelineModal());
}

/* ═══════════════════════════════════════════════════════════════════════════
   LEFT RAIL — unit & zone lists
   ═══════════════════════════════════════════════════════════════════════════ */

function initRail() {
  $$('#rail-switch .seg-btn').forEach(b =>
    b.addEventListener('click', () => setRailView(b.dataset.view)));

  $('rail-search').addEventListener('input', (e) => {
    state.search = e.target.value.trim().toLowerCase();
    $('rail-search-clear').classList.toggle('hidden', !state.search);
    renderRailLists();
  });
  $('rail-search-clear').addEventListener('click', () => {
    $('rail-search').value = ''; state.search = '';
    $('rail-search-clear').classList.add('hidden');
    renderRailLists();
  });

  $('unit-filters').addEventListener('click', (e) => {
    const btn = e.target.closest('.fchip'); if (!btn) return;
    state.unitFilter = btn.dataset.filter;
    $$('#unit-filters .fchip').forEach(b => b.classList.toggle('active', b === btn));
    renderRailLists();
  });
  $('zone-filters').addEventListener('click', (e) => {
    const btn = e.target.closest('.fchip'); if (!btn) return;
    state.zoneFilter = btn.dataset.filter;
    $$('#zone-filters .fchip').forEach(b => b.classList.toggle('active', b === btn));
    renderRailLists();
  });

  $('btn-add-unit').addEventListener('click', openUnitModal);
  $('btn-add-zone').addEventListener('click', openZoneModal);
}

function setRailView(view) {
  state.railView = view;
  $$('#rail-switch .seg-btn').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $('unit-list').classList.toggle('hidden', view !== 'units');
  $('zone-list').classList.toggle('hidden', view !== 'zones');
  $('unit-filters').classList.toggle('hidden', view !== 'units');
  $('zone-filters').classList.toggle('hidden', view !== 'zones');
  $('btn-add-unit').classList.toggle('hidden', view !== 'units');
  $('btn-add-zone').classList.toggle('hidden', view !== 'zones');
  $('rail-search').placeholder = view === 'units'
    ? 'Search by name, callsign, agency…' : 'Search zones by name or code…';
  renderRailLists();
}

function matchesSearch(hay) {
  return !state.search || hay.toLowerCase().includes(state.search);
}

function renderRailLists() {
  $('count-units').textContent = state.resources.length;
  $('count-zones').textContent = state.zones.length;
  renderUnitList();
  renderZoneList();
}

function renderUnitList() {
  const list = $('unit-list');
  let items = state.resources;

  if (state.unitFilter !== 'all') items = items.filter(r => r.status === state.unitFilter);
  items = items.filter(r => matchesSearch(`${r.name} ${r.callsign} ${r.owning_agency_id} ${r.resource_type}`));

  // Ready first, then everything else, alphabetically inside each group.
  const rank = { available: 0, dispatched: 1, on_scene: 2, returning: 3, needs_resupply: 4, resupplying: 5, maintenance: 6 };
  items = [...items].sort((a, b) =>
    (rank[a.status] ?? 9) - (rank[b.status] ?? 9) || a.name.localeCompare(b.name));

  if (!items.length) {
    list.innerHTML = `<div class="rail-empty">${state.resources.length
      ? 'No units match that filter.' : 'No units yet. Add one below, or load the sample data.'}</div>`;
    return;
  }

  list.innerHTML = items.map(r => {
    const key = r.is_uncertain ? 'uncertain' : r.status;
    const selected = state.selection?.type === 'resource' && state.selection.id === r.id;
    const zone = r.assigned_zone_id ? state.zones.find(z => z.id === r.assigned_zone_id) : null;
    const where = r.home_base ? describeLocation(r.home_base.latitude, r.home_base.longitude) : '';
    return `
      <button class="card ${selected ? 'is-selected' : ''}" data-type="resource" data-id="${esc(r.id)}">
        <span class="card-stripe" style="--c:${STATUS_COLORS[key]}"></span>
        <span class="card-main">
          <span class="card-row">
            <span class="card-title">${TYPE_GLYPHS[r.resource_type] || '📦'} ${esc(r.name)}</span>
            <span class="pill" style="--c:${STATUS_COLORS[key]}">${STATUS_LABELS[key] || key}</span>
          </span>
          <span class="card-meta">
            <code>${esc(r.callsign)}</code> · ${esc(TYPE_LABELS[r.resource_type] || r.resource_type)}
          </span>
          <span class="card-meta card-meta--dim">${esc(r.owning_agency_id)}${where ? ` · ${esc(where)}` : ''}</span>
          ${zone ? `<span class="card-flag" style="--c:${STATUS_COLORS[r.status]}">→ ${esc(zone.name)}</span>` : ''}
        </span>
      </button>`;
  }).join('');

  bindCardClicks(list);
}

function renderZoneList() {
  const list = $('zone-list');
  let items = state.zones;

  if (state.zoneFilter === 'critical') items = items.filter(z => z.priority <= 2);
  if (state.zoneFilter === 'unserved') items = items.filter(z => !(z.assigned_resource_ids || []).length);
  items = items.filter(z => matchesSearch(`${z.name} ${z.zone_code} ${z.address_description || ''}`));
  items = [...items].sort((a, b) => (a.priority || 9) - (b.priority || 9) || a.name.localeCompare(b.name));

  if (!items.length) {
    list.innerHTML = `<div class="rail-empty">${state.zones.length
      ? 'No zones match that filter.' : 'No zones yet. Add one below, or load the sample data.'}</div>`;
    return;
  }

  list.innerHTML = items.map(z => {
    const selected = state.selection?.type === 'zone' && state.selection.id === z.id;
    const color = PRIORITY_COLORS[z.priority] || PRIORITY_COLORS[3];
    const n = z.needs || {};
    const assigned = (z.assigned_resource_ids || []).length;
    const stats = [
      n.estimated_trapped ? `${num(n.estimated_trapped)} trapped` : '',
      n.estimated_injured ? `${num(n.estimated_injured)} injured` : '',
      n.estimated_displaced ? `${num(n.estimated_displaced)} displaced` : '',
    ].filter(Boolean).join(' · ');

    return `
      <button class="card ${selected ? 'is-selected' : ''}" data-type="zone" data-id="${esc(z.id)}">
        <span class="card-stripe" style="--c:${color}"></span>
        <span class="card-main">
          <span class="card-row">
            <span class="card-title">${esc(z.name)}</span>
            <span class="pill" style="--c:${color}">${PRIORITY_LABELS[z.priority] || 'P?'}</span>
          </span>
          <span class="card-meta"><code>${esc(z.zone_code)}</code> · ${esc(DAMAGE_LABELS[z.damage_level] || z.damage_level)}</span>
          <span class="card-meta card-meta--dim">${esc(ACCESS_LABELS[z.access_status] || '')}${stats ? ` · ${stats}` : ''}</span>
          ${assigned
            ? `<span class="card-flag" style="--c:#34d399">${assigned} unit${assigned === 1 ? '' : 's'} assigned</span>`
            : `<span class="card-flag" style="--c:${color}">No units sent yet</span>`}
        </span>
      </button>`;
  }).join('');

  bindCardClicks(list);
}

function bindCardClicks(list) {
  $$('.card', list).forEach(card => {
    card.addEventListener('click', () => {
      selectEntity({ type: card.dataset.type, id: card.dataset.id }, true);
    });
  });
}

/* ═══════════════════════════════════════════════════════════════════════════
   SELECTION + RIGHT RAIL
   ═══════════════════════════════════════════════════════════════════════════ */

function selectEntity(sel, flyToIt = false) {
  state.selection = sel;
  radar?.setSelection(sel);
  renderRailLists();
  renderDetailRail();

  if (sel && flyToIt) {
    const target = sel.type === 'resource'
      ? state.resources.find(r => r.id === sel.id)?.home_base
      : (() => { const c = state.zones.find(z => z.id === sel.id)?.boundary?.center;
                 return c && { latitude: c.latitude, longitude: c.longitude }; })();
    if (target) {
      const z = sel.type === 'zone' ? Math.max(radar.pxPerKm, 22) : Math.max(radar.pxPerKm, 30);
      radar.flyTo(target.latitude, target.longitude, z);
    }
  }
}

function renderDetailRail() {
  const summary = $('detail-summary');
  const entity = $('detail-entity');

  if (!state.selection) {
    summary.classList.remove('hidden');
    entity.classList.add('hidden');
    summary.innerHTML = summaryHTML();
    bindSummaryActions(summary);
    return;
  }

  summary.classList.add('hidden');
  entity.classList.remove('hidden');
  entity.innerHTML = state.selection.type === 'resource'
    ? unitDetailHTML(state.resources.find(r => r.id === state.selection.id))
    : zoneDetailHTML(state.zones.find(z => z.id === state.selection.id));

  entity.querySelector('[data-act="back"]')?.addEventListener('click', () => selectEntity(null));
  entity.querySelector('[data-act="plan"]')?.addEventListener('click', (e) =>
    openPipelineModal(e.currentTarget.dataset.zone));
  entity.querySelector('[data-act="manual"]')?.addEventListener('click', (e) =>
    openManualModal(e.currentTarget.dataset.zone));
  entity.querySelector('[data-act="send-unit"]')?.addEventListener('click', (e) =>
    openManualModal(null, e.currentTarget.dataset.unit));
  entity.querySelector('[data-act="center"]')?.addEventListener('click', () =>
    selectEntity(state.selection, true));
}

function summaryHTML() {
  const ready = state.resources.filter(r => r.status === 'available' && !r.is_uncertain).length;
  const enRoute = state.resources.filter(r => r.status === 'dispatched').length;
  const onScene = state.resources.filter(r => r.status === 'on_scene').length;
  const urgent = state.zones.filter(z => z.priority <= 2);
  const unserved = urgent.filter(z => !(z.assigned_resource_ids || []).length);
  const people = state.zones.reduce((a, z) => a + (z.needs?.estimated_trapped || 0), 0);

  const urgentList = state.zones
    .filter(z => z.priority <= 3)
    .sort((a, b) => (a.priority || 9) - (b.priority || 9))
    .slice(0, 4)
    .map(z => {
      const color = PRIORITY_COLORS[z.priority];
      const assigned = (z.assigned_resource_ids || []).length;
      return `
        <button class="mini-row" data-zone="${esc(z.id)}">
          <i style="--c:${color}"></i>
          <span class="mini-row__name">${esc(z.name)}</span>
          <span class="mini-row__state" style="--c:${assigned ? '#34d399' : color}">
            ${assigned ? `${assigned} sent` : 'none sent'}
          </span>
        </button>`;
    }).join('');

  return `
    <div class="rail-section">
      <h3 class="rail-h">Right now</h3>
      <div class="stat-grid">
        <div class="stat"><b style="--c:#34d399">${ready}</b><span>units ready</span></div>
        <div class="stat"><b style="--c:#38bdf8">${enRoute}</b><span>en route</span></div>
        <div class="stat"><b style="--c:#a78bfa">${onScene}</b><span>on scene</span></div>
        <div class="stat"><b style="--c:${unserved.length ? '#ff8a3d' : '#8193ab'}">${unserved.length}</b><span>urgent zones<br>with nobody sent</span></div>
      </div>
      ${people ? `<p class="rail-note">An estimated <strong>${num(people)} people</strong> are trapped across all reported zones.</p>` : ''}
    </div>

    ${state.pending.length ? `
      <div class="rail-section rail-section--alert">
        <h3 class="rail-h">Waiting on you</h3>
        <p class="rail-note">${state.pending.length} dispatch ${state.pending.length === 1 ? 'recommendation needs' : 'recommendations need'} a decision.</p>
        <button class="btn btn-primary btn-block btn-sm" data-act="go-approvals">Review ${state.pending.length === 1 ? 'it' : 'them'}</button>
      </div>` : ''}

    ${urgentList ? `
      <div class="rail-section">
        <h3 class="rail-h">Zones by priority</h3>
        <div class="mini-list">${urgentList}</div>
      </div>` : ''}

    <div class="rail-section">
      <h3 class="rail-h">Actions</h3>
      <button class="btn btn-primary btn-block btn-sm" data-act="plan-any">▶ Plan a dispatch</button>
      <button class="btn btn-secondary btn-block btn-sm" data-act="fit">Fit map to everything</button>
      <p class="rail-hint">Click anything on the map to inspect it. Press <kbd>?</kbd> for a plain-language guide.</p>
    </div>`;
}

function bindSummaryActions(root) {
  root.querySelector('[data-act="go-approvals"]')?.addEventListener('click', () => switchTab('approvals'));
  root.querySelector('[data-act="plan-any"]')?.addEventListener('click', () => openPipelineModal());
  root.querySelector('[data-act="fit"]')?.addEventListener('click', () => radar?.fitData());
  $$('.mini-row', root).forEach(b =>
    b.addEventListener('click', () => selectEntity({ type: 'zone', id: b.dataset.zone }, true)));
}

function unitDetailHTML(r) {
  if (!r) return '<div class="rail-section"><p class="rail-note">That unit is no longer listed.</p></div>';
  const key = r.is_uncertain ? 'uncertain' : r.status;
  const caps = r.capabilities || {};
  const capList = [
    ['Search & rescue', caps.can_perform_sar], ['Medical', caps.can_perform_medical],
    ['Firefighting', caps.can_perform_firefighting], ['HAZMAT', caps.can_perform_hazmat],
    ['Water rescue', caps.can_perform_water_rescue], ['Air access', caps.can_access_air],
    ['Thermal imaging', caps.has_thermal_imaging], ['Life detection', caps.has_listening_devices],
    ['Debris clearing', caps.can_clear_debris], ['Rough terrain', caps.can_access_rough_terrain],
  ].filter(([, v]) => v).map(([k]) => `<span class="tag">${k}</span>`).join('');

  const zone = r.assigned_zone_id ? state.zones.find(z => z.id === r.assigned_zone_id) : null;
  const dist = zone && r.home_base && zone.boundary?.center
    ? kmBetween(r.home_base.latitude, r.home_base.longitude,
                zone.boundary.center.latitude, zone.boundary.center.longitude) : null;

  return `
    <div class="detail-head">
      <button class="back-btn" data-act="back">← Back</button>
      <span class="pill" style="--c:${STATUS_COLORS[key]}">${STATUS_LABELS[key] || key}</span>
    </div>
    <div class="rail-section">
      <h3 class="detail-title">${TYPE_GLYPHS[r.resource_type] || '📦'} ${esc(r.name)}</h3>
      <p class="detail-sub"><code>${esc(r.callsign)}</code> · ${esc(TYPE_LABELS[r.resource_type] || r.resource_type)}</p>
      <p class="detail-sub">Operated by ${esc(r.owning_agency_id)}</p>
      ${r.is_uncertain ? `<p class="warn-note">Status cannot be verified while this post is cut off from the network. Do not rely on it.</p>` : ''}
    </div>

    <div class="rail-section">
      <h4 class="rail-h">Where it is based</h4>
      <p class="detail-sub">${r.home_base ? esc(describeLocation(r.home_base.latitude, r.home_base.longitude)) : '—'}</p>
      <p class="detail-coord">${r.home_base ? `${r.home_base.latitude.toFixed(4)}°N · ${r.home_base.longitude.toFixed(4)}°E` : ''}</p>
      <button class="btn btn-secondary btn-sm btn-block" data-act="center">Centre the map on it</button>
      ${r.status === 'available' && !r.is_uncertain
        ? `<button class="btn btn-primary btn-sm btn-block" data-act="send-unit" data-unit="${esc(r.id)}">Send this unit somewhere</button>`
        : ''}
    </div>

    ${zone ? `
      <div class="rail-section rail-section--alert">
        <h4 class="rail-h">Current assignment</h4>
        <p class="detail-sub"><strong>${esc(zone.name)}</strong></p>
        ${dist != null ? `<p class="detail-sub">${dist.toFixed(1)} km from base</p>` : ''}
        ${r.dispatched_by ? `<p class="detail-sub">Approved by ${esc(r.dispatched_by)}</p>` : ''}
      </div>` : ''}

    ${capList ? `<div class="rail-section"><h4 class="rail-h">What it can do</h4><div class="tag-row">${capList}</div></div>` : ''}

    <div class="rail-section">
      <h4 class="rail-h">Numbers</h4>
      <div class="kv-row"><span class="kv-key">Crew</span><span class="kv-val">${caps.personnel_count ?? 0}</span></div>
      <div class="kv-row"><span class="kv-key">Range</span><span class="kv-val">${caps.max_range_km ?? 0} km</span></div>
      <div class="kv-row"><span class="kv-key">Endurance left</span><span class="kv-val">${caps.fuel_hours_remaining ?? 0} h</span></div>
      <div class="kv-row"><span class="kv-key">Shift used</span><span class="kv-val">${r.hours_deployed ?? 0} of ${r.max_shift_hours ?? 12} h</span></div>
      <div class="kv-row"><span class="kv-key" data-tip="Position of this unit's last change in the permanent record.">Record #</span><span class="kv-val">${r.raft_log_index ?? '—'}</span></div>
      <div class="kv-row"><span class="kv-key">Unit ID</span><span class="kv-val kv-val--id">${esc(r.id)}</span></div>
    </div>`;
}

function zoneDetailHTML(z) {
  if (!z) return '<div class="rail-section"><p class="rail-note">That zone is no longer listed.</p></div>';
  const color = PRIORITY_COLORS[z.priority] || PRIORITY_COLORS[3];
  const n = z.needs || {};
  const needs = [
    ['Search & rescue', n.needs_sar], ['Medical', n.needs_medical], ['Evacuation', n.needs_evacuation],
    ['Firefighting', n.needs_firefighting], ['HAZMAT', n.needs_hazmat], ['Drinking water', n.needs_water],
    ['Food', n.needs_food], ['Shelter', n.needs_shelter], ['Power', n.needs_power],
    ['Debris clearing', n.needs_engineering], ['Communications', n.needs_communication],
  ].filter(([, v]) => v).map(([k]) => `<span class="tag">${k}</span>`).join('');

  const assigned = state.resources.filter(r => r.assigned_zone_id === z.id);
  const conf = Math.round((z.assessment_confidence ?? 0) * 100);

  return `
    <div class="detail-head">
      <button class="back-btn" data-act="back">← Back</button>
      <span class="pill" style="--c:${color}">${PRIORITY_LABELS[z.priority] || 'P?'}</span>
    </div>
    <div class="rail-section">
      <h3 class="detail-title">${esc(z.name)}</h3>
      <p class="detail-sub"><code>${esc(z.zone_code)}</code> · ${esc(DAMAGE_LABELS[z.damage_level] || '')}</p>
      ${z.address_description ? `<p class="detail-sub">${esc(z.address_description)}</p>` : ''}
      <p class="detail-sub">${esc(ACCESS_LABELS[z.access_status] || '')} · ${(z.boundary?.radius_km ?? 0)} km radius</p>
      <p class="detail-coord">${z.boundary ? `${z.boundary.center.latitude.toFixed(4)}°N · ${z.boundary.center.longitude.toFixed(4)}°E` : ''}</p>
    </div>

    <div class="rail-section">
      <h4 class="rail-h">People affected</h4>
      <div class="stat-grid stat-grid--tight">
        <div class="stat"><b style="--c:#ff4d4d">${num(n.estimated_trapped)}</b><span>trapped</span></div>
        <div class="stat"><b style="--c:#ff8a3d">${num(n.estimated_injured)}</b><span>injured</span></div>
        <div class="stat"><b style="--c:#ffd23d">${num(n.estimated_displaced)}</b><span>displaced</span></div>
        <div class="stat"><b style="--c:#8193ab">${num(n.estimated_population)}</b><span>population</span></div>
      </div>
    </div>

    ${needs ? `<div class="rail-section"><h4 class="rail-h">What it needs</h4><div class="tag-row">${needs}</div></div>` : ''}

    <div class="rail-section ${assigned.length ? '' : 'rail-section--alert'}">
      <h4 class="rail-h">Units assigned</h4>
      ${assigned.length
        ? `<div class="mini-list">${assigned.map(r => `
            <button class="mini-row" data-unit="${esc(r.id)}">
              <i style="--c:${STATUS_COLORS[r.status]}"></i>
              <span class="mini-row__name">${esc(r.name)}</span>
              <span class="mini-row__state" style="--c:${STATUS_COLORS[r.status]}">${STATUS_LABELS[r.status] || r.status}</span>
            </button>`).join('')}</div>`
        : `<p class="rail-note">Nobody has been sent here yet.</p>`}
      <button class="btn btn-primary btn-sm btn-block" data-act="plan" data-zone="${esc(z.id)}">▶ Plan a dispatch here</button>
      <button class="btn btn-secondary btn-sm btn-block" data-act="manual" data-zone="${esc(z.id)}">Send a unit here manually</button>
    </div>

    <div class="rail-section">
      <h4 class="rail-h">Assessment</h4>
      <div class="kv-row"><span class="kv-key" data-tip="How sure we are about this zone's assessment. Low means the information is thin.">Confidence</span><span class="kv-val">${conf}%</span></div>
      <div class="meter"><i style="width:${conf}%;--c:${color}"></i></div>
      <div class="kv-row"><span class="kv-key">Last contact</span><span class="kv-val">${z.time_since_last_contact_minutes ?? 0} min ago</span></div>
      <div class="kv-row"><span class="kv-key">Zone ID</span><span class="kv-val kv-val--id">${esc(z.id)}</span></div>
    </div>`;
}

// Delegated: unit chips inside the zone detail.
document.addEventListener('click', (e) => {
  const row = e.target.closest('.mini-row[data-unit]');
  if (row) selectEntity({ type: 'resource', id: row.dataset.unit }, true);
});

/* ═══════════════════════════════════════════════════════════════════════════
   RADAR WIRING
   ═══════════════════════════════════════════════════════════════════════════ */

function initRadar() {
  radar = new RadarMap($('radar-canvas'), {
    onSelect: (sel) => selectEntity(sel),
    onHover: (hit, cx, cy) => showMapTooltip(hit, cx, cy),
    onPick: (coord) => applyPick(coord),
    onCursor: (coord) => updateCursorReadout(coord),
    onViewChange: () => updateViewReadout(),
  });
  radar.setData(state.resources, state.zones);
  radar.start();
  updateViewReadout();

  new ResizeObserver(() => radar.resize()).observe($('radar-canvas').parentElement);

  $('btn-zoom-in').addEventListener('click', () => radar.zoomBy(1.4));
  $('btn-zoom-out').addEventListener('click', () => radar.zoomBy(1 / 1.4));
  $('btn-fit').addEventListener('click', () => radar.fitData());
  $('btn-recenter').addEventListener('click', () => radar.fitDelhi());
  $('btn-cancel-pick').addEventListener('click', cancelPick);

  $$('.hud-toggle input').forEach(cb =>
    cb.addEventListener('change', () => radar.setLayer(cb.dataset.layer, cb.checked)));
}

function updateViewReadout() {
  if (!radar) return;
  const c = radar.center;
  $('ro-center').textContent = `${c.lat.toFixed(3)}°N ${c.lng.toFixed(3)}°E`;
  const spanKm = radar._w / radar.pxPerKm;
  $('ro-scale').textContent = `${spanKm.toFixed(1)} km across`;
  $('ro-place').textContent = describeLocation(c.lat, c.lng);
}

function updateCursorReadout(coord) {
  $('ro-cursor').textContent = `${coord.lat.toFixed(4)}°N ${coord.lng.toFixed(4)}°E`;
}

function showMapTooltip(hit, cx, cy) {
  const tip = $('map-tooltip');
  if (!hit) { tip.classList.remove('active'); return; }

  let html = '';
  if (hit.type === 'resource') {
    const r = state.resources.find(x => x.id === hit.id);
    if (!r) return;
    const key = r.is_uncertain ? 'uncertain' : r.status;
    html = `
      <div class="tt-title">${TYPE_GLYPHS[r.resource_type] || '📦'} ${esc(r.name)}</div>
      <div class="tt-line"><span class="tt-pill" style="--c:${STATUS_COLORS[key]}">${STATUS_LABELS[key]}</span> <code>${esc(r.callsign)}</code></div>
      <div class="tt-line tt-dim">${esc(TYPE_LABELS[r.resource_type] || '')} · ${esc(r.owning_agency_id)}</div>
      <div class="tt-line tt-dim">${r.home_base ? esc(describeLocation(r.home_base.latitude, r.home_base.longitude)) : ''}</div>
      <div class="tt-hint">Click to open details</div>`;
  } else {
    const z = state.zones.find(x => x.id === hit.id);
    if (!z) return;
    const n = z.needs || {};
    const assigned = (z.assigned_resource_ids || []).length;
    html = `
      <div class="tt-title">${esc(z.name)}</div>
      <div class="tt-line"><span class="tt-pill" style="--c:${PRIORITY_COLORS[z.priority]}">${PRIORITY_LABELS[z.priority]}</span> <code>${esc(z.zone_code)}</code></div>
      <div class="tt-line tt-dim">${esc(DAMAGE_LABELS[z.damage_level] || '')} · ${esc(ACCESS_LABELS[z.access_status] || '')}</div>
      ${n.estimated_trapped ? `<div class="tt-line">${num(n.estimated_trapped)} trapped · ${num(n.estimated_injured)} injured</div>` : ''}
      <div class="tt-line tt-dim">${assigned ? `${assigned} unit${assigned === 1 ? '' : 's'} assigned` : 'No units sent yet'}</div>
      <div class="tt-hint">Click to open details</div>`;
  }

  tip.innerHTML = html;
  tip.classList.add('active');

  const stage = $('radar-canvas').getBoundingClientRect();
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let x = cx - stage.left + 16, y = cy - stage.top + 16;
  if (x + w > stage.width - 8) x = cx - stage.left - w - 16;
  if (y + h > stage.height - 8) y = cy - stage.top - h - 16;
  tip.style.left = Math.max(8, x) + 'px';
  tip.style.top = Math.max(8, y) + 'px';
}

function updateMapEmpty() {
  $('map-empty').classList.toggle('active', !state.resources.length && !state.zones.length);
}

/* ── "Pick on map" ───────────────────────────────────────────────────────── */

function startPick(target) {
  state.pickTarget = target;
  closeModal(target === 'unit' ? 'modal-unit' : 'modal-zone');
  switchTab('ops');
  $('pick-banner').classList.add('active');
  radar.setPickMode(true);
}

function cancelPick() {
  if (!state.pickTarget) return;
  const t = state.pickTarget;
  state.pickTarget = null;
  $('pick-banner').classList.remove('active');
  radar.setPickMode(false);
  openModal(t === 'unit' ? 'modal-unit' : 'modal-zone');
}

function applyPick(coord) {
  const t = state.pickTarget;
  if (!t) return;
  const lat = +coord.lat.toFixed(4), lng = +coord.lng.toFixed(4);
  if (t === 'unit') {
    $('res-lat').value = lat; $('res-lng').value = lng;
    $('res-preset').value = '';
    updateLocHint('res');
  } else {
    $('zone-lat').value = lat; $('zone-lng').value = lng;
    $('zone-preset').value = '';
    updateLocHint('zone');
  }
  state.pickTarget = null;
  $('pick-banner').classList.remove('active');
  radar.setPickMode(false);
  openModal(t === 'unit' ? 'modal-unit' : 'modal-zone');
  showToast(`Location set — ${describeLocation(lat, lng)}.`, 'success');
}

/* ═══════════════════════════════════════════════════════════════════════════
   APPROVALS
   ═══════════════════════════════════════════════════════════════════════════ */

function renderPending() {
  const container = $('pending-list');
  const badge = $('approvals-badge');
  badge.textContent = state.pending.length || '';
  badge.classList.toggle('hidden', !state.pending.length);

  if (!state.pending.length) {
    container.innerHTML = `
      <div class="empty-state empty-state--lg">
        <div class="empty-state__title">Nothing waiting for you</div>
        <p>When the AI planner produces a recommendation it lands here for your decision.
           Until you approve one, no unit moves.</p>
        <div class="empty-state__actions">
          <button class="btn btn-secondary" onclick="openManualModal()">Send a unit manually</button>
          <button class="btn btn-primary" onclick="openPipelineModal()">▶ Plan a dispatch</button>
        </div>
      </div>`;
    return;
  }

  container.innerHTML = state.pending.map(p => {
    // Manual proposals carry no AI confidence, so don't dress a 0 up as one.
    const manual = String(p.dispatch_order_id || '').startsWith('MAN-');
    const conf = Math.round((p.ai_confidence || 0) * 100);
    const tone = conf >= 80 ? '#34d399' : conf >= 50 ? '#facc15' : '#f87171';
    const confWord = conf >= 80 ? 'High confidence' : conf >= 50 ? 'Moderate confidence — worth a read'
                                                    : 'Low confidence — check this carefully';
    const ttl = formatTTL(p.expires_at);
    const expiring = ttl.seconds >= 0 && ttl.seconds < 30;

    const unit = state.resources.find(r => r.id === p.resource_id);
    const zone = state.zones.find(z => z.id === p.zone_id);
    const dist = unit?.home_base && zone?.boundary?.center
      ? kmBetween(unit.home_base.latitude, unit.home_base.longitude,
                  zone.boundary.center.latitude, zone.boundary.center.longitude) : null;

    const alternatives = state.resources
      .filter(r => r.status === 'available' && !r.is_uncertain && r.id !== p.resource_id)
      .map(r => `<option value="${esc(r.id)}">${esc(r.name)} (${esc(r.callsign)})</option>`).join('');

    return `
      <article class="approval" data-id="${esc(p.id)}">
        <header class="approval__head">
          <div class="approval__route">
            <div class="approval__from">
              <span class="approval__eyebrow">Send</span>
              <strong>${TYPE_GLYPHS[unit?.resource_type] || '📦'} ${esc(p.resource_name || p.resource_id)}</strong>
              ${unit ? `<span class="approval__meta"><code>${esc(unit.callsign)}</code> · ${esc(unit.owning_agency_id)}</span>` : ''}
            </div>
            <div class="approval__arrow">→${dist != null ? `<span>${dist.toFixed(1)} km</span>` : ''}</div>
            <div class="approval__to">
              <span class="approval__eyebrow">To</span>
              <strong>${esc(zone?.name || p.zone_name || p.zone_id)}</strong>
              ${zone ? `<span class="approval__meta" style="color:${PRIORITY_COLORS[zone.priority]}">${PRIORITY_LABELS[zone.priority]} · ${esc(DAMAGE_LABELS[zone.damage_level] || '')}</span>` : ''}
            </div>
          </div>
          <div class="approval__ttl ${expiring ? 'is-expiring' : ''}" data-expires="${esc(p.expires_at || '')}">
            <span>${ttl.label}</span><em>left to decide</em>
          </div>
        </header>

        ${manual
          ? `<div class="approval__manual">You picked this unit yourself — the AI planner was not involved.</div>`
          : `<div class="approval__conf">
               <div class="meter"><i style="width:${conf}%;--c:${tone}"></i></div>
               <span style="color:${tone}">${conf}% — ${confWord}</span>
             </div>`}

        ${p.ai_reasoning ? `<div class="approval__why">
          <span class="approval__eyebrow">${manual ? 'On the record' : 'Why the planner chose this'}</span>
          <p>${esc(p.ai_reasoning)}</p></div>` : ''}

        <div class="approval__actions">
          <input type="text" class="approval-notes" placeholder="Add a note for the record (optional)">
          <button class="btn btn-success btn-approve" ${state.isPartitioned ? 'disabled' : ''}>✓ Approve and dispatch</button>
          <button class="btn btn-danger btn-reject">✗ Reject</button>
        </div>

        <details class="approval__override">
          <summary>Send a different unit instead</summary>
          <div class="approval__override-body">
            <select class="override-select">
              <option value="">Choose a unit that is ready…</option>
              ${alternatives || '<option value="" disabled>No other units are ready</option>'}
            </select>
            <button class="btn btn-amber btn-override" ${state.isPartitioned ? 'disabled' : ''}>Override and dispatch</button>
          </div>
        </details>

        ${state.isPartitioned ? `<p class="approval__blocked">Approvals are blocked while this post is cut off from the network.</p>` : ''}
      </article>`;
  }).join('');

  $$('.approval', container).forEach(card => {
    const id = card.dataset.id;
    const notes = card.querySelector('.approval-notes');
    card.querySelector('.btn-approve').addEventListener('click', () => confirmDispatch(id, notes.value));
    card.querySelector('.btn-reject').addEventListener('click', () => rejectDispatch(id, notes.value));
    card.querySelector('.btn-override').addEventListener('click', () => {
      const sel = card.querySelector('.override-select');
      if (!sel.value) { showToast('Choose which unit to send instead.', 'warning'); return; }
      overrideDispatch(id, sel.value, notes.value);
    });
  });
}

function formatTTL(expiresAt) {
  if (!expiresAt) return { label: '—', seconds: -1 };
  const diff = new Date(expiresAt) - Date.now();
  if (diff <= 0) return { label: 'expired', seconds: -1 };
  const sec = Math.floor(diff / 1000);
  const min = Math.floor(sec / 60);
  return { label: min > 0 ? `${min}m ${String(sec % 60).padStart(2, '0')}s` : `${sec}s`, seconds: sec };
}

async function confirmDispatch(id, notes) {
  try {
    const res = await api(`/dispatch/${id}/confirm`, {
      method: 'POST',
      body: { commander_id: state.commander.id, commander_agency_id: state.commander.agency_id, notes: notes || '' },
    });
    showToast(`Dispatched. Agreed by the network as change #${res.log_index}.`, 'success');
    fetchPending(); fetchResources(); fetchZones(); fetchAudit();
  } catch (e) { showToast(`Could not approve: ${errText(e)}`, 'error'); }
}

async function rejectDispatch(id, reason) {
  try {
    await api(`/dispatch/${id}/reject`, {
      method: 'POST',
      body: { commander_id: state.commander.id, commander_agency_id: state.commander.agency_id, reason: reason || '' },
    });
    showToast('Recommendation rejected. Nothing was dispatched.', 'info');
    fetchPending(); fetchAudit();
  } catch (e) { showToast(`Could not reject: ${errText(e)}`, 'error'); }
}

async function overrideDispatch(id, overrideResourceId, notes) {
  try {
    const res = await api(`/dispatch/${id}/override`, {
      method: 'POST',
      body: {
        commander_id: state.commander.id,
        override_resource_id: overrideResourceId,
        commander_agency_id: state.commander.agency_id,
        notes: notes || '',
      },
    });
    showToast(`Your chosen unit was dispatched — change #${res.log_index}.`, 'success');
    fetchPending(); fetchResources(); fetchZones(); fetchAudit();
  } catch (e) { showToast(`Could not override: ${errText(e)}`, 'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════════
   NETWORK
   ═══════════════════════════════════════════════════════════════════════════ */

function renderNetwork() {
  const c = state.cluster, h = state.health, p = state.peers;

  if (c) {
    $('cl-node-id').textContent = c.node_id || '—';
    $('cl-state').textContent = c.state === 'leader' ? 'Leader — writes changes'
      : c.state === 'follower' ? 'Follower — copies the leader'
      : c.state === 'candidate' ? 'Candidate — election in progress' : (c.state || '—');
    $('cl-leader').textContent = c.leader_id || 'none elected';
    $('cl-term').textContent = c.current_term ?? '—';
    $('cl-commit').textContent = num(c.commit_index ?? 0);
    $('cl-log').textContent = num(c.log_length ?? 0);
    const part = $('cl-partition');
    part.textContent = c.is_partitioned ? 'Yes — degraded' : 'No';
    part.style.color = c.is_partitioned ? 'var(--red)' : 'var(--green)';
  }

  if (h) {
    const badge = $('cl-health-badge');
    const ready = h.ready && !state.isPartitioned;
    badge.className = 'health-indicator ' + (ready ? 'health-indicator--ready' : 'health-indicator--not-ready');
    badge.textContent = ready ? '● Accepting dispatches' : '● Not accepting dispatches';
  }

  if (p) $('cl-quorum').textContent = `${p.quorum_size ?? '?'} of ${p.cluster_size ?? '?'} posts`;
  $('cl-res-count').textContent = state.resources.length;
  $('cl-zone-count').textContent = state.zones.length;

  // Plain-language verdict
  const verdict = $('net-verdict');
  const headline = $('net-headline'), detail = $('net-detail');
  if (state.isPartitioned) {
    verdict.dataset.tone = 'bad';
    headline.textContent = 'Cut off from the rest of the network';
    detail.textContent = 'This post cannot confirm unit status, so approvals are blocked and every unit shows as unconfirmed. This is deliberate: acting on stale data is how a unit gets sent to two places at once.';
  } else if (!c) {
    verdict.dataset.tone = 'unknown';
    headline.textContent = 'Waiting for the command post';
    detail.textContent = 'No status received yet.';
  } else if (c.state === 'candidate' || !c.leader_id) {
    verdict.dataset.tone = 'warn';
    headline.textContent = 'Choosing a leader';
    detail.textContent = 'The network is electing which post writes changes. This normally takes under a second — writes will resume by themselves.';
  } else {
    verdict.dataset.tone = 'good';
    headline.textContent = 'Healthy — everything is in sync';
    detail.textContent = `${c.state === 'leader' ? 'This post is the leader and can write changes.' : `Following ${c.leader_id}.`} ${num(c.commit_index ?? 0)} changes agreed by the network.`;
  }

  // Peers
  const tbody = $('cl-peer-tbody');
  if (!p || !p.peers?.length) {
    tbody.innerHTML = `<tr><td colspan="3" class="td-muted">
      Running as a single command post — no peers configured. Consensus still applies; there is simply nobody else to replicate to.
    </td></tr>`;
  } else {
    tbody.innerHTML = p.peers.map(peer => `
      <tr>
        <td>${esc(peer)}</td>
        <td>${p.next_index?.[peer] ?? '—'}</td>
        <td>${p.match_index?.[peer] ?? '—'}</td>
      </tr>`).join('');
  }
}

function updateWSDependentHealth() {
  const verdict = $('net-verdict');
  if (!verdict) return;
  verdict.dataset.tone = 'unknown';
  $('net-headline').textContent = 'Cannot reach this command post';
  $('net-detail').textContent = 'The dashboard could not load status from the server. Check that the Salus node is still running.';
}

/* ═══════════════════════════════════════════════════════════════════════════
   HISTORY
   ═══════════════════════════════════════════════════════════════════════════ */

function initHistory() {
  $('btn-audit-filter').addEventListener('click', fetchAudit);
  $('btn-audit-refresh').addEventListener('click', fetchAudit);
  $('audit-filter-action').addEventListener('change', fetchAudit);
}

function actionTone(action) {
  if (!action) return '';
  if (action.startsWith('ai_')) return 'ai';
  if (action === 'ic_confirm' || action === 'ic_override') return 'ok';
  if (action === 'ic_reject' || action === 'ic_timeout') return 'rej';
  if (action.startsWith('resource_')) return 'res';
  return 'sys';
}

function renderAudit() {
  const tbody = $('audit-tbody');
  const empty = $('audit-empty');

  if (!state.audit.length) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  tbody.innerHTML = state.audit.map(e => {
    const when = e.timestamp ? new Date(e.timestamp) : null;
    const ago = when ? relativeTime(when) : '—';
    const actor = e.actor_type === 'agent' || e.actor_type === 'system'
      ? `${esc(e.actor_id || 'system')} <span class="td-tag">automated</span>`
      : `${esc(e.actor_id || '—')} <span class="td-tag td-tag--human">person</span>`;
    return `
      <tr>
        <td><div>${ago}</div><div class="td-muted">${when ? when.toLocaleString('en-IN') : ''}</div></td>
        <td><span class="act act--${actionTone(e.action)}">${esc(ACTION_LABELS[e.action] || e.action || '—')}</span>
            ${e.commander_override ? '<span class="td-tag td-tag--warn">override</span>' : ''}</td>
        <td>${actor}</td>
        <td class="td-wrap">${esc(e.reasoning || e.override_reason || '—')}</td>
        <td>${e.confidence != null ? Math.round(e.confidence * 100) + '%' : '—'}</td>
        <td class="font-mono">${e.raft_log_index ?? '—'}</td>
      </tr>`;
  }).join('');
}

function relativeTime(date) {
  const s = Math.floor((Date.now() - date) / 1000);
  if (s < 45) return 'just now';
  if (s < 90) return 'under a minute ago';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/* ═══════════════════════════════════════════════════════════════════════════
   FORMS
   ═══════════════════════════════════════════════════════════════════════════ */

function initForms() {
  // Close buttons
  $$('[data-close]').forEach(b => b.addEventListener('click', () => closeModal(b.dataset.close)));
  $$('.modal-backdrop').forEach(bd => bd.addEventListener('click', (e) => {
    if (e.target === bd) closeModal(bd.id);
  }));

  // Delhi location presets
  for (const sel of [$('res-preset'), $('zone-preset')]) {
    sel.innerHTML = '<option value="">Choose a place…</option>' +
      DELHI.PRESETS.map((p, i) => `<option value="${i}">${esc(p.label)}</option>`).join('');
  }

  $('res-preset').addEventListener('change', (e) => {
    const p = DELHI.PRESETS[+e.target.value];
    if (!p) return;
    $('res-lat').value = p.lat; $('res-lng').value = p.lng;
    updateLocHint('res');
  });
  $('zone-preset').addEventListener('change', (e) => {
    const p = DELHI.PRESETS[+e.target.value];
    if (!p) return;
    $('zone-lat').value = p.lat; $('zone-lng').value = p.lng;
    updateLocHint('zone');
  });

  ['res-lat', 'res-lng'].forEach(id => $(id).addEventListener('input', () => updateLocHint('res')));
  ['zone-lat', 'zone-lng'].forEach(id => $(id).addEventListener('input', () => updateLocHint('zone')));

  $('btn-pick-unit').addEventListener('click', () => startPick('unit'));
  $('btn-pick-zone').addEventListener('click', () => startPick('zone'));

  // Type presets fill in capabilities
  $('res-type').addEventListener('change', applyTypeDefaults);

  $('btn-submit-unit').addEventListener('click', submitUnit);
  $('btn-submit-zone').addEventListener('click', submitZone);

  // Manual dispatch — the route that does not need the AI planner.
  $('btn-manual-dispatch').addEventListener('click', () => openManualModal());
  $('manual-zone').addEventListener('change', () => populateManualUnits($('manual-zone').value));
  $('btn-submit-manual').addEventListener('click', submitManualDispatch);
}

/* ── Manual dispatch ───────────────────────────────────────────────────────
   Posts straight into the commander gate via /dispatch/recommend. The human
   approval step is unchanged — this only skips the AI's suggestion.        */

function openManualModal(zoneId = null, resourceId = null) {
  if (!state.zones.length) {
    showToast('Add a disaster zone first — a unit has to be sent somewhere.', 'warning');
    switchTab('ops'); setRailView('zones');
    return;
  }
  const ready = state.resources.filter(r => r.status === 'available' && !r.is_uncertain);
  if (!ready.length) {
    showToast('No units are ready to send right now.', 'warning');
    return;
  }

  const zSel = $('manual-zone');
  zSel.innerHTML = [...state.zones]
    .sort((a, b) => (a.priority || 9) - (b.priority || 9))
    .map(z => `<option value="${esc(z.id)}">${esc(z.name)} — ${PRIORITY_LABELS[z.priority]}</option>`).join('');
  if (zoneId) zSel.value = zoneId;
  else if (state.selection?.type === 'zone') zSel.value = state.selection.id;

  populateManualUnits(zSel.value, resourceId);
  $('manual-reason').value = '';
  openModal('modal-manual');
}
window.openManualModal = openManualModal;

/** Ready units, nearest to the chosen zone first. */
function populateManualUnits(zoneId, preferredId = null) {
  const zone = state.zones.find(z => z.id === zoneId);
  const center = zone?.boundary?.center;

  const ready = state.resources
    .filter(r => r.status === 'available' && !r.is_uncertain)
    .map(r => ({
      r,
      km: center && r.home_base
        ? kmBetween(r.home_base.latitude, r.home_base.longitude, center.latitude, center.longitude)
        : null,
    }))
    .sort((a, b) => (a.km ?? 1e9) - (b.km ?? 1e9));

  const sel = $('manual-unit');
  sel.innerHTML = ready.map(({ r, km }) =>
    `<option value="${esc(r.id)}">${esc(r.name)} (${esc(r.callsign)})${km != null ? ` — ${km.toFixed(1)} km away` : ''}</option>`
  ).join('');
  if (preferredId && ready.some(x => x.r.id === preferredId)) sel.value = preferredId;

  $('manual-unit-hint').textContent = ready.length
    ? `${ready.length} unit${ready.length === 1 ? '' : 's'} ready. Nearest to the zone first.`
    : 'No units are ready to send.';
}

async function submitManualDispatch() {
  const zoneId = $('manual-zone').value;
  const resourceId = $('manual-unit').value;
  if (!zoneId || !resourceId) { showToast('Choose both a zone and a unit.', 'error'); return; }

  const zone = state.zones.find(z => z.id === zoneId);
  const unit = state.resources.find(r => r.id === resourceId);
  const reason = $('manual-reason').value.trim();

  try {
    await api('/dispatch/recommend', {
      method: 'POST',
      body: {
        dispatch_order_id: 'MAN-' + Math.random().toString(36).slice(2, 10).toUpperCase(),
        resource_id: resourceId,
        resource_name: unit?.name || '',
        zone_id: zoneId,
        zone_name: zone?.name || '',
        incident_id: 'INC-' + Math.random().toString(36).slice(2, 8).toUpperCase(),
        ai_confidence: 0,
        ai_reasoning: `Proposed manually by ${state.commander.id} (${state.commander.agency_id}) — not an AI recommendation.`
                      + (reason ? ` Reason given: ${reason}` : ''),
        alternative_resources: [],
      },
    });
    closeModal('modal-manual');
    showToast('Queued for approval. Confirm it on the Approvals screen.', 'success');
    await fetchPending();
    switchTab('approvals');
  } catch (e) {
    showToast(`Could not queue the dispatch: ${errText(e)}`, 'error');
  }
}

function updateLocHint(prefix) {
  const lat = parseFloat($(`${prefix}-lat`).value);
  const lng = parseFloat($(`${prefix}-lng`).value);
  const hint = $(`${prefix}-loc-hint`);
  if (isNaN(lat) || isNaN(lng)) { hint.textContent = 'No location set yet.'; hint.classList.remove('is-ok'); return; }
  const inDelhi = lat > 28.2 && lat < 29.0 && lng > 76.6 && lng < 77.7;
  hint.textContent = inDelhi
    ? `📍 ${describeLocation(lat, lng)}`
    : `📍 ${lat.toFixed(3)}°, ${lng.toFixed(3)}° — outside the Delhi NCR area.`;
  hint.classList.toggle('is-ok', inDelhi);
}

function applyTypeDefaults() {
  const d = TYPE_DEFAULTS[$('res-type').value];
  if (!d) return;
  const capIds = ['sar', 'medical', 'firefighting', 'hazmat', 'water-rescue', 'air', 'thermal', 'listening'];
  capIds.forEach(c => { $(`cap-${c}`).checked = d.caps.includes(c); });
  $('res-personnel').value = d.personnel;
  $('res-range').value = d.range;
  $('res-fuel').value = d.fuel;
  $('res-type-hint').textContent = 'Capabilities below were filled in for this type — adjust if needed.';
}

function openUnitModal() {
  ['res-name', 'res-callsign', 'res-lat', 'res-lng'].forEach(id => { $(id).value = ''; });
  $('res-preset').value = '';
  $('res-agency').value = state.commander?.agency_id || '';
  applyTypeDefaults();
  updateLocHint('res');
  openModal('modal-unit');
  setTimeout(() => $('res-name').focus(), 60);
}

function openZoneModal() {
  ['zone-name', 'zone-code', 'zone-lat', 'zone-lng', 'zone-address'].forEach(id => { $(id).value = ''; });
  $('zone-preset').value = '';
  $('zone-radius').value = 2.0;
  $('zone-priority').value = '3';
  $('zone-damage').value = 'unknown';
  $('zone-access').value = 'unknown';
  $$('#modal-zone .checkbox-item input').forEach(cb => { cb.checked = false; });
  ['zone-trapped', 'zone-injured', 'zone-displaced', 'zone-population'].forEach(id => { $(id).value = 0; });
  updateLocHint('zone');
  openModal('modal-zone');
  setTimeout(() => $('zone-name').focus(), 60);
}

async function submitUnit() {
  const name = $('res-name').value.trim();
  const callsign = $('res-callsign').value.trim();
  const agency = $('res-agency').value.trim();
  const lat = parseFloat($('res-lat').value);
  const lng = parseFloat($('res-lng').value);

  const missing = [];
  if (!name) missing.push('name');
  if (!callsign) missing.push('callsign');
  if (!agency) missing.push('owning agency');
  if (isNaN(lat) || isNaN(lng)) missing.push('home base location');
  if (missing.length) { showToast(`Still needed: ${missing.join(', ')}.`, 'error'); return; }

  const resource = {
    name, callsign, resource_type: $('res-type').value, owning_agency_id: agency,
    home_base: { latitude: lat, longitude: lng },
    capabilities: {
      can_perform_sar: $('cap-sar').checked,
      can_perform_medical: $('cap-medical').checked,
      has_medical_personnel: $('cap-medical').checked,
      can_perform_firefighting: $('cap-firefighting').checked,
      can_perform_hazmat: $('cap-hazmat').checked,
      can_perform_water_rescue: $('cap-water-rescue').checked,
      can_access_water: $('cap-water-rescue').checked,
      can_access_air: $('cap-air').checked,
      has_thermal_imaging: $('cap-thermal').checked,
      has_listening_devices: $('cap-listening').checked,
      personnel_count: parseInt($('res-personnel').value) || 0,
      max_range_km: parseFloat($('res-range').value) || 0,
      fuel_hours_remaining: parseFloat($('res-fuel').value) || 0,
    },
  };

  try {
    const res = await api('/resources', { method: 'POST', body: { resource } });
    showToast(`${name} added — agreed by the network as change #${res.log_index}.`, 'success');
    closeModal('modal-unit');
    await fetchResources();
    radar?.flyTo(lat, lng, Math.max(radar.pxPerKm, 26));
  } catch (e) { showToast(`Could not add the unit: ${errText(e)}`, 'error'); }
}

async function submitZone() {
  const name = $('zone-name').value.trim();
  const code = $('zone-code').value.trim();
  const lat = parseFloat($('zone-lat').value);
  const lng = parseFloat($('zone-lng').value);

  const missing = [];
  if (!name) missing.push('name');
  if (!code) missing.push('short code');
  if (isNaN(lat) || isNaN(lng)) missing.push('centre location');
  if (missing.length) { showToast(`Still needed: ${missing.join(', ')}.`, 'error'); return; }

  const zone = {
    name, zone_code: code,
    priority: parseInt($('zone-priority').value),
    damage_level: $('zone-damage').value,
    access_status: $('zone-access').value,
    address_description: $('zone-address').value.trim(),
    boundary: { center: { latitude: lat, longitude: lng }, radius_km: parseFloat($('zone-radius').value) || 1.0 },
    needs: {
      needs_sar: $('need-sar').checked,
      needs_medical: $('need-medical').checked,
      needs_evacuation: $('need-evacuation').checked,
      needs_water: $('need-water').checked,
      needs_food: $('need-food').checked,
      needs_shelter: $('need-shelter').checked,
      needs_power: $('need-power').checked,
      needs_hazmat: $('need-hazmat').checked,
      needs_firefighting: $('need-firefighting').checked,
      needs_engineering: $('need-engineering').checked,
      needs_communication: $('need-comms').checked,
      estimated_trapped: parseInt($('zone-trapped').value) || 0,
      estimated_injured: parseInt($('zone-injured').value) || 0,
      estimated_displaced: parseInt($('zone-displaced').value) || 0,
      estimated_population: parseInt($('zone-population').value) || 0,
    },
  };

  try {
    const res = await api('/zones', { method: 'POST', body: { zone } });
    showToast(`${name} added — agreed by the network as change #${res.log_index}.`, 'success');
    closeModal('modal-zone');
    await fetchZones();
    radar?.flyTo(lat, lng, Math.max(radar.pxPerKm, 22));
  } catch (e) { showToast(`Could not add the zone: ${errText(e)}`, 'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════════
   AI PIPELINE
   ═══════════════════════════════════════════════════════════════════════════ */

function initPipeline() {
  $('btn-plan-dispatch').addEventListener('click', () => openPipelineModal());
  $('btn-run-pipeline').addEventListener('click', runPipeline);
  $('pipe-examples').addEventListener('click', (e) => {
    const b = e.target.closest('.echip'); if (!b) return;
    $('pipe-description').value = PIPELINE_EXAMPLES[b.dataset.example] || '';
    $('pipe-description').focus();
  });
}

function openPipelineModal(zoneId = null) {
  if (!state.zones.length) {
    showToast('Add a disaster zone first — the planner needs somewhere to send units.', 'warning');
    switchTab('ops'); setRailView('zones');
    return;
  }

  const sel = $('pipe-zone');
  sel.innerHTML = [...state.zones]
    .sort((a, b) => (a.priority || 9) - (b.priority || 9))
    .map(z => `<option value="${esc(z.id)}">${esc(z.name)} — ${PRIORITY_LABELS[z.priority]}</option>`).join('');
  if (zoneId) sel.value = zoneId;
  else if (state.selection?.type === 'zone') sel.value = state.selection.id;

  $('pipe-incident-id').value = 'INC-' + Math.random().toString(36).slice(2, 8).toUpperCase();
  $('pipe-description').value = '';
  $('pipeline-progress').classList.add('hidden');
  $('pipeline-result').classList.add('hidden');
  $('pipeline-result').innerHTML = '';
  $$('.pipeline-stage').forEach(s => s.className = 'pipeline-stage');

  openModal('modal-pipeline');
  setTimeout(() => $('pipe-description').focus(), 60);
}
window.openPipelineModal = openPipelineModal;

async function runPipeline() {
  const zoneId = $('pipe-zone').value;
  const incidentId = $('pipe-incident-id').value.trim();
  const desc = $('pipe-description').value.trim();

  if (!zoneId) { showToast('Choose which zone needs help.', 'error'); return; }
  if (desc.length < 10) { showToast('Describe what is happening — at least a sentence.', 'error'); return; }

  state.pipelineRunning = true;
  $('btn-run-pipeline').disabled = true;

  const progress = $('pipeline-progress');
  const result = $('pipeline-result');
  progress.classList.remove('hidden');
  result.classList.add('hidden');
  result.innerHTML = '';

  const stages = $$('.pipeline-stage');
  stages.forEach(s => s.className = 'pipeline-stage');

  let i = 0;
  const tick = setInterval(() => {
    if (i > 0 && i <= stages.length) stages[i - 1].classList.replace('active', 'complete');
    if (i < stages.length) stages[i].classList.add('active');
    i++;
  }, 700);

  try {
    const res = await api('/dispatch/run-pipeline', {
      method: 'POST',
      body: { incident_id: incidentId, zone_id: zoneId, incident_description: desc },
    });

    clearInterval(tick);
    stages.forEach(s => { s.classList.remove('active'); s.classList.add('complete'); });

    const order = res.dispatch_order || {};
    const conf = order.decision_confidence;
    const confPct = conf != null ? Math.round(conf * 100) : null;
    const unit = state.resources.find(r => r.id === order.assigned_resource_id);

    result.classList.remove('hidden');
    result.innerHTML = `
      <div class="pipe-result">
        <div class="pipe-result__head">
          <span class="pipe-result__tick">✓</span>
          <div>
            <strong>The planner has a recommendation.</strong>
            <p>It is now waiting in <em>Approvals</em>. Nothing has moved yet — you decide.</p>
          </div>
        </div>
        ${res.used_fallback ? `<p class="warn-note">The AI was unavailable, so this came from simple rules instead. Read it carefully before approving.</p>` : ''}
        <div class="kv-row"><span class="kv-key">Recommended unit</span><span class="kv-val">${esc(order.assigned_resource_name || unit?.name || '—')}</span></div>
        ${confPct != null ? `<div class="kv-row"><span class="kv-key">Confidence</span><span class="kv-val">${confPct}%</span></div>` : ''}
        <div class="kv-row"><span class="kv-key">Time taken</span><span class="kv-val">${res.total_latency_ms != null ? `${num(res.total_latency_ms)} ms` : '—'}</span></div>
        ${order.decision_summary ? `<div class="pipe-result__why">${esc(order.decision_summary)}</div>` : ''}
        <button class="btn btn-primary btn-block" id="btn-goto-approvals">Go to Approvals →</button>
      </div>`;

    $('btn-goto-approvals').addEventListener('click', () => {
      closeModal('modal-pipeline');
      switchTab('approvals');
    });

    showToast('Recommendation ready — it is waiting in Approvals.', 'success');
    fetchPending(); fetchAudit();
  } catch (e) {
    clearInterval(tick);
    stages.forEach(s => s.classList.remove('active'));
    progress.classList.add('hidden');

    if (e.status === 503) {
      result.classList.remove('hidden');
      result.innerHTML = `
        <div class="pipe-result pipe-result--err">
          <strong>The AI planner is not installed on this server.</strong>
          <p>Everything else still works. Use <em>Send a unit manually</em> to choose the
             unit yourself — it goes through the same approval gate. To enable the
             planner, install the AI extras and restart the node:</p>
          <pre>pip install -e ".[ai]"</pre>
          <button class="btn btn-secondary btn-block" id="btn-manual-instead">Send a unit manually instead</button>
        </div>`;
      $('btn-manual-instead').addEventListener('click', () => {
        closeModal('modal-pipeline');
        openManualModal($('pipe-zone').value);
      });
    } else {
      showToast(`The planner failed: ${errText(e)}`, 'error', 7000);
    }
  } finally {
    state.pipelineRunning = false;
    $('btn-run-pipeline').disabled = false;
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   WEBSOCKET
   ═══════════════════════════════════════════════════════════════════════════ */

function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  updateWSStatus('connecting');

  try {
    state.ws = new WebSocket(`${proto}://${location.host}/ws/events`);
  } catch (_) {
    updateWSStatus('offline');
    setTimeout(connectWebSocket, 5000);
    return;
  }

  state.ws.onopen = () => updateWSStatus('live');

  state.ws.onmessage = (evt) => {
    let msg; try { msg = JSON.parse(evt.data); } catch (_) { return; }
    switch (msg.type || msg.event) {
      case 'resource_registered':
        fetchResources(); break;
      case 'resource_dispatched':
      case 'resource_dispatched_override':
        fetchResources(); fetchZones(); fetchAudit(); break;
      case 'zone_registered':
        fetchZones(); break;
      case 'dispatch_recommendation_queued':
        fetchPending(); break;
      case 'pipeline_recommendation_ready':
        fetchPending();
        showToast('A new recommendation is waiting for your approval.', 'info');
        break;
      case 'dispatch_rejected':
        fetchPending(); break;
    }
  };

  state.ws.onclose = () => {
    updateWSStatus('offline');
    setTimeout(() => {
      if (!state.ws || state.ws.readyState === WebSocket.CLOSED) connectWebSocket();
    }, 5000);
  };

  state.ws.onerror = () => updateWSStatus('offline');
}

function updateWSStatus(status) {
  const dot = $('ws-dot'), label = $('ws-label');
  if (!dot) return;
  const map = {
    live: ['dot--green', 'Live'],
    connecting: ['dot--amber', 'Connecting'],
    offline: ['dot--red', 'Offline'],
  };
  const [cls, text] = map[status] || map.offline;
  dot.className = 'dot ' + cls;
  label.textContent = text;
}

/* ═══════════════════════════════════════════════════════════════════════════
   TOOLTIPS  (anything with data-tip)
   ═══════════════════════════════════════════════════════════════════════════ */

function initTooltips() {
  const tip = document.createElement('div');
  tip.className = 'tip-bubble';
  document.body.appendChild(tip);
  let target = null;

  document.addEventListener('pointerover', (e) => {
    const el = e.target.closest?.('[data-tip]');
    if (el === target) return;
    target = el;
    if (!el) { tip.classList.remove('active'); return; }
    tip.textContent = el.dataset.tip;
    tip.classList.add('active');
    const r = el.getBoundingClientRect();
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let x = r.left + r.width / 2 - tw / 2;
    let y = r.bottom + 8;
    if (y + th > window.innerHeight - 8) y = r.top - th - 8;
    tip.style.left = Math.max(8, Math.min(x, window.innerWidth - tw - 8)) + 'px';
    tip.style.top = Math.max(8, y) + 'px';
  });

  document.addEventListener('pointerdown', () => { tip.classList.remove('active'); target = null; });
  window.addEventListener('scroll', () => { tip.classList.remove('active'); target = null; }, true);
}
