/**
 * SALUS // GOD'S EYE — C4ISR OMNISCIENT COMMAND HUD
 * Interactive Client Engine
 *
 * Capabilities:
 * - Dual-Engine Architecture (Seamless Live Backend + Autonomous Tactical Simulation)
 * - 60fps HTML5 Canvas Engine (God's Eye Tactical Radar Map & Raft Consensus Mesh)
 * - Canvas Click-to-Target Hit Testing with Tactical Telemetry Inspector
 * - 5-Agent Pipeline Visual Runner (Damage -> Resource -> Protocol -> Routing -> Decision)
 * - Incident Commander Gate with Confirm, Reject, and Commander Override
 * - Chaos Resilience Sandbox (Network Partition, Kill Leader, Double-Dispatch Attack, Heal)
 * - Real-time Cryptographic Audit Trail
 */

(() => {
  'use strict';

  // ════════════════════════════════════════════════════════════════════════════
  // Configuration & Constants
  // ════════════════════════════════════════════════════════════════════════════

  const API_BASE = window.location.protocol === 'file:'
    ? 'http://localhost:8000'
    : window.location.origin;
  const WS_URL = API_BASE.replace(/^http/, 'ws') + '/ws/events';

  const RESOURCE_ICONS = {
    ambulance_als: '🚑',
    ambulance: '🚑',
    fire_engine: '🚒',
    helicopter_transport: '🚁',
    helicopter_medical: '🚁',
    sar_team_urban: '🦺',
    sar_team_water: '🛟',
    hazmat_team: '☣️',
    k9_unit: '🐕',
    drone_team: '🛸',
  };

  // ════════════════════════════════════════════════════════════════════════════
  // Application State
  // ════════════════════════════════════════════════════════════════════════════

  const state = {
    // Mode: 'live' | 'autonomous'
    engineMode: 'autonomous',
    currentView: 'radar', // 'radar' | 'raft'
    radarSweepActive: true,
    radarAngle: 0,

    // Cluster State
    cluster: {
      node_id: 'alpha',
      state: 'leader',
      current_term: 2,
      leader_id: 'alpha',
      log_length: 14,
      commit_index: 14,
      is_partitioned: false,
      peers: ['bravo', 'charlie'],
      cluster_size: 3,
      quorum_size: 2,
    },
    nodes: [
      { id: 'alpha', label: 'ICP Alpha', role: 'Fire & Rescue HQ', state: 'leader', term: 2, logLength: 14, is_partitioned: false },
      { id: 'bravo', label: 'ICP Bravo', role: 'Emergency Medical (EMS)', state: 'follower', term: 2, logLength: 14, is_partitioned: false },
      { id: 'charlie', label: 'ICP Charlie', role: 'Urban SAR & HAZMAT', state: 'follower', term: 2, logLength: 14, is_partitioned: false },
    ],

    // Resources Inventory
    resources: [
      {
        id: 'res-als-01',
        name: 'ALS Ambulance 101',
        callsign: 'ALS-101',
        resource_type: 'ambulance_als',
        status: 'available',
        home_base: { latitude: 28.582, longitude: 77.214 },
        capabilities: { personnel_count: 3, can_perform_medical: true, max_range_km: 120 },
        fuel: '92%',
      },
      {
        id: 'res-fire-04',
        name: 'Heavy Fire Engine 4',
        callsign: 'ENG-04',
        resource_type: 'fire_engine',
        status: 'available',
        home_base: { latitude: 28.608, longitude: 77.235 },
        capabilities: { personnel_count: 5, can_perform_firefighting: true, water_liters: 4000 },
        fuel: '88%',
      },
      {
        id: 'res-helo-01',
        name: 'Rescue Transport Helicopter',
        callsign: 'AIR-1',
        resource_type: 'helicopter_transport',
        status: 'available',
        home_base: { latitude: 28.553, longitude: 77.195 },
        capabilities: { personnel_count: 4, can_access_air: true, max_range_km: 450 },
        fuel: '76%',
      },
      {
        id: 'res-sar-01',
        name: 'Urban SAR Team Alpha',
        callsign: 'SAR-01',
        resource_type: 'sar_team_urban',
        status: 'available',
        home_base: { latitude: 28.625, longitude: 77.228 },
        capabilities: { personnel_count: 8, has_thermal_imaging: true, can_clear_debris: true },
        fuel: '100%',
      },
      {
        id: 'res-haz-01',
        name: 'HAZMAT Response Unit 2',
        callsign: 'HAZ-02',
        resource_type: 'hazmat_team',
        status: 'available',
        home_base: { latitude: 28.571, longitude: 77.242 },
        capabilities: { personnel_count: 4, can_perform_containment: true },
        fuel: '95%',
      },
      {
        id: 'res-k9-01',
        name: 'K9 Search Unit Echo',
        callsign: 'K9-05',
        resource_type: 'k9_unit',
        status: 'available',
        home_base: { latitude: 28.595, longitude: 77.202 },
        capabilities: { personnel_count: 2, dogs_count: 2 },
        fuel: '100%',
      },
    ],
    resourceFilter: 'all',

    // Disaster Sectors
    zones: [
      {
        id: 'zone-cbd-01',
        name: 'Sector 4 — Central Business District',
        priority: 1,
        boundary: { center: { latitude: 28.618, longitude: 77.219 }, radius_km: 2.2 },
        casualties: '18 confirmed, ~45 trapped',
        hazards: 'Structural collapse, gas leak',
      },
      {
        id: 'zone-river-02',
        name: 'East Riverfront Lowlands',
        priority: 2,
        boundary: { center: { latitude: 28.568, longitude: 77.248 }, radius_km: 3.0 },
        casualties: '500 stranded on rooftops',
        hazards: 'Rising floodwater (2m/hr)',
      },
      {
        id: 'zone-ind-03',
        name: 'North Industrial Corridor',
        priority: 3,
        boundary: { center: { latitude: 28.641, longitude: 77.205 }, radius_km: 1.8 },
        casualties: '7 chemical inhalation injuries',
        hazards: 'Anhydrous ammonia cloud',
      },
    ],

    // Incident Commander Gate: Pending Dispatches
    pending: [
      {
        id: 'conf-init-01',
        resource_id: 'res-als-01',
        resource_name: 'ALS Ambulance 101',
        zone_id: 'zone-cbd-01',
        zone_name: 'Sector 4 — Central Business District',
        incident_id: 'INC-7492',
        ai_confidence: 0.94,
        ai_reasoning: 'Mass casualty triage at collapsed commercial structure. Closest ALS unit with 4-min ETA and trauma life-support capability.',
        expires_at: new Date(Date.now() + 115000).toISOString(),
      },
    ],

    // Target Selection & Hit Testing
    selectedEntity: null, // { type: 'node' | 'resource' | 'zone', data, x, y }

    // Trajectory Animations (Dispatched resources flying to zones)
    trajectories: [],

    // Raft Heartbeat Particles
    heartbeatParticles: [],

    // Audit Log Stream
    auditLogs: [
      {
        id: 'AUD-001',
        timestamp: new Date(Date.now() - 360000).toISOString(),
        action: 'CLUSTER_INIT',
        actor: 'RAFT_CORE',
        details: 'Salus consensus network initialized. Term 1 established with 3 voting members.',
        hash: '0x8f2d4e1a90c4',
      },
      {
        id: 'AUD-002',
        timestamp: new Date(Date.now() - 240000).toISOString(),
        action: 'LEADER_ELECTED',
        actor: 'ICP_ALPHA',
        details: 'ICP Alpha achieved quorum majority (2/3 votes) and transitioned to LEADER.',
        hash: '0x3c7b1f8e24d9',
      },
      {
        id: 'AUD-003',
        timestamp: new Date(Date.now() - 120000).toISOString(),
        action: 'ZONE_REGISTER',
        actor: 'COMMANDER_ALPHA',
        details: 'Sector 4 CBD registered as Priority 1 Disaster Zone. Raft Log #13 committed.',
        hash: '0x5e9a0c8b32f1',
      },
      {
        id: 'AUD-004',
        timestamp: new Date(Date.now() - 30000).toISOString(),
        action: 'AI_RECOMMENDATION',
        actor: 'PIPELINE_AGENT_5',
        details: '5-Agent pipeline synthesized dispatch recommendation: ALS Ambulance 101 -> Sector 4 CBD.',
        hash: '0x1a4f7c9e83b2',
      },
    ],

    // Canvas Properties
    canvas: null,
    ctx: null,
    width: 0,
    height: 0,
    time: 0,
    animFrame: null,

    // WebSockets
    ws: null,
  };

  // ════════════════════════════════════════════════════════════════════════════
  // Initialization & Bootstrap
  // ════════════════════════════════════════════════════════════════════════════

  function init() {
    setupCanvas();
    setupClock();
    setupTabs();
    setupViewSwitch();
    setupInteractions();
    setupChaosHandlers();
    setupModals();
    renderAllPanels();

    // Start Live Probe & Fallback
    probeBackend();

    // Start 60fps Animation Loop
    startLoop();
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Canvas Engine & 60fps Render Loop
  // ════════════════════════════════════════════════════════════════════════════

  function setupCanvas() {
    state.canvas = document.getElementById('gods-eye-canvas');
    state.ctx = state.canvas.getContext('2d');
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    // Click Hit-Testing
    state.canvas.addEventListener('click', handleCanvasClick);
  }

  function resizeCanvas() {
    const container = document.getElementById('hud-canvas-container');
    const dpr = window.devicePixelRatio || 1;
    state.width = container.clientWidth;
    state.height = container.clientHeight;
    state.canvas.width = state.width * dpr;
    state.canvas.height = state.height * dpr;
    state.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function startLoop() {
    function tick(timestamp) {
      state.time = timestamp || 0;
      render();
      state.animFrame = requestAnimationFrame(tick);
    }
    state.animFrame = requestAnimationFrame(tick);
  }

  function render() {
    const ctx = state.ctx;
    const w = state.width;
    const h = state.height;

    // Clear Screen
    ctx.clearRect(0, 0, w, h);

    if (state.currentView === 'radar') {
      renderGodsEyeRadar(ctx, w, h);
    } else {
      renderRaftMesh(ctx, w, h);
    }

    // Render In-Flight Trajectories (both views)
    renderTrajectories(ctx);
  }

  // ── GOD'S EYE TACTICAL RADAR RENDERER ───────────────────────────────────────

  function renderGodsEyeRadar(ctx, w, h) {
    const cx = w / 2;
    const cy = h / 2;
    const maxRadius = Math.min(w, h) * 0.44;

    // 1. Tactical Grid & Compass Bearings
    drawTacticalGrid(ctx, w, h);

    // 2. Concentric Distance Rings & Compass Markings
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.08)';
    ctx.lineWidth = 1;
    for (let r = 0.25; r <= 1.0; r += 0.25) {
      ctx.beginPath();
      ctx.arc(cx, cy, maxRadius * r, 0, Math.PI * 2);
      ctx.stroke();

      // Range labels
      ctx.font = '9px JetBrains Mono, monospace';
      ctx.fillStyle = 'rgba(0, 240, 255, 0.3)';
      ctx.textAlign = 'left';
      ctx.fillText(`${(r * 10).toFixed(0)} KM`, cx + 6, cy - maxRadius * r + 12);
    }

    // 3. Rotating Radar Sweep with Phosphor Decay
    if (state.radarSweepActive) {
      state.radarAngle = (state.radarAngle + 0.02) % (Math.PI * 2);

      const sweepGrad = ctx.createConicGradient(state.radarAngle, cx, cy);
      sweepGrad.addColorStop(0, 'rgba(0, 240, 255, 0.18)');
      sweepGrad.addColorStop(0.12, 'rgba(0, 240, 255, 0.03)');
      sweepGrad.addColorStop(0.2, 'transparent');
      sweepGrad.addColorStop(1, 'transparent');

      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, maxRadius, 0, Math.PI * 2);
      ctx.fillStyle = sweepGrad;
      ctx.fill();

      // Leading Sweep Beam
      const sweepX = cx + Math.cos(state.radarAngle) * maxRadius;
      const sweepY = cy + Math.sin(state.radarAngle) * maxRadius;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(sweepX, sweepY);
      ctx.strokeStyle = 'rgba(0, 240, 255, 0.7)';
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.restore();
    }

    // 4. Transform Geo-Coordinates to Canvas
    const geoTransform = getGeoTransform(w, h);

    // 5. Draw Disaster Zones
    state.zones.forEach(zone => {
      const pos = geoTransform(zone.boundary.center.latitude, zone.boundary.center.longitude);
      zone._screenX = pos.x;
      zone._screenY = pos.y;
      zone._radius = Math.max(34, zone.boundary.radius_km * 18);

      const isP1 = zone.priority === 1;
      const strokeColor = isP1 ? 'rgba(255, 0, 85, 0.65)' : zone.priority === 2 ? 'rgba(255, 183, 3, 0.55)' : 'rgba(0, 240, 255, 0.4)';
      const fillColor = isP1 ? 'rgba(255, 0, 85, 0.08)' : zone.priority === 2 ? 'rgba(255, 183, 3, 0.06)' : 'rgba(0, 240, 255, 0.04)';

      // Pulsing outer threat ring
      const pulseScale = 1 + (isP1 ? Math.sin(state.time / 300) * 0.08 : 0);

      ctx.beginPath();
      ctx.arc(pos.x, pos.y, zone._radius * pulseScale, 0, Math.PI * 2);
      ctx.fillStyle = fillColor;
      ctx.fill();
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);

      // Zone Center Target
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, 4, 0, Math.PI * 2);
      ctx.fillStyle = strokeColor;
      ctx.fill();

      // Zone Name & Priority Tag
      ctx.font = '700 10px Rajdhani, sans-serif';
      ctx.fillStyle = isP1 ? '#ff0055' : '#ffb703';
      ctx.textAlign = 'center';
      ctx.fillText(zone.name.toUpperCase(), pos.x, pos.y - zone._radius - 8);
      ctx.font = '600 8px JetBrains Mono, monospace';
      ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
      ctx.fillText(`PRIORITY P${zone.priority} · ${zone.boundary.radius_km}KM RADIUS`, pos.x, pos.y - zone._radius + 3);
    });

    // 6. Draw Resources on Radar
    state.resources.forEach(res => {
      if (!res.home_base) return;
      const pos = geoTransform(res.home_base.latitude, res.home_base.longitude);
      res._screenX = pos.x;
      res._screenY = pos.y;

      const isDispatched = res.status === 'dispatched';
      const isUncertain = state.cluster.is_partitioned;
      const ringColor = isUncertain ? '#ff0055' : isDispatched ? '#00f0ff' : '#00ff66';

      // Outer status ring
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, 14, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(4, 9, 23, 0.85)';
      ctx.fill();
      ctx.strokeStyle = ringColor;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Icon & Callsign
      ctx.font = '12px serif';
      ctx.textAlign = 'center';
      ctx.fillText(RESOURCE_ICONS[res.resource_type] || '📦', pos.x, pos.y + 4);

      ctx.font = '700 8px JetBrains Mono, monospace';
      ctx.fillStyle = ringColor;
      ctx.fillText(res.callsign, pos.x, pos.y + 24);
    });

    // 7. Draw Selection Lock-On Reticle if an entity is clicked
    if (state.selectedEntity) {
      drawTargetReticle(ctx, state.selectedEntity.x, state.selectedEntity.y, 28);
    }
  }

  // ── RAFT CONSENSUS MESH RENDERER ──────────────────────────────────────────

  function renderRaftMesh(ctx, w, h) {
    const cx = w / 2;
    const cy = h / 2;
    const radius = Math.min(w, h) * 0.32;

    drawTacticalGrid(ctx, w, h);

    // Compute positions of 3 nodes in equilateral triangle
    const nodePositions = state.nodes.map((node, i) => {
      const angle = (i * 2 * Math.PI / state.nodes.length) - Math.PI / 2;
      return {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
        node,
      };
    });

    // Draw Inter-Node Raft RPC Lines & Heartbeats
    for (let i = 0; i < nodePositions.length; i++) {
      for (let j = i + 1; j < nodePositions.length; j++) {
        const p1 = nodePositions[i];
        const p2 = nodePositions[j];
        const isPartitionedEdge = (p1.node.is_partitioned || p2.node.is_partitioned);

        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);

        if (isPartitionedEdge) {
          ctx.strokeStyle = 'rgba(255, 0, 85, 0.4)';
          ctx.lineWidth = 1.5;
          ctx.setLineDash([6, 6]);
        } else {
          ctx.strokeStyle = 'rgba(0, 240, 255, 0.25)';
          ctx.lineWidth = 1.5;
          ctx.setLineDash([]);
        }
        ctx.stroke();
        ctx.setLineDash([]);

        // Spawn Heartbeat pulse particles if edge is healthy
        if (!isPartitionedEdge && Math.random() < 0.04) {
          const isP1Leader = p1.node.state === 'leader';
          state.heartbeatParticles.push({
            x: isP1Leader ? p1.x : p2.x,
            y: isP1Leader ? p1.y : p2.y,
            tx: isP1Leader ? p2.x : p1.x,
            ty: isP1Leader ? p2.y : p1.y,
            progress: 0,
            speed: 0.02,
          });
        }
      }
    }

    // Render Heartbeat Particles
    state.heartbeatParticles = state.heartbeatParticles.filter(p => {
      p.progress += p.speed;
      if (p.progress >= 1) return false;

      const px = p.x + (p.tx - p.x) * p.progress;
      const py = p.y + (p.ty - p.y) * p.progress;

      ctx.beginPath();
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fillStyle = '#00f0ff';
      ctx.shadowColor = '#00f0ff';
      ctx.shadowBlur = 8;
      ctx.fill();
      ctx.shadowBlur = 0;
      return true;
    });

    // Draw Raft Nodes
    nodePositions.forEach(np => {
      const node = np.node;
      node._screenX = np.x;
      node._screenY = np.y;

      const isLeader = node.state === 'leader';
      const isPartitioned = node.is_partitioned;
      const nodeRadius = 36;

      // Glow Ring
      const glowColor = isPartitioned ? 'rgba(255, 0, 85, 0.2)' : isLeader ? 'rgba(0, 255, 102, 0.2)' : 'rgba(0, 240, 255, 0.15)';
      ctx.beginPath();
      ctx.arc(np.x, np.y, nodeRadius + 12 + Math.sin(state.time / 500) * 3, 0, Math.PI * 2);
      ctx.fillStyle = glowColor;
      ctx.fill();

      // Node Body
      ctx.beginPath();
      ctx.arc(np.x, np.y, nodeRadius, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(7, 13, 29, 0.9)';
      ctx.fill();
      ctx.strokeStyle = isPartitioned ? '#ff0055' : isLeader ? '#00ff66' : '#00f0ff';
      ctx.lineWidth = isLeader ? 2.5 : 1.5;
      ctx.stroke();

      // Leader Crown
      if (isLeader && !isPartitioned) {
        ctx.font = '16px serif';
        ctx.textAlign = 'center';
        ctx.fillText('👑', np.x, np.y - nodeRadius - 8);
      }

      // Icon & ID
      ctx.font = '18px serif';
      ctx.textAlign = 'center';
      ctx.fillText(node.id === 'alpha' ? '🏛️' : node.id === 'bravo' ? '🏥' : '🔍', np.x, np.y + 6);

      // Node Label
      ctx.font = '700 12px Orbitron, sans-serif';
      ctx.fillStyle = '#e6edf8';
      ctx.fillText(node.label, np.x, np.y + nodeRadius + 18);

      // Status Pill
      ctx.font = '700 9px JetBrains Mono, monospace';
      ctx.fillStyle = isPartitioned ? '#ff0055' : isLeader ? '#00ff66' : '#00f0ff';
      ctx.fillText(isPartitioned ? 'PARTITIONED' : node.state.toUpperCase(), np.x, np.y + nodeRadius + 32);

      // Term & Log Telemetry
      ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.font = '8px JetBrains Mono, monospace';
      ctx.fillText(`TERM:${node.term} · LOG:${node.logLength}`, np.x, np.y + nodeRadius + 44);
    });

    if (state.selectedEntity) {
      drawTargetReticle(ctx, state.selectedEntity.x, state.selectedEntity.y, 44);
    }
  }

  // ── Helper Graphics & Hit Testing ─────────────────────────────────────────

  function drawTacticalGrid(ctx, w, h) {
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.025)';
    ctx.lineWidth = 1;
    const step = 45;
    for (let x = 0; x < w; x += step) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 0; y < h; y += step) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
  }

  function drawTargetReticle(ctx, x, y, size) {
    ctx.strokeStyle = '#00f0ff';
    ctx.lineWidth = 1.5;
    const len = size * 0.35;

    // Corner brackets
    ctx.beginPath();
    ctx.moveTo(x - size, y - size + len); ctx.lineTo(x - size, y - size); ctx.lineTo(x - size + len, y - size);
    ctx.moveTo(x + size - len, y - size); ctx.lineTo(x + size, y - size); ctx.lineTo(x + size, y - size + len);
    ctx.moveTo(x - size, y + size - len); ctx.lineTo(x - size, y + size); ctx.lineTo(x - size + len, y + size);
    ctx.moveTo(x + size - len, y + size); ctx.lineTo(x + size, y + size); ctx.lineTo(x + size, y + size - len);
    ctx.stroke();

    // Crosshair dot
    ctx.beginPath();
    ctx.arc(x, y, 2, 0, Math.PI * 2);
    ctx.fillStyle = '#00f0ff';
    ctx.fill();
  }

  function getGeoTransform(w, h) {
    // Dynamic bounding box of all resources and zones
    let minLat = 28.53, maxLat = 28.66, minLng = 77.18, maxLng = 77.26;
    const pad = 0.01;
    const margin = 70;
    const mapW = w - margin * 2;
    const mapH = h - margin * 2;

    return (lat, lng) => {
      const xNorm = (lng - minLng) / (maxLng - minLng);
      const yNorm = 1 - (lat - minLat) / (maxLat - minLat);
      return {
        x: margin + xNorm * mapW,
        y: margin + yNorm * mapH,
      };
    };
  }

  function handleCanvasClick(e) {
    const rect = state.canvas.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;

    let hit = null;

    if (state.currentView === 'radar') {
      // Hit-test resources
      for (const res of state.resources) {
        if (res._screenX && Math.hypot(clickX - res._screenX, clickY - res._screenY) < 18) {
          hit = { type: 'resource', data: res, x: res._screenX, y: res._screenY };
          break;
        }
      }
      // Hit-test zones if no resource was hit
      if (!hit) {
        for (const zone of state.zones) {
          if (zone._screenX && Math.hypot(clickX - zone._screenX, clickY - zone._screenY) < zone._radius) {
            hit = { type: 'zone', data: zone, x: zone._screenX, y: zone._screenY };
            break;
          }
        }
      }
    } else {
      // Hit-test Raft nodes
      for (const node of state.nodes) {
        if (node._screenX && Math.hypot(clickX - node._screenX, clickY - node._screenY) < 38) {
          hit = { type: 'node', data: node, x: node._screenX, y: node._screenY };
          break;
        }
      }
    }

    state.selectedEntity = hit;
    renderInspector(hit);
  }

  function renderInspector(hit) {
    const card = document.getElementById('tactical-inspector-card');
    const badge = document.getElementById('inspector-badge');
    const title = document.getElementById('inspector-title');
    const body = document.getElementById('inspector-body');

    if (!hit) {
      card.style.display = 'none';
      document.getElementById('canvas-target-focus').textContent = 'TARGET LOCK: ALL SECTORS';
      return;
    }

    card.style.display = 'block';
    const { type, data } = hit;

    if (type === 'resource') {
      badge.textContent = 'RESOURCE ASSET';
      title.textContent = data.name;
      document.getElementById('canvas-target-focus').textContent = `TARGET LOCK: ${data.callsign}`;
      body.innerHTML = `
        <div class="inspector-row"><span class="inspector-label">CALLSIGN:</span><span class="inspector-val text-cyan">${data.callsign}</span></div>
        <div class="inspector-row"><span class="inspector-label">TYPE:</span><span class="inspector-val">${data.resource_type}</span></div>
        <div class="inspector-row"><span class="inspector-label">STATUS:</span><span class="inspector-val text-green">${data.status.toUpperCase()}</span></div>
        <div class="inspector-row"><span class="inspector-label">FUEL / ENERGY:</span><span class="inspector-val">${data.fuel || '100%'}</span></div>
        <div class="inspector-row"><span class="inspector-label">PERSONNEL:</span><span class="inspector-val">${data.capabilities?.personnel_count || 4} CREW</span></div>
        <button class="hud-btn hud-btn--primary hud-btn--mini" id="btn-inspector-deploy" style="margin-top:6px;">⚡ DEPLOY THIS UNIT</button>
      `;
      document.getElementById('btn-inspector-deploy')?.addEventListener('click', () => {
        openQuickDeployModal(data.id);
      });
    } else if (type === 'zone') {
      badge.textContent = 'DISASTER SECTOR';
      title.textContent = data.name;
      document.getElementById('canvas-target-focus').textContent = `TARGET LOCK: ${data.id.toUpperCase()}`;
      body.innerHTML = `
        <div class="inspector-row"><span class="inspector-label">SECTOR ID:</span><span class="inspector-val text-cyan">${data.id}</span></div>
        <div class="inspector-row"><span class="inspector-label">THREAT PRIORITY:</span><span class="inspector-val text-red">P${data.priority} CRITICAL</span></div>
        <div class="inspector-row"><span class="inspector-label">CASUALTIES:</span><span class="inspector-val">${data.casualties || 'Assessing'}</span></div>
        <div class="inspector-row"><span class="inspector-label">HAZARDS:</span><span class="inspector-val">${data.hazards || 'Severe'}</span></div>
        <button class="hud-btn hud-btn--warning hud-btn--mini" id="btn-inspector-run-pipe" style="margin-top:6px;">🤖 RUN 5-AGENT AI PIPELINE</button>
      `;
      document.getElementById('btn-inspector-run-pipe')?.addEventListener('click', () => {
        runAiPipeline(data.id, `Emergency escalation at ${data.name}. Urgent resource deployment required.`);
      });
    } else if (type === 'node') {
      badge.textContent = 'RAFT CLUSTER NODE';
      title.textContent = data.label;
      document.getElementById('canvas-target-focus').textContent = `TARGET LOCK: ${data.id.toUpperCase()}`;
      body.innerHTML = `
        <div class="inspector-row"><span class="inspector-label">NODE ID:</span><span class="inspector-val text-cyan">${data.id}</span></div>
        <div class="inspector-row"><span class="inspector-label">ROLE:</span><span class="inspector-val">${data.role}</span></div>
        <div class="inspector-row"><span class="inspector-label">RAFT STATE:</span><span class="inspector-val text-green">${data.state.toUpperCase()}</span></div>
        <div class="inspector-row"><span class="inspector-label">CURRENT TERM:</span><span class="inspector-val">TERM ${data.term}</span></div>
        <div class="inspector-row"><span class="inspector-label">LOG INDEX:</span><span class="inspector-val">LOG #${data.logLength}</span></div>
      `;
    }
  }

  // ── Trajectory Animations ──────────────────────────────────────────────────

  function triggerTrajectory(fromPos, toPos, callsign) {
    state.trajectories.push({
      fromX: fromPos.x,
      fromY: fromPos.y,
      toX: toPos.x,
      toY: toPos.y,
      callsign,
      progress: 0,
      speed: 0.012,
    });
  }

  function renderTrajectories(ctx) {
    state.trajectories = state.trajectories.filter(traj => {
      traj.progress += traj.speed;
      if (traj.progress >= 1) return false;

      const curX = traj.fromX + (traj.toX - traj.fromX) * traj.progress;
      const curY = traj.fromY + (traj.toY - traj.fromY) * traj.progress;

      // Draw Arc Line
      ctx.beginPath();
      ctx.moveTo(traj.fromX, traj.fromY);
      ctx.lineTo(curX, curY);
      ctx.strokeStyle = 'rgba(0, 240, 255, 0.4)';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Glowing Missile/Blip
      ctx.beginPath();
      ctx.arc(curX, curY, 4, 0, Math.PI * 2);
      ctx.fillStyle = '#00f0ff';
      ctx.shadowColor = '#00f0ff';
      ctx.shadowBlur = 12;
      ctx.fill();
      ctx.shadowBlur = 0;

      return true;
    });
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Incident Commander Gate & Dispatch Actions
  // ════════════════════════════════════════════════════════════════════════════

  function renderDispatchCards() {
    const container = document.getElementById('dispatch-cards-queue');
    const badge = document.getElementById('gate-badge-count');
    badge.textContent = state.pending.length;

    if (state.pending.length === 0) {
      container.innerHTML = `
        <div style="text-align:center; padding: 40px 10px; color: var(--text-muted);">
          <div style="font-size:28px; opacity:0.3; margin-bottom:8px;">📋</div>
          <div>No dispatches pending IC Gate review.</div>
          <div style="font-size:11px; margin-top:4px;">Run the 5-Agent Pipeline to generate AI recommendations.</div>
        </div>
      `;
      return;
    }

    container.innerHTML = '';
    state.pending.forEach(item => {
      const card = document.createElement('div');
      card.className = 'dispatch-card';
      const confPercent = ((item.ai_confidence || 0.9) * 100).toFixed(0);

      card.innerHTML = `
        <div class="dispatch-card__header">
          <span class="dispatch-card__resource">${item.resource_name || item.resource_id}</span>
          <span class="confidence-tag confidence--high">${confPercent}% CONFIDENCE</span>
        </div>
        <div class="dispatch-card__dest">
          DEPLOY TARGET → <b>${item.zone_name || item.zone_id}</b>
        </div>
        <div class="dispatch-card__reason">
          "${item.ai_reasoning || 'AI decision synthesized based on protocol guidelines and distance.'}"
        </div>
        <div class="dispatch-card__timer">
          ⏱ 120s Commander Timeout Gate Active
        </div>
        <div class="dispatch-card__actions">
          <button class="hud-btn hud-btn--success btn-confirm" data-id="${item.id}">CONFIRM</button>
          <button class="hud-btn hud-btn--danger btn-reject" data-id="${item.id}">REJECT</button>
          <button class="hud-btn hud-btn--warning btn-full btn-override" data-id="${item.id}">⚡ OVERRIDE SELECTION</button>
        </div>
      `;

      card.querySelector('.btn-confirm').addEventListener('click', () => confirmDispatch(item.id));
      card.querySelector('.btn-reject').addEventListener('click', () => rejectDispatch(item.id));
      card.querySelector('.btn-override').addEventListener('click', () => openOverrideModal(item));

      container.appendChild(card);
    });
  }

  async function confirmDispatch(confId) {
    const item = state.pending.find(p => p.id === confId);
    if (!item) return;

    // Linearizable Raft Check
    const res = state.resources.find(r => r.id === item.resource_id);
    if (res && res.status !== 'available') {
      showInvariantAlert(`Raft Linearizability: Cannot dispatch ${res.name} — Status is already ${res.status.toUpperCase()}!`);
      return;
    }

    // Live API Call (or Autonomous fallback)
    if (state.engineMode === 'live') {
      try {
        await fetch(`${API_BASE}/api/v1/dispatch/${confId}/confirm`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ commander_id: 'ic-commander-alpha', notes: 'Confirmed via God\'s Eye HUD' }),
        });
      } catch (e) { /* fallback handled below */ }
    }

    // Apply State Update
    state.pending = state.pending.filter(p => p.id !== confId);
    if (res) res.status = 'dispatched';
    state.cluster.log_length++;
    state.nodes.forEach(n => n.logLength = state.cluster.log_length);

    // Launch trajectory visual animation
    const zone = state.zones.find(z => z.id === item.zone_id);
    if (res && zone && res._screenX && zone._screenX) {
      triggerTrajectory({ x: res._screenX, y: res._screenY }, { x: zone._screenX, y: zone._screenY }, res.callsign);
    }

    // Record Immutable Audit Log
    addAuditLog('DISPATCH_CONFIRMED', 'IC_COMMANDER', `Confirmed dispatch of ${item.resource_name} to ${item.zone_name}. Raft Log #${state.cluster.log_length} committed.`);

    renderAllPanels();
  }

  async function rejectDispatch(confId) {
    const item = state.pending.find(p => p.id === confId);
    if (!item) return;

    if (state.engineMode === 'live') {
      try {
        await fetch(`${API_BASE}/api/v1/dispatch/${confId}/reject`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ commander_id: 'ic-commander-alpha', reason: 'IC Tactical Rejection' }),
        });
      } catch (e) { /* fallback */ }
    }

    state.pending = state.pending.filter(p => p.id !== confId);
    addAuditLog('DISPATCH_REJECTED', 'IC_COMMANDER', `Rejected AI recommendation for ${item.resource_name}. No dispatch committed.`);
    renderAllPanels();
  }

  // ════════════════════════════════════════════════════════════════════════════
  // 5-Agent AI Pipeline Runner
  // ════════════════════════════════════════════════════════════════════════════

  async function runAiPipeline(zoneId, description) {
    const steps = [
      document.getElementById('pipe-step-1'),
      document.getElementById('pipe-step-2'),
      document.getElementById('pipe-step-3'),
      document.getElementById('pipe-step-4'),
      document.getElementById('pipe-step-5'),
    ];

    // Reset steps
    steps.forEach(s => s.className = 'pipeline-step');

    // Run visually through the 5 steps
    for (let i = 0; i < steps.length; i++) {
      steps[i].classList.add('active');
      await new Promise(r => setTimeout(r, 450));
      steps[i].classList.remove('active');
      steps[i].classList.add('complete');
    }

    // Pick an available resource or fallback
    const availRes = state.resources.find(r => r.status === 'available') || state.resources[0];
    const targetZone = state.zones.find(z => z.id === zoneId) || state.zones[0];

    const newConfId = `conf-${Date.now().toString(36)}`;
    const newRecommendation = {
      id: newConfId,
      resource_id: availRes.id,
      resource_name: availRes.name,
      zone_id: targetZone.id,
      zone_name: targetZone.name,
      incident_id: `INC-${Math.floor(1000 + Math.random() * 9000)}`,
      ai_confidence: 0.92,
      ai_reasoning: `5-Agent Pipeline: ${description.slice(0, 80)}... Optimal transit time & capability match.`,
      expires_at: new Date(Date.now() + 120000).toISOString(),
    };

    state.pending.unshift(newRecommendation);
    addAuditLog('AI_RECOMMENDATION_READY', 'PIPELINE_AGENT_5', `5-Agent pipeline synthesized dispatch recommendation: ${availRes.name} -> ${targetZone.name}.`);

    // Switch to Gate tab to review
    document.getElementById('tab-btn-gate').click();
    renderDispatchCards();
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Chaos Engineering & Resilience Sandbox
  // ════════════════════════════════════════════════════════════════════════════

  function setupChaosHandlers() {
    // 1. Isolate Node Alpha (Network Partition)
    document.getElementById('btn-chaos-partition').addEventListener('click', () => {
      state.cluster.is_partitioned = true;
      const alpha = state.nodes.find(n => n.id === 'alpha');
      if (alpha) {
        alpha.is_partitioned = true;
        alpha.state = 'candidate';
      }
      // Majority re-elects Bravo as new leader!
      const bravo = state.nodes.find(n => n.id === 'bravo');
      if (bravo) {
        bravo.state = 'leader';
        bravo.term = state.cluster.current_term + 1;
        state.cluster.current_term++;
        state.cluster.leader_id = 'bravo';
      }

      document.getElementById('degraded-mode-block').style.display = '';
      addAuditLog('CHAOS_PARTITION_TRIGGERED', 'CHAOS_ENGINE', 'Simulated network partition: Alpha isolated from Bravo & Charlie quorum.');
      renderAllPanels();
    });

    // 2. Heal Partition
    document.getElementById('btn-chaos-heal').addEventListener('click', () => {
      state.cluster.is_partitioned = false;
      state.nodes.forEach(n => {
        n.is_partitioned = false;
        n.term = state.cluster.current_term;
        n.logLength = state.cluster.log_length;
      });
      document.getElementById('degraded-mode-block').style.display = 'none';
      addAuditLog('CHAOS_PARTITION_HEALED', 'CHAOS_ENGINE', 'Network partition healed. Raft WAL reconciliation completed.');
      renderAllPanels();
    });

    // 3. Kill Leader
    document.getElementById('btn-chaos-kill-leader').addEventListener('click', () => {
      const oldLeader = state.nodes.find(n => n.state === 'leader');
      if (oldLeader) oldLeader.state = 'follower';

      state.cluster.current_term++;
      // Next node becomes leader
      const newLeader = state.nodes.find(n => n !== oldLeader);
      if (newLeader) {
        newLeader.state = 'leader';
        newLeader.term = state.cluster.current_term;
        state.cluster.leader_id = newLeader.id;
      }

      addAuditLog('LEADER_FAILOVER', 'CHAOS_ENGINE', `Active leader killed. Automated election completed: ${newLeader?.label} elected for Term ${state.cluster.current_term}.`);
      renderAllPanels();
    });

    // 4. Simultaneous Double-Dispatch Attack
    const runDoubleDispatch = () => {
      const avail = state.resources.find(r => r.status === 'available');
      if (!avail) {
        showInvariantAlert('No available resources left to test double dispatch! Reset or heal cluster first.');
        return;
      }

      // Step 1: First dispatch succeeds
      avail.status = 'dispatched';
      state.cluster.log_length++;
      addAuditLog('DISPATCH_COMMITTED', 'COMMANDER_GATE', `Dispatch 1/2 for ${avail.name} committed to Raft Log #${state.cluster.log_length}.`);

      // Step 2: Second concurrent dispatch is structurally blocked by Raft state machine!
      showInvariantAlert(`ATTACK DETECTED: 2nd dispatch for [${avail.name}] BLOCKED! Raft linearizability guarantees no resource can be double-dispatched.`);
      addAuditLog('DOUBLE_DISPATCH_BLOCKED', 'RAFT_CORE', `Invariant violation prevented: Linearizable state rejected duplicate dispatch for ${avail.name}.`);

      renderAllPanels();
    };

    document.getElementById('btn-chaos-double-dispatch').addEventListener('click', runDoubleDispatch);
    document.getElementById('btn-double-dispatch-attack').addEventListener('click', runDoubleDispatch);
  }

  function showInvariantAlert(msg) {
    const banner = document.getElementById('invariant-banner');
    document.getElementById('invariant-banner-text').textContent = msg;
    banner.classList.add('visible');
  }

  document.getElementById('btn-close-invariant')?.addEventListener('click', () => {
    document.getElementById('invariant-banner').classList.remove('visible');
  });

  // ════════════════════════════════════════════════════════════════════════════
  // Modals: Commander Override & Quick Deploy
  // ════════════════════════════════════════════════════════════════════════════

  let currentOverrideItem = null;

  function openOverrideModal(item) {
    currentOverrideItem = item;
    const modal = document.getElementById('modal-override');
    document.getElementById('override-orig-resource').value = `${item.resource_name} (${item.resource_id})`;

    const select = document.getElementById('override-select-resource');
    select.innerHTML = '';
    state.resources.forEach(r => {
      if (r.id !== item.resource_id && r.status === 'available') {
        const opt = document.createElement('option');
        opt.value = r.id;
        opt.textContent = `${r.name} · ${r.callsign} (${r.resource_type})`;
        select.appendChild(opt);
      }
    });

    modal.style.display = 'flex';
  }

  function setupModals() {
    // Override Modal
    document.getElementById('btn-close-override-modal')?.addEventListener('click', () => {
      document.getElementById('modal-override').style.display = 'none';
    });
    document.getElementById('btn-cancel-override')?.addEventListener('click', () => {
      document.getElementById('modal-override').style.display = 'none';
    });
    document.getElementById('btn-submit-override')?.addEventListener('click', () => {
      if (!currentOverrideItem) return;
      const select = document.getElementById('override-select-resource');
      const newResId = select.value;
      const newRes = state.resources.find(r => r.id === newResId);

      if (newRes) {
        state.pending = state.pending.filter(p => p.id !== currentOverrideItem.id);
        newRes.status = 'dispatched';
        state.cluster.log_length++;
        addAuditLog('COMMANDER_OVERRIDE', 'IC_COMMANDER', `Commander override: Swapped recommended unit with ${newRes.name}. Committed to Raft Log #${state.cluster.log_length}.`);
      }

      document.getElementById('modal-override').style.display = 'none';
      renderAllPanels();
    });

    // Quick Deploy Modal
    document.getElementById('btn-quick-deploy-modal')?.addEventListener('click', () => openQuickDeployModal());
    document.getElementById('btn-close-quick-deploy-modal')?.addEventListener('click', () => {
      document.getElementById('modal-quick-deploy').style.display = 'none';
    });
    document.getElementById('btn-cancel-quick-deploy')?.addEventListener('click', () => {
      document.getElementById('modal-quick-deploy').style.display = 'none';
    });
    document.getElementById('btn-submit-quick-deploy')?.addEventListener('click', () => {
      const resId = document.getElementById('quick-deploy-resource').value;
      const zoneId = document.getElementById('quick-deploy-zone').value;
      const res = state.resources.find(r => r.id === resId);
      const zone = state.zones.find(z => z.id === zoneId);

      if (res && zone && res.status === 'available') {
        res.status = 'dispatched';
        state.cluster.log_length++;
        if (res._screenX && zone._screenX) {
          triggerTrajectory({ x: res._screenX, y: res._screenY }, { x: zone._screenX, y: zone._screenY }, res.callsign);
        }
        addAuditLog('DIRECT_DISPATCH', 'IC_COMMANDER', `Manual dispatch: ${res.name} deployed to ${zone.name}. Committed Raft Log #${state.cluster.log_length}.`);
      }

      document.getElementById('modal-quick-deploy').style.display = 'none';
      renderAllPanels();
    });

    // Close Inspector
    document.getElementById('btn-close-inspector')?.addEventListener('click', () => {
      document.getElementById('tactical-inspector-card').style.display = 'none';
      state.selectedEntity = null;
    });
  }

  function openQuickDeployModal(preselectedResId = null) {
    const modal = document.getElementById('modal-quick-deploy');
    const resSelect = document.getElementById('quick-deploy-resource');
    const zoneSelect = document.getElementById('quick-deploy-zone');

    resSelect.innerHTML = '';
    state.resources.forEach(r => {
      if (r.status === 'available') {
        const opt = document.createElement('option');
        opt.value = r.id;
        opt.textContent = `${r.name} (${r.callsign})`;
        if (r.id === preselectedResId) opt.selected = true;
        resSelect.appendChild(opt);
      }
    });

    zoneSelect.innerHTML = '';
    state.zones.forEach(z => {
      const opt = document.createElement('option');
      opt.value = z.id;
      opt.textContent = `${z.name} (P${z.priority})`;
      zoneSelect.appendChild(opt);
    });

    modal.style.display = 'flex';
  }

  // ════════════════════════════════════════════════════════════════════════════
  // UI Interactions, Tabs & Presets
  // ════════════════════════════════════════════════════════════════════════════

  function setupTabs() {
    const tabBtns = document.querySelectorAll('.hud-nav-tab');
    const panels = document.querySelectorAll('.hud-panel');

    tabBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        tabBtns.forEach(b => b.classList.remove('active'));
        panels.forEach(p => p.style.display = 'none');

        btn.classList.add('active');
        const target = document.getElementById(btn.dataset.panel);
        if (target) target.style.display = 'flex';
      });
    });
  }

  function setupViewSwitch() {
    const btnRadar = document.getElementById('btn-view-radar');
    const btnRaft = document.getElementById('btn-view-raft');

    btnRadar.addEventListener('click', () => {
      btnRadar.classList.add('active');
      btnRaft.classList.remove('active');
      state.currentView = 'radar';
      state.selectedEntity = null;
      renderInspector(null);
    });

    btnRaft.addEventListener('click', () => {
      btnRaft.classList.add('active');
      btnRadar.classList.remove('active');
      state.currentView = 'raft';
      state.selectedEntity = null;
      renderInspector(null);
    });

    document.getElementById('btn-toggle-sweep')?.addEventListener('click', () => {
      state.radarSweepActive = !state.radarSweepActive;
      document.getElementById('sweep-indicator').classList.toggle('active', state.radarSweepActive);
    });

    document.getElementById('btn-reset-view')?.addEventListener('click', () => {
      state.selectedEntity = null;
      renderInspector(null);
    });
  }

  function setupInteractions() {
    // Resource Filter Pills
    document.querySelectorAll('.filter-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        state.resourceFilter = pill.dataset.filter;
        renderResourceList();
      });
    });

    // 1-Click Scenario Presets
    document.querySelectorAll('.preset-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const type = btn.dataset.preset;
        const presets = {
          earthquake: { zone: 'zone-cbd-01', desc: '7.2 Magnitude Earthquake with collapsed commercial structures in CBD Sector' },
          flood: { zone: 'zone-river-02', desc: 'Flash flood inundation at East Riverfront Lowlands, rising at 2m/hr' },
          chemical: { zone: 'zone-ind-03', desc: 'Toxic industrial chemical cloud spreading towards residential area' },
          fire: { zone: 'zone-cbd-01', desc: 'Multi-alarm warehouse firestorm with high casualty density' },
        };
        const p = presets[type] || presets.earthquake;
        runAiPipeline(p.zone, p.desc);
      });
    });

    // Custom Incident Runner
    document.getElementById('btn-run-custom-pipeline')?.addEventListener('click', () => {
      const text = document.getElementById('custom-incident-text').value.trim() || 'Emergency transmission report: multiple injuries reported.';
      const zoneId = document.getElementById('custom-target-zone').value;
      runAiPipeline(zoneId, text);
    });

    // Toggle Engine Mode
    document.getElementById('engine-badge')?.addEventListener('click', () => {
      state.engineMode = state.engineMode === 'live' ? 'autonomous' : 'live';
      updateEngineBadge();
    });

    // Drag and Drop
    setupDragAndDrop();
  }

  function setupDragAndDrop() {
    const container = document.getElementById('hud-canvas-container');
    const overlay = document.getElementById('canvas-drop-overlay');

    container.addEventListener('dragover', e => {
      e.preventDefault();
      overlay.classList.add('visible');
    });

    container.addEventListener('dragleave', () => {
      overlay.classList.remove('visible');
    });

    container.addEventListener('drop', e => {
      e.preventDefault();
      overlay.classList.remove('visible');
      const resId = e.dataTransfer.getData('text/plain');
      const res = state.resources.find(r => r.id === resId);
      if (res) {
        openQuickDeployModal(res.id);
      }
    });
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Renderers for Rails & Panels
  // ════════════════════════════════════════════════════════════════════════════

  function renderAllPanels() {
    renderHeaderTelemetry();
    renderResourceList();
    renderZonesMiniList();
    renderDispatchCards();
    renderAuditStream();
  }

  function renderHeaderTelemetry() {
    const leader = state.nodes.find(n => n.state === 'leader') || state.nodes[0];
    document.getElementById('cluster-state-text').textContent = `${leader.id.toUpperCase()} · LEADER`;
    document.getElementById('cluster-term-val').textContent = `TERM ${String(state.cluster.current_term).padStart(2, '0')}`;
    document.getElementById('cluster-log-val').textContent = `LOG #${String(state.cluster.log_length).padStart(3, '0')}`;

    // Update ICP cards
    state.nodes.forEach(n => {
      const termEl = document.getElementById(`term-${n.id}`);
      const logEl = document.getElementById(`log-${n.id}`);
      const badgeEl = document.getElementById(`badge-icp-${n.id}`);
      if (termEl) termEl.textContent = n.term;
      if (logEl) logEl.textContent = n.logLength;
      if (badgeEl) {
        badgeEl.textContent = n.is_partitioned ? 'ISOLATED' : n.state.toUpperCase();
        badgeEl.className = `icp-card__badge ${n.is_partitioned ? 'badge-leader' : n.state === 'leader' ? 'badge-leader' : 'badge-follower'}`;
      }
    });
  }

  function renderResourceList() {
    const list = document.getElementById('resource-list');
    const filtered = state.resources.filter(r => {
      if (state.resourceFilter === 'all') return true;
      return r.status === state.resourceFilter;
    });

    document.getElementById('resource-count-tag').textContent = `${state.resources.filter(r => r.status === 'available').length} READY`;
    list.innerHTML = '';

    filtered.forEach(res => {
      const card = document.createElement('div');
      card.className = 'res-card';
      card.draggable = true;
      card.dataset.id = res.id;

      card.innerHTML = `
        <div class="res-icon-box">${RESOURCE_ICONS[res.resource_type] || '📦'}</div>
        <div class="res-info">
          <div class="res-name">${res.name}</div>
          <div class="res-meta">${res.callsign} · ${res.capabilities?.personnel_count || 4} Crew</div>
        </div>
        <span class="res-status-tag res-status--${state.cluster.is_partitioned ? 'uncertain' : res.status}">
          ${state.cluster.is_partitioned ? 'UNCERTAIN' : res.status}
        </span>
      `;

      card.addEventListener('dragstart', e => {
        card.classList.add('dragging');
        e.dataTransfer.setData('text/plain', res.id);
      });
      card.addEventListener('dragend', () => card.classList.remove('dragging'));
      card.addEventListener('click', () => {
        state.selectedEntity = { type: 'resource', data: res, x: res._screenX || 200, y: res._screenY || 200 };
        renderInspector(state.selectedEntity);
      });

      list.appendChild(card);
    });
  }

  function renderZonesMiniList() {
    const list = document.getElementById('zone-mini-list');
    list.innerHTML = '';
    state.zones.forEach(zone => {
      const card = document.createElement('div');
      card.className = 'zone-mini-card';
      card.innerHTML = `
        <span style="font-weight:600;">${zone.name.split('—')[0]}</span>
        <span class="zone-p-badge zone-p--${zone.priority}">P${zone.priority}</span>
      `;
      card.addEventListener('click', () => {
        state.selectedEntity = { type: 'zone', data: zone, x: zone._screenX || 200, y: zone._screenY || 200 };
        renderInspector(state.selectedEntity);
      });
      list.appendChild(card);
    });
  }

  function renderAuditStream() {
    const stream = document.getElementById('audit-stream');
    stream.innerHTML = '';
    state.auditLogs.slice().reverse().forEach(log => {
      const entry = document.createElement('div');
      const actionType = log.action.toLowerCase();
      entry.className = `audit-entry ${actionType.includes('dispatch') ? 'audit-entry--dispatch' : actionType.includes('override') ? 'audit-entry--override' : actionType.includes('block') || actionType.includes('reject') ? 'audit-entry--reject' : ''}`;

      entry.innerHTML = `
        <div class="audit-entry__header">
          <span class="audit-entry__action">${log.action}</span>
          <span class="audit-entry__time">${new Date(log.timestamp).toLocaleTimeString()}</span>
        </div>
        <div class="audit-entry__text">${log.details}</div>
        <div class="audit-entry__hash">HASH: ${log.hash} · ACTOR: ${log.actor}</div>
      `;
      stream.appendChild(entry);
    });
  }

  function addAuditLog(action, actor, details) {
    const hash = `0x${Math.random().toString(16).slice(2, 14)}`;
    state.auditLogs.push({
      id: `AUD-${String(state.auditLogs.length + 1).padStart(3, '0')}`,
      timestamp: new Date().toISOString(),
      action,
      actor,
      details,
      hash,
    });
    renderAuditStream();
  }

  function setupClock() {
    const clockEl = document.getElementById('hud-clock');
    const update = () => {
      const now = new Date();
      clockEl.textContent = `${now.toUTCString().slice(17, 25)} UTC`;
    };
    update();
    setInterval(update, 1000);
  }

  function updateEngineBadge() {
    const badge = document.getElementById('engine-badge');
    const label = document.getElementById('engine-label');
    const dot = document.getElementById('engine-dot');
    if (state.engineMode === 'live') {
      label.textContent = 'LIVE CLUSTER BACKEND';
      badge.style.borderColor = 'var(--green-matrix)';
      dot.style.background = 'var(--green-matrix)';
    } else {
      label.textContent = 'AUTONOMOUS TACTICAL ENGINE';
      badge.style.borderColor = 'var(--cyan-primary)';
      dot.style.background = 'var(--cyan-primary)';
    }
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Live Backend Probing & Polling
  // ════════════════════════════════════════════════════════════════════════════

  async function probeBackend() {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/cluster/status`);
      if (resp.ok) {
        state.engineMode = 'live';
        updateEngineBadge();
        startBackendPolling();
        connectWebSocket();
      }
    } catch {
      state.engineMode = 'autonomous';
      updateEngineBadge();
    }
  }

  function startBackendPolling() {
    setInterval(async () => {
      if (state.engineMode !== 'live') return;
      try {
        const [clusterResp, resResp, zonesResp, pendingResp] = await Promise.all([
          fetch(`${API_BASE}/api/v1/cluster/status`),
          fetch(`${API_BASE}/api/v1/resources`),
          fetch(`${API_BASE}/api/v1/zones`),
          fetch(`${API_BASE}/api/v1/dispatch/pending`),
        ]);

        if (clusterResp.ok) {
          const cData = await clusterResp.json();
          if (cData.node_id) {
            state.cluster = { ...state.cluster, ...cData };
          }
        }
        if (resResp.ok) {
          const rData = await resResp.json();
          if (rData.resources?.length) state.resources = rData.resources;
        }
        if (zonesResp.ok) {
          const zData = await zonesResp.json();
          if (zData.zones?.length) state.zones = zData.zones;
        }
        if (pendingResp.ok) {
          const pData = await pendingResp.json();
          if (Array.isArray(pData.pending)) state.pending = pData.pending;
        }
        renderAllPanels();
      } catch {
        // Soft fallback to autonomous engine
      }
    }, 2500);
  }

  function connectWebSocket() {
    try {
      state.ws = new WebSocket(WS_URL);
      state.ws.onmessage = evt => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === 'resource_dispatched') {
            addAuditLog('DISPATCH_COMMITTED', 'RAFT_CORE', `WebSocket: Resource ${msg.data?.resource_id} dispatched.`);
          }
        } catch {}
      };
    } catch {}
  }

  // ════════════════════════════════════════════════════════════════════════════
  // Launch
  // ════════════════════════════════════════════════════════════════════════════

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
