#!/usr/bin/env python3
"""
Оновлює feed.xml (фід для імпорту в Prom.ua) цінами та наявністю
з Google Sheet, опублікованого для читання в форматі CSV.

Метадані товарів (назва, категорія, фото, опис) задані тут статично -
з Google Sheet підтягуються тільки ціна та наявність. Це зроблено
навмисно: текст у таблиці "Найменування і характеристики" не має
фіксованої структури, і його автоматичний розбір на структуровані поля
(потужність/напруга/вага) був би ненадійним.

Запускається за розкладом через .github/workflows/update-feed.yml.
"""

import csv
import io
import re
import sys
import urllib.request
from pathlib import Path

SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1vxMdT03FDGt2yi9u_b8RNWlek1avd4rzngiv_ptJBPA/export"
    "?format=csv&gid=1763821507"
)

ROOT = Path(__file__).resolve().parent.parent
FEED_PATH = ROOT / "feed.xml"
SITE_URL = "https://energia24.com.ua"

# id -> (унікальний підрядок для пошуку в колонці "Найменування і характеристики",
#        categoryId, шлях до фото, виробник, назва товару, опис без ціни/наявності)
PRODUCTS = [
    (1, "PV18-1012VPK", 1, "inv-pv18-1012vpk.jpg", "Must", "Must PV18-1012VPK",
     "Інвертор Must PV18-1012VPK. Потужність: 1 кВт. Напруга АКБ: 12 В. Вага: 5 кг."),
    (2, "PV18-1512", 1, "inv-pv18-1512vpm.jpg", "Must", "Must PV18-1512 VPM II",
     "Інвертор Must PV18-1512 VPM II. Потужність: 1.5 кВт. Напруга АКБ: 12 В. Вага: 5.5 кг."),
    (3, "PV18-3224", 1, "inv-pv18-3224vpm.jpg", "Must", "Must PV18-3224VPM II",
     "Інвертор Must PV18-3224VPM II. Потужність: 3.2 кВт. Напруга АКБ: 24 В. Вага: 5.6 кг."),
    (4, "PV19-4024", 1, "inv-pv19-4024exp.jpg", "Must", "MUST PV19-4024 EXP",
     "Інвертор MUST PV19-4024 EXP. Потужність: 4 кВт. Напруга АКБ: 24 В. Вага: 9.5 кг."),
    (5, "PV19-6048", 1, "inv-pv19-6048exp.jpg", "Must", "Must PV19-6048EXP",
     "Інвертор Must PV19-6048EXP. Потужність: 6 кВт. Напруга АКБ: 48 В. Вага: 14 кг."),
    (6, "IVEM4024", 1, "inv-ivem4024.jpg", "Felicity", "Felicity IVEM4024-II",
     "Інвертор Felicity IVEM4024-II. Потужність: 4 кВт. Напруга АКБ: 24 В. Вага: 10.4 кг."),
    (7, "IVEM6048", 1, "inv-ivem6048.jpg", "Felicity", "Felicity IVEM6048-II",
     "Інвертор Felicity IVEM6048-II. Потужність: 6 кВт. Напруга АКБ: 48 В. Вага: 12.5 кг."),
    (8, "IVEM8048", 1, "inv-ivem8048.jpg", "Felicity", "Felicity IVEM8048-II",
     "Інвертор Felicity IVEM8048-II. Потужність: 8 кВт. Напруга АКБ: 48 В. Вага: 23.7 кг."),
    (9, "IVEM12048", 1, "inv-ivem12048.jpg", "Felicity", "Felicity IVEM12048-II",
     "Інвертор Felicity IVEM12048-II. Потужність: 12 кВт. Напруга АКБ: 48 В. Вага: 26.8 кг."),
    (10, "SE-F5", 2, "bat-sef5-proc.jpg", "Deye", "DEYE SE-F5 Pro-C",
     "Акумулятор DEYE SE-F5 Pro-C. Напруга/ємність: 51.2 В · 100 Аг. Енергія: 5.12 кВт·год. Тип комірок: LiFePO4. Вага: 45 кг."),
    (11, "F16", 2, "bat-sef16-c.jpg", "Deye", "Deye SE-F16-C",
     "Акумулятор Deye SE-F16-C. Напруга/ємність: 51.2 В · 314 Аг. Енергія: 16 кВт·год. Тип комірок: LiFePO4. Вага: 109 кг."),
    (12, "LP15-12100", 2, "bat-lp15-12100.jpg", "Must", "MUST LP15-12100",
     "Акумулятор MUST LP15-12100. Напруга/ємність: 12 В · 100 Аг. Енергія: 1.2 кВт·год. Тип комірок: LiFePO4. Вага: 10.5 кг."),
    (13, "LP15-24100", 2, "bat-lp15-24100.jpg", "Must", "MUST LP15-24100",
     "Акумулятор MUST LP15-24100. Напруга/ємність: 25.6 В · 100 Аг. Енергія: 2.56 кВт·год. Тип комірок: LiFePO4. Вага: 23 кг."),
    (14, "LP16-24100", 2, "bat-lp16-24100.jpg", "Must", "MUST LP16-24100",
     "Акумулятор MUST LP16-24100. Напруга/ємність: 25.6 В · 100 Аг. Енергія: 2.56 кВт·год. Тип комірок: LiFePO4. Вага: 23 кг."),
    (15, "LP16-24200", 2, "bat-lp16-24200.jpg", "Must", "MUST LP16-24200",
     "Акумулятор MUST LP16-24200. Напруга/ємність: 25.6 В · 200 Аг. Енергія: 5.12 кВт·год. Тип комірок: LiFePO4. Вага: 45 кг."),
    (16, "LP16-48100", 2, "bat-lp16-48100.jpg", "Must", "MUST LP16-48100",
     "Акумулятор MUST LP16-48100. Напруга/ємність: 48 В · 100 Аг. Енергія: 4.8 кВт·год. Тип комірок: LiFePO4. Вага: 44 кг."),
    (17, "LP16-48300", 2, "bat-lp16-48300.jpg", "Must", "MUST LP16-48300",
     "Акумулятор MUST LP16-48300. Напруга/ємність: 51.2 В · 300 Аг. Енергія: 15.36 кВт·год. Тип комірок: LiFePO4. Конструкція: на колесах. Вага: 117 кг."),
    (18, "FLA12100", 2, "bat-fla12100pg2.jpg", "Felicity", "Felicity FLA12100PG2",
     "Акумулятор Felicity FLA12100PG2. Напруга/ємність: 12.8 В · 100 Аг. Енергія: 1.28 кВт·год. Тип комірок: LiFePO4. Вага: 10 кг."),
    (19, "FLA24230", 2, "bat-fla24230.jpg", "Felicity", "Felicity FLA24230",
     "Акумулятор Felicity FLA24230. Напруга/ємність: 25.6 В · 230 Аг. Енергія: 5.89 кВт·год. Тип комірок: LiFePO4. Вага: 52.5 кг."),
    (20, "FLB48100", 2, "bat-flb48100wg1.jpg", "Felicity", "Felicity FLB48100WG1-H",
     "Акумулятор Felicity FLB48100WG1-H. Напруга/ємність: 51.2 В · 100 Аг. Енергія: 5.12 кВт·год. Тип комірок: LiFePO4. Функція: вбудований підігрів. Вага: 48.5 кг."),
    (21, "FLA48171", 2, "bat-fla48171.jpg", "Felicity", "Felicity FLA48171",
     "Акумулятор Felicity FLA48171. Напруга/ємність: 51.2 В · 171 Аг. Енергія: 8.76 кВт·год. Тип комірок: LiFePO4. Вага: 68 кг."),
    (22, "FLA48230", 2, "bat-fla48230.jpg", "Felicity", "Felicity FLA48230",
     "Акумулятор Felicity FLA48230. Напруга/ємність: 51.2 В · 230 Аг. Енергія: 11.78 кВт·год. Тип комірок: LiFePO4. Вага: 97 кг."),
    (23, "FLB48230", 2, "bat-flb48230wg1.jpg", "Felicity", "Felicity FLB48230WG1-H",
     "Акумулятор Felicity FLB48230WG1-H. Напруга/ємність: 51.2 В · 230 Аг. Енергія: 11.78 кВт·год. Тип комірок: LiFePO4. Функція: вбудований підігрів. Вага: 91 кг."),
    (24, "FLA48280", 2, "bat-fla48280.jpg", "Felicity", "Felicity FLA48280",
     "Акумулятор Felicity FLA48280. Напруга/ємність: 51.2 В · 280 Аг. Енергія: 14.34 кВт·год. Тип комірок: LiFePO4. Конструкція: на колесах. Вага: 135 кг."),
    (25, "FLA48314", 2, "bat-fla48314eu.jpg", "Felicity", "Felicity FLA48314-EU",
     "Акумулятор Felicity FLA48314-EU. Напруга/ємність: 51.2 В · 314 Аг. Енергія: 16 кВт·год. Тип комірок: LiFePO4. Конструкція: на колесах. Вага: 121.5 кг."),
    (26, "FLB48314", 2, "bat-flb48314tg1.jpg", "Felicity", "Felicity FLB48314TG1-H",
     "Акумулятор Felicity FLB48314TG1-H. Напруга/ємність: 51.2 В · 314 Аг. Енергія: 16 кВт·год. Тип комірок: LiFePO4. Функція: вбудований підігрів. Конструкція: на колесах. Вага: 121 кг."),
    (27, "HBP18-1012", 3, "sys-hbp18-1012.jpg", "Must", "MUST HBP18-1012 OS",
     "Система зберігання енергії 2в1 MUST HBP18-1012 OS. Потужність: 1.2 кВт. Ємність: 1280 Вт·год. Конструкція: інвертор + акумулятор в одному корпусі."),
    (28, "HBP18-3024", 3, "sys-hbp18-3024.jpg", "Must", "MUST HBP18-3024OS",
     "Система зберігання енергії 2в1 MUST HBP18-3024OS. Потужність: 3 кВт. Ємність: 3072 Вт·год. Конструкція: інвертор + акумулятор в одному корпусі, на колесах. Вага: 33 кг."),
    (29, "HBP19-5548", 3, "sys-hbp19-5548.jpg", "Must", "MUST HBP19-5548 VPM",
     "Система зберігання енергії 2в1 MUST HBP19-5548 VPM. Потужність: 5.5 кВт. Ємність: 5120 Вт·год. Конструкція: інвертор + акумулятор в одному корпусі. Вага: 58 кг."),
    (30, "Delta 2", 4, "station-delta2.jpg", "EcoFlow", "EcoFlow Delta 2",
     "Портативна зарядна станція EcoFlow Delta 2. Потужність: 1800 Вт. Ємність: 1024 Вт·год."),
    (31, "Delta 3", 4, "station-delta3.jpg", "EcoFlow", "EcoFlow Delta 3",
     "Портативна зарядна станція EcoFlow Delta 3. Потужність: 1800 Вт. Ємність: 1024 Вт·год."),
]

CATEGORIES = {
    1: "Інвертори",
    2: "Акумулятори",
    3: "Системи зберігання енергії 2 в 1",
    4: "Зарядні станції",
}


def fetch_rows():
    req = urllib.request.Request(SHEET_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    return list(csv.reader(io.StringIO(raw)))


def match_prices(rows):
    """Повертає {product_id: (price:int|None, available:bool)}"""
    result = {}
    for pid, key, *_ in PRODUCTS:
        matches = [row for row in rows if len(row) > 5 and key.lower() in (row[1] or "").lower()]
        if len(matches) == 0:
            print(f"[warn] товар id={pid} (key={key!r}) не знайдено в таблиці - лишаю без змін", file=sys.stderr)
            result[pid] = None
            continue
        if len(matches) > 1:
            print(f"[warn] товар id={pid} (key={key!r}) неоднозначний ({len(matches)} збігів) - лишаю без змін", file=sys.stderr)
            result[pid] = None
            continue
        price_cell = (matches[0][5] or "").strip().replace(" ", "")
        if re.fullmatch(r"\d+([.,]\d+)?", price_cell):
            price = int(float(price_cell.replace(",", ".")))
            result[pid] = (price, True)
        else:
            result[pid] = (None, False)
    return result


def build_feed(price_map, date_str):
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
    for cid, cname in CATEGORIES.items():
        lines.append(f'      <category id="{cid}">{cname}</category>')
    lines.append('    </categories>')
    lines.append('    <offers>')

    current_cat = None
    for pid, _key, cat, img, vendor, name, desc in PRODUCTS:
        if cat != current_cat:
            lines.append('')
            current_cat = cat
        update = price_map.get(pid)
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
        lines.append(f'        <name>{name}</name>')
        if price_line is not None:
            lines.append(f'        <price>{price_line}</price>')
        lines.append('        <currencyId>UAH</currencyId>')
        lines.append(f'        <categoryId>{cat}</categoryId>')
        lines.append(f'        <picture>{SITE_URL}/images/products/{img}</picture>')
        lines.append(f'        <vendor>{vendor}</vendor>')
        lines.append(f'        <description><![CDATA[{desc}]]></description>')
        lines.append('      </offer>')

    lines.append('')
    lines.append('    </offers>')
    lines.append('  </shop>')
    lines.append('</yml_catalog>')
    lines.append('')
    return "\n".join(lines)


def main():
    import datetime

    rows = fetch_rows()
    price_map = match_prices(rows)
    date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    feed = build_feed(price_map, date_str)
    FEED_PATH.write_text(feed, encoding="utf-8")
    print(f"feed.xml оновлено ({date_str} UTC)")


if __name__ == "__main__":
    main()
