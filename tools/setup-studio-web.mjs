import { mkdir, copyFile } from 'node:fs/promises';
const root = new URL('../', import.meta.url);
const target = new URL('studio/web/vendor/', root);
await mkdir(target, { recursive: true });
for (const [source, dest] of [
  ['build/three.module.js', 'three.module.js'],
  ['build/three.core.js', 'three.core.js'],
  ['examples/jsm/controls/OrbitControls.js', 'OrbitControls.js'],
  ['examples/jsm/environments/RoomEnvironment.js', 'RoomEnvironment.js'],
  ['LICENSE', 'THREE-LICENSE.txt'],
]) await copyFile(new URL(`node_modules/three/${source}`, root), new URL(dest, target));
console.log('Local Three.js runtime prepared. No CDN is needed.');
