// Teacher brauzerida darsni yozib oladi va bo'laklarni to'g'ridan-to'g'ri media backend'ga yuklaydi.
//
// Video: butun dars bitta canvas'ga chiziladi. Kimdir ekran ulashayotgan bo'lsa — ekran katta,
// ishtirokchilar yon ustunda; aks holda barcha ishtirokchilar to'r (grid) bo'lib joylashadi.
// Ovoz: teacher mikrofoni va barcha ishtirokchilar bitta trekka aralashtiriladi.

const REC_WIDTH = 1280;
const REC_HEIGHT = 720;
const REC_FPS = 15;
const REC_SIDEBAR = 256;
const REC_GAP = 2;
const CHUNK_MS = 5000;
const MAX_UPLOAD_ATTEMPTS = 6;

/**
 * getScene() hozirgi holatni qaytaradi:
 *   { screens: [{ video, name }], people: [{ video | null, name }] }
 * video — sahifadagi <video> element; kamerasi o'chiq ishtirokchida null.
 */
function createRecorder(room, grant, getScene, onFail) {
  const { Track } = window.LivekitClient;
  const canvas = Object.assign(document.createElement("canvas"), { width: REC_WIDTH, height: REC_HEIGHT });
  const painter = canvas.getContext("2d");
  const audioNodes = new Map(); // MediaStreamTrack.id -> MediaStreamAudioSourceNode
  const audioContext = new AudioContext();
  const mixed = audioContext.createMediaStreamDestination();

  const queue = [];
  let seq = 0;
  let pumping = null;
  let stopped = false;

  function drawCell({ video, name }, x, y, width, height) {
    x += REC_GAP;
    y += REC_GAP;
    width -= REC_GAP * 2;
    height -= REC_GAP * 2;
    painter.fillStyle = "#1c1c1e";
    painter.fillRect(x, y, width, height);
    if (video?.videoWidth) {
      const scale = Math.min(width / video.videoWidth, height / video.videoHeight);
      const drawWidth = video.videoWidth * scale;
      const drawHeight = video.videoHeight * scale;
      painter.drawImage(video, x + (width - drawWidth) / 2, y + (height - drawHeight) / 2, drawWidth, drawHeight);
    }
    if (!name) return;
    const fontSize = Math.max(12, Math.min(20, Math.round(height / 12)));
    painter.font = `${fontSize}px system-ui, sans-serif`;
    painter.textBaseline = "middle";
    const labelWidth = Math.min(painter.measureText(name).width + 12, width);
    const labelHeight = fontSize + 8;
    painter.fillStyle = "rgba(0, 0, 0, 0.6)";
    painter.fillRect(x, y + height - labelHeight, labelWidth, labelHeight);
    painter.fillStyle = "#fff";
    painter.fillText(name, x + 6, y + height - labelHeight / 2, width - 12);
  }

  function draw() {
    const { screens, people } = getScene();
    painter.fillStyle = "#000";
    painter.fillRect(0, 0, REC_WIDTH, REC_HEIGHT);
    if (screens.length) {
      const sidebar = people.length ? REC_SIDEBAR : 0;
      drawCell(screens[0], 0, 0, REC_WIDTH - sidebar, REC_HEIGHT);
      const cellHeight = Math.min((REC_SIDEBAR * 9) / 16, REC_HEIGHT / people.length);
      people.forEach((person, index) => drawCell(person, REC_WIDTH - sidebar, index * cellHeight, sidebar, cellHeight));
      return;
    }
    const columns = Math.ceil(Math.sqrt(people.length || 1));
    const rows = Math.ceil((people.length || 1) / columns);
    const cellWidth = REC_WIDTH / columns;
    const cellHeight = REC_HEIGHT / rows;
    people.forEach((person, index) =>
      drawCell(person, (index % columns) * cellWidth, Math.floor(index / columns) * cellHeight, cellWidth, cellHeight));
  }

  function addAudio(mediaTrack) {
    if (stopped || audioNodes.has(mediaTrack.id)) return;
    const node = audioContext.createMediaStreamSource(new MediaStream([mediaTrack]));
    node.connect(mixed);
    audioNodes.set(mediaTrack.id, node);
  }

  async function send(blob) {
    let retried = false;
    for (let attempt = 0; attempt < MAX_UPLOAD_ATTEMPTS; attempt++) {
      let response;
      try {
        response = await fetch(`${grant.upload_url}?seq=${seq}`, {
          method: "POST",
          headers: { Authorization: `Bearer ${grant.token}` },
          body: blob,
        });
      } catch {
        retried = true;
        await new Promise((resolve) => setTimeout(resolve, Math.min(1000 * 2 ** attempt, 15000)));
        continue;
      }
      if (response.ok) return;
      if (response.status === 409) {
        const expected = (await response.json()).detail.expected_seq;
        // javob yo'lda yo'qolgan, lekin server bo'lakni yozib bo'lgan
        if (retried && expected === seq + 1) return;
        throw new Error(seq === 0 ? "bu dars uchun yozuv allaqachon bor" : "yozuv bo'laklari tartibi buzildi");
      }
      throw new Error(`yozuvni yuklashda xato: ${response.status}`);
    }
    throw new Error("media serverga ulanib bo'lmadi, yozuv to'xtatildi");
  }

  function pump() {
    pumping ??= (async () => {
      try {
        while (queue.length) {
          await send(queue[0]);
          queue.shift();
          seq++;
        }
      } finally {
        pumping = null;
      }
    })();
    return pumping;
  }

  // Worker taymeri tab fonda bo'lganda ham sekinlashmaydi (oddiy setInterval sekinlashadi)
  const ticker = new Worker(URL.createObjectURL(
    new Blob([`setInterval(() => postMessage(0), ${Math.round(1000 / REC_FPS)})`], { type: "text/javascript" }),
  ));
  ticker.onmessage = draw;

  const mimeType = ["video/webm;codecs=vp8,opus", "video/webm"].find((type) => MediaRecorder.isTypeSupported(type));
  if (!mimeType) {
    ticker.terminate();
    audioContext.close();
    throw new Error("bu brauzer webm yozib olishni qo'llamaydi");
  }
  const stream = new MediaStream([
    ...canvas.captureStream(REC_FPS).getVideoTracks(),
    ...mixed.stream.getAudioTracks(),
  ]);
  const mediaRecorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 2_000_000 });
  mediaRecorder.ondataavailable = (event) => {
    if (!event.data.size) return;
    queue.push(event.data);
    pump().catch((error) => {
      queue.length = 0;
      stop();
      onFail(error);
    });
  };

  for (const source of [Track.Source.Microphone, Track.Source.ScreenShareAudio]) {
    const publication = room.localParticipant.getTrackPublication(source);
    if (publication?.track) addAudio(publication.track.mediaStreamTrack);
  }
  for (const participant of room.remoteParticipants.values()) {
    for (const publication of participant.audioTrackPublications.values()) {
      if (publication.track) addAudio(publication.track.mediaStreamTrack);
    }
  }
  draw();
  mediaRecorder.start(CHUNK_MS);

  /** Yozuvni to'xtatadi va oxirgi bo'lak yuklanib bo'lguncha kutadi. */
  async function stop() {
    if (!stopped) {
      stopped = true;
      if (mediaRecorder.state !== "inactive") {
        await new Promise((resolve) => {
          mediaRecorder.addEventListener("stop", resolve, { once: true });
          mediaRecorder.stop();
        });
      }
      ticker.terminate();
      audioContext.close();
    }
    if (queue.length) await pump();
  }

  return { addAudio, stop };
}
