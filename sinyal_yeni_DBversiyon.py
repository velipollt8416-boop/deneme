# sinyal_yeni.py

import os
import psycopg2
import requests
from flask import Flask, request, jsonify
from datetime import datetime
from dotenv import load_dotenv

# .env dosyasındaki değişkenleri yükle
load_dotenv()

# --- VERİTABANI AYARLARI (Ortam Değişkenlerinden Oku) ---
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
# -------------------------------------------------------------

# --- TELEGRAM AYARLARI (Ortam Değişkenlerinden Oku) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
# os.getenv string döndürdüğü için integer'a çeviriyoruz
HISSELER_CHAT_ID = int(os.getenv("HISSELER_CHAT_ID"))
ENDEKS_CHAT_ID = int(os.getenv("ENDEKS_CHAT_ID"))
# -------------------------------------------------------------

ENDEKS_SEMBOLLERI = [
    "XBANK", "XELKT", "XGIDA", "XGMYO", "XHARZ", "XHOLD",
    "XILTM", "XKMYA", "XMADN", "XMANA", "XSINS", "XU030", "XU100"
]
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

app = Flask(__name__)

def get_db_connection():
    return psycopg2.connect(
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT
    )

def setup_database():
    """Uygulama başlangıcında tabloları otomatik oluşturur."""
    print("Veritabanı tabloları kontrol ediliyor...")
    conn = get_db_connection()
    cur = conn.cursor()
    
    create_open_trades_table = """
    CREATE TABLE IF NOT EXISTS open_trades (
        id SERIAL PRIMARY KEY,
        ticker VARCHAR(25) NOT NULL UNIQUE,
        signal_type VARCHAR(10) NOT NULL,
        entry_price NUMERIC(20, 5) NOT NULL,
        entry_time TIMESTAMPTZ NOT NULL
    );
    """
    
    create_closed_trades_table = """
    CREATE TABLE IF NOT EXISTS closed_trades (
        id SERIAL PRIMARY KEY,
        ticker VARCHAR(25) NOT NULL,
        signal_type VARCHAR(10) NOT NULL,
        entry_price NUMERIC(20, 5) NOT NULL,
        entry_time TIMESTAMPTZ NOT NULL,
        exit_price NUMERIC(20, 5) NOT NULL,
        exit_time TIMESTAMPTZ NOT NULL,
        profit_percentage REAL
    );
    """
    
    try:
        cur.execute(create_open_trades_table)
        cur.execute(create_closed_trades_table)
        conn.commit()
        print("Veritabanı tabloları hazır.")
    except Exception as e:
        print(f"!! VERİTABANI KURULUM HATASI: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

# --- Diğer Yardımcı Fonksiyonlar ---
def get_signal_emoji(signal_text):
    signal = str(signal_text).lower()
    if "buy" in signal: return "🟢"
    if "sell" in signal: return "🔴"
    return "⚪️"
def translate_signal(signal_text):
    signal = str(signal_text).lower()
    if "buy" in signal: return "ALIŞ"
    if "sell" in signal: return "SATIŞ"
    return signal.upper()
def format_timestamp(dt_object):
    if isinstance(dt_object, datetime):
        return dt_object.strftime("%d-%m-%Y %H:%M:%S")
    return str(dt_object)
# -----------------------------------

@app.route('/webhook', methods=['POST'])
def webhook():
    print("\n" + "="*20 + " YENİ WEBHOOK GELDİ " + "="*20)
    data = request.get_json()
    ticker = data["ticker"]
    signal_type = data["signal"].lower()
    price = float(data["price"])
    timestamp = datetime.fromisoformat(data["timestamp"].replace('Z', '+00:00'))
    print(f"Alınan Veri: {data}")
    
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT id, signal_type, entry_price, entry_time FROM open_trades WHERE ticker = %s", (ticker,))
        open_trade = cur.fetchone()

        if open_trade and open_trade[1] != signal_type:
            trade_id, open_signal_type, entry_price, entry_time = open_trade
            profit = ((price / float(entry_price)) - 1) * 100 if open_signal_type == 'buy' else ((float(entry_price) / price) - 1) * 100
            cur.execute(
                "INSERT INTO closed_trades (ticker, signal_type, entry_price, entry_time, exit_price, exit_time, profit_percentage) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (ticker, open_signal_type, entry_price, entry_time, price, timestamp, profit)
            )
            cur.execute("DELETE FROM open_trades WHERE id = %s", (trade_id,))
            print(f"POZİSYON KAPATILDI: {ticker} | Kâr: {profit:.2f}%")

        cur.execute(
            "INSERT INTO open_trades (ticker, signal_type, entry_price, entry_time) VALUES (%s, %s, %s, %s)",
            (ticker, signal_type, price, timestamp)
        )
        print(f"YENİ POZİSYON AÇILDI: {ticker} | Yön: {signal_type.upper()}")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"!! VERİTABANI HATASI: {e}")
        return jsonify({"status": "error", "message": "Database operation failed"}), 500
    finally:
        cur.close()
        conn.close()

    # --- Telegram Bildirimi ---
    hedef_chat_id = HISSELER_CHAT_ID
    if any(endeks in ticker.upper() for endeks in ENDEKS_SEMBOLLERI):
        hedef_chat_id = ENDEKS_CHAT_ID
    
    emoji = get_signal_emoji(signal_type)
    sinyal_turkce = translate_signal(signal_type)
    
    yeni_sinyal_mesaji = (
        f"{emoji} <b>{ticker} SİNYAL BİLDİRİMİ</b> {emoji}\n\n"
        f"<b>Sinyal:</b> {sinyal_turkce}\n"
        f"<b>Fiyat:</b> {price}\n"
        f"<b>Zaman:</b> {format_timestamp(timestamp)}"
    )

    payload = {'chat_id': hedef_chat_id, 'text': yeni_sinyal_mesaji, 'parse_mode': 'HTML'}
    
    try:
        requests.post(TELEGRAM_API_URL, json=payload).raise_for_status()
        print(f"✅ Sinyal bildirimi başarıyla '{hedef_chat_id}' ID'li gruba gönderildi.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Sinyal bildirimi gönderilirken hata oluştu: {e}")

    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    setup_database()
    app.run(host='0.0.0.0', port=80, debug=True)