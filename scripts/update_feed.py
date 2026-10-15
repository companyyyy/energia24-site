#!/usr/bin/env python3
"""
Генерує XML-фіди для Prom.ua з даних товарів data/products/<id>.json і
налаштувань фідів data/feeds.json. Усе це редагується в адмінці /admin/
(ціни, гурт, курс, галочка «В наявності», клієнтські фіди) і в редакторі
товарів /admin/cms/ (назви, фото, описи, характеристики).

Фіди:
  feed.xml          - роздріб: ціна товару (з фіду avtonomka або вручну);
  pa.xml            - опт: гуртова ціна $ × курс; товари без гуртової ціни не йдуть;
  feed/<назва>.xml  - клієнтські фіди: роздріб або опт ± відсоток ± випадкова надбавка.

Наявність у всіх фідах: НЕ off (галочка в адмінці) І (in_stock з фіду avtonomka,
а для товарів, яких у avtonomka немає, - завжди). Товар без ціни або без фото у фід не йде.

Запускається з .github/workflows/update-feed.yml після кожної зміни товарів/фідів
і з site-catalog.yml після оновлення цін з avtonomka. Якщо дані некоректні,
фіди не перезаписуються, а скрипт завершується з помилкою.
"""

import datetime
import json
import random
import re
import sys
from pathlib import Path

from translate_ru import LABELS_RU, to_ru, translate_value_ru

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_DIR = ROOT / "data" / "products"
FEEDS_CONFIG = ROOT / "data" / "feeds.json"
FEEDS_BUILT = ROOT / "data" / "feeds_built.json"
SITE_URL = "https://energia24.com.ua"

# Основні фіди. base: "retail" - роздрібна ціна, "wholesale" - гуртова $ × курс.
MAIN_FEEDS = [
    {"file": "feed.xml", "base": "retail"},
    {
        # Опт (клієнт PA). Фото для нього: images/pa/<id товару>.jpg, якщо є.
        "file": "pa.xml",
        "base": "wholesale",
        "photo_dir": "images/pa",
        # <name>/<description> - російською (Prom.ua вважає їх російською версією).
        "russian": True,
    },
]
# Імена, які не можна дати клієнтському фіду.
RESERVED = {"feed.xml", "pa.xml", "sitemap.xml", "prom.xml"}

# id -> (назва, portal_id - ID категорії в каталозі Prom.ua).
# id групи ніколи не перенумеровувати, лише додавати нові.
CATEGORIES = {
    1: ("Інвертори", 5140401),
    2: ("Акумулятори", 5280501),
    3: ("Системи зберігання енергії 2 в 1", 14191106),
    4: ("Зарядні станції", 71109),
    5: ("Кабельна продукція", 501001),
    6: ("Безперебійники для роутерів", 501001),
    7: ("Автоматичне введення резерву (АВР)", 501001),
    8: ("Комплекти автономного енергоживлення", 501001),
}
# Ці групи пишуться в кожен фід; решта - лише якщо у фіді є їхні товари.
BASE_CATEGORIES = (1, 2, 3, 4)

# Виробники, які є в базі Prom; інші у <vendor> не пишемо.
PROM_VENDORS = {"must", "felicity", "deye", "dyness", "ecoflow", "kbe"}

REQUIRED_FIELDS = ("id", "category", "name", "summary")
DFI = re.compile(r"dfi|дфі|дфи", re.I)


def load_products():
    """Читає data/products/*.json, перевіряє і повертає увімкнені товари
    у порядку фіду (категорія, потім поле "order")."""
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
        v = p.get("price")
        if v in ("", None):
            p["price"] = None
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            errors.append(f"{path.name}: ціна {v!r} має бути додатним числом або порожньою")
        else:
            p["price"] = round(v)
        v = p.get("wholesale_usd")
        if v in ("", None):
            p["wholesale_usd"] = 0
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            errors.append(f"{path.name}: гуртова ціна {v!r} має бути числом ≥ 0")
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


def load_feeds_config():
    """data/feeds.json: клієнтські фіди і курс $. Повертає (feeds, usd_rate)."""
    cfg = json.loads(FEEDS_CONFIG.read_text(encoding="utf-8")) if FEEDS_CONFIG.exists() else {}
    rate = cfg.get("usd_rate", 45)
    errors = []
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 1 <= rate <= 1000:
        errors.append(f"курс $ {rate!r} має бути числом від 1 до 1000")
    feeds, files = [], set()
    for f in cfg.get("feeds") or []:
        name = f.get("file", "")
        if not re.fullmatch(r"feed/[a-z0-9][a-z0-9-]*\.xml", name) or name in RESERVED:
            errors.append(f"фід {f.get('name')!r}: неприпустимий файл {name!r}")
            continue
        if name in files:
            errors.append(f"фід {name}: файл повторюється")
        files.add(name)
        pct = f.get("percent", 0)
        if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not -90 <= pct <= 500:
            errors.append(f"фід {name}: відсоток {pct!r} має бути від -90 до 500")
        has_min, has_max = "add_min" in f, "add_max" in f
        if has_min != has_max:
            errors.append(f"фід {name}: надбавка має бути «від» і «до» разом")
        elif has_min and not (isinstance(f["add_min"], int) and isinstance(f["add_max"], int)
                              and f["add_min"] <= f["add_max"]):
            errors.append(f"фід {name}: надбавка - цілі числа, «від» ≤ «до»")
        if f.get("base") not in (None, "wholesale"):
            errors.append(f"фід {name}: невідома основа {f.get('base')!r}")
        feeds.append({
            "file": name,
            "base": f.get("base") or "retail",
            "percent": pct,
            "add": (f["add_min"], f["add_max"]) if has_min else None,
            "photo_dir": "images/pa",
            "russian": True,
        })
    if errors:
        sys.exit("[error] помилки в data/feeds.json, фіди не оновлено:\n  " + "\n  ".join(errors))
    return feeds, rate


def base_price(p, base, rate):
    if base == "wholesale":
        usd = p.get("wholesale_usd") or 0
        return round(usd * rate, 2) if usd > 0 else None
    return p.get("price")


def feed_price(p, cfg, rate):
    """Ціна товару у фіді або None, якщо товар у цей фід не йде."""
    base = base_price(p, cfg["base"], rate)
    if base is None:
        return None
    pct, add = cfg.get("percent", 0), cfg.get("add")
    if not pct and not add:
        return base
    value = base * (1 + pct / 100) + (random.randint(*add) if add else 0)
    return round(max(1, value), 2)


def fmt_price(v):
    v = round(v, 2)
    return str(int(v)) if v == int(v) else f"{v:.2f}"


def is_available(p):
    if p.get("off"):
        return False
    return bool(p.get("in_stock")) if p.get("avtonomka_id") else True


def photo_url(p, photo_dir):
    pid = p["id"]
    if photo_dir and (ROOT / photo_dir / f"{pid}.jpg").exists():
        return f"{SITE_URL}/{photo_dir}/{pid}.jpg"
    if p.get("photo"):
        return f"{SITE_URL}/{p['photo'].lstrip('/')}"
    return None


def build_description(p, russian):
    """Опис товару для фіду: короткий текст + характеристики (якщо є).

    Повертає (опис для <description>, опис для <description_ua>)."""
    # Товари, додані з фіду avtonomka: готові описи UA і RU.
    if p.get("description_ua_html"):
        ua = p["description_ua_html"]
        return (p.get("description_ru_html") or ua) if russian else ua, ua

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


def esc(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_feed(products, cfg, rate, date_str, report):
    photo_dir, russian = cfg.get("photo_dir"), cfg.get("russian", False)
    offers = []
    for p in products:
        price = feed_price(p, cfg, rate)
        picture = photo_url(p, photo_dir)
        if price is None:
            if cfg["base"] == "retail":
                report.append(f"{cfg['file']}: id={p['id']} без ціни - не йде у фід")
            continue
        if not picture:
            report.append(f"{cfg['file']}: id={p['id']} без фото - не йде у фід")
            continue
        offers.append((p, price, picture))

    used = {p["category"] for p, _, _ in offers}
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<!DOCTYPE yml_catalog SYSTEM "shops.dtd">')
    lines.append(f'<yml_catalog date="{date_str}">')
    lines.append('  <shop>')
    lines.append('    <name>ENERGIA24</name>')
    lines.append('    <company>ENERGIA24</company>')
    lines.append(f'    <url>{SITE_URL}/</url>')
    lines.append('    <currencies>')
    lines.append('      <currency id="UAH" rate="1"/>')
    lines.append('    </currencies>')
    lines.append('    <categories>')
    for cid, (cname, portal_id) in CATEGORIES.items():
        if cid in BASE_CATEGORIES or cid in used:
            lines.append(f'      <category id="{cid}" portal_id="{portal_id}">{cname}</category>')
    lines.append('    </categories>')
    lines.append('    <offers>')

    current_cat = None
    for p, price, picture in offers:
        pid, cat, name = p["id"], p["category"], p["name"]
        if cat != current_cat:
            lines.append('')
            current_cat = cat
        available = "true" if is_available(p) else "false"
        lines.append(f'      <offer id="{pid}" available="{available}">')
        # Prom.ua вважає <name>/<description> російським варіантом, а *_ua - українським.
        name_ru = (p.get("name_ru") or to_ru(name)) if russian else name
        desc_ru, desc_ua = build_description(p, russian)
        lines.append(f'        <name>{esc(name_ru)}</name>')
        lines.append(f'        <name_ua>{esc(name)}</name_ua>')
        lines.append(f'        <price>{fmt_price(price)}</price>')
        lines.append('        <currencyId>UAH</currencyId>')
        lines.append(f'        <categoryId>{cat}</categoryId>')
        lines.append(f'        <picture>{esc(picture)}</picture>')
        vendor = (p.get("vendor") or "").strip()
        if vendor.lower() in PROM_VENDORS:
            lines.append(f'        <vendor>{esc(vendor)}</vendor>')
        lines.append(f'        <description><![CDATA[{desc_ru}]]></description>')
        lines.append(f'        <description_ua><![CDATA[{desc_ua}]]></description_ua>')
        lines.append('      </offer>')

    lines.append('')
    lines.append('    </offers>')
    lines.append('  </shop>')
    lines.append('</yml_catalog>')
    lines.append('')
    text = "\n".join(lines)
    m = DFI.search(text)
    if m:
        sys.exit(f"[error] у {cfg['file']} знайдено {m.group(0)!r} - фіди не оновлено: "
                 f"…{text[max(0, m.start() - 80):m.end() + 80]!r}…")
    return text


def strip_date(text):
    return re.sub(r'<yml_catalog date="[^"]*">', "<yml_catalog>", text, count=1)


def main():
    products = load_products()
    client_feeds, rate = load_feeds_config()
    date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    report = []
    built = {}
    for cfg in MAIN_FEEDS + client_feeds:
        built[cfg["file"]] = build_feed(products, cfg, rate, date_str, report)

    for name, new in built.items():
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # Якщо змінилась лише дата в заголовку - файл не чіпаємо, щоб фід (напр. pa.xml)
        # не «оновлювався» без жодних змін у товарах.
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        if strip_date(old) == strip_date(new):
            print(f"{name}: змін немає")
            continue
        path.write_text(new, encoding="utf-8")
        print(f"{name} оновлено ({date_str} UTC)")

    # Файли клієнтських фідів, прибраних в адмінці, видаляємо (лише ті, що будували самі).
    prev = json.loads(FEEDS_BUILT.read_text(encoding="utf-8")) if FEEDS_BUILT.exists() else []
    current = sorted(f["file"] for f in client_feeds)
    for name in prev:
        if name not in current and (ROOT / name).is_file():
            (ROOT / name).unlink()
            print(f"{name} видалено (фід прибрано в адмінці)")
    if prev != current:
        FEEDS_BUILT.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for line in report:
        print("  " + line)


if __name__ == "__main__":
    main()
