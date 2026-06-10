// tweaks-panel.jsx — Reusable Tweaks shell + form-control helpers.

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    background:rgba(250,249,247,.92);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 'DM Sans',ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:pointer;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}
  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}
  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:pointer}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:pointer}
  .twk-toggle-btn{position:fixed;bottom:16px;right:16px;z-index:2147483645;
    background:#1a1d2e;color:#fff;border:none;border-radius:99px;
    padding:8px 16px;font:600 12px 'DM Sans',sans-serif;cursor:pointer;
    box-shadow:0 4px 16px rgba(0,0,0,.2);letter-spacing:.3px}
  .twk-toggle-btn:hover{background:#3a5bef}
`;

function useTweaks(defaults) {
  const [values, setValues] = React.useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('fda_tweaks') || 'null');
      return saved ? { ...defaults, ...saved } : defaults;
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

function TweaksPanel({ title = 'Tweaks', children }) {
  const [open, setOpen] = React.useState(false);

  if (!open) {
    return (
      <>
        <style>{__TWEAKS_STYLE}</style>
        <button className="twk-toggle-btn" onClick={() => setOpen(true)}>⚙ Tweaks</button>
      </>
    );
  }
  return (
    <>
      <style>{__TWEAKS_STYLE}</style>
      <div className="twk-panel">
        <div className="twk-hd">
          <b>{title}</b>
          <button className="twk-x" aria-label="Close" onClick={() => setOpen(false)}>✕</button>
        </div>
        <div className="twk-body">{children}</div>
      </div>
    </>
  );
}

function TweakSection({ title, label, children }) {
  return (
    <>
      <div className="twk-sect">{title || label}</div>
      {children}
    </>
  );
}

function TweakRow({ label, value, children }) {
  return (
    <div className="twk-row">
      <div className="twk-lbl">
        <span>{label}</span>
        {value != null && <span className="twk-val">{value}</span>}
      </div>
      {children}
    </div>
  );
}

function TweakSlider({ id, label, min = 0, max = 100, step = 1, unit = '', tweaks, setTweaks, value, onChange }) {
  const v = value !== undefined ? value : tweaks[id];
  const handleChange = e => {
    const num = Number(e.target.value);
    if (onChange) onChange(num);
    else if (setTweaks && id) setTweaks(id, num);
  };
  return (
    <TweakRow label={label} value={`${v}${unit}`}>
      <input type="range" className="twk-slider" min={min} max={max} step={step}
        value={v} onChange={handleChange} />
    </TweakRow>
  );
}

Object.assign(window, {
  useTweaks, TweaksPanel, TweakSection, TweakRow, TweakSlider,
});
