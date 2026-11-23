/* Fetch the things the app needs that the user's machine will not have.
 *
 *   node scripts/bundle-runtime.mjs [--arch arm64|x64]
 *
 * Three pieces land in runtime/, which electron-builder copies into the app's
 * Resources:
 *
 *   runtime/python/  a relocatable CPython with the wheels installed
 *   runtime/bin/     static ffmpeg and ffprobe
 *   runtime/bin/FFMPEG-LICENSE.txt
 *
 * Why not the machine's own copies: Homebrew's ffmpeg links against dylibs in
 * /opt/homebrew/Cellar, so copying that binary produces an app that works only
 * on a machine that already has Homebrew ffmpeg — which is the one machine that
 * did not need the bundle. A venv is just as bad: its interpreter is a symlink
 * to a Python somewhere else on disk.
 *
 * Idempotent: anything already in place is left alone, so a failed run is
 * resumed rather than restarted.
 */
import { execFileSync } from 'node:child_process';
import { createWriteStream } from 'node:fs';
import { mkdir, rm, stat, chmod, readdir, rename } from 'node:fs/promises';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..');
const OUT = path.join(ROOT, 'runtime');

// 3.14 because that is the version this project's wheels are known to resolve
// on; a bundle is the wrong place to discover that a native wheel is missing.
const PYTHON_RELEASE = '20261110';
const PYTHON_VERSION = '3.14.10';
const FFMPEG_RELEASE = 'b6.1.1';

const argv = process.argv.slice(2);
const arch = argv.includes('--arch') ? argv[argv.indexOf('--arch') + 1] : process.arch;
const platform = process.platform;

const TRIPLE = {
  'darwin-arm64': 'aarch64-apple-darwin',
  'darwin-x64': 'x86_64-apple-darwin',
  'linux-x64': 'x86_64-unknown-linux-gnu',
  'linux-arm64': 'aarch64-unknown-linux-gnu',
  'win32-x64': 'x86_64-pc-windows-msvc',
}[`${platform}-${arch}`];

const FFMPEG_SLUG = { darwin: 'darwin', linux: 'linux', win32: 'win32' }[platform];
const EXE = platform === 'win32' ? '.exe' : '';

if (!TRIPLE) throw new Error(`no portable Python published for ${platform}-${arch}`);

async function exists(p) {
  try { await stat(p); return true; } catch { return false; }
}

async function download(url, dest) {
  process.stdout.write(`  ${path.basename(dest)} … `);
  const response = await fetch(url, { redirect: 'follow' });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText} for ${url}`);
  await pipeline(Readable.fromWeb(response.body), createWriteStream(dest));
  const { size } = await stat(dest);
  console.log(`${(size / 1e6).toFixed(0)} MB`);
}

async function fetchPython() {
  const target = path.join(OUT, 'python');
  if (await exists(path.join(target, 'bin', `python3${EXE}`))) {
    console.log('python: already present');
    return target;
  }
  console.log(`python ${PYTHON_VERSION} (${TRIPLE})`);
  const name = `cpython-${PYTHON_VERSION}+${PYTHON_RELEASE}-${TRIPLE}-install_only_stripped.tar.gz`;
  const url = `https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_RELEASE}/${name}`;
  const archive = path.join(OUT, name);
  await download(url, archive);
  // The tarball holds a single top-level "python" directory.
  execFileSync('tar', ['-xzf', archive, '-C', OUT], { stdio: 'inherit' });
  await rm(archive);
  return target;
}

function installWheels(pythonDir) {
  const python = path.join(pythonDir, 'bin', `python3${EXE}`);
  console.log('wheels: pip install -r requirements.txt');
  execFileSync(python, ['-m', 'pip', 'install', '--no-cache-dir', '--upgrade', 'pip'],
               { cwd: ROOT, stdio: 'inherit' });
  execFileSync(python, ['-m', 'pip', 'install', '--no-cache-dir', '-r', 'requirements.txt'],
               { cwd: ROOT, stdio: 'inherit' });
  // Nothing invokes a console script, so the shebangs pip rewrote to this
  // machine's path never run; the app always calls `python3 -m uvicorn`.
}

async function fetchFfmpeg() {
  const bin = path.join(OUT, 'bin');
  await mkdir(bin, { recursive: true });
  const base = `https://github.com/eugeneware/ffmpeg-static/releases/download/${FFMPEG_RELEASE}`;
  for (const program of ['ffmpeg', 'ffprobe']) {
    const dest = path.join(bin, program + EXE);
    if (await exists(dest)) { console.log(`${program}: already present`); continue; }
    console.log(`${program} (${FFMPEG_SLUG}-${arch})`);
    await download(`${base}/${program}-${FFMPEG_SLUG}-${arch}${EXE}`, dest);
    await chmod(dest, 0o755);
  }
  const licence = path.join(bin, 'FFMPEG-LICENSE.txt');
  if (!(await exists(licence))) {
    // Shipped because these builds are redistributed, and whoever receives the
    // app is entitled to the terms they came under.
    await download(`${base}/${FFMPEG_SLUG}-${arch}.LICENSE`, licence);
  }
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const pythonDir = await fetchPython();
  installWheels(pythonDir);
  await fetchFfmpeg();
  console.log(`\nruntime/ ready for ${platform}-${arch}`);
}

await main();
