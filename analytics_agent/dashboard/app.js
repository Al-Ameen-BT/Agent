// Chart instances
let categoryChart = null;
let sentimentChart = null;

// DOM Elements
const statusBadge = document.getElementById('agent-status-badge');
const statusText = document.getElementById('agent-status-text');
const currentProcessing = document.getElementById('current-processing');
const totalProcessed = document.getElementById('total-processed');
const lastCheck = document.getElementById('last-check');
const recentTicketsBody = document.getElementById('recent-tickets-body');

// Chart Colors
const colors = {
    blue: 'rgba(59, 130, 246, 0.8)',
    purple: 'rgba(139, 92, 246, 0.8)',
    green: 'rgba(16, 185, 129, 0.8)',
    red: 'rgba(239, 68, 68, 0.8)',
    orange: 'rgba(245, 158, 11, 0.8)'
};

const bgColors = [colors.blue, colors.purple, colors.green, colors.orange, colors.red];

// Initialize Charts
function initCharts() {
    Chart.defaults.color = '#8a9bb2';
    Chart.defaults.font.family = "'Inter', sans-serif";
    
    const ctxCat = document.getElementById('categoryChart').getContext('2d');
    categoryChart = new Chart(ctxCat, {
        type: 'doughnut',
        data: { labels: [], datasets: [{ data: [], backgroundColor: bgColors, borderWidth: 0 }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right', labels: { color: '#f0f4f8' } },
                title: { display: true, text: 'Issues by Category', color: '#f0f4f8', font: { size: 16, family: 'Outfit' } }
            },
            cutout: '70%'
        }
    });

    const ctxSent = document.getElementById('sentimentChart').getContext('2d');
    sentimentChart = new Chart(ctxSent, {
        type: 'bar',
        data: { labels: [], datasets: [{ label: 'Tickets', data: [], backgroundColor: colors.purple, borderRadius: 6 }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                title: { display: true, text: 'Ticket Sentiment Analysis', color: '#f0f4f8', font: { size: 16, family: 'Outfit' } }
            },
            scales: {
                y: { grid: { color: 'rgba(255,255,255,0.05)' }, beginAtZero: true },
                x: { grid: { display: false } }
            }
        }
    });
}

function updateLiveStatus(state) {
    // Update Badge
    statusBadge.className = 'agent-status status-' + state.status;
    statusText.innerText = state.status.charAt(0).toUpperCase() + state.status.slice(1);
    
    // Update Processing Visual
    if (state.status === 'processing' && state.current_ticket) {
        currentProcessing.innerHTML = `Analyzing: <br><strong>${state.current_ticket}</strong>`;
        currentProcessing.style.color = '#fff';
    } else if (state.status === 'polling') {
        currentProcessing.innerHTML = `Scanning Ticketing API...`;
        currentProcessing.style.color = '#8a9bb2';
    } else {
        currentProcessing.innerHTML = `Idle`;
        currentProcessing.style.color = '#8a9bb2';
    }

    if (state.last_check) {
        const d = new Date(state.last_check + 'Z');
        lastCheck.innerText = d.toLocaleTimeString();
    }
}

function updateStats(data) {
    // Total Processed
    totalProcessed.innerText = data.total_analyzed;

    // Categories
    const catKeys = Object.keys(data.categories);
    const catVals = Object.values(data.categories);
    categoryChart.data.labels = catKeys;
    categoryChart.data.datasets[0].data = catVals;
    categoryChart.update();

    // Sentiments
    const sentKeys = Object.keys(data.sentiments);
    const sentVals = Object.values(data.sentiments);
    sentimentChart.data.labels = sentKeys;
    sentimentChart.data.datasets[0].data = sentVals;
    sentimentChart.update();

    // Recent Tickets
    recentTicketsBody.innerHTML = '';
    data.recent_tickets.forEach(ticket => {
        const tr = document.createElement('tr');
        
        let sentClass = 'badge-neutral';
        const sentLower = ticket.sentiment.toLowerCase();
        if (sentLower.includes('positive')) sentClass = 'badge-positive';
        if (sentLower.includes('negative')) sentClass = 'badge-negative';
        if (sentLower.includes('frustrat')) sentClass = 'badge-frustrated';

        tr.innerHTML = `
            <td style="font-family:monospace; color:#3b82f6">${ticket.ticket_id}</td>
            <td>${ticket.category}</td>
            <td><span class="badge ${sentClass}">${ticket.sentiment}</span></td>
            <td style="max-width:300px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${ticket.resolution_summary}">
                ${ticket.resolution_summary}
            </td>
            <td style="color:#8a9bb2; font-size:0.85rem">${new Date(ticket.created_at + 'Z').toLocaleString()}</td>
        `;
        recentTicketsBody.appendChild(tr);
    });
}

async function fetchStatus() {
    try {
        const res = await fetch('/api/live-status');
        const state = await res.json();
        updateLiveStatus(state);
    } catch (e) {
        console.error("Error fetching status", e);
    }
}

async function fetchStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        updateStats(data);
    } catch (e) {
        console.error("Error fetching stats", e);
    }
}

// Settings Modal Logic
const settingsModal = document.getElementById('settings-modal');
const settingsBtn = document.getElementById('settings-btn');
const closeModalBtn = document.getElementById('close-modal-btn');
const saveSettingsBtn = document.getElementById('save-settings-btn');
const apiKeyInput = document.getElementById('ticketing-api-key');
const saveStatus = document.getElementById('save-status');

function toggleModal(show) {
    if (show) {
        settingsModal.classList.remove('hidden');
        fetchSettings(); // refresh value on open
    } else {
        settingsModal.classList.add('hidden');
        saveStatus.classList.remove('visible');
    }
}

async function fetchSettings() {
    try {
        const res = await fetch('/api/settings');
        if (res.ok) {
            const data = await res.json();
            if (data.has_key) {
                apiKeyInput.value = data.masked_key;
            } else {
                apiKeyInput.value = '';
            }
        }
    } catch (e) {
        console.error("Error fetching settings", e);
    }
}

async function saveSettings() {
    const newKey = apiKeyInput.value.trim();
    if (!newKey) return;

    // Don't save if it's just the masked placeholder
    if (newKey.includes('****')) {
        saveStatus.innerText = 'Please enter a new valid key';
        saveStatus.style.color = 'var(--accent-red)';
        saveStatus.classList.add('visible');
        setTimeout(() => saveStatus.classList.remove('visible'), 3000);
        return;
    }

    try {
        saveSettingsBtn.innerText = 'Saving...';
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticketing_api_key: newKey })
        });

        if (res.ok) {
            saveStatus.innerText = 'Saved Successfully!';
            saveStatus.style.color = 'var(--accent-green)';
            saveStatus.classList.add('visible');
            setTimeout(() => {
                saveStatus.classList.remove('visible');
                toggleModal(false);
            }, 1500);
        } else {
            throw new Error('Save failed');
        }
    } catch (e) {
        console.error("Error saving settings", e);
        saveStatus.innerText = 'Failed to save';
        saveStatus.style.color = 'var(--accent-red)';
        saveStatus.classList.add('visible');
    } finally {
        saveSettingsBtn.innerText = 'Save Changes';
    }
}

settingsBtn.addEventListener('click', () => toggleModal(true));
closeModalBtn.addEventListener('click', () => toggleModal(false));
settingsModal.addEventListener('click', (e) => {
    if (e.target === settingsModal) toggleModal(false);
});
saveSettingsBtn.addEventListener('click', saveSettings);

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    
    // Initial fetch
    fetchStatus();
    fetchStats();

    // Polling loops
    setInterval(fetchStatus, 1000); // 1s for live flow animations
    setInterval(fetchStats, 5000);  // 5s for DB aggregations
});
