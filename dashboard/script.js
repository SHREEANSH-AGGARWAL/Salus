/**
 * Salus Command Dashboard — Interactive Client
 *
 * Canvas rendering engine for Raft cluster topology and zone map visualization,
 * real-time WebSocket event streaming, drag-and-drop entity placement, and
 * dispatch confirmation UI.
 */

(() => {
  'use strict';

  // ════════════════════════════════════════════════════════════════════════════
  // Configuration
  // ════════════════════════════════════════════════════════════════════════════

  const API_BASE = window.location.protocol === 'file:'
    ? 'http://localhost:8000'
    : window.location.origin;
  const WS_URL = API_BASE.replace(/^http/, 'ws') + '/ws/events';
  const POLL_CLUSTER_MS = 2000;
  const POLL_PENDING_MS = 3000;
  const POLL_RESOURCES_MS = 5000;
  const MAX_EVENTS = 200;

  // ════════════════════════════════════════════════════════════════════════════
  // State
  // ════════════════════════════════════════════════════════════════════════════

  const state = {
    // View mode
    currentView: 'topology', // 'topology' | 'map'

    // Cluster
    clusterStatus: null,
    nodes: [
      { id: 'alpha', label: 'ICP Alpha', agency: 'Fire Dept', state: 'offline', term: 0, logLength: 0 },
      { id: 'bravo', label: 'ICP Bravo', agency: 'EMS', state: 'offline', term: 0, logLength: 0 },
      { id: 'charlie', label: 'ICP Charlie', agency: 'USAR', state: 'offline', term: 0, logLength: 0 },
    ],

    // Resources & Zones (from API)
    resources: [],
    zones: [],

    // Dispatch queue
    pending: [],

    // Events
    events: [],
    eventCount: 0,

    // WebSocket
    ws: null,
    wsConnected: false,
    wsReconnectDelay: 1000,
    wsReconnectTimer: null,

    // Canvas
    canvas: null,
    ctx: null,
    canvasWidth: 0,
    canvasHeight: 0,
    animationFrame: null,
    time: 0,

    // Heartbeat particles
    heartbeatParticles: [],

    // Dispatch animations (resource flying to zone)
    dispatchAnimations: [],

    // Dropped entities on canvas
    droppedEntities: [],
  };

  // ════════════════════════════════════════════════════════════════════════════
  // Initialization
  // ════════════════════════════════════════════════════════════════════════════

  function init() {
    setupCanvas();
    setupTabs();
    setupDragDrop();
    setupViewToggle();
    connectWebSocket();
    pollClusterStatus();
    pollPendingDispatches();
    pollResources();
    startRenderLoop();
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Canvas Setup & Rendering
  // ════════════════════════════════════════════════════════════════════════════

  function setupCanvas() {
    state.canvas = document.getElementById('main-canvas');
    state.ctx = state.canvas.getContext('2d');
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
  }

  function resizeCanvas() {
    const area = document.getElementById('canvas-area');
    const dpr = window.devicePixelRatio || 1;
    state.canvasWidth = area.clientWidth;
    state.canvasHeight = area.clientHeight;
    state.canvas.width = state.canvasWidth * dpr;
    state.canvas.height = state.canvasHeight * dpr;
    state.canvas.style.width = state.canvasWidth + 'px';
    state.canvas.style.height = state.canvasHeight + 'px';
    state.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function startRenderLoop() {
    function frame(timestamp) {
      state.time = timestamp || 0;
      render();
      state.animationFrame = requestAnimationFrame(frame);
    }
    state.animationFrame = requestAnimationFrame(frame);
  }

  function render() {
    const ctx = state.ctx;
    const w = state.canvasWidth;
    const h = state.canvasHeight;

    // Clear
    ctx.clearRect(0, 0, w, h);

    // Background grid
    drawGrid(ctx, w, h);

    if (state.currentView === 'topology') {
      drawTopology(ctx, w, h);
    } else {
      drawZoneMap(ctx, w, h);
    }

    // Dispatch animations (both views)
    updateDispatchAnimations(ctx, w, h);
  }

  function drawGrid(ctx, w, h) {
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.015)';
    ctx.lineWidth = 1;
    const step = 40;
    for (let x = step; x < w; x += step) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = step; y < h; y += step) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
  }

  // ── Topology View ──────────────────────────────────────────────────────────

  function drawTopology(ctx, w, h) {
    const nodes = state.nodes;
    const cx = w / 2;
    const cy = h / 2;
    const radius = Math.min(w, h) * 0.28;

    // Compute positions in a triangle
    const positions = nodes.map((_, i) => {
      const angle = (i * 2 * Math.PI / nodes.length) - Math.PI / 2;
      return {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
      };
    });

    // Draw connection lines between all nodes
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        drawHeartbeatLine(ctx, positions[i], positions[j], nodes[i], nodes[j]);
      }
    }

    // Draw heartbeat particles
    drawHeartbeatParticles(ctx);

    // Draw nodes
    nodes.forEach((node, i) => {
      drawNode(ctx, positions[i].x, positions[i].y, node);
    });

    // Title
    ctx.fillStyle = 'rgba(255, 255, 255, 0.12)';
    ctx.font = '600 11px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('RAFT CONSENSUS CLUSTER', cx, 36);
  }

  function drawHeartbeatLine(ctx, p1, p2, n1, n2) {
    const bothAlive = n1.state !== 'offline' && n2.state !== 'offline';
    const hasLeader = n1.state === 'leader' || n2.state === 'leader';

    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);

    if (!bothAlive) {
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 8]);
    } else if (hasLeader) {
      ctx.strokeStyle = 'rgba(0, 230, 118, 0.18)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([]);
    } else {
      ctx.strokeStyle = 'rgba(0, 229, 255, 0.1)';
      ctx.lineWidth = 1;
      ctx.setLineDash([]);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    // Spawn heartbeat particles if leader is present
    if (bothAlive && hasLeader && Math.random() < 0.012) {
      const leaderPos = n1.state === 'leader' ? p1 : p2;
      const followerPos = n1.state === 'leader' ? p2 : p1;
      state.heartbeatParticles.push({
        x: leaderPos.x,
        y: leaderPos.y,
        tx: followerPos.x,
        ty: followerPos.y,
        progress: 0,
        speed: 0.015 + Math.random() * 0.008,
      });
    }
  }

  function drawHeartbeatParticles(ctx) {
    state.heartbeatParticles = state.heartbeatParticles.filter(p => {
      p.progress += p.speed;
      if (p.progress >= 1) return false;

      const x = p.x + (p.tx - p.x) * p.progress;
      const y = p.y + (p.ty - p.y) * p.progress;
      const alpha = 1 - Math.abs(p.progress - 0.5) * 2;

      ctx.beginPath();
      ctx.arc(x, y, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0, 230, 118, ${alpha * 0.8})`;
      ctx.fill();

      // Glow
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0, 230, 118, ${alpha * 0.15})`;
      ctx.fill();

      return true;
    });
  }

  function drawNode(ctx, x, y, node) {
    const isLeader = node.state === 'leader';
    const isFollower = node.state === 'follower';
    const isCandidate = node.state === 'candidate';
    const isOffline = node.state === 'offline';
    const baseRadius = 32;

    // Outer glow
    if (!isOffline) {
      const glowColor = isLeader ? 'rgba(0, 230, 118, 0.12)' :
                         isCandidate ? 'rgba(255, 171, 0, 0.1)' :
                         'rgba(0, 229, 255, 0.08)';
      const glowRadius = baseRadius + 16 + (isLeader ? Math.sin(state.time / 600) * 4 : 0);
      const grad = ctx.createRadialGradient(x, y, baseRadius * 0.5, x, y, glowRadius);
      grad.addColorStop(0, glowColor);
      grad.addColorStop(1, 'transparent');
      ctx.beginPath();
      ctx.arc(x, y, glowRadius, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();
    }

    // Node circle
    ctx.beginPath();
    ctx.arc(x, y, baseRadius, 0, Math.PI * 2);
    if (isLeader) {
      ctx.fillStyle = 'rgba(0, 230, 118, 0.12)';
      ctx.strokeStyle = 'rgba(0, 230, 118, 0.6)';
    } else if (isCandidate) {
      ctx.fillStyle = 'rgba(255, 171, 0, 0.1)';
      ctx.strokeStyle = 'rgba(255, 171, 0, 0.5)';
    } else if (isFollower) {
      ctx.fillStyle = 'rgba(0, 229, 255, 0.08)';
      ctx.strokeStyle = 'rgba(0, 229, 255, 0.4)';
    } else {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.03)';
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
    }
    ctx.lineWidth = isLeader ? 2 : 1.5;
    ctx.fill();
    ctx.stroke();

    // Leader crown
    if (isLeader) {
      ctx.fillStyle = '#00e676';
      ctx.font = '14px serif';
      ctx.textAlign = 'center';
      ctx.fillText('👑', x, y - baseRadius - 8);
    }

    // Node icon
    const icon = node.id === 'alpha' ? '🏛️' : node.id === 'bravo' ? '🏥' : '🔍';
    ctx.font = '18px serif';
    ctx.textAlign = 'center';
    ctx.fillText(icon, x, y + 6);

    // Label
    ctx.fillStyle = isOffline ? 'rgba(255, 255, 255, 0.25)' : '#e8ecf4';
    ctx.font = '600 12px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(node.label, x, y + baseRadius + 20);

    // State label
    const stateLabel = (node.state || 'offline').toUpperCase();
    ctx.fillStyle = isLeader ? '#00e676' :
                    isCandidate ? '#ffab00' :
                    isFollower ? '#00e5ff' : 'rgba(255,255,255,0.2)';
    ctx.font = '600 9px JetBrains Mono, monospace';
    ctx.fillText(stateLabel, x, y + baseRadius + 34);

    // Term & Log
    if (!isOffline) {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
      ctx.font = '10px JetBrains Mono, monospace';
      ctx.fillText(`T:${node.term} L:${node.logLength}`, x, y + baseRadius + 48);
    }
  }

  // ── Zone Map View ──────────────────────────────────────────────────────────

  function drawZoneMap(ctx, w, h) {
    const zones = state.zones;
    const resources = state.resources;

    // Title
    ctx.fillStyle = 'rgba(255, 255, 255, 0.12)';
    ctx.font = '600 11px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('DISASTER ZONE MAP', w / 2, 36);

    if (zones.length === 0 && resources.length === 0) {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.15)';
      ctx.font = '400 14px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No zones or resources registered yet.', w / 2, h / 2 - 10);
      ctx.font = '400 11px Inter, sans-serif';
      ctx.fillStyle = 'rgba(255, 255, 255, 0.08)';
      ctx.fillText('Seed the cluster or drop entities from the sidebar.', w / 2, h / 2 + 14);
      return;
    }

    // Calculate bounds for auto-fit
    let minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity;
    zones.forEach(z => {
      const c = z.boundary?.center;
      if (c) {
        minLat = Math.min(minLat, c.latitude);
        maxLat = Math.max(maxLat, c.latitude);
        minLng = Math.min(minLng, c.longitude);
        maxLng = Math.max(maxLng, c.longitude);
      }
    });
    resources.forEach(r => {
      const hb = r.home_base;
      if (hb) {
        minLat = Math.min(minLat, hb.latitude);
        maxLat = Math.max(maxLat, hb.latitude);
        minLng = Math.min(minLng, hb.longitude);
        maxLng = Math.max(maxLng, hb.longitude);
      }
    });

    // Add padding
    const pad = 0.01;
    minLat -= pad; maxLat += pad; minLng -= pad; maxLng += pad;
    if (maxLat === minLat) { maxLat += 0.05; minLat -= 0.05; }
    if (maxLng === minLng) { maxLng += 0.05; minLng -= 0.05; }

    const margin = 60;
    const mapW = w - margin * 2;
    const mapH = h - margin * 2;

    function geoToCanvas(lat, lng) {
      const xNorm = (lng - minLng) / (maxLng - minLng);
      const yNorm = 1 - (lat - minLat) / (maxLat - minLat);
      return { x: margin + xNorm * mapW, y: margin + yNorm * mapH };
    }

    // Draw zones
    const priorityColors = {
      1: { fill: 'rgba(255, 23, 68, 0.12)', stroke: 'rgba(255, 23, 68, 0.5)', text: '#ff1744' },
      2: { fill: 'rgba(255, 171, 0, 0.1)', stroke: 'rgba(255, 171, 0, 0.4)', text: '#ffab00' },
      3: { fill: 'rgba(255, 235, 59, 0.08)', stroke: 'rgba(255, 235, 59, 0.3)', text: '#ffeb3b' },
      4: { fill: 'rgba(0, 230, 118, 0.08)', stroke: 'rgba(0, 230, 118, 0.3)', text: '#00e676' },
      5: { fill: 'rgba(255, 255, 255, 0.04)', stroke: 'rgba(255, 255, 255, 0.15)', text: '#8a94a6' },
    };

    zones.forEach(z => {
      const c = z.boundary?.center;
      if (!c) return;
      const pos = geoToCanvas(c.latitude, c.longitude);
      const r = Math.max(20, (z.boundary?.radius_km || 1) * 15);
      const p = z.priority || 5;
      const colors = priorityColors[p] || priorityColors[5];

      // Zone circle
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, r, 0, Math.PI * 2);
      ctx.fillStyle = colors.fill;
      ctx.fill();
      ctx.strokeStyle = colors.stroke;
      ctx.lineWidth = 1.5;

      // Critical zone animation
      if (p === 1) {
        const flash = 0.3 + Math.sin(state.time / 400) * 0.2;
        ctx.strokeStyle = `rgba(255, 23, 68, ${flash})`;
        ctx.lineWidth = 2;
      }
      ctx.stroke();

      // Zone label
      ctx.fillStyle = colors.text;
      ctx.font = '600 10px Inter, sans-serif';
      ctx.textAlign = 'center';
      const name = z.name || z.zone_code || z.id;
      ctx.fillText(name.length > 20 ? name.slice(0, 20) + '…' : name, pos.x, pos.y + r + 14);

      // Priority badge
      ctx.fillStyle = colors.stroke;
      ctx.font = '700 9px JetBrains Mono, monospace';
      ctx.fillText(`P${p}`, pos.x, pos.y - 2);
    });

    // Draw resources
    const statusIcons = {
      available: '🟢',
      dispatched: '🔵',
      on_scene: '🟡',
      returning: '🔄',
      needs_resupply: '🟠',
      resupplying: '⏳',
      maintenance: '🔧',
    };

    const typeIcons = {
      helicopter_transport: '🚁',
      helicopter_medical: '🚁',
      helicopter_heavy_lift: '🚁',
      ambulance: '🚑',
      ambulance_als: '🚑',
      fire_engine: '🚒',
      sar_team_urban: '🦺',
      sar_team_water: '🛟',
      hazmat_team: '☣️',
      k9_unit: '🐕',
      drone_team: '🛸',
      supply_truck: '🚚',
      evacuation_bus: '🚌',
      field_hospital: '⛺',
      generator: '⚡',
      water_tanker: '💧',
      engineering_unit: '🏗️',
    };

    resources.forEach(r => {
      const hb = r.home_base;
      if (!hb) return;
      const pos = geoToCanvas(hb.latitude, hb.longitude);
      const icon = typeIcons[r.resource_type] || '📦';
      const status = r.status || 'available';

      // Status indicator ring
      const ringColor = status === 'available' ? 'rgba(0, 230, 118, 0.4)' :
                         status === 'dispatched' ? 'rgba(0, 229, 255, 0.4)' :
                         status === 'on_scene' ? 'rgba(255, 235, 59, 0.4)' :
                         status === 'maintenance' ? 'rgba(255, 255, 255, 0.15)' :
                         'rgba(255, 171, 0, 0.3)';
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, 12, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(12, 17, 32, 0.8)';
      ctx.fill();
      ctx.strokeStyle = ringColor;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Icon
      ctx.font = '12px serif';
      ctx.textAlign = 'center';
      ctx.fillText(icon, pos.x, pos.y + 5);

      // Name
      ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.font = '400 8px JetBrains Mono, monospace';
      ctx.fillText(r.callsign || r.name?.slice(0, 10) || '', pos.x, pos.y + 22);
    });
  }

  // ── Dispatch Animations ────────────────────────────────────────────────────

  function triggerDispatchAnimation(resourceId, zoneId) {
    const resource = state.resources.find(r => r.id === resourceId);
    const zone = state.zones.find(z => z.id === zoneId);
    if (!resource?.home_base || !zone?.boundary?.center) return;

    state.dispatchAnimations.push({
      from: { lat: resource.home_base.latitude, lng: resource.home_base.longitude },
      to: { lat: zone.boundary.center.latitude, lng: zone.boundary.center.longitude },
      progress: 0,
      speed: 0.008,
      color: '#00e5ff',
    });
  }

  function updateDispatchAnimations(ctx, w, h) {
    if (state.currentView !== 'map') return;

    state.dispatchAnimations = state.dispatchAnimations.filter(anim => {
      anim.progress += anim.speed;
      if (anim.progress >= 1) return false;

      // We need the same geoToCanvas transform. Simplified version:
      // (In production, extract the transform function. Here we re-derive.)
      // This is a simplified approach — just draw a moving dot across canvas.
      const fromX = 100 + anim.from.lng * 10;
      const fromY = 100 + anim.from.lat * 10;
      const toX = 100 + anim.to.lng * 10;
      const toY = 100 + anim.to.lat * 10;

      const x = fromX + (toX - fromX) * anim.progress;
      const y = fromY + (toY - fromY) * anim.progress;
      const alpha = 1 - Math.pow(anim.progress - 0.5, 2) * 4;

      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0, 229, 255, ${Math.max(0.2, alpha)})`;
      ctx.fill();

      // Trail
      for (let t = 0; t < 5; t++) {
        const tp = Math.max(0, anim.progress - t * 0.02);
        const tx = fromX + (toX - fromX) * tp;
        const ty = fromY + (toY - fromY) * tp;
        ctx.beginPath();
        ctx.arc(tx, ty, 2 - t * 0.3, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(0, 229, 255, ${0.3 - t * 0.05})`;
        ctx.fill();
      }

      return true;
    });
  }

  // ════════════════════════════════════════════════════════════════════════════
  // WebSocket
  // ════════════════════════════════════════════════════════════════════════════

  function connectWebSocket() {
    if (state.ws && state.ws.readyState <= WebSocket.OPEN) return;

    updateWsIndicator('reconnecting');
    try {
      state.ws = new WebSocket(WS_URL);
    } catch (err) {
      scheduleReconnect();
      return;
    }

    state.ws.onopen = () => {
      state.wsConnected = true;
      state.wsReconnectDelay = 1000;
      updateWsIndicator('connected');
      addEvent('info', 'WebSocket connected to cluster');
    };

    state.ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        handleWsEvent(msg);
      } catch (e) { /* ignore parse errors */ }
    };

    state.ws.onclose = () => {
      state.wsConnected = false;
      updateWsIndicator('disconnected');
      scheduleReconnect();
    };

    state.ws.onerror = () => {
      state.wsConnected = false;
      updateWsIndicator('disconnected');
    };
  }

  function scheduleReconnect() {
    if (state.wsReconnectTimer) clearTimeout(state.wsReconnectTimer);
    state.wsReconnectTimer = setTimeout(() => {
      state.wsReconnectDelay = Math.min(state.wsReconnectDelay * 2, 30000);
      connectWebSocket();
    }, state.wsReconnectDelay);
  }

  function updateWsIndicator(status) {
    const dot = document.getElementById('ws-status-dot');
    const text = document.getElementById('ws-status-text');
    dot.className = 'status-dot';
    if (status === 'connected') {
      dot.classList.add('status-dot--connected');
      text.textContent = 'WS Connected';
    } else if (status === 'reconnecting') {
      dot.classList.add('status-dot--reconnecting');
      text.textContent = 'Reconnecting…';
    } else {
      dot.classList.add('status-dot--disconnected');
      text.textContent = 'WS Disconnected';
    }
  }

  function handleWsEvent(msg) {
    const type = msg.type;
    const data = msg.data || {};

    switch (type) {
      case 'resource_registered':
        addEvent('resource', `Resource registered: ${data.name || data.resource_id}`);
        pollResources();
        break;
      case 'resource_dispatched':
        addEvent('dispatch', `✅ Resource ${data.resource_id} dispatched to zone ${data.zone_id} (log #${data.log_index})`);
        triggerDispatchAnimation(data.resource_id, data.zone_id);
        pollResources();
        break;
      case 'resource_dispatched_override':
        addEvent('dispatch', `⚠️ Override: ${data.resource_id} dispatched (was ${data.original_recommendation})`);
        triggerDispatchAnimation(data.resource_id, data.zone_id);
        pollResources();
        break;
      case 'dispatch_recommendation_queued':
        addEvent('recommend', `📋 Dispatch recommendation queued for review`);
        pollPendingDispatches();
        break;
      case 'pipeline_recommendation_ready':
        addEvent('recommend', `🤖 AI pipeline: ${data.resource_name || data.resource_id} → zone ${data.zone_id} (${(data.confidence * 100).toFixed(0)}% conf)`);
        pollPendingDispatches();
        break;
      case 'dispatch_rejected':
        addEvent('reject', `❌ Dispatch rejected by ${data.commander_id}: ${data.reason || 'no reason'}`);
        pollPendingDispatches();
        break;
      case 'zone_registered':
        addEvent('zone', `Zone registered: ${data.name || data.zone_id}`);
        pollResources(); // also refreshes zones
        break;
      default:
        addEvent('info', `Event: ${type}`);
    }
  }

  // ════════════════════════════════════════════════════════════════════════════
  // API Polling
  // ════════════════════════════════════════════════════════════════════════════

  async function pollClusterStatus() {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/cluster/status`);
      if (resp.ok) {
        const data = await resp.json();
        state.clusterStatus = data;
        updateClusterUI(data);
      }
    } catch (e) {
      updateClusterUI(null);
    }
    setTimeout(pollClusterStatus, POLL_CLUSTER_MS);
  }

  function updateClusterUI(data) {
    const chip = document.getElementById('cluster-state-chip');
    const dot = document.getElementById('cluster-state-dot');
    const label = document.getElementById('cluster-state-label');
    const termEl = document.getElementById('cluster-term');
    const logEl = document.getElementById('cluster-log-length');

    if (!data) {
      chip.className = 'status-chip status-chip--disconnected';
      dot.className = 'status-dot status-dot--disconnected';
      label.textContent = 'OFFLINE';
      termEl.textContent = '—';
      logEl.textContent = '—';
      return;
    }

    const st = (typeof data.state === 'string' ? data.state : data.state?.value) || 'unknown';
    label.textContent = `${(data.node_id || '?').toUpperCase()} · ${st.toUpperCase()}`;
    termEl.textContent = data.current_term ?? '—';
    logEl.textContent = data.log_length ?? '—';

    if (st === 'leader') {
      chip.className = 'status-chip status-chip--leader';
      dot.className = 'status-dot status-dot--connected';
    } else if (st === 'follower') {
      chip.className = 'status-chip status-chip--follower';
      dot.className = 'status-dot status-dot--connected';
    } else {
      chip.className = 'status-chip status-chip--disconnected';
      dot.className = 'status-dot status-dot--reconnecting';
    }

    // Update node states
    state.nodes.forEach(n => {
      if (n.id === data.node_id) {
        n.state = st;
        n.term = data.current_term || 0;
        n.logLength = data.log_length || 0;
      } else if (data.peers && data.peers.includes(n.id)) {
        // We know the peer exists; if we're leader we know they're followers
        if (st === 'leader' && n.state === 'offline') {
          n.state = 'follower';
        }
      }
    });

    // Update the leader_id info
    if (data.leader_id) {
      state.nodes.forEach(n => {
        if (n.id === data.leader_id && n.state === 'offline') n.state = 'follower';
        if (n.id === data.leader_id) n.state = 'leader';
      });
    }

    updateClusterTab();
  }

  function updateClusterTab() {
    const container = document.getElementById('cluster-node-list');
    container.innerHTML = '';
    state.nodes.forEach(n => {
      const dotClass = n.state === 'leader' ? 'node-status-card__dot--leader' :
                       n.state === 'follower' ? 'node-status-card__dot--follower' :
                       n.state === 'candidate' ? 'node-status-card__dot--candidate' :
                       'node-status-card__dot--offline';
      const card = document.createElement('div');
      card.className = 'node-status-card';
      card.innerHTML = `
        <div class="node-status-card__dot ${dotClass}"></div>
        <div class="node-status-card__info">
          <div class="node-status-card__name">${n.label}</div>
          <div class="node-status-card__meta">${n.agency} · ${(n.state || 'offline').toUpperCase()} · T:${n.term} L:${n.logLength}</div>
        </div>
      `;
      container.appendChild(card);
    });
  }

  async function pollPendingDispatches() {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/dispatch/pending`);
      if (resp.ok) {
        const data = await resp.json();
        state.pending = data.pending || [];
        renderDispatchQueue();
      }
    } catch (e) { /* cluster may be down */ }
    setTimeout(pollPendingDispatches, POLL_PENDING_MS);
  }

  async function pollResources() {
    try {
      const [resResp, zonesResp] = await Promise.all([
        fetch(`${API_BASE}/api/v1/resources`),
        fetch(`${API_BASE}/api/v1/zones`),
      ]);
      if (resResp.ok) {
        const data = await resResp.json();
        state.resources = data.resources || [];
      }
      if (zonesResp.ok) {
        const data = await zonesResp.json();
        state.zones = data.zones || [];
      }
    } catch (e) { /* cluster may be down */ }
    setTimeout(pollResources, POLL_RESOURCES_MS);
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Dispatch Queue UI
  // ════════════════════════════════════════════════════════════════════════════

  function renderDispatchQueue() {
    const container = document.getElementById('dispatch-queue');
    const empty = document.getElementById('dispatch-empty');
    const badge = document.getElementById('dispatch-count');

    if (state.pending.length === 0) {
      container.innerHTML = '';
      container.appendChild(empty);
      empty.style.display = '';
      badge.style.display = 'none';
      return;
    }

    empty.style.display = 'none';
    badge.style.display = '';
    badge.textContent = state.pending.length;

    // Build cards
    container.innerHTML = '';
    state.pending.forEach(p => {
      if (p.resolved) return;

      const conf = p.ai_confidence || 0;
      const confClass = conf >= 0.7 ? 'confidence--high' : conf >= 0.4 ? 'confidence--medium' : 'confidence--low';
      const expiresAt = new Date(p.expires_at);
      const remaining = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000));

      const card = document.createElement('div');
      card.className = 'dispatch-card';
      card.innerHTML = `
        <div class="dispatch-card__header">
          <span class="dispatch-card__resource">${p.resource_name || p.resource_id}</span>
          <span class="dispatch-card__confidence ${confClass}">${(conf * 100).toFixed(0)}%</span>
        </div>
        <div class="dispatch-card__zone">
          → <strong>${p.zone_name || p.zone_id}</strong> · Incident ${p.incident_id}
        </div>
        ${p.ai_reasoning ? `<div class="dispatch-card__zone" style="font-style: italic; opacity: 0.7;">"${p.ai_reasoning.slice(0, 120)}${p.ai_reasoning.length > 120 ? '…' : ''}"</div>` : ''}
        <div class="dispatch-card__timer">⏱ ${remaining}s remaining</div>
        <div class="dispatch-card__actions">
          <button class="btn btn--confirm" data-action="confirm" data-id="${p.id}" id="confirm-${p.id}">Confirm Dispatch</button>
          <button class="btn btn--reject" data-action="reject" data-id="${p.id}" id="reject-${p.id}">Reject</button>
        </div>
      `;
      container.appendChild(card);

      // Attach event handlers
      card.querySelector('[data-action="confirm"]').addEventListener('click', () => confirmDispatch(p.id));
      card.querySelector('[data-action="reject"]').addEventListener('click', () => rejectDispatch(p.id));
    });
  }

  async function confirmDispatch(confirmationId) {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/dispatch/${confirmationId}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          commander_id: 'dashboard-commander',
          commander_agency_id: 'dashboard',
          notes: 'Confirmed via Salus Command Dashboard',
        }),
      });
      if (resp.ok) {
        addEvent('dispatch', '✅ Dispatch confirmed via dashboard');
        pollPendingDispatches();
      } else {
        const err = await resp.json().catch(() => ({}));
        addEvent('reject', `❌ Confirm failed: ${err.detail || resp.statusText}`);
      }
    } catch (e) {
      addEvent('reject', `❌ Confirm error: ${e.message}`);
    }
  }

  async function rejectDispatch(confirmationId) {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/dispatch/${confirmationId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          commander_id: 'dashboard-commander',
          commander_agency_id: 'dashboard',
          reason: 'Rejected via Salus Command Dashboard',
        }),
      });
      if (resp.ok) {
        addEvent('reject', '❌ Dispatch rejected via dashboard');
        pollPendingDispatches();
      }
    } catch (e) {
      addEvent('reject', `❌ Reject error: ${e.message}`);
    }
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Event Log
  // ════════════════════════════════════════════════════════════════════════════

  function addEvent(type, text) {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

    state.events.unshift({ type, text, time: timeStr });
    if (state.events.length > MAX_EVENTS) state.events.pop();
    state.eventCount++;

    renderEventLog();

    // Update badge
    const badge = document.getElementById('events-count');
    badge.style.display = '';
    badge.textContent = Math.min(state.eventCount, 99);
  }

  function renderEventLog() {
    const container = document.getElementById('event-log');
    let empty = document.getElementById('events-empty');

    if (!empty) {
      empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.id = 'events-empty';
      empty.innerHTML = `
        <div class="empty-state__icon">📡</div>
        <div class="empty-state__text">Waiting for WebSocket events from the cluster…</div>
      `;
    }

    if (state.events.length === 0) {
      container.innerHTML = '';
      container.appendChild(empty);
      empty.style.display = '';
      return;
    }

    // Only re-render if the container child count doesn't match
    // (for performance, avoid full re-render every time)
    while (container.children.length > state.events.length) {
      container.removeChild(container.lastChild);
    }

    container.innerHTML = '';
    const badgeMap = {
      dispatch: 'event-entry__badge--dispatch',
      recommend: 'event-entry__badge--recommend',
      reject: 'event-entry__badge--reject',
      zone: 'event-entry__badge--zone',
      resource: 'event-entry__badge--resource',
      cluster: 'event-entry__badge--cluster',
      info: 'event-entry__badge--info',
    };

    state.events.slice(0, 50).forEach(evt => {
      const el = document.createElement('div');
      el.className = 'event-entry';
      el.innerHTML = `
        <div class="event-entry__badge ${badgeMap[evt.type] || 'event-entry__badge--info'}"></div>
        <div class="event-entry__content">
          <div class="event-entry__text">${escapeHtml(evt.text)}</div>
          <div class="event-entry__time">${evt.time}</div>
        </div>
      `;
      container.appendChild(el);
    });
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Tabs
  // ════════════════════════════════════════════════════════════════════════════

  function setupTabs() {
    const tabs = document.querySelectorAll('.right-panel__tab');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const tabName = tab.dataset.tab;
        document.getElementById('panel-dispatch').style.display = tabName === 'dispatch' ? '' : 'none';
        document.getElementById('panel-events').style.display = tabName === 'events' ? '' : 'none';
        document.getElementById('panel-cluster').style.display = tabName === 'cluster' ? '' : 'none';
      });
    });
  }

  // ════════════════════════════════════════════════════════════════════════════
  // View Toggle
  // ════════════════════════════════════════════════════════════════════════════

  function setupViewToggle() {
    const btns = document.querySelectorAll('.view-toggle');
    btns.forEach(btn => {
      btn.addEventListener('click', () => {
        btns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.currentView = btn.dataset.view;
      });
    });
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Drag & Drop
  // ════════════════════════════════════════════════════════════════════════════

  function setupDragDrop() {
    const cards = document.querySelectorAll('.entity-card[draggable="true"]');
    const canvasArea = document.getElementById('canvas-area');
    const dropHint = document.getElementById('canvas-drop-hint');

    cards.forEach(card => {
      card.addEventListener('dragstart', (e) => {
        card.classList.add('dragging');
        e.dataTransfer.setData('application/json', JSON.stringify({
          type: card.dataset.entityType,
          id: card.dataset.entityId,
          resourceType: card.dataset.resourceType,
          disasterType: card.dataset.disasterType,
        }));
        e.dataTransfer.effectAllowed = 'copy';
      });

      card.addEventListener('dragend', () => {
        card.classList.remove('dragging');
        dropHint.classList.remove('visible');
      });
    });

    canvasArea.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      dropHint.classList.add('visible');
    });

    canvasArea.addEventListener('dragleave', () => {
      dropHint.classList.remove('visible');
    });

    canvasArea.addEventListener('drop', async (e) => {
      e.preventDefault();
      dropHint.classList.remove('visible');

      let data;
      try {
        data = JSON.parse(e.dataTransfer.getData('application/json'));
      } catch { return; }

      const rect = canvasArea.getBoundingClientRect();
      const dropX = e.clientX - rect.left;
      const dropY = e.clientY - rect.top;

      await handleEntityDrop(data, dropX, dropY);
    });
  }

  async function handleEntityDrop(data, x, y) {
    if (data.type === 'icp') {
      addEvent('cluster', `Dropped ICP node: ${data.id}`);
      // Mark the node as alive in local state (follower by default)
      const node = state.nodes.find(n => n.id === data.id);
      if (node && node.state === 'offline') {
        node.state = 'follower';
      }
    } else if (data.type === 'resource') {
      addEvent('resource', `Dropping resource: ${data.resourceType}`);
      // Generate a resource and try to register it via API
      const resourcePayload = {
        resource: {
          name: `${data.resourceType}-${Date.now().toString(36)}`,
          callsign: `${data.resourceType.slice(0, 3).toUpperCase()}-${Math.floor(Math.random() * 99)}`,
          resource_type: data.resourceType,
          owning_agency_id: 'dashboard-agency',
          home_base: { latitude: 28.56 + Math.random() * 0.05, longitude: 77.2 + Math.random() * 0.05 },
          status: 'available',
          capabilities: { personnel_count: 4 },
        },
      };
      try {
        const resp = await fetch(`${API_BASE}/api/v1/resources`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(resourcePayload),
        });
        if (resp.ok) {
          addEvent('resource', `✅ Resource registered successfully`);
          pollResources();
        } else {
          const err = await resp.json().catch(() => ({}));
          addEvent('resource', `⚠️ Registration failed: ${err.detail || resp.statusText}`);
        }
      } catch (e) {
        addEvent('resource', `❌ API unreachable: ${e.message}`);
      }
    } else if (data.type === 'disaster') {
      addEvent('zone', `🌋 Disaster triggered: ${data.disasterType}`);
      // Try to run the pipeline
      const pipelinePayload = {
        incident_id: `inc-${Date.now().toString(36)}`,
        zone_id: state.zones.length > 0 ? state.zones[Math.floor(Math.random() * state.zones.length)].id : 'zone-001',
        incident_description: getDisasterDescription(data.disasterType),
      };
      try {
        const resp = await fetch(`${API_BASE}/api/v1/dispatch/run-pipeline`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(pipelinePayload),
        });
        if (resp.ok) {
          const result = await resp.json();
          addEvent('recommend', `🤖 Pipeline complete! Confidence: ${((result.dispatch_order?.decision_confidence || 0) * 100).toFixed(0)}%`);
          pollPendingDispatches();
        } else {
          const err = await resp.json().catch(() => ({}));
          addEvent('reject', `Pipeline error: ${err.detail || resp.statusText}`);
        }
      } catch (e) {
        addEvent('reject', `Pipeline unreachable: ${e.message}`);
      }
    }
  }

  function getDisasterDescription(type) {
    const descriptions = {
      earthquake: 'A massive 7.2 magnitude earthquake has struck the region. Multiple buildings have collapsed in the commercial district. Reports of people trapped under rubble. Main access bridge has collapsed, creating severe access issues.',
      flood: 'Flash flooding has inundated the riverside district. Water levels rising rapidly at 2 meters per hour. Approximately 500 residents stranded on rooftops. Several roads completely submerged. Evacuation urgently needed.',
      fire: 'Large-scale structural fire engulfing a commercial warehouse complex. Fire spreading to adjacent residential buildings. Thick toxic smoke visible for kilometers. Multiple casualties reported. Fire department requests additional resources.',
      chemical: 'Industrial chemical spill at the manufacturing plant. Toxic fumes spreading downwind toward residential area. Approximately 2000 residents in evacuation zone. HAZMAT containment required. Multiple workers injured.',
    };
    return descriptions[type] || descriptions.earthquake;
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Bootstrap
  // ════════════════════════════════════════════════════════════════════════════

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
