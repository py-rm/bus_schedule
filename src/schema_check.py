# -*- coding: utf-8 -*-
"""
Набор проверок качества JSON-файлов расписания и новостей.

Работает в двух режимах:
- локально: `python schema_check.py` — простая проверка структуры;
- в облаке (gate перед публикацией): дополнительная передача `--expected`,
  чтобы поймать «резкое» сокращение числа маршрутов.

Про семантику результата (для облака и автоматики):
- код 0 — OK: всё в порядке, файл можно публиковать / ничего не делать;
- код 2 — WARN (мягкая тревога): есть замечания, но не критично.
  Например, маршрутов стало меньше на 1–3. Публиковать можно, но стоит
  уведомить администратора;
- код 1 — ERROR (жёсткая тревога): есть ошибки (повреждён JSON, маршрутов
  стало заметно меньше и т.п.). Публиковать НЕЛЬЗЯ — оставить предыдущий
  удачный файл и уведомить администратора.

Порог маршрутов:
- если фактическое число маршрутов меньше ожидаемого (аргумент `--expected`):
  - разница 1–3  -> WARN (продолжаем, но уведомляем);
  - разница >3   -> ERROR (останавливаем выпуск, уведомляем).
  Без `--expected` это сравнение не выполняется (работает только структура).
"""

import argparse
import hashlib
import json
import os
import re
import sys

TIME_RE = re.compile(r"^\d{2}:\d{2}$")
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")

DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCHEDULE = os.path.join(DIR, "dacha_schedule.json")
DEFAULT_NEWS = os.path.join(DIR, "dacha_news.json")

# Уровни серьёзности результата
OK = 0
ERROR = 1
WARN = 2


def canonical_json(obj):
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def md5_of(obj):
    return hashlib.md5(canonical_json(obj)).hexdigest()


def overall_md5(data):
    copy = dict(data)
    copy["md5"] = ""
    text = json.dumps(copy, ensure_ascii=False, indent=2)
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_schedule(path, results, expected=None):
    try:
        data = load(path)
    except FileNotFoundError:
        results.append((ERROR, "не найден файл: " + path))
        return
    except json.JSONDecodeError as exc:
        results.append((ERROR, "файл повреждён (JSON): {}: {}".format(path, exc)))
        return

    if not isinstance(data, dict):
        results.append((ERROR, "верхний уровень файла — не объект JSON"))
        return

    routes = data.get("routes")
    if not isinstance(routes, list):
        results.append((ERROR, "нет ключа 'routes' (список маршрутов)"))
        return

    declared = data.get("routes_count")
    if declared != len(routes):
        results.append((ERROR, "routes_count заявлено {}, фактически {}".format(declared, len(routes))))

    # Санкционированный порог: не сжимался ли список маршрутов заметно.
    if expected is not None:
        lost = expected - len(routes)
        if lost > 0:
            if lost > 3:
                results.append((ERROR,
                    "маршрутов стало меньше на {} (ожидалось {}, фактически {}): "
                    "остановить публикацию".format(lost, expected, len(routes))))
            else:
                results.append((WARN,
                    "маршрутов стало меньше на {} (ожидалось {}, фактически {}): "
                    "продолжить, но уведомить".format(lost, expected, len(routes))))
        elif lost < 0:
            results.append((WARN,
                "маршрутов стало БОЛЬШЕ, чем ожидалось (ожидалось {}, "
                "фактически {})".format(expected, len(routes))))

    seen = {}
    for route in routes:
        if not isinstance(route, dict):
            results.append((ERROR, "маршрут — не объект JSON"))
            continue
        number = str(route.get("number", ""))
        seen[number] = seen.get(number, 0) + 1
        for key in ("number", "name", "url"):
            val = route.get(key)
            if not isinstance(val, str) or not val.strip():
                results.append((ERROR, "маршрут {}: пустое поле '{}'".format(number or "?", key)))
        if route.get("md5") != md5_of({k: v for k, v in route.items() if k != "md5"}):
            results.append((ERROR, "маршрут {}: MD5 не совпадает с пересчитанным".format(number or "?")))
        if not route.get("carrier"):
            results.append((WARN, "маршрут {}: не найден перевозчик".format(number or "?")))

        schedule = route.get("schedule")
        if not isinstance(schedule, list) or not schedule:
            results.append((ERROR, "маршрут {}: нет блоков расписания".format(number or "?")))
            continue
        for b in schedule:
            if not isinstance(b, dict):
                results.append((ERROR, "маршрут {}: блок — не объект JSON".format(number or "?")))
                continue
            stops = b.get("stops")
            if not isinstance(stops, list) or not stops:
                results.append((ERROR, "маршрут {}: блок без остановок".format(number or "?")))
                continue
            vf = b.get("valid_from")
            if vf and not DATE_RE.fullmatch(str(vf)):
                results.append((ERROR, "маршрут {}: неверный формат даты '{}'".format(number or "?", vf)))
            for s in stops:
                if not isinstance(s, dict):
                    results.append((ERROR, "маршрут {}: остановка — не объект JSON".format(number or "?")))
                    continue
                point = str(s.get("point", ""))
                times = s.get("times")
                if not isinstance(times, list) or not times:
                    results.append((ERROR, "маршрут {}: пункт '{}' без времени".format(number or "?", point)))
                    continue
                prev = -1
                seen_times = set()
                for t in times:
                    t = str(t)
                    if not TIME_RE.fullmatch(t):
                        results.append((ERROR, "маршрут {}: '{}' — время '{}' не в формате HH:MM".format(number or "?", point, t)))
                        continue
                    h, m = int(t[:2]), int(t[3:])
                    if h > 23 or m > 59:
                        results.append((ERROR, "маршрут {}: '{}' — время '{}' вне 00:00–23:59".format(number or "?", point, t)))
                    if t in seen_times:
                        results.append((ERROR, "маршрут {}: '{}' — повтор времени '{}'".format(number or "?", point, t)))
                    seen_times.add(t)
                    cur = h * 60 + m
                    if cur < prev:
                        results.append((WARN, "маршрут {}: '{}' — время '{}' раньше предыдущего".format(number or "?", point, t)))
                    prev = cur

    dup = [n for n, c in seen.items() if c > 1]
    if dup:
        results.append((ERROR, "повторяющиеся номера маршрутов: " + ", ".join(dup)))

    if data.get("md5") != overall_md5(data):
        results.append((ERROR, "общий MD5 файла не совпадает с пересчитанным"))


def check_news(path, results):
    try:
        data = load(path)
    except FileNotFoundError:
        results.append((ERROR, "не найден файл: " + path))
        return
    except json.JSONDecodeError as exc:
        results.append((ERROR, "файл повреждён (JSON): {}: {}".format(path, exc)))
        return

    if not isinstance(data, dict):
        results.append((ERROR, "верхний уровень файла — не объект JSON"))
        return

    news = data.get("news")
    if not isinstance(news, dict):
        results.append((ERROR, "нет ключа 'news' с новостью"))
        return
    for key in ("news_id", "title", "url", "date", "text"):
        val = news.get(key)
        if not isinstance(val, str) or not val.strip():
            results.append((ERROR, "новость: пустое поле '{}'".format(key)))
    if news.get("md5") != md5_of({k: v for k, v in news.items() if k != "md5"}):
        results.append((ERROR, "MD5 новости не совпадает с пересчитанным"))
    if data.get("md5") != overall_md5(data):
        results.append((ERROR, "общий MD5 файла (news) не совпадает с пересчитанным"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", default=DEFAULT_SCHEDULE,
                        help="путь к dacha_schedule.json")
    parser.add_argument("--news", default=DEFAULT_NEWS,
                        help="путь к dacha_news.json")
    parser.add_argument("--expected", type=int, default=None,
                        help="ожидаемое число маршрутов; если задано, "
                             "проверяется падение их количества "
                             "(1–3 -> WARN, больше -> ERROR)")
    args = parser.parse_args()

    results = []
    print("Проверка расписания...")
    check_schedule(args.schedule, results, args.expected)
    print("Проверка новостей...")
    check_news(args.news, results)

    errors = [m for sev, m in results if sev == ERROR]
    warnings = [m for sev, m in results if sev == WARN]

    for line in errors:
        print("  [ОШИБКА] " + line)
    if warnings:
        print("  Предупреждения:")
        for line in warnings:
            print("  - " + line)

    print()
    print("ОШИБОК: {}".format(len(errors)))
    print("ЗАМЕЧАНИЙ: {}".format(len(warnings)))

    # Код возврата: 0 — OK, 2 — WARN (мягко, но уведомить), 1 — ERROR.
    if errors:
        sys.exit(ERROR)
    if warnings:
        sys.exit(WARN)
    sys.exit(OK)


if __name__ == "__main__":
    main()
