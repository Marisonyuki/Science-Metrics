from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import sqlite3
import psycopg2
import threading
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import pdfplumber
import io
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)
CORS(app)

# ========== НАСТРОЙКА БАЗЫ ДАННЫХ ==========
# Определяем, где мы находимся
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    """Возвращает соединение с БД (PostgreSQL на сервере, SQLite локально)"""
    if DATABASE_URL:
        # На Render — используем PostgreSQL
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        # Локально — используем SQLite
        conn = sqlite3.connect('university.db')
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    """Инициализация базы данных (создание таблиц)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if DATABASE_URL:
        # PostgreSQL синтаксис
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sections (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE,
                section_id INTEGER REFERENCES sections(id),
                h_index INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS publications (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER REFERENCES employees(id),
                year INTEGER,
                publications_count INTEGER,
                citations_count INTEGER
            )
        ''')
    else:
        # SQLite синтаксис
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                section_id INTEGER,
                h_index INTEGER,
                FOREIGN KEY (section_id) REFERENCES sections (id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS publications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER,
                year INTEGER,
                publications_count INTEGER,
                citations_count INTEGER,
                FOREIGN KEY (employee_id) REFERENCES employees (id)
            )
        ''')
    
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

# ========== ОСТАЛЬНЫЕ ФУНКЦИИ ==========
def extract_number(value):
    """Извлечение числа из строки"""
    if not value or value == '':
        return 0
    
    value_str = str(value).strip()
    
    # Убираем пробелы и заменяем запятую
    value_str = value_str.replace(' ', '').replace(',', '')
    
    # Ищем числа
    numbers = re.findall(r'\d+', value_str)
    
    if numbers:
        # Берём первое число (обычно это основное значение)
        return int(numbers[0])
    
    return 0


def get_or_create_section(cursor, section_name):
    """Получить или создать раздел (кафедру/факультет)"""
    if not section_name or section_name == '':
        section_name = 'Общий рейтинг'
    
    cursor.execute("SELECT id FROM sections WHERE name = ?", (section_name,))
    result = cursor.fetchone()
    
    if result:
        return result[0]
    else:
        cursor.execute("INSERT INTO sections (name, parent_type) VALUES (?, ?)", 
                      (section_name, 'unknown'))
        return cursor.lastrowid


# ========== ПАРСЕР PDF ==========

def parse_rating_pdf(pdf_bytes, filename=""):
    """Парсер, извлекающий данные напрямую из строк"""
    
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
                                print(f"📌 Раздел: {current_section}")
            
            # Сбор таблиц
            all_tables = []
            for page in pdf.pages:
                for table in page.extract_tables():
                    if table and len(table) > 1:
                        header = table[0]
                        header_text = ' '.join([str(c).lower() for c in header if c])
                        if any(word in header_text for word in ['фио', 'ф.и.о']):
                            all_tables.append(table)
            
            print(f"\n📊 Разделов: {len(sections)}, Таблиц: {len(all_tables)}")
            
            # Обработка таблиц
            for idx, table in enumerate(all_tables):
                if idx < len(sections):
                    section_name = sections[idx]
                else:
                    if sections:
                        section_name = sections[-1]
                    else:
                        continue
                
                print(f"\n📌 Обработка: {section_name}")
                
                records_count = 0
                for row in table[1:]:  # Пропускаем заголовок
                    if not row or len(row) < 5:
                        continue
                    
                    # Ищем ФИО — строка с русскими буквами и пробелами
                    fio = None
                    for cell in row:
                        if cell and isinstance(cell, str):
                            cell_clean = cell.strip()
                            # ФИО обычно содержит 2-3 слова, начинается с заглавной
                            if re.search(r'[А-Я][а-я]+(\s+[А-Я][а-я]+)+', cell_clean):
                                fio = cell_clean
                                break
                    
                    if not fio:
                        continue
                    
                    # Извлекаем все числа из строки
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
                    
                    if records_count < 3:
                        print(f"   {fio[:35]} -> Публ:{pubs}, Цит:{cites}, Хирш:{h}")
                    
                    all_data.append({
                        'fio': fio,
                        'section': section_name,
                        'publications': pubs,
                        'citations': cites,
                        'h_index': h
                    })
                    records_count += 1
                
                if records_count > 0:
                    print(f"   ✅ Добавлено {records_count} сотрудников")
                else:
                    print(f"   ⚠️ Нет данных")
    
    except Exception as e:
        print(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    print(f"\n📊 ВСЕГО записей: {len(all_data)}")
    section_counts = {}
    for item in all_data:
        s = item['section']
        section_counts[s] = section_counts.get(s, 0) + 1
    for s, count in sorted(section_counts.items(), key=lambda x: -x[1]):
        print(f"   - {s}: {count}")
    
    return all_data

# ========== СОХРАНЕНИЕ ДАННЫХ ==========

def save_to_database(data, year):
    """Сохранение данных с привязкой к году"""
    conn = sqlite3.connect('university.db')
    cursor = conn.cursor()
    
    new_count = 0
    updated_count = 0
    
    for item in data:
        if not item['fio'] or len(item['fio']) < 5:
            continue
        
        # Получение раздела
        cursor.execute("SELECT id FROM sections WHERE name = ?", (item['section'],))
        section_result = cursor.fetchone()
        if section_result:
            section_id = section_result[0]
        else:
            cursor.execute("INSERT INTO sections (name) VALUES (?)", (item['section'],))
            section_id = cursor.lastrowid
        
        # Получение сотрудника
        cursor.execute("SELECT id FROM employees WHERE name = ?", (item['fio'],))
        emp_result = cursor.fetchone()
        
        if emp_result:
            employee_id = emp_result[0]
            # Обновление h_index.
            cursor.execute("SELECT h_index FROM employees WHERE id = ?", (employee_id,))
            old_h = cursor.fetchone()[0]
            if item['h_index'] > old_h:
                cursor.execute("UPDATE employees SET h_index = ? WHERE id = ?", (item['h_index'], employee_id))
                updated_count += 1
        else:
            cursor.execute('''
                INSERT INTO employees (name, section_id, h_index)
                VALUES (?, ?, ?)
            ''', (item['fio'], section_id, item['h_index']))
            employee_id = cursor.lastrowid
            new_count += 1
        
        # Сохранение данных за год.
        cursor.execute('''
            SELECT publications_count, citations_count FROM publications 
            WHERE employee_id = ? AND year = ?
        ''', (employee_id, year))
        pub_result = cursor.fetchone()
        
        if pub_result:
            old_pubs, old_cites = pub_result
            if item['publications'] != old_pubs or item['citations'] != old_cites:
                cursor.execute('''
                    UPDATE publications 
                    SET publications_count = ?, citations_count = ?
                    WHERE employee_id = ? AND year = ?
                ''', (item['publications'], item['citations'], employee_id, year))
                updated_count += 1
        else:
            cursor.execute('''
                INSERT INTO publications (employee_id, year, publications_count, citations_count)
                VALUES (?, ?, ?, ?)
            ''', (employee_id, year, item['publications'], item['citations']))
            new_count += 1
    
    conn.commit()
    conn.close()
    return new_count, updated_count

# ========== ПОЛУЧЕНИЕ ССЫЛОК PDF ==========
def get_pdf_links():
    """Получение всех ссылок на PDF с сайта РЭУ"""
    pdf_links = []
    url = "https://www.rea.ru/education/ob-universitete/reyting-sotrudnikov-po-indeksu-tsitirovaniya"
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().lower()
            
            # Поиск ссылок содержащих год
            if href.endswith('.pdf') and any(year in text for year in ['2024', '2025', '2026']):
                if not href.startswith('http'):
                    href = urljoin(url, href)
                
                # Определение года по тексту
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
        
        print(f"🔍 Найдено PDF файлов: {len(pdf_links)}")
        return pdf_links
        
    except Exception as e:
        print(f"❌ Ошибка получения ссылок: {e}")
        return []

# ========== ОСНОВНАЯ ФУНКЦИЯ ПАРСИНГА ==========

def run_scraping():
    global scraping_status
    
    scraping_status['is_running'] = True
    scraping_status['progress'] = 0
    scraping_status['message'] = 'Поиск PDF файлов...'
    scraping_status['new_count'] = 0
    scraping_status['updated_count'] = 0
    scraping_status['total_files'] = 0
    scraping_status['current_file'] = 0
    
    try:
        pdf_links = get_pdf_links()
        
        if not pdf_links:
            scraping_status['message'] = 'PDF файлы не найдены'
            scraping_status['is_running'] = False
            return
        
        scraping_status['total_files'] = len(pdf_links)
        
        for i, pdf_info in enumerate(pdf_links):
            scraping_status['current_file'] = i + 1
            scraping_status['message'] = f'Загрузка: {pdf_info["name"]}'
            scraping_status['progress'] = (i / len(pdf_links)) * 50
            
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                response = requests.get(pdf_info['url'], headers=headers, timeout=30)
                
                if response.status_code == 200:
                    scraping_status['message'] = f'Парсинг: {pdf_info["name"]}'
                    scraping_status['progress'] = 50 + (i / len(pdf_links)) * 40
                    
                    data = parse_rating_pdf(response.content, pdf_info['name'])
                    
                    if data:
                        new, updated = save_to_database(data, pdf_info['year'])
                        scraping_status['new_count'] += new
                        scraping_status['updated_count'] += updated
                        print(f"✅ {pdf_info['name']}: {len(data)} записей, новых: {new}, обновлено: {updated}")
                    else:
                        print(f"⚠️ Не удалось извлечь данные из {pdf_info['name']}")
                        
            except Exception as e:
                print(f"❌ Ошибка обработки {pdf_info['name']}: {e}")
        
        scraping_status['progress'] = 100
        scraping_status['message'] = f'Парсинг завершён! Новых: {scraping_status["new_count"]}, Обновлено: {scraping_status["updated_count"]}'
        
    except Exception as e:
        scraping_status['message'] = f'Ошибка: {e}'
        print(f"Ошибка парсинга: {e}")
    
    finally:
        scraping_status['is_running'] = False

# ========== API ЭНДПОИНТЫ ==========
@app.route('/api/departments', methods=['GET'])
def get_departments():
    """Получение данных для дашборда с фильтром по году"""
    year_filter = request.args.get('year', 'all')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if DATABASE_URL:
        # PostgreSQL синтаксис
        if year_filter == 'all':
            cursor.execute('''
                SELECT s.id, s.name,
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
                SELECT s.id, s.name,
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
    else:
        # SQLite синтаксис
        if year_filter == 'all':
            cursor.execute('''
                SELECT s.id, s.name,
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
                SELECT s.id, s.name,
                       COUNT(DISTINCT e.id) as employees_count,
                       COALESCE(SUM(p.publications_count), 0) as total_publications,
                       COALESCE(SUM(p.citations_count), 0) as total_citations,
                       COALESCE(AVG(e.h_index), 0) as avg_h_index
                FROM sections s
                LEFT JOIN employees e ON s.id = e.section_id
                LEFT JOIN publications p ON e.id = p.employee_id AND p.year = ?
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
    global scraping_status
    if scraping_status['is_running']:
        return jsonify({'error': 'Парсинг уже выполняется'}), 400
    thread = threading.Thread(target=run_scraping)
    thread.start()
    return jsonify({'message': 'Парсинг запущен'})

@app.route('/api/scrape/status', methods=['GET'])
def get_scraping_status():
    return jsonify({
        'is_running': scraping_status['is_running'],
        'progress': scraping_status['progress'],
        'message': scraping_status['message'],
        'new_count': scraping_status['new_count'],
        'updated_count': scraping_status['updated_count']
    })


scraping_status = {
    'is_running': False,
    'progress': 0,
    'message': '',
    'new_count': 0,
    'updated_count': 0,
    'total_files': 0,
    'current_file': 0
}

# Маршрут для главной страницы
@app.route('/')
def index():
    return send_from_directory('frontend', 'index.html')

# Маршрут для статических файлов (CSS, JS)
@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('frontend', path)

if __name__ == '__main__':
    init_db()
    print("\n" + "="*50)
    print("🚀 Сервер запущен!")
    print("📊 Откройте: http://localhost:5000")
    print("="*50 + "\n")
    app.run(debug=True, port=5000)