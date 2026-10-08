// Kirish, darslar ro'yxati va yozuvni ko'rish sahifalari. Umumiy yordamchilar: ui.js

const HOME_REFRESH_MS = 15000;

async function boot() {
  telegram?.ready();
  telegram?.expand();
  if (token) {
    try {
      me = await api("GET", "/me");
    } catch {
      setToken(null);
    }
  }
  if (!me && initData) {
    try {
      const session = await api("POST", "/auth/telegram", { init_data: initData });
      setToken(session.token);
      me = session.user;
    } catch (error) {
      // 404: bu Telegram akkaunt hali ulanmagan — kirish sahifasi ko'rsatiladi
      if (error.status !== 404) toast(error.message);
    }
  }
  route();
}

async function route() {
  if (!me) return loginView();
  const roomName = new URLSearchParams(location.search).get("lesson");
  if (roomName) {
    try {
      return await lessonView(roomName);
    } catch (error) {
      toast(error.message);
      setLessonParam(null);
      if (!me) return loginView();
    }
  }
  await act(me.role === "admin" ? () => adminView() : () => homeView())();
}

// ---------- kirish ----------

/** Kirish sahifasi: bo'sh hisoblar ro'yxati, ustiga bosilsa kiriladi. Band hisoblar ko'rinmaydi. */
async function loginView(known) {
  let users = known || [];
  if (!known) {
    try {
      users = await api("GET", "/auth/demo");
    } catch (error) {
      toast(error.message);
    }
  }
  const enter = (user) => act(async () => {
    let session;
    try {
      session = await api("POST", "/auth/demo", { username: user.username, init_data: initData || null });
    } catch (error) {
      if (error.status === 409) loginView(); // shu hisobni boshqa kishi ulgurib tanladi — ro'yxat yangilanadi
      throw error;
    }
    setToken(session.token);
    me = session.user;
    await route();
  });
  const section = (title, role) => {
    const list = users.filter((user) => user.role === role);
    return list.length > 0 && h("section", null,
      h("h2", null, title, " ", h("span", { class: "count" }, String(list.length))),
      h("div", { class: "account-grid" }, list.map((user) =>
        h("button", { type: "button", class: "account", onclick: enter(user) },
          avatar(user.full_name, user.groups[0] && groupColor(user.groups[0].id)),
          h("div", { class: "account-text" },
            h("div", { class: "account-name" }, user.full_name),
            h("div", { class: "muted small" }, `@${user.username}`)),
          h("div", { class: "badges" }, user.groups.map(groupBadge))))));
  };
  const root = h("div", { class: "login" },
    h("div", { class: "login-top" }, themeButton()),
    h("div", { class: "login-hero" },
      h("span", { class: "brand-mark large" }, icon("graduation-cap")),
      h("h1", null, "Onlayn darslar"),
      h("p", { class: "muted" }, users.length
        ? "Bo'sh hisoblardan birini tanlang. Band hisoblar ro'yxatda ko'rinmaydi."
        : "Hozir bo'sh hisob yo'q. Kimdir chiqishi bilan shu yerda paydo bo'ladi.")),
    section("O'qituvchilar", "teacher"),
    section("O'quvchilar", "student"),
    h("p", { class: "login-admin" }, button("Admin sifatida kirish", "key-round", "ghost", adminLogin)),
  );
  render(root);

  // Ro'yxat o'zi yangilanadi: kimdir hisob tanlasa, u boshqalarning ekranidan yo'qoladi
  const snapshot = JSON.stringify(users);
  const timer = setInterval(async () => {
    if (!root.isConnected) return clearInterval(timer);
    let fresh;
    try {
      fresh = await api("GET", "/auth/demo", null, { quiet: true });
    } catch {
      return; // vaqtinchalik xato — keyingi safar yana so'raladi
    }
    if (root.isConnected && JSON.stringify(fresh) !== snapshot) {
      clearInterval(timer);
      loginView(fresh);
    }
  }, ACCOUNTS_REFRESH_MS);
}

/** Admin tayyor hisoblar ro'yxatida yo'q: unga username va pincode bilan kiriladi. */
function adminLogin() {
  formDialog("Admin sifatida kirish", [
    { name: "username", label: "Username", value: "admin", attrs: { autocomplete: "username" } },
    { name: "pincode", label: "Pincode", type: "password", attrs: { inputmode: "numeric", autocomplete: "current-password" } },
  ], "Kirish", async ({ username, pincode }) => {
    const session = await api("POST", "/auth/login", { username, pincode, init_data: initData || null });
    setToken(session.token);
    me = session.user;
    await route();
  });
}

// ---------- mening darslarim ----------

function lessonCard(lesson, action) {
  const live = lesson.status === "live";
  const soon = !live && lesson.status === "scheduled" && startsIn(lesson.starts_at);
  return h("div", { class: `card lesson ${live ? "live" : ""}` },
    h("div", { class: "lesson-time" },
      h("div", { class: "lesson-clock" }, formatClock(lesson.starts_at)),
      h("div", { class: "muted small" }, formatDay(lesson.starts_at))),
    h("div", { class: "lesson-body" },
      h("div", { class: "lesson-title" }, lesson.group_name,
        live && h("span", { class: "chip live" }, h("span", { class: "dot" }), STATUS.live),
        soon && h("span", { class: "chip soon" }, soon)),
      h("div", { class: "muted small" },
        lesson.is_teacher ? "Siz o'qituvchisiz" : `O'qituvchi: ${lesson.teacher_name}`, ` · ${lesson.duration_min} daqiqa`)),
    h("div", { class: "lesson-action" }, action),
  );
}

async function homeView(data, knownGroups) {
  const lessons = data || await api("GET", "/lessons");
  const groups = knownGroups || (me.role === "teacher" ? await api("GET", "/lessons/groups") : []);
  const { upcoming, past } = lessons;
  const startNow = (group) => act(async () => {
    const { room_name } = await api("POST", `/lessons/groups/${group.id}/start`);
    await lessonView(room_name);
  });
  const joinLabel = (lesson) => {
    if (lesson.status === "live") return "Darsga kirish";
    return lesson.is_teacher ? "Darsni boshlash" : "Kirish";
  };
  const root = h("div", null,
    h("div", { class: "page-title" }, h("div", null,
      h("h1", null, `Salom, ${me.full_name}`),
      h("p", { class: "muted" }, upcoming.some((lesson) => lesson.status === "live")
        ? "Hozir jonli dars ketmoqda."
        : upcoming.length ? "Yaqin darslaringiz quyida." : "Hozircha rejalashtirilgan dars yo'q."))),
    groups.length > 0 && h("section", null,
      h("h2", null, "Guruhlarim"),
      h("div", { class: "list" }, groups.map((group) =>
        h("div", { class: "card group-row", "data-group": group.name },
          h("span", { class: "group-stripe", style: `background: ${groupColor(group.id)}` }),
          h("div", { class: "grow" },
            h("div", { class: "row-title" }, group.name),
            h("div", { class: "muted small" }, `${group.member_count} o'quvchi`)),
          button("Dars boshlash", "zap", "", startNow(group), { "data-start": group.id }))))),
    h("section", null,
      h("h2", null, "Yaqin darslar"),
      upcoming.length
        ? h("div", { class: "list" }, upcoming.map((lesson) => lessonCard(lesson,
          button(joinLabel(lesson), "log-in", lesson.status === "live" ? "" : "secondary",
            act(() => lessonView(lesson.room_name)), { "data-join": lesson.room_name }))))
        : emptyState("calendar-days", "Dars rejalashtirilganda shu yerda ko'rinadi")),
    h("section", null,
      h("h2", null, "O'tgan darslar"),
      past.length
        ? h("div", { class: "list" }, past.map((lesson) => lessonCard(lesson, recordingAction(lesson))))
        : emptyState("film", "Tugagan darslar va ularning yozuvlari shu yerda turadi")),
  );
  shell(null, root);

  // Ro'yxat o'zi yangilanadi: dars boshlanganda "Jonli efir" belgisi sahifani yangilamasdan chiqadi
  const snapshot = JSON.stringify(lessons);
  const timer = setInterval(async () => {
    if (!root.isConnected) return clearInterval(timer);
    let fresh;
    try {
      fresh = await api("GET", "/lessons", null, { quiet: true });
    } catch {
      if (!me) loginView();
      return; // vaqtinchalik xato — keyingi safar yana so'raladi
    }
    const labelsMayChange = fresh.upcoming.some((lesson) => startsIn(lesson.starts_at));
    if (root.isConnected && !document.querySelector("dialog[open]")
        && (JSON.stringify(fresh) !== snapshot || labelsMayChange)) {
      clearInterval(timer);
      homeView(fresh, groups);
    }
  }, HOME_REFRESH_MS);
}

/** O'tgan dars yonidagi tugma: yozuv tayyor bo'lsa ko'rish, tayyorlanayotgan bo'lsa foiz. */
function recordingAction(lesson) {
  const watchButton = () => button("Yozuvni ko'rish", "play", "secondary", act(() => playerView(lesson)));
  const none = () => h("span", { class: "muted small" }, "Yozuv yo'q");
  if (lesson.recording === "ready") return watchButton();
  if (lesson.recording !== "processing") return none();

  const label = h("span", { class: "muted small" }, "Yozuv tayyorlanmoqda...");
  const bar = h("progress", { max: 100 });
  const box = h("div", { class: "progress" }, label, bar);
  const poll = async () => {
    if (!box.isConnected) return; // sahifa almashgan
    let status;
    try {
      status = await api("GET", `/lessons/${lesson.room_name}/recording/status`, null, { quiet: true });
    } catch {
      if (!me) return loginView();
      return setTimeout(poll, RECORDING_POLL_MS); // vaqtinchalik xato — yana so'raladi
    }
    if (status.state === "ready") return box.replaceWith(watchButton());
    if (status.state === "none") return box.replaceWith(none());
    if (status.progress != null) {
      bar.value = status.progress;
      label.textContent = `Yozuv tayyorlanmoqda: ${status.progress}%`;
    }
    setTimeout(poll, RECORDING_POLL_MS);
  };
  setTimeout(poll, 300);
  return box;
}

async function playerView(lesson) {
  const { url } = await api("GET", `/lessons/${lesson.room_name}/recording`);
  shell(null,
    h("div", { class: "page-title with-back" },
      iconButton("arrow-left", "Orqaga", act(() => homeView()), "secondary"),
      h("div", null,
        h("h1", null, lesson.group_name),
        h("p", { class: "muted" }, `${formatDay(lesson.starts_at)}, ${formatClock(lesson.starts_at)} · dars yozuvi`))),
    h("video", { class: "player", src: url, controls: true, playsinline: true, autoplay: true }),
  );
}

boot();
