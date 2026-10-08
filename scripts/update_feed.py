#!/usr/bin/env python3
"""
Оновлює feed.xml (фід для імпорту в Prom.ua) цінами та наявністю
з Google Sheet, опублікованого для читання в форматі CSV.

Метадані товарів (назва, категорія, фото, опис, характеристики) лежать
у data/products/<id>.json і редагуються через адмінку /admin (Sveltia CMS).
З Google Sheet підтягуються тільки ціна та наявність: текст у таблиці
"Найменування і характеристики" не має фіксованої структури, і його
автоматичний розбір на структуровані поля був би ненадійним.

Генерує кілька фідів (див. FEEDS): основний feed.xml і окремі фіди
під конкретних клієнтів з іншими цінами.

Запускається через .github/workflows/update-feed.yml - за розкладом
і після кожної зміни товарів в адмінці. Якщо дані товарів некоректні,
фіди не перезаписуються, а скрипт завершується з помилкою.
"""

import csv
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

from translate_ru import LABELS_RU, to_ru, translate_value_ru

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_DIR = ROOT / "data" / "products"
SITE_URL = "https://energia24.com.ua"

# Кожен фід: звідки брати ціни і куди писати результат.
#   name_col / stock_col - індекси колонок (stock_col=None - наявність визначається лише ціною);
#   price_col - індекс колонки або назва заголовка, яку шукаємо в таблиці;
#   rate - множник для ціни з таблиці (курс USD->UAH), якщо прайс у доларах;
#   skip_missing - True: товари, яких немає в таблиці, не потрапляють у фід взагалі
#                  (для клієнтських фідів, де прайс містить тільки частину асортименту).
FEEDS = [
    {
        "path": ROOT / "feed.xml",
        "sheet_url": (
            "https://docs.google.com/spreadsheets/d/"
            "1vxMdT03FDGt2yi9u_b8RNWlek1avd4rzngiv_ptJBPA/export"
            "?format=csv&gid=1763821507"
        ),
        "name_col": 1,
        "price_col": 5,
        "stock_col": None,
        "currency": "UAH",
        "skip_missing": False,
    },
    {
        # Клієнт PA: дилерський прайс у доларах, ціна з колонки "До 5 шт",
        # у фід іде в гривнях за фіксованим курсом.
        "path": ROOT / "pa.xml",
        "sheet_url": (
            "https://docs.google.com/spreadsheets/d/"
            "1OXsQttcSS0pSZrGsuZOVnJ8y6ahDiOTUh53P2F2Hzu8/export"
            "?format=csv&gid=672977454"
        ),
        "name_col": 0,
        "price_col": "До 5 шт",
        "stock_col": 3,
        "rate": 45,
        "currency": "UAH",
        "skip_missing": True,
        # Фото для фіду PA: images/pa/<id товару>.jpg;
        # якщо такого немає - беремо звичайне фото.
        "photo_dir": "images/pa",
        # <name>/<description> - російською (Prom.ua вважає їх російською версією).
        "russian": True,
    },
]

# id -> (назва, portal_id - ID відповідної категорії в каталозі Prom.ua,
#        щоб маркетплейс не вгадував категорію сам і не плутав, напр., із Samsung).
# ID звірені з категоріями конкурентів, що продають ті самі бренди (MUST/Felicity/EcoFlow).
CATEGORIES = {
    1: ("Інвертори", 5140401),
    2: ("Акумулятори", 5280501),
    3: ("Системи зберігання енергії 2 в 1", 14191106),
    4: ("Зарядні станції", 71109),
}

REQUIRED_FIELDS = ("id", "category", "vendor", "name", "key", "summary")


def load_products():
    """Читає data/products/*.json, перевіряє і повертає увімкнені товари
    у порядку фіду (категорія, потім поле "order").

    При будь-якій помилці в даних - завершує скрипт, щоб не зіпсувати фіди."""
    products, errors = [], []
    for path in sorted(PRODUCTS_DIR.glob("*.json")):
        try:
            p = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            errors.append(f"{path.name}: некоректний JSON ({e})")
            continue
        missing = [f for f in REQUIRED_FIELDS if p.get(f) in (None, "")]
        if missing:
            errors.append(f"{path.name}: не заповнено {', '.join(missing)}")
            continue
        # Адмінка може зберегти числа рядком - приводимо до int.
        try:
            p["id"], p["category"] = int(p["id"]), int(p["category"])
            p["order"] = int(p.get("order") or 0)
        except (TypeError, ValueError):
            errors.append(f"{path.name}: id, категорія і порядок мають бути числами")
            continue
        if p["category"] not in CATEGORIES:
            errors.append(f"{path.name}: невідома категорія {p['category']!r}")
        photo = p.get("photo") or ""
        if photo and not (ROOT / photo.lstrip("/")).is_file():
            errors.append(f"{path.name}: фото {photo!r} не знайдено")
        for i, row in enumerate(p.get("specs") or [], 1):
            if not (row.get("label") or "").strip() or not (row.get("value") or "").strip():
                errors.append(f"{path.name}: характеристика №{i} без назви або значення")
        p["_file"] = path.name
        products.append(p)

    ids = {}
    for p in products:
        if p["id"] in ids:
            errors.append(f"{p['_file']}: id={p['id']} вже є у {ids[p['id']]}")
        ids[p["id"]] = p["_file"]
    if errors:
        sys.exit("[error] помилки в даних товарів, фіди не оновлено:\n  " + "\n  ".join(errors))

    products = [p for p in products if p.get("enabled", True)]
    products.sort(key=lambda p: (p["category"], p.get("order") or 0, p["id"]))
    return products


def build_description(p, russian):
    """Опис товару для фіду: короткий текст + характеристики (якщо є).

    Повертає (опис для <description>, опис для <description_ua>)."""
    pid, desc, specs = p["id"], p["summary"], p.get("specs") or []
    to_lang = to_ru if russian else (lambda t: t)
    if not specs:
        return to_lang(desc), desc

    # Короткі дані з опису (вага, енергія) можуть розходитися з даташитом,
    # тому при наявності характеристик лишаємо з опису лише назву і функцію підігріву.
    intro = desc.split(". ")[0].rstrip(".") + "."
    if "вбудований підігрів" in desc:
        intro += " Функція: вбудований підігрів."

    def render(intro_text, heading, rows):
        items = "".join(f"<li><b>{label}:</b> {value}</li>" for label, value in rows)
        return f"<p>{intro_text}</p><h3>{heading}</h3><ul>{items}</ul>"

    desc_ua = render(intro, "Технічні характеристики", [(r["label"], r["value"]) for r in specs])
    if not russian:
        return desc_ua, desc_ua
    rows_ru = []
    for r in specs:
        label_ru = r.get("label_ru") or LABELS_RU.get(r["label"])
        if not label_ru:
            print(f"[warn] id={pid}: немає перекладу назви характеристики {r['label']!r}", file=sys.stderr)
            label_ru = r["label"]
        rows_ru.append((label_ru, r.get("value_ru") or translate_value_ru(r["value"])))
    desc_ru = render(to_ru(intro), "Технические характеристики", rows_ru)
    if re.search(r"[ІіЇїЄєҐґ]", desc_ru):
        print(f"[warn] неповний переклад характеристик id={pid}: {desc_ru!r}", file=sys.stderr)
    return desc_ru, desc_ua


def fetch_rows(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    return list(csv.reader(io.StringIO(raw)))


def find_column(rows, header):
    for row in rows:
        for i, cell in enumerate(row):
            if cell.strip().lower() == header.lower():
                return i
    sys.exit(f"[error] колонку {header!r} не знайдено в таблиці")


def match_prices(products, rows, cfg):
    """Повертає {product_id: (price:int|None, available:bool)}"""
    name_col, stock_col = cfg["name_col"], cfg["stock_col"]
    price_col = cfg["price_col"]
    if isinstance(price_col, str):
        price_col = find_column(rows, price_col)
    min_len = max(c for c in (name_col, price_col, stock_col) if c is not None) + 1

    result = {}
    for p in products:
        pid, key = p["id"], p["key"].strip()
        matches = [row for row in rows if len(row) >= min_len and key.lower() in (row[name_col] or "").lower()]
        if len(matches) == 0:
            print(f"[warn] {cfg['path'].name}: товар id={pid} (key={key!r}) не знайдено в таблиці", file=sys.stderr)
            result[pid] = None
            continue
        if len(matches) > 1:
            print(f"[warn] {cfg['path'].name}: товар id={pid} (key={key!r}) неоднозначний ({len(matches)} збігів)", file=sys.stderr)
            result[pid] = None
            continue
        row = matches[0]
        price_cell = (row[price_col] or "").strip().replace(" ", "")
        in_stock = stock_col is None or bool((row[stock_col] or "").strip())
        if re.fullmatch(r"\d+([.,]\d+)?", price_cell):
            price = round(float(price_cell.replace(",", ".")) * cfg.get("rate", 1))
            result[pid] = (price, in_stock)
        else:
            result[pid] = (None, False)
    return result


def build_feed(products, price_map, date_str, currency, skip_missing, photo_dir=None, russian=False):
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<!DOCTYPE yml_catalog SYSTEM "shops.dtd">')
    lines.append(f'<yml_catalog date="{date_str}">')
    lines.append('  <shop>')
    lines.append('    <name>ENERGIA24</name>')
    lines.append('    <company>ENERGIA24</company>')
    lines.append(f'    <url>{SITE_URL}/</url>')
    lines.append('    <currencies>')
    lines.append(f'      <currency id="{currency}" rate="1"/>')
    lines.append('    </currencies>')
    lines.append('    <categories>')
    for cid, (cname, portal_id) in CATEGORIES.items():
        lines.append(f'      <category id="{cid}" portal_id="{portal_id}">{cname}</category>')
    lines.append('    </categories>')
    lines.append('    <offers>')

    current_cat = None
    for p in products:
        pid, cat, name = p["id"], p["category"], p["name"]
        update = price_map.get(pid)
        if update is None and skip_missing:
            continue
        if cat != current_cat:
            lines.append('')
            current_cat = cat
        if update is None:
            # немає надійних даних з таблиці - лишаємо позицію недоступною,
            # щоб не публікувати застарілу ціну без підтвердження.
            available = "false"
            price_line = None
        else:
            price, is_avail = update
            available = "true" if is_avail else "false"
            price_line = price

        lines.append(f'      <offer id="{pid}" available="{available}">')
        # Prom.ua вважає <name>/<description> російським варіантом, а *_ua - українським.
        # Без перекладу дублюємо українську в обидва, інакше товар позначається
        # як "Відсутня назва українською".
        name_ru = (p.get("name_ru") or to_ru(name)) if russian else name
        desc_ru, desc_ua = build_description(p, russian)
        lines.append(f'        <name>{name_ru}</name>')
        lines.append(f'        <name_ua>{name}</name_ua>')
        if price_line is not None:
            lines.append(f'        <price>{price_line}</price>')
        lines.append(f'        <currencyId>{currency}</currencyId>')
        lines.append(f'        <categoryId>{cat}</categoryId>')
        if photo_dir and (ROOT / photo_dir / f"{pid}.jpg").exists():
            lines.append(f'        <picture>{SITE_URL}/{photo_dir}/{pid}.jpg</picture>')
        elif p.get("photo"):
            lines.append(f'        <picture>{SITE_URL}/{p["photo"].lstrip("/")}</picture>')
        lines.append(f'        <vendor>{p["vendor"]}</vendor>')
        lines.append(f'        <description><![CDATA[{desc_ru}]]></description>')
        lines.append(f'        <description_ua><![CDATA[{desc_ua}]]></description_ua>')
        lines.append('      </offer>')

    lines.append('')
    lines.append('    </offers>')
    lines.append('  </shop>')
    lines.append('</yml_catalog>')
    lines.append('')
    return "\n".join(lines)


def main():
    import datetime

    products = load_products()
    date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    feeds = []
    for cfg in FEEDS:
        rows = fetch_rows(cfg["sheet_url"])
        price_map = match_prices(products, rows, cfg)
        feed = build_feed(products, price_map, date_str, cfg["currency"], cfg["skip_missing"],
                          cfg.get("photo_dir"), cfg.get("russian", False))
        feeds.append((cfg["path"], feed))
    # Пишемо лише коли всі фіди зібрано, щоб збій однієї таблиці не лишив їх неузгодженими.
    for path, feed in feeds:
        path.write_text(feed, encoding="utf-8")
        print(f"{path.name} оновлено ({date_str} UTC)")


if __name__ == "__main__":
    main()
