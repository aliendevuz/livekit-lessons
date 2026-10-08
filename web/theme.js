// Mavzu (kunduzgi / tungi). <head> ichida yuklanadi — sahifa chizilishidan oldin qo'llanadi, miltillamaydi.
//
// Birinchi kirganda tizim (yoki Telegram) afzal ko'rgan mavzu olinadi; tugma bosilgach tanlov saqlanadi.

const THEME_KEY = "theme";

function systemTheme() {
  const telegram = window.Telegram?.WebApp;
  // Telegram ichida uning o'z mavzusi "tizim" hisoblanadi
  if (telegram?.initData) return telegram.colorScheme === "dark" ? "dark" : "light";
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function savedTheme() {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "dark" || value === "light" ? value : null;
  } catch {
    return null; // storage yopiq — har safar tizim mavzusi olinadi
  }
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch {
    // saqlanmasa ham shu sahifada ishlayveradi
  }
  return next;
}

applyTheme(savedTheme() || systemTheme());
