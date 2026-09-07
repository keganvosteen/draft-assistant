// The disk workspace is authoritative across app versions, ports and browsers.
// A browser copy journals pending writes so a failed request never clears data.
const WORKSPACE_CACHE_KEY = 'fda_workspace';

function workspaceData(value) {
  if (!value || value.schemaVersion !== 1 || !Array.isArray(value.leagues)
      || !value.picks || typeof value.picks !== 'object' || Array.isArray(value.picks)) {
    throw new Error('This is not a supported Draft Assistant backup.');
  }
  if (value.leagues.some(league => !league || typeof league.id !== 'string'
      || typeof league.name !== 'string' || !Number.isInteger(league.numTeams) || league.numTeams < 1
      || !league.rosterSlots || typeof league.rosterSlots !== 'object' || Array.isArray(league.rosterSlots))) {
    throw new Error('The backup contains an incomplete league. Your saved leagues have not been replaced.');
  }
  return {schemaVersion:1, leagues:value.leagues, picks:value.picks, preferences:value.preferences || {}};
}

function legacyWorkspace(storage) {
  const read = (key, fallback) => JSON.parse(storage.getItem(key) || JSON.stringify(fallback));
  return workspaceData({schemaVersion:1, leagues:read('fda_leagues', []), picks:read('fda_picks', {}),
    preferences:{tweaks:read('fda_tweaks', {})}});
}

function createWorkspaceClient({storage = localStorage, request = fetch, onStatus = () => {}} = {}) {
  let revision = 0, committed = null, pending = null, running = null, restoring = null, lastError = null;
  const encode = value => JSON.stringify(workspaceData(value));
  const cache = () => {
    try { storage.setItem(WORKSPACE_CACHE_KEY, JSON.stringify({
      ...workspaceData(pending || committed), revision, pending:!!pending,
    })); } catch { /* Disk saving remains available when browser storage is full. */ }
  };
  const api = async (method, body) => {
    const response = await request('/api/workspace', {method, cache:'no-store',
      ...(body ? {headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {})});
    const result = await response.json();
    if (!response.ok || result.error) {
      throw new Error(result.error || 'Could not access the saved leagues.');
    }
    return result;
  };
  const pump = () => {
    if (running) return running;
    lastError = null;
    running = (async () => {
      while (pending) {
        onStatus({state:'saving'});
        const snapshot = pending;
        const saved = await api('POST', {...snapshot, revision});
        revision = saved.revision;
        committed = workspaceData(saved);
        if (pending === snapshot) pending = null;
        cache();
      }
      onStatus({state:'saved'});
    })().catch(error => {
      lastError = error;
      onStatus({state:'error', message:error.message});
      throw error;
    }).finally(() => { running = null; });
    return running;
  };
  return {
    async load() {
      const disk = await api('GET');
      const cached = JSON.parse(storage.getItem(WORKSPACE_CACHE_KEY) || 'null');
      revision = disk.revision;
      if (disk.exists) {
        committed = workspaceData(disk);
        if (cached?.pending && encode(cached) !== encode(committed)) {
          if (cached.revision !== revision) {
            throw new Error('This window has unsaved changes and another window saved a newer version. Export this window’s backup before reloading.');
          }
          pending = workspaceData(cached);
          await pump();
        }
      } else {
        committed = cached ? workspaceData(cached) : legacyWorkspace(storage);
        pending = committed;
        cache();
        await pump();
      }
      cache();
      onStatus({state:'saved'});
      return {...committed, exists:disk.exists};
    },
    save(value) {
      // The restore dialog owns the next state. Background work from the old
      // screen must not race its POST or queue that old screen over the backup.
      if (restoring) return;
      const next = JSON.parse(encode(value));
      if (encode(next) === encode(pending || committed)) return;
      pending = next;
      cache();
      pump().catch(() => {});
    },
    async flush() {
      if (restoring) await restoring;
      if (running) await running;
      else if (pending) await pump();
      if (lastError) throw lastError;
      return {...committed, revision};
    },
    async restore(value) {
      const restored = JSON.parse(encode(value));
      if (restoring) throw new Error('A backup restore is already in progress.');
      restoring = (async () => {
        if (running) await running;
        if (pending) await pump();
        onStatus({state:'saving'});
        const saved = await api('POST', {...restored, revision});
        committed = workspaceData(saved);
        revision = saved.revision;
        cache();
        onStatus({state:'saved'});
        return committed;
      })().catch(error => {
        // A failed pre-restore flush keeps its pending recovery journal. If
        // only the restore failed, the previous saved copy is still current.
        if (!pending) onStatus({state:'saved'});
        throw error;
      }).finally(() => { restoring = null; });
      return restoring;
    },
    hasPending: () => !!pending || !!restoring,
    async useDiskCopy() {
      if (running || restoring) throw new Error('Wait for the current save to finish first.');
      const disk = await api('GET');
      if (!disk.exists) throw new Error('No saved disk copy is available. Export this window’s backup first.');
      const saved = workspaceData(disk);
      committed = saved;
      revision = disk.revision;
      pending = null;
      lastError = null;
      cache();
      onStatus({state:'saved'});
      return saved;
    },
    snapshot() {
      if (pending) return {...pending, revision};
      const cached = JSON.parse(storage.getItem(WORKSPACE_CACHE_KEY) || 'null');
      return cached?.pending ? cached : committed || cached || legacyWorkspace(storage);
    },
  };
}

Object.assign(window, {workspaceData, legacyWorkspace, createWorkspaceClient});
