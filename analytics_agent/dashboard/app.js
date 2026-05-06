// ── State ─────────────────────────────────────────────────────────
let charts = {};
let latestStats = null;

// ── Tab Navigation ─────────────────────────────────────────────────
const TAB_TITLES = {
    overview:  'Overview',
    analytics: 'Analytics',
    tickets:   'Analyzed Tickets',
    brain:     'Agent Brain',
    chat:      'Chat with Agent'
};

document.querySelectorAll('.nav-item[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        // Toggle active nav
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        btn.classList.add('active');
        // Toggle panels
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        document.getElementById('panel-' + tab).classList.add('active');
        // Update topbar title
        document.getElementById('topbar-title').textContent = TAB_TITLES[tab];
        // Refresh charts when analytics tab is opened
        if (tab === 'analytics') Object.values(charts).forEach(c => c && c.resize());
        // Auto-load brain files when Brain tab is opened
        if (tab === 'brain' && !brainFilesLoaded) fetchBrainFiles();
    });
});

// ── Live Clock ─────────────────────────────────────────────────────
function updateClock() {
    document.getElementById('topbar-time').textContent = new Date().toLocaleTimeString();
}
setInterval(updateClock, 1000);
updateClock();

// ── Charts Init ────────────────────────────────────────────────────
function initCharts() {
    Chart.defaults.color = '#7a8ba4';
    Chart.defaults.font.family = "'Inter', sans-serif";

    const chartDefaults = (title, type) => ({
        type,
        data: { labels: [], datasets: [{ data: [], backgroundColor: PALETTE, borderWidth: 0, borderRadius: type === 'bar' ? 6 : 0 }] },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: type === 'doughnut' ? 'right' : 'bottom', labels: { color: '#eef2f8', boxWidth: 12, padding: 12 } },
                title:  { display: true, text: title, color: '#eef2f8', font: { size: 13, family: 'Outfit', weight: '600' }, padding: { bottom: 12 } }
            },
            cutout: type === 'doughnut' ? '65%' : undefined,
            scales: type === 'bar' ? {
                y: { grid: { color: 'rgba(255,255,255,0.04)' }, beginAtZero: true, ticks: { precision: 0 } },
                x: { grid: { display: false } }
            } : undefined
        }
    });

    charts.category   = new Chart(document.getElementById('categoryChart').getContext('2d'),   chartDefaults('Issues by Category', 'doughnut'));
    charts.sentiment  = new Chart(document.getElementById('sentimentChart').getContext('2d'),   chartDefaults('Sentiment Distribution', 'bar'));
    charts.priority   = new Chart(document.getElementById('priorityChart').getContext('2d'),    chartDefaults('Priority Breakdown', 'doughnut'));
    charts.escalation = new Chart(document.getElementById('escalationChart').getContext('2d'),  chartDefaults('Escalation Routing', 'bar'));
}

const PALETTE = [
    'rgba(59,130,246,0.85)',
    'rgba(139,92,246,0.85)',
    'rgba(16,185,129,0.85)',
    'rgba(245,158,11,0.85)',
    'rgba(239,68,68,0.85)',
    'rgba(236,72,153,0.85)',
];

function updateChart(chart, labels, data) {
    chart.data.labels = labels;
    chart.data.datasets[0].data = data;
    chart.update('none');
}

function formatIsoTime(isoValue) {
    if (!isoValue) return '—';
    return new Date(isoValue + 'Z').toLocaleTimeString();
}

function computeIntegrationHealth(state) {
    const fetchCode = state.last_fetch_status_code;
    const pushCode = state.last_push_status_code;
    const hasFetchError = !!state.last_fetch_error;
    const hasPushError = !!state.last_push_error && !String(state.last_push_error).startsWith('Skipped push');

    if (!fetchCode || hasFetchError || (typeof fetchCode === 'number' && fetchCode >= 400) || hasPushError || (typeof pushCode === 'number' && pushCode >= 400)) {
        return { level: 'red', label: 'Critical' };
    }

    if (state.using_mock_source || !state.api_key_configured) {
        return { level: 'yellow', label: 'Warning' };
    }

    return { level: 'green', label: 'Healthy' };
}

function renderIntegrationWidget(state) {
    const pill = document.getElementById('integration-pill');
    const summary = document.getElementById('integration-summary');
    const source = document.getElementById('integration-source');
    const fetch = document.getElementById('integration-fetch');
    const push = document.getElementById('integration-push');
    if (!pill || !summary || !source || !fetch || !push) return;

    const health = computeIntegrationHealth(state);
    pill.className = `integration-pill state-${health.level}`;
    pill.textContent = health.label;

    const modeHint = state.using_mock_source ? 'Mock/local source in use' : 'Production source in use';
    const keyHint = state.api_key_configured ? 'API key configured' : 'API key missing';
    summary.textContent = `${modeHint} • ${keyHint}`;

    source.textContent = `Source: ${state.using_mock_source ? 'Mock/Local' : 'Production'}`;
    fetch.textContent = `Fetch: ${state.last_fetch_status_code || '—'} @ ${formatIsoTime(state.last_fetch_at)}`;
    push.textContent = `Push: ${state.last_push_status_code || '—'} @ ${formatIsoTime(state.last_push_at)}`;
}

async function fetchIntegrationStatus() {
    try {
        const res = await fetch('/api/integration-status');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const state = await res.json();
        renderIntegrationWidget(state);
    } catch (e) {
        const pill = document.getElementById('integration-pill');
        const summary = document.getElementById('integration-summary');
        if (pill) {
            pill.className = 'integration-pill state-red';
            pill.textContent = 'Critical';
        }
        if (summary) summary.textContent = 'Integration telemetry endpoint unavailable';
    }
}

// ── Live Status ────────────────────────────────────────────────────
async function fetchLiveStatus() {
    try {
        const res   = await fetch('/api/live-status');
        const state = await res.json();

        // ── Status badge ─────────────────────────────────────────────
        const badge = document.getElementById('agent-status-badge');
        const mode  = state.mode || 'live';
        badge.className = 'agent-status-pill status-' + state.status;

        let statusLabel = state.status.charAt(0).toUpperCase() + state.status.slice(1);
        if (mode === 'backfilling') {
            statusLabel = `Backfilling (pg ${state.backfill_page || 1})`;
        }
        document.getElementById('agent-status-text').textContent = statusLabel;

        // ── KPI status card ──────────────────────────────────────────
        let kpiLabel = state.status.charAt(0).toUpperCase() + state.status.slice(1);
        if (mode === 'backfilling') kpiLabel = '📥 Backfilling';
        if (mode === 'live')        kpiLabel = '🟢 Live';
        document.getElementById('kpi-status').textContent = kpiLabel;

        // ── Pipeline label ───────────────────────────────────────────
        const proc = document.getElementById('current-processing');
        if (state.status === 'processing' && state.current_ticket) {
            proc.textContent = mode === 'backfilling'
                ? `Backfill: ${state.current_ticket}`
                : `Analyzing: ${state.current_ticket}`;
        } else if (state.status === 'polling') {
            proc.textContent = mode === 'backfilling'
                ? `Reading page ${state.backfill_page}…`
                : 'Checking for new tickets…';
        } else if (state.status === 'sleeping') {
            proc.textContent = mode === 'live' ? 'Live — watching for new tickets' : 'Idle';
        } else {
            proc.textContent = 'Starting…';
        }

        // ── Last check ───────────────────────────────────────────────
        if (state.last_check) {
            const d = new Date(state.last_check + 'Z');
            document.getElementById('live-last-check').textContent = 'Last check: ' + d.toLocaleTimeString();
        }

        // ── System Health ────────────────────────────────────────────
        if (state.system_health) {
            document.getElementById('val-cpu').textContent = state.system_health.cpu_percent + '%';
            document.getElementById('bar-cpu').style.width = state.system_health.cpu_percent + '%';

            document.getElementById('val-ram').textContent = state.system_health.ram_percent + '%';
            document.getElementById('bar-ram').style.width = state.system_health.ram_percent + '%';

            document.getElementById('val-disk').textContent = state.system_health.disk_percent + '%';
            document.getElementById('bar-disk').style.width = state.system_health.disk_percent + '%';

            document.getElementById('health-last-update').textContent = new Date().toLocaleTimeString();
        }

    } catch (e) {
        console.error('Status fetch error', e);
    }
}

// ── Stats ──────────────────────────────────────────────────────────
async function fetchStats() {
    try {
        const res  = await fetch('/api/stats');
        const data = await res.json();
        latestStats = data;

        // KPI cards
        document.getElementById('kpi-total').textContent    = data.total_analyzed;
        document.getElementById('kpi-critical').textContent = data.priorities?.CRITICAL || 0;
        document.getElementById('kpi-high').textContent     = data.priorities?.HIGH     || 0;

        // Charts
        updateChart(charts.category,   Object.keys(data.categories  || {}), Object.values(data.categories  || {}));
        updateChart(charts.sentiment,  Object.keys(data.sentiments  || {}), Object.values(data.sentiments  || {}));
        updateChart(charts.priority,   Object.keys(data.priorities  || {}), Object.values(data.priorities  || {}));
        updateChart(charts.escalation, Object.keys(data.escalations || {}), Object.values(data.escalations || {}));

        // Tickets table
        renderTicketsTable(data.recent_tickets || []);

        // Activity feed
        renderActivityFeed(data.recent_tickets || []);

        // Ticket count badge
        document.getElementById('ticket-count-badge').textContent = data.total_analyzed + ' records';

    } catch (e) {
        console.error('Stats fetch error', e);
    }
}

// ── Tickets Table ──────────────────────────────────────────────────
function priClass(p) {
    const m = { 'CRITICAL': 'pri-critical', 'HIGH': 'pri-high', 'MEDIUM': 'pri-medium', 'LOW': 'pri-low' };
    return m[(p || '').toUpperCase()] || 'pri-medium';
}

function senClass(s) {
    const m = { 'positive': 'sen-positive', 'neutral': 'sen-neutral', 'negative': 'sen-negative', 'frustrated': 'sen-frustrated' };
    return m[(s || '').toLowerCase()] || 'sen-neutral';
}

function renderTicketsTable(tickets) {
    const tbody = document.getElementById('tickets-tbody');
    tbody.innerHTML = '';
    if (!tickets.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#7a8ba4;padding:2rem">No tickets analyzed yet</td></tr>';
        return;
    }
    tickets.forEach(t => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="td-id">${t.ticket_id}</td>
            <td>${t.category || '—'}</td>
            <td><span class="badge ${priClass(t.priority)}">${t.priority || '—'}</span></td>
            <td><span class="badge ${senClass(t.sentiment)}">${t.sentiment || '—'}</span></td>
            <td>${t.escalate_to || '—'}</td>
            <td>${t.time_to_resolve_estimate || '—'}</td>
            <td class="td-trunc" title="${t.resolution_summary || ''}">${t.resolution_summary || '—'}</td>
            <td style="color:#7a8ba4;font-size:0.8rem;white-space:nowrap">${new Date(t.created_at + 'Z').toLocaleString()}</td>
        `;
        tbody.appendChild(tr);
    });
}

// ── Activity Feed ──────────────────────────────────────────────────
function renderActivityFeed(tickets) {
    const feed = document.getElementById('activity-feed');
    if (!tickets.length) {
        feed.innerHTML = '<div class="activity-empty">Waiting for data...</div>';
        return;
    }
    feed.innerHTML = '';
    tickets.slice(0, 8).forEach(t => {
        const item = document.createElement('div');
        item.className = 'activity-item ' + (t.priority || 'medium').toLowerCase();
        const timeStr = new Date(t.created_at + 'Z').toLocaleTimeString();
        item.innerHTML = `
            <span class="activity-id">${t.ticket_id}</span>
            <span class="badge ${priClass(t.priority)}">${t.priority || '?'}</span>
            <span class="activity-cat">${t.category || '—'}</span>
            <span class="activity-time">${timeStr}</span>
        `;
        feed.appendChild(item);
    });
}

// ── Settings Modal ─────────────────────────────────────────────────
const settingsModal  = document.getElementById('settings-modal');
const settingsBtn    = document.getElementById('settings-btn');
const closeModalBtn  = document.getElementById('close-modal-btn');
const saveSettingsBtn = document.getElementById('save-settings-btn');
const apiKeyInput    = document.getElementById('ticketing-api-key');
const agentKeyInput  = document.getElementById('agent-integration-key');
const generateAgentKeyBtn = document.getElementById('generate-agent-key-btn');
const copyAgentKeyBtn = document.getElementById('copy-agent-key-btn');
const revokeAgentKeyBtn = document.getElementById('revoke-agent-key-btn');
const toggleApiKeyBtn = document.getElementById('toggle-api-key-btn');
const toggleAgentKeyBtn = document.getElementById('toggle-agent-key-btn');
const saveStatus     = document.getElementById('save-status');
let generatedAgentKeyPlain = '';
let apiKeyUserEdited = false;   // true once the user types in the API key field
const AGENT_KEY_SESSION_STORAGE_KEY = 'generatedAgentKeyPlain';

function flashStatus(msg, color, ms = 2500) {
    saveStatus.textContent = msg;
    saveStatus.style.color = color;
    saveStatus.classList.add('visible');
    setTimeout(() => saveStatus.classList.remove('visible'), ms);
}

function fallbackCopyText(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;left:-9999px;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch {}
    document.body.removeChild(ta);
    return ok;
}

async function copyToClipboard(text) {
    // Try modern clipboard API first (works on HTTPS + localhost).
    // Falls back to execCommand for plain HTTP / LAN IPs.
    if (navigator.clipboard && window.isSecureContext) {
        try { await navigator.clipboard.writeText(text); return true; } catch {}
    }
    return fallbackCopyText(text);
}

function toggleModal(show) {
    settingsModal.classList.toggle('hidden', !show);
    if (show) {
        apiKeyUserEdited = false;
        fetchCurrentKey();
    }
}

async function fetchCurrentKey() {
    try {
        const res  = await fetch('/api/settings');
        const data = await res.json();
        apiKeyInput.value = data.has_key ? data.masked_key : '';
        apiKeyInput.type = 'password';  // reset to hidden on fresh load
        const storedPlain = sessionStorage.getItem(AGENT_KEY_SESSION_STORAGE_KEY) || '';
        generatedAgentKeyPlain = storedPlain;
        if (storedPlain) {
            agentKeyInput.value = storedPlain;
            agentKeyInput.type = 'text';
            toggleAgentKeyBtn.textContent = '🙈';
        } else {
            agentKeyInput.value = data.has_agent_integration_key ? data.masked_agent_integration_key : '';
            agentKeyInput.type = 'password';
            toggleAgentKeyBtn.textContent = '👁';
        }
    } catch {}
}

// ── Toggle show/hide ───────────────────────────────────────────────
function setupKeyToggle(toggleBtn, inputEl) {
    toggleBtn.addEventListener('click', () => {
        if (inputEl.type === 'password') {
            inputEl.type = 'text';
            toggleBtn.textContent = '🙈';
            toggleBtn.title = 'Hide';
        } else {
            inputEl.type = 'password';
            toggleBtn.textContent = '👁';
            toggleBtn.title = 'Show';
        }
    });
}
setupKeyToggle(toggleApiKeyBtn, apiKeyInput);
setupKeyToggle(toggleAgentKeyBtn, agentKeyInput);

// Track user edits to the API key so we don't reject a masked value
// that the user intentionally left untouched.
apiKeyInput.addEventListener('input', () => { apiKeyUserEdited = true; });

async function saveSettings() {
    const key = apiKeyInput.value.trim();

    // If user didn't edit the field, the masked value is still there — skip
    // validation and just close (nothing to save).
    if (!apiKeyUserEdited || (!key)) {
        if (!apiKeyUserEdited) {
            flashStatus('No changes to save', '#7a8ba4');
            return;
        }
        flashStatus('Please enter a valid key', '#ef4444');
        return;
    }

    // User typed something but it still contains mask chars — reject.
    if (key.includes('****')) {
        flashStatus('Clear the field and paste the full API key', '#ef4444');
        return;
    }

    try {
        saveSettingsBtn.textContent = 'Saving…';
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticketing_api_key: key })
        });
        if (!res.ok) throw new Error();
        flashStatus('✓ Saved successfully', '#10b981');
        setTimeout(() => toggleModal(false), 1500);
    } catch {
        flashStatus('Failed to save', '#ef4444');
    } finally {
        saveSettingsBtn.textContent = 'Save Changes';
    }
}

async function generateAgentKey() {
    try {
        generateAgentKeyBtn.textContent = 'Generating...';
        const res = await fetch('/api/settings/agent-key/generate', { method: 'POST' });
        const data = await res.json();
        if (!res.ok || data.status !== 'success') throw new Error();
        generatedAgentKeyPlain = data.agent_integration_key || '';
        sessionStorage.setItem(AGENT_KEY_SESSION_STORAGE_KEY, generatedAgentKeyPlain);
        // Show the full key in plain text so user can copy it immediately.
        agentKeyInput.value = generatedAgentKeyPlain;
        agentKeyInput.type = 'text';
        toggleAgentKeyBtn.textContent = '🙈';
        flashStatus('✓ Agent key generated — copy it now!', '#10b981', 4000);
    } catch {
        flashStatus('Failed to generate agent key', '#ef4444');
    } finally {
        generateAgentKeyBtn.textContent = 'Generate';
    }
}

async function revokeAgentKey() {
    try {
        revokeAgentKeyBtn.textContent = 'Revoking...';
        const res = await fetch('/api/settings/agent-key/revoke', { method: 'POST' });
        const data = await res.json();
        if (!res.ok || data.status !== 'success') throw new Error();
        generatedAgentKeyPlain = '';
        sessionStorage.removeItem(AGENT_KEY_SESSION_STORAGE_KEY);
        agentKeyInput.value = '';
        flashStatus('✓ Agent key revoked', '#10b981');
    } catch {
        flashStatus('Failed to revoke agent key', '#ef4444');
    } finally {
        revokeAgentKeyBtn.textContent = 'Revoke';
    }
}

async function copyAgentKey() {
    const value = (generatedAgentKeyPlain || '').trim();
    if (!value) {
        flashStatus('Generate a new key first — masked keys cannot be copied', '#f59e0b');
        return;
    }

    const ok = await copyToClipboard(value);
    if (ok) {
        flashStatus('✓ Agent key copied to clipboard', '#10b981');
    } else {
        // Last resort — select text in the field so user can Ctrl+C
        agentKeyInput.type = 'text';
        agentKeyInput.value = value;
        agentKeyInput.select();
        agentKeyInput.setSelectionRange(0, value.length);
        flashStatus('Auto-copy failed — key is selected, press Ctrl+C', '#f59e0b', 4000);
    }
}

settingsBtn.addEventListener('click', () => toggleModal(true));
closeModalBtn.addEventListener('click', () => toggleModal(false));
settingsModal.addEventListener('click', e => { if (e.target === settingsModal) toggleModal(false); });
saveSettingsBtn.addEventListener('click', saveSettings);
generateAgentKeyBtn.addEventListener('click', generateAgentKey);
copyAgentKeyBtn.addEventListener('click', copyAgentKey);
revokeAgentKeyBtn.addEventListener('click', revokeAgentKey);

// ── Agent Chat ─────────────────────────────────────────────────────
const chatMessages = document.getElementById('chat-messages');
const chatInput    = document.getElementById('chat-input');
const chatSendBtn  = document.getElementById('chat-send-btn');

function appendBubble(role, text) {
    const wrap    = document.createElement('div');
    wrap.className = `chat-bubble ${role === 'user' ? 'user-bubble' : 'agent-bubble'}`;

    const avatar   = document.createElement('div');
    avatar.className = 'bubble-avatar';
    avatar.textContent = role === 'user' ? 'YOU' : 'AI';

    const content  = document.createElement('div');
    content.className = 'bubble-content';
    content.textContent = text;

    wrap.appendChild(avatar);
    wrap.appendChild(content);
    chatMessages.appendChild(wrap);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return content; // return so we can append tokens to it
}

function showTyping() {
    const wrap = document.createElement('div');
    wrap.className = 'chat-bubble agent-bubble typing-bubble';
    wrap.id = 'typing-indicator';
    wrap.innerHTML = `<div class="bubble-avatar">AI</div><div class="bubble-content"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>`;
    chatMessages.appendChild(wrap);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function removeTyping() {
    document.getElementById('typing-indicator')?.remove();
}

async function sendChatMessage() {
    const msg = chatInput.value.trim();
    if (!msg) return;

    chatInput.value = '';
    chatSendBtn.disabled = true;
    appendBubble('user', msg);
    showTyping();

    // Create an empty agent bubble — tokens will be appended to it as they stream in
    let agentContentEl = null;

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg })
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const reader  = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer    = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // keep incomplete line in buffer

            for (const line of lines) {
                const normalized = line.replace(/\r$/, '');
                if (!normalized.startsWith('data: ')) continue;
                const raw = normalized.slice(6).trim();
                if (raw === '[DONE]') break;

                try {
                    const { token } = JSON.parse(raw);
                    if (!token || !String(token).trim()) continue;
                    if (agentContentEl === null) {
                        // First token — swap out the typing indicator for a real bubble
                        removeTyping();
                        agentContentEl = appendBubble('agent', '');
                    }
                    agentContentEl.textContent += token;
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                } catch {}
            }
        }
    } catch (err) {
        removeTyping();
        if (!agentContentEl) agentContentEl = appendBubble('agent', '');
        agentContentEl.textContent = '⚠️ Failed to reach the backend. Is the server running?';
    } finally {
        if (agentContentEl === null) {
            // Never received any tokens
            removeTyping();
            appendBubble('agent', '⚠️ No response received from the agent.');
        }
        chatSendBtn.disabled = false;
        chatInput.focus();
    }
}

function sendSuggested(btn) {
    chatInput.value = btn.textContent;
    sendChatMessage();
}

chatInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendChatMessage(); });

// ── Brain Editor ──────────────────────────────────────────────────
let brainFilesLoaded = false;
let brainActiveFile = null;
let brainOriginalContent = '';
let brainHasUnsaved = false;

const brainEditor = document.getElementById('brain-editor');
const brainFilenameText = document.getElementById('brain-filename-text');
const brainSaveBtn = document.getElementById('brain-save-btn');
const brainSaveStatus = document.getElementById('brain-save-status');
const brainUnsavedDot = document.getElementById('brain-unsaved-dot');
const brainFileMeta = document.getElementById('brain-file-meta');
const brainFilesContainer = document.getElementById('brain-files-container');

const BRAIN_FILE_ICONS = {
    'skill.md': '⚡',
    'memory.md': '💾',
    'thinking.md': '💭',
    'personality.md': '🎭',
    'rules.md': '📏',
};

function brainFlash(msg, color, ms = 2500) {
    brainSaveStatus.textContent = msg;
    brainSaveStatus.style.color = color;
    brainSaveStatus.classList.add('visible');
    setTimeout(() => brainSaveStatus.classList.remove('visible'), ms);
}

async function fetchBrainFiles() {
    try {
        const res = await fetch('/api/brain-files');
        const data = await res.json();
        brainFilesLoaded = true;
        renderBrainFileList(data.files || []);
    } catch (e) {
        brainFilesContainer.innerHTML = '<div class="brain-loading" style="color:var(--red)">Failed to load files</div>';
    }
}

function renderBrainFileList(files) {
    brainFilesContainer.innerHTML = '';
    if (!files.length) {
        brainFilesContainer.innerHTML = '<div class="brain-loading">No .md files found in Use/</div>';
        return;
    }
    files.forEach(f => {
        const btn = document.createElement('button');
        btn.className = 'brain-file-item';
        btn.dataset.filename = f.name;
        const icon = BRAIN_FILE_ICONS[f.name] || '📄';
        const sizeKB = (f.size_bytes / 1024).toFixed(1);
        btn.innerHTML = `
            <span class="brain-file-item-icon">${icon}</span>
            <span class="brain-file-item-name">${f.name}</span>
            <span class="brain-file-item-size">${sizeKB}k</span>
        `;
        btn.addEventListener('click', () => loadBrainFile(f.name));
        brainFilesContainer.appendChild(btn);
    });
}

async function loadBrainFile(filename) {
    // Warn if unsaved
    if (brainHasUnsaved && brainActiveFile) {
        if (!confirm(`Unsaved changes in ${brainActiveFile}. Discard?`)) return;
    }

    try {
        const res = await fetch(`/api/brain-files/${encodeURIComponent(filename)}`);
        const data = await res.json();
        if (data.error) {
            brainFlash(data.error, '#ef4444');
            return;
        }

        brainActiveFile = filename;
        brainOriginalContent = data.content;
        brainEditor.value = data.content;
        brainEditor.disabled = false;
        brainSaveBtn.disabled = false;
        brainHasUnsaved = false;
        brainUnsavedDot.classList.add('hidden');

        const icon = BRAIN_FILE_ICONS[filename] || '📄';
        brainFilenameText.textContent = filename;
        document.querySelector('.brain-file-icon').textContent = icon;

        const sizeKB = (data.size_bytes / 1024).toFixed(1);
        const modified = data.modified_at ? new Date(data.modified_at + 'Z').toLocaleString() : '—';
        brainFileMeta.textContent = `${sizeKB} KB • Modified: ${modified}`;

        // Highlight active file in list
        document.querySelectorAll('.brain-file-item').forEach(el => {
            el.classList.toggle('active', el.dataset.filename === filename);
        });
    } catch (e) {
        brainFlash('Failed to load file', '#ef4444');
    }
}

async function saveBrainFile() {
    if (!brainActiveFile) return;
    const content = brainEditor.value;
    try {
        brainSaveBtn.textContent = 'Saving…';
        brainSaveBtn.disabled = true;
        const res = await fetch(`/api/brain-files/${encodeURIComponent(brainActiveFile)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        });
        const data = await res.json();
        if (data.error) {
            brainFlash('Save failed: ' + data.error, '#ef4444');
        } else {
            brainOriginalContent = content;
            brainHasUnsaved = false;
            brainUnsavedDot.classList.add('hidden');
            const sizeKB = (data.size_bytes / 1024).toFixed(1);
            const modified = data.modified_at ? new Date(data.modified_at + 'Z').toLocaleString() : '—';
            brainFileMeta.textContent = `${sizeKB} KB • Modified: ${modified}`;
            brainFlash('✓ Saved', '#10b981');
            // Refresh file list sizes
            fetchBrainFiles();
        }
    } catch (e) {
        brainFlash('Save failed', '#ef4444');
    } finally {
        brainSaveBtn.textContent = 'Save';
        brainSaveBtn.disabled = false;
    }
}

// Track unsaved changes
brainEditor.addEventListener('input', () => {
    if (!brainActiveFile) return;
    brainHasUnsaved = brainEditor.value !== brainOriginalContent;
    brainUnsavedDot.classList.toggle('hidden', !brainHasUnsaved);
});

// Ctrl+S to save
brainEditor.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (brainActiveFile) saveBrainFile();
    }
});

brainSaveBtn.addEventListener('click', saveBrainFile);

// ── Bootstrap ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    fetchLiveStatus();
    fetchStats();
    fetchIntegrationStatus();
    setInterval(fetchLiveStatus, 2000);
    setInterval(fetchStats, 6000);
    setInterval(fetchIntegrationStatus, 6000);
});
