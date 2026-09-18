function sidecarUrl(path) {
  return new URL(`../../${String(path).replace(/^\//, '')}`, window.location.href).toString();
}

const api = {
  async json(path, options = {}) {
    const response = await fetch(sidecarUrl(path), {
      credentials: 'omit',
      headers: { 'content-type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(body.detail || body.error || 'request_failed');
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return body;
  },
};

function mountSidebar() {
  const list = document.getElementById('list');
  const status = document.getElementById('status');
  const form = document.getElementById('create');
  const prompt = document.getElementById('prompt');

  async function refresh() {
    try {
      const health = await api.json('/health');
      if (status) status.dataset.state = health.ok ? 'ready' : 'offline';
      const payload = await api.json('/agents');
      const agents = payload.items || payload.agents || [];
      if (!list) return;
      list.replaceChildren();
      if (!agents.length) {
        const empty = document.createElement('p');
        empty.className = 'muted';
        empty.textContent = 'No local agents yet.';
        list.appendChild(empty);
        return;
      }
      for (const agent of agents) {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'row';
        row.textContent = agent.title || agent.agent_id;
        row.addEventListener('click', () => {
          window.parent.postMessage({ type: 'cursor-agents-open', agentId: agent.agent_id }, '*');
        });
        list.appendChild(row);
      }
    } catch (_error) {
      if (status) status.dataset.state = 'offline';
    }
  }

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = String(prompt?.value || '').trim();
    if (!text) return;
    await api.json('/agents', { method: 'POST', body: JSON.stringify({ prompt: text }) });
    if (prompt) prompt.value = '';
    refresh();
  });
  refresh();
  window.setInterval(refresh, 8000);
}

function mountOverlay() {
  const panel = document.getElementById('panel');
  const title = document.getElementById('title');
  const canvas = document.getElementById('canvas');
  const send = document.getElementById('send');
  const prompt = document.getElementById('prompt');
  let agentId = new URLSearchParams(window.location.search).get('agent') || '';

  async function loadSession() {
    if (!agentId || !panel) return;
    try {
      const session = await api.json(`/agents/${agentId}/session`);
      title && (title.textContent = session.agent?.title || 'Agent');
      const messages = session.messages || [];
      panel.textContent = messages.map((row) => `${row.role}: ${JSON.stringify(row.blocks || row)}`).join('\n\n') || 'Empty session.';
    } catch (error) {
      if (error.status === 409) {
        await api.json(`/agents/${agentId}/fork`, {
          method: 'POST',
          body: JSON.stringify({ messages: [{ role: 'user', blocks: [{ type: 'text', text: 'Fork from IDE' }] }] }),
        });
        loadSession();
        return;
      }
      panel.textContent = String(error.message || error);
    }
    try {
      const events = await api.json('/canvas/events');
      const first = (events.events || [])[0];
      if (first && canvas) {
        canvas.style.display = 'block';
        canvas.textContent = first.preview || first.path;
      }
    } catch (_error) {
      /* canvases are optional */
    }
  }

  send?.addEventListener('click', async () => {
    const text = String(prompt?.value || '').trim();
    if (!text || !agentId) return;
    try {
      await api.json(`/agents/${agentId}/send`, { method: 'POST', body: JSON.stringify({ prompt: text }) });
      if (prompt) prompt.value = '';
      loadSession();
    } catch (error) {
      if (panel) panel.textContent = String(error.message || error);
    }
  });
  loadSession();
}

window.cursorAgentsUi = { mountSidebar, mountOverlay };
