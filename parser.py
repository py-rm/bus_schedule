import json
import requests
import time
import hashlib
import re
from bs4 import BeautifulSoup

BASE_URL = "https://orenburg.ru"
MAIN_URL = f"{BASE_URL}/activity/16226/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

print("Шаг 1: Подключаемся к главной странице садоводческих маршрутов...")
response = requests.get(MAIN_URL, headers=HEADERS)

if response.status_code != 200:
    print(f"Ошибка доступа к главной странице: {response.status_code}")
    exit()

soup = BeautifulSoup(response.text, "html.parser")
routes_table = soup.find("table", class_="noline")
bus_schedule = {}

print("\n=== НАЧИНАЕМ СБОР ССЫЛОК НА МАРШРУТЫ ===")

if routes_table:
    all_links = routes_table.find_all("a")
    for link in all_links:
        link_href = link.get("href", "")
        link_text = link.get_text().strip()
        
        if "/activity/" in link_href:
            bus_no = "".join(link_text.split()).upper()
            
            if bus_no and bus_no not in bus_schedule:
                if link_href.startswith("/"):
                    link_href = BASE_URL + link_href
                    
                print(f"Обнаружен маршрут! Автобус № {bus_no} -> {link_href}")
                bus_schedule[bus_no] = {
                    "route_number": bus_no,
                    "route_name": f"Садоводческий маршрут № {bus_no}",
                    "days_info_raw": "Не указано",
                    "carrier_name": "Не указан",
                    "carrier_phones": [],
                    "url": link_href,
                    "md5_hash": "",
                    "workdays": {"to_gardens": [], "from_gardens": []},
                    "weekends": {"to_gardens": [], "from_gardens": []}
                }
else:
    print("Ошибка: Таблица маршрутов не найдена.")
    exit()

print(f"\n[УСПЕХ] Сбор ссылок завершен. Найдено уникальных автобусов: {len(bus_schedule)}")
print("\nШаг 2: Запускаем СТРУКТУРНЫЙ обход страниц (без привязки к названиям остановок)...")

# Маркеры для определения сложного расписания (будни/выходные)
WORKDAYS_MARKERS = ["рабочие дни", "будни", "будние дни"]
WEEKENDS_MARKERS = ["выходные дни", "выходные"]

for idx, (bus_no, bus_info) in enumerate(bus_schedule.items(), 1):
    print(f"[{idx}/{len(bus_schedule)}] Скачиваем расписание для автобуса № {bus_no}...")
    
    try:
        sub_res = requests.get(bus_info["url"], headers=HEADERS)
        if sub_res.status_code == 200:
            sub_soup = BeautifulSoup(sub_res.text, "html.parser")
            
            # Извлекаем красивое название из H1
            h1_tag = sub_soup.find("h1")
            if h1_tag:
                bus_schedule[bus_no]["route_name"] = " ".join(h1_tag.get_text().split()).strip()

            # Ищем текстовое примечание (для №86 и подобных)
            all_p_elements = sub_soup.find_all("p")
            for p in all_p_elements:
                p_text = p.get_text().strip()
                if any(k in p_text.lower() for k in ["по вторникам", "дни работы", "выходные дни - понедельник"]):
                    bus_schedule[bus_no]["days_info_raw"] = " ".join(p_text.split())
                    break

            # Сбор информации о перевозчике
            all_text_elements = sub_soup.find_all(["p", "div", "b", "strong"])
            for elem in all_text_elements:
                full_text = elem.get_text().strip()
                if "перевозчик" in full_text.lower():
                    clean_text = " ".join(full_text.split())
                    carrier_match = re.search(r'(?:перевозчик\s*[\-–—:]\s*)([A-ZА-Яа-яЁё«»""\s\.\-\d]+?)(?=(?:,|\.|\s*тел|$))', clean_text, re.IGNORECASE)
                    if carrier_match:
                        bus_schedule[bus_no]["carrier_name"] = carrier_match.group(1).strip(" ,.-")
                    
                    phone_matches = re.findall(r'\b(?:\+7|8)?\s*\(?\d{3,4}\)?\s*\d{3}[-\s]?\d{2}[-\s]?\d{2}\b|\b\d{2}[-\s]?\d{2}[-\s]?\d{2}\b', clean_text)
                    if phone_matches:
                        bus_schedule[bus_no]["carrier_phones"] = list(set([p.strip() for p in phone_matches]))
                    break

            # --- СТРУКТУРНЫЙ ПАРСИНГ ТАБЛИЦ ПО ИХ ПОРЯДКУ ---
            page_text_lower = sub_soup.get_text().lower()
            # Проверяем, есть ли разделение по дням на этой странице
            has_split_by_days = any(m in page_text_lower for m in WORKDAYS_MARKERS) and any(m in page_text_lower for m in WEEKENDS_MARKERS)

            # Находим блок основного контента, где лежат таблицы расписания
            detail_text_div = sub_soup.find("div", class_="detail_text")
            if not detail_text_div:
                detail_text_div = sub_soup

            # Находим ВСЕ таблицы внутри контента строго по порядку их появления в HTML
            tables = detail_text_div.find_all("table")
            
            # Функция для извлечения времени из таблицы
            def extract_times_from_table(table_element):
                times = []
                cells = table_element.find_all("td")
                for cell in cells:
                    cell_text = cell.get_text().strip()
                    time_match = re.search(r'\b(\d{1,2})[:.](\d{2})\b', cell_text)
                    if time_match:
                        hours = time_match.group(1)
                        minutes = time_match.group(2)
                        if len(hours) == 1:
                            hours = "0" + hours
                        times.append(f"{hours}:{minutes}")
                return sorted(list(set(times)))

            # Логика распределения таблиц по индексам (порядку)
            if has_split_by_days and len(tables) >= 4:
                # Если на странице 4 таблицы (как у 91 и 195):
                bus_schedule[bus_no]["workdays"]["to_gardens"] = extract_times_from_table(tables[0])
                bus_schedule[bus_no]["workdays"]["from_gardens"] = extract_times_from_table(tables[1])
                bus_schedule[bus_no]["weekends"]["to_gardens"] = extract_times_from_table(tables[2])
                bus_schedule[bus_no]["weekends"]["from_gardens"] = extract_times_from_table(tables[3])
                status_msg = "Сложное (Будни/Вых)"
            elif len(tables) >= 2:
                # Если на странице всего 2 таблицы (как у 188 и большинства других):
                common_to = extract_times_from_table(tables[0])
                common_from = extract_times_from_table(tables[1])
                
                # Дублируем график и в будни, и в выходные
                bus_schedule[bus_no]["workdays"]["to_gardens"] = common_to
                bus_schedule[bus_no]["workdays"]["from_gardens"] = common_from
                bus_schedule[bus_no]["weekends"]["to_gardens"] = common_to
                bus_schedule[bus_no]["weekends"]["from_gardens"] = common_from
                status_msg = "Обычное (Единое)"
            else:
                status_msg = "Ошибка: недостаточно таблиц на странице"

            # Считаем MD5-хэш
            all_times = (bus_schedule[bus_no]["workdays"]["to_gardens"] + 
                         bus_schedule[bus_no]["workdays"]["from_gardens"] +
                         bus_schedule[bus_no]["weekends"]["to_gardens"] + 
                         bus_schedule[bus_no]["weekends"]["from_gardens"])
            bus_schedule[bus_no]["md5_hash"] = hashlib.md5("".join(all_times).encode('utf-8')).hexdigest()
            
            print(f"    -> Тип страницы: {status_msg}. Собрано ТУДА/ОБРАТНО.")
            
        else:
            print(f"    Ошибка загрузки страницы автобуса {bus_no}: Статус {sub_res.status_code}")
            
    except Exception as e:
        print(f"    Технический сбой на маршруте {bus_no}: {e}")
        
    time.sleep(0.5)

final_data = {
    "ads_config": {
        "show_local_ad": False,
        "local_ad_image": "https://githubusercontent.com",
        "local_ad_link": "https://site.ru",
        "yandex_ad_unit_id": "R-M-XXXXXX-X"
    },
    "schedule": bus_schedule
}

with open("schedule.json", "w", encoding="utf-8") as file:
    json.dump(final_data, file, ensure_ascii=False, indent=4)

print("\n[УСПЕХ] Структурный парсер успешно выполнил работу! Проверяйте файл schedule.json!")
