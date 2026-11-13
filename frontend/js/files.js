(function () {
  let path = localStorage.getItem('thg_path') || 'projects';
  const join = (a, b) => (a ? a + '/' + b : b);

  async function load(p) {
    if (p !== undefined) path = p;
    let r;
    try { r = await api('/api/files/list?path=' + encodeURIComponent(path)); }
    catch (e) { if (path !== 'projects') { path = 'projects'; return load(); } throw e; }
    path = r.path; localStorage.setItem('thg_path', path);
    const parts = path ? path.split('/') : [];
    $('#crumbs').innerHTML = '<a data-p="">/data</a>' + parts.map((s, i) => `<span>/</span><a data-p="${esc(parts.slice(0, i + 1).join('/'))}">${esc(s)}</a>`).join('');
    $$('#crumbs a').forEach((a) => { a.onclick = () => guard(load)(a.dataset.p); });
    const rows = [];
    if (r.parent !== null) rows.push(`<div class="frow"><span class="nm dir" data-open="${esc(r.parent)}">⬑ ..</span></div>`);
    r.items.forEach((i) => {
      rows.push(`<div class="frow" data-path="${esc(i.path)}" data-dir="${i.is_dir ? 1 : 0}" data-zip="${i.is_zip ? 1 : 0}">
        <span class="nm ${i.is_dir ? 'dir' : ''}" ${i.is_dir ? `data-open="${esc(i.path)}"` : ''}>${i.is_dir ? '📁 ' : ''}${esc(i.name)}</span>
        <span class="meta">${i.is_dir ? 'folder' : fmtBytes(i.size)} · ${fmtTime(i.mtime)}</span>
        <div class="acts">
          <a class="btn small" href="/api/files/download?path=${encodeURIComponent(i.path)}" download>${i.is_dir ? 'Download ZIP' : 'Download'}</a>
          <button class="btn small" data-act="rename">Rename</button>
          ${i.is_zip ? '<button class="btn small primary" data-act="extract-here">Extract Here</button><button class="btn small primary" data-act="extract-new">Extract to New Folder</button>' : ''}
          <button class="btn small danger" data-act="delete">${i.is_zip ? 'Delete ZIP' : 'Delete'}</button>
        </div></div>`);
    });
    $('#f-list').innerHTML = rows.join('') || '<div class="frow muted">Empty folder</div>';
  }

  $('#f-list').onclick = guard(async (e) => {
    const open = e.target.closest('[data-open]');
    if (open) return load(open.dataset.open);
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const row = btn.closest('.frow'), p = row.dataset.path, name = p.split('/').pop();
    switch (btn.dataset.act) {
      case 'rename': {
        const n = prompt('New name', name);
        if (n && n !== name) { await api('/api/files/rename', { json: { path: p, new_name: n } }); toast('Renamed'); load(); }
        break;
      }
      case 'delete':
        if (confirm(`Delete ${row.dataset.dir === '1' ? 'folder' : 'file'} "${name}"? This cannot be undone.`)) {
          await api('/api/files/delete', { json: { path: p } }); toast('Deleted'); load();
        }
        break;
      case 'extract-here':
      case 'extract-new': {
        btn.disabled = true;
        const r = await api('/api/files/extract', { json: { path: p, mode: btn.dataset.act === 'extract-here' ? 'here' : 'new_folder' } });
        toast(`Extracted ${r.files} files to /${r.extracted_to}`); load();
        break;
      }
    }
  });

  $('#f-mkdir').onclick = guard(async () => {
    const n = prompt('Folder name'); if (!n) return;
    await api('/api/files/mkdir', { json: { path: join(path, n) } }); load();
  });
  $('#f-touch').onclick = guard(async () => {
    const n = prompt('File name'); if (!n) return;
    await api('/api/files/touch', { json: { path: join(path, n) } }); load();
  });
  $('#f-refresh').onclick = guard(() => load());
  $('#f-upload').onclick = () => $('#f-input').click();
  $('#f-upload-dir').onclick = () => $('#f-input-dir').click();

  function sendBatch(items, base, total, done) {
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.append('path', path);
      items.forEach((it) => { fd.append('relpaths', it.rel); fd.append('files', it.file, it.file.name); });
      const x = new XMLHttpRequest();
      x.open('POST', '/api/files/upload');
      x.setRequestHeader('X-CSRF-Token', THG.csrf);
      x.upload.onprogress = (e) => {
        const pct = Math.round(((base + e.loaded) / total) * 100);
        const bar = $('#upload-progress');
        bar.firstElementChild.style.width = pct + '%';
        bar.lastElementChild.textContent = `Uploading ${pct}% (${done + 1}/${done + items.length}+)`;
      };
      x.onload = () => {
        if (x.status < 300) return resolve();
        let m = 'Upload failed (' + x.status + ')';
        try { m = JSON.parse(x.responseText).detail || m; } catch (_) {}
        reject(new Error(m));
      };
      x.onerror = () => reject(new Error('Network error during upload'));
      x.send(fd);
    });
  }

  async function upload(fileList) {
    const items = [...fileList].map((f) => ({ file: f, rel: f.webkitRelativePath || f.name }));
    if (!items.length) return;
    const total = items.reduce((s, i) => s + i.file.size, 0) || 1;
    const bar = $('#upload-progress'); bar.hidden = false;
    let base = 0, done = 0;
    try {
      while (items.length) {  // batches: <=100 files and ~48 MB each
        const batch = []; let size = 0;
        while (items.length && batch.length < 100 && (size === 0 || size + items[0].file.size < 48 * 1024 * 1024)) {
          const it = items.shift(); batch.push(it); size += it.file.size;
        }
        await sendBatch(batch, base, total, done);
        base += size; done += batch.length;
      }
      toast('Upload complete');
    } finally { bar.hidden = true; load(); }
  }
  $('#f-input').onchange = guard(async (e) => { await upload(e.target.files); e.target.value = ''; });
  $('#f-input-dir').onchange = guard(async (e) => { await upload(e.target.files); e.target.value = ''; });

  THG.views.files = { onShow: guard(() => load()) };
})();
