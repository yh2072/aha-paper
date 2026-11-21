/* Halftone lattice and coverage adapted from sevenevesai/riso-windowseat (MIT).
 * Source: films/window-seat/index.html; original copyright see RISO-LICENSE.txt.
 * Screens remain anchored in page pixels while vector geometry moves. */
(function(){
const PITCH=4.6;
const SCREEN={blue:{a:4,b:1},orange:{a:2,b:1},violet:{a:1,b:2},green:{a:1,b:1}};
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
function cv(w,h){const c=document.createElement('canvas');c.width=w;c.height=h;return c}
const screens = {};

function buildScreen(name) {
  const { a, b } = SCREEN[name];
  const n = a * a + b * b;
  const S = Math.max(2, Math.round(PITCH * Math.sqrt(n)));
  const P = S / Math.sqrt(n);              // effective pitch after rounding
  const u = P / Math.sqrt(n);
  const v1 = [u * a, u * b], v2 = [-u * b, u * a];

  // Lattice points reduced into the tile, plus wrapped neighbours so dots that
  // straddle an edge are drawn on both sides.
  const pts = [];
  for (let m = -n; m <= n; m++) {
    for (let k = -n; k <= n; k++) {
      const x = m * v1[0] + k * v2[0], y = m * v1[1] + k * v2[1];
      const wx = ((x % S) + S) % S, wy = ((y % S) + S) % S;
      if (!pts.some(p => Math.abs(p[0] - wx) < 0.01 && Math.abs(p[1] - wy) < 0.01)) pts.push([wx, wy]);
    }
  }
  const wrapped = [];
  for (const [x, y] of pts) for (const dx of [-S, 0, S]) for (const dy of [-S, 0, S]) wrapped.push([x + dx, y + dy]);

  // Threshold tile: a pixel takes ink when coverage exceeds π·d²/P², which is
  // the coverage at which a dot of radius d would reach that pixel.
  const th = new Float32Array(S * S);
  for (let y = 0; y < S; y++) {
    for (let x = 0; x < S; x++) {
      let d2 = Infinity;
      for (const [px, py] of wrapped) {
        const dx = x + 0.5 - px, dy = y + 0.5 - py, q = dx * dx + dy * dy;
        if (q < d2) d2 = q;
      }
      th[y * S + x] = clamp(Math.PI * d2 / (P * P), 0, 1);
    }
  }
  return { S, P, pts, wrapped, th, patterns: new Map() };
}

function screenOf(name) {
  return screens[name] || (screens[name] = buildScreen(name));
}

/** Screen a greyscale coverage canvas into hard dots. Bake-time only. */
function screenCoverage(covCanvas, name) {
  const sc = screenOf(name);
  const w = covCanvas.width, h = covCanvas.height;
  const src = covCanvas.getContext('2d').getImageData(0, 0, w, h);
  const s = src.data;
  for (let y = 0; y < h; y++) {
    const row = (y % sc.S) * sc.S;
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      const cover = s[i + 3] / 255;
      s[i + 3] = cover > sc.th[row + (x % sc.S)] ? 255 : 0;
    }
  }
  const out = cv(w, h);
  out.getContext('2d').putImageData(src, 0, 0);
  return out;
}


const patterns=new Map();
window.AhaRiso={pattern(ctx,name,color,coverage=.28){const key=name+color+coverage;let tile=patterns.get(key);if(!tile){const sc=screenOf(name),mask=cv(sc.S,sc.S),g=mask.getContext('2d');g.fillStyle=`rgba(0,0,0,${coverage})`;g.fillRect(0,0,sc.S,sc.S);tile=screenCoverage(mask,name);const t=tile.getContext('2d');t.globalCompositeOperation='source-in';t.fillStyle=color;t.fillRect(0,0,tile.width,tile.height);patterns.set(key,tile)}return ctx.createPattern(tile,'repeat')}};
})();
