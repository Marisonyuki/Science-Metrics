import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

class UniversityScraper:
    def __init__(self, database):
        self.db = database
    
    def scrape_department_page(self, url):
        """Парсинг страницы кафедры"""
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Пример для сайта с типовой структурой (адаптируйте под свой)
            department_data = {
                'name': self._extract_department_name(soup),
                'faculty': self._extract_faculty(soup),
                'professors': self._extract_professors(soup),
                'publications': self._extract_publications(soup),
                'url': url
            }
            
            return department_data
        except Exception as e:
            print(f"Ошибка парсинга {url}: {e}")
            return None
    
    def _extract_department_name(self, soup):
        # Пример: ищем заголовок h1
        title = soup.find('h1')
        return title.text.strip() if title else "Неизвестно"
    
    def _extract_faculty(self, soup):
        # Ищем упоминание факультета
        faculty_elem = soup.find('div', class_='faculty')
        return faculty_elem.text.strip() if faculty_elem else "Не указан"
    
    def _extract_professors(self, soup):
        professors = []
        # Ищем список преподавателей
        prof_elements = soup.find_all('div', class_='professor')
        for prof in prof_elements:
            name = prof.find('h3')
            position = prof.find('div', class_='position')
            professors.append({
                'name': name.text.strip() if name else "Неизвестно",
                'position': position.text.strip() if position else "Преподаватель"
            })
        return professors
    
    def _extract_publications(self, soup):
        publications = []
        # Ищем список публикаций
        pub_elements = soup.find_all('div', class_='publication')
        for pub in pub_elements:
            title = pub.find('h4')
            year = pub.find('span', class_='year')
            citations = pub.find('span', class_='citations')
            publications.append({
                'title': title.text.strip() if title else "Без названия",
                'year': int(year.text) if year and year.text.isdigit() else 2024,
                'citations': int(citations.text) if citations and citations.text.isdigit() else 0
            })
        return publications
    
    def scrape_google_scholar(self, professor_name):
        """Поиск публикаций через Google Scholar (требует осторожности)"""
        # Реальная реализация требует API или обхода блокировок
        # Для демо используем заглушку
        return []
    
    def compare_and_update(self, new_data, old_data):
        """Сравнение старых и новых данных"""
        new_publications = []
        updated_publications = []
        
        # Сравнение публикаций
        old_titles = {pub['title'] for pub in old_data.get('publications', [])}
        
        for pub in new_data.get('publications', []):
            if pub['title'] not in old_titles:
                new_publications.append(pub)
            else:
                # Проверяем изменения в цитированиях
                old_pub = next((p for p in old_data['publications'] if p['title'] == pub['title']), None)
                if old_pub and old_pub['citations'] != pub['citations']:
                    updated_publications.append(pub)
        
        return {
            'new': new_publications,
            'updated': updated_publications
        }

# Пример использования
if __name__ == "__main__":
    from database import Database
    db = Database()
    scraper = UniversityScraper(db)
    
    # Пример парсинга
    data = scraper.scrape_department_page("https://example.com/department")
    if data:
        print(f"Найдено {len(data['professors'])} профессоров")
        print(f"Найдено {len(data['publications'])} публикаций")