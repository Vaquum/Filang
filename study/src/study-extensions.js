import { installExtension } from './boot.js';
import { sha256Hex } from './data.js';
import { Registry } from './registry.js';
import { h, mount } from './ui/dom.js';

const STORE = 'sfd.study.extensions.v1';
const encoder = new TextEncoder();

function identify(artifact) {
  return `${artifact.id}@${artifact.version}`;
}

function decode(input) {
  if (typeof input?.text !== 'string' || typeof input?.file !== 'string' || !input.file) {
    throw new Error('Each definition needs its original file name and JSON text.');
  }
  const bytes = encoder.encode(input.text);
  const digest = sha256Hex(bytes);
  if (input.sha256 !== digest) throw new Error(`Content digest mismatch in ${input.file}.`);
  let artifact;
  try { artifact = JSON.parse(input.text); }
  catch (err) { throw new Error(`${input.file} contains invalid JSON. ${err.message}`); }
  if (artifact?.artifact !== 'limen.sfd.definition' || !Number.isSafeInteger(artifact.version) || artifact.version < 1 || !/^[a-z_][a-z0-9_]*$/.test(artifact.id ?? '')) {
    throw new Error(`${input.file} needs a versioned limen.sfd.definition object.`);
  }
  if (artifact.depends !== undefined && !Array.isArray(artifact.depends)) throw new Error(`${input.file} dependencies must form an array.`);
  return { file: input.file, text: input.text, sha256: digest, bytes, artifact, key: identify(artifact) };
}

function stage(bundle, inputs) {
  if (!Array.isArray(inputs)) throw new Error('Expected an array of saved definition files.');
  const registry = new Registry();
  registry.functions = new Map(bundle.registry.functions);
  registry.named = new Map(bundle.registry.named);
  registry.extensions = [...bundle.registry.extensions];
  const shadow = { ...bundle, env: { ...bundle.env, registry }, registry, extensions: [...bundle.extensions] };
  const decoded = inputs.map(decode);
  const byId = new Map(shadow.extensions.filter((r) => r.ok).map((r) => [identify(r.artifact), r]));
  const pending = new Map();
  for (const source of decoded) {
    const previous = byId.get(source.key) || pending.get(source.key);
    if (previous) {
      if (previous.sha256 !== source.sha256) throw new Error(`${source.key} already has different content. Give the edited definition a new version.`);
    } else {
      pending.set(source.key, source);
    }
  }
  const additions = [];
  // A stable topological order lets a study carry its files in any order.
  while (pending.size) {
    const keys = [...pending.keys()].sort();
    const key = keys.find((id) => (pending.get(id).artifact.depends || []).every((dep) => !pending.has(`${dep?.name}@${dep?.version}`)));
    if (!key) throw new Error(`Cyclic definition dependencies among ${keys.join(', ')}.`);
    const source = pending.get(key);
    const record = installExtension(shadow, source);
    if (!record.ok) throw new Error(`${key} failed validation. ${record.errors.join(' ')}`);
    record.custom = true;
    byId.set(key, record);
    additions.push(record);
    pending.delete(key);
  }
  return { additions, requested: decoded.map((s) => byId.get(s.key)) };
}

function commit(bundle, staged) {
  for (const record of staged.additions) {
    bundle.registry.addFunction(record.def);
    bundle.registry.extensions.push(record.def);
    bundle.extensions.push(record);
  }
  return staged.requested;
}

/** Atomically restore a packet's exact raw UTF-8 JSON files into this session. */
export function installSaved(bundle, artifacts) {
  return commit(bundle, stage(bundle, artifacts));
}

function readStored(storage) {
  const text = storage.getItem(STORE);
  if (text === null) return [];
  const records = JSON.parse(text);
  if (!Array.isArray(records)) throw new Error('The local definition library is unreadable.');
  return records;
}

export function loadInstalled(bundle, storage = globalThis.localStorage) {
  return installSaved(bundle, readStored(storage));
}

function portable(record) {
  return { file: record.file, text: record.text, sha256: record.sha256 };
}

/** Persist only after validation. A quota or storage failure leaves the registry intact. */
export function installLocal(bundle, artifacts, storage = globalThis.localStorage) {
  const stored = readStored(storage);
  const staged = stage(bundle, [...stored, ...artifacts]);
  const saved = new Map(staged.requested.filter((r) => r.custom).map((r) => [identify(r.artifact), portable(r)]));
  storage.setItem(STORE, JSON.stringify([...saved.values()]));
  commit(bundle, staged);
  return staged.requested.slice(stored.length);
}

export function renderExtensions(root, bundle, onInstalled) {
  const status = h('p', { class: 'small', role: 'status', 'aria-live': 'polite' });
  const list = h('div', { class: 'definition-list' });
  const picker = h('input', { type: 'file', accept: '.json,application/json', multiple: true, 'aria-label': 'Choose definition JSON files' });
  let busy = false;

  function refresh() {
    const definitions = bundle.extensions.filter((r) => r.ok);
    mount(list, definitions.map((r) => h('div', { class: 'row' },
      h('code', null, identify(r.artifact)),
      h('span', { class: 'small' }, r.def.title),
      h('button', { type: 'button', 'aria-label': `Use ${identify(r.artifact)} in question`, onclick: () => {
        try { onInstalled(r.def); status.textContent = `Applied ${identify(r.artifact)}.`; }
        catch (err) { status.textContent = err.message; }
      } }, 'Use in question'))));
  }

  async function importFiles(files) {
    if (busy || !files.length) return;
    busy = true;
    picker.disabled = true;
    status.textContent = 'Checking definitions against the recording…';
    try {
      const artifacts = await Promise.all([...files].map(async (f) => {
        const bytes = new Uint8Array(await f.arrayBuffer());
        const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
        return { file: f.name, text, sha256: sha256Hex(bytes) };
      }));
      const write = () => installLocal(bundle, artifacts);
      const records = globalThis.navigator?.locks ? await navigator.locks.request(STORE, write) : write();
      refresh();
      status.textContent = records.map((r) => `${identify(r.artifact)} · ${r.artifact.conformance.length} recorded checks passed`).join(' / ');
    } catch (err) {
      status.textContent = `Installation failed. ${err.message}`;
    } finally {
      picker.value = '';
      picker.disabled = false;
      busy = false;
    }
  }

  picker.addEventListener('change', () => importFiles(picker.files));
  const drop = h('div', { class: 'definition-drop',
    ondragover: (e) => e.preventDefault(),
    ondrop: (e) => { e.preventDefault(); importFiles(e.dataTransfer.files); },
  }, h('label', null, 'Choose or drop agent-authored definition files ', picker));
  mount(root, drop, status, list);
  refresh();
}
