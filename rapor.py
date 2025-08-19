# rapor.py

import os
import csv
import psycopg2
import yfinance as yf
import numpy as np
from tabulate import tabulate
from datetime import datetime  # <-- EKLENEN VE HATAYI DÜZELTEN SATIR
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

def get_db_connection():
    return psycopg2.connect(
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT
    )

def check_open_positions():
    """Açık pozisyonları çeker, anlık fiyatları hesaplar, terminalde gösterir ve CSV olarak kaydeder."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT ticker, signal_type, entry_price FROM open_trades")
        open_trades = cur.fetchall()

        if not open_trades:
            print("Takip edilen açık pozisyon bulunmuyor.")
            return

        report_data = []
        headers = ["Ticker", "Yön", "Giriş Fiyatı", "Anlık Fiyat", "Anlık Kâr/Zarar (%)"]
        
        tickers = [f"{trade[0]}.IS" for trade in open_trades]
        
        # yfinance ile anlık fiyatları çek
        try:
            data = yf.download(tickers=tickers, period='1d', interval='1m', progress=False)
            
            # Veri boş gelirse period değiştirip tekrar dene
            if data.empty or data['Close'].empty:
                data = yf.download(tickers=tickers, period='1d', interval='5m', progress=False)
                
            # Hala boşsa 1 günlük veri dene
            if data.empty or data['Close'].empty:
                data = yf.download(tickers=tickers, period='5d', interval='1d', progress=False)
                
        except Exception as e:
            print(f"Veri indirme hatası: {e}")
            data = None
        
        for trade in open_trades:
            ticker, signal_type, entry_price = trade
            current_price = None
            profit_str = "N/A"
            
            try:
                # Entry price kontrolü
                entry_price_float = float(entry_price)
                if entry_price_float <= 0:
                    report_data.append([ticker, signal_type.upper(), f"{entry_price}", "Geçersiz Giriş Fiyatı", "N/A"])
                    continue
                
                # Veri kontrolü
                if data is None or data.empty:
                    report_data.append([ticker, signal_type.upper(), f"{entry_price}", "Veri Alınamadı", "N/A"])
                    continue
                
                # Anlık fiyat çekme
                if len(tickers) == 1:
                    if 'Close' in data.columns and not data['Close'].empty:
                        current_price = data['Close'].iloc[-1]
                else:
                    ticker_column = f"{ticker}.IS"
                    if 'Close' in data.columns and ticker_column in data['Close'].columns:
                        close_series = data['Close'][ticker_column]
                        if not close_series.empty:
                            current_price = close_series.iloc[-1]
                
                # Eğer toplu indirmede bulunamadıysa, tek tek dene
                if current_price is None or np.isnan(current_price):
                    try:
                        single_data = yf.download(f"{ticker}.IS", period='1d', interval='1m', progress=False)
                        if not single_data.empty and 'Close' in single_data.columns:
                            current_price = single_data['Close'].iloc[-1]
                    except Exception:
                        pass  # Sessizce devam et
                
                # NaN kontrolü
                if current_price is None or np.isnan(current_price) or current_price <= 0:
                    report_data.append([ticker, signal_type.upper(), f"{entry_price}", "Geçersiz Fiyat", "N/A"])
                    continue
                
                # Kâr/zarar hesaplama
                if signal_type == 'buy':
                    profit = ((current_price / entry_price_float) - 1) * 100
                else: # sell
                    profit = ((entry_price_float / current_price) - 1) * 100
                
                # NaN kontrolü kâr/zarar için
                if np.isnan(profit):
                    profit_str = "Hesaplanamadı"
                else:
                    profit_str = f"{profit:+.2f}%"
                
                report_data.append([ticker, signal_type.upper(), f"{entry_price}", f"{current_price:.4f}", profit_str])
            
            except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
                # Sessizce hata durumunu işle
                report_data.append([ticker, signal_type.upper(), f"{entry_price}", "Hata", "N/A"])

        print("\n--- AÇIK POZİSYONLAR ANLIK DURUM RAPORU ---")
        report_time = datetime.now()
        print(f"Rapor Zamanı: {report_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(tabulate(report_data, headers=headers, tablefmt="grid"))

        csv_filename = f"open_positions_report_{report_time.strftime('%Y%m%d_%H%M%S')}.csv"
        try:
            with open(csv_filename, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(headers)
                writer.writerows(report_data)
            print(f"Rapor CSV olarak kaydedildi: {csv_filename}")
        except Exception as e:
            print(f"CSV yazma hatası: {e}")

    except Exception as e:
        print(f"Rapor oluşturulurken bir hata oluştu: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    check_open_positions()
