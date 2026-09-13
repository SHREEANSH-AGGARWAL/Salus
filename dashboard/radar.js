/* ═══════════════════════════════════════════════════════════════════════════
   SALUS — Interactive radar map
   ───────────────────────────────────────────────────────────────────────────
   A canvas radar scope over a schematic of Delhi. Pan by dragging, zoom with
   the wheel or the on-screen buttons, click a unit or zone to select it, or
   switch on "pick" mode to read a coordinate straight off the map.

   The map owns nothing but its own view. It is handed data with setData()
   and reports interaction back through the callbacks in `opts`.
   ═══════════════════════════════════════════════════════════════════════════ */

'use strict';

const KM_PER_DEG_LAT = 110.574;
const kmPerDegLng = (lat) => 111.320 * Math.cos(lat * Math.PI / 180);

const PRIORITY_COLORS = {
  1: '#ff4d4d',  // P1 critical
  2: '#ff8a3d',  // P2 high
  3: '#ffd23d',  // P3 moderate
  4: '#2dd4bf',  // P4 low
  5: '#8193ab',  // P5 minimal
};

const STATUS_COLORS = {
  available:      '#34d399',
  dispatched:     '#38bdf8',
  on_scene:       '#a78bfa',
  returning:      '#facc15',
  needs_resupply: '#fb923c',
  resupplying:    '#fb923c',
  maintenance:    '#f87171',
  uncertain:      '#fbbf24',
};

const STATUS_LABELS = {
  available:      'Ready',
  dispatched:     'En route',
  on_scene:       'On scene',
  returning:      'Returning',
  needs_resupply: 'Needs resupply',
  resupplying:    'Resupplying',
  maintenance:    'Out of service',
  uncertain:      'Unconfirmed',
};

const TYPE_GLYPHS = {
  ambulance: '🚑', ambulance_als: '🚑', fire_engine: '🚒', hazmat_team: '🧪',
  helicopter_transport: '🚁', helicopter_medical: '🚁', helicopter_heavy_lift: '🚁',
  sar_team_urban: '⛑️', sar_team_water: '🚤', sar_team_mountain: '🧗',
  k9_unit: '🐕', drone_team: '📡', evacuation_bus: '🚌', supply_truck: '🚚',
  water_tanker: '💧', generator: '🔌', field_hospital: '🏥', engineering_unit: '🚜',
};

const PLACE_STYLES = {
  hub:      { color: '#7dd3fc', size: 3.2 },
  hospital: { color: '#f9a8d4', size: 3.0 },
  landmark: { color: '#cbd5e1', size: 2.8 },
  locality: { color: '#64748b', size: 2.2 },
  ncr:      { color: '#475569', size: 2.4 },
};

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const easeOut = (t) => 1 - Math.pow(1 - t, 3);

class RadarMap {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.opts = opts;

    this.center = { ...DELHI.CENTER };
    this.pxPerKm = 12;
    this.minPxPerKm = 3;
    this.maxPxPerKm = 320;

    this.data = { resources: [], zones: [] };
    this.selection = null;           // { type, id }
    this.focus = null;               // transient highlight, same shape
    this.hover = null;
    this.pickMode = false;

    this.layers = {
      units: true, zones: true, routes: true,
      places: true, labels: true, rings: true, sweep: true,
    };

    this._hits = [];
    this._labelBoxes = [];
    this._pointers = new Map();
    this._drag = null;
    this._pinch = null;
    this._fly = null;
    this._raf = null;
    this._w = 0; this._h = 0; this._dpr = 1;

    this._bind();
    this.resize();
  }

  /* ── View maths ──────────────────────────────────────────────────────── */

  project(lat, lng) {
    const x = this._w / 2 + (lng - this.center.lng) * kmPerDegLng(this.center.lat) * this.pxPerKm;
    const y = this._h / 2 - (lat - this.center.lat) * KM_PER_DEG_LAT * this.pxPerKm;
    return [x, y];
  }

  unproject(x, y) {
    return {
      lat: this.center.lat + (this._h / 2 - y) / (KM_PER_DEG_LAT * this.pxPerKm),
      lng: this.center.lng + (x - this._w / 2) / (kmPerDegLng(this.center.lat) * this.pxPerKm),
    };
  }

  zoomAbout(px, py, factor) {
    const before = this.unproject(px, py);
    this.pxPerKm = clamp(this.pxPerKm * factor, this.minPxPerKm, this.maxPxPerKm);
    const after = this.unproject(px, py);
    this.center.lat += before.lat - after.lat;
    this.center.lng += before.lng - after.lng;
    this._fly = null;
    this._notifyView();
  }

  zoomBy(factor) {
    this.zoomAbout(this._w / 2, this._h / 2, factor);
  }

  /** Animate the view to a coordinate (and optionally a zoom level). */
  flyTo(lat, lng, pxPerKm = null, ms = 550) {
    this._fly = {
      t0: performance.now(), ms,
      from: { ...this.center, z: this.pxPerKm },
      to: { lat, lng, z: clamp(pxPerKm ?? this.pxPerKm, this.minPxPerKm, this.maxPxPerKm) },
    };
  }

  /** Frame the whole National Capital Territory. */
  fitDelhi(animate = true) {
    const z = Math.min(this._w, this._h) / 52;
    if (animate) this.flyTo(DELHI.CENTER.lat, DELHI.CENTER.lng, z);
    else { this.center = { ...DELHI.CENTER }; this.pxPerKm = z; this._notifyView(); }
  }

  /** Frame everything currently on the board. */
  fitData(animate = true) {
    const pts = [];
    for (const r of this.data.resources) if (r.home_base) pts.push([r.home_base.latitude, r.home_base.longitude]);
    for (const z of this.data.zones) if (z.boundary?.center) pts.push([z.boundary.center.latitude, z.boundary.center.longitude]);
    if (pts.length === 0) return this.fitDelhi(animate);

    let minLat = 90, maxLat = -90, minLng = 180, maxLng = -180;
    for (const [la, ln] of pts) {
      minLat = Math.min(minLat, la); maxLat = Math.max(maxLat, la);
      minLng = Math.min(minLng, ln); maxLng = Math.max(maxLng, ln);
    }
    const midLat = (minLat + maxLat) / 2, midLng = (minLng + maxLng) / 2;
    const spanKmY = Math.max((maxLat - minLat) * KM_PER_DEG_LAT, 3);
    const spanKmX = Math.max((maxLng - minLng) * kmPerDegLng(midLat), 3);
    const z = clamp(Math.min((this._h - 120) / spanKmY, (this._w - 220) / spanKmX),
                    this.minPxPerKm, 60);
    if (animate) this.flyTo(midLat, midLng, z);
    else { this.center = { lat: midLat, lng: midLng }; this.pxPerKm = z; this._notifyView(); }
  }

  /* ── Data & state ────────────────────────────────────────────────────── */

  setData(resources, zones) {
    this.data.resources = resources || [];
    this.data.zones = zones || [];
  }

  setSelection(sel) { this.selection = sel; }

  setLayer(name, on) { this.layers[name] = on; }

  setPickMode(on) {
    this.pickMode = on;
    this.canvas.classList.toggle('is-picking', on);
  }

  /* ── Lifecycle ───────────────────────────────────────────────────────── */

  resize() {
    const box = this.canvas.parentElement;
    const w = Math.max(1, box.clientWidth);
    const h = Math.max(1, box.clientHeight);
    const dpr = window.devicePixelRatio || 1;
    // Re-frame if we have never had a usable size — the first layout pass can
    // hand us a collapsed box, and a fit computed from that is meaningless.
    const first = this._w < 80 || this._h < 80;
    this._w = w; this._h = h; this._dpr = dpr;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.canvas.style.width = w + 'px';
    this.canvas.style.height = h + 'px';
    if (first) this.fitDelhi(false);
  }

  start() {
    if (this._raf) return;
    const loop = () => { this._raf = requestAnimationFrame(loop); this.draw(); };
    this._raf = requestAnimationFrame(loop);
  }

  stop() {
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
  }

  _notifyView() { this.opts.onViewChange?.(); }

  /* ── Frame ───────────────────────────────────────────────────────────── */

  draw() {
    const ctx = this.ctx;
    const w = this._w, h = this._h;
    if (w < 4 || h < 4) return;

    // Fly-to easing
    if (this._fly) {
      const f = this._fly;
      const t = clamp((performance.now() - f.t0) / f.ms, 0, 1);
      const e = easeOut(t);
      this.center.lat = f.from.lat + (f.to.lat - f.from.lat) * e;
      this.center.lng = f.from.lng + (f.to.lng - f.from.lng) * e;
      this.pxPerKm = f.from.z + (f.to.z - f.from.z) * e;
      if (t >= 1) { this._fly = null; this._notifyView(); }
    }

    const now = performance.now();
    ctx.setTransform(this._dpr, 0, 0, this._dpr, 0, 0);
    this._hits = [];
    this._labelBoxes = [];

    this._paintBackground(w, h);
    this._drawGraticule(w, h);
    this._drawBoundary();
    this._drawRoads();
    this._drawRiver();
    if (this.layers.rings) this._drawRangeRings(w, h);
    if (this.layers.labels) this._drawDistricts();
    // Zones claim their label space before landmarks do — a zone chip matters
    // more than a place name, and central Delhi has no room for both.
    if (this.layers.zones) this._drawZones(now);
    if (this.layers.places) this._drawPlaces();
    if (this.layers.routes) this._drawRoutes(now);
    if (this.layers.units) this._drawUnits(now);
    if (this.layers.sweep) this._drawSweep(w, h, now);
    this._drawReticle(now);
    this._drawFrame(w, h);
    if (this.pickMode) this._drawCrosshair(w, h);
  }

  _paintBackground(w, h) {
    const ctx = this.ctx;
    const g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.75);
    g.addColorStop(0, '#0a1420');
    g.addColorStop(0.55, '#060d16');
    g.addColorStop(1, '#03070c');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
  }

  _drawGraticule(w, h) {
    const ctx = this.ctx;
    // Choose a graticule step that lands near 60–140 px on screen.
    const steps = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5];
    let step = steps[steps.length - 1];
    for (const s of steps) { if (s * KM_PER_DEG_LAT * this.pxPerKm > 55) { step = s; break; } }

    const tl = this.unproject(0, 0), br = this.unproject(w, h);
    ctx.lineWidth = 1;

    ctx.strokeStyle = 'rgba(56,189,248,0.055)';
    ctx.beginPath();
    for (let lat = Math.floor(br.lat / step) * step; lat <= tl.lat; lat += step) {
      const y = Math.round(this.project(lat, this.center.lng)[1]) + 0.5;
      ctx.moveTo(0, y); ctx.lineTo(w, y);
    }
    for (let lng = Math.floor(tl.lng / step) * step; lng <= br.lng; lng += step) {
      const x = Math.round(this.project(this.center.lat, lng)[0]) + 0.5;
      ctx.moveTo(x, 0); ctx.lineTo(x, h);
    }
    ctx.stroke();
  }

  _poly(points, close) {
    const ctx = this.ctx;
    ctx.beginPath();
    points.forEach(([la, ln], i) => {
      const [x, y] = this.project(la, ln);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    if (close) ctx.closePath();
  }

  _drawBoundary() {
    const ctx = this.ctx;
    this._poly(DELHI.BOUNDARY, true);
    ctx.fillStyle = 'rgba(22,110,110,0.055)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(45,212,191,0.45)';
    ctx.lineWidth = 1.4;
    ctx.setLineDash([7, 5]);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  _drawRoads() {
    const ctx = this.ctx;
    ctx.lineJoin = 'round';
    for (const [path, width, color] of [
      [DELHI.OUTER_RING, 2.2, 'rgba(148,180,214,0.22)'],
      [DELHI.RING_ROAD, 2.0, 'rgba(148,180,214,0.30)'],
    ]) {
      this._poly(path, true);
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.stroke();
    }
  }

  _drawRiver() {
    const ctx = this.ctx;
    const w = Math.min(7, Math.max(1.6, 0.22 * this.pxPerKm));
    this._poly(DELHI.YAMUNA, false);
    ctx.strokeStyle = 'rgba(38,110,220,0.14)';
    ctx.lineWidth = w * 2.2;
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.stroke();
    ctx.strokeStyle = 'rgba(76,146,255,0.55)';
    ctx.lineWidth = w;
    ctx.stroke();

    if (this.pxPerKm > 9) {
      const [x, y] = this.project(28.690, 77.233);
      ctx.save();
      ctx.translate(x + 10, y);
      ctx.rotate(-Math.PI / 2.2);
      ctx.fillStyle = 'rgba(125,180,255,0.55)';
      ctx.font = '600 10px "Rajdhani", sans-serif';
      ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      ctx.fillText('Y A M U N A', 0, 0);
      ctx.restore();
    }
  }

  _drawRangeRings(w, h) {
    const ctx = this.ctx;
    const [cx, cy] = [w / 2, h / 2];
    const maxKm = Math.hypot(w, h) / 2 / this.pxPerKm;
    const candidates = [1, 2, 5, 10, 20, 50];
    let stepKm = candidates.find(k => k * this.pxPerKm > 70) || 50;

    ctx.strokeStyle = 'rgba(56,189,248,0.13)';
    ctx.lineWidth = 1;
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.fillStyle = 'rgba(125,211,252,0.40)';
    ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';

    for (let km = stepKm; km <= maxKm; km += stepKm) {
      const r = km * this.pxPerKm;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.stroke();
      const lx = cx + r * Math.cos(-Math.PI / 4);
      const ly = cy + r * Math.sin(-Math.PI / 4);
      ctx.fillText(`${km} km`, lx + 3, ly - 2);
    }

    // Bearing ticks around the second ring.
    const tickR = stepKm * 2 * this.pxPerKm;
    ctx.strokeStyle = 'rgba(56,189,248,0.22)';
    for (let deg = 0; deg < 360; deg += 15) {
      const a = (deg - 90) * Math.PI / 180;
      const inner = deg % 90 === 0 ? tickR - 10 : tickR - 5;
      ctx.beginPath();
      ctx.moveTo(cx + inner * Math.cos(a), cy + inner * Math.sin(a));
      ctx.lineTo(cx + tickR * Math.cos(a), cy + tickR * Math.sin(a));
      ctx.stroke();
    }
    ctx.fillStyle = 'rgba(125,211,252,0.55)';
    ctx.font = '600 10px "JetBrains Mono", monospace';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (const [label, deg] of [['N', 0], ['E', 90], ['S', 180], ['W', 270]]) {
      const a = (deg - 90) * Math.PI / 180;
      ctx.fillText(label, cx + (tickR + 12) * Math.cos(a), cy + (tickR + 12) * Math.sin(a));
    }
  }

  _drawDistricts() {
    if (this.pxPerKm < 6) return;
    const ctx = this.ctx;
    ctx.fillStyle = 'rgba(100,130,165,0.20)';
    ctx.font = '600 10px "Rajdhani", sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (const d of DELHI.DISTRICTS) {
      const [x, y] = this.project(d.lat, d.lng);
      if (x < -60 || x > this._w + 60 || y < -20 || y > this._h + 20) continue;
      ctx.save();
      ctx.letterSpacing = '2px';
      ctx.fillText(d.name, x, y);
      ctx.restore();
    }
  }

  _drawPlaces() {
    const ctx = this.ctx;
    const showLabels = this.layers.labels;
    const minKind = this.pxPerKm < 8 ? ['hub', 'ncr'] : this.pxPerKm < 14
      ? ['hub', 'ncr', 'hospital', 'landmark'] : null;

    for (const p of DELHI.LANDMARKS) {
      if (minKind && !minKind.includes(p.kind)) continue;
      const [x, y] = this.project(p.lat, p.lng);
      if (x < -40 || x > this._w + 40 || y < -20 || y > this._h + 20) continue;
      const st = PLACE_STYLES[p.kind] || PLACE_STYLES.locality;

      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = st.color + '';
      ctx.globalAlpha = 0.55;
      ctx.fillRect(-st.size / 2, -st.size / 2, st.size, st.size);
      ctx.restore();

      if (showLabels) {
        ctx.font = '500 9.5px "Inter", sans-serif';
        const tw = ctx.measureText(p.name).width;
        const box = { x: x + 6, y: y - 6, w: tw, h: 11 };
        if (this._claimLabel(box)) {
          ctx.fillStyle = 'rgba(203,213,225,0.52)';
          ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
          ctx.fillText(p.name, x + 6, y + 0.5);
        }
      }
    }
  }

  /** Reserve screen space for a label; returns false if it would collide. */
  _claimLabel(box) {
    for (const b of this._labelBoxes) {
      if (box.x < b.x + b.w + 3 && box.x + box.w + 3 > b.x &&
          box.y < b.y + b.h + 2 && box.y + box.h + 2 > b.y) return false;
    }
    this._labelBoxes.push(box);
    return true;
  }

  _drawZones(now) {
    const ctx = this.ctx;
    for (const z of this.data.zones) {
      if (!z.boundary?.center) continue;
      const [x, y] = this.project(z.boundary.center.latitude, z.boundary.center.longitude);
      const r = Math.max(10, (z.boundary.radius_km || 1) * this.pxPerKm);
      const color = PRIORITY_COLORS[z.priority] || PRIORITY_COLORS[3];
      const selected = this.selection?.type === 'zone' && this.selection.id === z.id;
      const hovered = this.hover?.type === 'zone' && this.hover.id === z.id;

      // Body
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, color + '33');
      g.addColorStop(0.7, color + '18');
      g.addColorStop(1, color + '05');
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = g; ctx.fill();
      ctx.strokeStyle = color + (selected || hovered ? 'ee' : '99');
      ctx.lineWidth = selected ? 2 : 1.3;
      ctx.stroke();

      // Unserved critical zones pulse outward.
      const unserved = (z.assigned_resource_ids || []).length === 0;
      if (z.priority <= 2 && unserved) {
        const phase = ((now / 2200) % 1);
        ctx.beginPath();
        ctx.arc(x, y, r + phase * 26, 0, Math.PI * 2);
        ctx.strokeStyle = color + Math.round((1 - phase) * 130).toString(16).padStart(2, '0');
        ctx.lineWidth = 1.6;
        ctx.stroke();
      }

      // Centre cross
      ctx.strokeStyle = color + 'cc';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x - 5, y); ctx.lineTo(x + 5, y);
      ctx.moveTo(x, y - 5); ctx.lineTo(x, y + 5);
      ctx.stroke();

      // Label chip
      const code = z.zone_code || 'ZONE';
      const title = z.name && z.name.length > 24 ? z.name.slice(0, 22) + '…' : (z.name || '');
      ctx.font = '700 9px "JetBrains Mono", monospace';
      const codeW = ctx.measureText(`P${z.priority} ${code}`).width;
      ctx.font = '600 11px "Rajdhani", sans-serif';
      const nameW = ctx.measureText(title).width;
      const bw = Math.max(codeW, nameW) + 14;
      const bh = 27;
      // Try the usual spot above the circle, then below, then to either side.
      // Zones cluster tightly in central Delhi, so a fixed position stacks
      // three labels on top of each other.
      const spots = [
        [x - bw / 2, y - r - bh - 6],
        [x - bw / 2, y + r + 6],
        [x + r + 8, y - bh / 2],
        [x - r - bw - 8, y - bh / 2],
      ].filter(([sx, sy]) => sx > 2 && sx + bw < this._w - 2 && sy > 2 && sy + bh < this._h - 2);

      let placed = spots.find(([sx, sy]) => this._claimLabel({ x: sx, y: sy, w: bw, h: bh }));
      if (!placed && spots.length) {
        placed = spots[0];
        this._labelBoxes.push({ x: placed[0], y: placed[1], w: bw, h: bh });
      }

      if (placed) {
        const [bx, drawY] = placed;
        ctx.fillStyle = 'rgba(5,11,19,0.88)';
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(bx, drawY, bw, bh, 4); else ctx.rect(bx, drawY, bw, bh);
        ctx.fill();
        ctx.strokeStyle = color + 'aa'; ctx.lineWidth = 1; ctx.stroke();

        ctx.textAlign = 'center'; ctx.textBaseline = 'top';
        ctx.fillStyle = color;
        ctx.font = '700 9px "JetBrains Mono", monospace';
        ctx.fillText(`P${z.priority} ${code}`, bx + bw / 2, drawY + 3);
        ctx.fillStyle = '#e8eef6';
        ctx.font = '600 11px "Rajdhani", sans-serif';
        ctx.fillText(title, bx + bw / 2, drawY + 13);

        // Leader line when the chip is not sitting directly over the circle.
        if (Math.abs(bx + bw / 2 - x) > bw / 2) {
          ctx.beginPath();
          ctx.moveTo(x, y);
          ctx.lineTo(bx + bw / 2 < x ? bx + bw : bx, drawY + bh / 2);
          ctx.strokeStyle = color + '55';
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }

      this._hits.push({ type: 'zone', id: z.id, x, y, r: Math.max(r, 14), name: z.name });
    }
  }

  _drawRoutes(now) {
    const ctx = this.ctx;
    for (const r of this.data.resources) {
      if (!r.assigned_zone_id || !r.home_base) continue;
      if (r.status !== 'dispatched' && r.status !== 'on_scene') continue;
      const z = this.data.zones.find(zz => zz.id === r.assigned_zone_id);
      if (!z?.boundary?.center) continue;

      const [x1, y1] = this.project(r.home_base.latitude, r.home_base.longitude);
      const [x2, y2] = this.project(z.boundary.center.latitude, z.boundary.center.longitude);
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
      const dx = x2 - x1, dy = y2 - y1;
      const len = Math.hypot(dx, dy) || 1;
      const cpx = mx - dy / len * len * 0.16;
      const cpy = my + dx / len * len * 0.16;
      const color = STATUS_COLORS[r.status] || STATUS_COLORS.dispatched;

      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.quadraticCurveTo(cpx, cpy, x2, y2);
      ctx.strokeStyle = color + '66';
      ctx.lineWidth = 1.4;
      ctx.setLineDash([6, 6]);
      ctx.lineDashOffset = -(now / 45) % 12;
      ctx.stroke();
      ctx.setLineDash([]);

      // Travelling marker
      const t = (now / 3000) % 1;
      const it = 1 - t;
      const px = it * it * x1 + 2 * it * t * cpx + t * t * x2;
      const py = it * it * y1 + 2 * it * t * cpy + t * t * y2;
      ctx.beginPath();
      ctx.arc(px, py, 2.6, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    }
  }

  _drawUnits(now) {
    const ctx = this.ctx;
    const showLabels = this.layers.labels;
    for (const r of this.data.resources) {
      if (!r.home_base) continue;
      const [x, y] = this.project(r.home_base.latitude, r.home_base.longitude);
      if (x < -30 || x > this._w + 30 || y < -30 || y > this._h + 30) continue;

      const key = r.is_uncertain ? 'uncertain' : r.status;
      const color = STATUS_COLORS[key] || STATUS_COLORS.available;
      const selected = this.selection?.type === 'resource' && this.selection.id === r.id;
      const hovered = this.hover?.type === 'resource' && this.hover.id === r.id;
      const rad = selected || hovered ? 11 : 9;

      // Active units get a soft breathing halo.
      if (r.status === 'dispatched' || r.status === 'on_scene') {
        const ph = (now / 1800) % 1;
        ctx.beginPath();
        ctx.arc(x, y, rad + 4 + ph * 12, 0, Math.PI * 2);
        ctx.strokeStyle = color + Math.round((1 - ph) * 110).toString(16).padStart(2, '0');
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }

      ctx.beginPath(); ctx.arc(x, y, rad + 5, 0, Math.PI * 2);
      ctx.fillStyle = color + '22'; ctx.fill();

      ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(6,13,22,0.94)'; ctx.fill();
      ctx.strokeStyle = selected ? '#ffffff' : color;
      ctx.lineWidth = selected ? 2.2 : 1.6;
      ctx.stroke();

      const glyph = TYPE_GLYPHS[r.resource_type] || '📦';
      ctx.font = `${Math.round(rad * 1.15)}px "Segoe UI Emoji", "Apple Color Emoji", sans-serif`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(glyph, x, y + 0.5);

      if (r.is_uncertain) {
        ctx.fillStyle = STATUS_COLORS.uncertain;
        ctx.font = '700 11px "JetBrains Mono", monospace';
        ctx.fillText('?', x + rad + 4, y - rad + 2);
      }

      if (showLabels) {
        const tag = r.callsign || r.name || '';
        ctx.font = '700 9px "JetBrains Mono", monospace';
        const tw = ctx.measureText(tag).width + 9;
        const th = 14;
        const bx = x - tw / 2, by = y + rad + 4;
        if (selected || hovered || this._claimLabel({ x: bx, y: by, w: tw, h: th })) {
          ctx.fillStyle = 'rgba(5,11,19,0.9)';
          ctx.beginPath();
          if (ctx.roundRect) ctx.roundRect(bx, by, tw, th, 3); else ctx.rect(bx, by, tw, th);
          ctx.fill();
          ctx.strokeStyle = color + '88'; ctx.lineWidth = 0.9; ctx.stroke();
          ctx.fillStyle = '#dce6f2';
          ctx.fillText(tag, x, by + th / 2 + 0.5);
        }
      }

      this._hits.push({ type: 'resource', id: r.id, x, y, r: rad + 4, name: r.name });
    }
  }

  _drawSweep(w, h, now) {
    const ctx = this.ctx;
    const cx = w / 2, cy = h / 2;
    const R = Math.hypot(w, h) / 2;
    const angle = (now / 14000) % 1 * Math.PI * 2 - Math.PI / 2;

    ctx.save();
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.clip();

    if (ctx.createConicGradient) {
      const g = ctx.createConicGradient(angle, cx, cy);
      g.addColorStop(0.00, 'rgba(45,212,191,0.00)');
      g.addColorStop(0.97, 'rgba(45,212,191,0.045)');
      g.addColorStop(1.00, 'rgba(45,212,191,0.16)');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    } else {
      for (let i = 0; i < 26; i++) {
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, R, angle - i * 0.035, angle - (i - 1) * 0.035);
        ctx.closePath();
        ctx.fillStyle = `rgba(45,212,191,${0.14 * (1 - i / 26)})`;
        ctx.fill();
      }
    }

    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + R * Math.cos(angle), cy + R * Math.sin(angle));
    ctx.strokeStyle = 'rgba(94,234,212,0.40)';
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.restore();
  }

  _drawReticle(now) {
    const sel = this.selection;
    if (!sel) return;
    const hit = this._hits.find(h => h.type === sel.type && h.id === sel.id);
    if (!hit) return;

    const ctx = this.ctx;
    const R = hit.r + 12 + Math.sin(now / 420) * 2;
    const a = (now / 5200) % 1 * Math.PI * 2;
    ctx.save();
    ctx.translate(hit.x, hit.y);
    ctx.rotate(a);
    ctx.strokeStyle = 'rgba(255,255,255,0.85)';
    ctx.lineWidth = 1.5;
    for (let q = 0; q < 4; q++) {
      ctx.rotate(Math.PI / 2);
      ctx.beginPath();
      ctx.arc(0, 0, R, -0.34, -0.06);
      ctx.stroke();
    }
    ctx.restore();
  }

  _drawFrame(w, h) {
    const ctx = this.ctx;
    ctx.strokeStyle = 'rgba(45,212,191,0.32)';
    ctx.lineWidth = 1.5;
    const L = 18, m = 8;
    const corners = [[m, m, 1, 1], [w - m, m, -1, 1], [m, h - m, 1, -1], [w - m, h - m, -1, -1]];
    for (const [x, y, sx, sy] of corners) {
      ctx.beginPath();
      ctx.moveTo(x + sx * L, y); ctx.lineTo(x, y); ctx.lineTo(x, y + sy * L);
      ctx.stroke();
    }
  }

  _drawCrosshair(w, h) {
    const ctx = this.ctx;
    const p = this._lastPointer;
    if (!p) return;
    ctx.strokeStyle = 'rgba(94,234,212,0.55)';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, p.y); ctx.lineTo(w, p.y);
    ctx.moveTo(p.x, 0); ctx.lineTo(p.x, h);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 9, 0, Math.PI * 2);
    ctx.stroke();
  }

  /* ── Interaction ─────────────────────────────────────────────────────── */

  _local(e) {
    const rect = this.canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  _hitTest(x, y) {
    // Units sit above zones, so walk the list backwards.
    for (let i = this._hits.length - 1; i >= 0; i--) {
      const h = this._hits[i];
      if (h.type !== 'resource') continue;
      if (Math.hypot(x - h.x, y - h.y) <= h.r) return h;
    }
    let best = null, bestR = Infinity;
    for (const h of this._hits) {
      if (h.type !== 'zone') continue;
      const d = Math.hypot(x - h.x, y - h.y);
      if (d <= h.r && h.r < bestR) { best = h; bestR = h.r; }
    }
    return best;
  }

  _bind() {
    const c = this.canvas;

    c.addEventListener('pointerdown', (e) => {
      c.setPointerCapture(e.pointerId);
      this._pointers.set(e.pointerId, this._local(e));
      if (this._pointers.size === 2) {
        const [a, b] = [...this._pointers.values()];
        this._pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y) };
        this._drag = null;
      } else {
        const p = this._local(e);
        this._drag = { ...p, startX: p.x, startY: p.y, moved: 0 };
      }
    });

    c.addEventListener('pointermove', (e) => {
      const p = this._local(e);
      this._lastPointer = p;
      if (this._pointers.has(e.pointerId)) this._pointers.set(e.pointerId, p);

      if (this._pinch && this._pointers.size === 2) {
        const [a, b] = [...this._pointers.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (this._pinch.dist > 0) {
          this.zoomAbout((a.x + b.x) / 2, (a.y + b.y) / 2, d / this._pinch.dist);
        }
        this._pinch.dist = d;
        return;
      }

      if (this._drag) {
        const dx = p.x - this._drag.x, dy = p.y - this._drag.y;
        this._drag.moved += Math.abs(dx) + Math.abs(dy);
        this.center.lng -= dx / (kmPerDegLng(this.center.lat) * this.pxPerKm);
        this.center.lat += dy / (KM_PER_DEG_LAT * this.pxPerKm);
        this._drag.x = p.x; this._drag.y = p.y;
        this._fly = null;
        c.classList.add('is-panning');
        this._notifyView();
        return;
      }

      const hit = this._hitTest(p.x, p.y);
      const changed = (hit?.id || null) !== (this.hover?.id || null);
      this.hover = hit ? { type: hit.type, id: hit.id } : null;
      c.classList.toggle('is-hovering', !!hit && !this.pickMode);
      if (changed || hit) this.opts.onHover?.(hit, e.clientX, e.clientY);
      this.opts.onCursor?.(this.unproject(p.x, p.y));
    });

    const endPointer = (e) => {
      this._pointers.delete(e.pointerId);
      if (this._pointers.size < 2) this._pinch = null;
      c.classList.remove('is-panning');
      const d = this._drag;
      this._drag = null;
      if (!d) return;
      if (d.moved > 6) return;                      // that was a pan, not a click

      const p = this._local(e);
      if (this.pickMode) {
        this.opts.onPick?.(this.unproject(p.x, p.y));
        return;
      }
      const hit = this._hitTest(p.x, p.y);
      this.opts.onSelect?.(hit ? { type: hit.type, id: hit.id } : null);
    };

    c.addEventListener('pointerup', endPointer);
    c.addEventListener('pointercancel', (e) => { this._pointers.delete(e.pointerId); this._drag = null; this._pinch = null; });

    c.addEventListener('pointerleave', () => {
      this.hover = null;
      this._lastPointer = null;
      this.opts.onHover?.(null);
    });

    c.addEventListener('wheel', (e) => {
      e.preventDefault();
      const p = this._local(e);
      this.zoomAbout(p.x, p.y, Math.exp(-e.deltaY * 0.0018));
    }, { passive: false });

    c.addEventListener('dblclick', (e) => {
      const p = this._local(e);
      this.zoomAbout(p.x, p.y, 1.8);
    });

    c.addEventListener('contextmenu', (e) => e.preventDefault());
  }
}
