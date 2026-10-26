"""Write a local HTML page for one concept-map response and open it."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import webbrowser

from importlib.resources import files

from .types import ClientError

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Membrain map</title>
<style>
  html, body { margin: 0; height: 100%; background: #111; color: #eee; font: 14px/1.4 sans-serif; }
  #scene { position: absolute; inset: 0 280px 0 0; }
  #side { position: absolute; top: 0; right: 0; bottom: 0; width: 280px; overflow: auto;
          border-left: 1px solid #333; padding: 12px; box-sizing: border-box; }
  #side h1 { font-size: 16px; margin: 0 0 8px; }
  #note { color: #aaa; font-size: 12px; margin-bottom: 12px; }
  button.item, .unplaced { display: block; width: 100%; text-align: left; background: #1c1c1c;
    color: inherit; border: 1px solid #333; padding: 6px 8px; margin: 0 0 6px; cursor: pointer; }
  button.item.active { border-color: #ddd; }
  #detail { margin-top: 16px; white-space: pre-wrap; }
  label { display: block; margin: 8px 0; font-size: 12px; color: #ccc; }
</style>
</head>
<body>
<div id="scene"></div>
<aside id="side">
  <h1>Saved explanations</h1>
  <div id="note"></div>
  <label><input type="checkbox" id="similar"> Show similarity links</label>
  <div id="list"></div>
  <div id="detail">Click a point or a name to read the saved explanation.</div>
</aside>
<script>window.MAP = __DATA__;</script>
<script src="three.min.js"></script>
<script>
const map = window.MAP;
const placed = map.nodes.filter(n => n.position);
const unplaced = map.nodes.filter(n => !n.position);
document.getElementById('note').textContent = map.layout.meaning +
  (map.vector_status === 'vectors_pending' ? ' Some explanations are still being placed.' : '') +
  (unplaced.length ? ' ' + unplaced.length + ' without a vector are listed only.' : '');

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x111111);
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 1000);
const renderer = new THREE.WebGLRenderer({ antialias: true });
document.getElementById('scene').appendChild(renderer.domElement);
const group = new THREE.Group();
scene.add(group);
scene.add(new THREE.AmbientLight(0xffffff, 0.8));

const meshes = {};
const colour = new THREE.Color(0x88aacc);
placed.forEach(node => {
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.08, 16, 16),
    new THREE.MeshLambertMaterial({ color: colour }));
  mesh.position.set(node.position.x, node.position.y, node.position.z || 0);
  mesh.userData.id = node.id;
  group.add(mesh);
  meshes[node.id] = mesh;
});
const confirmed = new THREE.Group();
map.confirmed_edges.forEach(edge => {
  const a = meshes[edge.source], b = meshes[edge.target];
  if (!a || !b) return;
  const geom = new THREE.BufferGeometry().setFromPoints([a.position.clone(), b.position.clone()]);
  confirmed.add(new THREE.Line(geom, new THREE.LineBasicMaterial({ color: 0xcccccc })));
});
group.add(confirmed);
const similar = new THREE.Group();
similar.visible = false;
(map.similarity_candidates || []).forEach(edge => {
  const a = meshes[edge.source], b = meshes[edge.target];
  if (!a || !b) return;
  const geom = new THREE.BufferGeometry().setFromPoints([a.position.clone(), b.position.clone()]);
  similar.add(new THREE.Line(geom, new THREE.LineDashedMaterial({ color: 0x666666, dashSize: 0.08, gapSize: 0.06 })));
});
similar.children.forEach(line => { line.computeLineDistances(); });
group.add(similar);
document.getElementById('similar').onchange = event => { similar.visible = event.target.checked; };

const list = document.getElementById('list');
const buttons = {};
function show(id) {
  const node = map.nodes.find(n => n.id === id);
  document.getElementById('detail').textContent = (node.label || '') + '\\n\\n' + (node.excerpt || 'No saved explanation.');
  Object.values(buttons).forEach(b => b.classList.remove('active'));
  if (buttons[id]) buttons[id].classList.add('active');
  Object.values(meshes).forEach(m => m.material.color.set(0x88aacc));
  if (meshes[id]) meshes[id].material.color.set(0xffffff);
}
map.nodes.forEach(node => {
  if (!node.position) {
    const p = document.createElement('div');
    p.className = 'unplaced';
    p.textContent = node.label + ' (not yet placed)';
    p.onclick = () => show(node.id);
    list.appendChild(p);
    buttons[node.id] = p;
    return;
  }
  const button = document.createElement('button');
  button.className = 'item';
  button.textContent = node.label;
  button.onclick = () => show(node.id);
  list.appendChild(button);
  buttons[node.id] = button;
});

let theta = 0.7, phi = 1.1, radius = 4, dragging = false, lastX = 0, lastY = 0;
function fit() {
  if (!placed.length) { radius = 4; return; }
  let max = 0.5;
  placed.forEach(n => {
    const p = n.position;
    max = Math.max(max, Math.hypot(p.x, p.y, p.z || 0));
  });
  radius = max * 3.2;
}
fit();
function placeCamera() {
  camera.position.set(radius * Math.sin(phi) * Math.cos(theta),
                      radius * Math.cos(phi),
                      radius * Math.sin(phi) * Math.sin(theta));
  camera.lookAt(0, 0, 0);
}
function resize() {
  const box = document.getElementById('scene').getBoundingClientRect();
  camera.aspect = box.width / Math.max(box.height, 1);
  camera.updateProjectionMatrix();
  renderer.setSize(box.width, box.height);
}
window.addEventListener('resize', resize);
resize();
const canvas = renderer.domElement;
canvas.addEventListener('pointerdown', event => { dragging = true; lastX = event.clientX; lastY = event.clientY; });
window.addEventListener('pointerup', () => { dragging = false; });
window.addEventListener('pointermove', event => {
  if (!dragging) return;
  theta -= (event.clientX - lastX) * 0.01;
  phi = Math.min(Math.max(0.12, phi + (event.clientY - lastY) * 0.01), Math.PI - 0.12);
  lastX = event.clientX; lastY = event.clientY;
});
canvas.addEventListener('wheel', event => {
  event.preventDefault();
  radius = Math.min(Math.max(0.4, radius * (event.deltaY > 0 ? 1.08 : 0.92)), 80);
}, { passive: false });
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
canvas.addEventListener('click', event => {
  const box = canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - box.left) / box.width) * 2 - 1;
  pointer.y = -((event.clientY - box.top) / box.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(Object.values(meshes))[0];
  if (hit) show(hit.object.userData.id);
});
function tick() {
  placeCamera();
  renderer.render(scene, camera);
  requestAnimationFrame(tick);
}
tick();
</script>
</body>
</html>
"""


def write_map(data: dict, directory: Path | None = None, opener=webbrowser.open) -> Path:
    """Write data into map.html beside vendored three.min.js and open it."""
    root = directory or Path(os.getenv("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "membrain" / "map"
    root.mkdir(parents=True, exist_ok=True)
    source = files("membrain_cli").joinpath("static/three.min.js")
    if not source.is_file():
        raise ClientError("The map page is missing its local three.js copy.")
    shutil.copyfile(source, root / "three.min.js")
    page = PAGE.replace("__DATA__", json.dumps(data, default=str))
    path = root / "map.html"
    path.write_text(page, encoding="utf-8")
    opener(path.as_uri())
    return path
