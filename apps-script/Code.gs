/**
 * ENERGIA24 - приймання заявок з форми партнерства (partnership.html) у Google Sheet.
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

const SHEET_NAME   = 'Заявки';        // назва вкладки в таблиці (створиться автоматично)
const SECRET       = 'CHANGE_ME';     // має точно збігатися зі значенням у script.js
const NOTIFY_EMAIL = '';              // одна або кілька адрес через кому; порожньо = не слати
                                     // напр. 'sales@energia24.com.ua, director@energia24.com.ua'

// Порядок і заголовки колонок. Ключі зліва - це name полів форми.
const FIELDS = [
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
];

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

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);

    if (sheet.getLastRow() === 0) {
      sheet.appendRow(['Дата'].concat(FIELDS.map(function (f) { return f[1]; })));
      sheet.setFrozenRows(1);
      sheet.getRange(1, 1, 1, FIELDS.length + 1).setFontWeight('bold');
    }

    var row = [new Date()];
    FIELDS.forEach(function (f) {
      var v = body[f[0]];
      if (Array.isArray(v)) v = v.join(', ');
      row.push(v == null ? '' : String(v));
    });
    sheet.appendRow(row);

    if (NOTIFY_EMAIL) {
      var lines = FIELDS.map(function (f) {
        var v = body[f[0]];
        if (Array.isArray(v)) v = v.join(', ');
        return f[1] + ': ' + (v == null ? '' : v);
      });
      MailApp.sendEmail(
        NOTIFY_EMAIL,
        'Нова заявка на партнерство - ' + (body.company || body.phone || ''),
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
  return json({ result: 'ok', info: 'ENERGIA24 partnership form endpoint' });
}

function json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
