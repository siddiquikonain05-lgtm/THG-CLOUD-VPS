(function () {
  const CHUNK = 65536, MAX_CHARS = 1500000;
  const panes = {};
  let job = null, timer = null;
  const clean = (t) => t.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const hhmmss = (t) => new Date(t * 1000).toLocaleTimeString();
  const status = (t, c) => { const p = $('#log-status'); p.textContent = t; p.className = 'pill ' + (c || ''); };

  function build() {
    if (Object.keys(panes).length) return;
    ['stdout', 'stderr'].forEach((s) => {
      const el = document.createElement('div');
      el.className = 'logpane' + (s === 'stderr' ? ' err' : '');
      el.innerHTML = `<div class="lph"><b>${s}</b><span class="meta"></span>
        <button class="btn small" data-a="earlier">Load earlier</button>
        <button class="btn small" data-a="clear">Clear screen</button>
        <a class="btn small" data-a="dl">Download</a></div><div class="logbody"></div>`;
      $('#log-panes').appendChild(el);
      const p = panes[s] = { stream: s, el, body: $('.logbody', el), meta: $('.meta', el), first: 0, next: 0, size: 0, init: true, busy: false, chars: 0 };
      el.onclick = guard(async (e) => {
        const a = e.target.dataset.a;
        if (a === 'clear') { p.body.innerHTML = ''; p.chars = 0; }
        if (a === 'earlier') await earlier(p);
      });
      $('[data-a=dl]', el).onclick = () => { if (job) location.href = `/api/jobs/${job}/log/download?stream=${s}`; };
    });
    $('#log-job').onchange = (e) => select(+e.target.value);
  }

  function chunkEl(text, ts, label) {
    const d = document.createElement('div'); d.className = 'chunk';
    const t = document.createElement('span'); t.className = 'ts'; t.textContent = label + ' ' + (ts ? hhmmss(ts) : ''); t.title = 'Time of the last write to this log when it was fetched';
    const pre = document.createElement('pre'); pre.textContent = clean(text);
    d.append(t, pre); return d;
  }

  function append(p, text, ts, label) {
    const stick = p.body.scrollHeight - p.body.scrollTop - p.body.clientHeight < 40;
    p.body.appendChild(chunkEl(text, ts, label)); p.chars += text.length;
    while (p.chars > MAX_CHARS && p.body.firstChild) { p.chars -= p.body.firstChild.querySelector('pre').textContent.length; p.body.removeChild(p.body.firstChild); }
    if (!$('#log-pause').checked && stick) p.body.scrollTop = p.body.scrollHeight;
  }

  async function poll(p) {
    if (!job || p.busy) return;
    p.busy = true;
    const mine = job;
    try {
      const r = await api(`/api/jobs/${mine}/log?stream=${p.stream}&offset=${p.init ? -1 : p.next}&limit=${CHUNK}`);
      if (mine !== job) return;
      if (r.reset) { p.body.innerHTML = ''; p.chars = 0; append(p, '— log was rotated —\n', r.mtime, 'live'); }
      const wasInit = p.init;
      if (p.init) { p.first = r.offset; p.init = false; }
      if (r.data) append(p, r.data, r.mtime, wasInit ? 'tail' : 'live');
      p.next = r.next_offset; p.size = r.size;
      p.meta.textContent = fmtBytes(r.size);
      status('live', 'ok');
      if (p.next < r.size) setTimeout(() => poll(p), 0);
    } catch (e) { status('reconnecting…', 'bad'); }
    finally { p.busy = false; }
  }

  async function earlier(p) {
    if (p.first <= 0) { toast('Start of log reached'); return; }
    const start = Math.max(0, p.first - CHUNK);
    const r = await api(`/api/jobs/${job}/log?stream=${p.stream}&offset=${start}&limit=${p.first - start}`);
    const before = p.body.scrollHeight;
    p.body.insertBefore(chunkEl(r.data, r.mtime, 'history'), p.body.firstChild);
    p.chars += r.data.length; p.first = start;
    p.body.scrollTop += p.body.scrollHeight - before;
  }

  function select(id) {
    job = id; build();
    Object.values(panes).forEach((p) => { p.body.innerHTML = ''; Object.assign(p, { first: 0, next: 0, size: 0, init: true, chars: 0, busy: false }); });
    if (id) { $('#log-job').value = id; Object.values(panes).forEach(poll); }
  }

  async function refreshJobs() {
    const jobs = await api('/api/jobs');
    const sel = $('#log-job');
    sel.innerHTML = jobs.map((j) => `<option value="${j.id}">#${j.id} ${esc(j.name)} — ${j.status}</option>`).join('') || '<option value="">no jobs</option>';
    if (job && jobs.some((j) => j.id === job)) sel.value = job;
    else if (jobs.length) select(jobs[0].id);
  }

  THG.openLogs = (id) => { job = id; show('logs'); };
  THG.views.logs = {
    async onShow() {
      build();
      const want = job;
      await guard(refreshJobs)();
      if (want) select(want);
      timer = setInterval(() => Object.values(panes).forEach(poll), 1000);
    },
    onHide() { clearInterval(timer); },
  };
})();
