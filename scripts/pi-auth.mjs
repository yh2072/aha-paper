// Credential storage and ambient-environment policy for Pi's provider registry.
//
// Mirrors ahaexplain: the app owns persistence, pi-ai owns resolution. We never
// re-implement "which env var holds the key" or "is this provider configured" --
// every provider in pi-ai carries its own auth.resolve() precedence chain, and
// Models.checkAuth()/getAuth() report the answer with a source label.
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { builtinModels } from '@earendil-works/pi-ai/providers/all';
import path from 'node:path';
import os from 'node:os';

const ROOT = path.resolve(import.meta.dirname, '..');

// The Python app loads .env into its environment, so a subprocess inherits it;
// loading it here too makes a directly-run CLI report the same state instead of
// a second, emptier truth. Already-set variables win, as in python-dotenv.
// The user's own files live beside the code only when running from a checkout.
// A packaged app's bundle is read-only, so the shell points AHA_STATE_DIR at the
// platform's application-data directory and everything writable follows it.
const STATE = process.env.AHA_STATE_DIR || ROOT;

try { process.loadEnvFile(path.join(STATE, '.env')); } catch { /* no .env: ambient only */ }

// Overridable so tests get their own store instead of the user's real one.
export const CREDENTIAL_FILE = process.env.PI_CREDENTIAL_FILE || path.join(STATE, '.runtime', 'credentials.json');

/**
 * The app's Models collection: every built-in provider, this app's credential
 * store, and this app's ambient-environment policy. Built fresh per process --
 * the store is the shared state, not this object.
 */
export function appModels() {
  return builtinModels({ credentials: fileCredentialStore(CREDENTIAL_FILE), authContext: appAuthContext() });
}

/**
 * File-backed CredentialStore: `{version:1, credentials:{<providerId>:Credential}}`.
 *
 * Contract from pi-ai `auth/types.ts`: `modify` is the only write path and must
 * serialize per provider id, because OAuth refresh runs inside it -- two
 * concurrent requests must not both refresh a rotated token. Writes land via
 * temp-file + rename so a crash can never leave a half-written key file.
 */
export function fileCredentialStore(filePath) {
  let cache;
  const chains = new Map();

  const load = async () => {
    if (cache) return cache;
    try {
      const parsed = JSON.parse(await readFile(filePath, 'utf8'));
      cache = parsed?.version === 1 && parsed.credentials && typeof parsed.credentials === 'object'
        ? { ...parsed.credentials } : {};
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      cache = {};
    }
    return cache;
  };

  const flush = async () => {
    await mkdir(path.dirname(filePath), { recursive: true });
    const temporary = `${filePath}.tmp`;
    const body = `${JSON.stringify({ version: 1, credentials: cache }, null, 2)}\n`;
    await writeFile(temporary, body, { encoding: 'utf8', mode: 0o600 });
    await rename(temporary, filePath);
  };

  // Per-provider promise chain: the next task starts only after the active one
  // settles, so a read-modify-write is never interleaved with another.
  const enqueue = (providerId, task) => {
    const previous = chains.get(providerId) ?? Promise.resolve();
    const next = previous.then(task, task);
    chains.set(providerId, next.then(() => {}, () => {}));
    return next;
  };

  return {
    async read(providerId) {
      return (await load())[providerId];
    },
    async list() {
      const credentials = await load();
      return Object.entries(credentials).map(([providerId, credential]) => ({ providerId, type: credential.type }));
    },
    async modify(providerId, fn) {
      return enqueue(providerId, async () => {
        const credentials = await load();
        const next = await fn(credentials[providerId]);
        if (next === undefined) return credentials[providerId];
        cache[providerId] = next;
        await flush();
        return next;
      });
    },
    async delete(providerId) {
      await enqueue(providerId, async () => {
        const credentials = await load();
        if (!(providerId in credentials)) return;
        delete cache[providerId];
        if (Object.keys(cache).length) await flush();
        else await rm(filePath, { force: true });
      });
    },
  };
}

/**
 * Variables Claude Code injects into a session it spawns to route the *agent's*
 * own model traffic. They are this tool's session credential, not the user's app
 * configuration: honouring them would make the app work only while it runs under
 * Claude Code, and would bill a credential the user never pointed at this app.
 *
 * Everything else -- ANTHROPIC_API_KEY, OPENROUTER_API_KEY, OPENAI_API_KEY ... --
 * is the user's own environment and stays visible, with its source shown in the UI.
 */
export const SESSION_ONLY_ENV = ['ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_OAUTH_TOKEN'];

/**
 * AuthContext for pi-ai. `env()` hides the session-only variables above; a stored
 * credential wins over ambient anyway (see resolveProviderAuth), so this only
 * governs what a *not yet connected* provider may silently fall back to.
 */
export function appAuthContext(env = process.env, hidden = SESSION_ONLY_ENV) {
  const blocked = new Set(hidden);
  return {
    async env(name) {
      return blocked.has(name) ? undefined : env[name];
    },
    async fileExists(file) {
      return existsSync(file.startsWith('~') ? path.join(os.homedir(), file.slice(1)) : file);
    },
  };
}
