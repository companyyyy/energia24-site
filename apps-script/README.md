# Приймання заявок партнерства у Google Sheet

Сайт статичний (GitHub Pages), тому дані форми `partnership.html` пишуться у
Google-таблицю через Google Apps Script Web App.

## Налаштування (у браузері)

1. Створити Google-таблицю на акаунті, де мають зберігатися заявки.
2. У таблиці: **Розширення → Apps Script**.
3. Вміст файлу `Code.gs` замінити на код з [`Code.gs`](./Code.gs).
4. У коді:
   - `SECRET` — вписати випадковий рядок (наприклад 20+ символів). Той самий рядок
     треба вписати у `script.js` сайту (константа `PARTNER_ENDPOINT_SECRET`).
   - `NOTIFY_EMAIL` — за бажанням, адреса для копії кожної заявки на пошту.
5. **Deploy → New deployment → Web app**:
   - *Execute as*: **Me**
   - *Who has access*: **Anyone**
6. Пройти авторизацію Google (екран "Google hasn't verified this app" → *Advanced* →
   *Go to … (unsafe)* → *Allow*).
7. Скопіювати **Web app URL** (закінчується на `/exec`).

## Підключення на сайті

У `script.js` заповнити:

```js
var PARTNER_ENDPOINT     = "https://script.google.com/macros/s/…/exec";
var PARTNER_ENDPOINT_SECRET = "той самий SECRET";
```

Якщо `PARTNER_ENDPOINT` порожній — форма працює у старому режимі (лог у консоль).

## Оновлення коду скрипта

Після правок у `Code.gs`: **Deploy → Manage deployments → (олівець) → Version: New version → Deploy**.
URL при цьому не змінюється.

## Перевірка

Відкрити Web app URL у браузері — має повернути `{"result":"ok",…}`.
Надіслати тестову заявку з сайту — у таблиці має з'явитися новий рядок.
