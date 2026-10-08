# Flow

Ilova Telegram mini app sifatida ishlaydi: login, admin sahifasi va jonli dars — hammasi mini app ichida.

Jadvallar: [database.md](database.md)

## Mini app ochilganda
1. client Telegram bergan `initData` ni serverga yuboradi
2. server imzoni bot token bilan tekshiradi va undan telegram_id ni oladi
3. shu telegram_id li aktiv User bo'lsa — Session yaratiladi, pincode so'ralmaydi
4. bo'lmasa — login / register sahifasi ko'rsatiladi

## Register
1. username va pincode qoidalarga tekshiriladi
2. username band bo'lsa — xato
3. User yaratiladi (role = student, telegram_id = initData'dagi id)
4. Session yaratiladi, token qaytariladi

## Login
1. username bo'yicha User topiladi
2. pincode hash bilan solishtiriladi
3. topilmasa yoki mos kelmasa — bir xil xato: "username yoki pincode noto'g'ri"
4. is_active = false bo'lsa — rad
5. User.telegram_id yoziladi; shu telegram_id boshqa User'da turgan bo'lsa — undan olib tashlanadi
6. Session yaratiladi, token qaytariladi

## Auth (har so'rovda)
1. token hash'i bo'yicha Session topiladi
2. expires_at va User.is_active tekshiriladi
3. user_id orqali User va uning roli aniqlanadi

## Logout
1. Session o'chiriladi
2. User.telegram_id tozalanadi (aks holda mini app qayta ochilganda avtomatik kirib ketadi)

## Admin sahifasi (faqat role = admin)
1. userlar ro'yxati: qidiruv, rol bo'yicha filtr
2. user yaratish (username, pincode, full_name, role)
3. rolni o'zgartirish, full_name ni tahrirlash
4. pincode'ni almashtirish — userning barcha Session'lari o'chiriladi
5. bloklash / blokdan chiqarish (is_active) — bloklaganda Session'lar o'chiriladi
6. o'chirish — guruhi bor teacher o'chirilmaydi
7. admin o'zini bloklay, o'chira yoki rolini tushira olmaydi (tizim adminsiz qolmasligi uchun)

## Admin: guruhlar (faqat role = admin)
1. guruh yaratish: name va teacher tanlanadi (faqat role = teacher, is_active userlar ichidan)
2. guruh nomini o'zgartirish, teacher'ni almashtirish (Group.teacher_id)
3. student biriktirish / chiqarish (GroupMember; faqat role = student userlar)
4. guruhni o'chirish — uning a'zoliklari, jadvali va darslari ham o'chadi
5. teacher yoki student rolidagi userning roli o'zgartirilsa — avval guruhlardan chiqarilishi kerak, aks holda rad

## Admin: dars jadvali (faqat role = admin)
1. guruhga Schedule qo'shish: weekday, start_time, duration_min — keyingi 7 kunlik Lesson'lar shu zahoti yaratiladi (cron kutilmaydi)
2. Schedule'ni o'zgartirish — hali boshlanmagan (status = scheduled, link_sent_at bo'sh) Lesson'lari o'chiriladi va shu zahoti yangi vaqt bilan qayta yaratiladi
3. Schedule'ni o'chirish — hali boshlanmagan Lesson'lari ham o'chiriladi; o'tgan darslar qoladi (schedule_id bo'sh bo'lib)
4. jadvaldan tashqari bir martalik Lesson yaratish (schedule_id bo'sh)
5. bitta darsni bekor qilish: status = cancelled (o'chirilmaydi, aks holda cron uni qayta yaratadi)
6. bitta teacher'ning ikki guruhida vaqti ustma-ust tushadigan Schedule qo'shilmaydi

## O'qituvchi darsni o'zi boshlashi
1. o'qituvchi bosh sahifadagi "Guruhlarim" bo'limida guruh yonidagi "Dars boshlash" ni bosadi
2. guruhda jonli dars yoki 15 daqiqa ichida boshlanadigan rejali dars bo'lsa — yangi dars yaratilmaydi, o'sha ochiladi
3. aks holda hozir boshlanadigan 60 daqiqalik Lesson yaratiladi va o'qituvchi darhol unga kiradi
4. havola o'quvchilarga odatdagidek cron orqali ketadi; saytdagilar darsni "Yaqin darslar"da ko'radi

## Darslarni jadvaldan yaratish (cron, kuniga bir marta)
1. har bir Schedule uchun keyingi 7 kun ichidagi sanalar hisoblanadi
2. mavjud bo'lmaganlari uchun Lesson yaratiladi (status = scheduled)

## Havola yuborish (cron, har daqiqada)
1. status = scheduled, link_sent_at bo'sh va `starts_at - 1 daqiqa <= hozir < starts_at + duration_min` bo'lgan Lesson'lar olinadi (cron kechiksa ham dars tugamaguncha havola yuboriladi)
2. guruh teacher'i va barcha GroupMember'larga (telegram_id bor va is_active bo'lsa) bot xabar yuboradi
3. xabarda `web_app` tugmasi bo'ladi, URL: `/?lesson={room_name}` — bosilganda mini app shu darsda ochiladi
4. link_sent_at yoziladi

## Darsga kirish
1. user tugmani bosadi, mini app ochiladi va "Mini app ochilganda" oqimi orqali avtomatik login bo'ladi
2. room_name bo'yicha Lesson topiladi
3. user shu guruhning teacher'i yoki a'zosi ekani tekshiriladi, aks holda — rad
4. status tekshiriladi: cancelled — "dars bekor qilingan", ended — "dars tugagan" (recording bo'lsa ko'rsatiladi); faqat scheduled va live da davom etiladi
5. LiveKit room token beriladi (identity = User.id, name = full_name): teacher'ga publish + room admin, student'ga oddiy ishtirokchi huquqlari
6. jonli efir mini app ichida davom etadi; student teacher'dan oldin kirsa — kutib turadi
7. teacher birinchi marta kirganda status = live

## Darsni tugatish
1. teacher "Darsni tugatish" tugmasini bosadi
2. status = ended, LiveKit room o'chiriladi — barcha ishtirokchilar chiqariladi
3. teacher shunchaki chiqib ketsa yoki aloqasi uzilsa — dars tugamaydi, qayta kira oladi
4. zaxira (cron, har daqiqada): `starts_at + duration_min + 30 daqiqa` o'tgan, hali scheduled yoki live turgan Lesson'lar ended qilinadi va room o'chiriladi

## Mening darslarim (teacher va student uchun bosh sahifa)
1. user a'zo yoki teacher bo'lgan guruhlarning yaqin darslari ro'yxati (scheduled va live)
2. har birida "Kirish" tugmasi — bot xabarini o'tkazib yuborgan yoki botni kech ulagan user shu yerdan kiradi
3. tugagan darslar va ularning recording'lari

## Recording
Video API backend orqali o'tmaydi: brauzer uni to'g'ridan-to'g'ri media backend'ga yuklaydi, API faqat qisqa muddatli token beradi. Media backend bazaga ulanmaydi, tokenni umumiy kalit (MEDIA_SECRET) bilan tekshiradi.

Yozuvga nima tushadi:
- barcha ishtirokchilar kamerasi to'r (grid) bo'lib, ismlari bilan; kamerasi o'chiq ishtirokchi bo'sh katak
- kimdir ekran ulashsa — o'sha ekran katta, ishtirokchilar yon ustunda (jonli efir sahifasida ham shunday)
- ovoz: barcha ishtirokchilar aralashtirilgan holda

Yozib olish:
1. teacher "Yozib olish" ni bosadi; API recording_key ni yozadi va media backend manzili bilan upload token qaytaradi (faqat shu dars teacher'iga)
2. brauzer MediaRecorder bo'laklarini tartib raqami (seq = 0, 1, 2...) bilan media backend'ga yuboradi
3. media backend bo'lakni fayl oxiriga qo'shadi; seq kutilganidan farq qilsa — rad etadi va kutilgan raqamni aytadi (qayta yuborilgan bo'lak ikki marta yozilmaydi)
4. dars tugaganda brauzer oxirgi bo'lakni yuklaydi, keyin "Darsni tugatish" ni chaqiradi
5. API media backend'ga "yozuv tugadi" deydi; fayl yo'q bo'lsa recording_key tozalanadi
6. media backend yozuvni yopadi (endi bo'lak qabul qilmaydi) va fonda ffmpeg bilan MP4 ga (H.264 + AAC) siqib o'tkazadi — bir vaqtda bittadan
7. "O'tgan darslar" sahifasi har 2 soniyada holatni so'raydi va necha foiz bo'lganini ko'rsatadi; sahifa ochiq bo'lmasa API cron har daqiqada so'raydi
8. MP4 tayyor bo'lgach recording_ready = true, xom webm o'chiriladi, sahifada "Yozuvni ko'rish" tugmasi chiqadi
9. o'tkazish xato bersa — xom webm o'zi beriladi, yozuv yo'qolmaydi

Teacher brauzeri yopilib qolsa:
1. yuklangan bo'laklar media backend'da qoladi
2. "Darsni tugatish" zaxira cron'i darsni yopganda recording ham yuqoridagi 5–7-qadamlar bilan yakunlanadi
3. media backend javob bermasa — cron har daqiqada qayta urinadi

Ko'rish:
1. guruh a'zosi yoki teacher recording'ni so'raydi; API a'zolikni va recording_ready ni tekshiradi
2. API qisqa muddatli view token bilan media backend havolasini beradi; video media backend'dan to'g'ridan-to'g'ri o'ynaladi
