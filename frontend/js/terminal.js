(function () {
  let term, fit, ws, retry = 0, exited = false, wantOpen = false, ctrlArmed = false, reconnectTimer;
  let sessionId = localStorage.getItem('thg_term_session') || '';
  const status = (txt, cls) => { const p = $('#term-status'); p.textContent = txt; p.className = 'pill ' + (cls || ''); };
  const send = (obj) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); };

  function init() {
    if (term) return;
    term = new Terminal({
      fontSize: +(localStorage.getItem('thg_font') || 14), cursorBlink: true, scrollback: 5000,
      fontFamily: 'ui-monospace, Menlo, Consolas, monospace', allowProposedApi: true,
      theme: { background: '#02060f', foreground: '#e6edf7', cursor: '#19e3b1', selectionBackground: '#1b2f55' },
    });
    fit = new FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open($('#term'));
    term.onData((d) => {
      if (exited) { exited = false; connect(true); return; }
      if (ctrlArmed && d.length === 1) {
        const c = d.toUpperCase().charCodeAt(0);
        if (c >= 64 && c <= 95) d = String.fromCharCode(c - 64);
        setCtrl(false);
      }
      send({ type: 'input', data: d });
    });
    term.onResize(({ cols, rows }) => send({ type: 'resize', cols, rows }));
    new ResizeObserver(() => { if (THG.current === 'terminal') fit.fit(); }).observe($('#term'));
    THG.setFont = (n) => { term.options.fontSize = n; fit.fit(); };
  }

  function setCtrl(on) { ctrlArmed = on; $('#key-ctrl').classList.toggle('on', on); }

  function connect(fresh) {
    clearTimeout(reconnectTimer);
    if (ws && ws.readyState <= 1) { ws.onclose = null; ws.close(); }
    if (fresh) { sessionId = ''; localStorage.removeItem('thg_term_session'); }
    fit.fit();
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    status('connecting');
    ws = new WebSocket(`${proto}//${location.host}/ws/terminal?session=${encodeURIComponent(sessionId)}&cols=${term.cols}&rows=${term.rows}`);
    ws.binaryType = 'arraybuffer';
    ws.onopen = () => { retry = 0; status('connected', 'ok'); };
    ws.onmessage = (e) => {
      if (typeof e.data !== 'string') { term.write(new Uint8Array(e.data)); return; }
      const m = JSON.parse(e.data);
      if (m.type === 'session') {
        sessionId = m.id; localStorage.setItem('thg_term_session', m.id);
        term.reset();
        status(m.reattached ? 'reattached' : 'new shell', 'ok');
      } else if (m.type === 'exit') {
        exited = true; sessionId = ''; localStorage.removeItem('thg_term_session');
        term.write('\r\n\x1b[33m[shell exited — press any key for a new shell]\x1b[0m\r\n');
        status('exited', 'bad');
      } else if (m.type === 'error') {
        term.write('\r\n\x1b[31m' + m.message + '\x1b[0m\r\n'); exited = true; status('error', 'bad');
      }
    };
    ws.onclose = (e) => {
      if (e.code === 4401) { location.href = '/login'; return; }
      if (exited || !wantOpen) return;
      status('reconnecting…', 'bad');
      reconnectTimer = setTimeout(() => connect(false), Math.min(1000 * 2 ** retry++, 10000));
    };
  }

  $('#term-new').onclick = () => { exited = false; connect(true); term.focus(); };
  $('#term-reconnect').onclick = () => { connect(false); term.focus(); };
  const bumpFont = (d) => { const n = Math.max(9, Math.min(28, (+localStorage.getItem('thg_font') || 14) + d)); localStorage.setItem('thg_font', n); THG.setFont(n); };
  $('#font-inc').onclick = () => bumpFont(1);
  $('#font-dec').onclick = () => bumpFont(-1);
  $('#key-ctrl').onclick = () => { setCtrl(!ctrlArmed); term.focus(); };
  $$('#keybar [data-seq]').forEach((b) => {
    b.addEventListener('pointerdown', (e) => e.preventDefault());  // keep the soft keyboard open
    b.onclick = () => { if (exited) { exited = false; connect(true); return; } send({ type: 'input', data: b.dataset.seq }); term.focus(); };
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && wantOpen && (!ws || ws.readyState > 1) && !exited) connect(false);
  });

  THG.views.terminal = {
    onShow() {
      init(); wantOpen = true;
      requestAnimationFrame(() => { fit.fit(); if (!ws || ws.readyState > 1) connect(false); term.focus(); });
    },
    onHide() { /* keep the socket (and the shell) alive while browsing other pages */ },
  };
})();
