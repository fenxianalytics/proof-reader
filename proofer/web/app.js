/* Fenxi Proofer - single-file UI. No build step. Renders either the live app or, when
   window.__PROOF__ is present, a read-only offline copy of one proof. */
'use strict';

const STANDALONE = !!window.__PROOF__;
const LOGO = '/static/logo.png';
const SHOW_DPI = 150;
const PX_PER_PT = SHOW_DPI / 72;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
};

const ICONS = {
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
  file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  xcircle: '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  right: '<path d="m9 18 6-6-6-6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
  columns: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M12 3v18"/>',
  zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
  swipe: '<path d="m18 8 4 4-4 4"/><path d="M2 12h20"/><path d="m6 8-4 4 4 4"/>',
  zin: '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/><line x1="11" x2="11" y1="8" y2="14"/><line x1="8" x2="14" y1="11" y2="11"/>',
  zout: '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/><line x1="8" x2="14" y1="11" y2="11"/>',
  fit: '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
  history: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
  flask: '<path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  eye: '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
  pen: '<path d="M12 20h9"/><path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z"/>',
  panel: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
  printer: '<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 9V3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v6"/><rect x="6" y="14" width="12" height="8" rx="1"/>',
  list: '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M8 6h13"/>',
};
const icon = (n, cls = '') => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ''}</svg>`;
const SEV = ['critical', 'major', 'minor', 'info'];
const SEV_LABEL = { critical: 'Critical', major: 'Major', minor: 'Minor', info: 'Note' };
const VERDICT_TEXT = { FAIL: ['Do not approve', 'Major or critical differences found'], REVIEW: ['Needs review', 'A person should look before this goes further'], PASS: ['No differences found', 'Within tolerance on every check that ran'] };
const VERDICT_ICON = { FAIL: 'xcircle', REVIEW: 'alert', PASS: 'shield' };

/* ── helpers ─────────────────────────────────────────────────────────── */
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch (e) { /* not json */ }
    throw new Error(msg);
  }
  return r.json();
}
const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
function toast(msg, err = false) {
  const t = document.createElement('div');
  t.className = 'toast' + (err ? ' err' : '');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), err ? 6000 : 3000);
}
function fmtDate(iso) { try { return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }); } catch (e) { return iso || ''; } }
function fmtSize(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; }
const pct = (x) => (100 * x).toFixed(x >= 0.9995 || x === 0 ? 0 : 1) + '%';

/* character-level diff, for showing exactly which digit or letter changed */
function diffHtml(a, b) {
  if (!a || !b || a.length > 220 || b.length > 220) return [esc(a), esc(b)];
  const n = a.length, m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  let i = 0, j = 0, ha = '', hb = '';
  const wrap = (tag, s) => (s ? `<${tag}>${esc(s)}</${tag}>` : '');
  let da = '', db = '';
  const flush = () => { ha += wrap('del', da); hb += wrap('ins', db); da = db = ''; };
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { flush(); ha += esc(a[i]); hb += esc(b[j]); i++; j++; }
    else if (j < m && (i >= n || dp[i][j + 1] >= dp[i + 1][j])) db += b[j++];
    else da += a[i++];
  }
  flush();
  return [ha, hb];
}

function modal(html, onMount) {
  const s = document.createElement('div');
  s.className = 'scrim';
  s.innerHTML = `<div class="modal card" role="dialog" aria-modal="true">${html}</div>`;
  s.addEventListener('mousedown', (e) => { if (e.target === s) s.remove(); });
  document.body.appendChild(s);
  onMount && onMount(s.firstElementChild, () => s.remove());
  return s;
}

/* ── app shell ───────────────────────────────────────────────────────── */
const root = $('#app');
const app = { health: null, samples: null, files: { ref: null, sample: null, deck: null }, poll: null, cleanup: null, collapsed: store.get('fx-collapsed', '0') === '1' };

function themeIcon() { return document.documentElement.classList.contains('dark') ? 'sun' : 'moon'; }
function shellHtml(active) {
  const nav = [['#/', 'plus', 'New proof', 'new'], ['#/batch', 'layers', 'Batch', 'batch'], ['#/history', 'history', 'History', 'history'], ['#/validation', 'flask', 'Validation', 'validation'], ['#/settings', 'shield', 'Settings', 'settings']];
  return `<div class="shell ${app.collapsed ? 'collapsed' : ''}">
    <aside class="sidebar">
      <div class="brand"><div class="mark"><img src="${LOGO}" alt=""></div><div><b>Proofer</b><small>by Fenxi Analytics</small></div></div>
      <nav class="nav"><div class="nav-label">PROOFING</div>
        ${nav.map(([h, i, l, k]) => `<a href="${h}" class="${active === k ? 'on' : ''}" title="${l}">${icon(i, 'lg')}<span>${l}</span></a>`).join('')}
      </nav>
      <div class="side-foot">
        <div class="engine-tag" title="${app.health && app.health.ocr ? 'OCR engine available' : 'OCR engine not installed: image-only pages are compared visually only'}"><i class="dot ${app.health && app.health.ocr ? '' : 'off'}"></i><span class="txt">Engine v${esc(app.health ? app.health.version : '')} · OCR ${app.health && app.health.ocr ? 'on' : 'off'}</span></div>
        <button data-act="theme" title="Toggle theme">${icon(themeIcon(), 'lg')}<span class="txt">Theme</span></button>
        <button data-act="collapse" title="Collapse sidebar">${icon('panel', 'lg')}<span class="txt">Collapse</span></button>
      </div>
    </aside>
    <main class="main" id="view"></main></div>`;
}
function mountShell(active, collapse) {
  if (collapse !== undefined && !store.get('fx-collapsed-user', '')) app.collapsed = collapse;
  root.innerHTML = shellHtml(active);
  return $('#view');
}
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-act]');
  if (!b) return;
  if (b.dataset.act === 'theme') {
    const dark = document.documentElement.classList.toggle('dark');
    store.set('fx-theme', dark ? 'dark' : 'light');
    const bt = b.querySelector('svg'); if (bt) bt.outerHTML = icon(themeIcon(), 'lg');
  } else if (b.dataset.act === 'collapse') {
    app.collapsed = !app.collapsed; store.set('fx-collapsed', app.collapsed ? '1' : '0'); store.set('fx-collapsed-user', '1');
    $('.shell').classList.toggle('collapsed', app.collapsed);
  }
});

/* ── router ──────────────────────────────────────────────────────────── */
function teardown() {
  if (app.poll) { clearTimeout(app.poll); app.poll = null; }
  if (app.cleanup) { app.cleanup(); app.cleanup = null; }
}
async function route() {
  teardown();
  const [, name, arg] = (location.hash || '#/').split('/');
  try {
    if (name === 'run' && arg) return await viewRun(arg);
    if (name === 'report' && arg) return await viewReport(arg);
    if (name === 'batch') return arg ? await viewBatch(arg) : await viewBatchNew();
    if (name === 'history') return await viewHistory();
    if (name === 'validation') return await viewValidation();
    if (name === 'settings') return await viewSettings();
    return await viewNew();
  } catch (err) {
    mountShell('new').innerHTML = `<div class="page"><div class="card" style="padding:28px"><h2>Something went wrong</h2><p class="muted">${esc(err.message)}</p><a class="btn" href="#/">Back to start</a></div></div>`;
  }
}

/* ── view: new proof ─────────────────────────────────────────────────── */
async function viewNew() {
  const view = mountShell('new', false);
  app.files = { ref: null, sample: null, deck: null };
  view.innerHTML = `<div class="hero-glow"></div><div class="page">
    <div class="hero"><span class="eyebrow">${icon('shield')} Artwork proofing</span>
      <h1>Catch every difference <em>before it prints</em></h1>
      <p>Compare a received packaging PDF against the approved artwork and the approved text. Text, barcodes, braille, colour, layers, layout, spelling and page structure are each checked on their own, and every finding is explained.</p></div>
    <div class="drops">
      ${dropHtml('ref', 'Reference', 'The approved artwork')}
      ${dropHtml('sample', 'Sample', 'The file to check against it')}
    </div>
    <label class="drop slim" data-role="deck"><input type="file" accept=".docx,.txt,.pdf"><div class="ico">${icon('file', 'lg')}</div>
      <div class="grow" style="text-align:left"><div class="role">Approved text <span class="muted" style="letter-spacing:0;text-transform:none;font-weight:500">(optional)</span></div>
      <div class="fname">Drop the approved copy document (.docx, .txt or .pdf)</div><div class="fsub sub">Every approved paragraph is located on the sample and checked word for word, in any order.</div></div></label>
    <div class="glass opts">
      <label class="f">Render resolution <select id="dpi"><option value="300" selected>300 dpi (recommended)</option><option value="400">400 dpi</option><option value="600">600 dpi (slow)</option><option value="200">200 dpi (fast draft)</option></select></label>
      <label class="toggle"><input type="checkbox" id="ocr" checked><span>Read changed regions with OCR</span></label>
      <a class="chip btnlike" href="#/settings" id="profchip" title="Change in Settings">${icon('shield')} Profile: …</a>
      <span class="sub" style="margin-left:auto">${icon('lock')} Files stay on this machine.</span>
    </div>
    <div class="cta"><button class="btn primary" id="go" disabled>${icon('zap')} Run proof</button></div>
    <div class="examples card" style="padding:20px"><h3>No files handy? Try a built-in example</h3>
      <div class="sub">Synthetic pack designs with known, injected defects (and control pairs that must come back clean).</div>
      <div class="ex-grid"><select id="ex"><option>Loading examples…</option></select><button class="btn" id="exgo" disabled>Run example</button></div>
      <label class="toggle" style="margin-top:12px"><input type="checkbox" id="exdeck" checked><span class="sub">Also check against the design's approved text document</span></label></div>
    <div class="caps">${['Text', 'Approved text', 'Spelling', 'Barcodes', 'Braille', 'Vector colour', 'Layers', 'Layout', 'Page structure', 'Image-only artwork (OCR)'].map((c) => `<span class="chip">${icon('check')} ${c}</span>`).join('')}</div>
    <div class="trust">
      <div class="glass"><b>${icon('eye')} Nothing is hidden</b><p>Every proof lists which checks ran and which could not, per page. A clean result on limited coverage is labelled as such.</p></div>
      <div class="glass"><b>${icon('shield')} Text is read, not guessed</b><p>Words come straight from the PDF. OCR only describes regions the pixel check already flagged, and never overrules it.</p></div>
      <div class="glass"><b>${icon('pen')} Sign-off with an audit trail</b><p>Accept or reject each finding, then sign off. Decisions are logged in a tamper-evident chain with file hashes.</p></div>
    </div></div>`;
  const go = $('#go', view);
  const refresh = () => { go.disabled = !(app.files.ref && app.files.sample); };
  $$('.drop', view).forEach((d) => {
    const role = d.dataset.role, input = $('input', d);
    const set = (f) => {
      if (!f) return;
      if (role === 'deck' ? !/\.(docx|txt|pdf)$/i.test(f.name) : !/\.(pdf|jpe?g|png)$/i.test(f.name)) return toast(role === 'deck' ? 'Approved text must be .docx, .txt or .pdf' : 'Please choose a PDF, JPG or PNG file', true);
      app.files[role] = f;
      d.classList.add('has');
      $('.fname', d).textContent = f.name;
      $('.fsub', d).textContent = fmtSize(f.size) + ' · click to replace';
      $('.ico', d).innerHTML = icon('check', 'lg');
      refresh();
    };
    input.addEventListener('change', () => set(input.files[0]));
    ['dragenter', 'dragover'].forEach((ev) => d.addEventListener(ev, (e) => { e.preventDefault(); d.classList.add('over'); }));
    ['dragleave', 'drop'].forEach((ev) => d.addEventListener(ev, (e) => { e.preventDefault(); d.classList.remove('over'); }));
    d.addEventListener('drop', (e) => set(e.dataTransfer.files[0]));
  });
  go.addEventListener('click', async () => {
    go.disabled = true; go.textContent = 'Uploading…';
    const fd = new FormData();
    fd.append('reference', app.files.ref); fd.append('sample', app.files.sample);
    if (app.files.deck) fd.append('deck', app.files.deck);
    fd.append('dpi', $('#dpi', view).value); fd.append('ocr_on', $('#ocr', view).checked ? 'true' : 'false');
    try { const { id } = await api('/api/jobs', { method: 'POST', body: fd }); location.hash = '#/run/' + id; }
    catch (err) { toast(err.message, true); go.disabled = false; go.innerHTML = `${icon('zap')} Run proof`; }
  });
  loadExamples(view);
  api('/api/settings').then(({ settings, presets }) => { const c = $('#profchip', view); if (c) c.innerHTML = `${icon('shield')} Profile: ${esc((presets.find((p) => p.id === settings.profile) || {}).label || 'Standard')}`; }).catch(() => {});
}
function dropHtml(role, label, hint) {
  return `<label class="drop" data-role="${role}"><input type="file" accept="application/pdf,.pdf,.jpg,.jpeg,.png,image/jpeg,image/png"><div class="ico">${icon('upload', 'lg')}</div>
    <div class="role">${label}</div><div class="fname">Drop a PDF, JPG or PNG here</div><div class="fsub sub">${hint} · or click to browse</div></label>`;
}
async function loadExamples(view) {
  try {
    app.samples = app.samples || await api('/api/samples');
    const sel = $('#ex', view), btn = $('#exgo', view);
    if (!app.samples.length) { sel.innerHTML = '<option>No examples found - run make_samples.py</option>'; return; }
    const by = {};
    app.samples.forEach((s) => (by[s.design] = by[s.design] || []).push(s));
    sel.innerHTML = Object.keys(by).sort().map((d) => `<optgroup label="${esc(d)}">${by[d].map((s) => `<option value="${esc(s.name)}">${esc(s.kind === 'control' ? s.name + ' (control: should be clean)' : s.name + ': ' + s.description)}</option>`).join('')}</optgroup>`).join('');
    btn.disabled = false;
    btn.onclick = async () => {
      btn.disabled = true;
      try { const { id } = await post('/api/jobs/sample', { pair: sel.value, with_deck: $('#exdeck', view).checked }); location.hash = '#/run/' + id; }
      catch (err) { toast(err.message, true); btn.disabled = false; }
    };
  } catch (err) { /* examples are optional */ }
}

/* ── view: running ───────────────────────────────────────────────────── */
async function viewRun(id) {
  const view = mountShell('new', false);
  const C = 2 * Math.PI * 42;
  view.innerHTML = `<div class="hero-glow"></div><div class="page"><div class="run card">
    <div class="ring"><svg viewBox="0 0 100 100" width="96" height="96"><circle class="bg" cx="50" cy="50" r="42"/><circle class="fg" cx="50" cy="50" r="42" stroke-dasharray="${C}" stroke-dashoffset="${C}"/></svg><span id="rp">0%</span></div>
    <h2 id="rt">Starting…</h2><p class="sub" id="rs">Reading both PDFs</p>
    <div class="steps">${['Text', 'Barcodes', 'Colour', 'Braille', 'Layers', 'Structure', 'Visual', 'OCR', 'Approved text', 'Spelling'].map((c) => `<span class="chip">${c}</span>`).join('')}</div></div></div>`;
  const tick = async () => {
    let st;
    try { st = await api('/api/jobs/' + id); } catch (err) { return toast(err.message, true); }
    const p = Math.max(0, Math.min(1, st.progress || 0));
    $('.ring .fg').style.strokeDashoffset = C * (1 - p);
    $('#rp').textContent = Math.round(p * 100) + '%';
    $('#rt').textContent = st.state === 'error' ? 'Could not compare these files' : 'Running proof';
    $('#rs').textContent = st.state === 'error' ? st.error : st.stage;
    if (st.state === 'done') { location.replace('#/report/' + id); return; }
    if (st.state === 'error') { $('.run').insertAdjacentHTML('beforeend', '<div style="margin-top:18px"><a class="btn primary" href="#/">Start over</a></div>'); return; }
    app.poll = setTimeout(tick, 500);
  };
  tick();
}

/* ── view: new batch ─────────────────────────────────────────────────── */
async function viewBatchNew() {
  const view = mountShell('batch', false);
  const B = { files: new Map(), plan: null };
  view.innerHTML = `<div class="hero-glow"></div><div class="page">
    <div class="ph"><div><h1>Batch proofing</h1><div class="sub">Drop a whole folder. Files are paired automatically by name, run one after another, and tracked on one dashboard.</div></div></div>
    <label class="drop" id="bdrop" style="min-height:170px"><input type="file" id="bfiles" multiple accept=".pdf,.jpg,.jpeg,.png,.docx,.txt">
      <div class="ico">${icon('layers', 'lg')}</div><div class="role">Files or folders</div>
      <div class="fname">Drop PDFs, JPGs or PNGs (and approved-text documents) here</div>
      <div class="fsub sub">or click to choose files · <a href="#" id="bfolder">choose a folder</a></div></label>
    <input type="file" id="bdir" webkitdirectory multiple hidden>
    <div class="glass opts" style="margin-top:14px">
      <span class="sub"><b>Naming that pairs automatically:</b> <code>name_reference.pdf</code> + <code>name_sample.pdf</code> (+ <code>name_approved_text.docx</code>),
      or folders <code>reference/</code> and <code>sample/</code> with matching file names, or versions <code>name_v3.pdf</code> → <code>name_v4.pdf</code>.</span></div>
    <div id="bplan"></div></div>`;
  const add = (list) => {
    for (const f of list) {
      if (!/\.(pdf|jpe?g|png|docx|txt)$/i.test(f.name)) continue;
      B.files.set(f.webkitRelativePath || f.name, f);
    }
    plan();
  };
  $('#bfiles', view).addEventListener('change', (e) => add(e.target.files));
  $('#bdir', view).addEventListener('change', (e) => add(e.target.files));
  $('#bfolder', view).addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); $('#bdir', view).click(); });
  const dz = $('#bdrop', view);
  ['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('over'); }));
  dz.addEventListener('drop', async (e) => {
    const items = [...(e.dataTransfer.items || [])].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
    if (!items.length) return add(e.dataTransfer.files);
    const out = [];
    const walk = (entry, prefix) => new Promise((res) => {
      if (entry.isFile) entry.file((f) => { Object.defineProperty(f, 'webkitRelativePath', { value: prefix + f.name }); out.push(f); res(); });
      else {
        const r = entry.createReader(), all = [];
        const more = () => r.readEntries(async (ents) => {
          if (!ents.length) { for (const en of all) await walk(en, prefix + entry.name + '/'); res(); }
          else { all.push(...ents); more(); }
        });
        more();
      }
    });
    for (const it of items) await walk(it, '');
    add(out);
  });

  async function plan() {
    const paths = [...B.files.keys()];
    if (!paths.length) return;
    B.plan = await post('/api/pairing', { paths });
    render();
  }
  function opt(sel, want) {
    return `<option value="">-</option>` + [...B.files.keys()].sort().map((p) => `<option ${p === sel ? 'selected' : ''} value="${esc(p)}">${esc(p)}</option>`).join('');
  }
  function render() {
    const P = B.plan;
    const ready = P.pairs.filter((g) => g.ref && g.sample).length;
    $('#bplan', view).innerHTML = `<div class="card" style="margin-top:16px;overflow-x:auto"><div class="row" style="padding:14px 16px;flex-wrap:wrap">
        <b>${ready} pair${ready === 1 ? '' : 's'} ready</b><span class="sub">${B.files.size} files${P.unpaired.length ? ` · ${P.unpaired.length} not paired` : ''}</span><span class="spacer"></span>
        <input type="text" id="bname" placeholder="Batch name" style="width:200px" value="Batch ${new Date().toLocaleDateString()}">
        <label class="toggle"><input type="checkbox" id="bocr" checked><span class="sub">OCR</span></label>
        <button class="btn primary" id="brun" ${ready ? '' : 'disabled'}>${icon('zap')} Run ${ready} proof${ready === 1 ? '' : 's'}</button></div>
      <table class="t"><thead><tr><th>Pair</th><th>Reference</th><th>Sample</th><th>Approved text</th><th></th></tr></thead><tbody>
      ${P.pairs.map((g, i) => `<tr data-i="${i}"><td><b>${esc(g.key)}</b></td>
        <td><select data-role="ref">${opt(g.ref)}</select></td><td><select data-role="sample">${opt(g.sample)}</select></td>
        <td><select data-role="deck">${opt(g.deck)}</select></td><td><button class="btn ghost icon" data-drop="${i}" title="Leave this pair out">${icon('x')}</button></td></tr>`).join('')}
      </tbody></table>
      ${P.unpaired.length ? `<div class="attn" style="margin:12px"><b>${icon('info')} Couldn't pair these automatically</b>${P.unpaired.map((u) => `<div class="it" style="cursor:default">${esc(u)}</div>`).join('')}
        <div style="margin-top:8px"><button class="btn sm" id="baddpair">${icon('plus')} Add a pair by hand</button></div></div>` : ''}</div>`;
    $$('select[data-role]', view).forEach((s) => s.addEventListener('change', () => {
      const g = P.pairs[Number(s.closest('tr').dataset.i)];
      g[s.dataset.role] = s.value || null;
      render();
    }));
    $$('[data-drop]', view).forEach((b) => b.addEventListener('click', () => { P.pairs.splice(Number(b.dataset.drop), 1); render(); }));
    const ap = $('#baddpair', view);
    if (ap) ap.addEventListener('click', () => { P.pairs.push({ key: 'pair ' + (P.pairs.length + 1), ref: null, sample: null, deck: null }); render(); });
    $('#brun', view).addEventListener('click', run);
  }
  async function run() {
    const btn = $('#brun', view);
    btn.disabled = true;
    const todo = B.plan.pairs.filter((g) => g.ref && g.sample);
    try {
      const { id } = await post('/api/batches', { name: $('#bname', view).value, unpaired: B.plan.unpaired });
      for (let i = 0; i < todo.length; i++) {
        btn.textContent = `Uploading ${i + 1} of ${todo.length}…`;
        const g = todo[i], fd = new FormData();
        fd.append('reference', B.files.get(g.ref)); fd.append('sample', B.files.get(g.sample));
        if (g.deck) fd.append('deck', B.files.get(g.deck));
        fd.append('ocr_on', $('#bocr', view).checked ? 'true' : 'false');
        fd.append('batch', id); fd.append('key', g.key);
        await api('/api/jobs', { method: 'POST', body: fd });
      }
      location.hash = '#/batch/' + id;
    } catch (err) { toast(err.message, true); btn.disabled = false; btn.innerHTML = `${icon('zap')} Retry`; }
  }
}

/* ── view: batch dashboard ───────────────────────────────────────────── */
async function viewBatch(id) {
  const view = mountShell('batch', false);
  let sortKey = 'sev';
  const tick = async () => {
    let b;
    try { b = await api('/api/batches/' + id); } catch (err) { view.innerHTML = `<div class="page"><div class="card" style="padding:24px">${esc(err.message)}</div></div>`; return; }
    const pct = b.total ? Math.round(100 * (b.done + b.failed) / b.total) : 100;
    const rank = (r) => r.state !== 'done' ? 9 : ({ FAIL: 0, REVIEW: 1, PASS: 2 }[r.verdict] ?? 3) * 1000 - ((r.counts || {}).critical || 0);
    const rows = [...b.rows].sort((x, y) => sortKey === 'sev' ? rank(x) - rank(y) : x.key.localeCompare(y.key));
    const vb = (r) => r.state === 'done' ? `<span class="badge ${r.verdict === 'PASS' ? 'good' : r.verdict === 'FAIL' ? 'critical' : 'major'}">${r.verdict}</span>${r.coverage_limited ? ' <span class="badge muted">limited</span>' : ''}`
      : r.state === 'error' ? `<span class="badge critical">error</span>` : `<span class="badge muted">${r.state === 'queued' ? 'queued' : Math.round((r.progress || 0) * 100) + '%'}</span>`;
    view.innerHTML = `<div class="page">
      <div class="ph"><div><div class="row"><a class="btn ghost icon" href="#/history">${icon('right').replace('<svg', '<svg style="transform:rotate(180deg)"')}</a><h1>${esc(b.name)}</h1></div>
        <div class="sub">${fmtDate(b.created)} · ${b.total} proofs${b.unpaired.length ? ` · ${b.unpaired.length} files not paired` : ''}</div></div><span class="spacer"></span>
        <a class="btn" href="/api/batches/${id}/export.csv">${icon('list')} All findings (.csv)</a>
        <a class="btn" href="/api/batches/${id}/export.zip">${icon('download')} Reports (.zip)</a></div>
      <div class="kpis" style="padding:0;grid-template-columns:repeat(5,1fr)">
        <div class="card kpi"><div class="n">${b.done + b.failed}<span class="muted" style="font-size:15px"> / ${b.total}</span></div><div class="l">Finished</div><div class="bar"><i style="width:${pct}%"></i></div></div>
        <div class="card kpi critical"><div class="n">${b.verdicts.FAIL}</div><div class="l">Do not approve</div></div>
        <div class="card kpi major"><div class="n">${b.verdicts.REVIEW}</div><div class="l">Need review</div></div>
        <div class="card kpi"><div class="n" style="color:var(--good)">${b.verdicts.PASS}</div><div class="l">No differences</div></div>
        <div class="card kpi critical"><div class="n">${b.critical}</div><div class="l">Critical findings in total</div></div></div>
      <div class="card" style="margin-top:16px;overflow-x:auto"><div class="row" style="padding:12px 16px"><b>Proofs</b><span class="spacer"></span>
        <div class="seg"><button data-sort="sev" class="${sortKey === 'sev' ? 'on' : ''}">Worst first</button><button data-sort="name" class="${sortKey === 'name' ? 'on' : ''}">By name</button></div></div>
        <table class="t"><thead><tr><th>Pair</th><th>Files</th><th>Result</th><th title="critical · major · minor">Findings</th><th>Reviewed</th><th>Sign-off</th></tr></thead><tbody>
        ${rows.map((r) => { const c = r.counts || {};
          return `<tr data-id="${r.id}" data-state="${r.state}"><td><b>${esc(r.key)}</b></td><td><div>${esc(r.names.sample)}</div><div class="sub">vs ${esc(r.names.ref)}${r.names.deck ? ' + ' + esc(r.names.deck) : ''}</div></td>
          <td>${vb(r)}${r.state === 'error' ? `<div class="sub">${esc(r.error || '')}</div>` : ''}</td>
          <td class="nowrap">${r.state === 'done' ? `<span style="color:var(--critical);font-weight:700">${c.critical || 0}</span> · <span style="color:var(--major);font-weight:700">${c.major || 0}</span> · <span style="color:var(--minor);font-weight:700">${c.minor || 0}</span>` : ''}</td>
          <td>${r.state === 'done' ? r.reviewed : ''}</td><td>${r.signoff ? `<span class="badge ${r.signoff === 'approved' ? 'good' : 'critical'}">${r.signoff}</span>` : '<span class="muted">-</span>'}</td></tr>`; }).join('')}
        </tbody></table></div>
      ${b.unpaired.length ? `<div class="attn" style="margin:16px 0 0"><b>${icon('info')} Not paired, not proofed</b>${b.unpaired.map((u) => `<div class="it" style="cursor:default">${esc(u)}</div>`).join('')}</div>` : ''}
      <div class="row" style="margin-top:16px"><span class="spacer"></span><button class="btn bad sm" id="bdel">${icon('trash')} Delete batch</button></div></div>`;
    $$('[data-sort]', view).forEach((x) => x.onclick = () => { sortKey = x.dataset.sort; tick(); });
    $$('tr[data-id]', view).forEach((tr) => tr.onclick = () => { if (tr.dataset.state === 'done') location.hash = '#/report/' + tr.dataset.id; });
    $('#bdel', view).onclick = async () => { if (!confirm('Delete this batch and all its proofs?')) return; await api('/api/batches/' + id, { method: 'DELETE' }); location.hash = '#/history'; };
    if (b.running > 0) app.poll = setTimeout(tick, 1500);
  };
  tick();
}

/* ── view: settings ──────────────────────────────────────────────────── */
async function viewSettings() {
  const view = mountShell('settings', false);
  const { settings, presets, defaults } = await api('/api/settings');
  const S = JSON.parse(JSON.stringify(settings));
  const FIELDS = [
    ['delta_e', 'Colour change threshold', 'ΔE (CIE76) a pixel must change by to count', 0.5, 20, 0.5],
    ['move_tol_mm', 'Position tolerance', 'mm an element may shift before it is reported as moved', 0.05, 5, 0.05],
    ['min_area_px', 'Smallest mark', 'pixels at render resolution; smaller specks are ignored', 1, 200, 1],
    ['separation_tol', 'Ink plate tolerance', '% difference on one CMYK plate that counts as an ink change', 2, 50, 1],
    ['barcode_shift_mm', 'Barcode position tolerance', 'mm a barcode may move before it is reported', 0.1, 5, 0.1],
    ['dpi', 'Render resolution', 'dpi used for visual and barcode checks', 150, 600, 50],
  ];
  const eff = (k) => { const p = presets.find((x) => x.id === S.profile); return S.overrides[k] ?? p.overrides[k] ?? defaults[k]; };
  function render() {
    const cur = presets.find((x) => x.id === S.profile);
    view.innerHTML = `<div class="page"><div class="ph"><div><h1>Settings</h1><div class="sub">How strict every new proof is. Each proof records the settings it ran with.</div></div>
      <span class="spacer"></span><button class="btn primary" id="ssave">${icon('check')} Save</button></div>
      <h3 style="margin:0 0 10px">Profile</h3>
      <div class="vgrid">${presets.map((p) => `<button class="card stat prof ${S.profile === p.id ? 'on' : ''}" data-prof="${p.id}" style="text-align:left;cursor:pointer;border-width:${S.profile === p.id ? 2 : 1}px;border-color:${S.profile === p.id ? 'var(--accent)' : 'var(--border)'}">
        <div class="row"><b style="font:700 16px var(--font-head)">${esc(p.label)}</b>${S.profile === p.id ? `<span class="badge good" style="margin-left:auto">active</span>` : ''}</div>
        <div class="l" style="margin-top:6px">${esc(p.description)}</div></button>`).join('')}</div>
      <div class="card" style="padding:18px 22px;margin-top:16px"><h3 style="margin-bottom:4px">Tolerances</h3>
        <div class="sub" style="margin-bottom:12px">Leave a field empty to use the ${esc(cur.label)} profile's value (shown greyed).</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px 22px">
        ${FIELDS.map(([k, l, d, mn, mx, st]) => `<label style="display:block"><b style="font-size:13px">${l}</b><div class="sub" style="font-size:12px;margin:2px 0 6px">${d}</div>
          <input type="number" data-k="${k}" min="${mn}" max="${mx}" step="${st}" value="${S.overrides[k] ?? ''}" placeholder="${eff(k)}"></label>`).join('')}</div></div>
      <div class="card" style="padding:18px 22px;margin-top:16px;${cur.variable ? '' : 'opacity:.55'}"><h3 style="margin-bottom:4px">Variable data labels</h3>
        <div class="sub" style="margin-bottom:10px">${cur.variable ? 'Active: a change right after one of these labels is reported as expected variable data, not a defect.'
          : 'Only used by the <b>Print run check</b> profile. In other profiles a changed lot or expiry is a real defect.'} One label per line.</div>
        <textarea id="svar" rows="6" style="font-family:var(--font-mono);font-size:12.5px">${esc((S.variable_labels || []).join('\n'))}</textarea></div>
      <div class="card" style="padding:18px 22px;margin-top:16px"><h3 style="margin-bottom:4px">Product dictionary</h3>
        <div class="sub">Brand names, INNs and company names the spell check should accept live in <code>dictionary.txt</code> in the project folder, one word per line.</div></div></div>`;
    $$('[data-prof]', view).forEach((b) => b.onclick = () => { S.profile = b.dataset.prof; render(); });
    $$('input[data-k]', view).forEach((i) => i.oninput = () => { if (i.value === '') delete S.overrides[i.dataset.k]; else S.overrides[i.dataset.k] = Number(i.value); });
    $('#svar', view).oninput = (e) => { S.variable_labels = e.target.value.split('\n').map((x) => x.trim()).filter(Boolean); };
    $('#ssave', view).onclick = async () => {
      try { await api('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(S) }); toast('Saved. New proofs use these settings.'); }
      catch (err) { toast(err.message, true); }
    };
  }
  render();
}

function keyHelp() {
  modal(`<h2>Keyboard shortcuts</h2><div class="sub">In a proof report</div>
    <dl class="kv" style="grid-template-columns:120px 1fr;margin-top:14px;font-size:13.5px">
      <dt><kbd>j</kbd> / <kbd>↓</kbd></dt><dd style="font-family:inherit">Next finding</dd>
      <dt><kbd>k</kbd> / <kbd>↑</kbd></dt><dd style="font-family:inherit">Previous finding</dd>
      <dt><kbd>a</kbd></dt><dd style="font-family:inherit">Accept the selected finding</dd>
      <dt><kbd>r</kbd></dt><dd style="font-family:inherit">Reject the selected finding</dd>
      <dt><kbd>f</kbd></dt><dd style="font-family:inherit">Fit the page</dd>
      <dt><kbd>m</kbd></dt><dd style="font-family:inherit">Show / hide markers</dd>
      <dt><kbd>1</kbd>–<kbd>4</kbd></dt><dd style="font-family:inherit">Side by side · Overlay · Swipe · Flicker</dd>
      <dt><kbd>[</kbd> / <kbd>]</kbd></dt><dd style="font-family:inherit">Previous / next proof in the batch</dd>
      <dt><kbd>Esc</kbd></dt><dd style="font-family:inherit">Clear selection</dd>
      <dt><kbd>?</kbd></dt><dd style="font-family:inherit">This help</dd></dl>
    <div class="foot"><button class="btn" data-close>Close</button></div>`, (box, close) => { $('[data-close]', box).onclick = close; });
}

/* ── view: history ───────────────────────────────────────────────────── */
async function viewHistory() {
  const view = mountShell('history', false);
  const [list, bl] = await Promise.all([api('/api/jobs'), api('/api/batches')]);
  view.innerHTML = `<div class="page"><div class="ph"><div><h1>History</h1><div class="sub">Every proof run on this machine. Stored under <code>results/jobs/</code>.</div></div><span class="spacer"></span><a class="btn primary" href="#/">${icon('plus')} New proof</a></div>
    ${bl.length ? `<h3 style="margin:4px 0 10px">Batches</h3><div class="card" style="overflow-x:auto;margin-bottom:22px"><table class="t"><thead><tr><th>When</th><th>Batch</th><th>Progress</th><th>Results</th></tr></thead><tbody>
      ${bl.map((b) => `<tr data-batch="${b.id}"><td class="nowrap">${fmtDate(b.created)}</td><td><b>${esc(b.name)}</b></td><td>${b.done + b.failed} / ${b.total}${b.running ? ' <span class="badge muted">running</span>' : ''}</td>
        <td class="nowrap"><span class="badge critical">${b.verdicts.FAIL} fail</span> <span class="badge major">${b.verdicts.REVIEW} review</span> <span class="badge good">${b.verdicts.PASS} pass</span></td></tr>`).join('')}
      </tbody></table></div><h3 style="margin:4px 0 10px">Individual proofs</h3>` : ''}
    <div class="card" style="overflow-x:auto">${list.length ? `<table class="t"><thead><tr><th>When</th><th>Sample vs reference</th><th>Result</th><th title="critical · major · minor">Findings</th><th>Reviewed</th><th>Sign-off</th><th></th></tr></thead><tbody>
    ${list.map((j) => {
      const c = j.counts || {}, n = (c.critical || 0) + (c.major || 0) + (c.minor || 0);
      return `<tr data-id="${j.id}" data-state="${j.state}"><td class="nowrap">${fmtDate(j.created)}</td>
        <td><b>${esc(j.names.sample)}</b><div class="sub">vs ${esc(j.names.ref)}</div></td>
        <td>${j.state === 'done' ? `<span class="badge ${j.verdict === 'PASS' ? 'good' : j.verdict === 'FAIL' ? 'critical' : 'major'}">${j.verdict}</span>${j.coverage_limited ? ' <span class="badge muted">limited</span>' : ''}` : `<span class="badge muted">${j.state}</span>`}</td>
        <td class="nowrap">${j.state === 'done' ? `<span style="color:var(--critical);font-weight:700">${c.critical || 0}</span> · <span style="color:var(--major);font-weight:700">${c.major || 0}</span> · <span style="color:var(--minor);font-weight:700">${c.minor || 0}</span>` : ''}</td>
        <td>${j.state === 'done' ? `${j.reviewed} of ${n}` : ''}</td>
        <td>${j.signoff ? `<span class="badge ${j.signoff === 'approved' ? 'good' : 'critical'}">${j.signoff}</span>` : '<span class="muted">-</span>'}</td>
        <td style="text-align:right"><button class="btn ghost icon" data-del="${j.id}" title="Delete this proof and its files">${icon('trash')}</button></td></tr>`;
    }).join('')}</tbody></table>` : `<div class="empty">${icon('history')}<div>No proofs yet.</div></div>`}</div></div>`;
  view.addEventListener('click', async (e) => {
    const del = e.target.closest('[data-del]');
    if (del) {
      e.stopPropagation();
      if (!confirm('Delete this proof, its input PDFs and its audit log?')) return;
      await api('/api/jobs/' + del.dataset.del, { method: 'DELETE' }); return viewHistory();
    }
    const bt = e.target.closest('tr[data-batch]');
    if (bt) { location.hash = '#/batch/' + bt.dataset.batch; return; }
    const tr = e.target.closest('tr[data-id]');
    if (tr) location.hash = (tr.dataset.state === 'done' ? '#/report/' : '#/run/') + tr.dataset.id;
  });
}

/* ── view: validation ────────────────────────────────────────────────── */
async function viewValidation() {
  const view = mountShell('validation', false);
  const v = await api('/api/validation');
  const m = v.mutation, ak = v.answer_key;
  const meter = (ok, n) => { const r = n ? ok / n : 1; return `<div class="meter"><i class="${r >= 0.995 ? '' : r >= 0.9 ? 'mid' : 'low'}" style="width:${(r * 100).toFixed(1)}%"></i></div>`; };
  const real = m && m.pdfs.some((p) => !/^master/.test(p));
  const row = (r) => `<div class="r"><div style="text-transform:capitalize">${esc(r.name.replace(/_/g, ' '))}</div><div class="muted">${r.mode}</div>${meter(r.ok, r.n)}<div>${r.ok} / ${r.n}</div><div class="muted">&le; ${pct(r.miss_upper95)}</div></div>`;
  let body = '';
  if (m) {
    const t = m.total;
    body += `<div class="vgrid">
      <div class="card stat"><div class="n" style="color:var(--good)">${pct(t.recall)}</div><div class="l">of ${t.n} automatically injected defects caught, correctly classified and rated serious enough</div><div class="s">Mutation testing · ${m.pdfs.length} PDFs · seed ${m.seed}</div></div>
      <div class="card stat"><div class="n">&le; ${pct(t.miss_upper95)}</div><div class="l">95% upper bound on the true miss rate</div><div class="s">More trials tighten this. With zero misses in n trials it is 1 &minus; 0.05<sup>1/n</sup>.</div></div>
      <div class="card stat"><div class="n" style="color:${m.controls.false_alarms ? 'var(--critical)' : 'var(--good)'}">${m.controls.false_alarms} / ${m.controls.n}</div><div class="l">clean controls falsely flagged</div><div class="s">Identical and flattened copies of the same file</div></div>
      <div class="card stat"><div class="n">${ak ? `${ak.summary.classified} / ${ak.summary.defects}` : '-'}</div><div class="l">hand-built answer-key defects caught and correctly classified</div><div class="s">${ak ? `${ak.summary.false_alarm_controls} / ${ak.summary.controls} clean controls falsely flagged` : 'not measured'}</div></div></div>`;
    body += `<div class="card" style="padding:18px 22px;margin-top:16px"><h3 style="margin-bottom:8px">Recall by defect type</h3><div class="bars">
      <div class="r h"><div>Defect</div><div>Mode</div><div></div><div>Caught</div><div>Miss rate (95% upper)</div></div>
      ${m.table.filter((r) => r.name !== 'copy deck').map(row).join('')}</div></div>`;
    const deckRows = m.table.filter((r) => r.name === 'copy deck');
    if (deckRows.length) body += `<div class="card" style="padding:18px 22px;margin-top:16px"><h3 style="margin-bottom:4px">Approved-text check on its own</h3>
      <div class="sub" style="margin-bottom:8px">The same text defects, caught by comparing the sample with the approved text document alone, with no reference PDF. A second, independent line of defence.</div><div class="bars">
      <div class="r h"><div>Check</div><div>Mode</div><div></div><div>Caught</div><div>Miss rate (95% upper)</div></div>${deckRows.map(row).join('')}</div></div>`;
  } else {
    body += `<div class="card" style="padding:26px"><h3>No mutation-testing results yet</h3><p class="muted">Run it to measure recall on any PDF:</p><pre class="cmd">python mutate.py</pre></div>`;
  }
  body += `<div class="card honest" style="margin-top:16px"><b>${real ? 'Measured on your artwork as well' : 'What these numbers do and do not show'}</b><ul>
    ${real ? '' : '<li><b>These are synthetic pack designs.</b> They show the engine works; they do not show it will score this on your real artwork. Different exporters, outlined fonts, spot colours and overprint will surface things this set cannot.</li>'}
    <li>Mutation testing derives defects programmatically from any PDF, so it can run on real client artwork the tool was never tuned on. Put approved PDFs in <code>real/</code> and run <code>python mutate.py</code>.</li>
    <li>Colour is compared as vector colorant values and rendered RGB, not true CMYK / spot separations. Barcode grading is a print-quality proxy, not a full ISO/IEC 15416 grade.</li>
    <li>Not validated for regulated (GxP / 21 CFR Part 11) use. The audit trail here is tamper-evident but is not a substitute for formal validation.</li></ul></div>
    <div class="card" style="padding:18px 22px;margin-top:16px"><h3>Re-measure</h3><pre class="cmd">python make_samples.py            # build the answer-key samples (once)
python evaluate.py                # hand-built answer key + controls
python mutate.py                  # mutation testing on samples/ and real/
python mutate.py real/*.pdf --per 6</pre></div>`;
  view.innerHTML = `<div class="page"><div class="ph"><div><h1>Validation</h1><div class="sub">${m ? 'Mutation run ' + esc(m.measured) : ''}${ak ? ' · answer key ' + esc(ak.measured) : ''}. What has actually been measured, and how.</div></div></div>${body}</div>`;
}

/* ── view: report ────────────────────────────────────────────────────── */
async function viewReport(id) {
  const p = await api(`/api/jobs/${id}/report`);
  openReport(p, false);
}

function openReport(p, standalone) {
  const R = {
    p, standalone, page: 0, mode: 'side', sel: null, tab: 'findings', showMarks: true,
    filter: { sev: new Set(['critical', 'major', 'minor']), cat: '', status: '', q: '', thisPage: false },
    reviews: p.reviews || {}, audit: p.audit || { entries: [], intact: true }, signoff: p.signoff || null,
    k: 1, tx: 0, ty: 0, swipe: 0.5, flick: { timer: null, showB: false, paused: false },
    reviewer: store.get('fx-reviewer', ''), group: store.get('fx-group', '0') === '1', batchRows: null,
  };
  const pages = p.pages;
  const real = p.findings.filter((f) => f.severity !== 'info');
  const pageOf = (f) => Math.max(0, pages.findIndex((x) => x.index === f.page));
  const decision = (f) => (R.reviews[String(f.id)] || {}).decision || 'pending';

  let view;
  if (standalone) { root.innerHTML = '<div class="shell solo"><main class="main" id="view"></main></div>'; view = $('#view'); }
  else view = mountShell('history', true);

  const counts = p.counts;
  const limitedPages = p.coverage.filter((c) => c.limited);
  view.innerHTML = `
    <div class="rpt-head">
      <div style="min-width:0">
        <div class="row" style="gap:8px">${standalone ? `<img src="${LOGO}" alt="" style="width:26px;height:26px;mix-blend-mode:multiply" class="logo-inline">` : `<a class="btn ghost icon" href="${p.batch ? '#/batch/' + p.batch : '#/history'}" title="${p.batch ? 'Back to the batch' : 'Back to history'}">${icon('right').replace('<svg', '<svg style="transform:rotate(180deg)"')}</a>`}<h1>Proof report</h1><span id="bnav" class="row" style="gap:4px;margin-left:6px"></span></div>
        <div class="files sub"><span class="chip">Sample <b>${esc(p.names.sample)}</b></span><span class="muted">vs</span><span class="chip">Reference <b>${esc(p.names.ref)}</b></span>${p.names.deck ? `<span class="muted">+</span><span class="chip">Approved text <b>${esc(p.names.deck)}</b></span>` : ''}
        <span>${fmtDate(p.created)} · engine v${esc(p.engine.version)} · ${esc(p.engine.profile || 'Standard')} profile · ${p.engine.dpi} dpi · OCR ${p.engine.ocr ? 'on' : 'off'}${p.meta && p.meta.elapsed_s ? ' · ' + p.meta.elapsed_s + ' s' : ''}</span></div>
      </div>
      <div class="rpt-actions"><div class="verdict ${p.verdict}">${icon(VERDICT_ICON[p.verdict], 'lg')}<div>${VERDICT_TEXT[p.verdict][0]}<br><small>${VERDICT_TEXT[p.verdict][1]}</small></div></div>
      ${standalone ? `<button class="btn" onclick="window.print()">${icon('printer')} Print</button>` : `
      <input type="text" id="reviewer" placeholder="Your name (reviewer)" style="width:170px" value="${esc(R.reviewer)}">
      <div class="menu"><button class="btn" id="expbtn">${icon('download')} Export ${icon('down')}</button>
        <div class="pop card" id="exppop" hidden>
          <button data-exp="html">${icon('file')} Standalone report (.html)</button><button data-exp="pdf">${icon('pen')} Annotated sample (.pdf)</button><button data-exp="csv">${icon('list')} Findings (.csv)</button><button data-exp="json">${icon('layers')} Full data (.json)</button></div></div>
      <button class="btn primary" id="signbtn">${icon('pen')} Sign off</button>`}
    </div></div>
    <div id="banners"></div>
    <div class="kpis" id="kpis"></div>
    <div class="work">
      <section class="viewer card"><div class="vbar" id="vbar"></div><div class="vp" id="vp"></div><div class="legend" id="legend"></div></section>
      <aside class="side card"><div class="tabs" id="tabs"></div><div id="sidebody"></div></aside>
    </div>`;
  if (standalone) { const im = $('.logo-inline'); if (im && document.documentElement.classList.contains('dark')) im.style.filter = 'invert(1)'; }

  /* banners + kpis */
  function renderBanners() {
    const b = [];
    if (R.signoff) {
      const ok = R.signoff.outcome === 'approved';
      b.push(`<div class="banner ${ok ? 'ok' : 'bad'}">${icon(ok ? 'shield' : 'xcircle', 'lg')}<div><b>${ok ? 'Approved' : 'Sent back'} by ${esc(R.signoff.reviewer)}</b> on ${fmtDate(R.signoff.ts)}${R.signoff.note ? ' - ' + esc(R.signoff.note) : ''}<div class="sub">Recorded with SHA-256 of both input files in the audit log.</div></div></div>`);
    }
    if (!R.audit.intact) b.push(`<div class="banner bad">${icon('alert', 'lg')}<div><b>The audit log fails its integrity check.</b> An entry was altered, removed or reordered after it was written.</div></div>`);
    if (limitedPages.length) {
      b.push(`<div class="banner warn">${icon('info', 'lg')}<div><b>Limited coverage on ${limitedPages.length} of ${p.coverage.length} page${p.coverage.length > 1 ? 's' : ''}.</b> ${p.verdict === 'PASS' ? 'A clean result here means no <i>visual</i> difference was found; ' : ''}text, braille and layers could not be compared where a file has no text layer (image-only or outlined artwork)${p.engine.ocr ? '; changed regions were read with OCR' : ''}. Ask for live-text artwork for a full check. <a href="#" data-goto="coverage">See exactly what ran</a></div></div>`);
    }
    $('#banners').innerHTML = b.join('');
  }
  function renderKpis() {
    const done = real.filter((f) => decision(f) !== 'pending').length;
    const k = (cls, n, l) => `<div class="card kpi ${cls}"><div class="n">${n}</div><div class="l">${l}</div></div>`;
    $('#kpis').innerHTML = k('critical', counts.critical, 'Critical') + k('major', counts.major, 'Major') + k('minor', counts.minor, 'Minor')
      + k('', p.attention.length, 'Need a human eye') + k('', limitedPages.length ? 'Limited' : 'Full', 'Coverage')
      + `<div class="card kpi"><div class="n">${done}<span class="muted" style="font-size:15px"> / ${real.length}</span></div><div class="l">Findings reviewed</div><div class="bar"><i style="width:${real.length ? (100 * done / real.length) : 100}%"></i></div></div>`;
  }
  view.addEventListener('click', (e) => {
    const g = e.target.closest('[data-goto]');
    if (g) { e.preventDefault(); R.tab = g.dataset.goto; renderSide(); }
  });

  /* ── viewer ─────────────────────────────────────────────────────── */
  const Pg = () => pages[R.page];
  const dims = () => { const g = Pg(); return { W: g.w_pt * PX_PER_PT, H: g.h_pt * PX_PER_PT }; };
  let panes = [];
  const unit = () => 1 / (R.k * PX_PER_PT); // one screen pixel, expressed in page points

  function renderVbar() {
    const modes = [['side', 'columns', 'Side by side'], ['overlay', 'layers', 'Overlay'], ['swipe', 'swipe', 'Swipe'], ['flick', 'zap', 'Flicker']];
    $('#vbar').innerHTML = `
      ${pages.length > 1 ? `<div class="seg" id="pgseg">${pages.map((g, i) => `<button data-pg="${i}" class="${i === R.page ? 'on' : ''}">Page ${g.index + 1}</button>`).join('')}</div>` : ''}
      <div class="seg" id="modeseg">${modes.map(([m, i, l]) => `<button data-mode="${m}" class="${R.mode === m ? 'on' : ''}" title="${l}">${icon(i)}<span>${l}</span></button>`).join('')}</div>
      <span class="spacer"></span>
      <label class="toggle" title="Show finding markers (m)"><input type="checkbox" id="marks" ${R.showMarks ? 'checked' : ''}><span class="sub">Markers</span></label>
      <div class="row" style="gap:2px"><button class="btn ghost icon" data-z="out" title="Zoom out">${icon('zout')}</button><button class="btn ghost icon" data-z="in" title="Zoom in">${icon('zin')}</button><button class="btn ghost icon" data-z="fit" title="Fit page (f)">${icon('fit')}</button></div>`;
  }
  function renderLegend() {
    const lg = { side: '<span>Scroll to zoom · drag to pan · both pages move together</span>', overlay: '<span><i style="background:#d32f2f"></i>only in reference</span><span><i style="background:#1976d2"></i>only in sample</span><span><i style="background:#aaa"></i>in both</span>',
      swipe: '<span>Drag the handle: reference on the left, sample on the right</span>', flick: '<span>Alternates reference and sample every 0.7 s; click the page to pause</span>' }[R.mode];
    $('#legend').innerHTML = lg + `<span class="hint"><kbd>j</kbd>/<kbd>k</kbd> next / previous · <kbd>a</kbd> accept · <kbd>r</kbd> reject · <kbd>?</kbd> all shortcuts</span>`;
  }

  function markSvg(key) {
    const g = Pg();
    const items = real.filter((f) => pageOf(f) === R.page && (f[key] || f.bbox_a || f.bbox_b));
    const seen = {};
    const rects = items.map((f) => {
      const b = f[key] || (key === 'bbox_b' ? f.bbox_a : f.bbox_b) || f.bbox_a || f.bbox_b;
      const k = b.map((v) => Math.round(v / 3)).join(',');  // findings on the same spot: put labels side by side
      const off = (seen[k] = (seen[k] ?? -1) + 1);
      return `<g class="mk ${f.severity} ${R.sel === f.id ? 'sel' : ''}" data-id="${f.id}" data-off="${off}" data-b="${b.join(',')}"><rect class="glow"/><rect class="box"/><g class="lbl"><rect/><text>${f.id}</text></g></g>`;
    }).join('');
    return `<svg class="marks" viewBox="0 0 ${g.w_pt} ${g.h_pt}" style="${R.showMarks ? '' : 'display:none'}">${rects}</svg>`;
  }
  function stage(imgs, key) {
    const { W, H } = dims();
    return `<div class="stage" style="width:${W}px;height:${H}px">${imgs}${markSvg(key)}</div>`;
  }
  function buildPanes() {
    if (R.flick.timer) { clearInterval(R.flick.timer); R.flick.timer = null; }
    const g = Pg(), vp = $('#vp');
    vp.className = 'vp' + (R.mode === 'side' ? ' two' : '');
    if (R.mode === 'side') {
      // stack the two pages top/bottom when that shows them larger (wide labels in a narrow viewer)
      const { W, H } = dims(), bw = vp.clientWidth, bh = vp.clientHeight;
      const across = Math.min(bw / 2 / W, bh / H), stacked = Math.min(bw / W, bh / 2 / H);
      vp.style.gridTemplateColumns = stacked > across ? '1fr' : '';
      vp.style.gridTemplateRows = stacked > across ? '1fr 1fr' : '';
    } else { vp.style.gridTemplateColumns = ''; vp.style.gridTemplateRows = ''; }
    const P = (tag, body) => `<div class="pane">${tag ? `<div class="tag"><span>${tag}</span></div>` : ''}${body}</div>`;
    if (R.mode === 'side') vp.innerHTML = P('REFERENCE', stage(`<img src="${g.img.ref}" alt="reference page" draggable="false">`, 'bbox_a')) + P('SAMPLE', stage(`<img src="${g.img.sample}" alt="sample page" draggable="false">`, 'bbox_b'));
    else if (R.mode === 'overlay') vp.innerHTML = P('OVERLAY', stage(`<img src="${g.img.overlay}" alt="overlay" draggable="false">`, 'bbox_a'));
    else if (R.mode === 'swipe') vp.innerHTML = P('', stage(`<img src="${g.img.ref}" draggable="false"><img class="top" src="${g.img.sample}" draggable="false" style="position:absolute;inset:0;clip-path:inset(0 0 0 ${R.swipe * 100}%)">`, 'bbox_a')) ;
    else vp.innerHTML = P('<span id="fl">REFERENCE</span>', stage(`<img id="fa" src="${g.img.ref}" draggable="false"><img id="fb" src="${g.img.sample}" draggable="false" style="position:absolute;inset:0;opacity:${R.flick.showB ? 1 : 0}">`, 'bbox_a'));
    if (R.mode === 'swipe') $('.pane', vp).insertAdjacentHTML('beforeend', '<div class="swipe-handle" id="sh"></div>');
    if (R.mode === 'swipe') $$('.tag', vp).forEach((t) => t.remove());
    panes = $$('.pane', vp);
    panes.forEach(bindPane);
    if (R.mode === 'flick') startFlicker();
    fit(false);
    bindSwipe();
  }
  function startFlicker() {
    const set = () => { const a = $('#fa'), b = $('#fb'), l = $('#fl'); if (!b) return; b.style.opacity = R.flick.showB ? 1 : 0; if (l) l.textContent = R.flick.showB ? 'SAMPLE' : 'REFERENCE'; };
    set();
    R.flick.timer = setInterval(() => { if (!R.flick.paused) { R.flick.showB = !R.flick.showB; set(); } }, 700);
  }
  function paneSize() { const r = panes[0].getBoundingClientRect(); return { w: r.width, h: r.height }; }
  function apply(animate) {
    panes.forEach((pn) => {
      const st = $('.stage', pn);
      st.classList.toggle('anim', !!animate);
      st.style.transform = `translate(${R.tx}px,${R.ty}px) scale(${R.k})`;
    });
    updateMarks();
    const sh = $('#sh'); if (sh) { const { W } = dims(); sh.style.left = (R.tx + R.swipe * W * R.k) + 'px'; }
  }
  function updateMarks() {
    const u = unit();
    $$('.mk', $('#vp')).forEach((g) => {
      const [x0, y0, x1, y1] = g.dataset.b.split(',').map(Number), pad = 2 * u * 2;
      const bx = x0 - pad, by = y0 - pad, bw = x1 - x0 + 2 * pad, bh = y1 - y0 + 2 * pad;
      $$('rect.box, rect.glow', g).forEach((r) => { r.setAttribute('x', bx); r.setAttribute('y', by); r.setAttribute('width', bw); r.setAttribute('height', bh); });
      const lh = 15 * u, txt = $('text', g), lw = Math.max(15, 8 + 7 * String(txt.textContent).length) * u;
      const lr = $('.lbl rect', g);
      const lx = bx + Number(g.dataset.off || 0) * (lw + 2 * u);
      lr.setAttribute('x', lx); lr.setAttribute('y', by - lh); lr.setAttribute('width', lw); lr.setAttribute('height', lh); lr.setAttribute('rx', 3 * u);
      txt.setAttribute('x', lx + lw / 2); txt.setAttribute('y', by - lh / 2); txt.style.fontSize = (10 * u) + 'px';
    });
  }
  function fit(animate = true) {
    const { W, H } = dims(), { w, h } = paneSize();
    R.k = Math.min(w / W, h / H) * 0.96;
    R.tx = (w - W * R.k) / 2; R.ty = (h - H * R.k) / 2;
    apply(animate);
  }
  function zoomAt(cx, cy, f) {
    const nk = Math.max(0.05, Math.min(12, R.k * f)), r = nk / R.k;
    R.tx = cx - (cx - R.tx) * r; R.ty = cy - (cy - R.ty) * r; R.k = nk;
    apply(false);
  }
  function bindPane(pn) {
    let drag = null, moved = 0;
    pn.addEventListener('pointerdown', (e) => {
      if (e.target.closest('.swipe-handle')) return;
      drag = { x: e.clientX, y: e.clientY, tx: R.tx, ty: R.ty }; moved = 0; pn.setPointerCapture(e.pointerId); pn.classList.add('grabbing');
    });
    pn.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y; moved = Math.max(moved, Math.hypot(dx, dy));
      R.tx = drag.tx + dx; R.ty = drag.ty + dy; apply(false);
    });
    const end = (e) => {
      if (!drag) return;
      drag = null; pn.classList.remove('grabbing');
      if (moved < 4) {
        const mk = document.elementsFromPoint(e.clientX, e.clientY).map((n) => n.closest && n.closest('.mk')).find(Boolean);
        if (mk) select(Number(mk.dataset.id), { focus: false, scroll: true });
        else if (R.mode === 'flick') R.flick.paused = !R.flick.paused;
      }
    };
    pn.addEventListener('pointerup', end); pn.addEventListener('pointercancel', () => { drag = null; pn.classList.remove('grabbing'); });
    pn.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = pn.getBoundingClientRect();
      zoomAt(e.clientX - r.left, e.clientY - r.top, Math.pow(1.0018, -e.deltaY));
    }, { passive: false });
    pn.addEventListener('dblclick', () => fit());
  }
  function bindSwipe() {
    const sh = $('#sh'); if (!sh) return;
    sh.addEventListener('pointerdown', (e) => {
      e.stopPropagation(); sh.setPointerCapture(e.pointerId);
      const pn = sh.parentElement, top = $('img.top', pn);
      const move = (ev) => {
        const r = pn.getBoundingClientRect(), { W } = dims();
        R.swipe = Math.max(0, Math.min(1, (ev.clientX - r.left - R.tx) / (W * R.k)));
        top.style.clipPath = `inset(0 0 0 ${R.swipe * 100}%)`; apply(false);
      };
      const up = () => { sh.removeEventListener('pointermove', move); sh.removeEventListener('pointerup', up); };
      sh.addEventListener('pointermove', move); sh.addEventListener('pointerup', up);
    });
  }
  function focusBoxes(f) {
    const bs = [f.bbox_a, f.bbox_b].filter(Boolean);
    if (!bs.length) return;
    const b = [Math.min(...bs.map((x) => x[0])), Math.min(...bs.map((x) => x[1])), Math.max(...bs.map((x) => x[2])), Math.max(...bs.map((x) => x[3]))];
    const { w, h } = paneSize(), bw = Math.max(8, (b[2] - b[0]) * PX_PER_PT), bh = Math.max(8, (b[3] - b[1]) * PX_PER_PT);
    const { W, H } = dims(), fitK = Math.min(w / W, h / H) * 0.96;
    R.k = Math.max(fitK, Math.min(2.4, Math.min(w * 0.3 / bw, h * 0.3 / bh)));
    R.tx = w / 2 - ((b[0] + b[2]) / 2) * PX_PER_PT * R.k; R.ty = h / 2 - ((b[1] + b[3]) / 2) * PX_PER_PT * R.k;
    apply(true);
  }
  function markSelection() {
    $$('.mk', $('#vp')).forEach((g) => g.classList.toggle('sel', Number(g.dataset.id) === R.sel));
    $$('.find', $('#sidebody')).forEach((c) => c.classList.toggle('sel', Number(c.dataset.id) === R.sel));
  }
  function select(id, opt = {}) {
    R.sel = id;
    const f = p.findings.find((x) => x.id === id);
    if (f && pageOf(f) !== R.page) { R.page = pageOf(f); renderVbar(); buildPanes(); }
    if (R.tab !== 'findings') { R.tab = 'findings'; renderSide(); }
    markSelection();
    if (f && opt.focus !== false) focusBoxes(f);
    if (opt.scroll !== false) {
      // scroll only the findings panel, never the page
      const box = $('#sidebody'), c = $(`.find[data-id="${id}"]`, box);
      if (c) {
        const top = c.offsetTop - box.offsetTop, bottom = top + c.offsetHeight;
        if (top < box.scrollTop + 8) box.scrollTo({ top: top - 8, behavior: 'smooth' });
        else if (bottom > box.scrollTop + box.clientHeight - 8) box.scrollTo({ top: bottom - box.clientHeight + 8, behavior: 'smooth' });
      }
    }
  }

  view.addEventListener('click', (e) => {
    const pg = e.target.closest('[data-pg]'); if (pg) { R.page = Number(pg.dataset.pg); renderVbar(); buildPanes(); renderSide(); }
    const md = e.target.closest('[data-mode]'); if (md) { R.mode = md.dataset.mode; renderVbar(); renderLegend(); buildPanes(); }
    const z = e.target.closest('[data-z]');
    if (z) { const { w, h } = paneSize(); if (z.dataset.z === 'fit') fit(); else zoomAt(w / 2, h / 2, z.dataset.z === 'in' ? 1.4 : 1 / 1.4); }
  });
  view.addEventListener('change', (e) => {
    if (e.target.id === 'marks') { R.showMarks = e.target.checked; $$('svg.marks', $('#vp')).forEach((s) => (s.style.display = R.showMarks ? '' : 'none')); }
  });

  /* ── side panel ─────────────────────────────────────────────────── */
  function renderTabs() {
    const t = [['findings', 'list', 'Findings', real.length], ['coverage', 'shield', 'Coverage', null], ['audit', 'lock', 'Audit', R.audit.entries.length || null]];
    $('#tabs').innerHTML = t.map(([k, i, l, c]) => `<button data-tab="${k}" class="${R.tab === k ? 'on' : ''}">${icon(i)}${l}${c ? `<span class="ct">${c}</span>` : ''}</button>`).join('');
  }
  function visibleFindings() {
    const F = R.filter, q = F.q.trim().toLowerCase();
    return p.findings.filter((f) => {
      if (!F.sev.has(f.severity) && !(f.severity === 'info' && F.sev.has('info'))) return false;
      if (F.cat && f.category !== F.cat) return false;
      if (F.status && decision(f) !== F.status) return false;
      if (F.thisPage && pageOf(f) !== R.page) return false;
      if (q && !(f.message + ' ' + f.a_text + ' ' + f.b_text + ' ' + f.category + ' ' + f.kind).toLowerCase().includes(q)) return false;
      return true;
    });
  }
  function findHtml(f) {
    const d = decision(f), rv = R.reviews[String(f.id)] || {};
    let diff = '';
    if (f.a_text || f.b_text) {
      const [ha, hb] = f.a_text && f.b_text ? diffHtml(f.a_text, f.b_text) : [esc(f.a_text), esc(f.b_text)];
      diff = `<div class="diff">${f.a_text ? `<span class="k">Reference</span><span>${f.a_text && f.b_text ? ha : `<del>${ha}</del>`}</span>` : ''}${f.b_text ? `<span class="k">Sample</span><span>${f.a_text && f.b_text ? hb : `<ins>${hb}</ins>`}</span>` : ''}</div>`;
    }
    const related = (f.detail && f.detail.related_text || []).map((t) => `<div class="sub" style="margin-top:4px">Also: ${esc(t)}</div>`).join('');
    const canReview = !R.standalone && f.severity !== 'info';
    return `<div class="find ${f.severity} ${R.sel === f.id ? 'sel' : ''} ${d !== 'pending' ? 'done' : ''}" data-id="${f.id}">
      <div class="top"><span class="num">${f.id}</span><span class="badge ${f.severity}">${SEV_LABEL[f.severity]}</span><span class="badge muted">${esc(f.category)} · ${esc(f.kind.replace(/_/g, ' '))}</span>
        <span class="spacer"></span><span class="conf ${f.confidence}" title="${f.confidence === 'high' ? 'Read directly from the PDF or decoded' : 'Inferred from rendered pixels or a proxy measurement'}"><i></i>${f.confidence}</span><span class="sub">p${f.page + 1}</span></div>
      <p class="msg">${esc(f.message)}</p>${diff}${related}
      <details class="why"><summary>${icon('right')} Why this was flagged</summary><p>${esc(f.why)}</p></details>
      ${canReview ? `<div class="review"><div class="btns">
          <button class="btn sm ${d === 'accepted' ? 'on-acc' : ''}" data-dec="accepted" title="An intended or approved difference (a)">${icon('check')} Accept</button>
          <button class="btn sm ${d === 'rejected' ? 'on-rej' : ''}" data-dec="rejected" title="A defect that must be fixed (r)">${icon('x')} Reject</button>
          ${d !== 'pending' ? `<button class="btn sm ghost" data-dec="pending">Undo</button>` : ''}</div>
          ${d !== 'pending' || rv.note ? `<textarea placeholder="Note (optional)" data-note>${esc(rv.note || '')}</textarea>` : ''}</div>`
        : (d !== 'pending' ? `<div class="decided">${icon(d === 'accepted' ? 'check' : 'x')} ${d}${rv.reviewer ? ' by ' + esc(rv.reviewer) : ''}${rv.note ? ' - ' + esc(rv.note) : ''}</div>` : '')}
      ${canReview && d !== 'pending' && rv.reviewer ? `<div class="decided">${icon(d === 'accepted' ? 'check' : 'x')} ${d} by ${esc(rv.reviewer)}</div>` : ''}
    </div>`;
  }
  function renderSide() {
    renderTabs();
    const body = $('#sidebody');
    if (R.tab === 'coverage') return (body.innerHTML = coverageHtml());
    if (R.tab === 'audit') return (body.innerHTML = auditHtml());
    const cats = [...new Set(p.findings.map((f) => f.category))].sort();
    const cnt = (s) => p.findings.filter((f) => f.severity === s).length;
    const list = visibleFindings();
    body.innerHTML = `<div class="filters">
        <div class="chips">${SEV.filter((s) => cnt(s)).map((s) => `<button class="chip btnlike ${R.filter.sev.has(s) ? 'on' : ''}" data-sev="${s}">${SEV_LABEL[s]} ${cnt(s)}</button>`).join('')}
          ${pages.length > 1 ? `<button class="chip btnlike ${R.filter.thisPage ? 'on' : ''}" data-thispage>This page</button>` : ''}
          <button class="chip btnlike ${R.group ? 'on' : ''}" data-group title="Group findings by type">Group by type</button></div>
        <div class="row wrap"><div class="search grow">${icon('search')}<input type="text" id="q" placeholder="Search findings" value="${esc(R.filter.q)}"></div>
          <select id="cat" style="width:auto"><option value="">All types</option>${cats.map((c) => `<option ${R.filter.cat === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>
          ${R.standalone ? '' : `<select id="stat" style="width:auto"><option value="">Any status</option>${['pending', 'accepted', 'rejected'].map((s) => `<option ${R.filter.status === s ? 'selected' : ''}>${s}</option>`).join('')}</select>`}</div></div>
      ${p.attention.length ? `<div class="attn"><b>${icon('eye')} Not differences, but worth a look</b>${p.attention.map((a, i) => `<div class="it" data-att="${i}">${esc(a.message)}</div>`).join('')}</div>` : ''}
      <div class="flist" id="flist">${list.length ? (R.group ? groupHtml(list) : list.map(findHtml).join('')) : (real.length ? `<div class="empty">No findings match these filters.</div>` : `<div class="empty">${icon('shield')}<div><b>No differences found</b></div><div class="sub">${limitedPages.length ? 'Coverage was limited; see the Coverage tab for what could not run.' : 'Every check that ran came back clean.'}</div></div>`)}</div>`;
    if (R.sel) markSelection();
  }
  function groupHtml(list) {
    const CAT = { text: 'Text', copydeck: 'Approved text', spelling: 'Spelling', barcode: 'Barcodes', braille: 'Braille', color: 'Colour & inks',
      layer: 'Layers', layout: 'Layout', graphic: 'Graphics', format: 'Formatting', structure: 'Page structure', info: 'Notes' };
    const by = {};
    list.forEach((f) => (by[f.category] = by[f.category] || []).push(f));
    return Object.keys(by).sort((a, b) => Math.min(...by[a].map((f) => SEV.indexOf(f.severity))) - Math.min(...by[b].map((f) => SEV.indexOf(f.severity))))
      .map((c) => `<div class="grp"><b>${esc(CAT[c] || c)}</b><span class="ct">${by[c].length}</span></div>` + by[c].map(findHtml).join('')).join('');
  }
  function coverageHtml() {
    return `<div class="cov"><div class="sub">What this proof checked, page by page, and what it could not. A clean result only speaks for the checks that ran.</div>
      ${p.coverage.map((c) => `<div class="pg"><div class="pgh"><span>Page ${c.page + 1}</span><span class="badge muted">${c.mode}</span>${c.limited ? '<span class="badge major">limited</span>' : '<span class="badge good">full</span>'}</div>
        ${c.checks.map((k) => `<div class="chk"><span class="st ${k.status}">${k.status === 'ran' ? icon('check') : ''}</span><b>${esc(k.name)}</b><small>${esc(k.note)}</small></div>`).join('')}</div>`).join('')}
      ${p.warnings.map((w) => `<div class="attn">${esc(w)}</div>`).join('')}</div>`;
  }
  function auditHtml() {
    const m = p.meta || {}, sh = m.sha256 || {}, en = R.audit.entries;
    return `<div class="aud"><div class="row"><span class="badge ${R.audit.intact ? 'good' : 'critical'}">${R.audit.intact ? 'Chain intact' : 'Chain broken'}</span><span class="sub">Each entry is hashed together with the one before it.</span></div>
      <dl class="kv"><dt>Reference</dt><dd>${esc(p.names.ref)}<br>${esc(sh.ref || 'n/a')}</dd><dt>Sample</dt><dd>${esc(p.names.sample)}<br>${esc(sh.sample || 'n/a')}</dd>${p.names.deck ? `<dt>Approved text</dt><dd>${esc(p.names.deck)}<br>${esc(sh.deck || 'n/a')}</dd>` : ''}
        <dt>Engine</dt><dd>v${esc(p.engine.version)} · ${p.engine.dpi} dpi · OCR ${p.engine.ocr ? 'on' : 'off'}</dd></dl>
      ${en.length ? en.slice().reverse().map((e) => `<div class="ent"><b>${e.type === 'signoff' ? `Sign-off: ${esc(e.outcome)}` : `Finding #${e.finding} ${esc(e.decision)}`}</b> ${e.reviewer ? 'by ' + esc(e.reviewer) : ''}<small>${fmtDate(e.ts)}${e.note ? ' · ' + esc(e.note) : ''}</small></div>`).join('') : '<div class="empty">No review activity yet.</div>'}</div>`;
  }

  const side = $('#sidebody');
  side.addEventListener('click', async (e) => {
    const sev = e.target.closest('[data-sev]');
    if (sev) { const s = sev.dataset.sev; R.filter.sev.has(s) ? R.filter.sev.delete(s) : R.filter.sev.add(s); return renderSide(); }
    if (e.target.closest('[data-thispage]')) { R.filter.thisPage = !R.filter.thisPage; return renderSide(); }
    if (e.target.closest('[data-group]')) { R.group = !R.group; store.set('fx-group', R.group ? '1' : '0'); return renderSide(); }
    const att = e.target.closest('[data-att]');
    if (att) { const a = p.attention[Number(att.dataset.att)]; if (a && a.bbox) { const idx = Math.max(0, pages.findIndex((x) => x.index === a.page)); if (idx !== R.page) { R.page = idx; renderVbar(); buildPanes(); } focusBoxes({ bbox_a: a.bbox }); } return; }
    const dec = e.target.closest('[data-dec]');
    const card = e.target.closest('.find');
    if (dec && card) { e.stopPropagation(); return decide(Number(card.dataset.id), dec.dataset.dec); }
    if (card && !e.target.closest('summary, textarea, details')) select(Number(card.dataset.id));
  });
  side.addEventListener('input', (e) => {
    if (e.target.id === 'q') { R.filter.q = e.target.value; const pos = e.target.selectionStart; renderSide(); const q = $('#q'); q.focus(); q.setSelectionRange(pos, pos); }
  });
  side.addEventListener('change', (e) => {
    if (e.target.id === 'cat') { R.filter.cat = e.target.value; renderSide(); }
    if (e.target.id === 'stat') { R.filter.status = e.target.value; renderSide(); }
    if (e.target.matches('[data-note]')) { const card = e.target.closest('.find'); const f = Number(card.dataset.id); decide(f, decision({ id: f }), e.target.value, true); }
  });
  $('#tabs').addEventListener('click', (e) => { const t = e.target.closest('[data-tab]'); if (t) { R.tab = t.dataset.tab; renderSide(); } });

  async function decide(fid, dec, note, keepFocus) {
    const cur = R.reviews[String(fid)] || {};
    const reviewer = ($('#reviewer') || {}).value || R.reviewer;
    if (reviewer) { R.reviewer = reviewer; store.set('fx-reviewer', reviewer); }
    try {
      const out = await post(`/api/jobs/${p.id}/review`, { finding: fid, decision: dec, note: note !== undefined ? note : (cur.note || ''), reviewer });
      R.reviews = out.reviews; R.audit = out.audit;
      renderKpis(); renderBanners();
      if (keepFocus) { renderTabs(); return; }
      const y = $('#flist') && $('#flist').scrollTop; renderSide(); markSelection();
    } catch (err) { toast(err.message, true); }
  }

  /* export + sign-off */
  if (!standalone) {
    const pop = $('#exppop');
    $('#expbtn').addEventListener('click', (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; });
    document.addEventListener('click', () => { pop.hidden = true; });
    pop.addEventListener('click', (e) => { const b = e.target.closest('[data-exp]'); if (b) { const a = document.createElement('a'); a.href = `/api/jobs/${p.id}/export.${b.dataset.exp}`; a.download = ''; a.click(); } });
    $('#reviewer').addEventListener('change', (e) => { R.reviewer = e.target.value; store.set('fx-reviewer', R.reviewer); });
    $('#signbtn').addEventListener('click', openSignoff);
  }
  function openSignoff() {
    const undecided = real.filter((f) => decision(f) === 'pending').length, rejected = real.filter((f) => decision(f) === 'rejected').length;
    const blockers = [];
    if (undecided) blockers.push(`${undecided} finding${undecided > 1 ? 's have' : ' has'} no decision yet`);
    if (rejected) blockers.push(`${rejected} finding${rejected > 1 ? 's are' : ' is'} rejected, so the sample can only be sent back`);
    modal(`<h2>Sign off this proof</h2><div class="sub">Your decision is written to the audit log with the SHA-256 of both input files.</div>
      <div class="field"><label class="l">Reviewer name</label><input type="text" id="so-name" value="${esc(R.reviewer)}" placeholder="Full name"></div>
      <div class="field"><label class="l">Note (optional)</label><textarea id="so-note" placeholder="Anything the next person should know"></textarea></div>
      ${p.coverage_limited ? `<label class="toggle field" style="align-items:flex-start"><input type="checkbox" id="so-ack" style="flex:none;margin-top:2px"><span>I understand coverage was limited on ${limitedPages.length} page${limitedPages.length > 1 ? 's' : ''} (image-only artwork), so text, braille and layers were not compared there.</span></label>` : ''}
      ${blockers.length ? `<div class="blockers"><b>To approve:</b><ul>${blockers.map((b) => `<li>${b}</li>`).join('')}</ul></div>` : ''}
      <div class="foot"><button class="btn" data-close>Cancel</button><button class="btn bad" id="so-rej">Send back</button><button class="btn good" id="so-ok" ${undecided || rejected ? 'disabled' : ''}>${icon('check')} Approve</button></div>`,
    (box, close) => {
      $('[data-close]', box).onclick = close;
      const send = async (outcome) => {
        const name = $('#so-name', box).value.trim();
        if (!name) return toast('Please enter your name', true);
        R.reviewer = name; store.set('fx-reviewer', name);
        try {
          const out = await post(`/api/jobs/${p.id}/signoff`, { outcome, reviewer: name, note: $('#so-note', box).value, acknowledged_limits: !!($('#so-ack', box) && $('#so-ack', box).checked) });
          R.signoff = out.signoff; R.audit = out.audit; close(); renderBanners(); renderSide(); toast(outcome === 'approved' ? 'Approved and recorded' : 'Sent back and recorded');
        } catch (err) { toast(err.message, true); }
      };
      $('#so-ok', box).onclick = () => send('approved');
      $('#so-rej', box).onclick = () => send('rejected');
    });
  }

  /* keyboard */
  const keyh = (e) => {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
    const list = visibleFindings().filter((f) => f.severity !== 'info');
    const i = list.findIndex((f) => f.id === R.sel);
    if (e.key === 'j' || e.key === 'ArrowDown') { if (list.length) select(list[Math.min(list.length - 1, i + 1)].id); e.preventDefault(); }
    else if (e.key === 'k' || e.key === 'ArrowUp') { if (list.length) select(list[Math.max(0, i - 1)].id); e.preventDefault(); }
    else if (e.key === 'f') fit();
    else if (e.key === 'm') { const c = $('#marks'); c.checked = !c.checked; c.dispatchEvent(new Event('change', { bubbles: true })); }
    else if (e.key === 'Escape') { R.sel = null; markSelection(); }
    else if (e.key === '?') keyHelp();
    else if (['1', '2', '3', '4'].includes(e.key)) { R.mode = ['side', 'overlay', 'swipe', 'flick'][Number(e.key) - 1]; renderVbar(); renderLegend(); buildPanes(); }
    else if ((e.key === '[' || e.key === ']') && R.batchRows) {
      const i = R.batchRows.findIndex((r) => r.id === p.id), j = i + (e.key === ']' ? 1 : -1);
      if (i >= 0 && R.batchRows[j]) location.hash = '#/report/' + R.batchRows[j].id;
    }
    else if (!R.standalone && R.sel && (e.key === 'a' || e.key === 'r')) decide(R.sel, e.key === 'a' ? 'accepted' : 'rejected');
  };
  document.addEventListener('keydown', keyh);
  const onResize = () => fit(false);
  window.addEventListener('resize', onResize);
  app.cleanup = () => { document.removeEventListener('keydown', keyh); window.removeEventListener('resize', onResize); if (R.flick.timer) clearInterval(R.flick.timer); };

  renderBanners(); renderKpis(); renderVbar(); renderLegend(); renderSide();
  if (!standalone && p.batch) {
    api('/api/batches/' + p.batch).then((b) => {
      R.batchRows = b.rows.filter((r) => r.state === 'done');
      const i = R.batchRows.findIndex((r) => r.id === p.id);
      const nav = $('#bnav');
      if (!nav || i < 0) return;
      const prev = R.batchRows[i - 1], next = R.batchRows[i + 1];
      nav.innerHTML = `<span class="chip">${esc(b.name)} · ${i + 1} of ${R.batchRows.length}</span>`
        + `<a class="btn ghost icon" ${prev ? `href="#/report/${prev.id}"` : 'style="opacity:.3;pointer-events:none"'} title="Previous proof ([)">${icon('right').replace('<svg', '<svg style="transform:rotate(180deg)"')}</a>`
        + `<a class="btn ghost icon" ${next ? `href="#/report/${next.id}"` : 'style="opacity:.3;pointer-events:none"'} title="Next proof (])">${icon('right')}</a>`;
    }).catch(() => {});
  }
  if (pages.length) setTimeout(() => {
    buildPanes();
    // open on the most serious finding, already zoomed in, so the problem is the first thing anyone sees
    const first = real.find((f) => f.bbox_a || f.bbox_b);
    if (first) setTimeout(() => select(first.id), 400);
  }, 0);
  else $('#vp').innerHTML = '<div class="empty">No pages were compared.</div>';
}

/* ── boot ────────────────────────────────────────────────────────────── */
(async function boot() {
  try { app.health = await api('/api/health'); } catch (e) { app.health = null; }
  if (STANDALONE) { app.health = { version: window.__PROOF__.engine.version, ocr: window.__PROOF__.engine.ocr }; return openReport(window.__PROOF__, true); }
  window.addEventListener('hashchange', route);
  route();
})();
