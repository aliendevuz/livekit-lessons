// Barcha sahifalar ishlatadigan umumiy narsalar: holat, API, element yasash, dialoglar, formatlash.

const telegram = window.Telegram?.WebApp;
const initData = telegram?.initData || "";
const app = document.getElementById("app");

const WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"];
const ROLES = { admin: "Admin", teacher: "O'qituvchi", student: "O'quvchi" };
const STATUS = { scheduled: "Kutilmoqda", live: "Jonli efir", ended: "Tugagan", cancelled: "Bekor qilingan" };
const GROUP_COLORS = ["#2563eb", "#15803d", "#c2410c", "#7e22ce", "#be185d", "#0f766e"];
const AVATAR_COLORS = ["#475569", "#0f766e", "#7e22ce", "#b45309", "#be185d", "#1d4ed8", "#4d7c0f"];
const RECORDING_POLL_MS = 2000;

let token = null;
let me = null;
try {
  token = localStorage.getItem("token");
} catch {
  // storage yopiq bo'lsa (masalan, maxfiy rejim) har safar qayta kiriladi
}

// ---------- element yasash ----------

function h(tag, props, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
    else if (key === "class") element.className = value;
    else if (value === true) element.setAttribute(key, "");
    else if (value !== false && value != null) element.setAttribute(key, value);
  }
  element.append(...children.flat(Infinity).filter((child) => child != null && child !== false));
  return element;
}

function render(...nodes) {
  app.replaceChildren(...nodes.flat(Infinity).filter(Boolean));
  window.scrollTo(0, 0);
}

/** Matnli tugma, xohlasa ikonka bilan. variant: "" (asosiy) | "secondary" | "danger" | "ghost" */
function button(label, iconName, variant, onclick, props) {
  return h("button", { type: "button", class: `btn ${variant || ""}`, onclick, ...props },
    iconName && icon(iconName), h("span", null, label));
}

/** Faqat ikonkali tugma; label ekran o'quvchi va ko'rsatma (tooltip) uchun. */
function iconButton(iconName, label, onclick, variant = "ghost") {
  return h("button", { type: "button", class: `btn icon-only ${variant}`, title: label, "aria-label": label, onclick },
    icon(iconName));
}

function select(options, value, props) {
  const element = h("select", props, options.map(([key, label]) => h("option", { value: key }, label)));
  if (value != null) element.value = value;
  return element;
}

function initials(name) {
  const words = name.trim().split(/\s+/);
  // "Student 10" -> "S10": raqam to'liq olinadi, aks holda Student 1 bilan bir xil chiqadi
  const second = /^\d+$/.test(words[1] || "") ? words[1] : words[1]?.[0] || "";
  return ((words[0]?.[0] || "") + second).toUpperCase();
}

/** Har bir guruhga o'z rangi — kim qaysi guruhda ekani bir qarashda ko'rinadi. */
function groupColor(groupId) {
  return GROUP_COLORS[(groupId - 1) % GROUP_COLORS.length];
}

/** Rang berilmasa ismdan olinadi: bitta odam hamma joyda bir xil rangda chiqadi. */
function avatar(name, color) {
  let hash = 0;
  for (const character of name) hash = (hash * 31 + character.codePointAt(0)) % 997;
  return h("span", { class: "avatar", style: `background: ${color || AVATAR_COLORS[hash % AVATAR_COLORS.length]}` },
    initials(name));
}

function groupBadge(group) {
  return h("span", { class: "badge", style: `background: ${groupColor(group.id)}` }, group.name);
}

function emptyState(iconName, text) {
  return h("div", { class: "empty" }, icon(iconName), h("p", null, text));
}

// ---------- xabarlar va dialoglar ----------

let toastTimer;
function toast(message, kind = "error") {
  const element = document.getElementById("toast");
  element.textContent = message;
  element.className = kind;
  element.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (element.hidden = true), kind === "error" ? 5000 : 2500);
}

function openDialog(...content) {
  const dialog = h("dialog", { class: "modal" }, content);
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();
  return dialog;
}

/** confirm() o'rniga: Telegram ichida brauzerning o'z oynalari ishlamasligi mumkin. */
function confirmDialog(title, message, confirmLabel = "Ha", danger = false) {
  return new Promise((resolve) => {
    let confirmed = false;
    const dialog = openDialog(
      h("h2", null, title),
      message && h("p", { class: "muted" }, message),
      h("div", { class: "modal-actions" },
        button("Bekor qilish", null, "secondary", () => dialog.close()),
        button(confirmLabel, null, danger ? "danger" : "", () => {
          confirmed = true;
          dialog.close();
        }, { "data-confirm": true })),
    );
    dialog.addEventListener("close", () => resolve(confirmed));
  });
}

/**
 * Forma oynasi. fields: [{ name, label, type?, options?, value?, attrs? }].
 * onSubmit(values) xato tashlasa oyna yopilmaydi va xato ichida ko'rsatiladi.
 */
function formDialog(title, fields, submitLabel, onSubmit) {
  const inputs = {};
  const error = h("p", { class: "form-error", hidden: true });
  const submit = h("button", { class: "btn" }, h("span", null, submitLabel));
  const form = h("form", { class: "modal-form" },
    h("h2", null, title),
    fields.map((field) => {
      const input = field.options
        ? select(field.options, field.value, field.attrs)
        : h("input", { type: field.type || "text", value: field.value, required: true, ...field.attrs });
      input.name = field.name;
      inputs[field.name] = input;
      return h("label", { class: "field" }, h("span", null, field.label), input);
    }),
    error,
    h("div", { class: "modal-actions" },
      button("Bekor qilish", null, "secondary", () => dialog.close()),
      submit),
  );
  const dialog = openDialog(form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.setAttribute("aria-busy", "true");
    try {
      await onSubmit(Object.fromEntries(Object.entries(inputs).map(([name, input]) => [name, input.value])));
      dialog.close();
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    } finally {
      submit.removeAttribute("aria-busy");
    }
  });
  return dialog;
}

// ---------- API ----------

function setToken(value) {
  token = value;
  try {
    if (value) localStorage.setItem("token", value);
    else localStorage.removeItem("token");
  } catch {
    // yuqoridagi kabi: storage'siz ham ishlayveradi
  }
}

let pendingRequests = 0;
function trackRequest(delta) {
  pendingRequests += delta;
  document.documentElement.classList.toggle("busy", pendingRequests > 0);
}

/** quiet: fon so'rovlari (holatni qayta so'rash) uchun — yuklanish chizig'i ko'rsatilmaydi. */
async function api(method, path, body, { quiet = false } = {}) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  if (!quiet) trackRequest(1);
  let response;
  try {
    response = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new Error("Serverga ulanib bo'lmadi. Internetni tekshiring.");
  } finally {
    if (!quiet) trackRequest(-1);
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (response.ok) return data;
  if (response.status === 401 && token && !path.startsWith("/auth/")) {
    setToken(null);
    me = null;
  }
  const detail = data?.detail;
  const message = Array.isArray(detail) ? detail.map((item) => item.msg).join("; ") : detail;
  throw Object.assign(new Error(typeof message === "string" ? message : `Xato: ${response.status}`), {
    status: response.status,
  });
}

/**
 * Tugma va formalar uchun: ish tugaguncha tugmani band qiladi (ikki marta bosilmaydi),
 * xatoni ko'rsatadi, session o'lgan bo'lsa kirish sahifasiga qaytaradi.
 */
function act(handler) {
  return async (event) => {
    event?.preventDefault?.();
    const control = event?.submitter || event?.currentTarget;
    const busy = control instanceof HTMLButtonElement ? control : null;
    if (busy?.getAttribute("aria-busy") === "true") return;
    busy?.setAttribute("aria-busy", "true");
    try {
      await handler(event);
    } catch (error) {
      toast(error.message);
      if (!me) loginView();
    } finally {
      busy?.removeAttribute("aria-busy");
    }
  };
}

function setLessonParam(roomName) {
  const search = roomName ? `?lesson=${encodeURIComponent(roomName)}` : "";
  history.replaceState(null, "", location.pathname + search + location.hash);
}

// ---------- vaqt ----------

function formatClock(value) {
  return new Date(value).toLocaleTimeString("uz", { hour: "2-digit", minute: "2-digit" });
}

function formatDate(value) {
  return new Date(value).toLocaleDateString("uz", { weekday: "long", day: "numeric", month: "long" });
}

function dayDifference(value) {
  const day = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  return Math.round((day(new Date(value)) - day(new Date())) / 86_400_000);
}

/** "Bugun", "Ertaga", "Kecha" yoki to'liq sana. */
function formatDay(value) {
  return { "-1": "Kecha", 0: "Bugun", 1: "Ertaga" }[dayDifference(value)] || formatDate(value);
}

/** Dars qachon boshlanishi: "5 daqiqadan keyin", "Boshlanish vaqti keldi" yoki null (hali uzoq). */
function startsIn(value) {
  const minutes = Math.ceil((new Date(value) - Date.now()) / 60_000);
  if (minutes <= 0) return "Boshlanish vaqti keldi";
  if (minutes < 60) return `${minutes} daqiqadan keyin`;
  return null;
}

function formatElapsed(since) {
  const seconds = Math.max(0, Math.floor((Date.now() - since) / 1000));
  const pad = (number) => String(number).padStart(2, "0");
  const hours = Math.floor(seconds / 3600);
  return `${hours ? `${hours}:` : ""}${pad(Math.floor(seconds / 60) % 60)}:${pad(seconds % 60)}`;
}

// ---------- umumiy qobiq ----------

/** Kunduzgi / tungi mavzu tugmasi. Belgi bosilganda qaysi mavzuga o'tishini ko'rsatadi. */
function themeButton() {
  const current = () => icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon");
  const toggle = iconButton("sun", "Mavzuni almashtirish", () => {
    toggleTheme();
    toggle.replaceChildren(current());
  }, "secondary");
  toggle.classList.add("theme-toggle");
  toggle.replaceChildren(current());
  return toggle;
}

const logout = act(async () => {
  await api("POST", "/auth/logout");
  setToken(null);
  me = null;
  loginView();
});

/** Yuqori panel: logotip, admin uchun bo'limlar, foydalanuvchi, mavzu va chiqish. */
function shell(activeNav, ...content) {
  const navItem = (key, label, iconName, open) =>
    h("button", { type: "button", class: `nav-item ${activeNav === key ? "active" : ""}`, onclick: act(open) },
      icon(iconName), h("span", null, label));
  render(
    h("header", { class: "topbar" },
      h("div", { class: "brand" }, h("span", { class: "brand-mark" }, icon("graduation-cap")), h("span", null, "Darslar")),
      me.role === "admin" && h("nav", null,
        navItem("users", "Foydalanuvchilar", "users", () => adminView()),
        navItem("groups", "Guruhlar", "layers", () => groupsView())),
      h("span", { class: "spacer" }),
      h("div", { class: "user-chip" },
        avatar(me.full_name),
        h("div", null, h("div", { class: "user-name" }, me.full_name), h("div", { class: "muted small" }, ROLES[me.role]))),
      themeButton(),
      iconButton("log-out", "Chiqish", logout, "secondary"),
    ),
    h("main", null, content),
  );
}
