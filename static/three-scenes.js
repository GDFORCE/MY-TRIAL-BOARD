// Three.js scenes: hero network globe, DNA helix on auth pages, particle wave in the CTA band.
// Each scene keeps one WebGL renderer and moves its canvas into the matching
// [data-three="..."] element whenever app.js re-renders the page.
import * as THREE from './vendor/three.module.min.js';

const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const app = document.getElementById('app');
const COL = {
  coral: new THREE.Color('#ff685b'),
  cream: new THREE.Color('#f4ede0'),
  blue: new THREE.Color('#7d93ff'),
  warm: new THREE.Color('#fff1e6'),
};
const ADD = { transparent: true, depthWrite: false, blending: THREE.AdditiveBlending };

let seed = 20261107; // fixed seed so the globe looks the same on every visit
const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const ease = x => 1 - Math.pow(1 - Math.min(Math.max(x, 0), 1), 3);

const pointer = { x: 0, y: 0 };
addEventListener('pointermove', e => {
  pointer.x = (e.clientX / innerWidth) * 2 - 1;
  pointer.y = (e.clientY / innerHeight) * 2 - 1;
}, { passive: true });

let dotTex;
function dotTexture() {
  if (dotTex) return dotTex;
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d'), grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.22, 'rgba(255,255,255,.95)');
  grd.addColorStop(0.5, 'rgba(255,255,255,.25)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, 64, 64);
  return (dotTex = new THREE.CanvasTexture(c));
}

function points(positions, colors, size, opacity = 1) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  if (colors) g.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  const m = new THREE.PointsMaterial({ size, map: dotTexture(), vertexColors: !!colors, opacity, ...ADD });
  return new THREE.Points(g, m);
}

const FRESNEL_VERT = `varying vec3 vN; varying vec3 vV;
void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0); vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }`;

class Stage {
  constructor(fov) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.75));
    this.renderer.setClearColor(0x000000, 0);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(fov, 1, 0.1, 100);
    this.mount = null; this.visible = false;
    this.born = 0; this.last = 0; this.lastFrame = -1;
    this.px = 0; this.py = 0;
    this.sized = []; // [material, base size] pairs, rescaled in layout()
    this.ro = new ResizeObserver(() => this.resize());
    this.io = new IntersectionObserver(([e]) => { this.visible = e.isIntersecting; });
  }
  attach(el) {
    if (this.mount === el) return;
    const now = performance.now() / 1000;
    if (this.mount) { this.ro.unobserve(this.mount); this.io.unobserve(this.mount); }
    // Replay the intro only for a fresh visit, not when the same page just re-rendered.
    if (now - this.lastFrame > 0.5) this.born = now;
    this.mount = el;
    el.appendChild(this.renderer.domElement);
    this.ro.observe(el);
    this.io.observe(el);
    this.resize();
  }
  resize() {
    const el = this.mount;
    if (!el?.isConnected) return;
    const w = el.clientWidth, h = el.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.layout(w, h);
    this.frame();
  }
  viewSize() {
    const H = 2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * this.camera.position.length();
    return [H * this.camera.aspect, H];
  }
  scaleSizes(k) { for (const [m, s] of this.sized) m.size = s * k; }
  smoothPointer(dt) {
    const k = Math.min(dt * 3, 1);
    this.px += (pointer.x - this.px) * k;
    this.py += (pointer.y - this.py) * k;
  }
  frame(ms = performance.now()) {
    const t = ms / 1000, dt = Math.min(Math.max(t - this.last, 0), 0.05);
    this.last = this.lastFrame = t;
    this.update(t, dt, reduce ? 99 : t - this.born);
    this.renderer.render(this.scene, this.camera);
  }
  layout() {}
  update() {}
}

/* ---------- Hero: interactive research-network globe ---------- */
class Globe extends Stage {
  constructor() {
    super(40);
    this.camera.position.set(0, 0, 7);
    this.root = new THREE.Group();
    this.tilt = new THREE.Group();
    this.spin = new THREE.Group();
    this.tilt.rotation.set(0.2, 0, 0.32);
    this.tilt.add(this.spin);
    this.root.add(this.tilt);
    this.scene.add(this.root);
    this.vel = 0; this.radius = 1; this.baseX = 0; this.baseY = 0; this.wpp = 0.01;

    // Solid core with a glowing rim; hides the far side of the globe.
    this.root.add(new THREE.Mesh(new THREE.SphereGeometry(0.985, 64, 48), new THREE.ShaderMaterial({
      uniforms: { uBase: { value: new THREE.Color('#0d1833') }, uRim: { value: COL.coral.clone().lerp(COL.blue, 0.12) } },
      vertexShader: FRESNEL_VERT,
      fragmentShader: `uniform vec3 uBase; uniform vec3 uRim; varying vec3 vN; varying vec3 vV;
        void main(){ float f = pow(1.0 - max(dot(vN, vV), 0.0), 3.5); gl_FragColor = vec4(mix(uBase, uRim, f * 0.75), 1.0);
        #include <colorspace_fragment>
        }`,
    })));
    // Soft atmosphere halo.
    this.root.add(new THREE.Mesh(new THREE.SphereGeometry(1.3, 64, 48), new THREE.ShaderMaterial({
      uniforms: { uColor: { value: COL.coral.clone().lerp(COL.blue, 0.15) } },
      vertexShader: FRESNEL_VERT,
      fragmentShader: `uniform vec3 uColor; varying vec3 vN; varying vec3 vV;
        void main(){ float i = pow(clamp(-dot(vN, vV), 0.0, 1.0), 2.6) * 1.1; gl_FragColor = vec4(uColor, i);
        #include <colorspace_fragment>
        }`,
      side: THREE.BackSide, ...ADD,
    })));

    // Dotted "continents" from a Fibonacci sphere filtered by a smooth noise field.
    const N = 6000, golden = Math.PI * (3 - Math.sqrt(5)), pos = [], col = [], land = [];
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = golden * i;
      const x = Math.cos(th) * r, z = Math.sin(th) * r;
      const n = Math.sin(x * 4.2 + 1.1) * Math.cos(y * 4.8 - 0.6) + Math.sin(z * 5.1 + y * 2.3 + 2.0) * 0.7 + Math.sin(x * 9.5 - z * 7.3) * 0.3;
      const isLand = n > 0.3; // ~32% of the sphere
      if (!isLand && i % 4) continue;
      pos.push(x, y, z);
      const c = isLand ? COL.cream.clone().lerp(COL.coral, rnd() * 0.3) : COL.blue.clone().multiplyScalar(0.28);
      col.push(c.r, c.g, c.b);
      if (isLand) land.push(new THREE.Vector3(x, y, z));
    }
    const dots = points(pos, col, 0.05);
    this.dotsMat = dots.material;
    this.spin.add(dots);

    // Research hubs, spread out across the land.
    for (let i = land.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [land[i], land[j]] = [land[j], land[i]]; }
    const hubs = [];
    for (const p of land) {
      if (hubs.every(h => h.distanceTo(p) > 0.42)) hubs.push(p);
      if (hubs.length >= 22) break;
    }
    const hubPts = points(hubs.flatMap(h => h.clone().multiplyScalar(1.006).toArray()), null, 0.15);
    hubPts.material.color = COL.coral;
    this.hubMat = hubPts.material;
    this.spin.add(hubPts);

    // Expanding "ping" rings on a few hubs.
    this.pings = hubs.slice(0, 8).map((h, i) => {
      const m = new THREE.Mesh(new THREE.RingGeometry(0.022, 0.03, 40),
        new THREE.MeshBasicMaterial({ color: COL.coral, side: THREE.DoubleSide, ...ADD }));
      m.position.copy(h).multiplyScalar(1.01);
      m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), h.clone().normalize());
      m.userData.off = i * 0.37;
      this.spin.add(m);
      return m;
    });

    // Connection arcs with light pulses running along them.
    const pairs = [];
    hubs.forEach((a, i) => hubs
      .map((b, j) => [a.distanceTo(b), j])
      .filter(([d, j]) => j > i && d > 0.45 && d < 1.5)
      .sort((p, q) => p[0] - q[0]).slice(0, 2)
      .forEach(([, j]) => pairs.push([a, hubs[j]])));
    const SEG = 64, apos = [], aT = [], aOff = [], aSpd = [];
    this.arcs = pairs.slice(0, 30).map(([a, b]) => {
      const lift = 1 + a.distanceTo(b) * 0.42;
      const curve = new THREE.CubicBezierCurve3(
        a.clone().multiplyScalar(1.005),
        a.clone().lerp(b, 0.25).normalize().multiplyScalar(lift),
        a.clone().lerp(b, 0.75).normalize().multiplyScalar(lift),
        b.clone().multiplyScalar(1.005));
      const pts = curve.getPoints(SEG), off = rnd(), spd = 0.16 + rnd() * 0.2;
      for (let s = 0; s < SEG; s++) {
        apos.push(...pts[s].toArray(), ...pts[s + 1].toArray());
        aT.push(s / SEG, (s + 1) / SEG); aOff.push(off, off); aSpd.push(spd, spd);
      }
      return { curve, off, spd };
    });
    const ag = new THREE.BufferGeometry();
    ag.setAttribute('position', new THREE.Float32BufferAttribute(apos, 3));
    ag.setAttribute('aT', new THREE.Float32BufferAttribute(aT, 1));
    ag.setAttribute('aOff', new THREE.Float32BufferAttribute(aOff, 1));
    ag.setAttribute('aSpd', new THREE.Float32BufferAttribute(aSpd, 1));
    this.arcMat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 }, uFade: { value: 0 }, uBase: { value: COL.coral }, uHead: { value: COL.warm } },
      vertexShader: `attribute float aT; attribute float aOff; attribute float aSpd; varying float vT; varying float vOff; varying float vSpd;
        void main(){ vT = aT; vOff = aOff; vSpd = aSpd; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      fragmentShader: `uniform float uTime; uniform float uFade; uniform vec3 uBase; uniform vec3 uHead; varying float vT; varying float vOff; varying float vSpd;
        void main(){
          float head = fract(uTime * vSpd + vOff) * 1.6 - 0.3;
          float d = head - vT;
          float trail = (d > 0.0 && d < 0.3) ? 1.0 - d / 0.3 : 0.0;
          gl_FragColor = vec4(mix(uBase, uHead, trail * trail), (0.14 + trail * 0.9) * uFade);
          #include <colorspace_fragment>
        }`,
      ...ADD,
    });
    this.spin.add(new THREE.LineSegments(ag, this.arcMat));
    this.heads = points(new Array(this.arcs.length * 3).fill(0), null, 0.16);
    this.heads.material.color = COL.warm;
    this.heads.frustumCulled = false;
    this.spin.add(this.heads);

    // Orbit rings with two satellites.
    const ring = (radius, count, size, color, opacity, rot) => {
      const g = new THREE.Group();
      g.rotation.set(...rot);
      const arr = [];
      for (let i = 0; i < count; i++) { const a = (i / count) * Math.PI * 2; arr.push(Math.cos(a) * radius, 0, Math.sin(a) * radius); }
      const p = points(arr, null, size, opacity);
      p.material.color = color;
      g.add(p);
      this.root.add(g);
      this.sized.push([p.material, size]);
      return g;
    };
    this.ring1 = ring(1.55, 260, 0.03, COL.cream, 0.4, [1.2, 0, -0.3]);
    this.ring2 = ring(1.85, 200, 0.024, COL.blue, 0.35, [1.0, 0.5, 0.45]);
    this.sats = points([0, 0, 0, 0, 0, 0], null, 0.17);
    this.sats.material.color = COL.coral;
    this.sats.frustumCulled = false;
    this.ring1.add(this.sats);

    // Background star field.
    const sp = [], sc = [];
    for (let i = 0; i < 900; i++) {
      sp.push((rnd() - 0.5) * 26, (rnd() - 0.5) * 16, -2 - rnd() * 10);
      const c = COL.cream.clone().lerp(COL.blue, rnd());
      sc.push(c.r, c.g, c.b);
    }
    this.stars = points(sp, sc, 0.05, 0.6);
    this.scene.add(this.stars);

    this.sized.push([this.dotsMat, 0.05], [this.hubMat, 0.15], [this.heads.material, 0.16], [this.sats.material, 0.17]);
    this.setupDrag();
  }
  setupDrag() {
    let lastX = null, stage = null;
    addEventListener('pointerdown', e => {
      stage = e.target.closest?.('.hero-stage');
      if (!stage || e.target.closest('.float-chip')) { stage = null; return; }
      lastX = e.clientX;
      stage.classList.add('grabbing');
    });
    addEventListener('pointermove', e => {
      if (lastX === null) return;
      this.vel = Math.max(-6, Math.min(6, this.vel + (e.clientX - lastX) * 0.05));
      lastX = e.clientX;
    }, { passive: true });
    const end = () => { lastX = null; stage?.classList.remove('grabbing'); stage = null; };
    addEventListener('pointerup', end);
    addEventListener('pointercancel', end);
  }
  layout(w, h) {
    const [W, H] = this.viewSize();
    this.wpp = H / h;
    let cx = w * 0.72, cy = h * 0.5, size = Math.min(w, h) * 0.8;
    const stage = this.mount.parentElement?.querySelector('.hero-stage');
    if (stage) {
      const m = this.mount.getBoundingClientRect(), r = stage.getBoundingClientRect();
      cx = r.left - m.left + r.width / 2;
      cy = r.top - m.top + r.height / 2;
      size = Math.min(r.width, r.height);
    }
    this.baseX = (cx / w - 0.5) * W;
    this.baseY = -(cy / h - 0.5) * H;
    this.radius = size * this.wpp * 0.39;
    this.scaleSizes(this.radius);
    this.stars.material.size = 0.05;
  }
  update(t, dt, age) {
    const intro = ease(age / 2.4);
    this.smoothPointer(dt);
    this.vel *= Math.pow(0.08, dt);
    this.spin.rotation.y += dt * (0.12 + this.vel);
    this.root.position.set(this.baseX, this.baseY + scrollY * this.wpp * 0.35, 0);
    this.root.rotation.set(this.py * 0.12, this.px * 0.22, 0);
    this.root.scale.setScalar(this.radius * (0.8 + 0.2 * intro));

    this.dotsMat.opacity = intro;
    this.hubMat.opacity = ease((age - 0.6) / 1.2);
    this.arcMat.uniforms.uTime.value = t;
    this.arcMat.uniforms.uFade.value = ease((age - 1) / 1.4);

    this.pings.forEach(m => {
      const p = (t * 0.55 + m.userData.off) % 1;
      m.scale.setScalar(1 + p * 4);
      m.material.opacity = (1 - p) * 0.8 * this.hubMat.opacity;
    });
    const hp = this.heads.geometry.attributes.position;
    this.arcs.forEach(({ curve, off, spd }, i) => {
      const head = ((t * spd + off) % 1) * 1.6 - 0.3;
      if (head < 0 || head > 1 || age < 1) hp.setXYZ(i, 0, 0, 0); // parked inside the core
      else { const p = curve.getPoint(head); hp.setXYZ(i, p.x, p.y, p.z); }
    });
    hp.needsUpdate = true;

    this.ring1.rotation.y = t * 0.05;
    this.ring2.rotation.y = -t * 0.035;
    const sa = this.sats.geometry.attributes.position;
    for (let k = 0; k < 2; k++) {
      const a = t * 0.3 + k * Math.PI;
      sa.setXYZ(k, Math.cos(a) * 1.55, 0, Math.sin(a) * 1.55);
    }
    sa.needsUpdate = true;

    this.stars.position.set(-this.px * 0.3, this.py * 0.2, 0);
    this.stars.rotation.z = t * 0.01;
  }
}

/* ---------- Auth pages: rotating DNA double helix ---------- */
class Helix extends Stage {
  constructor() {
    super(40);
    this.camera.position.set(0, 0, 10);
    this.outer = new THREE.Group();
    this.inner = new THREE.Group();
    this.outer.rotation.z = 0.22;
    this.outer.add(this.inner);
    this.scene.add(this.outer);

    const N = 370, R = 1, L = 22, turns = 7.3, a = [], b = [], ca = [], cb = [], rung = [], rc = [];
    for (let i = 0; i < N; i++) {
      const f = i / (N - 1), y = (f - 0.5) * L, ang = f * turns * Math.PI * 2;
      const A = new THREE.Vector3(Math.cos(ang) * R, y, Math.sin(ang) * R);
      const B = new THREE.Vector3(Math.cos(ang + Math.PI) * R, y, Math.sin(ang + Math.PI) * R);
      a.push(A.x, A.y, A.z); b.push(B.x, B.y, B.z);
      const k = 0.5 + 0.5 * Math.sin(f * 9);
      const c1 = COL.coral.clone().lerp(COL.warm, k * 0.35), c2 = COL.cream.clone().lerp(COL.blue, k * 0.5);
      ca.push(c1.r, c1.g, c1.b); cb.push(c2.r, c2.g, c2.b);
      if (i % 5 === 0) for (let s = 1; s < 8; s++) {
        const p = A.clone().lerp(B, s / 8), c = COL.coral.clone().lerp(COL.blue, s / 8);
        rung.push(p.x, p.y, p.z); rc.push(c.r, c.g, c.b);
      }
    }
    this.strands = [[a, ca, 0.3, 1], [b, cb, 0.25, 0.9], [rung, rc, 0.11, 0.55]].map(([p, c, size, op]) => {
      const pts = points(p, c, size, op);
      this.inner.add(pts);
      this.sized.push([pts.material, size]);
      return pts;
    });

    const dust = [];
    for (let i = 0; i < 420; i++) dust.push((rnd() - 0.5) * 14, (rnd() - 0.5) * 18, (rnd() - 0.5) * 8);
    this.dust = points(dust, null, 0.06, 0.4);
    this.dust.material.color = COL.cream;
    this.scene.add(this.dust);
  }
  layout() {
    const [W, H] = this.viewSize();
    // Keep the helix in the right third of the panel, clear of the text.
    const s = Math.min(Math.max(W * 0.1, H / (22 * 0.95)), W * 0.13);
    this.outer.scale.setScalar(s);
    this.outer.position.x = W * 0.36;
    this.scaleSizes(s);
  }
  update(t, dt, age) {
    const intro = ease(age / 2.6);
    this.smoothPointer(dt);
    this.strands.forEach(p => p.geometry.setDrawRange(0, Math.ceil(p.geometry.attributes.position.count * intro)));
    this.inner.rotation.y += dt * 0.45;
    this.outer.rotation.x = this.py * 0.15;
    this.outer.rotation.y = this.px * 0.25;
    this.dust.rotation.y = t * 0.03;
    this.dust.material.opacity = 0.4 * intro;
  }
}

/* ---------- CTA band: flowing particle wave ---------- */
class Wave extends Stage {
  constructor() {
    super(50);
    this.camera.position.set(0, 2.6, 7);
    this.camera.lookAt(0, -0.3, 0);
    const COLS = 170, ROWS = 34, SP = 0.17;
    this.n = COLS * ROWS;
    this.base = new Float32Array(this.n * 2);
    const pos = new Float32Array(this.n * 3);
    for (let r = 0, i = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++, i++) {
      const x = (c - (COLS - 1) / 2) * SP, z = (r - (ROWS - 1) / 2) * SP;
      this.base[i * 2] = x; this.base[i * 2 + 1] = z;
      pos[i * 3] = x; pos[i * 3 + 2] = z;
    }
    this.field = points(pos, new Float32Array(this.n * 3), 0.07, 0.9);
    this.field.frustumCulled = false;
    this.scene.add(this.field);
    this.sized.push([this.field.material, 1]);
    this.tmp = new THREE.Color();
  }
  layout(w, h) { this.scaleSizes(44 / h); }
  update(t, dt, age) {
    this.smoothPointer(dt);
    const intro = ease(age / 2);
    const pos = this.field.geometry.attributes.position, col = this.field.geometry.attributes.color;
    const pa = pos.array, ca = col.array, c = this.tmp, lift = 0.25 + this.px * 0.1;
    for (let i = 0; i < this.n; i++) {
      const x = this.base[i * 2], z = this.base[i * 2 + 1];
      const y = (Math.sin(x * 0.45 + t * 0.9) * 0.35 + Math.cos(z * 0.8 + t * 0.7 + x * 0.18) * 0.22 + Math.sin((x + z) * 0.3 - t * 0.5) * lift) * intro;
      pa[i * 3 + 1] = y;
      const k = Math.min(Math.max((y + 0.7) / 1.4, 0), 1);
      if (k < 0.5) c.copy(COL.blue).lerp(COL.coral, k * 2); else c.copy(COL.coral).lerp(COL.warm, (k - 0.5) * 2);
      ca[i * 3] = c.r; ca[i * 3 + 1] = c.g; ca[i * 3 + 2] = c.b;
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
  }
}

/* ---------- Mounting + render loop ---------- */
const factories = { globe: Globe, helix: Helix, wave: Wave };
const stages = new Map();
let failed = false;
const html = document.documentElement;

function mountAll() {
  if (failed) return;
  app.querySelectorAll('[data-three]').forEach(el => {
    const kind = el.dataset.three, Ctor = factories[kind];
    if (!Ctor) return;
    let s = stages.get(kind);
    if (!s) {
      try { s = new Ctor(); stages.set(kind, s); }
      catch (err) {
        failed = true;
        html.classList.remove('has-three');
        html.classList.add('no-three');
        console.warn('3D scenes disabled:', err);
        return;
      }
    }
    s.attach(el);
  });
}

function loop(ms) {
  requestAnimationFrame(loop);
  for (const s of stages.values()) if (s.visible && s.mount?.isConnected) s.frame(ms);
}

html.classList.add('has-three');
new MutationObserver(mountAll).observe(app, { childList: true });
mountAll();
document.fonts?.ready.then(() => stages.forEach(s => s.resize()));
if (!reduce) requestAnimationFrame(loop);
