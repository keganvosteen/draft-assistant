// ─── UI KIT ───────────────────────────────────────────────────────────────────
// The shared design system: colour/spacing tokens plus every primitive used by
// more than one screen. Loaded first, so everything else can reference these as
// plain globals (each Babel script gets its own scope — the Object.assign at
// the bottom is what publishes them).

// Token values mirror the custom properties in styles.css. Inline styles read
// them from here; real CSS reads them from there. Change both together.
const T = {
  bg:           '#f4f6fb',
  surface:      '#ffffff',
  surfaceAlt:   '#f7f9fd',
  border:       '#e2e6f0',
  borderLight:  '#eef1f7',
  primary:      '#3a5bef',
  primaryHover: '#2d4ad4',
  primaryLight: '#eef1fd',
  green:        '#15803d',
  greenLight:   '#dcfce7',
  amber:        '#b45309',
  amberLight:   '#fef3c7',
  red:          '#dc2626',
  redLight:     '#fee2e2',
  blue:         '#0369a1',
  blueLight:    '#e0f2fe',
  text:         '#171a2b',
  muted:        '#66708a',
  mutedLight:   '#98a1b6',

  r:   '10px',
  rsm: '7px',
  rxs: '5px',

  shadowSm: '0 1px 2px rgba(16, 24, 60, .06)',
  shadowMd: '0 4px 14px rgba(16, 24, 60, .10)',
  shadowLg: '0 18px 48px rgba(16, 24, 60, .18)',

  mono: 'var(--mono)',
};
// Historic alias — a couple of call sites reached for T.danger before it existed.
T.danger = T.red;

const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'DST'];

// Brand accents used to tint league cards by platform.
const PLATFORM_COLORS = {
  ESPN: '#cc0000', Yahoo: '#6001d2', Sleeper: '#1e1e1e', 'NFL.com': '#013369',
};

const POS_COLORS = {
  QB:  { bg:'#fef3c7', fg:'#92400e' },
  RB:  { bg:'#dcfce7', fg:'#14532d' },
  WR:  { bg:'#dbeafe', fg:'#1e3a8a' },
  TE:  { bg:'#ede9fe', fg:'#4c1d95' },
  K:   { bg:'#f3f4f6', fg:'#374151' },
  DST: { bg:'#fce7f3', fg:'#831843' },
};

// ─── VIEWPORT ────────────────────────────────────────────────────────────────
function useWindowWidth() {
  const [width, setWidth] = React.useState(
    typeof window !== 'undefined' ? window.innerWidth : 1200
  );
  React.useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return width;
}

// One breakpoint vocabulary for the whole app, so "what is mobile" is answered
// in exactly one place.
function useLayout() {
  const width = useWindowWidth();
  return {
    width,
    isMobile:  width < 760,
    isTablet:  width >= 760 && width < 1140,
    isDesktop: width >= 1140,
  };
}

// Close on Escape. Overlays register in mount order and only the topmost one
// responds, so Escape inside a confirm dialog raised over a modal doesn't
// dismiss both at once.
const _overlayStack = [];

function useEscape(onEscape, active = true) {
  React.useEffect(() => {
    if (!active) return undefined;
    const token = {};
    _overlayStack.push(token);
    const onKey = e => {
      if (e.key !== 'Escape') return;
      if (_overlayStack[_overlayStack.length - 1] !== token) return;
      e.stopPropagation();
      onEscape();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      const i = _overlayStack.indexOf(token);
      if (i >= 0) _overlayStack.splice(i, 1);
    };
  }, [onEscape, active]);
}

// Keep Tab inside a dialog. Without this, tabbing past the last control walks
// into the page behind the overlay, which is invisible and unusable.
function useFocusTrap(ref, active = true) {
  React.useEffect(() => {
    if (!active || !ref.current) return undefined;
    const node = ref.current;
    const focusables = () => Array.from(node.querySelectorAll(
      'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
    )).filter(el => el.offsetParent !== null);
    const onKey = e => {
      if (e.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    node.addEventListener('keydown', onKey);
    return () => node.removeEventListener('keydown', onKey);
  }, [ref, active]);
}

// ─── BUTTONS ─────────────────────────────────────────────────────────────────
// variant: primary | secondary | subtle | danger | success
// size:    sm | md | lg
function Btn({ children, onClick, variant = 'primary', size = 'md', disabled,
               type = 'button', title, style = {}, ...rest }) {
  const sizes = {
    sm: { padding: '5px 10px', fontSize: 12,   borderRadius: T.rxs },
    md: { padding: '8px 14px', fontSize: 13.5, borderRadius: T.rsm },
    lg: { padding: '11px 20px', fontSize: 15,  borderRadius: T.rsm },
  };
  const variants = {
    primary:   { background: T.primary,    color: '#fff',    border: '1px solid ' + T.primary },
    secondary: { background: T.surface,    color: T.text,    border: '1px solid ' + T.border },
    subtle:    { background: 'transparent', color: T.muted,  border: '1px solid transparent' },
    danger:    { background: T.surface,    color: T.red,     border: '1px solid ' + T.border },
    success:   { background: T.greenLight, color: T.green,   border: '1px solid ' + T.greenLight },
  };
  return (
    <button
      type={type} onClick={onClick} disabled={disabled} title={title} className="da-btn"
      style={{
        cursor: 'pointer', fontWeight: 600, display: 'inline-flex',
        alignItems: 'center', justifyContent: 'center', gap: 6, whiteSpace: 'nowrap',
        ...sizes[size], ...variants[variant], ...style,
      }}
      {...rest}>
      {children}
    </button>
  );
}

function Badge({ label, color = 'gray', title }) {
  const colors = {
    blue:  { bg: T.blueLight,   fg: T.blue },
    green: { bg: T.greenLight,  fg: T.green },
    amber: { bg: T.amberLight,  fg: T.amber },
    red:   { bg: T.redLight,    fg: T.red },
    gray:  { bg: T.borderLight, fg: T.muted },
  };
  const c = colors[color] || colors.gray;
  return (
    <span title={title} style={{
      background: c.bg, color: c.fg, borderRadius: 99, padding: '2px 9px',
      fontSize: 11, fontWeight: 700, letterSpacing: .2, whiteSpace: 'nowrap',
    }}>{label}</span>
  );
}

function PosBadge({ pos }) {
  const c = POS_COLORS[pos] || { bg: T.borderLight, fg: T.muted };
  return (
    <span style={{
      background: c.bg, color: c.fg, borderRadius: T.rxs, padding: '2px 7px',
      fontSize: 11, fontWeight: 800, letterSpacing: .3,
      display: 'inline-block', minWidth: 34, textAlign: 'center',
    }}>{pos}</span>
  );
}

// Availability status from the news context. It reaches the chip in three
// different vocabularies, because `primary_availability` returns whichever
// signal it finds first: Sleeper's short injury codes ("Q", "IR"), a roster
// status spelled out in prose ("Injured Reserve", "Practice Squad"), or
// practice participation ("Did Not Participate In Practice"). Normalise all
// three onto one abbreviation and one severity — otherwise a season-ending
// status renders in the same amber as a questionable tag, at a width no chip
// beside a player name can hold.
const AVAILABILITY_TONES = {
  red:   { bg: T.redLight,    fg: T.red },
  amber: { bg: T.amberLight,  fg: T.amber },
  gray:  { bg: T.borderLight, fg: T.muted },
};

// Matched in order against the normalised status, so a phrase always wins over
// a shorter code it happens to contain ("out for season" before "out"). Codes
// match on word boundaries because the feed also compounds them
// ("Reserve/PUP", "Reserve/COVID-19").
const AVAILABILITY_RULES = [
  [/injured reserve|\bir\b/,      'IR',   'red'],
  [/physically unable|\bpup\b/,   'PUP',  'red'],
  [/non football injury|\bnfi\b/, 'NFI',  'red'],
  [/suspend|\bsus\b/,             'SUS',  'red'],
  [/covid/,                       'COV',  'red'],
  [/\bdnr\b/,                     'DNR',  'red'],
  [/^na$/,                        'NA',   'red'],
  [/retired/,                     'RET',  'red'],
  [/inactive/,                    'INA',  'red'],
  [/practice squad/,              'PS',   'gray'],
  [/free agent/,                  'FA',   'gray'],
  [/did not participate/,         'DNP',  'amber'],
  [/limited participation/,       'LTD',  'amber'],
  [/full participation/,          'FULL', 'gray'],
  [/doubtful|^d$/,                'D',    'amber'],
  [/questionable|^q$/,            'Q',    'amber'],
  [/out/,                         'OUT',  'red'],
];

// Mirrors context.py::_normalized, so both sides read the feed's wording the
// same way.
function normalizedAvailability(status) {
  return String(status).toLowerCase().replace(/[-/]/g, ' ').replace(/\s+/g, ' ').trim();
}

function availabilityChipStyle(status) {
  const key = normalizedAvailability(status);
  const rule = AVAILABILITY_RULES.find(([re]) => re.test(key));
  if (rule) return { short: rule[1], tone: rule[2] };
  // Unknown wording is still worth showing — amber says "check this", and the
  // tooltip carries the full text the chip cannot.
  const raw = String(status).toUpperCase();
  return { short: raw.length > 6 ? `${raw.slice(0, 5).trim()}…` : raw, tone: 'amber' };
}

function AvailabilityChip({ status, title }) {
  if (!status) return null;
  const { short, tone } = availabilityChipStyle(status);
  const c = AVAILABILITY_TONES[tone];
  return (
    <span title={title || `Availability: ${status}`} style={{
      background: c.bg, color: c.fg, borderRadius: 3, padding: '1px 5px',
      fontSize: 9.5, fontWeight: 800, letterSpacing: .3, flexShrink: 0, whiteSpace: 'nowrap',
    }}>{short}</span>
  );
}

// "source updated" is bookkeeping about the feed, not news about the player —
// it should never occupy the one line a card has for explaining a change.
function playerNewsSignals(signals) {
  return (signals || []).filter(sig => sig && sig.kind !== 'source_updated');
}

function Spinner({ size = 32 }) {
  return <div className="loading-spinner" style={{ width: size, height: size }} />;
}

// ─── FORM CONTROLS ───────────────────────────────────────────────────────────
function Field({ label, hint, children, style = {} }) {
  return (
    <div style={{ marginBottom: 16, ...style }}>
      <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: T.text, marginBottom: 5 }}>
        {label}
        {hint && <span style={{ fontWeight: 400, color: T.muted, marginLeft: 6 }}>{hint}</span>}
      </label>
      {children}
    </div>
  );
}

const CONTROL_STYLE = {
  width: '100%', padding: '8px 11px',
  border: '1.5px solid ' + T.border, borderRadius: T.rsm, fontSize: 13.5,
  color: T.text, background: T.surface, outline: 'none',
};

function Input({ value, onChange, type = 'text', style = {}, ...rest }) {
  return (
    <input type={type} value={value} onChange={onChange} className="da-input"
      style={{ ...CONTROL_STYLE, ...style }} {...rest} />
  );
}

function Textarea({ value, onChange, style = {}, ...rest }) {
  return (
    <textarea value={value} onChange={onChange} className="da-input"
      style={{ ...CONTROL_STYLE, resize: 'vertical', lineHeight: 1.5, ...style }} {...rest} />
  );
}

function Select({ value, onChange, options, style = {}, ...rest }) {
  return (
    <select value={value} onChange={onChange} className="da-input"
      style={{ ...CONTROL_STYLE, cursor: 'pointer', ...style }} {...rest}>
      {options.map(o => (
        <option key={o.value !== undefined ? o.value : o} value={o.value !== undefined ? o.value : o}>
          {o.label !== undefined ? o.label : o}
        </option>
      ))}
    </select>
  );
}

// Radio group rendered as a segmented control — the pattern this app uses for
// scoring format, draft type, and data source.
function SegmentedControl({ value, onChange, options, name, style = {} }) {
  return (
    <div role="radiogroup" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', ...style }}>
      {options.map(o => {
        const on = value === o.value;
        return (
          <label key={o.value} style={{
            flex: '1 1 0', minWidth: 92, cursor: 'pointer', textAlign: 'center',
            border: `1.5px solid ${on ? T.primary : T.border}`, borderRadius: T.rsm,
            padding: o.hint ? '9px 12px' : '8px 12px',
            background: on ? T.primaryLight : T.surface,
          }}>
            <input type="radio" name={name} value={o.value} checked={on}
              onChange={() => onChange(o.value)}
              style={{ position: 'absolute', opacity: 0, width: 0, height: 0 }} />
            <div style={{ fontSize: 13, fontWeight: 600, color: on ? T.primary : T.text }}>{o.label}</div>
            {o.hint && <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>{o.hint}</div>}
          </label>
        );
      })}
    </div>
  );
}

function Checkbox({ checked, onChange, label, hint }) {
  return (
    <div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: T.text, cursor: 'pointer' }}>
        <input type="checkbox" checked={checked} onChange={onChange} />
        {label}
      </label>
      {hint && (
        <div style={{ fontSize: 11.5, color: T.muted, marginTop: 4, marginLeft: 24, lineHeight: 1.45 }}>{hint}</div>
      )}
    </div>
  );
}

// ─── OVERLAYS ────────────────────────────────────────────────────────────────
// dismissible=false is for a modal that owns an in-flight operation: the
// backdrop, Escape, and the × all stop working rather than pretending to.
function Modal({ title, subtitle, onClose, children, footer, width = 560, dismissible = true }) {
  useEscape(onClose, dismissible);
  const dialogRef = React.useRef(null);
  useFocusTrap(dialogRef);
  const bodyRef = React.useRef(null);
  React.useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    // Land focus inside the dialog so Tab stays in it and Escape is live.
    const first = bodyRef.current && bodyRef.current.querySelector(
      'input,select,textarea,button,[href],[tabindex]:not([tabindex="-1"])');
    if (first) first.focus({ preventScroll: true });
    return () => { document.body.style.overflow = prev; };
  }, []);

  return (
    <div className="da-overlay" role="presentation"
      style={{
        position: 'fixed', inset: 0, background: 'rgba(15,20,40,.42)', zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
      }}
      onMouseDown={e => dismissible && e.target === e.currentTarget && onClose()}>
      <div ref={dialogRef} className="da-pop" role="dialog" aria-modal="true" aria-label={title}
        style={{
          background: T.surface, borderRadius: 14, width: '100%', maxWidth: width,
          maxHeight: 'min(90vh, 900px)', display: 'flex', flexDirection: 'column',
          boxShadow: T.shadowLg, overflow: 'hidden',
        }}>
        <div style={{
          padding: '16px 20px', borderBottom: `1px solid ${T.border}`, flexShrink: 0,
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12,
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: T.text }}>{title}</div>
            {subtitle && <div style={{ fontSize: 12.5, color: T.muted, marginTop: 3 }}>{subtitle}</div>}
          </div>
          {dismissible && (
            <button onClick={onClose} aria-label="Close" style={{
              background: 'none', border: 'none', fontSize: 20, cursor: 'pointer',
              color: T.muted, lineHeight: 1, padding: '2px 4px', flexShrink: 0,
            }}>×</button>
          )}
        </div>
        <div ref={bodyRef} style={{ padding: 20, overflowY: 'auto', flex: 1, minHeight: 0 }}>{children}</div>
        {footer && (
          <div style={{
            padding: '13px 20px', borderTop: `1px solid ${T.border}`, flexShrink: 0,
            display: 'flex', justifyContent: 'flex-end', gap: 9, background: T.surfaceAlt,
          }}>{footer}</div>
        )}
      </div>
    </div>
  );
}

function Drawer({ title, onClose, children, width = 380 }) {
  useEscape(onClose);
  return (
    <div className="da-overlay" style={{
      position: 'fixed', inset: 0, background: 'rgba(15,20,40,.42)', zIndex: 990,
      display: 'flex', justifyContent: 'flex-end',
    }} onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="da-drawer" role="dialog" aria-modal="true" aria-label={title} style={{
        background: T.surface, width: '100%', maxWidth: width, height: '100%',
        display: 'flex', flexDirection: 'column', boxShadow: T.shadowLg, overflow: 'hidden',
      }}>
        <div style={{
          padding: '13px 16px', borderBottom: `1px solid ${T.border}`, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: T.text }}>{title}</span>
          <button onClick={onClose} aria-label="Close" style={{
            background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: T.muted, padding: '0 4px',
          }}>×</button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          {children}
        </div>
      </div>
    </div>
  );
}

// Anchored dropdown. `items` entries: {label, onClick, hint, disabled, tone} or
// {type:'sep'} / {type:'label', label}.
function Menu({ label, items, align = 'right', buttonProps = {} }) {
  const [open, setOpen] = React.useState(false);
  const wrapRef = React.useRef(null);
  useEscape(() => setOpen(false), open);
  React.useEffect(() => {
    if (!open) return undefined;
    const onDown = e => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); };
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, [open]);

  return (
    <div ref={wrapRef} style={{ position: 'relative', flexShrink: 0 }}>
      <Btn variant="secondary" size="sm" onClick={() => setOpen(o => !o)}
        aria-haspopup="menu" aria-expanded={open} {...buttonProps}>
        {label} <span style={{ fontSize: 9, opacity: .6 }}>▼</span>
      </Btn>
      {open && (
        <div className="da-pop" role="menu" style={{
          position: 'absolute', top: 'calc(100% + 6px)', [align]: 0, zIndex: 200,
          background: T.surface, border: `1px solid ${T.border}`, borderRadius: T.rsm,
          boxShadow: T.shadowLg, padding: 5, minWidth: 224,
          maxHeight: '70vh', overflowY: 'auto',
        }}>
          {items.filter(Boolean).map((it, i) => {
            if (it.type === 'sep') return <div key={i} className="da-menu-sep" />;
            if (it.type === 'label') return <div key={i} className="da-menu-label">{it.label}</div>;
            return (
              <button key={i} role="menuitem" className="da-menu-item" disabled={it.disabled}
                onClick={() => { setOpen(false); it.onClick(); }}
                style={it.tone === 'danger' ? { color: T.red } : undefined}>
                <span>{it.label}</span>
                {it.hint && <span className="da-menu-hint">{it.hint}</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── TOASTS ──────────────────────────────────────────────────────────────────
// A tiny imperative store: `toast('Saved')` from anywhere, one <Toaster/> at
// the app root. Beats threading a message-and-timeout state pair through every
// component that can report an outcome.
const _toastStore = { items: [], listeners: new Set(), seq: 0 };

function _emitToasts() { _toastStore.listeners.forEach(fn => fn(_toastStore.items)); }

function toast(message, tone = 'info', ms = 3200) {
  const id = ++_toastStore.seq;
  _toastStore.items = [..._toastStore.items, { id, message, tone }];
  _emitToasts();
  if (ms > 0) setTimeout(() => dismissToast(id), ms);
  return id;
}

function dismissToast(id) {
  _toastStore.items = _toastStore.items.filter(t => t.id !== id);
  _emitToasts();
}

function Toaster() {
  const [items, setItems] = React.useState(_toastStore.items);
  React.useEffect(() => {
    _toastStore.listeners.add(setItems);
    return () => { _toastStore.listeners.delete(setItems); };
  }, []);
  if (items.length === 0) return null;
  return (
    <div className="da-toaster" role="status" aria-live="polite">
      {items.map(t => (
        <div key={t.id} className="da-toast" data-tone={t.tone}>
          <span style={{ flex: 1 }}>{t.message}</span>
          <button onClick={() => dismissToast(t.id)} aria-label="Dismiss" style={{
            background: 'none', border: 'none', cursor: 'pointer', color: T.mutedLight,
            fontSize: 15, lineHeight: 1, padding: '0 2px',
          }}>×</button>
        </div>
      ))}
    </div>
  );
}

// ─── CONFIRM ─────────────────────────────────────────────────────────────────
// Replaces window.confirm: same await-a-boolean shape, but styled, escapable,
// and it says what will actually happen instead of a bare browser prompt.
const _confirmStore = { current: null, listener: null };

function confirmDialog(opts) {
  return new Promise(resolve => {
    _confirmStore.current = { ...opts, resolve };
    if (_confirmStore.listener) _confirmStore.listener(_confirmStore.current);
  });
}

function ConfirmHost() {
  const [state, setState] = React.useState(null);
  React.useEffect(() => {
    _confirmStore.listener = setState;
    return () => { _confirmStore.listener = null; };
  }, []);
  if (!state) return null;
  const finish = ok => { setState(null); _confirmStore.current = null; state.resolve(ok); };
  return (
    <Modal title={state.title} onClose={() => finish(false)} width={440}
      footer={
        <>
          <Btn variant="secondary" onClick={() => finish(false)}>{state.cancelLabel || 'Cancel'}</Btn>
          <Btn variant={state.tone === 'danger' ? 'danger' : 'primary'} onClick={() => finish(true)}>
            {state.confirmLabel || 'Confirm'}
          </Btn>
        </>
      }>
      <div style={{ fontSize: 13.5, color: T.muted, lineHeight: 1.6 }}>{state.body}</div>
    </Modal>
  );
}

// ─── LAYOUT HELPERS ──────────────────────────────────────────────────────────
// The bar every full screen sits under: back affordance, title block, actions.
function AppBar({ onBack, backLabel, title, subtitle, badges, children, compact = false }) {
  return (
    <header style={{
      background: T.surface, borderBottom: `1px solid ${T.border}`, flexShrink: 0,
      padding: compact ? '0 12px' : '0 20px', minHeight: compact ? 52 : 60,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0, flex: '1 1 auto' }}>
        {onBack && (
          <button onClick={onBack} style={{
            background: 'none', border: 'none', cursor: 'pointer', color: T.muted,
            fontSize: 12.5, fontWeight: 600, display: 'flex', alignItems: 'center',
            gap: 4, flexShrink: 0, padding: '6px 2px',
          }}>←{backLabel ? ` ${backLabel}` : ''}</button>
        )}
        {onBack && <div style={{ width: 1, height: 20, background: T.border, flexShrink: 0 }} />}
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
            <span className="da-ellipsis" style={{ fontSize: compact ? 14 : 16, fontWeight: 700, color: T.text }}>
              {title}
            </span>
            {badges}
          </div>
          {subtitle && <div className="da-ellipsis" style={{ fontSize: 12, color: T.muted, marginTop: 1 }}>{subtitle}</div>}
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexShrink: 0, minWidth: 0 }}>{children}</div>
    </header>
  );
}

function EmptyState({ title, body, action, icon }) {
  return (
    <div style={{
      background: T.surface, border: `1.5px dashed ${T.border}`, borderRadius: T.r,
      padding: '48px 28px', textAlign: 'center',
    }}>
      {icon && <div style={{ marginBottom: 14, display: 'flex', justifyContent: 'center' }}>{icon}</div>}
      <div style={{ fontSize: 15.5, fontWeight: 700, color: T.text, marginBottom: 6 }}>{title}</div>
      {body && (
        <div style={{ fontSize: 13.5, color: T.muted, marginBottom: action ? 18 : 0, maxWidth: 420, margin: '0 auto', lineHeight: 1.55 }}>
          {body}
        </div>
      )}
      {action && <div style={{ marginTop: 18 }}>{action}</div>}
    </div>
  );
}

// Section heading used inside panels and modals.
function SectionLabel({ children, style = {} }) {
  return (
    <div style={{
      fontSize: 10.5, fontWeight: 800, color: T.muted, letterSpacing: .7,
      textTransform: 'uppercase', ...style,
    }}>{children}</div>
  );
}

// Callout for explanatory or warning copy.
function Note({ children, tone = 'neutral', style = {} }) {
  const tones = {
    neutral: { bg: T.surfaceAlt,  fg: T.muted, br: T.border },
    info:    { bg: T.primaryLight, fg: T.text, br: T.primary },
    warn:    { bg: T.amberLight,  fg: T.text,  br: T.amber },
    error:   { bg: T.redLight,    fg: T.red,   br: T.red },
    ok:      { bg: T.greenLight,  fg: T.green, br: T.green },
  };
  const c = tones[tone] || tones.neutral;
  return (
    <div style={{
      background: c.bg, color: c.fg, border: `1px solid ${c.br}33`,
      borderLeft: `3px solid ${c.br}`, borderRadius: T.rsm,
      padding: '9px 12px', fontSize: 12.5, lineHeight: 1.55, ...style,
    }}>{children}</div>
  );
}

Object.assign(window, {
  T, POSITIONS, POS_COLORS, PLATFORM_COLORS,
  useWindowWidth, useLayout, useEscape, useFocusTrap,
  Btn, Badge, PosBadge, AvailabilityChip, playerNewsSignals, Spinner,
  Field, Input, Textarea, Select, SegmentedControl, Checkbox,
  Modal, Drawer, Menu,
  toast, dismissToast, Toaster, confirmDialog, ConfirmHost,
  AppBar, EmptyState, SectionLabel, Note,
});
