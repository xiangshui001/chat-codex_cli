import * as T from './vendor/three.module.js';
import {buildArchitecture} from './architecture.js';
import {LIBRARY_CAMERA_PATHS, createCameraPath} from './camera-paths.js';

/** Embeddable camera-path viewer. No player, walking input or collision loop. */
export function mountLibrary(host, options = {}) {
  if (!host) throw new Error('A container is required');
  const keyboard = options.keyboard ?? 'focus';
  if (!['focus', 'global', 'off'].includes(keyboard)) throw new Error('Invalid keyboard mode');
  const paths = new Map(Object.entries({...LIBRARY_CAMERA_PATHS, ...options.cameraPaths}).map(([name, points]) => [name, createCameraPath(points)]));
  const pixelRatio = T.MathUtils.clamp(Number(options.maxPixelRatio) || 1.6, .5, 2);
  const frameOffset = Number(options.frameOffset) || 0;
  const renderer = new T.WebGLRenderer({antialias: true, powerPreference: 'high-performance'});
  renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio || 1, pixelRatio));
  renderer.shadowMap.enabled = options.shadows !== false;
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  renderer.toneMapping = T.ACESFilmicToneMapping;
  host.appendChild(renderer.domElement);

  const scene = new T.Scene();
  scene.background = new T.Color('#b6cbd7');
  scene.fog = new T.Fog('#b6cbd7', 115, 210);
  const camera = new T.PerspectiveCamera(43, 1, .1, 250);
  camera.rotation.order = 'YXZ';
  const hemi = new T.HemisphereLight('#e6f2ff', '#a08c6f', 1.45);
  const sun = new T.DirectionalLight('#ffe4b5', 3.2);
  const fill = new T.DirectionalLight('#b6d1f0', .55);
  sun.position.set(-35, 60, 40);
  fill.position.set(26, 24, -28);
  sun.castShadow = options.shadows !== false;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, {left: -37, right: 37, top: 43, bottom: -32, near: 1, far: 150});
  sun.shadow.normalBias = .065;
  scene.add(hemi, sun, fill);
  const building = buildArchitecture(scene);
  const exteriorTarget = new T.Vector3(0, 13, 0);
  const canvas = renderer.domElement;
  canvas.tabIndex = 0;
  canvas.style.touchAction = 'none';
  canvas.setAttribute?.('aria-label', '体素图书馆：拖动查看，馆内沿预设镜头路线参观');

  let width = 1, height = 1, mode = 'outside', floor = 0, night = false, cutaway = false;
  let theta = .6, phi = 1.14, distance = 94, path = null, disposed = false, paused = false;
  let raf = 0, last = performance.now(), stateElapsed = 0;
  let previousX = 0, previousY = 0, pinch = 0;
  const pointers = new Map(), handlers = [];

  function getState() {
    return {
      mode, floor, position: camera.position.toArray(), yaw: camera.rotation.y, pitch: camera.rotation.x,
      night, cutaway, paused, transitioning: !!path?.playing,
      path: path?.name ?? null, pathLabel: path?.label ?? '',
      pathPlaying: !!path?.playing, pathProgress: path ? path.elapsed / path.route.duration : 0,
      pathDuration: path?.route.duration ?? 0, ...building.stats
    };
  }
  function emit() { options.onStateChange?.(getState()); }
  function lighting() {
    const indoors = mode === 'inside';
    hemi.intensity = night ? (indoors ? .58 : .72) : (indoors ? 1.12 : 1.45);
    hemi.color.set(indoors ? '#d4e0ed' : '#e6f2ff');
    hemi.groundColor.set(indoors ? '#936449' : '#a08c6f');
    sun.intensity = night ? .72 : 3.2;
    sun.color.set(night ? '#97b5f2' : '#ffe4b5');
    fill.intensity = night ? .26 : .55;
    renderer.toneMappingExposure = indoors ? 1.26 : night ? 1.22 : 1.17;
    building.lights.forEach((light, i) => light.intensity = i < 2 ? (night ? 26 : 12) : i < 4 ? (night ? 175 : 125) : (night ? 26 : 14));
  }
  function resize() {
    width = Math.max(1, host.clientWidth);
    height = Math.max(1, host.clientHeight);
    renderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  resize();
  distance = width < 760 ? 110 : 94;

  function applyPath() {
    const sample = path.route.sample(path.elapsed);
    camera.position.fromArray(sample.position);
    camera.lookAt(...sample.target);
    floor = sample.floor;
    path.label = sample.label;
  }
  function setCameraPath(name, waypoints) {
    if (typeof name !== 'string' || !name) throw new Error('A path name is required');
    paths.set(name, createCameraPath(waypoints));
  }
  function playPath(name = 'tour') {
    let route = paths.get(name);
    if (!route) throw new Error('Unknown camera path: ' + name);
    // The entrance and whole-library tour approach the open portal from the exterior.
    if (mode === 'outside' && (name === 'entrance' || name === 'tour')) {
      route = createCameraPath([
        {position: camera.position.toArray(), target: exteriorTarget.toArray(), floor: 0, label: '走近图书馆'},
        {position: [camera.position.x, Math.max(52, camera.position.y), camera.position.z], target: [0, 16, 0], duration: 1.5, floor: 0, label: '掠过尖顶'},
        {position: [0, 52, 32], target: [0, 13, 0], duration: 2.5, floor: 0, label: '转向门厅'},
        ...route.points.map((point, i) => ({...point, duration: i === 0 ? 3 : point.duration}))
      ]);
    }
    mode = 'inside';
    path = {name, route, elapsed: 0, playing: true, label: ''};
    pointers.clear();
    camera.clearViewOffset();
    canvas.focus?.({preventScroll: true});
    applyPath();
    lighting();
    emit();
  }
  function enter(view = 'entrance') { playPath(view); }
  function pausePath() {
    if (!path?.playing) return;
    path.playing = false;
    emit();
  }
  function resumePath() {
    if (!path || path.playing) return;
    if (path.elapsed >= path.route.duration) path.elapsed = 0;
    path.playing = true;
    applyPath();
    emit();
  }
  function seekPath(progress) {
    if (!Number.isFinite(progress)) throw new Error('Invalid camera progress');
    if (!path) return;
    path.elapsed = T.MathUtils.clamp(progress, 0, 1) * path.route.duration;
    path.playing = false;
    applyPath();
    emit();
  }
  function exterior() {
    mode = 'outside';
    path = null;
    floor = 0;
    theta = .6; phi = 1.14; distance = width < 760 ? 110 : 94;
    pointers.clear();
    lighting();
    emit();
  }
  function setNight(value) {
    night = !!value;
    scene.background.set(night ? '#101d33' : '#b6cbd7');
    scene.fog.color.copy(scene.background);
    lighting();
    emit();
  }
  function setCutaway(value) {
    cutaway = !!value;
    building.setCutaway(cutaway);
    emit();
  }
  function turn(deltaYaw, deltaPitch = 0) {
    pausePath();
    camera.rotation.y += deltaYaw;
    camera.rotation.x = T.MathUtils.clamp(camera.rotation.x + deltaPitch, -1.15, 1.2);
  }
  function on(target, name, handler, settings) {
    target.addEventListener(name, handler, settings);
    handlers.push(() => target.removeEventListener(name, handler, settings));
  }

  on(canvas, 'pointerdown', event => {
    canvas.focus?.({preventScroll: true});
    if (mode === 'inside') pausePath();
    pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
    canvas.setPointerCapture(event.pointerId);
    previousX = event.clientX; previousY = event.clientY;
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = Math.hypot(a.x - b.x, a.y - b.y);
    }
  });
  on(canvas, 'pointermove', event => {
    if (!pointers.has(event.pointerId)) return;
    pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
    const dx = event.clientX - previousX, dy = event.clientY - previousY;
    if (mode === 'outside') {
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()], span = Math.hypot(a.x - b.x, a.y - b.y);
        distance = T.MathUtils.clamp(distance + (pinch - span) * .14, 48, 140);
        pinch = span;
      } else {
        theta -= dx * .005;
        phi = T.MathUtils.clamp(phi + dy * .004, .27, 1.38);
      }
    } else turn(-dx * .0045, -dy * .004);
    previousX = event.clientX; previousY = event.clientY;
  });
  for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) on(canvas, event, e => {
    pointers.delete(e.pointerId);
    if (pointers.size) {
      const first = [...pointers.values()][0];
      previousX = first.x; previousY = first.y;
    }
  });
  on(canvas, 'wheel', event => {
    if (mode !== 'outside') return;
    event.preventDefault();
    distance = T.MathUtils.clamp(distance + event.deltaY * .045, 48, 140);
  }, {passive: false});
  if (keyboard !== 'off') on(keyboard === 'global' ? window : canvas, 'keydown', event => {
    if (/INPUT|TEXTAREA|SELECT/.test(event.target?.tagName) || event.target?.isContentEditable) return;
    if (event.code === 'Escape' && mode === 'inside') exterior();
    if (event.code === 'Space' && mode === 'inside') {
      event.preventDefault();
      path?.playing ? pausePath() : resumePath();
    }
  });
  on(window, 'blur', () => pointers.clear());
  on(canvas, 'blur', () => pointers.clear());

  function frame(now) {
    if (disposed || paused) return;
    raf = requestAnimationFrame(frame);
    const dt = T.MathUtils.clamp((now - last) / 1000, 0, .1);
    last = now;
    if (mode === 'outside') {
      camera.position.set(
        exteriorTarget.x + distance * Math.sin(phi) * Math.sin(theta),
        exteriorTarget.y + distance * Math.cos(phi),
        exteriorTarget.z + distance * Math.sin(phi) * Math.cos(theta)
      );
      camera.lookAt(exteriorTarget);
      if (frameOffset && width > 1000) camera.setViewOffset(width, height, -width * frameOffset, 0, width, height);
      else camera.clearViewOffset();
    } else if (path?.playing) {
      path.elapsed = Math.min(path.route.duration, path.elapsed + dt);
      applyPath();
      const ended = path.elapsed >= path.route.duration;
      path.playing = !ended;
      stateElapsed += dt;
      if (ended || stateElapsed >= .1) { stateElapsed = 0; emit(); }
    }
    building.update(dt);
    renderer.render(scene, camera);
  }
  function pause() {
    if (disposed || paused) return;
    paused = true; cancelAnimationFrame(raf); pointers.clear(); emit();
  }
  function resume() {
    if (disposed || !paused) return;
    paused = false; last = performance.now(); frame(last); emit();
  }
  function dispose() {
    if (disposed) return;
    disposed = true; cancelAnimationFrame(raf); observer.disconnect();
    handlers.forEach(remove => remove());
    building.dispose(); sun.shadow.map?.dispose();
    renderer.dispose(); renderer.forceContextLoss(); canvas.remove();
  }

  lighting(); frame(last); emit();
  return {enter, exterior, playPath, pausePath, resumePath, seekPath, setCameraPath, setCutaway, setNight, turn, getState, pause, resume, dispose, scene, camera, building};
}
