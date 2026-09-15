import * as THREE from "three";
import { Brush, Evaluator, SUBTRACTION } from "three-bvh-csg";

interface Cutter {
  geometry: THREE.BufferGeometry;
  position?: [number, number, number];
  rotation?: [number, number, number];
}

/**
 * Scade (CSG) o lista de geometrii "cutter" dintr-o geometrie de baza si
 * intoarce geometria rezultata - taieturi/goluri reale (porturi, gauri de
 * surub, canale), nu doar primitive compuse vizual una langa alta.
 */
export function csgSubtract(baseGeometry: THREE.BufferGeometry, cutters: Cutter[]): THREE.BufferGeometry {
  const evaluator = new Evaluator();
  let result: Brush = new Brush(baseGeometry);
  result.updateMatrixWorld();

  for (const cutter of cutters) {
    const cutBrush = new Brush(cutter.geometry);
    if (cutter.position) cutBrush.position.set(...cutter.position);
    if (cutter.rotation) cutBrush.rotation.set(...cutter.rotation);
    cutBrush.updateMatrixWorld();
    result = evaluator.evaluate(result, cutBrush, SUBTRACTION);
    result.updateMatrixWorld();
  }

  return result.geometry;
}
