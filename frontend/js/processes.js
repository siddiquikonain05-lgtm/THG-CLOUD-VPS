(function () {
  let timer;
  async function load() {
    const jobs = await api('/api/jobs');
    $('#job-list').innerHTML = jobs.length ? jobs.map(jobCard.full).join('') : '<p class="muted">No jobs yet. Run a script above or with <code>thgjob run python app.py</code>.</p>';
  }
  $('#job-form').onsubmit = guard(async (e) => {
    e.preventDefault();
    const j = await api('/api/jobs', { json: { command: $('#job-cmd').value, cwd: $('#job-cwd').value || null } });
    toast('Started job #' + j.id); $('#job-cmd').value = ''; load();
  });
  $('#job-list').onclick = guard(async (e) => {
    const btn = e.target.closest('button[data-act]'); if (!btn) return;
    const id = btn.closest('.job').dataset.id;
    btn.disabled = true;
    try {
      if (btn.dataset.act === 'logs') return THG.openLogs(+id);
      if (btn.dataset.act === 'stop') { await api(`/api/jobs/${id}/stop`, { method: 'POST' }); toast('Job stopped'); }
      if (btn.dataset.act === 'restart') { const j = await api(`/api/jobs/${id}/restart`, { method: 'POST' }); toast('Started new job #' + j.id); }
      if (btn.dataset.act === 'delete') {
        if (!confirm(`Delete history and logs of job #${id}?`)) return;
        await api(`/api/jobs/${id}`, { method: 'DELETE' }); toast('History deleted');
      }
      await load();
    } finally { btn.disabled = false; }
  });
  THG.views.processes = {
    onShow() { guard(load)(); timer = setInterval(guard(load), 3000); },
    onHide() { clearInterval(timer); },
  };
})();
