/* ==========================================================================
   ENERGIA24 - інтерактив (без бекенду)
   ========================================================================== */
(function () {
  "use strict";

  /* ---- Ендпоінт для заявок партнерства (Google Apps Script Web App) ---- */
  /* Порожній PARTNER_ENDPOINT = форма працює у демо-режимі (лог у консоль). */
  var PARTNER_ENDPOINT = "https://script.google.com/macros/s/AKfycbzGIC2t8e0U0pXcAwP1pGrST2NFkz-7XPLsl8QWWydYk_srLePo7h2ixrE7GmohpW4ozw/exec";
  var PARTNER_ENDPOINT_SECRET = "dgyru47365jte4uty4nt383tg3i48";

  /* ---- Поточний рік у футері ---- */
  var yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  /* ---- Поява елементів при прокрутці (scroll-reveal) ---- */
  var revealSelectors = [
    ".section__head",
    ".cat",
    ".card",
    ".brand",
    ".form",
    ".map",
    ".contacts__info",
    ".partner-banner__inner",
    ".partner-perks"
  ];
  var revealEls = document.querySelectorAll(revealSelectors.join(","));

  if (revealEls.length) {
    Array.prototype.forEach.call(revealEls, function (el) {
      el.classList.add("reveal");
    });

    if ("IntersectionObserver" in window) {
      var revealObserver = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              entry.target.classList.add("is-visible");
              revealObserver.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
      );
      Array.prototype.forEach.call(revealEls, function (el) {
        revealObserver.observe(el);
      });
    } else {
      // Немає підтримки IntersectionObserver - просто показуємо все
      Array.prototype.forEach.call(revealEls, function (el) {
        el.classList.add("is-visible");
      });
    }
  }

  /* ---- Мобільне меню ---- */
  var navToggle = document.getElementById("navToggle");
  var nav = document.getElementById("nav");
  if (navToggle && nav) {
    navToggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    nav.addEventListener("click", function (e) {
      if (e.target.tagName === "A") {
        nav.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  /* ---- Кнопки «Замовити»: підставляємо товар у форму контактів ---- */
  var orderButtons = document.querySelectorAll(".js-order");
  var contactMessage = document.getElementById("cf-message");
  Array.prototype.forEach.call(orderButtons, function (btn) {
    btn.addEventListener("click", function () {
      var product = btn.getAttribute("data-product") || "";
      if (contactMessage) {
        contactMessage.value = "Хочу замовити: " + product + ".\nПрошу зв'язатися для уточнення наявності та ціни.";
      }
      var contacts = document.getElementById("contacts");
      if (contacts) contacts.scrollIntoView({ behavior: "smooth", block: "start" });
      var nameField = document.getElementById("cf-name");
      if (nameField) setTimeout(function () { nameField.focus(); }, 500);
    });
  });

  /* ---- Допоміжне: показати статус під формою ---- */
  function showStatus(el, text, isError) {
    if (!el) return;
    el.textContent = text;
    el.classList.add("is-visible");
    el.classList.toggle("form-status--err", !!isError);
    el.classList.toggle("form-status--ok", !isError);
  }

  /* ---- Проста перевірка обов'язкових полів ---- */
  function validate(form) {
    var ok = true;

    // required-поля input/select/textarea
    Array.prototype.forEach.call(form.querySelectorAll("[required]"), function (field) {
      if (field.type === "radio") {
        if (!form.querySelector('input[name="' + field.name + '"]:checked')) ok = false;
        return;
      }
      if (!String(field.value || "").trim()) ok = false;
    });

    // група брендів (чекбокси) на сторінці партнерства
    var brandBoxes = form.querySelectorAll('input[name="brands"]');
    if (brandBoxes.length) {
      var anyBrand = Array.prototype.some.call(brandBoxes, function (b) { return b.checked; });
      if (!anyBrand) ok = false;
    }

    return ok;
  }

  /* ---- Збір даних форми у зручний обʼєкт ---- */
  function collect(form) {
    var data = {};
    var fd = new FormData(form);
    fd.forEach(function (value, key) {
      if (data[key] === undefined) {
        data[key] = value;
      } else if (Array.isArray(data[key])) {
        data[key].push(value);
      } else {
        data[key] = [data[key], value];
      }
    });
    return data;
  }

  /* ---- Форма зворотного звʼязку (index.html) ---- */
  var contactForm = document.getElementById("contactForm");
  if (contactForm) {
    contactForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var status = document.getElementById("contactStatus");

      if (!validate(contactForm)) {
        showStatus(status, "Будь ласка, заповніть ім'я та телефон.");
        return;
      }

      var data = collect(contactForm);
      console.log("[ENERGIA24] Заявка зі сторінки контактів:", data);

      showStatus(status, "Дякуємо, " + data.name + "! Ми зателефонуємо вам найближчим часом.");
      contactForm.reset();
    });
  }

  /* ---- Анкета партнера (partnership.html) ---- */
  var partnerForm = document.getElementById("partnerForm");
  if (partnerForm) {
    var partnerBtn = partnerForm.querySelector('button[type="submit"]');

    partnerForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var status = document.getElementById("partnerStatus");

      if (!validate(partnerForm)) {
        showStatus(status, "Заповніть, будь ласка, всі обов'язкові поля (позначені *).", true);
        return;
      }

      var data = collect(partnerForm);
      var okText = "Заявку надіслано! Ми перевіримо анкету та звʼяжемося з вами за вказаними контактами.";

      // Демо-режим: ендпоінт не налаштований.
      if (!PARTNER_ENDPOINT) {
        console.log("[ENERGIA24] Заявка на партнерство:", data);
        showStatus(status, okText);
        partnerForm.reset();
        return;
      }

      data.secret = PARTNER_ENDPOINT_SECRET;

      var btnText = partnerBtn ? partnerBtn.textContent : "";
      if (partnerBtn) { partnerBtn.disabled = true; partnerBtn.textContent = "Надсилаємо…"; }
      showStatus(status, "Надсилаємо заявку…");

      function restoreBtn() {
        if (partnerBtn) { partnerBtn.disabled = false; partnerBtn.textContent = btnText; }
      }

      fetch(PARTNER_ENDPOINT, {
        method: "POST",
        mode: "no-cors",
        headers: { "Content-Type": "text/plain;charset=utf-8" },
        body: JSON.stringify(data)
      })
        .then(function () {
          showStatus(status, okText);
          partnerForm.reset();
          restoreBtn();
        })
        .catch(function () {
          showStatus(
            status,
            "Не вдалося надіслати заявку. Перевірте з'єднання і спробуйте ще раз " +
              "або зателефонуйте: +38 077 888 00 24.",
            true
          );
          restoreBtn();
        });
    });
  }
})();
