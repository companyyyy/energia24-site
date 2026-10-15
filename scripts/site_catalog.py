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
             * нові товари й категорії з фіду додаються одразу ввімкненими
               (вимкнути можна в адмінці; товар вимкненої категорії на сайті не видно).
           Те саме для роздрібних цін фіду Prom feed.xml: товари data/products/*.json
           з полем avtonomka_id отримують price/in_stock з фіду avtonomka за тими ж правилами
           (вимкнені не оновлюються, ручна ціна з /admin/ діє до зміни ціни у фіді).
           Зник із фіду - «немає в наявності» (з фіду Prom не видаляємо: за id його знає Prom).
           Ціни PA (pa_price, pa_in_stock, pa) не змінюються.
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
            "category": (f.findtext("categoryId") or "").strip(),
            "price": parse_price(f.findtext("priceuah")),
            "available": (f.findtext("available") or "").strip().lower() == "true",
            "image": (f.findtext("image") or "").strip(),
            "description": f.findtext("description_ua") or "",
        }
    if not feed_items:
        raise RuntimeError("фід порожній або не розпізнаний - каталог не змінено")

    cats = {c["id"]: c for c in cat["categories"]}
    changes = []

    # Нові категорії - одразу ввімкненими.
    for cid, name in feed_cats.items():
        if cid not in cats:
            c = {"id": cid, "enabled": True, "anchor": f"cat-{cid}", "nav": name, "eyebrow": "Каталог",
                 "title": name, "lead": ""}
            cat["categories"].append(c)
            cats[cid] = c
            changes.append(f"нова категорія {name!r}")

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
        if fid in known:
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
    files = []
    for path in sorted(PRODUCTS_DIR.glob("*.json")):
        p = json.loads(path.read_text(encoding="utf-8"))
        if p.get("avtonomka_id"):
            files.append((path, p))
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
        except Exception as e:  # фід недоступний - сайт все одно збираємо з наявних даних
            print(f"::warning::не вдалося оновити ціни з фіду: {e}")
    if "build" in cmds:
        build(cat)


if __name__ == "__main__":
    main()
