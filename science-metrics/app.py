import os
import re
import io
import threading
from datetime import datetime
from urllib.parse import urljoin

import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from bs4 import BeautifulSoup
import pdfplumber
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ========== КОНФИГУРАЦИЯ БАЗЫ ДАННЫХ ==========
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:1@localhost:5432/science_metrics')

def get_db_connection():
    """Возвращает соединение с PostgreSQL"""
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    """Инициализация базы данных (создание таблиц)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Таблица разделов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sections (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    
    # Таблица сотрудников
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            section_id INTEGER REFERENCES sections(id) ON DELETE SET NULL,
            h_index INTEGER DEFAULT 0
        )
    ''')
    
    # Таблица публикаций
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS publications (
            id SERIAL PRIMARY KEY,
            employee_id INTEGER REFERENCES employees(id) ON DELETE CASCADE,
            year INTEGER NOT NULL,
            publications_count INTEGER DEFAULT 0,
            citations_count INTEGER DEFAULT 0,
            UNIQUE(employee_id, year)
        )
    ''')
    
    # Таблица логов парсинга
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS parsing_log (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            file_name TEXT,
            year INTEGER,
            records_count INTEGER,
            new_count INTEGER,
            updated_count INTEGER,
            status TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ База данных PostgreSQL инициализирована")

# ========== ГЛОБАЛЬНОЕ СОСТОЯНИЕ ==========
scraping_status = {
    'is_running': False,
    'progress': 0,
    'message': '',
    'new_count': 0,
    'updated_count': 0,
    'total_files': 0,
    'current_file': 0
}

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def extract_number(value):
    """Извлечение числа из строки"""
    if not value or value == '':
        return 0
    value_str = str(value).strip()
    value_str = value_str.replace(' ', '').replace(',', '.').replace(' ', '')
    numbers = re.findall(r'\d+', value_str)
    return int(numbers[0]) if numbers else 0

def get_pdf_links():
    """Получение ссылок на PDF с сайта РЭУ"""
    pdf_links = []
    url = "https://www.rea.ru/education/ob-universitete/reyting-sotrudnikov-po-indeksu-tsitirovaniya"
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().lower()
            
            if href.endswith('.pdf') and any(year in text for year in ['2024', '2025', '2026']):
                if not href.startswith('http'):
                    href = urljoin(url, href)
                
                year = 2024
                if '2025' in text:
                    year = 2025
                elif '2026' in text:
                    year = 2026
                
                pdf_links.append({
                    'url': href,
                    'year': year,
                    'name': link.get_text().strip()
                })
        
        print(f"🔍 Найдено PDF: {len(pdf_links)}")
        return pdf_links
    except Exception as e:
        print(f"Ошибка получения ссылок: {e}")
        return []

def parse_rating_pdf(pdf_bytes, filename=""):
    """Парсинг PDF-файла рейтинга"""
    # Пропускаем файлы без разделов
    if '100 наиболее цитируемых' in filename:
        return []
    
    all_data = []
    
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            sections = []
            current_section = None
            
            # Сбор разделов
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    for line in text.split('\n'):
                        if 'РАЗДЕЛ' in line and '«' in line:
                            match = re.search(r'РАЗДЕЛ\s*«([^»]+)»', line)
                            if match:
                                current_section = match.group(1).strip()
                                sections.append(current_section)
            
            # Сбор таблиц
            all_tables = []
            for page in pdf.pages:
                for table in page.extract_tables():
                    if table and len(table) > 1:
                        header = table[0]
                        header_text = ' '.join([str(c).lower() for c in header if c])
                        if any(word in header_text for word in ['фио', 'ф.и.о']):
                            all_tables.append(table)
            
            # Обработка таблиц
            for idx, table in enumerate(all_tables):
                if idx < len(sections):
                    section_name = sections[idx]
                else:
                    if sections:
                        section_name = sections[-1]
                    else:
                        continue
                
                for row in table[1:]:
                    if not row or len(row) < 5:
                        continue
                    
                    # Поиск ФИО
                    fio = None
                    for cell in row:
                        if cell and isinstance(cell, str):
                            cell_clean = cell.strip()
                            if re.search(r'[А-Я][а-я]+(\s+[А-Я][а-я]+)+', cell_clean):
                                fio = cell_clean
                                break
                    
                    if not fio:
                        continue
                    
                    # Сбор чисел из строки
                    numbers = []
                    for cell in row:
                        if cell and isinstance(cell, str):
                            nums = re.findall(r'\d+', cell.replace(' ', ''))
                            numbers.extend([int(n) for n in nums])
                        elif cell and isinstance(cell, (int, float)):
                            numbers.append(int(cell))
                    
                    pubs = numbers[0] if len(numbers) > 0 else 0
                    cites = numbers[1] if len(numbers) > 1 else 0
                    h = numbers[2] if len(numbers) > 2 else 0
                    
                    all_data.append({
                        'fio': fio,
                        'section': section_name,
                        'publications': pubs,
                        'citations': cites,
                        'h_index': h
                    })
    except Exception as e:
        print(f"Ошибка парсинга: {e}")
        return []
    
    return all_data

def save_to_database(data, year):
    """Сохранение данных в PostgreSQL"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    new_count = 0
    updated_count = 0
    
    for item in data:
        if not item['fio'] or len(item['fio']) < 5:
            continue
        
        # Получаем или создаём раздел
        cursor.execute("SELECT id FROM sections WHERE name = %s", (item['section'],))
        section_result = cursor.fetchone()
        
        if section_result:
            section_id = section_result[0]
        else:
            cursor.execute("INSERT INTO sections (name) VALUES (%s) RETURNING id", (item['section'],))
            section_id = cursor.fetchone()[0]
        
        # Получаем или создаём сотрудника
        cursor.execute("SELECT id, h_index FROM employees WHERE name = %s", (item['fio'],))
        emp_result = cursor.fetchone()
        
        if emp_result:
            employee_id = emp_result[0]
            old_h_index = emp_result[1]
            if item['h_index'] > old_h_index:
                cursor.execute("UPDATE employees SET h_index = %s, section_id = %s WHERE id = %s",
                             (item['h_index'], section_id, employee_id))
                updated_count += 1
        else:
            cursor.execute("INSERT INTO employees (name, section_id, h_index) VALUES (%s, %s, %s) RETURNING id",
                         (item['fio'], section_id, item['h_index']))
            employee_id = cursor.fetchone()[0]
            new_count += 1
        
        # Сохраняем данные за год
        cursor.execute('''
            INSERT INTO publications (employee_id, year, publications_count, citations_count)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (employee_id, year) DO UPDATE SET
                publications_count = EXCLUDED.publications_count,
                citations_count = EXCLUDED.citations_count
        ''', (employee_id, year, item['publications'], item['citations']))
    
    conn.commit()
    conn.close()
    return new_count, updated_count

def run_scraping():
    """Запуск процесса парсинга"""
    global scraping_status
    
    scraping_status['is_running'] = True
    scraping_status['progress'] = 0
    scraping_status['message'] = 'Поиск PDF...'
    scraping_status['new_count'] = 0
    scraping_status['updated_count'] = 0
    scraping_status['total_files'] = 0
    scraping_status['current_file'] = 0
    
    try:
        pdf_links = get_pdf_links()
        
        if not pdf_links:
            scraping_status['message'] = 'PDF не найдены'
            scraping_status['is_running'] = False
            return
        
        scraping_status['total_files'] = len(pdf_links)
        
        for i, pdf_info in enumerate(pdf_links):
            scraping_status['current_file'] = i + 1
            scraping_status['message'] = f'Загрузка: {pdf_info["name"][:50]}'
            scraping_status['progress'] = (i / len(pdf_links)) * 50
            
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                response = requests.get(pdf_info['url'], headers=headers, timeout=30)
                
                if response.status_code == 200:
                    scraping_status['message'] = f'Парсинг: {pdf_info["name"][:50]}'
                    scraping_status['progress'] = 50 + (i / len(pdf_links)) * 40
                    
                    data = parse_rating_pdf(response.content, pdf_info['name'])
                    if data:
                        new, updated = save_to_database(data, pdf_info['year'])
                        scraping_status['new_count'] += new
                        scraping_status['updated_count'] += updated
                        print(f"✅ {pdf_info['name']}: {len(data)} записей, новых: {new}, обновлено: {updated}")
            except Exception as e:
                print(f"❌ Ошибка: {e}")
        
        scraping_status['progress'] = 100
        scraping_status['message'] = f'Готово! Новых: {scraping_status["new_count"]}, Обновлено: {scraping_status["updated_count"]}'
    except Exception as e:
        scraping_status['message'] = f'Ошибка: {e}'
    finally:
        scraping_status['is_running'] = False

# ========== API ЭНДПОИНТЫ ==========

@app.route('/')
def index():
    """Главная страница"""
    return send_from_directory('frontend', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    """Обслуживание статических файлов (CSS, JS)"""
    return send_from_directory('frontend', path)

@app.route('/api/departments', methods=['GET'])
def get_departments():
    """Получение данных для дашборда с фильтром по году"""
    year_filter = request.args.get('year', 'all')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if year_filter == 'all':
        cursor.execute('''
            SELECT 
                s.id, s.name,
                COUNT(DISTINCT e.id) as employees_count,
                COALESCE(SUM(p.publications_count), 0) as total_publications,
                COALESCE(SUM(p.citations_count), 0) as total_citations,
                COALESCE(AVG(e.h_index), 0) as avg_h_index
            FROM sections s
            LEFT JOIN employees e ON s.id = e.section_id
            LEFT JOIN publications p ON e.id = p.employee_id
            GROUP BY s.id
            ORDER BY avg_h_index DESC
        ''')
    else:
        cursor.execute('''
            SELECT 
                s.id, s.name,
                COUNT(DISTINCT e.id) as employees_count,
                COALESCE(SUM(p.publications_count), 0) as total_publications,
                COALESCE(SUM(p.citations_count), 0) as total_citations,
                COALESCE(AVG(e.h_index), 0) as avg_h_index
            FROM sections s
            LEFT JOIN employees e ON s.id = e.section_id
            LEFT JOIN publications p ON e.id = p.employee_id AND p.year = %s
            GROUP BY s.id
            ORDER BY avg_h_index DESC
        ''', (year_filter,))
    
    rows = cursor.fetchall()
    sections = []
    for row in rows:
        sections.append({
            'id': row[0],
            'name': row[1],
            'employees_count': row[2] or 0,
            'publications': int(row[3]),
            'citations': int(row[4]),
            'h_index': int(row[5])
        })
    
    conn.close()
    return jsonify(sections)

@app.route('/api/scrape', methods=['POST'])
def start_scraping():
    """Запуск парсинга"""
    global scraping_status
    if scraping_status['is_running']:
        return jsonify({'error': 'Парсинг уже выполняется'}), 400
    thread = threading.Thread(target=run_scraping)
    thread.start()
    return jsonify({'message': 'Парсинг запущен'})

@app.route('/api/scrape/status', methods=['GET'])
def get_scraping_status():
    """Получение статуса парсинга"""
    return jsonify({
        'is_running': scraping_status['is_running'],
        'progress': scraping_status['progress'],
        'message': scraping_status['message'],
        'new_count': scraping_status['new_count'],
        'updated_count': scraping_status['updated_count'],
        'current_file': scraping_status['current_file'],
        'total_files': scraping_status['total_files']
    })

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    init_db()
    print("\n" + "="*50)
    print("🚀 Сервер запущен!")
    print("📊 Откройте: http://localhost:5000")
    print("="*50 + "\n")
    app.run(debug=True, port=5000)