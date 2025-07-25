import os
import glob
import logging
import tempfile
from io import BytesIO
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, request,
    jsonify, redirect, send_from_directory,
    url_for
)
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from google.cloud import texttospeech
import openai
from openai import OpenAI
import stripe

# ─── ログ設定 ─────────────────────────────────────
logging.basicConfig(level=logging.DEBUG)

# ─── Google 認証設定 ─────────────────────────────────
KEY_JSON_ENV = "GOOGLE_CREDENTIALS_JSON"
json_str = os.getenv(KEY_JSON_ENV) or ""
with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
    tmp.write(json_str.encode("utf-8"))
    tmp.flush()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name

# ─── Flask 初期化 ───────────────────────────────────
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)
limiter = Limiter(app, key_func=get_remote_address, default_limits=["10 per minute"])

# ─── API キー設定 ────────────────────────────────────
openai.api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai.api_key)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")  # 本番／テスト切り替えはここで行う

# ─── アップロード保存フォルダ準備 ─────────────────────────
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ─── キャッシュ無効化 ─────────────────────────────────
@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ─── 1. トップ画面 ────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

# ─── 2. 介護支援ボット画面（同じ index.html を表示）────────────
@app.route("/ja/", methods=["GET"])
def show_ja_index():
    return render_template("index.html")

# ─── 3. 本日の見守りレポート ───────────────────────────
@app.route("/ja/daily_report", methods=["GET"])
def daily_report():
    now = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")
    # 対話ログから日報テキストを生成
    files = sorted(glob.glob("logs/log_*.txt"))
    text_report = "ログがありません"
    if files:
        content = open(files[-1], encoding="utf-8").read()
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content":"以下の対話ログをもとに、本日の介護日報を日本語で短くまとめてください。"},
                {"role":"user","content":content}
            ]
        )
        text_report = resp.choices[0].message.content.strip()
    # 当日のメディア一覧
    all_media = os.listdir(UPLOAD_DIR)
    images = [f for f in all_media if f.startswith("image_")]
    videos = [f for f in all_media if f.startswith("video_")]
    return render_template(
        "daily_report.html",
        now=now,
        text_report=text_report,
        images=images,
        videos=videos
    )

# ─── 4. カメラテスト画面 ─────────────────────────────
@app.route("/camera-test/", methods=["GET"])
def camera_test():
    return render_template("camera_test.html")

# ─── 5. メディアアップロード受信 ───────────────────────────
@app.route("/upload_media", methods=["POST"])
def upload_media():
    media_type = request.form.get("media_type")
    file = request.files.get("file")
    if not media_type or not file:
        return jsonify({"error": "media_type or file missing"}), 400

    # 拡張子自動判断
    orig_name = file.filename
    _, ext = os.path.splitext(orig_name)
    if not ext:
        ext = ".webm" if media_type == "video" else ".png"

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{media_type}_{ts}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)

    try:
        file.save(path)
        logging.debug(f"Saved {media_type} to {path}")
        return jsonify({"status": "saved", "filename": filename}), 200
    except Exception as e:
        logging.exception("upload_media error")
        return jsonify({"error": str(e)}), 500

# ─── 6. アップロードファイル公開 ───────────────────────────
@app.route("/uploads/<path:filename>", methods=["GET"])
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)

# ─── 7. 既存の API 群 ─────────────────────────────────
@app.route("/ja/templates", methods=["GET"])
def get_templates():
    return jsonify([
        {"category":"体調","caregiver":["体調はいかがですか？","痛みはありますか？"],"caree":["元気です。","今日は少しだるいです。"]},
        {"category":"食事","caregiver":["お食事は何を召し上がりましたか？","美味しかったですか？"],"caree":["サンドイッチを食べました。","まだ食べていません。"]},
        {"category":"薬","caregiver":["お薬は飲みましたか？","飲み忘れはないですか？"],"caree":["飲みました。","まだです。"]},
        {"category":"睡眠","caregiver":["昨夜はよく眠れましたか？","何時にお休みになりましたか？"],"caree":["よく眠れました。","少し寝不足です。"]},
        {"category":"排便","caregiver":["お通じはいかがですか？","問題ありませんか？"],"caree":["問題ありません。","少し便秘気味です。"]}
    ])

@app.route("/ja/chat", methods=["POST"])
def chat_ja():
    data = request.get_json()
    resp = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role":"system","content":"You are a helpful assistant."}]
    )
    return jsonify({"response": resp.choices[0].message.content})

@app.route("/ja/explain", methods=["POST"])
def explain():
    data = request.get_json()
    term = data.get("term","")
    resp = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role":"system","content":"日本語で30文字以内で簡潔に専門用語を説明してください。"},
            {"role":"user","content":f"{term}とは？"}
        ]
    )
    return jsonify({"explanation": resp.choices[0].message.content.strip()})

@app.route("/ja/translate", methods=["POST"])
def translate():
    data = request.get_json()
    text = data.get("text","")
    direction = data.get("direction","ja-en")
    prompt = (
        f"以下の日本語を英語に翻訳してください：\n\n{text}"
        if direction=="ja-en" else
        f"Translate the following English into Japanese:\n\n{text}"
    )
    resp = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role":"user","content":prompt}]
    )
    return jsonify({"translated": resp.choices[0].message.content.strip()})

@app.route("/ja/save_log", methods=["POST"])
def save_log():
    data = request.get_json()
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("log_%Y%m%d_%H%M%S.txt")
    path = os.path.join(log_dir, ts)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"ユーザー名: {data.get('username','')}\n")
        f.write(f"日時: {data.get('timestamp','')}\n")
        f.write(f"入力: {data.get('input','')}\n")
        f.write(f"返答: {data.get('response','')}\n")
    return jsonify({"status":"success"})

@app.route("/chat", methods=["POST"])
@limiter.limit("3 per 10 seconds")
def chat_tts():
    data = request.get_json(force=True)
    text = data.get("text","").strip()
    if len(text) > 100:
        return jsonify({"reply":"メッセージは100文字以内でお願いします。"}), 400

    gpt = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role":"system","content":"あなたは親切な日本語のアシスタントです。"},
            {"role":"user","content":text}
        ]
    )
    reply = gpt.choices[0].message.content.strip()
    if len(reply) > 200:
        reply = reply[:197] + "..."

    tts = texttospeech.TextToSpeechClient()
    audio = tts.synthesize_speech(
        input=texttospeech.SynthesisInput(text=reply),
        voice=texttospeech.VoiceSelectionParams(
            language_code="ja-JP", ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
        ),
        audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
    )
    os.makedirs("static", exist_ok=True)
    with open("static/output.mp3", "wb") as f:
        f.write(audio.audio_content)

    with open("chatlog.txt", "a", encoding="utf-8") as logf:
        logf.write(f"ユーザー: {text}\nみまくん: {reply}\n---\n")

    return jsonify({"reply": reply})

@app.route("/logs")
def logs():
    try:
        text = open("chatlog.txt", "r", encoding="utf-8").read()
        return f"<pre>{text}</pre><a href='{url_for('download_logs')}'>ログダウンロード</a>"
    except FileNotFoundError:
        return "ログが存在しません。"

@app.route("/download-logs")
def download_logs():
    return (
        open("chatlog.txt","rb").read(), 200,
        {
            "Content-Type":"application/octet-stream",
            "Content-Disposition":'attachment; filename="chatlog.txt"'
        }
    )

# ─── 8. Stripe Invoice 発行 ───────────────────────────
@app.route("/create_invoice", methods=["POST"])
def create_invoice():
    # 環境変数で STRIPE_SECRET_KEY が切り替わっているものとする
    # 1) 顧客作成
    customer = stripe.Customer.create(
        email="test@example.com",
        name="テスト顧客"
    )
    # 2) 請求アイテム作成
    stripe.InvoiceItem.create(
        customer=customer.id,
        amount=1300,
        currency="jpy",
        description="デモ請求"
    )
    # 3) Invoice 作成（未払い状態）
    invoice = stripe.Invoice.create(
        customer=customer.id,
        auto_advance=False,               # 即時最終化しない
        collection_method="send_invoice"  # 請求書モードにする
    )
    # 4) サーバー側で明示的に最終化
    invoice = stripe.Invoice.finalize_invoice(invoice.id)
    # 5) 請求書ページへリダイレクト
    return redirect(invoice.hosted_invoice_url)

# ─── アプリ起動 ─────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
