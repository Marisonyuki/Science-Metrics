// frontend/app.js
let db = null;
let publicationsChart = null;
let citationsChart = null;
let isAdmin = false;

// API бэкенда (Python)
const API_URL = '/api';

// Инициализация базы данных (SQLite в браузере)
async function initDatabase() {
    const SQL = await initSqlJs({
        locateFile: file => `https://cdn.jsdelivr.net/npm/sql.js@1.14.0/dist/${file}`
    });
    
    db = new SQL.Database();
    
    db.run(`
        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY,
            name TEXT,
            employees_count INTEGER,
            publications INTEGER,
            citations INTEGER,
            h_index REAL
        )
    `);
    
    await loadDataFromBackend();
    await updateDashboardFromDatabase();
}

async function loadDataFromBackend() {
    const yearFilter = document.getElementById('yearFilter').value;
    try {
        const response = await fetch(`${API_URL}/departments?year=${yearFilter}`);
        if (!response.ok) throw new Error('Ошибка загрузки');
        
        const sections = await response.json();
        console.log('Загружено разделов:', sections.length);
        
        db.run('DELETE FROM sections');
        
        sections.forEach(section => {
            db.run(`
                INSERT INTO sections (id, name, employees_count, publications, citations, h_index)
                VALUES (?, ?, ?, ?, ?, ?)
            `, [section.id, section.name, section.employees_count || 0, 
                 section.publications, section.citations, section.h_index]);
        });
        
        return sections;
    } catch (error) {
        console.error('Ошибка загрузки данных:', error);
        showNotification('❌ Ошибка загрузки данных с сервера', 'error');
        return [];
    }
}

async function updateDashboardFromDatabase() {
    const result = db.exec(`
        SELECT name, employees_count, publications, citations, h_index 
        FROM sections
        ORDER BY citations DESC
    `);
    
    if (result.length === 0 || result[0].values.length === 0) {
        showEmptyState();
        return;
    }
    
    const sections = result[0].values.map(row => ({
        name: row[0],
        employees_count: row[1],
        publications: row[2],
        citations: row[3],
        h_index: row[4]
    }));
    
    // Только 3 карточки
    const totalPubs = sections.reduce((sum, s) => sum + s.publications, 0);
    const totalCits = sections.reduce((sum, s) => sum + s.citations, 0);
    const avgHIndex = (sections.reduce((sum, s) => sum + s.h_index, 0) / sections.length).toFixed(1);
    
    document.getElementById('totalPubs').textContent = totalPubs;
    document.getElementById('totalCits').textContent = totalCits;
    document.getElementById('avgHIndex').textContent = avgHIndex;
    
    const tableBody = document.getElementById('tableBody');
    tableBody.innerHTML = sections.map(s => `
        <tr>
            <td><strong>${s.name}</strong></td>
            <td>${s.employees_count || 0}</td>
            <td>${s.publications}</td>
            <td>${s.citations}</td>
            <td>${s.h_index}</td>
        </tr>
    `).join('');
    
    updateCharts(sections);
}

function updateCharts(sections) {
    const names = sections.map(s => s.name.length > 30 ? s.name.substring(0, 27) + '...' : s.name);
    const publications = sections.map(s => s.publications);
    const citations = sections.map(s => s.citations);
    
    if (publicationsChart) publicationsChart.destroy();
    if (citationsChart) citationsChart.destroy();
    
    const ctx1 = document.getElementById('publicationsChart').getContext('2d');
    const ctx2 = document.getElementById('citationsChart').getContext('2d');
    
    publicationsChart = new Chart(ctx1, {
        type: 'bar',
        data: { labels: names, datasets: [{ label: 'Публикации', data: publications, backgroundColor: 'rgba(102, 126, 234, 0.7)' }] },
        options: { responsive: true }
    });
    
    citationsChart = new Chart(ctx2, {
        type: 'line',
        data: { labels: names, datasets: [{ label: 'Цитирования', data: citations, borderColor: '#764ba2', tension: 0.3, fill: true }] },
        options: { responsive: true }
    });
}

function showEmptyState() {
    document.getElementById('totalPubs').textContent = '0';
    document.getElementById('totalCits').textContent = '0';
    document.getElementById('avgHIndex').textContent = '0';
    document.getElementById('tableBody').innerHTML = '<tr><td colspan="5" style="text-align:center;">Нет данных. Нажмите "Обновить данные" для загрузки.</tr></tr>';
    
    if (publicationsChart) publicationsChart.destroy();
    if (citationsChart) citationsChart.destroy();
    
    const ctx1 = document.getElementById('publicationsChart').getContext('2d');
    const ctx2 = document.getElementById('citationsChart').getContext('2d');
    
    publicationsChart = new Chart(ctx1, {
        type: 'bar',
        data: { labels: ['Нет данных'], datasets: [{ label: 'Публикации', data: [0] }] },
        options: { responsive: true }
    });
    
    citationsChart = new Chart(ctx2, {
        type: 'line', 
        data: { labels: ['Нет данных'], datasets: [{ label: 'Цитирования', data: [0] }] },
        options: { responsive: true }
    });
}

let isUpdating = false;

async function runScrapingAndUpdate() {
    console.log("🔵 Кнопка нажата, запускаем парсинг...");
    
    if (!isAdmin) {
        showNotification('⛔ Только администратор может обновлять данные!', 'error');
        return;
    }
    
    if (isUpdating) {
        showNotification('⚠️ Парсинг уже выполняется, подождите...', 'warning');
        return;
    }
    
    isUpdating = true;
    const refreshBtn = document.getElementById('refreshBtn');
    const originalText = refreshBtn.textContent;
    
    try {
        refreshBtn.textContent = '🕷️ Парсинг...';
        refreshBtn.disabled = true;
        showScrapingProgress();
        
        const startResponse = await fetch(`${API_URL}/scrape`, { method: 'POST' });
        if (!startResponse.ok) throw new Error('Ошибка запуска парсинга');
        
        showNotification('🚀 Парсинг запущен!', 'info');
        
        const interval = setInterval(async () => {
            try {
                const status = await fetch(`${API_URL}/scrape/status`).then(r => r.json());
                
                const progressFill = document.getElementById('progressFill');
                const statusMessage = document.getElementById('statusMessage');
                
                if (progressFill) progressFill.style.width = `${status.progress}%`;
                if (statusMessage) statusMessage.textContent = status.message;
                
                if (!status.is_running) {
                    clearInterval(interval);
                    await loadDataFromBackend();
                    await updateDashboardFromDatabase();
                    refreshBtn.textContent = originalText;
                    refreshBtn.disabled = false;
                    hideScrapingProgress();
                    isUpdating = false;
                    showNotification(`✅ Парсинг завершён!`, 'success');
                }
            } catch (error) {
                clearInterval(interval);
                refreshBtn.textContent = originalText;
                refreshBtn.disabled = false;
                hideScrapingProgress();
                isUpdating = false;
                showNotification('❌ Ошибка', 'error');
            }
        }, 1000);
        
    } catch (error) {
        showNotification('❌ Ошибка: ' + error.message, 'error');
        refreshBtn.textContent = originalText;
        refreshBtn.disabled = false;
        hideScrapingProgress();
        isUpdating = false;
    }
}

function showScrapingProgress() {
    let div = document.getElementById('scrapingStatus');
    if (!div) {
        div = document.createElement('div');
        div.id = 'scrapingStatus';
        div.innerHTML = `<div class="progress-bar"><div id="progressFill" class="progress-fill"></div></div><div id="statusMessage" style="margin-top: 10px; text-align: center;"></div>`;
        document.querySelector('.controls').after(div);
        
        if (!document.querySelector('#progressStyles')) {
            const style = document.createElement('style');
            style.id = 'progressStyles';
            style.textContent = `.progress-bar { width: 100%; height: 20px; background: #e9ecef; border-radius: 10px; overflow: hidden; margin-top: 15px; } .progress-fill { height: 100%; background: linear-gradient(90deg, #28a745, #20c997); width: 0%; transition: width 0.3s ease; }`;
            document.head.appendChild(style);
        }
    }
    div.style.display = 'block';
}

function hideScrapingProgress() {
    const div = document.getElementById('scrapingStatus');
    if (div) div.style.display = 'none';
}

function showNotification(message, type = 'info') {
    const oldNotifications = document.querySelectorAll('.notification');
    oldNotifications.forEach(n => n.remove());
    
    const notification = document.createElement('div');
    const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
    notification.innerHTML = `${icons[type] || '📢'} ${message}`;
    notification.style.cssText = `
        position: fixed; top: 20px; right: 20px; padding: 12px 24px;
        border-radius: 8px; font-weight: 500; z-index: 10000;
        animation: slideInRight 0.3s ease; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        background: ${type === 'success' ? '#28a745' : type === 'error' ? '#dc3545' : type === 'warning' ? '#ffc107' : '#17a2b8'};
        color: ${type === 'warning' ? '#000' : '#fff'};
    `;
    document.body.appendChild(notification);
    setTimeout(() => {
        notification.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 4000);
}

const notificationStyles = document.createElement('style');
notificationStyles.textContent = `
    @keyframes slideInRight { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    @keyframes slideOutRight { from { transform: translateX(0); opacity: 1; } to { transform: translateX(100%); opacity: 0; } }
`;
document.head.appendChild(notificationStyles);

// Авторизация
class Auth {
    constructor() {
        isAdmin = sessionStorage.getItem('adminSession') === 'authenticated';
        this.updateUI();
        this.initEventListeners();
    }
    
    initEventListeners() {
        const authBtn = document.getElementById('authBtn');
        const modal = document.getElementById('loginModal');
        const closeBtn = document.querySelector('.close');
        const loginForm = document.getElementById('loginForm');
        
        authBtn.onclick = () => {
            if (isAdmin) this.logout();
            else modal.style.display = 'block';
        };
        
        closeBtn.onclick = () => modal.style.display = 'none';
        window.onclick = (e) => { if (e.target === modal) modal.style.display = 'none'; };
        
        loginForm.onsubmit = (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            if (username === 'admin' && password === 'admin123') {
                isAdmin = true;
                sessionStorage.setItem('adminSession', 'authenticated');
                modal.style.display = 'none';
                this.updateUI();
                showNotification('✅ Добро пожаловать!', 'success');
            } else {
                showNotification('❌ Неверный логин или пароль', 'error');
            }
        };
    }
    
    updateUI() {
        const badge = document.getElementById('userRoleBadge');
        const btn = document.getElementById('authBtn');
        const refreshBtn = document.getElementById('refreshBtn');
        
        if (isAdmin) {
            badge.textContent = '👑 Администратор';
            badge.className = 'role-badge admin';
            btn.textContent = '🚪 Выйти';
            btn.classList.add('logout');
            refreshBtn.style.display = 'inline-block';
        } else {
            badge.textContent = '👤 Гость';
            badge.className = 'role-badge guest';
            btn.textContent = '🔑 Войти как админ';
            btn.classList.remove('logout');
            refreshBtn.style.display = 'none';
        }
    }
    
    logout() {
        isAdmin = false;
        sessionStorage.removeItem('adminSession');
        this.updateUI();
        showNotification('👋 Вы вышли из аккаунта', 'info');
    }
}

// Запуск
window.addEventListener('DOMContentLoaded', async () => {
    const auth = new Auth();
    await initDatabase();
    document.getElementById('refreshBtn').onclick = runScrapingAndUpdate;
    document.getElementById('yearFilter').onchange = async () => {
        await loadDataFromBackend();
        await updateDashboardFromDatabase();
    };
});