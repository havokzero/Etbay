import requests
from bs4 import BeautifulSoup
from colorama import Fore, init
import sqlite3
import os
import logging
from dotenv import load_dotenv
from retrying import retry

# Initialize colorama and logging
init(autoreset=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from a .env file
load_dotenv()

DB_NAME = 'ebay_etsy_listings.db'

class DatabaseManager:
    def __enter__(self):
        self.conn = sqlite3.connect(DB_NAME)
        self.cursor = self.conn.cursor()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            logging.error("Database operation failed", exc_info=True)
        self.conn.commit()
        self.conn.close()

    def setup_database(self):
        logging.info("Setting up the database.")
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                price TEXT,
                link TEXT NOT NULL,
                description TEXT,
                notes TEXT
            )
        ''')

    def save_to_database(self, platform, title, price, link, description, notes):
        logging.info(f"Saving item '{title}' to the database.")
        self.cursor.execute('''
            INSERT INTO listings (platform, title, price, link, description, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (platform, title, price, link, description, notes))


# Retry mechanism for web requests in case of temporary failures
@retry(stop_max_attempt_number=3, wait_fixed=2000)
def fetch_url(url):
    response = requests.get(url)
    response.raise_for_status()
    return response

# Improved web scraping function for eBay
def find_ebay_items(search_query, max_price=None):
    url = f'https://www.ebay.com/sch/i.html?_nkw={search_query}'
    try:
        response = fetch_url(url)
        soup = BeautifulSoup(response.text, 'html.parser')
    except requests.RequestException as e:
        logging.error(f"Failed to retrieve eBay items: {e}")
        return []

    items = []
    for item in soup.find_all('div', class_='s-item__info'):
        try:
            title = item.find('h3', class_='s-item__title').get_text(strip=True)
            price_text = item.find('span', class_='s-item__price')
            price = float(price_text.get_text().replace('$', '').replace(',', '')) if price_text else None
            link = item.find('a', class_='s-item__link')['href']
            description = item.find('div', class_='s-item__subtitle').get_text(strip=True) if item.find('div', class_='s-item__subtitle') else 'N/A'

            if max_price is None or (price is not None and price <= max_price):
                items.append({
                    'title': title,
                    'price': price_text.get_text() if price_text else 'N/A',
                    'link': link,
                    'description': description
                })
        except AttributeError as e:
            logging.warning(f"Error parsing eBay item data: {e}")

    logging.info(f"Found {len(items)} items on eBay.")
    return items

# Improved API request handling for Etsy
def find_etsy_items(search_query, max_price=None):
    api_key = os.getenv('ETSY_API_KEY')  # Fetch the API key from environment variables
    if not api_key:
        logging.error("Etsy API key not found. Please set the ETSY_API_KEY environment variable.")
        return []

    url = f'https://openapi.etsy.com/v2/listings/active?api_key={api_key}&keywords={search_query}&limit=10'
    try:
        response = fetch_url(url)
        data = response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to retrieve Etsy items: {e}")
        return []

    items = []
    for item in data.get('results', []):
        try:
            title = item.get('title', 'N/A')
            price = item.get('price', 'N/A')
            link = item.get('url', 'N/A')
            description = item.get('description', 'N/A')

            if max_price is None or (price != 'N/A' and float(price) <= max_price):
                items.append({
                    'title': title,
                    'price': f'${price}',
                    'link': link,
                    'description': description
                })
        except (TypeError, ValueError) as e:
            logging.warning(f"Error parsing Etsy item data: {e}")

    logging.info(f"Found {len(items)} items on Etsy.")
    return items

def get_user_input(prompt, validator=None):
    while True:
        user_input = input(Fore.CYAN + prompt).strip()
        if validator and not validator(user_input):
            print(Fore.RED + "Invalid input, please try again.")
        else:
            return user_input

def is_float(value):
    try:
        float(value)
        return True
    except ValueError:
        return False

def main():
    with DatabaseManager() as db:
        db.setup_database()

        platform = get_user_input("Enter the platform to search (eBay or Etsy): ", lambda x: x.lower() in ['ebay', 'etsy'])
        search_query = get_user_input("Enter the item you want to search for: ", lambda x: len(x) > 0)

        max_price_input = get_user_input("Enter the maximum price (or leave blank for no limit): ", lambda x: is_float(x) or x == '')
        max_price = float(max_price_input) if max_price_input else None

        if platform.lower() == 'ebay':
            items = find_ebay_items(search_query, max_price)
        else:
            items = find_etsy_items(search_query, max_price)

        if not items:
            print(Fore.YELLOW + "No items found.")
            return

        for item in items:
            print(Fore.GREEN + f"Title: {item['title']}, Price: {item['price']}, Link: {item['link']}")
            description = item.get('description', 'N/A')
            notes = get_user_input(f"Enter notes for '{item['title']}': ").strip()
            db.save_to_database(platform.capitalize(), item['title'], item['price'], item['link'], description, notes)

if __name__ == "__main__":
    main()
