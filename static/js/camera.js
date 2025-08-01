(async () => {
  const preview        = document.getElementById("preview");
  const recordBtn      = document.getElementById("record-video-btn");
  const recordedVideo  = document.getElementById("recorded-video");
  const photoBtn       = document.getElementById("take-photo-btn");
  const canvas         = document.getElementById("photo-canvas");
  const uploadBtn      = document.getElementById("upload-btn");

  const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
  preview.srcObject = stream;

  let recordedBlob = null;
  let photoBlob    = null;
  let recordMime   = "video/webm";

  // 動画録画
  recordBtn.onclick = () => {
    let options = { mimeType: "video/mp4" };
    if (!MediaRecorder.isTypeSupported(options.mimeType)) {
      options = { mimeType: "video/webm" };
    }
    recordMime = options.mimeType;

    const recorder = new MediaRecorder(stream, options);
    const chunks   = [];
    recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstop = () => {
      recordedBlob = new Blob(chunks, { type: recordMime });
      recordedVideo.src = URL.createObjectURL(recordedBlob);
    };
    recorder.start();
    setTimeout(() => recorder.stop(), 8000);
  };

  // 静止画取得（スマホ対応版）
  photoBtn.onclick = () => {
    const ctx = canvas.getContext("2d");
    canvas.width = preview.videoWidth || 640;
    canvas.height = preview.videoHeight || 480;
    ctx.drawImage(preview, 0, 0, canvas.width, canvas.height);

    canvas.toBlob(b => { photoBlob = b; console.log("📸 写真撮影OK"); }, "image/png");
  };

  // 保存＆アップロード
  uploadBtn.onclick = async () => {
    let uploaded = false;

    if (photoBlob) {
      const formImg = new FormData();
      formImg.append("media_type", "image");
      formImg.append("file", photoBlob, "photo.png");
      await fetch("/upload_media", { method: "POST", body: formImg });
      uploaded = true;
    }
    if (recordedBlob) {
      const ext = recordMime === "video/mp4" ? "mp4" : "webm";
      const formVid = new FormData();
      formVid.append("media_type", "video");
      formVid.append("file", recordedBlob, `movie.${ext}`);
      await fetch("/upload_media", { method: "POST", body: formVid });
      uploaded = true;
    }

    if (uploaded) {
      window.location.href = "/daily_report";
    } else {
      alert("保存する写真または動画がありません。");
    }
  };
})();
