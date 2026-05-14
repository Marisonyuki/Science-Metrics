# backend/pdf_parser.py
import re
import io
import os
import requests
import pandas as pd
import pdfplumber
from typing import List, Dict, Optional
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin

class REARatingParser:
    """
    Парсер рейтингов сотрудников РЭУ им. Плеханова из PDF
    """
    
    def __init__(self):
        # Колонки, которые ожидаем в таблице
        self.expected_columns = [
            'n_p_p',      # Номер п/п
            'fio',        # ФИО
            'rating_place', # Место рейтинга
            'publications', # Публикации
            'citations',    # Цитирования
            'h_index'       # Индекс Хирша
        ]
    
    def parse_pdf_table(self, pdf_path: str) -> Optional[pd.DataFrame]:
        """
        Извлечение таблицы из PDF-файла рейтинга
        """
        try:
            with pdfplumber.open(pdf_path) as pdf:
                all_tables = []
                
                for page_num, page in enumerate(pdf.pages):
                    # Извлекаем таблицы со страницы
                    tables = page.extract_tables()
                    
                    for table in tables:
                        if self._is_rating_table(table):
                            df = self._clean_table_data(table)
                            if df is not None and not df.empty:
                                all_tables.append(df)
                
                if all_tables:
                    # Объединяем таблицы со всех страниц
                    combined_df = pd.concat(all_tables, ignore_index=True)
                    return self._post_process(combined_df)
                
                return None
                
        except Exception as e:
            print(f"Ошибка парсинга PDF {pdf_path}: {e}")
            return None
    
    def _is_rating_table(self, table: List[List]) -> bool:
        """
        Определяет, является ли таблица таблицей рейтинга
        Проверяем наличие характерных заголовков
        """
        if not table or len(table) < 2:
            return False
        
        # Проверяем первую строку (заголовки)
        header_row = table[0]
        header_text = ' '.join([str(cell).lower() for cell in header_row if cell])
        
        keywords = ['п/п', 'фио', 'рейтинг', 'публикации', 'цитировани', 'хирш']
        matches = sum(1 for keyword in keywords if keyword in header_text)
        
        return matches >= 3  # Если нашли 3 и более ключевых слов
    
    def _clean_table_data(self, table: List[List]) -> Optional[pd.DataFrame]:
        """
        Очистка и структурирование табличных данных
        """
        if not table or len(table) < 2:
            return None
        
        # Первая строка — заголовки
        headers = []
        for cell in table[0]:
            if cell:
                clean_header = re.sub(r'[^а-яА-Яa-zA-Z]', '', str(cell).lower())
                headers.append(clean_header)
            else:
                headers.append('')
        
        # Создаём DataFrame из данных
        data_rows = []
        for row in table[1:]:
            # Пропускаем пустые строки
            if all(cell is None or str(cell).strip() == '' for cell in row):
                continue
            
            # Нормализуем длину строки
            while len(row) < len(headers):
                row.append('')
            
            data_rows.append(row[:len(headers)])
        
        if not data_rows:
            return None
        
        df = pd.DataFrame(data_rows, columns=headers)
        
        # Переименовываем колонки в стандартные
        column_mapping = {
            'пп': 'n_p_p',
            'п/п': 'n_p_p',
            'фио': 'fio',
            'месторейтинга': 'rating_place',
            'публикации': 'publications',
            'цитирования': 'citations',
            'индексхирша': 'h_index'
        }
        
        df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns}, inplace=True)
        
        return df
    
    def _post_process(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Постобработка данных: очистка, типизация
        """
        # Очищаем ФИО
        if 'fio' in df.columns:
            df['fio'] = df['fio'].astype(str).str.strip()
            df['fio'] = df['fio'].str.replace(r'\s+', ' ', regex=True)
        
        # Конвертируем числовые колонки
        numeric_columns = ['publications', 'citations', 'h_index']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        
        # Удаляем дубликаты по ФИО
        if 'fio' in df.columns:
            df = df.drop_duplicates(subset=['fio'], keep='first')
        
        return df


class REALinksScraper:
    """
    Сборщик ссылок на PDF-файлы рейтингов с сайта
    """
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_pdf_links(self) -> List[Dict]:
        """
        Парсинг страницы и поиск всех ссылок на PDF за 2024-2026 годы
        """
        pdf_links = []
        
        try:
            response = self.session.get(self.base_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Ищем все ссылки на PDF
            for link in soup.find_all('a', href=True):
                href = link['href']
                
                # Проверяем, ведёт ли ссылка на PDF
                if href.endswith('.pdf') or '/pdf/' in href.lower():
                    # Нормализуем URL
                    if not href.startswith('http'):
                        href = urljoin(self.base_url, href)
                    
                    # Извлекаем дату из текста ссылки
                    link_text = link.get_text().lower()
                    
                    # Ищем месяц и год
                    year_match = re.search(r'(202[4-6])', link_text)
                    month_match = re.search(r'(январ|феврал|март|апрел|май|июн|июл|август|сентябр|октябр|ноябр|декабр)', link_text)
                    
                    if year_match:
                        pdf_links.append({
                            'url': href,
                            'year': int(year_match.group(1)),
                            'month': month_match.group(1) if month_match else None,
                            'text': link.get_text().strip()
                        })
            
            print(f"🔍 Найдено {len(pdf_links)} PDF-файлов рейтингов")
            return pdf_links
            
        except Exception as e:
            print(f"Ошибка получения ссылок: {e}")
            return []
    
    def download_pdf(self, pdf_info: Dict) -> Optional[bytes]:
        """
        Загрузка PDF-файла
        """
        try:
            response = self.session.get(pdf_info['url'], timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as e:
            print(f"Ошибка загрузки {pdf_info['url']}: {e}")
            return None


class RatingAggregator:
    """
    Агрегация данных по годам
    """
    
    def __init__(self):
        self.yearly_data = {}
    
    def add_monthly_data(self, df: pd.DataFrame, year: int, month: str):
        """
        Добавление данных за месяц к годовому агрегату
        """
        if year not in self.yearly_data:
            self.yearly_data[year] = {}
        
        # Суммируем публикации и цитирования
        for _, row in df.iterrows():
            fio = row.get('fio')
            if not fio:
                continue
            
            if fio not in self.yearly_data[year]:
                self.yearly_data[year][fio] = {
                    'publications': 0,
                    'citations': 0,
                    'h_index': 0,
                    'months': []
                }
            
            self.yearly_data[year][fio]['publications'] += row.get('publications', 0)
            self.yearly_data[year][fio]['citations'] += row.get('citations', 0)
            # Для h-индекса берём максимальное за год
            self.yearly_data[year][fio]['h_index'] = max(
                self.yearly_data[year][fio]['h_index'],
                row.get('h_index', 0)
            )
            self.yearly_data[year][fio]['months'].append(month)
    
    def get_yearly_summary(self) -> pd.DataFrame:
        """
        Получение годовой сводки по всем сотрудникам
        """
        all_rows = []
        
        for year, employees in self.yearly_data.items():
            for fio, data in employees.items():
                all_rows.append({
                    'year': year,
                    'fio': fio,
                    'publications': data['publications'],
                    'citations': data['citations'],
                    'h_index': data['h_index'],
                    'months_count': len(set(data['months']))
                })
        
        return pd.DataFrame(all_rows)


# ========== ОСНОВНОЙ КЛАСС ПАРСЕРА ==========

class REARatingSystem:
    """
    Основной класс системы парсинга рейтингов РЭУ
    """
    
    def __init__(self):
        self.link_scraper = REALinksScraper("https://www.rea.ru/education/ob-universitete/reyting-sotrudnikov-po-indeksu-tsitirovaniya")
        self.pdf_parser = REARatingParser()
        self.aggregator = RatingAggregator()
    
    def run_full_parse(self) -> pd.DataFrame:
        """
        Запуск полного цикла парсинга
        """
        print("🚀 Начинаем сбор данных о рейтингах сотрудников...")
        
        # Шаг 1: Получаем все ссылки на PDF
        print("📎 Шаг 1: Поиск PDF-файлов рейтингов...")
        pdf_links = self.link_scraper.get_pdf_links()
        
        if not pdf_links:
            print("❌ Не найдено ни одного PDF-файла")
            return pd.DataFrame()
        
        # Шаг 2: Обрабатываем каждый PDF
        print(f"📄 Шаг 2: Обработка {len(pdf_links)} PDF-файлов...")
        
        for pdf_info in pdf_links:
            print(f"   - {pdf_info['text']} ({pdf_info['year']})")
            
            # Загружаем PDF
            pdf_content = self.link_scraper.download_pdf(pdf_info)
            if not pdf_content:
                continue
            
            # Сохраняем временно (или обрабатываем в памяти)
            temp_path = f"temp_{pdf_info['year']}_{pdf_info['month']}.pdf"
            with open(temp_path, 'wb') as f:
                f.write(pdf_content)
            
            # Извлекаем таблицу
            df = self.pdf_parser.parse_pdf_table(temp_path)
            
            if df is not None and not df.empty:
                # Добавляем в агрегатор
                self.aggregator.add_monthly_data(df, pdf_info['year'], pdf_info['month'])
                print(f"      ✅ Извлечено {len(df)} записей")
            else:
                print(f"      ⚠️ Не удалось извлечь таблицу")
            
            # Удаляем временный файл
            import os
            if os.path.exists(temp_path):
                os.remove(temp_path)
        
        # Шаг 3: Агрегируем по годам
        print("📊 Шаг 3: Агрегация данных по годам...")
        yearly_summary = self.aggregator.get_yearly_summary()
        
        print(f"✅ Парсинг завершён! Обработано сотрудников: {len(yearly_summary)}")
        
        return yearly_summary


# ========== ТЕСТИРОВАНИЕ ==========

if __name__ == "__main__":
    system = REARatingSystem()
    result = system.run_full_parse()
    
    if not result.empty:
        print("\n" + "="*60)
        print("РЕЗУЛЬТАТЫ ПО ГОДАМ:")
        print("="*60)
        
        for year in sorted(result['year'].unique()):
            year_data = result[result['year'] == year]
            print(f"\n📅 {year} год:")
            print(f"   - Всего сотрудников: {len(year_data)}")
            print(f"   - Среднее кол-во публикаций: {year_data['publications'].mean():.1f}")
            print(f"   - Среднее кол-во цитирований: {year_data['citations'].mean():.1f}")
            print(f"   - Средний h-индекс: {year_data['h_index'].mean():.1f}")
            print(f"\n   Топ-5 сотрудников по цитированиям:")
            top5 = year_data.nlargest(5, 'citations')[['fio', 'citations', 'h_index']]
            for _, row in top5.iterrows():
                print(f"     - {row['fio'][:30]:30} | Цит.: {row['citations']:3} | h: {row['h_index']}")