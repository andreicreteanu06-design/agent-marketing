"use client";

import { Suspense, useMemo, useRef } from "react";
import type { RefObject } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Environment, Float, Sparkles } from "@react-three/drei";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import * as THREE from "three";
import { csgSubtract } from "@/lib/csg";

export type ServiceVisualVariant = "ppc" | "web" | "automations";

/**
 * Rotatie usoara dupa pozitia cursorului in interiorul canvas-ului (state.pointer,
 * normalizat -1..1 de R3F per-canvas) - acelasi pattern ca in Portfolio3DCard.
 */
function usePointerTilt(ref: RefObject<THREE.Group | null>) {
  useFrame((state) => {
    if (!ref.current) return;
    const { x, y } = state.pointer;
    ref.current.rotation.y = THREE.MathUtils.lerp(ref.current.rotation.y, x * 0.4, 0.06);
    ref.current.rotation.x = THREE.MathUtils.lerp(ref.current.rotation.x, -y * 0.25, 0.06);
  });
}

// --------------------------------------------------------------------------
// PPC: un "nucleu de energie" cu shader propriu (zgomot simplex 3D + fbm pe
// vertex shader, fresnel + culoare modulata de zgomot pe fragment shader) -
// o suprafata organica reala, nu o sfera distorsionata generic. Nodurile
// care orbiteaza reprezinta cele trei canale (Google/Meta/TikTok) pe care
// agentul le opereaza simultan.
// --------------------------------------------------------------------------

// Simplex noise 3D (Ashima Arts / webgl-noise, implementarea standard
// folosita in majoritatea shaderelor de generatie) + fbm (4 octave) pentru o
// suprafata organica, nu o simpla suma de sinusuri.
const NOISE_GLSL = /* glsl */ `
  vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
  vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

  float snoise(vec3 v) {
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);

    vec3 i  = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);

    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);

    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;

    i = mod289(i);
    vec4 p = permute(permute(permute(
              i.z + vec4(0.0, i1.z, i2.z, 1.0))
            + i.y + vec4(0.0, i1.y, i2.y, 1.0))
            + i.x + vec4(0.0, i1.x, i2.x, 1.0));

    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;

    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);

    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);

    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);

    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);

    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));

    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;

    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);

    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x;
    p1 *= norm.y;
    p2 *= norm.z;
    p3 *= norm.w;

    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
  }

  float fbm(vec3 p) {
    float value = 0.0;
    float amplitude = 0.5;
    for (int i = 0; i < 4; i++) {
      value += amplitude * snoise(p);
      p *= 2.0;
      amplitude *= 0.5;
    }
    return value;
  }
`;

const ENERGY_CORE_VERTEX = /* glsl */ `
  uniform float uTime;
  varying vec3 vNormal;
  varying vec3 vViewPosition;
  varying float vNoise;

  ${NOISE_GLSL}

  void main() {
    float n = fbm(position * 1.6 + vec3(0.0, 0.0, uTime * 0.35));
    vNoise = n;
    vec3 displaced = position + normal * (n * 0.14);
    vec4 mvPosition = modelViewMatrix * vec4(displaced, 1.0);
    vNormal = normalize(normalMatrix * normal);
    vViewPosition = -mvPosition.xyz;
    gl_Position = projectionMatrix * mvPosition;
  }
`;

const ENERGY_CORE_FRAGMENT = /* glsl */ `
  uniform vec3 uColorDeep;
  uniform vec3 uColorMid;
  uniform vec3 uColorRim;
  varying vec3 vNormal;
  varying vec3 vViewPosition;
  varying float vNoise;

  void main() {
    vec3 viewDir = normalize(vViewPosition);
    float fresnel = pow(1.0 - clamp(dot(viewDir, normalize(vNormal)), 0.0, 1.0), 2.2);
    vec3 base = mix(uColorDeep, uColorMid, clamp(vNoise * 0.5 + 0.5, 0.0, 1.0));
    vec3 color = mix(base, uColorRim, fresnel);
    gl_FragColor = vec4(color, 1.0);
  }
`;

function EnergyCore() {
  const material = useRef<THREE.ShaderMaterial>(null);
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uColorDeep: { value: new THREE.Color("#060f30") },
      uColorMid: { value: new THREE.Color("#1450d8") },
      uColorRim: { value: new THREE.Color("#3fd8e8") },
    }),
    [],
  );
  useFrame((state) => {
    if (material.current) material.current.uniforms.uTime.value = state.clock.elapsedTime;
  });

  return (
    <mesh>
      <icosahedronGeometry args={[1.1, 4]} />
      <shaderMaterial
        ref={material}
        uniforms={uniforms}
        vertexShader={ENERGY_CORE_VERTEX}
        fragmentShader={ENERGY_CORE_FRAGMENT}
      />
    </mesh>
  );
}

function PpcScene() {
  const tilt = useRef<THREE.Group>(null);
  const orbit = useRef<THREE.Group>(null);
  const shell = useRef<THREE.Mesh>(null);
  usePointerTilt(tilt);
  useFrame((_, delta) => {
    if (orbit.current) orbit.current.rotation.y += delta * 0.4;
    if (shell.current) shell.current.rotation.y -= delta * 0.15;
  });

  return (
    <group ref={tilt}>
      <Sparkles count={70} scale={4.2} size={2} speed={0.3} color="#3fd8e8" opacity={0.5} />
      <Float speed={1.6} rotationIntensity={0.3} floatIntensity={0.6}>
        <EnergyCore />
        <mesh ref={shell}>
          <icosahedronGeometry args={[1.55, 1]} />
          <meshBasicMaterial color="#3fd8e8" wireframe transparent opacity={0.12} />
        </mesh>
      </Float>
      <group ref={orbit}>
        {[0, 1, 2].map((i) => {
          const angle = (i / 3) * Math.PI * 2;
          return (
            <mesh
              key={i}
              position={[Math.cos(angle) * 2, Math.sin(angle * 1.3) * 0.5, Math.sin(angle) * 2]}
              rotation={[Math.PI / 2, 0, 0]}
            >
              <torusGeometry args={[0.1, 0.032, 12, 24]} />
              <meshStandardMaterial color="#3fd8e8" emissive="#3fd8e8" emissiveIntensity={1} toneMapped={false} />
            </mesh>
          );
        })}
      </group>
    </group>
  );
}

// --------------------------------------------------------------------------
// Web design: un laptop propriu-zis, cu porturi si o zona de trackpad taiate
// real in baza (CSG - three-bvh-csg), plus un mockup de site desenat pe un
// CanvasTexture pe ecran - un obiect recognoscibil, nu panouri abstracte.
// --------------------------------------------------------------------------

function useLaptopBaseGeometry() {
  return useMemo(() => {
    const base = new THREE.BoxGeometry(2.4, 0.12, 1.6);
    const trackpadRecess = new THREE.BoxGeometry(1.0, 0.05, 0.65);
    const portSlot = new THREE.BoxGeometry(0.15, 0.04, 0.09);

    return csgSubtract(base, [
      { geometry: trackpadRecess, position: [0, 0.045, 0.15] },
      { geometry: portSlot, position: [1.2, -0.02, -0.55] },
      { geometry: portSlot, position: [1.2, -0.02, 0.35] },
    ]);
  }, []);
}

function useWebsiteMockupTexture() {
  return useMemo(() => {
    if (typeof document === "undefined") return null;
    const canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = 320;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;

    ctx.fillStyle = "#0a0a0f";
    ctx.fillRect(0, 0, 512, 320);

    ctx.fillStyle = "#15151d";
    ctx.fillRect(0, 0, 512, 30);
    ["#ff5f57", "#febc2e", "#28c840"].forEach((color, i) => {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(20 + i * 18, 15, 5, 0, Math.PI * 2);
      ctx.fill();
    });

    ctx.fillStyle = "#1450d8";
    ctx.fillRect(28, 54, 210, 16);
    ctx.fillStyle = "#3fd8e8";
    ctx.fillRect(28, 78, 140, 9);

    for (let i = 0; i < 3; i++) {
      const y = 118 + i * 62;
      ctx.fillStyle = "#12121a";
      ctx.fillRect(28, y, 456, 46);
      ctx.strokeStyle = "rgba(63,216,232,0.35)";
      ctx.lineWidth = 1;
      ctx.strokeRect(28, y, 456, 46);
      ctx.fillStyle = "#3fd8e8";
      ctx.fillRect(46, y + 14, 90, 8);
      ctx.fillStyle = "#3a3a44";
      ctx.fillRect(46, y + 30, 190, 6);
    }

    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
  }, []);
}

const SCREEN_TILT = -0.21;
const SCREEN_POSITION: [number, number, number] = [0, 0.24, -0.76];

function WebScene() {
  const tilt = useRef<THREE.Group>(null);
  usePointerTilt(tilt);
  const baseGeometry = useLaptopBaseGeometry();
  const screenTexture = useWebsiteMockupTexture();
  const screenGroup = useRef<THREE.Group>(null);

  useFrame((state) => {
    if (screenGroup.current) {
      screenGroup.current.rotation.x = SCREEN_TILT + Math.sin(state.clock.elapsedTime * 0.5) * 0.015;
    }
  });

  return (
    <group ref={tilt} rotation={[0.05, -0.55, 0]}>
      <Float speed={1.2} rotationIntensity={0.15} floatIntensity={0.35}>
        <mesh geometry={baseGeometry} position={[0, -0.55, 0.2]}>
          <meshStandardMaterial color="#1c1c22" roughness={0.4} metalness={0.5} />
        </mesh>

        <group ref={screenGroup} position={SCREEN_POSITION} rotation={[SCREEN_TILT, 0, 0]}>
          <mesh>
            <boxGeometry args={[2.4, 1.5, 0.08]} />
            <meshStandardMaterial color="#1c1c22" roughness={0.35} metalness={0.55} />
          </mesh>
          {screenTexture && (
            <mesh position={[0, 0, 0.045]}>
              <planeGeometry args={[2.2, 1.35]} />
              <meshBasicMaterial map={screenTexture} toneMapped={false} />
            </mesh>
          )}
        </group>
      </Float>
    </group>
  );
}

// --------------------------------------------------------------------------
// Automatizari AI: un brat robotic articulat, cu gauri de surub taiate real
// in baza si un canal de cablu taiat in brat (CSG - three-bvh-csg), intr-un
// ciclu continuu de "pick and place" - o masina reala, nu un graf abstract.
// --------------------------------------------------------------------------

function useRobotBaseGeometry() {
  return useMemo(() => {
    const base = new THREE.CylinderGeometry(0.42, 0.5, 0.22, 24);
    const boltHole = new THREE.CylinderGeometry(0.035, 0.035, 0.12, 12);
    const cutters = [0, 1, 2, 3].map((i) => {
      const angle = (i / 4) * Math.PI * 2;
      const radius = 0.34;
      return {
        geometry: boltHole,
        position: [Math.cos(angle) * radius, 0.09, Math.sin(angle) * radius] as [number, number, number],
      };
    });
    return csgSubtract(base, cutters);
  }, []);
}

function useUpperArmGeometry() {
  return useMemo(() => {
    const arm = new THREE.BoxGeometry(0.22, 1, 0.22);
    const groove = new THREE.BoxGeometry(0.08, 0.8, 0.08);
    return csgSubtract(arm, [{ geometry: groove, position: [0, 0, 0.08] }]);
  }, []);
}

function AutomationsScene() {
  const tilt = useRef<THREE.Group>(null);
  usePointerTilt(tilt);
  const baseGeometry = useRobotBaseGeometry();
  const upperArmGeometry = useUpperArmGeometry();
  const shoulder = useRef<THREE.Group>(null);
  const elbow = useRef<THREE.Group>(null);
  const gripL = useRef<THREE.Mesh>(null);
  const gripR = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (shoulder.current) shoulder.current.rotation.y = Math.sin(t * 0.5) * 0.6;
    if (elbow.current) elbow.current.rotation.z = -0.9 + Math.sin(t * 0.9) * 0.35;
    const grip = 0.06 + (Math.sin(t * 0.9) * 0.5 + 0.5) * 0.05;
    if (gripL.current) gripL.current.position.x = -grip;
    if (gripR.current) gripR.current.position.x = grip;
  });

  return (
    <group ref={tilt} position={[0, -0.35, 0]}>
      <Float speed={1} rotationIntensity={0.1} floatIntensity={0.25}>
        <mesh geometry={baseGeometry} position={[0, -0.55, 0]}>
          <meshStandardMaterial color="#141419" roughness={0.4} metalness={0.6} />
        </mesh>

        <group ref={shoulder} position={[0, -0.44, 0]}>
          <mesh geometry={upperArmGeometry} position={[0, 0.5, 0]}>
            <meshStandardMaterial
              color="#1450d8"
              emissive="#3fd8e8"
              emissiveIntensity={0.15}
              roughness={0.3}
              metalness={0.5}
            />
          </mesh>

          <group ref={elbow} position={[0, 1, 0]}>
            <mesh position={[0.45, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
              <boxGeometry args={[0.16, 0.9, 0.16]} />
              <meshStandardMaterial color="#1c1c22" roughness={0.35} metalness={0.6} />
            </mesh>
            <group position={[0.9, 0, 0]}>
              <mesh ref={gripL} position={[-0.06, 0, 0]}>
                <boxGeometry args={[0.08, 0.22, 0.2]} />
                <meshStandardMaterial color="#3fd8e8" emissive="#3fd8e8" emissiveIntensity={0.6} toneMapped={false} />
              </mesh>
              <mesh ref={gripR} position={[0.06, 0, 0]}>
                <boxGeometry args={[0.08, 0.22, 0.2]} />
                <meshStandardMaterial color="#3fd8e8" emissive="#3fd8e8" emissiveIntensity={0.6} toneMapped={false} />
              </mesh>
            </group>
          </group>
        </group>
      </Float>
    </group>
  );
}

export function ServiceVisual3D({ variant }: { variant: ServiceVisualVariant }) {
  return (
    <div className="h-full w-full">
      <Canvas camera={{ position: [0, 0, 4.8], fov: 32 }} dpr={[1, 2]} gl={{ alpha: true, antialias: true }}>
        <ambientLight intensity={0.7} />
        <directionalLight position={[2.5, 3, 4]} intensity={0.9} color="#3fd8e8" />
        <pointLight position={[-2, -1, 2]} intensity={0.5} color="#1450d8" />
        <Suspense fallback={null}>
          <Environment preset="night" environmentIntensity={0.6} background={false} />
          {variant === "ppc" && <PpcScene />}
          {variant === "web" && <WebScene />}
          {variant === "automations" && <AutomationsScene />}
        </Suspense>
        <EffectComposer>
          <Bloom luminanceThreshold={0.2} luminanceSmoothing={0.9} intensity={0.6} mipmapBlur />
        </EffectComposer>
      </Canvas>
    </div>
  );
}
