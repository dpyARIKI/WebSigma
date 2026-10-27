let translations = window.SIGMA_TRANSLATIONS || {};
const languageSelect = document.querySelector("#language-select");

function currentLanguage() {
  return document.documentElement.lang || "es";
}

function translate(key) {
  const language = currentLanguage();
  return translations[language]?.[key] ?? translations.es?.[key] ?? key;
}

function updateValidationMessages() {
  const requiredMessage = translate("form.error.required") || "Completa este campo.";

  document.querySelectorAll("#contact-form [required]").forEach((field) => {
    if (field.validity.valueMissing) {
      field.setCustomValidity(requiredMessage);
    } else if (field.type === "email" && field.validity.typeMismatch) {
      field.setCustomValidity(translate("form.error.email"));
    } else {
      field.setCustomValidity("");
    }
  });
}

function applyLanguage(language) {
  if (!translations || Object.keys(translations).length === 0) return;
  const dictionary = translations[language] || translations.es || {};
  document.documentElement.lang = language;

  document.querySelectorAll("[data-i18n]").forEach((element) => {
    const text = dictionary[element.dataset.i18n];
    if (text !== undefined) {
      if (/<[a-z][\s\S]*>/i.test(text)) {
        element.innerHTML = text;
      } else {
        element.textContent = text;
      }
    }
  });

  document.querySelectorAll("[data-i18n-html]").forEach((element) => {
    const markup = dictionary[element.dataset.i18nHtml];
    if (markup !== undefined) element.innerHTML = markup;
  });

  document.querySelectorAll("[data-i18n-aria]").forEach((element) => {
    const label = dictionary[element.dataset.i18nAria];
    if (label !== undefined) element.setAttribute("aria-label", label);
  });

  document.querySelectorAll("[data-i18n-alt]").forEach((element) => {
    const text = dictionary[element.dataset.i18nAlt];
    if (text !== undefined) element.setAttribute("alt", text);
  });

  document.querySelectorAll("[data-i18n-content]").forEach((element) => {
    const text = dictionary[element.dataset.i18nContent];
    if (text !== undefined) element.setAttribute("content", text);
  });

  const titleKey = document.body.dataset.pageTitle || "page.title";
  const descriptionKey = document.body.dataset.pageDescription || "page.description";
  if (dictionary[titleKey]) {
    document.title = dictionary[titleKey];
  }
  const description = document.querySelector('meta[name="description"]');
  if (description && dictionary[descriptionKey]) {
    description.content = dictionary[descriptionKey];
  }
  if (languageSelect) languageSelect.value = language;
  updateValidationMessages();
}

function getPreferredLanguage() {
  try {
    const storedLanguage = localStorage.getItem("sigma-language");
    if (storedLanguage && translations[storedLanguage]) return storedLanguage;
  } catch {}
  return "es";
}

let preferredLanguage = getPreferredLanguage();
applyLanguage(preferredLanguage);

async function loadTranslations() {
  try {
    const response = await fetch("translations.json?v=" + Date.now(), { cache: "no-store" });
    if (response.ok) {
      const data = await response.json();
      translations = data;
      window.SIGMA_TRANSLATIONS = data;
      preferredLanguage = getPreferredLanguage();
      applyLanguage(preferredLanguage);
    }
  } catch {
    // Si se abre vía file:// o sin red, se mantiene el objeto inicial
  }
}

loadTranslations();

document.querySelector("#contact-form")?.addEventListener("input", updateValidationMessages);

languageSelect?.addEventListener("change", (event) => {
  const language = event.target.value;
  applyLanguage(language);
  try {
    localStorage.setItem("sigma-language", language);
  } catch {}
});

const contactForm = document.querySelector("#contact-form");
if (contactForm) {
  const contactStatus = document.querySelector("#contact-status");
  const submitButton = contactForm.querySelector("button[type='submit']");

  contactForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    submitButton.disabled = true;
    contactStatus.textContent = translate("form.sending");

    try {
      const response = await fetch(contactForm.action, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
        body: new URLSearchParams(new FormData(contactForm))
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(translate(`form.error.${result.error_code || "invalid_request"}`));
      }

      contactStatus.textContent = result.email_sent === false
        ? translate("form.saved")
        : translate("form.success");
      contactForm.reset();
    } catch (error) {
      contactStatus.textContent = error.message || translate("form.network");
    } finally {
      submitButton.disabled = false;
    }
  });
}

const mobileQrDialog = document.querySelector("#mobile-qr-dialog");
if (mobileQrDialog) {
  document.querySelector("#mobile-qr-open").addEventListener("click", () => mobileQrDialog.showModal());
  document.querySelector("#mobile-qr-close").addEventListener("click", () => mobileQrDialog.close());
  mobileQrDialog.addEventListener("click", (event) => {
    if (event.target === mobileQrDialog) mobileQrDialog.close();
  });
}
