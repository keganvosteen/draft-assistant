// Engine tunables (rollout precision, how many opponents autodraft), persisted
// per browser. The values are surfaced by the draft room's Engine settings
// modal; this only owns storage and defaulting.
function useTweaks(defaults) {
  const [values, setValues] = React.useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('fda_tweaks') || 'null');
      if (!saved || typeof saved !== 'object') return defaults;
      // Keep only keys the current build knows about, so a stale saved blob
      // can't reintroduce a setting that no longer exists.
      return Object.fromEntries(Object.keys(defaults).map(key => [
        key, Object.prototype.hasOwnProperty.call(saved, key) ? saved[key] : defaults[key],
      ]));
    } catch { return defaults; }
  });

  const update = React.useCallback((keyOrObj, val) => {
    setValues(prev => {
      const next = typeof keyOrObj === 'string'
        ? { ...prev, [keyOrObj]: val }
        : { ...prev, ...keyOrObj };
      try { localStorage.setItem('fda_tweaks', JSON.stringify(next)); } catch {}
      return next;
    });
  }, []);

  return [values, update];
}

Object.assign(window, { useTweaks });
