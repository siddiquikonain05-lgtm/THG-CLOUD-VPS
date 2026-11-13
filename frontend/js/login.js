document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = document.getElementById('err');
  err.textContent = '';
  const btn = e.target.querySelector('button');
  btn.disabled = true;
  try {
    const r = await fetch('/api/auth/login', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: document.getElementById('u').value, password: document.getElementById('p').value }),
    });
    if (r.ok) { location.href = '/'; return; }
    let msg = 'Sign-in failed';
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    err.textContent = msg;
  } catch (_) { err.textContent = 'Network error'; }
  btn.disabled = false;
});
