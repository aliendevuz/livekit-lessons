// Admin panel: foydalanuvchilar, guruhlar, jadval va darslar.

const ROLE_OPTIONS = Object.entries(ROLES).map(([role, label]) => [role, label]);
const PINCODE_ATTRS = { inputmode: "numeric", pattern: "\\d{4,6}", placeholder: "4-6 raqam", autocomplete: "off" };

// ---------- foydalanuvchilar ----------

async function adminView() {
  const users = await api("GET", "/admin/users");
  let roleFilter = "";
  const search = h("input", { type: "search", placeholder: "Ism yoki username bo'yicha qidirish", "aria-label": "Qidirish" });
  const list = h("div", { class: "list" });
  const filters = h("div", { class: "segmented" });

  const change = (user, body, done) => act(async () => {
    await api("PATCH", `/admin/users/${user.id}`, body);
    if (done) toast(done, "success");
    await adminView();
  });

  function userRow(user) {
    const isMe = user.id === me.id;
    const roleSelect = select(ROLE_OPTIONS, user.role, { disabled: isMe, "aria-label": "Rol" });
    roleSelect.addEventListener("change", act(async () => {
      try {
        await api("PATCH", `/admin/users/${user.id}`, { role: roleSelect.value });
        toast("Rol o'zgartirildi", "success");
      } finally {
        // rad etilgan bo'lsa select eski rolga qaytadi
        await adminView();
      }
    }));
    return h("div", { class: `card row ${user.is_active ? "" : "blocked"}`, "data-username": user.username },
      avatar(user.full_name),
      h("div", { class: "grow" },
        h("div", { class: "row-title" }, user.full_name,
          isMe && h("span", { class: "chip" }, "Siz"),
          !user.is_active && h("span", { class: "chip danger" }, "Bloklangan"),
          user.telegram_linked && h("span", { class: "chip", title: "Telegram ulangan" }, icon("send"), "Telegram")),
        h("div", { class: "muted small" }, `@${user.username}`)),
      roleSelect,
      h("div", { class: "row-actions" },
        iconButton("key-round", "Pincode'ni almashtirish", () =>
          formDialog(`${user.full_name}: yangi pincode`,
            [{ name: "pincode", label: "Yangi pincode", attrs: PINCODE_ATTRS }], "Saqlash", async ({ pincode }) => {
              await api("PATCH", `/admin/users/${user.id}`, { pincode });
              toast("Pincode almashtirildi", "success");
            })),
        !isMe && (user.is_active
          ? iconButton("ban", "Bloklash", change(user, { is_active: false }, "Foydalanuvchi bloklandi"))
          : iconButton("circle-check", "Blokdan chiqarish", change(user, { is_active: true }, "Blokdan chiqarildi"))),
        !isMe && iconButton("trash-2", "O'chirish", act(async () => {
          if (!await confirmDialog(`${user.full_name} o'chirilsinmi?`, "Bu amalni qaytarib bo'lmaydi.", "O'chirish", true)) return;
          await api("DELETE", `/admin/users/${user.id}`);
          toast("Foydalanuvchi o'chirildi", "success");
          await adminView();
        }), "ghost danger-text")),
    );
  }

  function renderList() {
    const query = search.value.trim().toLowerCase();
    const visible = users.filter((user) =>
      (!roleFilter || user.role === roleFilter)
      && (!query || user.full_name.toLowerCase().includes(query) || user.username.includes(query)));
    list.replaceChildren(...(visible.length ? visible.map(userRow) : [emptyState("search", "Hech kim topilmadi")]));
    filters.replaceChildren(...[["", "Hammasi"], ...ROLE_OPTIONS].map(([role, label]) => {
      const count = role ? users.filter((user) => user.role === role).length : users.length;
      return h("button", {
        type: "button", class: role === roleFilter ? "active" : "",
        onclick: () => {
          roleFilter = role;
          renderList();
        },
      }, `${label} `, h("span", { class: "count" }, String(count)));
    }));
  }
  search.addEventListener("input", renderList);

  const addUser = () => formDialog("Yangi foydalanuvchi", [
    { name: "full_name", label: "Ism familiya", attrs: { maxlength: 64 } },
    { name: "username", label: "Username", attrs: { pattern: "[A-Za-z0-9_]{3,32}", placeholder: "a-z, 0-9, _", autocomplete: "off" } },
    { name: "pincode", label: "Pincode", attrs: PINCODE_ATTRS },
    { name: "role", label: "Rol", options: ROLE_OPTIONS, value: "student" },
  ], "Qo'shish", async (values) => {
    await api("POST", "/admin/users", values);
    toast("Foydalanuvchi qo'shildi", "success");
    await adminView();
  });

  shell("users",
    h("div", { class: "page-title with-action" },
      h("div", null, h("h1", null, "Foydalanuvchilar"), h("p", { class: "muted" }, "Rollar, pincode va bloklash.")),
      button("Foydalanuvchi qo'shish", "user-plus", "", addUser)),
    h("div", { class: "toolbar" }, h("div", { class: "search" }, icon("search"), search), filters),
    list,
  );
  renderList();
}

// ---------- guruhlar ----------

async function groupsView() {
  const [groups, teachers] = await Promise.all([api("GET", "/admin/groups"), api("GET", "/admin/users?role=teacher")]);
  const teacherOptions = teachers.filter((user) => user.is_active).map((user) => [user.id, user.full_name]);
  const addGroup = () => {
    if (!teacherOptions.length) return toast("Avval o'qituvchi rolidagi foydalanuvchi qo'shing");
    formDialog("Yangi guruh", [
      { name: "name", label: "Guruh nomi", attrs: { maxlength: 64 } },
      { name: "teacher_id", label: "O'qituvchi", options: teacherOptions },
    ], "Yaratish", async ({ name, teacher_id }) => {
      const group = await api("POST", "/admin/groups", { name, teacher_id: Number(teacher_id) });
      toast("Guruh yaratildi", "success");
      await groupView(group.id);
    });
  };
  shell("groups",
    h("div", { class: "page-title with-action" },
      h("div", null, h("h1", null, "Guruhlar"), h("p", { class: "muted" }, "O'quvchilar, jadval va darslar guruh ichida boshqariladi.")),
      button("Guruh yaratish", "plus", "", addGroup)),
    groups.length
      ? h("div", { class: "group-grid" }, groups.map((group) =>
        h("button", { type: "button", class: "card group-card", onclick: act(() => groupView(group.id)), "data-group": group.name },
          h("span", { class: "group-stripe", style: `background: ${groupColor(group.id)}` }),
          h("div", { class: "grow" },
            h("div", { class: "row-title" }, group.name),
            h("div", { class: "muted small" }, `O'qituvchi: ${group.teacher_name}`),
            h("div", { class: "muted small" }, `${group.member_count} o'quvchi`)),
          icon("chevron-right"))))
      : emptyState("layers", "Hali guruh yo'q. Birinchi guruhni yarating."),
  );
}

async function groupView(groupId) {
  const [group, teachers, students] = await Promise.all([
    api("GET", `/admin/groups/${groupId}`),
    api("GET", "/admin/users?role=teacher"),
    api("GET", "/admin/users?role=student"),
  ]);
  const reload = () => groupView(groupId);
  const run = (method, path, done, body) => act(async () => {
    await api(method, path, body);
    if (done) toast(done, "success");
    await reload();
  });

  const teacher = select(teachers.filter((user) => user.is_active).map((user) => [user.id, user.full_name]),
    group.teacher.id, { "aria-label": "O'qituvchi" });
  teacher.addEventListener("change", act(async () => {
    await api("PATCH", `/admin/groups/${groupId}`, { teacher_id: Number(teacher.value) });
    toast("O'qituvchi almashtirildi", "success");
    await reload();
  }));

  // --- o'quvchilar ---
  const memberIds = new Set(group.members.map((user) => user.id));
  const candidates = students.filter((user) => user.is_active && !memberIds.has(user.id));
  const newMember = select(candidates.map((user) => [user.id, `${user.full_name} (@${user.username})`]),
    null, { "aria-label": "Qo'shiladigan o'quvchi" });
  const addMember = act(async () => {
    await api("PUT", `/admin/groups/${groupId}/members/${newMember.value}`);
    toast("O'quvchi qo'shildi", "success");
    await reload();
  });

  // --- haftalik jadval ---
  const weekday = select(WEEKDAYS.map((label, index) => [index + 1, label]), ((new Date().getDay() + 6) % 7) + 1,
    { "aria-label": "Hafta kuni" });
  const startTime = h("input", { type: "time", required: true, "aria-label": "Boshlanish vaqti" });
  const duration = h("input", { type: "number", min: 1, max: 600, value: 60, required: true, class: "narrow", "aria-label": "Davomiyligi" });
  const addSchedule = act(async () => {
    await api("POST", `/admin/groups/${groupId}/schedules`, {
      weekday: Number(weekday.value), start_time: startTime.value, duration_min: Number(duration.value),
    });
    toast("Jadval qo'shildi", "success");
    await reload();
  });

  // --- darslar ---
  const createLesson = (startsAt, minutes, done) => act(async () => {
    await api("POST", `/admin/groups/${groupId}/lessons`, { starts_at: startsAt().toISOString(), duration_min: minutes() });
    toast(done, "success");
    await reload();
  });
  const pad = (number) => String(number).padStart(2, "0");
  const soon = new Date(Date.now() + 10 * 60_000);
  const lessonStart = h("input", {
    type: "datetime-local", required: true, "aria-label": "Dars vaqti",
    value: `${soon.getFullYear()}-${pad(soon.getMonth() + 1)}-${pad(soon.getDate())}T${pad(soon.getHours())}:${pad(soon.getMinutes())}`,
  });
  const lessonDuration = h("input", { type: "number", min: 1, max: 600, value: 60, required: true, class: "narrow", "aria-label": "Davomiyligi" });

  shell("groups",
    h("div", { class: "page-title with-back with-action" },
      iconButton("arrow-left", "Guruhlar ro'yxatiga", act(() => groupsView()), "secondary"),
      h("div", { class: "grow" },
        h("h1", null, h("span", { class: "group-dot", style: `background: ${groupColor(group.id)}` }), group.name),
        h("p", { class: "muted" }, `${group.members.length} o'quvchi · ${group.schedules.length} ta haftalik dars`)),
      button("Guruhni o'chirish", "trash-2", "ghost danger-text", act(async () => {
        const confirmed = await confirmDialog(`«${group.name}» o'chirilsinmi?`,
          "Guruh bilan birga uning jadvali va barcha darslari ham o'chadi.", "O'chirish", true);
        if (!confirmed) return;
        await api("DELETE", `/admin/groups/${groupId}`);
        toast("Guruh o'chirildi", "success");
        await groupsView();
      }))),

    h("div", { class: "panels" },
      h("section", { class: "card panel", "data-panel": "teacher" },
        h("h2", null, "O'qituvchi"),
        h("div", { class: "inline-form" }, avatar(group.teacher.full_name, groupColor(group.id)), teacher)),

      h("section", { class: "card panel", "data-panel": "lessons" },
        h("div", { class: "panel-head" },
          h("h2", null, "Darslar"),
          button("Hozir dars boshlash", "zap", "", createLesson(() => new Date(), () => 60, "Dars yaratildi — ishtirokchilar kira oladi"),
            { "data-quick-lesson": true })),
        h("p", { class: "muted small" }, "Tezkor dars darhol ochiladi va 60 daqiqa davom etadi. Boshqa vaqtga rejalashtirish:"),
        h("form", { class: "inline-form", onsubmit: createLesson(() => new Date(lessonStart.value), () => Number(lessonDuration.value), "Dars rejalashtirildi") },
          lessonStart, lessonDuration, h("span", { class: "muted small" }, "daqiqa"),
          h("button", { class: "btn secondary" }, icon("calendar-plus"), h("span", null, "Rejalashtirish"))),
        group.lessons.length
          ? h("div", { class: "list compact" }, group.lessons.map((lesson) =>
            h("div", { class: "row" },
              h("div", { class: "grow" },
                h("div", { class: "row-title" }, `${formatDay(lesson.starts_at)}, ${formatClock(lesson.starts_at)}`,
                  h("span", { class: `chip ${lesson.status === "live" ? "live" : ""}` },
                    lesson.status === "live" && h("span", { class: "dot" }), STATUS[lesson.status])),
                h("div", { class: "muted small" }, `${lesson.duration_min} daqiqa · ${lesson.schedule_id ? "jadval bo'yicha" : "bir martalik"}`)),
              lesson.status === "scheduled"
                && button("Bekor qilish", "x", "ghost", run("POST", `/admin/lessons/${lesson.id}/cancel`, "Dars bekor qilindi")))))
          : emptyState("calendar-days", "Yaqin darslar yo'q")),

      h("section", { class: "card panel", "data-panel": "members" },
        h("h2", null, "O'quvchilar ", h("span", { class: "count" }, String(group.members.length))),
        candidates.length
          ? h("form", { class: "inline-form", onsubmit: addMember }, newMember,
            h("button", { class: "btn secondary" }, icon("user-plus"), h("span", null, "Qo'shish")))
          : h("p", { class: "muted small" }, "Barcha o'quvchilar shu guruhda."),
        group.members.length
          ? h("div", { class: "list compact" }, group.members.map((user) =>
            h("div", { class: "row", "data-username": user.username },
              avatar(user.full_name, groupColor(group.id)),
              h("div", { class: "grow" }, h("div", { class: "row-title" }, user.full_name), h("div", { class: "muted small" }, `@${user.username}`)),
              iconButton("user-minus", "Guruhdan chiqarish", run("DELETE", `/admin/groups/${groupId}/members/${user.id}`, "O'quvchi guruhdan chiqarildi")))))
          : emptyState("users", "Guruhda hali o'quvchi yo'q")),

      h("section", { class: "card panel", "data-panel": "schedule" },
        h("h2", null, "Haftalik jadval"),
        h("p", { class: "muted small" }, "Toshkent vaqti bo'yicha. Darslar jadvaldan o'zi yaratiladi."),
        h("form", { class: "inline-form", onsubmit: addSchedule }, weekday, startTime, duration, h("span", { class: "muted small" }, "daqiqa"),
          h("button", { class: "btn secondary" }, icon("plus"), h("span", null, "Qo'shish"))),
        group.schedules.length
          ? h("div", { class: "list compact" }, group.schedules.map((schedule) =>
            h("div", { class: "row" },
              h("span", { class: "row-icon" }, icon("clock")),
              h("div", { class: "grow" },
                h("div", { class: "row-title" }, `${WEEKDAYS[schedule.weekday - 1]}, ${schedule.start_time}`),
                h("div", { class: "muted small" }, `${schedule.duration_min} daqiqa`)),
              iconButton("trash-2", "Jadvaldan o'chirish", run("DELETE", `/admin/schedules/${schedule.id}`, "Jadvaldan o'chirildi")))))
          : emptyState("clock", "Haftalik jadval bo'sh")),
    ),
  );
}
