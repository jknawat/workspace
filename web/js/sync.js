/**
 * GHSync — GitHub-based data sync for JK's tools
 * Stores tool data as JSON files in the GitHub repo via the GitHub API.
 * Settings (PAT, branch) stored in localStorage once per device.
 */
const GHSync = (() => {
  const OWNER = 'jknawat';
  const REPO  = 'workspace';

  const _get = k => localStorage.getItem(k);
  const _set = (k, v) => localStorage.setItem(k, v);

  const token  = () => _get('gh_pat') || '';
  const branch = () => _get('gh_branch') || 'tools';
  const shaKey = f => '_ghsha_' + f;

  const hdrs = () => ({
    'Authorization': `Bearer ${token()}`,
    'Accept': 'application/vnd.github+json',
    'Content-Type': 'application/json'
  });

  const apiUrl = f => `https://api.github.com/repos/${OWNER}/${REPO}/contents/data/${f}`;

  // Safe base64 encode/decode for Unicode (handles ฿ Thai chars etc.)
  const enc = s => btoa(unescape(encodeURIComponent(s)));
  const dec = s => decodeURIComponent(escape(atob(s.replace(/\s/g, ''))));

  /** Read a data file from GitHub. Returns parsed JS object or null. */
  async function read(file) {
    if (!token()) return null;
    try {
      const r = await fetch(`${apiUrl(file)}?ref=${branch()}`, { headers: hdrs() });
      if (!r.ok) return null;
      const d = await r.json();
      _set(shaKey(file), d.sha);
      return JSON.parse(dec(d.content));
    } catch { return null; }
  }

  /** Write a data file to GitHub. Returns true on success. */
  async function write(file, data) {
    if (!token()) return false;
    try {
      const body = {
        message: `sync: ${file}`,
        content: enc(JSON.stringify(data)),
        branch: branch()
      };
      const sha = _get(shaKey(file));
      if (sha) body.sha = sha;

      let r = await fetch(apiUrl(file), { method: 'PUT', headers: hdrs(), body: JSON.stringify(body) });

      // SHA conflict — re-read to get fresh SHA and retry once
      if (r.status === 409 || r.status === 422) {
        await read(file);
        body.sha = _get(shaKey(file));
        r = await fetch(apiUrl(file), { method: 'PUT', headers: hdrs(), body: JSON.stringify(body) });
      }

      if (r.ok) {
        const d = await r.json();
        if (d.content?.sha) _set(shaKey(file), d.content.sha);
        return true;
      }
      return false;
    } catch { return false; }
  }

  /** Test if the token is valid and has repo access. */
  async function verify() {
    if (!token()) return false;
    try {
      const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}`, {
        headers: { 'Authorization': `Bearer ${token()}`, 'Accept': 'application/vnd.github+json' }
      });
      return r.ok;
    } catch { return false; }
  }

  /**
   * Pull: fetch latest data from GitHub, save to localStorage.
   * Returns the data object, or null if no token / file not found / error.
   */
  async function pull(ghFile, lsKey) {
    const data = await read(ghFile);
    if (data !== null) _set(lsKey, JSON.stringify(data));
    return data;
  }

  /**
   * Push: read data from localStorage and write to GitHub.
   * statusCb called with: 'syncing' | 'ok' | 'error' | 'none'
   */
  async function push(ghFile, lsKey, statusCb) {
    if (!token()) { statusCb?.('none'); return; }
    statusCb?.('syncing');
    try {
      const raw = _get(lsKey);
      if (raw === null) { statusCb?.('error'); return; }
      const ok = await write(ghFile, JSON.parse(raw));
      statusCb?.(ok ? 'ok' : 'error');
    } catch { statusCb?.('error'); }
  }

  /**
   * Create a standard sync dot element and append it to a container.
   * Returns a setSyncDot(status) function.
   * status: 'none' | 'syncing' | 'ok' | 'error'
   */
  function createDot(container) {
    const dot = document.createElement('div');
    dot.id = 'sync-dot';
    dot.style.cssText = 'width:8px;height:8px;border-radius:50%;background:rgba(255,255,255,0.2);flex-shrink:0;transition:background 0.4s;cursor:default;';
    if (container) container.appendChild(dot);

    const colors = { none: 'rgba(255,255,255,0.2)', syncing: '#ffd60a', ok: '#30d158', error: '#ff453a' };
    const labels = { none: 'GitHub sync not set up', syncing: 'Syncing…', ok: 'Synced to GitHub', error: 'Sync failed — check token' };

    let blinkTimer;
    function set(status) {
      clearInterval(blinkTimer);
      dot.style.background = colors[status] || colors.none;
      dot.title = labels[status] || '';
      if (status === 'syncing') {
        let v = true;
        blinkTimer = setInterval(() => { dot.style.opacity = (v = !v) ? '1' : '0.3'; }, 400);
      } else {
        dot.style.opacity = '1';
      }
    }
    set(token() ? 'none' : 'none');
    return set;
  }

  return { read, write, verify, pull, push, createDot, token, branch };
})();
