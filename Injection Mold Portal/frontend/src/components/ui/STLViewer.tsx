import { useEffect, useRef } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export type ViewerColor = "natural" | "black" | "custom";
export type ViewerFinish = "as-molded" | "textured" | "polished";

const COLOR_HEX: Record<ViewerColor, number> = {
  natural: 0xd8d4c8,
  black: 0x1c1c1c,
  custom: 0x3987e5,
};

const FINISH_PARAMS: Record<ViewerFinish, { roughness: number; metalness: number }> = {
  "as-molded": { roughness: 0.55, metalness: 0.05 },
  textured: { roughness: 0.85, metalness: 0.02 },
  polished: { roughness: 0.15, metalness: 0.1 },
};

export function STLViewer({
  file,
  color,
  finish,
}: {
  file: File;
  color: ViewerColor;
  finish: ViewerFinish;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const meshRef = useRef<THREE.Mesh | null>(null);
  const colorRef = useRef(color);
  const finishRef = useRef(finish);
  colorRef.current = color;
  finishRef.current = finish;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = container.clientWidth;
    const height = container.clientHeight;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 10000);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    container.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(1, 1.5, 1);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.5);
    fill.position.set(-1, -0.5, -1);
    scene.add(fill);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 2.2;

    let frameId: number;
    let disposed = false;

    const reader = new FileReader();
    reader.onload = () => {
      if (disposed || !(reader.result instanceof ArrayBuffer)) return;
      const geometry = new STLLoader().parse(reader.result);
      geometry.computeVertexNormals();
      geometry.center();

      const box = new THREE.Box3().setFromObject(new THREE.Mesh(geometry));
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z) || 1;
      const scale = 3.2 / maxDim;
      geometry.scale(scale, scale, scale);

      const material = new THREE.MeshStandardMaterial({
        color: COLOR_HEX[colorRef.current],
        ...FINISH_PARAMS[finishRef.current],
      });
      const mesh = new THREE.Mesh(geometry, material);
      meshRef.current = mesh;
      scene.add(mesh);

      camera.position.set(3, 2.4, 4);
      controls.update();

      const animate = () => {
        controls.update();
        renderer.render(scene, camera);
        frameId = requestAnimationFrame(animate);
      };
      animate();
    };
    reader.readAsArrayBuffer(file);

    function handleResize() {
      if (!container) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
    window.addEventListener("resize", handleResize);

    return () => {
      disposed = true;
      window.removeEventListener("resize", handleResize);
      cancelAnimationFrame(frameId);
      controls.dispose();
      renderer.dispose();
      meshRef.current?.geometry.dispose();
      (meshRef.current?.material as THREE.Material | undefined)?.dispose();
      container.removeChild(renderer.domElement);
    };
  }, [file]);

  // Update material live when color/finish change, without re-loading the mesh.
  useEffect(() => {
    const material = meshRef.current?.material as THREE.MeshStandardMaterial | undefined;
    if (!material) return;
    material.color.setHex(COLOR_HEX[color]);
    Object.assign(material, FINISH_PARAMS[finish]);
  }, [color, finish]);

  return (
    <div
      ref={containerRef}
      className="h-64 w-full overflow-hidden rounded-lg border border-border bg-surface-raised sm:h-80"
    />
  );
}
