// Copy a curated set of Lucide icons (ISC) into app/assets for the icon cover.
//
//   node scripts/vendor-icons.mjs <path to a lucide-react or lucide package>
//
// The cover needs a few dozen icons, not a 3,500-icon dependency, so the shapes
// are copied once as data: [[tag, attrs], ...] on Lucide's 24x24 grid, the same
// form Lucide itself ships. The license travels with them.
import { readFileSync, writeFileSync, copyFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

// One icon per broad field a paper is likely to be about; the model picks from these.
const ICONS = `atom dna microscope flask-conical telescope brain brain-circuit cpu network bot
database chart-line chart-scatter chart-column sigma calculator globe leaf sprout trees
heart-pulse stethoscope pill syringe bug fish bird paw-print mountain waves cloud-rain sun
moon orbit rocket satellite zap battery-charging magnet flame droplet thermometer scale
landmark building-2 users baby graduation-cap book-open-text message-square-text languages
music palette camera eye lock-keyhole shield-check coins trending-up shopping-cart factory
car plane train-front map route puzzle lightbulb target git-branch code binary waypoints
scan-eye hand-heart vote gavel newspaper tractor wheat recycle wind gem hourglass infinity
scroll-text fingerprint ear bone apple hospital cog wrench radar shapes boxes layers
microchip glasses activity`.split(/\s+/);

const source = process.argv[2];
if (!source) throw new Error('Usage: node scripts/vendor-icons.mjs <lucide-react package dir>');
const version = JSON.parse(readFileSync(join(source, 'package.json'), 'utf8')).version;
const icons = {};
for (const name of ICONS) {
  const text = readFileSync(join(source, 'dist/esm/icons', `${name}.js`), 'utf8');
  // createLucideIcon("Name", [ ...node... ]) -- the node is a plain literal.
  const literal = /createLucideIcon\(\s*"[^"]+",\s*(\[[\s\S]*\])\s*\);/.exec(text)?.[1];
  if (!literal) throw new Error(`No icon node in ${name}.js`);
  const node = Function(`"use strict"; return (${literal});`)();
  icons[name] = node.map(([tag, { key, ...attrs }]) => [tag, attrs]);
}
const out = join(dirname(fileURLToPath(import.meta.url)), '..', 'app', 'assets');
mkdirSync(out, { recursive: true });
writeFileSync(join(out, 'lucide-icons.json'),
  JSON.stringify({ source: `lucide-react ${version}`, license: 'ISC', icons }) + '\n');
copyFileSync(join(source, 'LICENSE'), join(out, 'LICENSE-lucide.txt'));
console.log(`${Object.keys(icons).length} icons from lucide-react ${version}`);
