/* ==========================================================================
   ENERGIA24 - інтерактив (без бекенду)
   ========================================================================== */
(function () {
  "use strict";

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
  function showStatus(el, text) {
    if (!el) return;
    el.textContent = text;
    el.classList.add("is-visible");
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
    partnerForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var status = document.getElementById("partnerStatus");

      if (!validate(partnerForm)) {
        showStatus(status, "Заповніть, будь ласка, всі обов'язкові поля (позначені *).");
        return;
      }

      var data = collect(partnerForm);
      console.log("[ENERGIA24] Заявка на партнерство:", data);

      // За бажанням - відправка на пошту через поштовий клієнт:
      // var body = Object.keys(data).map(function (k) { return k + ": " + data[k]; }).join("\n");
      // window.location.href = "mailto:info@energia24.ua?subject=" +
      //   encodeURIComponent("Заявка на партнерство") + "&body=" + encodeURIComponent(body);

      showStatus(status, "Заявку надіслано! Ми перевіримо анкету та звʼяжемося з вами за вказаними контактами.");
      partnerForm.reset();
    });
  }
})();
