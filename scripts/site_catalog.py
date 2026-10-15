#!/usr/bin/env python3
"""
Каталог товарів на сайті (index.html): ціни з фіду avtonomka + рішення з адмінки.

Дані - data/site/catalog.json, редагуються на /admin/site.html:
  - які категорії й товари показувати на сайті (enabled);
  - ручна ціна / наявність.

Команди:
  sync   - бере ціни й наявність з фіду avtonomka (SOURCE у catalog.json).
           Правила:
             * вимкнені товари і товари вимкнених категорій НЕ змінюються взагалі;
             * ціна/наявність перезаписуються лише тоді, коли вони змінились у фіді
               (feed_price/feed_available - останні побачені значення), тому ручна
               ціна з адмінки діє до наступної зміни ціни у фіді;
             * товари, яких немає у фіді, видаляються із сайту;
             * категорії з excluded_categories (напр. «Комплекти», id 11) на сайт не потрапляють;
             * нові товари й категорії з фіду додаються одразу ввімкненими
               (вимкнути можна в адмінці; товар вимкненої категорії на сайті не видно).
           Те саме для роздрібних цін фіду Prom feed.xml: товари data/products/*.json
           з полем avtonomka_id отримують price/in_stock з фіду avtonomka за тими ж правилами
           (вимкнені не оновлюються, ручна ціна з /admin/ діє до зміни ціни у фіді).
           Зник із фіду - «немає в наявності» (з фіду Prom не видаляємо: за id його знає Prom).
           Гуртові ціни (wholesale_usd), галочка off і налаштування фідів не змінюються.
           Нові товари avtonomka одразу створюються в data/products (тексти UA/RU і фото
           на білому фоні з фіду avtonomka) і йдуть у фіди; у фід опту - лише після того,
           як в адмінці вписати гуртову ціну. Товарам з avtonomka_id без фото фото теж
           підтягується з avtonomka.
  build  - генерує картки товарів і меню в index.html між маркерами
           <!-- CATALOG:START/END --> і <!-- NAV:START/END -->.

Запускається з .github/workflows/site-catalog.yml (3 рази на день і після збережень в адмінці).
"""

import datetime
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "site" / "catalog.json"
PRODUCTS_DIR = ROOT / "data" / "products"
INDEX = ROOT / "index.html"
PHOTOS_DIR = ROOT / "images" / "products"

# Категорія у фіді avtonomka -> категорія фідів Prom (scripts/update_feed.py, CATEGORIES).
AVT_TO_PROM_CATEGORY = {"1": 1, "2": 2, "3": 3, "4": 5, "5": 4, "6": 6, "7": 7, "11": 8}
# Кирилиця, схожа на латиницю, - в артикулах avtonomka трапляється (напр. «SE-F16-С»).
LOOKALIKE = str.maketrans("АВСЕНКМОРТХ", "ABCEHKMOPTX")


def model_key(text):
    return re.sub(r"[^0-9A-Z]", "", (text or "").upper().translate(LOOKALIKE))


def relink(entries, feed_items, title_of, link_field):
    """avtonomka інколи переносить товар на новий id. Запис, чий id зник із фіду (або без id),
    переходить на новий товар фіду з тим самим артикулом, якщо такий збіг єдиний.
    Повертає список описів перепривʼязок."""
    linked = {e.get(link_field) for e in entries if e.get(link_field) in feed_items}
    orphans = [e for e in entries if e.get(link_field) not in feed_items]
    done = []
    for fid, f in feed_items.items():
        code = model_key(f["code"])
        if fid in linked or len(code) < 5:
            continue
        hits = [e for e in orphans if code in model_key(title_of(e))]
        if len(hits) != 1:
            continue
        e = hits[0]
        done.append(f"{title_of(e)}: avtonomka {e.get(link_field)} -> {fid} (той самий артикул {f['code']})")
        e[link_field] = fid
        # Скинути «останні побачені» значення, щоб ціна й наявність оновились одразу.
        for k in ("feed_price", "feed_available", "feed_in_stock"):
            e.pop(k, None)
        orphans.remove(e)
        linked.add(fid)
    return done
DFI = re.compile(r"dfi|дфі|дфи", re.I)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def save_catalog(cat):
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- sync

def fetch_feed(url):
    req = urllib.request.Request(url, headers={"User-Agent": "energia24-site-sync"})
    with urllib.request.urlopen(req, timeout=60) as res:
        return ET.fromstring(res.read())


def specs_from_description(desc):
    """Пункти списку «Основні характеристики» з HTML-опису фіду."""
    m = re.search(r"Основні характеристики:?</strong></p>\s*<ul>(.*?)</ul>", desc or "", re.S)
    if not m:
        return []
    return [html.unescape(re.sub(r"<[^>]+>", "", li)).strip() for li in re.findall(r"<li>(.*?)</li>", m.group(1))]


def parse_price(text):
    try:
        v = round(float((text or "").replace(",", ".")))
    except ValueError:
        return None
    return v if v > 0 else None


def sync(cat):
    root = fetch_feed(cat["source"])
    feed_cats = {c.get("id"): (c.text or "").strip() for c in root.iter("category")}
    feed_items = {}
    for f in root.iter("item"):
        feed_items[f.get("id")] = {
            "name": (f.findtext("name_ua") or f.findtext("name") or "").strip(),
            "name_ru": (f.findtext("name") or "").strip(),
            "category": (f.findtext("categoryId") or "").strip(),
            "price": parse_price(f.findtext("priceuah")),
            "available": (f.findtext("available") or "").strip().lower() == "true",
            "image": (f.findtext("image") or "").strip(),
            "images": [(i.text or "").strip() for i in f.findall("image") if (i.text or "").strip()],
            "description": f.findtext("description_ua") or "",
            "description_ru": f.findtext("description") or "",
            "vendor": (f.findtext("vendor") or "").strip(),
            "code": (f.findtext("vendorCode") or "").strip(),
        }
    if not feed_items:
        raise RuntimeError("фід порожній або не розпізнаний - каталог не змінено")

    changes = []
    # Категорії avtonomka, яких на сайті не має бути зовсім (excluded_categories у catalog.json):
    # їхні товари не додаються й прибираються із сайту. На фіди Prom це не впливає.
    excluded = set(cat.get("excluded_categories") or [])
    for it in [it for it in cat["items"] if it["category"] in excluded]:
        changes.append(f"{it['title']}: категорію виключено -> видалено із сайту")
        cat["items"].remove(it)
    cat["categories"] = [c for c in cat["categories"] if c["id"] not in excluded]
    cats = {c["id"]: c for c in cat["categories"]}

    # Нові категорії - одразу ввімкненими.
    for cid, name in feed_cats.items():
        if cid not in cats and cid not in excluded:
            c = {"id": cid, "enabled": True, "anchor": f"cat-{cid}", "nav": name, "eyebrow": "Каталог",
                 "title": name, "lead": ""}
            cat["categories"].append(c)
            cats[cid] = c
            changes.append(f"нова категорія {name!r}")

    for line in relink(cat["items"], feed_items, lambda it: it["title"], "feed_id"):
        changes.append(line)

    # Товарів немає у фіді - видаляємо із сайту. Але якщо зникла більшість,
    # це швидше за все збій фіду, тоді нічого не видаляємо.
    missing = [it for it in cat["items"] if it.get("feed_id") not in feed_items]
    if len(missing) > len(cat["items"]) / 2:
        print(f"::warning::у фіді немає {len(missing)} з {len(cat['items'])} товарів сайту - схоже на збій фіду, нічого не видалено")
    else:
        for it in missing:
            changes.append(f"{it['title']}: немає у фіді -> видалено із сайту")
        cat["items"] = [it for it in cat["items"] if it not in missing]

    known = {it["feed_id"] for it in cat["items"] if it.get("feed_id")}

    for it in cat["items"]:
        # Вимкнене в адмінці - не чіпаємо.
        if not it.get("enabled") or not cats.get(it["category"], {}).get("enabled"):
            continue
        f = feed_items.get(it.get("feed_id"))
        if f is None:
            continue
        if f["price"] is not None and f["price"] != it.get("feed_price"):
            changes.append(f"{it['title']}: ціна {it.get('price')} -> {f['price']}")
            it["feed_price"] = it["price"] = f["price"]
        if f["available"] != it.get("feed_available"):
            changes.append(f"{it['title']}: наявність -> {'є' if f['available'] else 'очікується'}")
            it["feed_available"] = it["available"] = f["available"]

    # Нові товари - одразу ввімкненими, картка будується з даних фіду.
    for fid, f in feed_items.items():
        if fid in known or f["category"] in excluded:
            continue
        cid = f["category"] if f["category"] in cats else cat["categories"][0]["id"]
        cat["items"].append({
            "key": f"feed-{fid}",
            "feed_id": fid,
            "enabled": True,
            "added_at": now(),
            "category": cid,
            "order": 1000,
            "title": f["name"],
            "badge": "",
            "image": f["image"],
            "specs": specs_from_description(f["description"]),
            "notes": [],
            "order_label": f["name"],
            "price": f["price"],
            "available": f["available"],
            "feed_price": f["price"],
            "feed_available": f["available"],
        })
        changes.append(f"новий товар {f['name']!r}")

    # Час лише останньої зміни - інакше кожен щогодинний запуск давав би коміт.
    if changes:
        cat["synced_at"] = now()
    for c in changes:
        print("  " + c)
    print(f"sync: {len(feed_items)} товарів у фіді, змін на сайті: {len(changes)}")
    return feed_items


def sync_products(feed_items):
    """Роздрібні ціни фіду Prom (data/products/*.json, лише price/in_stock) з фіду avtonomka."""
    all_files = []
    for path in sorted(PRODUCTS_DIR.glob("*.json")):
        all_files.append((path, json.loads(path.read_text(encoding="utf-8"))))
    before_ids = [p.get("avtonomka_id") for _, p in all_files]
    entries = [p for _, p in all_files if p.get("enabled", True)]
    for line in relink(entries, feed_items, lambda p: p["name"], "avtonomka_id"):
        print("  Prom " + line)
    for (path, p), old_id in zip(all_files, before_ids):
        if p.get("avtonomka_id") != old_id:
            path.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files = [(path, p) for path, p in all_files if p.get("avtonomka_id")]
    missing = [p for _, p in files if p["avtonomka_id"] not in feed_items]
    trust_missing = len(missing) <= len(files) / 2
    if not trust_missing:
        print(f"::warning::у фіді немає {len(missing)} з {len(files)} товарів Prom - схоже на збій фіду, наявність не змінено")

    changes = []
    for path, p in files:
        if p.get("enabled") is False:
            continue
        before = dict(p)
        f = feed_items.get(p["avtonomka_id"])
        if f is None:
            if trust_missing and p.get("feed_in_stock") is not False:
                p["feed_in_stock"] = p["in_stock"] = False
                changes.append(f"Prom {p['id']} {p['name']}: зник із фіду avtonomka -> немає в наявності")
        else:
            if f["price"] is not None and f["price"] != p.get("feed_price"):
                changes.append(f"Prom {p['id']} {p['name']}: ціна {p.get('price')} -> {f['price']}")
                p["feed_price"] = p["price"] = f["price"]
            if f["available"] != p.get("feed_in_stock"):
                changes.append(f"Prom {p['id']} {p['name']}: наявність -> {'є' if f['available'] else 'немає'}")
                p["feed_in_stock"] = p["in_stock"] = f["available"]
        if p != before:
            path.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for c in changes:
        print("  " + c)
    print(f"sync: товари фіду Prom, змін: {len(changes)}")


def white_photo(fid, urls):
    """Перше фото на білому фоні з фіду avtonomka -> images/products/avt-<fid>.jpg."""
    try:
        from white_bg import is_white_background
    except ImportError:
        print("::warning::немає Pillow - фото з avtonomka не перевірено й не додано")
        return ""
    import io
    for url in urls[:10]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "energia24-site-sync"})
            data = urllib.request.urlopen(req, timeout=60).read()
            if not is_white_background(io.BytesIO(data)):
                continue
        except Exception as e:
            print(f"  фото {url}: {e}")
            continue
        name = re.sub(r"[^a-z0-9-]", "-", f"avt-{fid}".lower())
        dest = PHOTOS_DIR / f"{name}.jpg"
        dest.write_bytes(data)
        return f"/images/products/{dest.name}"
    return ""


def first_paragraph(desc_html):
    m = re.search(r"<p>(.*?)</p>", desc_html or "", re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1) if m else desc_html or "")).strip()


def add_new_products(feed_items):
    """Товари avtonomka, яких ще немає в data/products, - створюються й одразу йдуть у фіди."""
    existing = [json.loads(p.read_text(encoding="utf-8")) for p in PRODUCTS_DIR.glob("*.json")]
    linked = {p.get("avtonomka_id") for p in existing}
    next_id = max(int(p["id"]) for p in existing) + 1
    added = []

    # Фото для вже пов'язаних товарів, у яких його немає.
    for path in sorted(PRODUCTS_DIR.glob("*.json")):
        p = json.loads(path.read_text(encoding="utf-8"))
        f = feed_items.get(p.get("avtonomka_id"))
        if f and p.get("enabled", True) and not p.get("photo"):
            photo = white_photo(p["avtonomka_id"], f["images"])
            if photo:
                p["photo"] = photo
                path.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                added.append(f"фото з avtonomka для {p['id']} {p['name']}")

    for fid, f in feed_items.items():
        if fid in linked:
            continue
        cat = AVT_TO_PROM_CATEGORY.get(f["category"])
        if cat is None:
            print(f"::warning::avtonomka {fid} {f['name']!r}: невідома категорія {f['category']!r}, не додано")
            continue
        texts = " ".join([f["name"], f["name_ru"], f["description"], f["description_ru"]])
        orders = [int(p.get("order") or 0) for p in existing if int(p["category"]) == cat]
        p = {
            "id": next_id,
            "avtonomka_id": fid,
            # «dfi» у текстах зламав би всі фіди - такий товар додаємо вимкненим.
            "enabled": not DFI.search(texts),
            "order": (max(orders) if orders else 0) + 10,
            "category": cat,
            "vendor": f["vendor"],
            "name": f["name"],
            "name_ru": f["name_ru"],
            "price": f["price"],
            "in_stock": f["available"],
            "wholesale_usd": 0,
            "off": False,
            "photo": white_photo(fid, f["images"]),
            "summary": first_paragraph(f["description"]) or f["name"],
            "description_ua_html": f["description"],
            "description_ru_html": f["description_ru"],
            "specs": [],
            "feed_price": f["price"],
            "feed_in_stock": f["available"],
        }
        (PRODUCTS_DIR / f"{next_id}.json").write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        existing.append(p)
        note = "" if p["enabled"] else " (ВИМКНЕНО: у тексті є «dfi»)"
        note += "" if p["photo"] else " (без фото на білому фоні - у фіди не піде)"
        added.append(f"новий товар у фідах Prom: {next_id} {f['name']}{note}")
        next_id += 1
    for a in added:
        print("  " + a)
    print(f"sync: нових товарів і фото для фідів Prom: {len(added)}")


# ---------------------------------------------------------------- build

def fmt_price(v):
    return f"{v:,}".replace(",", " ")


def esc(s):
    return html.escape(s or "", quote=True)


def render_card(it):
    img = it.get("image") or ""
    lis = [f"            <li>{esc(s)}</li>" for s in it.get("specs") or []]
    lis += [f"            <li><b>{esc(n)}</b></li>" for n in it.get("notes") or []]
    out = ['        <article class="card">']
    if img:
        out.append(f'          <div class="card__media"><img src="{esc(img)}" alt="{esc(it["title"])}" loading="lazy" /></div>')
    if it.get("badge"):
        out.append(f'          <span class="card__badge">{esc(it["badge"])}</span>')
    out.append(f'          <h3 class="card__title">{esc(it["title"])}</h3>')
    if lis:
        out += ['          <ul class="card__specs">', *lis, "          </ul>"]
    out.append('          <div class="card__foot">')
    label = it.get("order_label") or it["title"]
    if it.get("available") and it.get("price"):
        price = f"{fmt_price(it['price'])} грн"
        out.append(f'            <div class="card__price">{price}</div>')
        out.append(f'            <button class="btn btn--primary btn--block js-order" data-product="{esc(label)} - {price}">Замовити</button>')
    else:
        out.append('            <div class="card__price card__price--soon">Очікується</div>')
        out.append(f'            <button class="btn btn--ghost btn--block js-order" data-product="{esc(label)} - очікується надходження, уточнити ціну">Дізнатись про надходження</button>')
    out += ["          </div>", "        </article>"]
    return "\n".join(out)


def visible_sections(cat):
    for c in cat["categories"]:
        if not c.get("enabled"):
            continue
        items = [it for it in cat["items"] if it.get("enabled") and it["category"] == c["id"]]
        if items:
            items.sort(key=lambda it: (it.get("order") or 0, it["title"]))
            yield c, items


def build(cat):
    sections, nav = [], []
    for n, (c, items) in enumerate(visible_sections(cat)):
        alt = " section--alt" if n % 2 == 0 else ""
        lead = f"\n        <p>{esc(c['lead'])}</p>" if c.get("lead") else ""
        cards = "\n\n".join(render_card(it) for it in items)
        sections.append(f"""  <!-- ================= {esc(c['title']).upper()} ================= -->
  <section class="section{alt}" id="{esc(c['anchor'])}">
    <div class="container">
      <div class="section__head">
        <span class="eyebrow">{esc(c.get('eyebrow') or 'Каталог')}</span>
        <h2>{esc(c['title'])}</h2>{lead}
      </div>

      <div class="grid-products">
{cards}
      </div>
    </div>
  </section>""")
        nav.append(f'        <a href="#{esc(c["anchor"])}">{esc(c.get("nav") or c["title"])}</a>')

    src = INDEX.read_text(encoding="utf-8")
    src = replace_between(src, "CATALOG", "\n" + "\n\n".join(sections) + "\n  ")
    src = replace_between(src, "NAV", "\n" + "\n".join(nav) + "\n        ")
    INDEX.write_text(src, encoding="utf-8")
    print(f"build: index.html - {len(sections)} категорій, {sum(1 for _ in visible_items(cat))} товарів")


def visible_items(cat):
    for _, items in visible_sections(cat):
        yield from items


def replace_between(src, name, body):
    pattern = re.compile(rf"(<!-- {name}:START[^>]*-->)(.*?)(<!-- {name}:END -->)", re.S)
    if not pattern.search(src):
        sys.exit(f"[error] в index.html немає маркерів <!-- {name}:START --> / <!-- {name}:END -->")
    return pattern.sub(lambda m: m.group(1) + body + m.group(3), src, count=1)


def main():
    cmds = sys.argv[1:] or ["sync", "build"]
    cat = load_catalog()
    if "sync" in cmds:
        try:
            feed_items = sync(cat)
            save_catalog(cat)
            sync_products(feed_items)
            add_new_products(feed_items)
        except Exception as e:  # фід недоступний - сайт все одно збираємо з наявних даних
            print(f"::warning::не вдалося оновити ціни з фіду: {e}")
    if "build" in cmds:
        build(cat)


if __name__ == "__main__":
    main()
