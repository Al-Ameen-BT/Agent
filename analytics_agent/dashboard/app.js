// ── State ─────────────────────────────────────────────────────────
let charts = {};
let latestStats = null;

// ── Tab Navigation ─────────────────────────────────────────────────
const TAB_TITLES = {
    overview:  'Overview',
    analytics: 'Analytics',
    tickets:   'Analyzed Tickets',
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
const saveStatus     = document.getElementById('save-status');

function toggleModal(show) {
    settingsModal.classList.toggle('hidden', !show);
    if (show) fetchCurrentKey();
}

async function fetchCurrentKey() {
    try {
        const res  = await fetch('/api/settings');
        const data = await res.json();
        apiKeyInput.value = data.has_key ? data.masked_key : '';
    } catch {}
}

async function saveSettings() {
    const key = apiKeyInput.value.trim();
    if (!key || key.includes('****')) {
        saveStatus.textContent = 'Please enter a valid key';
        saveStatus.style.color = '#ef4444';
        saveStatus.classList.add('visible');
        setTimeout(() => saveStatus.classList.remove('visible'), 2500);
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
        saveStatus.textContent = '✓ Saved successfully';
        saveStatus.style.color = '#10b981';
        saveStatus.classList.add('visible');
        setTimeout(() => { saveStatus.classList.remove('visible'); toggleModal(false); }, 1500);
    } catch {
        saveStatus.textContent = 'Failed to save';
        saveStatus.style.color = '#ef4444';
        saveStatus.classList.add('visible');
    } finally {
        saveSettingsBtn.textContent = 'Save Changes';
    }
}

settingsBtn.addEventListener('click', () => toggleModal(true));
closeModalBtn.addEventListener('click', () => toggleModal(false));
settingsModal.addEventListener('click', e => { if (e.target === settingsModal) toggleModal(false); });
saveSettingsBtn.addEventListener('click', saveSettings);

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
                if (!line.startsWith('data: ')) continue;
                const raw = line.slice(6).trim();
                if (raw === '[DONE]') break;

                try {
                    const { token } = JSON.parse(raw);
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
