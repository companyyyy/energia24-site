#!/usr/bin/env python3
"""
Генерує XML-фіди для Prom.ua (feed.xml, pa.xml) з даних товарів
у data/products/<id>.json.

Усе - назви, фото, описи, характеристики, ціни й наявність - редагується
в адмінці: ціни для обох фідів - таблицею на /admin/, решта - у редакторі /admin/cms/ (Sveltia CMS).
Ціни в даних уже в гривнях, як підуть у фід.

Генерує кілька фідів (див. FEEDS): основний feed.xml і окремі фіди
під конкретних клієнтів з іншими цінами.

Запускається через .github/workflows/update-feed.yml після кожної зміни
товарів. Якщо дані товарів некоректні, фіди не перезаписуються, а скрипт
завершується з помилкою.
"""

import datetime
import json
import re
import sys
from pathlib import Path

from translate_ru import LABELS_RU, to_ru, translate_value_ru

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_DIR = ROOT / "data" / "products"
SITE_URL = "https://energia24.com.ua"

# Кожен фід: куди писати і з яких полів товару брати ціну/наявність.
#   price_field / stock_field - поля в data/products/*.json;
#   include_field - якщо задано, у фід потрапляють лише товари з цим полем = true
#                   (для клієнтських фідів, де прайс містить тільки частину асортименту).
FEEDS = [
    {
        "path": ROOT / "feed.xml",
        "price_field": "price",
        "stock_field": "in_stock",
        "currency": "UAH",
    },
    {
        # Клієнт PA: окремі (дилерські) ціни і власний набір товарів.
        "path": ROOT / "pa.xml",
        "price_field": "pa_price",
        "stock_field": "pa_in_stock",
        "include_field": "pa",
        "currency": "UAH",
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

REQUIRED_FIELDS = ("id", "category", "vendor", "name", "summary")


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
        for f in ("price", "pa_price"):
            v = p.get(f)
            if v in ("", None):
                p[f] = None
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                errors.append(f"{path.name}: ціна {f}={v!r} має бути додатним числом або порожньою")
            else:
                p[f] = round(v)
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


def build_feed(products, cfg, date_str):
    currency, photo_dir, russian = cfg["currency"], cfg.get("photo_dir"), cfg.get("russian", False)
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
        if cfg.get("include_field") and not p.get(cfg["include_field"]):
            continue
        if cat != current_cat:
            lines.append('')
            current_cat = cat
        # Без ціни товар не може бути в наявності.
        price_line = p.get(cfg["price_field"])
        available = "true" if price_line is not None and p.get(cfg["stock_field"]) else "false"

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
    products = load_products()
    date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    for cfg in FEEDS:
        path = cfg["path"]
        path.write_text(build_feed(products, cfg, date_str), encoding="utf-8")
        print(f"{path.name} оновлено ({date_str} UTC)")


if __name__ == "__main__":
    main()
