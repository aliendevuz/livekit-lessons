// Jonli dars sahifasi. Butun ekranni egallaydi va mavzudan qat'i nazar to'q rangda turadi.

const TILE_RATIO = 16 / 9;
const TILE_GAP = 8;

async function lessonView(roomName) {
  const LK = window.LivekitClient;
  const info = await api("POST", `/lessons/${roomName}/join`);
  setLessonParam(roomName);

  // adaptiveStream tab fonda bo'lganda videoni to'xtatadi — yozib olayotgan teacher'da bu yozuvni buzadi
  const room = new LK.Room({ adaptiveStream: !info.is_teacher, dynacast: true });
  const local = room.localParticipant;
  const stage = h("div", { class: "stage" }); // ulashilayotgan ekranlar: katta ko'rinadi
  const grid = h("div", { class: "grid" }); // ishtirokchilar
  const view = h("div", { class: "room" }, stage, grid);
  const tiles = new Map();
  const mounted = new Map(); // track -> sahifaga qo'yilgan element
  let recorder = null;
  let closing = false;
  let endedByMe = false;

  // ---------- ishtirokchi kataklari ----------

  function nameOf(participant) {
    return participant.name || (participant === local ? me.full_name : participant.identity);
  }
  function tileFor(participant) {
    if (!tiles.has(participant.identity)) {
      const name = nameOf(participant);
      const tile = h("div", { class: "tile no-video muted-mic", "data-name": name },
        avatar(name),
        h("div", { class: "name" },
          h("span", { class: "mic-off" }, icon("mic-off")),
          h("span", { class: "name-text" }, participant === local ? `${name} (siz)` : name)));
      tiles.set(participant.identity, tile);
      grid.append(tile);
      layout();
    }
    return tiles.get(participant.identity);
  }
  /** Katakdagi belgilar: kamera o'chiq bo'lsa ism bosh harflari, mikrofon o'chiq bo'lsa belgi. */
  function updateTile(participant) {
    const tile = tiles.get(participant.identity);
    if (!tile) return;
    const microphone = participant.getTrackPublication(LK.Track.Source.Microphone);
    tile.classList.toggle("muted-mic", !microphone || microphone.isMuted);
    tile.classList.toggle("no-video", !tile.querySelector("video:not([hidden])"));
  }
  function attach(track, participant) {
    let node = track.attach();
    if (track.kind === LK.Track.Kind.Video && track.source === LK.Track.Source.ScreenShare) {
      const name = `${nameOf(participant)} — ekran`;
      node = h("div", { class: "tile screen", "data-name": name }, node,
        h("div", { class: "name" }, h("span", { class: "name-text" }, name)));
      stage.append(node);
    } else {
      tileFor(participant).prepend(node);
    }
    mounted.set(track, node);
    updateTile(participant);
    layout();
  }
  function detach(track, participant) {
    // track.detach() ga tayanib bo'lmaydi: uzoqdagi ishtirokchi trekni olib tashlaganda u bo'sh qaytadi
    track.detach();
    mounted.get(track)?.remove();
    mounted.delete(track);
    if (participant) updateTile(participant);
    layout();
  }
  function showMuted(publication, participant) {
    // kamera o'chirilganda qotib qolgan kadr o'rniga ism bosh harflari ko'rinadi
    publication.track?.attachedElements.forEach((element) => {
      if (element.tagName === "VIDEO") element.hidden = publication.isMuted;
    });
    updateTile(participant);
  }
  /** Kataklar ekranga sig'adigan eng katta o'lchamda joylashadi. */
  function layout() {
    const sharing = stage.childElementCount > 0;
    view.classList.toggle("sharing", sharing);
    peopleCount.textContent = String(tiles.size);
    if (sharing) {
      grid.style.maxWidth = "";
      return;
    }
    const count = Math.max(1, tiles.size);
    const portrait = view.clientWidth < view.clientHeight;
    const columns = portrait ? (count <= 2 ? 1 : 2) : Math.ceil(Math.sqrt(count));
    const rows = Math.ceil(count / columns);
    const tileHeight = (view.clientHeight - TILE_GAP * (rows - 1)) / rows;
    const fitWidth = tileHeight * TILE_RATIO * columns + TILE_GAP * (columns - 1);
    grid.style.setProperty("--columns", columns);
    grid.style.maxWidth = `${Math.floor(Math.min(view.clientWidth, fitWidth))}px`;
  }
  /** Yozuv uchun hozirgi sahna: kim ekran ulashyapti va kimlar qatnashyapti. */
  function scene() {
    const visible = (root) => root.querySelector("video:not([hidden])");
    return {
      screens: [...stage.children].map((tile) => ({ video: visible(tile), name: tile.dataset.name })),
      people: [...tiles.values()].map((tile) => ({ video: visible(tile), name: tile.dataset.name })),
    };
  }

  // ---------- yuqori panel ----------

  const joinedAt = Date.now();
  const elapsed = h("span", null, "00:00");
  const peopleCount = h("span", null, "1");
  const recordingTime = h("span", null, "00:00");
  const recordingChip = h("span", { class: "chip rec", hidden: true }, h("span", { class: "dot" }), "REC ", recordingTime);
  let recordingSince = 0;
  const clock = setInterval(() => {
    elapsed.textContent = formatElapsed(joinedAt);
    if (recordingSince) recordingTime.textContent = formatElapsed(recordingSince);
  }, 1000);

  // ---------- boshqaruv tugmalari ----------

  function control(action, onclick, variant = "") {
    return h("button", { type: "button", class: `ctl ${variant}`, "data-action": action, onclick: act(onclick) },
      h("span", { class: "ctl-icon" }), h("span", { class: "ctl-label" }));
  }
  function setControl(element, iconName, label, state = "") {
    element.querySelector(".ctl-icon").replaceChildren(icon(iconName));
    element.querySelector(".ctl-label").textContent = label;
    element.title = label;
    element.dataset.state = state;
  }

  const micButton = control("mic", () => local.setMicrophoneEnabled(!local.isMicrophoneEnabled).then(refresh));
  const cameraButton = control("camera", () => local.setCameraEnabled(!local.isCameraEnabled).then(refresh));
  const screenButton = control("screen", () => local.setScreenShareEnabled(!local.isScreenShareEnabled).then(refresh));
  const recordButton = control("record", toggleRecording);
  const leaveButton = control("leave", () => close());
  const endButton = control("end", endLesson, "danger");
  const audioButton = h("button", { type: "button", class: "audio-blocked", hidden: true, onclick: act(() => room.startAudio()) },
    icon("volume-2"), h("span", null, "Ovozni yoqish uchun bosing"));
  setControl(recordButton, "circle", "Yozib olish");
  setControl(leaveButton, "log-out", "Chiqish");
  setControl(endButton, "phone-off", "Darsni tugatish");

  function refresh() {
    setControl(micButton, local.isMicrophoneEnabled ? "mic" : "mic-off", "Mikrofon", local.isMicrophoneEnabled ? "" : "off");
    setControl(cameraButton, local.isCameraEnabled ? "video" : "video-off", "Kamera", local.isCameraEnabled ? "" : "off");
    setControl(screenButton, local.isScreenShareEnabled ? "monitor-off" : "monitor-up",
      local.isScreenShareEnabled ? "Ulashishni to'xtatish" : "Ekranni ulashish", local.isScreenShareEnabled ? "active" : "");
    updateTile(local);
  }

  // ---------- yozib olish ----------

  function recordingEnded(label, iconName) {
    recordingSince = 0;
    recordingChip.hidden = true;
    setControl(recordButton, iconName, label, "done");
    recordButton.disabled = true;
  }
  async function stopRecording() {
    if (!recorder) return;
    const current = recorder;
    recorder = null;
    setControl(recordButton, "circle", "Saqlanmoqda...", "done");
    recordButton.disabled = true;
    try {
      await current.stop();
      recordingEnded("Yozuv saqlandi", "check");
    } catch (error) {
      recordingEnded("To'liq saqlanmadi", "triangle-alert");
      toast(error.message);
    }
  }
  async function toggleRecording() {
    if (recorder) return stopRecording();
    const grant = await api("POST", `/lessons/${roomName}/recording/start`);
    recorder = createRecorder(room, grant, scene, (error) => {
      recorder = null;
      recordingEnded("Yozuv to'xtadi", "triangle-alert");
      toast(error.message);
    });
    recordingSince = Date.now();
    recordingTime.textContent = "00:00";
    recordingChip.hidden = false;
    setControl(recordButton, "square", "Yozuvni to'xtatish", "recording");
  }

  // ---------- chiqish va tugatish ----------

  function cleanup() {
    clearInterval(clock);
    window.removeEventListener("resize", layout);
    setLessonParam(null);
  }
  const goHome = () => act(() => homeView())();

  async function close(message) {
    if (closing) return;
    closing = true;
    await stopRecording();
    await room.disconnect();
    cleanup();
    if (message) toast(message);
    await goHome();
  }
  async function endLesson() {
    const confirmed = await confirmDialog("Dars tugatilsinmi?",
      "Barcha ishtirokchilar darsdan chiqariladi. Yozuv saqlanadi.", "Darsni tugatish", true);
    if (!confirmed) return;
    // avval oxirgi bo'lak yuklanadi, keyin dars yopiladi — aks holda yozuv oxiri yo'qoladi
    await stopRecording();
    // avval o'zi chiqadi: aks holda server xonani yopganda aloqa "uzilgan" bo'lib ko'rinadi
    endedByMe = true;
    closing = true;
    await room.disconnect();
    cleanup();
    try {
      await api("POST", `/lessons/${roomName}/end`);
    } finally {
      await goHome();
    }
  }

  room
    .on(LK.RoomEvent.TrackSubscribed, (track, publication, participant) => {
      attach(track, participant);
      if (track.kind === LK.Track.Kind.Audio) recorder?.addAudio(track.mediaStreamTrack);
      else showMuted(publication, participant); // kamerasi o'chiq holda kirgan ishtirokchi
    })
    .on(LK.RoomEvent.TrackUnsubscribed, (track, _publication, participant) => detach(track, participant))
    .on(LK.RoomEvent.TrackMuted, showMuted)
    .on(LK.RoomEvent.TrackUnmuted, showMuted)
    .on(LK.RoomEvent.TrackPublished, (_publication, participant) => updateTile(participant))
    .on(LK.RoomEvent.TrackUnpublished, (_publication, participant) => updateTile(participant))
    .on(LK.RoomEvent.ParticipantConnected, (participant) => {
      tileFor(participant);
      updateTile(participant);
    })
    .on(LK.RoomEvent.ParticipantDisconnected, (participant) => {
      tiles.get(participant.identity)?.remove();
      tiles.delete(participant.identity);
      layout();
    })
    .on(LK.RoomEvent.ActiveSpeakersChanged, (speakers) => {
      const speaking = new Set(speakers.map((participant) => participant.identity));
      for (const [identity, tile] of tiles) tile.classList.toggle("speaking", speaking.has(identity));
    })
    .on(LK.RoomEvent.LocalTrackPublished, (publication) => {
      const track = publication.track;
      if (track.kind === LK.Track.Kind.Video) attach(track, local);
      else recorder?.addAudio(track.mediaStreamTrack);
      refresh();
    })
    .on(LK.RoomEvent.LocalTrackUnpublished, (publication) => {
      if (publication.track) detach(publication.track, local);
      refresh();
    })
    .on(LK.RoomEvent.AudioPlaybackStatusChanged, () => (audioButton.hidden = room.canPlaybackAudio))
    .on(LK.RoomEvent.Disconnected, () => close(endedByMe ? "" : "Dars tugadi yoki aloqa uzildi"));

  const connecting = h("div", { class: "room-connecting" }, h("span", { class: "spinner" }), "Darsga ulanmoqda...");
  render(
    h("div", { class: "room-page" },
      h("div", { class: "room-top" },
        h("div", { class: "room-title" }, info.group_name),
        h("span", { class: "chip live" }, h("span", { class: "dot" }), elapsed),
        h("span", { class: "chip" }, icon("users"), peopleCount),
        h("span", { class: "spacer" }),
        recordingChip),
      view,
      audioButton,
      h("div", { class: "controls" },
        micButton, cameraButton,
        // telefon brauzerlari ekran ulashishni qo'llamaydi
        navigator.mediaDevices?.getDisplayMedia && screenButton,
        info.is_teacher && recordButton,
        h("span", { class: "ctl-divider" }),
        leaveButton,
        info.is_teacher && endButton),
      connecting,
    ),
  );
  refresh();
  window.addEventListener("resize", layout);

  try {
    await room.connect(info.livekit_url, info.token);
  } catch (error) {
    closing = true;
    cleanup();
    await goHome();
    throw new Error(`Darsga ulanib bo'lmadi: ${error.message}`);
  }
  connecting.remove();
  tileFor(local);
  room.remoteParticipants.forEach((participant) => {
    tileFor(participant);
    updateTile(participant);
  });
  for (const enable of [() => local.setMicrophoneEnabled(true), () => local.setCameraEnabled(true)]) {
    try {
      await enable();
    } catch (error) {
      // ruxsat berilmagan yoki qurilma yo'q — darsni tomosha qilish baribir mumkin
      toast(`Kamera yoki mikrofon yoqilmadi: ${error.message}`);
    }
  }
  refresh();
}
