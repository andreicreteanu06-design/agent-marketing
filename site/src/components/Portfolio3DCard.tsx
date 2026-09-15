"use client";

import { Suspense, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Image as ImagePlane, Float } from "@react-three/drei";
import * as THREE from "three";

/**
 * Placa cu screenshot-ul site-ului, inclinata 3D real (WebGL, nu CSS) dupa
 * pozitia cursorului in interiorul canvas-ului - state.pointer e deja
 * normalizat -1..1 de R3F, nu mai calculam nimic manual. Float adauga o
 * plutire lenta, constanta, cat timp cursorul nu e deasupra.
 */
function TiltedScreenshot({ src }: { src: string }) {
  const group = useRef<THREE.Group>(null);

  useFrame((state) => {
    if (!group.current) return;
    const { x, y } = state.pointer;
    group.current.rotation.y = THREE.MathUtils.lerp(group.current.rotation.y, x * 0.32, 0.06);
    group.current.rotation.x = THREE.MathUtils.lerp(group.current.rotation.x, -y * 0.18, 0.06);
  });

  return (
    <Float speed={1.3} rotationIntensity={0.18} floatIntensity={0.5}>
      <group ref={group}>
        <ImagePlane url={src} scale={[3.7, 2.31]} radius={0.09} transparent toneMapped={false} />
      </group>
    </Float>
  );
}

export function Portfolio3DCard({ src, alt }: { src: string; alt: string }) {
  return (
    <div className="aspect-[16/10] w-full" role="img" aria-label={alt}>
      <Canvas camera={{ position: [0, 0, 4.6], fov: 30 }} dpr={[1, 2]} gl={{ alpha: true }}>
        <ambientLight intensity={1.2} />
        <directionalLight position={[2.5, 3, 4]} intensity={0.7} />
        <Suspense fallback={null}>
          <TiltedScreenshot src={src} />
        </Suspense>
      </Canvas>
    </div>
  );
}
