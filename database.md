# Database

## User

- id: int (PK)
- username: str(32) (unique, case-insensitive)
- pincode_hash: str
- role: enum(admin, teacher, student)
- full_name: str(64)
- telegram_id: bigint (unique, nullable)
- is_active: bool (default true)
- created_at: datetime

Qoidalar:
- username: 3–32 belgi, faqat `a-z`, `0-9`, `_`; saqlashdan oldin lowercase qilinadi
- pincode: 4–6 raqam; ochiq holda saqlanmaydi, faqat hash (bcrypt / argon2)
- register qilgan har bir user student bo'ladi; rolni faqat admin o'zgartiradi
- birinchi admin seed orqali yaratiladi (env'dagi username + pincode)
- telegram_id mini app ichida login qilinganda avtomatik yoziladi; bo'sh bo'lsa — havola yuborilmaydi
- is_active = false bo'lsa — user bloklangan: login qila olmaydi, darsga kira olmaydi

## Session

- id: int (PK)
- user_id: int (FK → User.id, on delete cascade)
- token_hash: str (unique)
- created_at: datetime
- expires_at: datetime
- last_seen_at: datetime (nullable)

Qoidalar:
- last_seen_at: shu session bilan oxirgi so'rov vaqti; sahifa har 20 soniyada signal yuboradi. 90 soniya ichida signal kelgan hisob "band" hisoblanadi va sinov rejimidagi kirish ro'yxatida ko'rinmaydi
- token: tasodifiy 32 bayt, clientga bir marta beriladi; bazada faqat hash'i turadi
- expires_at o'tgan session yaroqsiz
- bitta user'da bir nechta session bo'lishi mumkin (har qurilma uchun alohida)

## Group

- id: int (PK)
- teacher_id: int (FK → User.id, on delete restrict)
- name: str(64)
- created_at: datetime

Qoidalar:
- guruhi bor teacher'ni o'chirib bo'lmaydi — avval guruh boshqa teacher'ga o'tkaziladi yoki user bloklanadi

## GroupMember

- group_id: int (FK → Group.id, on delete cascade)
- student_id: int (FK → User.id, on delete cascade)
- joined_at: datetime
- PK: (group_id, student_id)

## Schedule

- id: int (PK)
- group_id: int (FK → Group.id, on delete cascade)
- weekday: int (1–7, dushanba = 1)
- start_time: time
- duration_min: int

Qoidalar:
- haftalik takrorlanadigan jadval; bitta guruhda bir nechta qator bo'lishi mumkin (masalan Du/Chor/Juma)
- start_time mahalliy vaqtda (Asia/Tashkent)

## Lesson

- id: int (PK)
- group_id: int (FK → Group.id, on delete cascade)
- schedule_id: int (FK → Schedule.id, nullable, on delete set null)
- starts_at: datetime (UTC)
- duration_min: int
- room_name: str(64) (unique)
- status: enum(scheduled, live, ended, cancelled)
- link_sent_at: datetime (nullable)
- recording_key: str (nullable)
- recording_ready: bool (default false)
- created_at: datetime
- unique: (schedule_id, starts_at)

Qoidalar:
- bitta Lesson = bitta aniq dars = bitta LiveKit room
- room_name tasodifiy generatsiya qilinadi (faqat `A-Z a-z 0-9 _ -`); mini app sahifasi: `/?lesson={room_name}`
- schedule_id bo'sh bo'lsa — jadvaldan tashqari, qo'lda yaratilgan dars
- link_sent_at bo'sh emas bo'lsa — havola allaqachon yuborilgan, qayta yuborilmaydi
- unique (schedule_id, starts_at) bitta dars ikki marta yaratilishining oldini oladi
- recording fayli API serverda emas, alohida media backend'da turadi; bazada faqat uning kaliti saqlanadi
- recording_key: media backend'dagi fayl nomi; yozib olish boshlanganda `{room_name}.webm`, MP4 ga o'tkazilgach `{room_name}.mp4`
- recording_ready = true bo'lgandagina recording ko'rsatiladi; recording_key bor, lekin ready emas — "tayyorlanmoqda"

## Bog'lanish

```text
User 1 ──── N Session
User(teacher) 1 ──── N Group
Group N ──── N User(student)      (GroupMember orqali)
Group 1 ──── N Schedule
Group 1 ──── N Lesson
Schedule 1 ──── N Lesson
```

