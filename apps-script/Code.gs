/**
 * ENERGIA24 - приймання заявок з форми партнерства (partnership.html)
 * та форми контактів (index.html) у Google Sheet.
 *
 * Розгортання:
 *   1. Створити Google-таблицю, відкрити Розширення -> Apps Script.
 *   2. Вставити цей код у файл Code.gs (замінити вміст повністю).
 *   3. Змінити SECRET на власний випадковий рядок (той самий вписати у script.js сайту).
 *   4. За бажанням вписати NOTIFY_EMAIL - на цю адресу приходитиме копія кожної заявки.
 *   5. Розгорнути: Deploy -> New deployment -> тип "Web app":
 *        Execute as: Me
 *        Who has access: Anyone
 *      Скопіювати URL, що закінчується на /exec.
 *   6. Після кожної зміни коду робити Deploy -> Manage deployments -> Edit -> Version: New version.
 */

const SECRET       = 'dgyru47365jte4uty4nt383tg3i48';  // має точно збігатися з PARTNER_ENDPOINT_SECRET у script.js
const NOTIFY_EMAIL = 'energia24.info@gmail.com'; // одна або кілька адрес через кому; порожньо = не слати
                                     // напр. 'sales@energia24.com.ua, director@energia24.com.ua'

// Дві форми пишуться у різні вкладки з різним набором колонок.
// Ключ "form" у тілі запиту визначає, яку форму обробляємо (значення шлють script.js).
const FORMS = {
  contact: {
    sheetName: 'Заявки з сайту',
    subject: 'Нова заявка з сайту',
    fields: [
      ['name',    "Ім'я"],
      ['phone',   'Телефон'],
      ['message', 'Повідомлення']
    ]
  },
  partnership: {
    sheetName: 'Заявки',
    subject: 'Нова заявка на партнерство',
    fields: [
      ['email',     'Email'],
      ['company',   'Компанія'],
      ['edrpou',    'ЄДРПОУ'],
      ['activity',  'Діяльність'],
      ['region',    'Регіон'],
      ['site',      'Сайт'],
      ['brands',    'Бренди'],
      ['payment',   'Оплата'],
      ['volume',    'Обсяг на місяць'],
      ['suppliers', 'Поточні постачальники'],
      ['prepay',    'Готовність до передоплати'],
      ['phone',     'Телефон']
    ]
  }
};

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || '{}');

    if (SECRET && body.secret !== SECRET) {
      return json({ result: 'error', message: 'unauthorized' });
    }

    // Пастка для ботів: приховане поле hp має лишатися порожнім.
    if (body.hp) {
      return json({ result: 'success' });
    }

    // Старі заявки без поля "form" (до додавання форми контактів) - вважати партнерськими.
    var formKey = FORMS[body.form] ? body.form : 'partnership';
    var form = FORMS[formKey];

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName(form.sheetName) || ss.insertSheet(form.sheetName);

    if (sheet.getLastRow() === 0) {
      sheet.appendRow(['Дата'].concat(form.fields.map(function (f) { return f[1]; })));
      sheet.setFrozenRows(1);
      sheet.getRange(1, 1, 1, form.fields.length + 1).setFontWeight('bold');
    }

    var row = [new Date()];
    form.fields.forEach(function (f) {
      var v = body[f[0]];
      if (Array.isArray(v)) v = v.join(', ');
      row.push(v == null ? '' : String(v));
    });

    var targetRow = sheet.getLastRow() + 1;
    var range = sheet.getRange(targetRow, 1, 1, row.length);
    // Колонки з даними (усе, крім дати) - примусово як текст, інакше Sheets
    // намагається розпарсити телефон "+380..." як формулу і показує #ERROR!.
    range.offset(0, 1, 1, row.length - 1).setNumberFormat('@');
    range.setValues([row]);

    if (NOTIFY_EMAIL) {
      var lines = form.fields.map(function (f) {
        var v = body[f[0]];
        if (Array.isArray(v)) v = v.join(', ');
        return f[1] + ': ' + (v == null ? '' : v);
      });
      MailApp.sendEmail(
        NOTIFY_EMAIL,
        form.subject + ' - ' + (body.name || body.company || body.phone || ''),
        lines.join('\n')
      );
    }

    return json({ result: 'success' });
  } catch (err) {
    return json({ result: 'error', message: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function doGet() {
  // version росте з кожним оновленням коду - зручно звірити, що деплой підхопив
  // саме цю версію (відкрити URL у браузері й порівняти значення).
  return json({ result: 'ok', info: 'ENERGIA24 forms endpoint', version: 2 });
}

function json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
