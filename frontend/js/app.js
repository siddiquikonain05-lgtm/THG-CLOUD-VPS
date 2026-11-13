const THG = { csrf: '', user: '', views: {}, current: '' };
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function fmtBytes(n) {
  if (n == null) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(1) : n) + ' ' + u[i];
}
function fmtDur(s) {
  s = Math.floor(s || 0);
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return (d ? d + 'd ' : '') + (h || d ? h + 'h ' : '') + (m || h || d ? m + 'm ' : '') + x + 's';
}
const fmtTime = (t) => (t ? new Date(t * 1000).toLocaleString() : '—');

let toastTimer;
function toast(msg, isErr) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'toast' + (isErr ? ' err' : ''); t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, isErr ? 6000 : 2500);
}

async function api(path, opts = {}) {
  const o = { credentials: 'same-origin', ...opts, headers: { ...(opts.headers || {}) } };
  if (opts.json !== undefined) {
    o.method = o.method || 'POST';
    o.headers['Content-Type'] = 'application/json';
    o.body = JSON.stringify(opts.json);
  }
  if (o.method && o.method !== 'GET') o.headers['X-CSRF-Token'] = THG.csrf;
  const r = await fetch(path, o);
  if (r.status === 401) { location.href = '/login'; throw new Error('Signed out'); }
  if (!r.ok) {
    let m = r.statusText;
    try { const j = await r.json(); m = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch (_) {}
    throw new Error(m);
  }
  return (r.headers.get('content-type') || '').includes('json') ? r.json() : r;
}
const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };

function show(view) {
  if (!$('#view-' + view)) view = 'dashboard';
  if (THG.current && THG.views[THG.current]?.onHide) THG.views[THG.current].onHide();
  THG.current = view;
  $$('.view').forEach((v) => v.classList.toggle('active', v.id === 'view-' + view));
  $$('#nav button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  if (location.hash !== '#' + view) history.replaceState(null, '', '#' + view);
  THG.views[view]?.onShow?.();
}

/* ---------- Dashboard ---------- */
(function () {
  let timer;
  const bar = (p) => `<div class="bar"><i class="${p > 90 ? 'hot' : ''}" style="width:${Math.min(100, p)}%"></i></div>`;
  async function load() {
    const s = await api('/api/system/status');
    const m = s.memory, d = s.disk;
    $('#dash-cards').innerHTML = [
      `<div class="card"><div class="k">Server</div><div class="v" style="color:var(--accent)">● ${esc(s.status)}</div><div class="muted">up ${fmtDur(s.uptime)}</div></div>`,
      `<div class="card"><div class="k">Python</div><div class="v">${esc(s.python)}</div><div class="muted">terminal default: venv on /data</div></div>`,
      `<div class="card"><div class="k">CPU</div><div class="v">${s.cpu_percent}%</div>${bar(s.cpu_percent)}<div class="muted">${s.cpu_count} cores · load ${s.load.map((x) => x.toFixed(2)).join(' ')}</div></div>`,
      `<div class="card"><div class="k">RAM ${m.container_limit ? '(container limit)' : ''}</div><div class="v">${m.percent}%</div>${bar(m.percent)}<div class="muted">${fmtBytes(m.used)} / ${fmtBytes(m.total)}</div></div>`,
      `<div class="card"><div class="k">Disk (/data)</div><div class="v">${d.percent}%</div>${bar(d.percent)}<div class="muted">${fmtBytes(d.used)} / ${fmtBytes(d.total)}</div></div>`,
      `<div class="card"><div class="k">Running processes</div><div class="v">${s.running_jobs}</div><div class="muted">${s.total_jobs} jobs in history</div></div>`,
      `<div class="card"><div class="k">Workspace</div><div class="v sm mono">${esc(s.workspace)}</div><div class="muted mono">${esc(s.projects_dir)}</div></div>`,
    ].join('');
    const b = $('#banner');
    b.hidden = !d.warning;
    if (d.warning) b.textContent = `Storage warning: volume is ${d.percent}% full (threshold ${d.warn_percent}%). Free space in Settings → Storage.`;
    $('#dash-jobs').innerHTML = s.recent_jobs.length ? s.recent_jobs.map(jobCard.mini).join('') : '<p class="muted">No jobs yet.</p>';
  }
  THG.views.dashboard = {
    onShow() { guard(load)(); timer = setInterval(guard(load), 5000); },
    onHide() { clearInterval(timer); },
  };
})();

/* ---------- Settings ---------- */
(function () {
  async function load() {
    const [st, info] = await Promise.all([api('/api/system/storage'), api('/api/system/info')]);
    $('#set-storage').innerHTML = `Disk ${fmtBytes(st.disk.used)} / ${fmtBytes(st.disk.total)} (${st.disk.percent}%)<br>` +
      Object.entries(st.sizes).map(([k, v]) => `<span class="mono">${k}/</span> ${fmtBytes(v)}`).join(' · ') +
      '<br><span class="small-text">Railway volume size and compute are subject to your Railway plan limits and charges.</span>';
    $('#set-info').innerHTML = `Upload limit ${info.max_upload_mb} MB · ZIP extract limit ${info.max_extract_mb} MB · log rotation at ${info.max_log_mb} MB (keeps ${info.log_keep}) · sessions last ${info.session_hours} h · max ${info.max_running_jobs} running jobs`;
    $('#set-user').textContent = THG.user;
    $('#set-font').value = localStorage.getItem('thg_font') || 14;
  }
  async function clean(dry) {
    const days = parseFloat($('#clean-days').value || '30');
    if (!dry && !confirm(`Permanently delete logs of finished jobs older than ${days} days?`)) return;
    const r = await api('/api/system/cleanup', { json: { older_than_days: days, dry_run: dry } });
    $('#clean-out').textContent = (dry ? 'Would delete ' : 'Deleted ') + r.files.length + ' files (' + fmtBytes(r.bytes) + ')\n' + r.files.map((f) => f.name + '  ' + fmtBytes(f.size)).join('\n');
    if (!dry) load();
  }
  $('#clean-preview').onclick = guard(() => clean(true));
  $('#clean-run').onclick = guard(() => clean(false));
  $('#set-font').onchange = (e) => { localStorage.setItem('thg_font', e.target.value); THG.setFont?.(+e.target.value); };
  $('#logout').onclick = guard(async () => { await api('/api/auth/logout', { method: 'POST' }); location.href = '/login'; });
  THG.views.settings = { onShow: guard(load) };
})();

/* ---------- shared job card (used by dashboard + processes) ---------- */
const jobCard = {
  mini(j) {
    return `<div class="job"><div class="top"><b>#${j.id} ${esc(j.name)}</b><span class="st ${j.status}">${j.status}</span></div><div class="cmd">${esc(j.command)}</div><div class="muted small-text">${fmtDur(j.runtime)} · started ${fmtTime(j.started_at)}</div></div>`;
  },
  full(j) {
    const run = j.status === 'RUNNING';
    const note = j.status === 'INTERRUPTED' ? '<div class="muted small-text">The process disappeared before reporting an exit code (container restart or redeploy). It was NOT finished.</div>' : '';
    return `<div class="job" data-id="${j.id}"><div class="top"><b>#${j.id} ${esc(j.name)}</b><span class="st ${j.status}">${j.status}</span></div>
      <div class="cmd">${esc(j.command)}</div>
      <dl><dt>Directory</dt><dd>${esc(j.cwd)}</dd><dt>PID</dt><dd>${j.pid ?? '—'}</dd>
      <dt>Started</dt><dd>${fmtTime(j.started_at)}</dd><dt>Runtime</dt><dd>${fmtDur(j.runtime)}</dd>
      <dt>Exit code</dt><dd>${j.exit_code ?? '—'}</dd>
      <dt>CPU / RAM</dt><dd>${j.cpu_percent == null ? '—' : j.cpu_percent + '% / ' + fmtBytes(j.memory_rss)}</dd>
      <dt>Output</dt><dd>${fmtBytes(j.stdout_size)} out · ${fmtBytes(j.stderr_size)} err</dd></dl>${note}
      <div class="acts"><button class="btn small" data-act="logs">View output</button>
      ${run ? '<button class="btn small danger" data-act="stop">Stop</button>' : ''}
      <button class="btn small" data-act="restart">Restart</button>
      ${run ? '' : '<button class="btn small" data-act="delete">Delete history</button>'}</div></div>`;
  },
};

async function boot() {
  const me = await api('/api/auth/me');
  THG.csrf = me.csrf; THG.user = me.user;
  $('#who').textContent = me.user;
  $$('#nav button').forEach((b) => { b.onclick = () => show(b.dataset.view); });
  window.addEventListener('hashchange', () => show(location.hash.slice(1)));
  show(location.hash.slice(1) || 'dashboard');
}
document.addEventListener('DOMContentLoaded', () => boot().catch((e) => toast(e.message, true)));
