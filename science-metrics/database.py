import sqlite3
import json
from datetime import datetime

class Database:
    def __init__(self, db_path='university.db'):
        self.db_path = db_path
        self.init_tables()
    
    def init_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблицы (только создание, без заполнения)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                faculty TEXT,
                url TEXT,
                last_updated TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS professors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                department_id INTEGER,
                position TEXT,
                email TEXT,
                scholar_url TEXT,
                FOREIGN KEY (department_id) REFERENCES departments(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS publications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                year INTEGER,
                citations INTEGER,
                doi TEXT,
                journal TEXT,
                authors TEXT,
                professor_id INTEGER,
                department_id INTEGER,
                scraped_at TIMESTAMP,
                FOREIGN KEY (professor_id) REFERENCES professors(id),
                FOREIGN KEY (department_id) REFERENCES departments(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scraping_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP,
                source_url TEXT,
                new_records INTEGER,
                updated_records INTEGER,
                status TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Таблицы базы данных созданы (пустые)")
    
    def get_all_departments(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT d.id, d.name, d.faculty, d.url,
                   COUNT(p.id) as publications,
                   COALESCE(SUM(p.citations), 0) as citations
            FROM departments d
            LEFT JOIN publications p ON d.id = p.department_id
            GROUP BY d.id
            ORDER BY citations DESC
        ''')
        data = cursor.fetchall()
        conn.close()
        return data
    
    def get_all_publications(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, title, year, citations, department_id, doi, journal, authors
            FROM publications
            ORDER BY year DESC
        ''')
        data = cursor.fetchall()
        conn.close()
        return data
    
    def add_department(self, name, faculty, url):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO departments (name, faculty, url, last_updated)
            VALUES (?, ?, ?, ?)
        ''', (name, faculty, url, datetime.now()))
        conn.commit()
        conn.close()
    
    def add_publication(self, pub_data):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO publications 
            (title, year, citations, doi, journal, authors, professor_id, department_id, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', pub_data)
        conn.commit()
        conn.close()
    
    def log_scraping(self, source_url, new_records, updated_records, status):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO scraping_log (timestamp, source_url, new_records, updated_records, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (datetime.now(), source_url, new_records, updated_records, status))
        conn.commit()
        conn.close()
    
    def is_empty(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM departments")
        count = cursor.fetchone()[0]
        conn.close()
        return count == 0

# Инициализация БД
db = Database()

# Проверка при запуске
if db.is_empty():
    print("📭 База данных пуста. Готова к приёму данных через веб-скрейпинг.")
else:
    print(f"📊 База данных содержит данные о кафедрах")