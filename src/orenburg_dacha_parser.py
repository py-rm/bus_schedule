# -*- coding: utf-8 -*-
"""
Парсер расписания дачных (садоводческих) автобусов Оренбурга.

Источник: https://orenburg.ru/activity/16226/
Парсит главную страницу со списком маршрутов, затем каждую страницу
маршрута, извлекает из HTML блоки расписания (направление, дни работы,
даты вступления в силу, время отправления, перевозчик) и формирует JSON.

Для каждого маршрута считается MD5-хеш его данных, а для всего файла —
общий MD5-хеш содержимого (без самого поля md5).
"""

import datetime
import hashlib
import json
import re
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://orenburg.ru"
LANDING_URL = BASE_URL + "/activity/16226/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

OUTPUT_FILE = "dacha_schedule.json"

# Время в клетках: часы и минуты через "." или ":" (стиль вручную разный)
TIME_RE = re.compile(r"^\s*(\d{1,2})[.:](\d{1,2})\s*$")


def parse_time_cell(cell_text):
    """Возвращает время в едином формате HH:MM (например "8.00" -> "08:00")."""
    m = TIME_RE.match(cell_text)
    if m:
        return "%02d:%02d" % (int(m.group(1)), int(m.group(2)))
    return None


def parse_date_marker(text):
    """Дата-маркер вида "с 01.09.2026:" (терпит пробелы внутри даты)."""
    m = re.match(r"с([\d.]+):?$", re.sub(r"\s+", "", text).lower())
    if m and re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", m.group(1)):
        return m.group(1)
    return None

# Признак строки перевозчика
CARRIER_MARKERS = ("перевозчик", "тел. диспетчерской", "диспетчерск")

# Ключевые слова для пунктов остановок (это пункты направления движения)
STOP_HINTS = ("конечная",)



def canonical_json(obj):
    """Компактная каноничная сериализация для стабильных MD5-хешей."""
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def md5_of(obj_or_str):
    if isinstance(obj_or_str, (dict, list)):
        data = canonical_json(obj_or_str)
    else:
        data = obj_or_str.encode("utf-8")
    return hashlib.md5(data).hexdigest()


def fetch(url):
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            print(f"  ! Ошибка получения {url}: {exc} (попытка {attempt + 1}/3)")
            time.sleep(2 * (attempt + 1))
    return None


def clean(text):
    """Вычищает лишние whitespace из текста."""
    return re.sub(r"\s+", " ", text).strip()


def extract_stops_from_detail(detail_div):
    """
    Разбирает HTML в activity__detail и возвращает упорядоченный список
    schedule-блоков.

    Логика: идём по прямым потомкам контейнера. Поддерживаем текущее
    состояние: день недели (days), дата вступления в силу (valid_from) и
    текущий пункт направления (point). Каждая таблица времени привязывается
    к последнему заданному пункту и текущему состоянию days/valid_from.
    """
    blocks = []          # итоговые блоки
    current_block = None # блок в процессе сборки
    current_point = None
    current_days = None
    current_valid_from = None

    point_like = ("челюскинцев", "автовокзал", "а/ст", "автостанция", "конечная",
                  "сады", "с/т", "ст ", "г. ", "а/с")

    def flush():
        nonlocal current_block, current_point
        if current_block and current_block["stops"]:
            blocks.append(current_block)
        current_block = None
        current_point = None

    for child in detail_div.find_all(["p", "table"]):
        name = child.name
        text = clean(child.get_text(" ", strip=True))

        if not text:
            continue

        if name == "table":
            # Собираем времена из всех td-ячеек таблицы
            times = []
            for td in child.find_all("td"):
                t = parse_time_cell(clean(td.get_text(" ", strip=True)))
                if t:
                    times.append(t)
            if not times:
                continue
            if current_block is None:
                current_block = {
                    "days": current_days,
                    "valid_from": current_valid_from,
                    "stops": [],
                }
            if current_point is None:
                current_point = "(не указан пункт)"
            current_block["stops"].append({
                "point": current_point,
                "times": times,
            })
            continue

        # Отбрасываем перевозчик — это не блок расписания
        if any(m in text.lower() for m in CARRIER_MARKERS):
            continue

        # Дата-маркер нового расписания "с 01.09.2026:"
        dm = parse_date_marker(text)
        if dm:
            flush()
            current_valid_from = dm
            current_days = None
            continue

        # Строка-ограничение по дням недели (например "по вторникам...")
        # Обычно выделяется курсивом/подчёркиванием, но проверим по смыслу.
        if text.lower().startswith(("по ", "в будние", "будни", "ежедневно",
                                    "суббота", "воскресенье", "праздн", "выходн",
                                    "рабоч")):
            flush()
            current_days = text
            continue

        # Иначе это, скорее всего, название пункта направления
        low = text.lower()
        is_point = (
            any(h in low for h in STOP_HINTS)
            or any(k in low for k in point_like)
            or (len(text) <= 40 and not low.startswith("с 01."))
        )
        if is_point:
            # Название пункта: начинаем новый stop в текущем блоке
            if current_block is None:
                current_block = {
                    "days": current_days,
                    "valid_from": current_valid_from,
                    "stops": [],
                }
            if current_block["stops"] and current_block["stops"][-1]["point"] == text:
                continue  # дубль названия
            current_point = text
            # Защита от повторов пустого пункта — добавим остановку позже с таблицей
            continue

        # Пометка-подзаголовок (например "в том числе рейсы ... до с/о ..."):
        # начинаем отдельный блок, чтобы пометка была перед своей группой.
        if current_block is not None and current_block["stops"]:
            flush()
            current_block = {
                "days": current_days,
                "valid_from": current_valid_from,
                "note": text,
                "stops": [],
            }

    flush()
    return blocks


def fetch_routes_from_landing():
    """Собирает номера и ссылки маршрутов с главной страницы."""
    resp = fetch(LANDING_URL)
    if resp is None:
        return [], None
    soup = BeautifulSoup(resp.text, "html.parser")

    detail = soup.find("div", class_="activity__detail")
    global_days_off = None
    if detail:
        m = re.search(r"Выходные дни\s*[-–:]\s*(.+)", clean(detail.get_text(" ", strip=True)))
        if m:
            global_days_off = clean(m.group(1))

    routes = {}
    order = []
    # Принимаем только "чистые" ссылки на страницы маршрутов вида /activity/<id>/
    route_href_re = re.compile(r"/activity/(\d+)/?\s*$")
    for link in soup.find_all("a", href=True):
        text = clean(link.get_text(" ", strip=True))
        href = link["href"]
        if not (1 <= len(text) <= 4):
            continue
        if not any(ch.isdigit() for ch in text):
            continue
        if route_href_re.search(href) is None:
            continue  # отсекаем пагинацию/news и пр.
        url = href if href.startswith("http") else BASE_URL + href
        key = (text, url)
        if key not in routes:
            routes[key] = key
            order.append(key)
    return [{"number": num, "url": url} for num, url in order], global_days_off


def parse_route(route):
    """Парсит одну страницу маршрута."""
    resp = fetch(route["url"])
    if resp is None:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")

    title_el = soup.find("h1", class_="activity__title") or soup.find("h1")
    title = clean(title_el.get_text(" ", strip=True)) if title_el else route["number"]

    detail = soup.find("div", class_="activity__detail")
    if detail is None:
        return None

    full_text = clean(detail.get_text(" ", strip=True))

    # Перевозчик — ищем в тексте строку после "Перевозчик – ..."
    carrier = None
    m = re.search(r"(Перевозчик\s*[–—-]\s*.*?)(?=Перевозчик|$)", full_text)
    if m:
        carrier = clean(m.group(1))

    blocks = extract_stops_from_detail(detail)

    # Сводка по дням работы на уровне маршрута (уникальные ограничения)
    days_notes = []
    for b in blocks:
        if b["days"] and b["days"] not in days_notes:
            days_notes.append(b["days"])

    route_data = {
        "number": route["number"],
        "name": title,
        "url": route["url"],
        "carrier": carrier,
        "days_notes": days_notes,
        "schedule": [b for b in blocks],
    }
    route_data["md5"] = md5_of({k: v for k, v in route_data.items() if k != "md5"})
    return route_data


def main():
    print("Шаг 1: собираем список маршрутов с главной страницы...")
    route_list, global_days_off = fetch_routes_from_landing()
    if not route_list:
        print("  Не удалось найти маршруты.")
        return
    print(f"  Найдено маршрутов: {len(route_list)}")
    print(f"  Общие выходные: {global_days_off}")

    routes = []
    for i, route in enumerate(route_list, 1):
        print(f"  [{i}/{len(route_list)}] Маршрут №{route['number']} ...")
        data = parse_route(route)
        if data is None:
            print(f"      ! Не удалось распарсить {route['url']}")
            continue
        routes.append(data)
        time.sleep(0.3)

    payload = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": LANDING_URL,
        "global_days_off": global_days_off,
        "routes_count": len(routes),
        "md5": "",
        "routes": routes,
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    overall = hashlib.md5(text.encode("utf-8")).hexdigest()
    final = text.replace('"md5": ""', '"md5": "' + overall + '"')

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(final)

    print(f"\nГотово. Маршрутов: {len(routes)}")
    print(f"Общий MD5 файла: {overall}")
    print(f"Файл сохранён: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
