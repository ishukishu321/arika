/* avatar.js — loads and renders a VRM 3D avatar with a relaxed idle pose,
 * breathing + subtle idle sway, random casual head-look, blinking,
 * emotion-driven facial expressions, and volume-driven lip sync.
 * Exposes window.Avatar = {
 *   init(canvasId), loadVRM(url), setMouth(volume),
 *   setEmotion(name, intensity?, holdMs?), onResize
 * }
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

// Standard VRM expression presets we drive for facial emotion. If a model
// doesn't define one of these, three-vrm's setValue simply no-ops for it,
// so this stays safe across different VRMs.
const EMOTIONS = ['happy', 'angry', 'sad', 'relaxed', 'surprised'];

const Avatar = (() => {
  let renderer, scene, camera, controls, clock;
  let currentVrm = null;
  let isVisible = true;
  let mouthTarget = 0;   // raw volume coming in from tts.js (0..1)
  let mouthValue = 0;    // smoothed value actually applied to the blendshape
  let blinkTimer = 2;
  let idleTime = 0;      // running clock used for breathing/sway sine waves

  // --- random casual head-look state (saccade-style idle) ---
  let headYaw = 0, headPitch = 0;             // smoothed angles applied to the bone
  let headTargetYaw = 0, headTargetPitch = 0; // where it's currently drifting toward
  let headMoveTimer = 2;                      // seconds until a new random target is picked

  // --- emotion blend state ---
  let emotionTarget = {};   // e.g. { happy: 1 }, everything else implicitly 0
  let emotionCurrent = {};  // smoothed weights actually sent to expressionManager
  let emotionResetHandle = null;
  EMOTIONS.forEach((e) => { emotionCurrent[e] = 0; });

  // cached bone refs so we don't look them up every frame
  let bones = {};

  function setVisible(visible) {
    isVisible = !!visible;
    if (!renderer) return;
    const canvas = renderer.domElement;
    if (canvas) canvas.style.display = isVisible ? 'block' : 'none';
    if (currentVrm?.scene) currentVrm.scene.visible = isVisible;
  }

  function init(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) {
      console.warn('[avatar] canvas not found:', canvasId);
      return;
    }

    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(30, 1, 0.1, 20);
    camera.position.set(0, 1.35, 1.6);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 1.25, 0);
    controls.enableDamping = true;
    controls.enablePan = false;
    controls.minDistance = 0.8;
    controls.maxDistance = 3;
    controls.update();

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight.position.set(1, 1, 1).normalize();
    scene.add(dirLight);
    scene.add(new THREE.AmbientLight(0xffffff, 0.7));

    clock = new THREE.Clock();
    window.addEventListener('resize', onResize);
    setVisible(isVisible);
    onResize();
    renderer.setAnimationLoop(tick);
  }

  function onResize() {
    if (!renderer) return;
    const canvas = renderer.domElement;
    const w = canvas.clientWidth || 300;
    const h = canvas.clientHeight || 400;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
    updateFraming();
  }

  // Frames the camera using the VRM's actual bone positions so it works for
  // any model's proportions. On narrow/portrait screens (phones) we frame
  // tighter, from the waist (hips) up, so Arika fills the available height
  // instead of showing a small full-body shot with lots of empty space.
  function updateFraming() {
    if (!renderer || !currentVrm || !currentVrm.humanoid) return;
    const h = currentVrm.humanoid;
    const hips = h.getNormalizedBoneNode('hips');
    const head = h.getNormalizedBoneNode('head');
    if (!hips || !head) return;

    const hipsWorld = new THREE.Vector3();
    hips.getWorldPosition(hipsWorld);
    const headWorld = new THREE.Vector3();
    head.getWorldPosition(headWorld);

    const canvas = renderer.domElement;
    const isPortrait = canvas.clientWidth < canvas.clientHeight;

    const topY = headWorld.y + (isPortrait ? 0.40 : 0.28);   // headroom above the hair
    // Portrait (phone): cut off right at the waist, flush with the input
    // overlay below — no wasted empty space between avatar and input box.
    // Landscape (desktop): keep more of the body visible.
    const bottomY = isPortrait ? hipsWorld.y : Math.max(0, hipsWorld.y - 0.9);
    const rawMidY = (topY + bottomY) / 2;
    // On phone, a small downward nudge so Arika isn't dead-centered — kept
    // subtle so she doesn't sit too low in the frame.
    const midY = isPortrait ? rawMidY + -0.15 : rawMidY;
    const desiredHeight = topY - bottomY;

    const fovRad = THREE.MathUtils.degToRad(camera.fov);
    const distance = (desiredHeight / 2) / Math.tan(fovRad / 2);

    camera.position.set(0, midY, distance);
    controls.target.set(0, midY, 0);
    controls.minDistance = distance * 0.6;
    controls.maxDistance = distance * 1.8;
    controls.update();
  }

  async function loadVRM(url) {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));

    const gltf = await loader.loadAsync(url);
    const vrm = gltf.userData.vrm;

    if (currentVrm) {
      scene.remove(currentVrm.scene);
      VRMUtils.deepDispose(currentVrm.scene);
    }

    VRMUtils.rotateVRM0(vrm); // fixes models exported facing +Z (old VRM0 spec)
    scene.add(vrm.scene);
    currentVrm = vrm;

    cacheBones(vrm);
    applyIdlePose(vrm);
    updateFraming();

    return vrm;
  }

  function cacheBones(vrm) {
    const h = vrm.humanoid;
    bones = {
      chest: h.getNormalizedBoneNode('chest') || h.getNormalizedBoneNode('upperChest'),
      spine: h.getNormalizedBoneNode('spine'),
      neck: h.getNormalizedBoneNode('neck'),
      head: h.getNormalizedBoneNode('head'),
      leftShoulder: h.getNormalizedBoneNode('leftShoulder'),
      rightShoulder: h.getNormalizedBoneNode('rightShoulder'),
      leftUpperArm: h.getNormalizedBoneNode('leftUpperArm'),
      rightUpperArm: h.getNormalizedBoneNode('rightUpperArm'),
      leftLowerArm: h.getNormalizedBoneNode('leftLowerArm'),
      rightLowerArm: h.getNormalizedBoneNode('rightLowerArm'),
      leftHand: h.getNormalizedBoneNode('leftHand'),
      rightHand: h.getNormalizedBoneNode('rightHand'),
    };
  }

  // VRoid/VRM models load in the raw T-pose bind pose. This drops the arms
  // into a natural resting stance so the avatar doesn't stand like a cross —
  // and unlike the old version, it actually relaxes the shoulders, bends the
  // elbows a little, and angles the hands in, so it reads as "standing
  // casually" instead of "arms bolted straight to the sides."
  function applyIdlePose(vrm) {
    if (!vrm.humanoid) return;

    // shoulders drop very slightly — too much roll here is what was
    // dragging the arms/hands inward toward the hips
    if (bones.leftShoulder) bones.leftShoulder.rotation.z = -0.04;
    if (bones.rightShoulder) bones.rightShoulder.rotation.z = 0.04;

    // upper arms hang close to the sides, minimal forward/inward twist —
    // just enough to not look T-pose-stiff, not enough to swing hands
    // into the hips
    if (bones.leftUpperArm) {
      bones.leftUpperArm.rotation.z = -1.22;
      bones.leftUpperArm.rotation.x = 0.05;
      bones.leftUpperArm.rotation.y = 0;
    }
    if (bones.rightUpperArm) {
      bones.rightUpperArm.rotation.z = 1.22;
      bones.rightUpperArm.rotation.x = 0.05;
      bones.rightUpperArm.rotation.y = 0;
    }

    // just a small elbow bend, no inward twist
    if (bones.leftLowerArm) {
      bones.leftLowerArm.rotation.z = -0.15;
      bones.leftLowerArm.rotation.y = 0;
    }
    if (bones.rightLowerArm) {
      bones.rightLowerArm.rotation.z = 0.15;
      bones.rightLowerArm.rotation.y = 0;
    }

    // hands stay neutral — no inward rotation, that's what was pulling
    // them onto the hips
    if (bones.leftHand) bones.leftHand.rotation.z = 0;
    if (bones.rightHand) bones.rightHand.rotation.z = 0;
  }

  // volume: 0..1, called continuously from tts.js while audio is playing
  function setMouth(volume) {
    mouthTarget = Math.max(0, Math.min(1, volume));
  }

  function blink() {
    if (!currentVrm?.expressionManager) return;
    const em = currentVrm.expressionManager;
    let t = 0;
    const dur = 0.18;
    function step() {
      t += 1 / 60;
      const v = t < dur / 2 ? t / (dur / 2) : 1 - (t - dur / 2) / (dur / 2);
      em.setValue('blink', Math.max(0, v));
      if (t < dur) requestAnimationFrame(step);
      else em.setValue('blink', 0);
    }
    step();
  }

  function randRange(min, max) {
    return min + Math.random() * (max - min);
  }

  // Picks a new random "look at" direction every couple of seconds and
  // drifts smoothly toward it, instead of a fixed sine loop. This is what
  // makes it read as "casually glancing around" rather than a robotic
  // metronome — most of the moves are small, occasionally a bigger one
  // slips in (e.g. actually turning to look off to a side).
  function updateCasualHeadLook(delta) {
    headMoveTimer -= delta;
    if (headMoveTimer <= 0) {
      // ~70% small glances, ~30% a bigger, more noticeable head turn
      const big = Math.random() < 0.3;
      headTargetYaw = big ? randRange(-0.5, 0.5) : randRange(-0.18, 0.18);
      headTargetPitch = big ? randRange(-0.12, 0.18) : randRange(-0.06, 0.08);
      headMoveTimer = randRange(2.2, 5.5);
    }
    // ease toward the target — slower = more natural, less twitchy
    const ease = Math.min(1, delta * 1.6);
    headYaw += (headTargetYaw - headYaw) * ease;
    headPitch += (headTargetPitch - headPitch) * ease;
  }

  // Breathing + very subtle idle sway so the avatar doesn't feel frozen.
  // Layers a couple of slow sine waves at different speeds so it doesn't
  // look like an obvious repeating loop.
  function applyIdleMotion(delta) {
    idleTime += delta;

    const breathe = Math.sin(idleTime * 1.1) * 0.035;      // chest rise/fall
    const sway = Math.sin(idleTime * 0.35) * 0.025;         // slow body sway
    const microTilt = Math.sin(idleTime * 0.5 + 1.0) * 0.015; // tiny added life on top of the head look

    updateCasualHeadLook(delta);

    if (bones.chest) bones.chest.rotation.x = breathe;
    if (bones.spine) bones.spine.rotation.z = sway;
    if (bones.head) {
      bones.head.rotation.x = headPitch + microTilt;
      bones.head.rotation.y = headYaw;
    }
    if (bones.neck) bones.neck.rotation.y = headYaw * 0.3;
  }

  // Drives facial emotion via VRM expression presets. Call with a name from
  // EMOTIONS (or 'neutral' to clear). Fades in/out smoothly in tick() rather
  // than snapping, and auto-relaxes back to neutral after holdMs so a caller
  // doesn't have to remember to reset it.
  function setEmotion(name, intensity = 1, holdMs = 4000) {
    const target = {};
    EMOTIONS.forEach((e) => { target[e] = 0; });
    if (EMOTIONS.includes(name)) {
      target[name] = Math.max(0, Math.min(1, intensity));
    }
    emotionTarget = target;

    if (emotionResetHandle) clearTimeout(emotionResetHandle);
    if (name !== 'neutral') {
      emotionResetHandle = setTimeout(() => setEmotion('neutral'), holdMs);
    }
  }

  function tick() {
    const delta = clock.getDelta();

    if (!isVisible) {
      renderer.render(scene, camera);
      return;
    }

    if (currentVrm) {
      applyIdleMotion(delta);

      // smooth the mouth value so it doesn't flicker frame to frame
      mouthValue += (mouthTarget - mouthValue) * Math.min(1, delta * 15);

      const em = currentVrm.expressionManager;
      if (em) {
        em.setValue('aa', mouthValue);

        // smoothly fade each emotion weight toward its target
        EMOTIONS.forEach((e) => {
          const target = emotionTarget[e] || 0;
          emotionCurrent[e] += (target - emotionCurrent[e]) * Math.min(1, delta * 4);
          em.setValue(e, emotionCurrent[e]);
        });
      }

      blinkTimer -= delta;
      if (blinkTimer <= 0) {
        blinkTimer = 2.5 + Math.random() * 3;
        blink();
      }

      currentVrm.update(delta);
    }

    controls.update();
    renderer.render(scene, camera);
  }

  return { init, loadVRM, setMouth, setEmotion, setVisible, onResize };
})();

window.Avatar = Avatar;
