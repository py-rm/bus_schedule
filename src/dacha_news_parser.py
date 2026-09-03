# -*- coding: utf-8 -*-
"""
Парсер последней новости об изменениях садоводческих маршрутов Оренбурга.

Источник: RSS-лента официального портала, отфильтрованная по сфере
"садоводческие маршруты" (activity=16226):
https://orenburg.ru/presscenter/news/rss/?filter%5Bnews%5D%5Bactivity%5D=16226

RSS возвращает новости от свежих к старым, поэтому последняя (актуальная)
новость — это первый элемент <item> в ленте.

Скрипт запоминает новость через её уникальный news_id (число из ссылки вида
.../presscenter/news/<id>/). Если news_id не изменился — файл не трогаем
(новостей не появилось). Если появилась новая — перезаписываем dacha_news.json
с заголовком, ссылкой, датой, текстом и MD5-отпечатком новости.
"""

import datetime
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET

import requests

# RSS-лента новостей по сфере "садоводческие маршруты" (activity=16226)
RSS_URL = (
    "https://orenburg.ru/presscenter/news/rss/"
    "?filter%5Bnews%5D%5Bactivity%5D=16226"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

OUTPUT_FILE = "dacha_news.json"

# "33" из ".../presscenter/news/33/"
NEWS_ID_RE = re.compile(r"/presscenter/news/(\d+)/")


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


def clean(text):
    """Вычищает лишние whitespace из текста."""
    return re.sub(r"\s+", " ", text).strip() if text else ""


def fetch_rss():
    for attempt in range(3):
        try:
            resp = requests.get(RSS_URL, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            print(f"  ! Ошибка получения RSS: {exc} (попытка {attempt + 1}/3)")
            time.sleep(2 * (attempt + 1))
    return None


def parse_first_item(xml_text):
    """Возвращает dict с данными последней новости или None."""
    root = ET.fromstring(xml_text)
    # root = <rss><channel><item>...
    channel = root.find("channel")
    if channel is None:
        return None
    item = channel.find("item")
    if item is None:
        return None

    def txt(tag):
        el = item.find(tag)
        return clean(el.text) if el is not None and el.text else ""

    title = txt("title")
    link = txt("link")
    pub_date = txt("pubDate")
    description = txt("description")

    if not title and not link:
        return None

    news_id = None
    m = NEWS_ID_RE.search(link)
    if m:
        news_id = m.group(1)

    return {
        "news_id": news_id,
        "title": title,
        "url": link,
        "date": pub_date,
        "text": description,
    }


def load_previous():
    """Читает уже сохранённую новость из JSON, если файл есть."""
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "news" in data:
            return data["news"]
    except (OSError, ValueError):
        pass
    return None


def main():
    print("Получаем RSS-ленту новостей (садоводческие маршруты)...")
    xml_text = fetch_rss()
    if xml_text is None:
        print("  Не удалось загрузить RSS.")
        return

    try:
        news = parse_first_item(xml_text)
    except ET.ParseError as exc:
        print(f"  ! Ошибка разбора RSS (XML): {exc}")
        return

    if news is None:
        print("  В ленте не нашлось новостей.")
        return

    news["md5"] = md5_of({k: v for k, v in news.items() if k != "md5"})

    previous = load_previous()
    if previous is not None and previous.get("md5") == news["md5"]:
        print("  Новая новость не появилась — файл не меняем.")
        print(f"  Текущая новость: {previous.get('title')}")
        return

    payload = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "feed_url": RSS_URL,
        "news": news,
        "md5": "",
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    overall = hashlib.md5(text.encode("utf-8")).hexdigest()
    final = text.replace('"md5": ""', '"md5": "' + overall + '"')

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(final)

    print(f"\nНовая новость от {news.get('date')}:")
    print(f"  {news.get('title')}")
    print(f"  {news.get('url')}")
    print(f"Общий MD5 файла: {overall}")
    print(f"Файл сохранён: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
