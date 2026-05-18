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
# Здесь остаются ВСЕ ваши функции без изменений:
# extract_number(), get_pdf_links(), parse_rating_pdf(), 
# save_to_database(), run_scraping()
# (скопируйте их из вашего текущего app.py, они не меняются)

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

# Глобальное состояние парсинга (скопируйте из вашего app.py)
scraping_status = {
    'is_running': False,
    'progress': 0,
    'message': '',
    'new_count': 0,
    'updated_count': 0,
    'total_files': 0,
    'current_file': 0
}

if __name__ == '__main__':
    init_db()
    print("\n" + "="*50)
    print("🚀 Сервер запущен!")
    print("📊 Откройте: http://localhost:5000")
    print("="*50 + "\n")
    app.run(debug=True, port=5000)