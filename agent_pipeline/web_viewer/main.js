import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { PLYLoader } from "three/addons/loaders/PLYLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

// ---------------------------------------------------------------------------------------
// Assets: data/scenes/<scene>/export/<scene>_{baked,rebuild,scan}.glb, _points.ply, _trajectory.json
// (all in glTF axes: Y up, metres). ?scene=<name> picks another export.
const params = new URLSearchParams(location.search);
const NAME = params.get("scene") || "home_living";
const BASE = `/data/scenes/${NAME}/export/${NAME}`;
const EYE = 1.6;
const LIGHT_SCALE = 0.01;          // glTF light intensities -> plausible household bulbs

const $ = (id) => document.getElementById(id);
document.title = `${NAME.replace(/_/g, " ")} · LingBot Room Viewer`;
$("title").textContent = NAME.replace(/_/g, " ");

// ---- Renderer / scene ------------------------------------------------------------------
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.AgXToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
$("view").appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b0c0e);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.12;

const camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.03, 200);
camera.position.set(-1.2, EYE, 0.05);
const orbit = new OrbitControls(camera, renderer.domElement);
orbit.target.set(1.2, 1.0, 0.0);
orbit.enableDamping = true;
orbit.update();
const walk = new PointerLockControls(camera, document.body);

const ceilingClip = new THREE.Plane(new THREE.Vector3(0, -1, 0), 2.5);
renderer.clippingPlanes = [];

addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

// ---- Status ----------------------------------------------------------------------------
let statusTimer;
function status(msg, sticky = false) {
  const el = $("status");
  el.textContent = msg;
  el.style.opacity = 1;
  clearTimeout(statusTimer);
  if (!sticky) statusTimer = setTimeout(() => (el.style.opacity = 0), 2500);
}

// ---- Helpers ---------------------------------------------------------------------------
const gltfLoader = new GLTFLoader();
const plyLoader = new PLYLoader();
const settings = { exposure: 1, lights: 1, psize: 3 };
const liveLights = [];
const basicMats = new Set();      // baked / vertex-colour materials (exposure applied by hand)
const pointMats = new Set();

function srgbToLinear(attr) {
  const c = new THREE.Color();
  for (let i = 0; i < attr.count; i++) {
    c.setRGB(attr.getX(i), attr.getY(i), attr.getZ(i), THREE.SRGBColorSpace);
    attr.setXYZ(i, c.r, c.g, c.b);   // three stores colours linear internally
  }
  attr.needsUpdate = true;
}

function basic(params) {
  const m = new THREE.MeshBasicMaterial({ ...params, toneMapped: false });
  m.userData.base = 1;
  basicMats.add(m);
  m.color.setScalar(settings.exposure);
  return m;
}

function frame(obj) {
  const box = new THREE.Box3().setFromObject(obj);
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3());
  const r = box.getSize(new THREE.Vector3()).length() / 2;
  camera.position.copy(c).add(new THREE.Vector3(r * 0.6, r * 0.8, r * 0.9));
  orbit.target.copy(c);
  orbit.update();
}

function progress(label) {
  return (e) => e.total && status(`${label} ${Math.round((100 * e.loaded) / e.total)}%`, true);
}

// ---- Layers ----------------------------------------------------------------------------
const layers = [
  { id: "baked", label: "Rebuild · baked lighting", url: `${BASE}_baked.glb`, kind: "baked", on: true },
  { id: "pbr", label: "Rebuild · live PBR", url: `${BASE}_rebuild.glb`, kind: "pbr", on: false },
  { id: "scan", label: "Scan mesh (fused)", url: `${BASE}_scan.glb`, kind: "scan", on: false },
  { id: "points", label: "Point cloud", url: `${BASE}_points.ply`, kind: "points", on: false },
  { id: "path", label: "Video camera path", url: `${BASE}_trajectory.json`, kind: "path", on: true },
];

async function loadLayer(L) {
  status(`Loading ${L.label}…`, true);
  if (L.kind === "points") {
    const g = await plyLoader.loadAsync(L.url, progress(L.label));
    return pointsFrom(g, L);
  }
  if (L.kind === "path") {
    const data = await (await fetch(L.url)).json();
    return pathFrom(data, L);
  }
  const gltf = await gltfLoader.loadAsync(L.url, progress(L.label));
  const root = gltf.scene;
  root.traverse((o) => {
    if (!o.isMesh) return;
    if (L.kind === "baked" && o.material.name === "Baked lighting") {
      o.material = basic({ map: o.material.map || o.material.emissiveMap });
    } else if (L.kind === "scan") {
      if (o.geometry.attributes.color) srgbToLinear(o.geometry.attributes.color);
      o.material = basic({ vertexColors: true, side: THREE.DoubleSide });
    } else if (L.kind === "pbr") {
      o.castShadow = o.receiveShadow = true;
      const m = o.material;
      if (m.sheen > 0) {             // Blender exports a white full-strength sheen; tint it with the fabric
        m.sheenColor.copy(m.color).multiplyScalar(0.6);
        m.sheenRoughness = 0.8;
      }
    }
  });
  if (L.kind === "pbr") setupLights(root);
  L.cameras = gltf.cameras;
  L.info = `${countTris(root).toLocaleString()} tris`;
  return root;
}

function countTris(root) {
  let n = 0;
  root.traverse((o) => {
    if (o.isMesh) n += (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count) / 3;
  });
  return Math.round(n);
}

function pointsFrom(g, L) {
  if (g.attributes.color) srgbToLinear(g.attributes.color);
  const m = new THREE.PointsMaterial({ size: settings.psize, sizeAttenuation: false, vertexColors: !!g.attributes.color, toneMapped: false });
  pointMats.add(m);
  L.info = `${g.attributes.position.count.toLocaleString()} pts`;
  return new THREE.Points(g, m);
}

function pathFrom(data, L) {
  const grp = new THREE.Group();
  const pts = data.frames.map((f) => new THREE.Vector3(...f.p));
  const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({ color: 0xe3a35b, toneMapped: false }));
  grp.add(line);
  const cone = new THREE.ConeGeometry(0.035, 0.08, 4).rotateX(-Math.PI / 2);
  const mat = new THREE.MeshBasicMaterial({ color: 0xe3a35b, wireframe: true, toneMapped: false });
  data.frames.forEach((f, i) => {
    if (i % 8) return;
    const m = new THREE.Mesh(cone, mat);
    m.position.set(...f.p);
    m.lookAt(m.position.clone().sub(new THREE.Vector3(...f.f)));
    grp.add(m);
  });
  L.data = data;
  L.info = `${data.frames.length} poses`;
  return grp;
}

function setupLights(root) {
  let shadows = 0;
  root.traverse((o) => {
    if (!o.isLight) return;
    // Blender's exporter maps radiometric watts to candela (W * 683 / 4pi); a 70 W Blender
    // point light becomes ~3800 cd, far brighter than the bulb it stands for.
    o.userData.base = o.intensity * LIGHT_SCALE;
    o.intensity = o.userData.base * settings.lights;
    liveLights.push(o);
    if ((o.isSpotLight || /Floor_lamp/i.test(o.name)) && shadows < 4) {
      o.castShadow = true;
      o.shadow.mapSize.set(1024, 1024);
      o.shadow.bias = -0.0005;
      o.shadow.radius = 4;
      shadows++;
    }
  });
  // glTF has no area lights: stand-in for the TV glow
  const tv = new THREE.PointLight(0x8fa6ff, 0.6, 0, 2);
  tv.position.set(0.05, 0.86, 1.7);
  tv.userData.base = tv.intensity;
  root.add(tv);
  liveLights.push(tv);
}

function layerRow(L) {
  const row = document.createElement("label");
  row.className = "row";
  row.innerHTML = `<input type="checkbox" ${L.on ? "checked" : ""}> <span>${L.label}</span> <small></small>`;
  const box = row.querySelector("input");
  L.small = row.querySelector("small");
  box.addEventListener("change", () => setLayer(L, box.checked));
  L.box = box;
  $("layers").appendChild(row);
}

async function setLayer(L, on) {
  L.on = on;
  if (on && !L.obj && !L.loading) {
    L.loading = true;
    L.small.textContent = "loading…";
    try {
      L.obj = L.obj || (await loadLayer(L));
      if (L.upaxis) applyUp(L.obj, L.upaxis);
      scene.add(L.obj);
      L.small.textContent = L.info || "";
      status(`${L.label}: ${L.info || "loaded"}`);
      if (L.cameras && L.cameras.length) addViewpoints(L);
      if (L.frameOnLoad) frame(L.obj);
    } catch (e) {
      console.error(e);
      L.small.textContent = "missing";
      L.box.checked = false;
      L.on = false;
      status(`Could not load ${L.label} (${L.url})`);
    } finally {
      L.loading = false;
    }
  }
  if (L.obj) L.obj.visible = L.on;
}

// ---- Viewpoints from the Blender cameras -----------------------------------------------
let viewpointsAdded = false;
function addViewpoints(L) {
  if (viewpointsAdded) return;
  viewpointsAdded = true;
  const sel = $("viewpoint");
  L.cameras.forEach((cam, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = (cam.name || `Camera ${i}`).replace(/_/g, " ");
    sel.appendChild(opt);
  });
  sel.onchange = () => {
    if (sel.value === "") return;
    const cam = L.cameras[+sel.value];
    cam.updateWorldMatrix(true, false);
    const p = new THREE.Vector3(), q = new THREE.Quaternion();
    cam.matrixWorld.decompose(p, q, new THREE.Vector3());
    camera.position.copy(p);
    const dir = new THREE.Vector3(0, 0, -1).applyQuaternion(q);
    orbit.target.copy(p).add(dir.multiplyScalar(2));
    orbit.update();
  };
  if (!params.has("nocam")) {
    sel.value = "0";
    sel.onchange();
  }
}

// ---- Video path fly-through -------------------------------------------------------------
let fly = null;
$("fly").onclick = async () => {
  const L = layers.find((l) => l.id === "path");
  if (!L.obj) await setLayer(L, true);
  if (!L.data) return;
  if (fly) { fly = null; $("fly").textContent = "Play video path"; orbit.enabled = true; return; }
  const P = L.data.frames.map((f) => new THREE.Vector3(...f.p));
  const F = L.data.frames.map((f) => new THREE.Vector3(...f.f));
  // smooth view directions a little (handheld video)
  const Fs = F.map((_, i) => {
    const v = new THREE.Vector3();
    for (let k = -3; k <= 3; k++) v.add(F[Math.min(F.length - 1, Math.max(0, i + k))]);
    return v.normalize();
  });
  fly = { curve: new THREE.CatmullRomCurve3(P), F: Fs, t0: performance.now(), dur: P.length * 0.2 * 1000 / 2 };
  L.obj.visible = false;
  orbit.enabled = false;
  $("fly").textContent = "Stop";
};

function updateFly() {
  const t = Math.min(1, Math.max(0, (performance.now() - fly.t0) / fly.dur));
  const p = fly.curve.getPointAt(t);
  const fi = t * (fly.F.length - 1), i = Math.floor(fi), w = fi - i;
  const f = fly.F[i].clone().lerp(fly.F[Math.min(i + 1, fly.F.length - 1)], w).normalize();
  camera.position.copy(p);
  camera.lookAt(p.clone().add(f));
  if (t >= 1) {
    orbit.target.copy(p).add(f.multiplyScalar(1.5));
    orbit.enabled = true;
    fly = null;
    $("fly").textContent = "Play video path";
    const L = layers.find((l) => l.id === "path");
    if (L.obj) L.obj.visible = L.on;
  }
}

// ---- Walk mode -------------------------------------------------------------------------
const keys = {};
addEventListener("keydown", (e) => (keys[e.code] = true));
addEventListener("keyup", (e) => (keys[e.code] = false));
$("walk").onclick = () => walk.lock();
walk.addEventListener("lock", () => { orbit.enabled = false; camera.position.y = EYE; status("Walk mode — WASD to move, Esc to exit"); });
walk.addEventListener("unlock", () => {
  orbit.enabled = true;
  const d = new THREE.Vector3();
  camera.getWorldDirection(d);
  orbit.target.copy(camera.position).add(d.multiplyScalar(1.5));
  orbit.update();
});
function updateWalk(dt) {
  const v = 1.4 * dt * (keys.ShiftLeft ? 2 : 1);
  if (keys.KeyW) walk.moveForward(v);
  if (keys.KeyS) walk.moveForward(-v);
  if (keys.KeyA) walk.moveRight(-v);
  if (keys.KeyD) walk.moveRight(v);
  if (keys.KeyE) camera.position.y += v;
  if (keys.KeyQ) camera.position.y -= v;
}

// ---- Display controls ------------------------------------------------------------------
function bindSlider(id, fmt, fn) {
  const el = $(id), out = $(id + "V");
  const upd = () => { out.textContent = fmt(+el.value); fn(+el.value); };
  el.addEventListener("input", upd);
  upd();
}
bindSlider("exposure", (v) => v.toFixed(2), (v) => {
  settings.exposure = v;
  renderer.toneMappingExposure = v;
  basicMats.forEach((m) => m.color.setScalar(v));
});
bindSlider("lights", (v) => v.toFixed(2), (v) => {
  settings.lights = v;
  liveLights.forEach((l) => (l.intensity = l.userData.base * v));
});
bindSlider("psize", (v) => v.toFixed(1), (v) => {
  settings.psize = v;
  pointMats.forEach((m) => (m.size = v));
});
$("cutCeiling").onchange = (e) => (renderer.clippingPlanes = e.target.checked ? [ceilingClip] : []);
$("toggle").onclick = () => {
  $("panel").classList.toggle("collapsed");
  $("toggle").textContent = $("panel").classList.contains("collapsed") ? "+" : "–";
};

// ---- Drag & drop / file picker (any PLY / GLB) ------------------------------------------
function applyUp(obj, axis) {
  obj.rotation.set(axis === "z" ? -Math.PI / 2 : axis === "cv" ? Math.PI : 0, 0, 0);
}

async function openFile(file) {
  const ext = file.name.split(".").pop().toLowerCase();
  const url = URL.createObjectURL(file);
  const L = { id: `file-${file.name}`, label: file.name, url, on: true, frameOnLoad: true, upaxis: $("upaxis").value };
  L.kind = ext === "ply" ? "userply" : "usergltf";
  L.load = async () => {
    if (ext === "ply") {
      const g = await plyLoader.loadAsync(url, progress(file.name));
      if (g.index) {
        if (g.attributes.color) srgbToLinear(g.attributes.color);
        if (!g.attributes.normal) g.computeVertexNormals();
        const mat = g.attributes.color ? basic({ vertexColors: true, side: THREE.DoubleSide })
          : new THREE.MeshStandardMaterial({ color: 0xcccccc, side: THREE.DoubleSide });
        L.info = `${(g.index.count / 3).toLocaleString()} tris`;
        return new THREE.Mesh(g, mat);
      }
      return pointsFrom(g, L);
    }
    const gltf = await gltfLoader.loadAsync(url, progress(file.name));
    L.info = `${countTris(gltf.scene).toLocaleString()} tris`;
    return gltf.scene;
  };
  layers.push(L);
  layerRow(L);
  L.obj = await L.load().catch((e) => { status(`Could not open ${file.name}: ${e.message}`); return null; });
  if (!L.obj) return;
  applyUp(L.obj, L.upaxis);
  scene.add(L.obj);
  L.small.textContent = L.info || "";
  frame(L.obj);
  status(`${file.name}: ${L.info}`);
}

const drop = $("drop");
addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
addEventListener("dragleave", () => drop.classList.remove("over"));
addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  [...e.dataTransfer.files].forEach(openFile);
});
$("pick").onclick = (e) => { e.preventDefault(); $("file").click(); };
$("file").onchange = (e) => [...e.target.files].forEach(openFile);
$("upaxis").onchange = (e) => layers.filter((l) => l.upaxis && l.obj).forEach((l) => { l.upaxis = e.target.value; applyUp(l.obj, l.upaxis); });

// ---- Boot ------------------------------------------------------------------------------
layers.forEach(layerRow);
(async () => {
  for (const L of layers) if (L.on) await setLayer(L, true);
  // the PBR file carries the Blender cameras (viewpoints); fetch it hidden if not shown
  const pbr = layers.find((l) => l.id === "pbr");
  if (!pbr.obj) {
    try {
      const gltf = await gltfLoader.loadAsync(pbr.url);
      pbr.cameras = gltf.cameras;
      addViewpoints(pbr);
    } catch (e) { /* no rebuild export */ }
  }
  if (!layers.some((l) => l.obj)) status("No exports found — drop a .ply or .glb file", true);
  else status("Ready");
})();

const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const dt = clock.getDelta();
  if (fly) updateFly();
  else if (walk.isLocked) updateWalk(dt);
  else orbit.update();
  renderer.render(scene, camera);
});
