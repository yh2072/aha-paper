// Provider and credential operations, exposed to the Python app as a JSON CLI.
//
// This is the "daemon" half of ahaexplain's split: pi-ai owns the provider
// registry, the model catalog and auth resolution; the app owns persistence and
// the UI. Nothing here knows which env var holds which key -- pi-ai's provider
// definitions do, and they report the answer through checkAuth().
import { getBuiltinImageModels, getBuiltinModel, getBuiltinModels } from '@earendil-works/pi-ai/providers/all';
import { appModels } from './pi-auth.mjs';

/** Non-secret status for every known provider, with the source label for the UI. */
async function providers(models) {
  const rows = [];
  for (const provider of models.getProviders()) {
    // checkAuth is the display-safe probe: it reports configuration without
    // refreshing OAuth tokens or running configured api-key commands.
    const check = await models.checkAuth(provider.id).catch(() => undefined);
    const methods = [];
    if (provider.auth?.oauth) methods.push({ type: 'oauth', label: provider.auth.oauth.name, subscription: Boolean(provider.auth.oauth.isSubscription) });
    if (provider.auth?.apiKey?.login) methods.push({ type: 'api_key', label: provider.auth.apiKey.name });
    rows.push({
      id: provider.id,
      name: provider.name,
      base_url: provider.baseUrl ?? '',
      configured: Boolean(check),
      ...(check?.source ? { source: check.source } : {}),
      ...(check?.type ? { credential_type: check.type } : {}),
      methods,
    });
  }
  return rows.sort((left, right) => Number(right.configured) - Number(left.configured) || left.name.localeCompare(right.name));
}

/** The provider's catalog, straight from pi-ai. No network call, no key needed. */
function catalog(providerId, kind = 'chat') {
  // One authority for every use: chat models for scripts and animation code,
  // image models for covers. An endpoint's own /models list is not consulted.
  const read = kind === 'image' ? getBuiltinImageModels : getBuiltinModels;
  let models;
  try {
    models = read(providerId);
  } catch {
    models = undefined;
  }
  // An unknown provider yields undefined or an empty list rather than throwing.
  if (!models?.length) throw new Error(getBuiltinModels(providerId)?.length ? `${providerId} has no ${kind} models` : `Unknown provider "${providerId}"`);
  return models.map((model) => ({
    id: model.id, name: model.name ?? model.id, api: model.api,
    reasoning: Boolean(model.reasoning), context_window: model.contextWindow ?? null,
    max_tokens: model.maxTokens ?? null, cost: model.cost ?? null,
  }));
}

/** Store an api-key credential through the provider's own login flow. */
async function login(models, providerId, key) {
  const provider = models.getProvider(providerId);
  if (!provider) throw new Error(`Unknown provider "${providerId}"`);
  if (!provider.auth?.apiKey?.login) throw new Error(`${provider.name} does not accept an API key`);
  if (!/^[\x21-\x7E]+$/.test(key)) throw new Error('API key must contain only printable ASCII characters');
  const controller = new AbortController();
  await models.login(providerId, 'api_key', {
    signal: controller.signal,
    notify: () => {},
    // The provider decides what it asks for; an api-key flow asks for the secret.
    prompt: async (prompt) => {
      if (prompt.type !== 'secret' && prompt.type !== 'text') throw new Error(`${provider.name} needs an interactive sign-in`);
      return key;
    },
  });
  const check = await models.checkAuth(providerId);
  return { id: providerId, configured: Boolean(check), ...(check?.source ? { source: check.source } : {}) };
}

/**
 * Resolve a provider's endpoint and credential for the app's own HTTP paths.
 *
 * Server-side only: it is how cover images and script generation share the one
 * connection the user made, instead of each keeping its own Base URL and key.
 * The settings API never calls this, so a credential still never reaches a browser.
 */
async function resolve(models, providerId) {
  const provider = models.getProvider(providerId);
  if (!provider) throw new Error(`Unknown provider "${providerId}"`);
  const result = await models.getAuth(providerId);
  if (!result) throw new Error(`${provider.name} is not connected`);
  return { id: providerId, name: provider.name,
           base_url: result.auth.baseUrl || provider.baseUrl || '',
           api_key: result.auth.apiKey || '',
           headers: result.auth.headers || {},
           source: result.source || '' };
}

/**
 * End-to-end check: auth, protocol, model ID and entitlement in one tiny request.
 *
 * Listing a catalog would prove none of those — a key can list models it may not
 * call — so this sends the smallest real request instead. Cost is a few tokens.
 */
async function probe(models, providerId, modelId, baseUrl) {
  let model = getBuiltinModel(providerId, modelId);
  if (!model?.id) throw new Error(`Model "${modelId}" is not in ${providerId}'s catalog`);
  if (baseUrl) model = { ...model, baseUrl };
  if (!(await models.checkAuth(providerId).catch(() => undefined))) throw new Error(`${providerId} is not connected`);
  const answer = await models.completeSimple(model, { messages: [{ role: 'user', content: 'Reply with OK.' }] }, { maxTokens: 64 });
  if (answer.errorMessage || answer.stopReason === 'error') throw new Error(answer.errorMessage || 'Provider rejected the request');
  const usage = answer.usage ?? {};
  return { id: providerId, model: model.id, api: model.api, ok: true,
           tokens: (usage.input ?? 0) + (usage.output ?? 0) };
}

const [command, argument, extra, extraTwo] = process.argv.slice(2);
try {
  const models = appModels();
  let result;
  if (command === 'providers') result = await providers(models);
  else if (command === 'models') result = catalog(argument, extra);
  else if (command === 'login') {
    const key = (await new Response(process.stdin).text()).trim();
    if (!key) throw new Error('No API key on stdin');
    result = await login(models, argument, key);
  } else if (command === 'logout') {
    await models.logout(argument);
    result = { id: argument, configured: false };
  } else if (command === 'resolve') {
    result = await resolve(models, argument);
  } else if (command === 'probe') {
    result = await probe(models, argument, extra, extraTwo);
  } else if (command === 'check') {
    const check = await models.checkAuth(argument).catch(() => undefined);
    result = { id: argument, configured: Boolean(check), ...(check?.source ? { source: check.source } : {}), ...(check?.type ? { credential_type: check.type } : {}) };
  } else throw new Error(`Unknown command "${command ?? ''}". Use providers | models <id> | login <id> | logout <id> | check <id> | resolve <id> | probe <id> <model> [baseUrl]`);
  process.stdout.write(JSON.stringify(result));
} catch (error) {
  process.stderr.write(String(error?.message ?? error));
  process.exitCode = 1;
}
