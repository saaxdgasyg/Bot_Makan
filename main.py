"""
Bot Telegram: Asisten Nutrisi Sehat & Murah ala Indonesia
=========================================================
Fitur:
  - Menu Navigasi berbasis Tombol (Reply Keyboard / Inline Keyboard)
  - Registrasi alergi TANPA slash & dengan Tombol (Segregasi User ID Ketat)
  - Fitur Hitung BMI (Berat & Tinggi Badan disimpan di Database per User)
  - 🧠 Chat Memory — AI mengingat percakapan sebelumnya via database
  - 😊 Mood Tracker — Lapor mood harian, AI personalisasi rekomendasi
  - 💧 Pengingat Minum Air — Reminder hidrasi otomatis
  - Konsultasi kesehatan personal berbasis data fisik & alergi terkini
  - Pengingat otomatis + Fitur Saklar Reminder Harian
  - Database PostgreSQL (dengan auto-fallback ke SQLite untuk lokal)
  - Fitur: Profil, Riwayat, Bantuan, Reset Data, Kalkulator BMI
"""

import logging
import sqlite3
import os
import re
import traceback as tb_module
from datetime import datetime
from pathlib import Path
import urllib.parse as urlparse

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from google import genai
from google.genai import types

# Coba import psycopg2 untuk PostgreSQL
try:
    import psycopg2
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Konfigurasi Token (dari Environment Variables)
# ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

if not TELEGRAM_TOKEN:
    raise RuntimeError("Environment variable TELEGRAM_TOKEN belum diset!")
if not GEMINI_API_KEY:
    raise RuntimeError("Environment variable GEMINI_API_KEY belum diset!")

# ──────────────────────────────────────────────
# Inisialisasi Gemini Client
# ──────────────────────────────────────────────
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# ──────────────────────────────────────────────
# Regex untuk deteksi
# ──────────────────────────────────────────────
POLA_ALERGI = re.compile(r"^(?:alergi|alrgi|allergi|alerji|alergy|allergy)\s+(.+)", re.IGNORECASE)
POLA_BMI = re.compile(r"^(?:bmi|tb|bb|berat|tinggi)\s+(\d+)\s+(\d+)", re.IGNORECASE)

# ──────────────────────────────────────────────
# Database Helper (PostgreSQL / SQLite Connection)
# ──────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "bot_data.db"
USE_POSTGRES = HAS_POSTGRES and DATABASE_URL is not None

# Variabel global untuk merekam status inisialisasi database
STATUS_DATABASE = "PostgreSQL terhubung sukses! ✅"
DB_ERROR_MESSAGE = ""


def dapatkan_koneksi():
    """Membuka koneksi ke PostgreSQL dengan fallback otomatis ke SQLite jika gagal."""
    global USE_POSTGRES, STATUS_DATABASE, DB_ERROR_MESSAGE
    if USE_POSTGRES:
        try:
            url = urlparse.urlparse(DATABASE_URL)
            dbname = url.path[1:]
            user = url.username
            password = url.password
            host = url.hostname
            port = url.port

            conn = psycopg2.connect(
                dbname=dbname,
                user=user,
                password=password,
                host=host,
                port=port,
                connect_timeout=5,
            )
            STATUS_DATABASE = "PostgreSQL terhubung sukses! ✅"
            return conn
        except Exception as e:
            DB_ERROR_MESSAGE = str(e)
            logger.error("Gagal menyambung ke PostgreSQL, beralih otomatis ke SQLite! Error: %s", DB_ERROR_MESSAGE)
            STATUS_DATABASE = f"PostgreSQL gagal terhubung (Beralih ke SQLite lokal). ⚠️\nDetail Error: `{DB_ERROR_MESSAGE}`"
            USE_POSTGRES = False
            return sqlite3.connect(DB_PATH)
    else:
        STATUS_DATABASE = "Menggunakan database SQLite lokal. 📂"
        return sqlite3.connect(DB_PATH)


def dapatkan_placeholder():
    return "%s" if USE_POSTGRES else "?"


def init_db() -> None:
    """Inisialisasi semua tabel: users, riwayat, chat_history, mood_log."""
    try:
        conn = dapatkan_koneksi()
        cursor = conn.cursor()

        if USE_POSTGRES:
            logger.info("Menggunakan database PostgreSQL.")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id         BIGINT PRIMARY KEY,
                    nama            VARCHAR(255) DEFAULT '',
                    alergi          TEXT         DEFAULT 'Tidak ada',
                    menu            VARCHAR(255) DEFAULT '',
                    reminder        INTEGER      DEFAULT 0,
                    bergabung       VARCHAR(50)  DEFAULT '',
                    tinggi_badan    INTEGER      DEFAULT 0,
                    berat_badan     INTEGER      DEFAULT 0,
                    bmi             REAL         DEFAULT 0.0,
                    reminder_harian INTEGER      DEFAULT 1
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS riwayat (
                    id          SERIAL PRIMARY KEY,
                    user_id     BIGINT NOT NULL,
                    keluhan     TEXT NOT NULL,
                    menu        VARCHAR(255) NOT NULL,
                    jawaban_ai  TEXT NOT NULL,
                    waktu       VARCHAR(50) NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id          SERIAL PRIMARY KEY,
                    user_id     BIGINT NOT NULL,
                    role        VARCHAR(20) NOT NULL,
                    pesan       TEXT NOT NULL,
                    waktu       VARCHAR(50) NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mood_log (
                    id          SERIAL PRIMARY KEY,
                    user_id     BIGINT NOT NULL,
                    mood        VARCHAR(30) NOT NULL,
                    catatan     TEXT DEFAULT '',
                    waktu       VARCHAR(50) NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
        else:
            logger.info("Menggunakan database SQLite.")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id         INTEGER PRIMARY KEY,
                    nama            TEXT    DEFAULT '',
                    alergi          TEXT    DEFAULT 'Tidak ada',
                    menu            TEXT    DEFAULT '',
                    reminder        INTEGER DEFAULT 0,
                    bergabung       TEXT    DEFAULT '',
                    tinggi_badan    INTEGER DEFAULT 0,
                    berat_badan     INTEGER DEFAULT 0,
                    bmi             REAL    DEFAULT 0.0,
                    reminder_harian INTEGER DEFAULT 1
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS riwayat (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    keluhan     TEXT    NOT NULL,
                    menu        TEXT    NOT NULL,
                    jawaban_ai  TEXT    NOT NULL,
                    waktu       TEXT    NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    role        TEXT    NOT NULL,
                    pesan       TEXT    NOT NULL,
                    waktu       TEXT    NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mood_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    mood        TEXT    NOT NULL,
                    catatan     TEXT    DEFAULT '',
                    waktu       TEXT    NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

        # Migrasi kolom — tambahkan kolom baru jika belum ada (PostgreSQL & SQLite)
        # Commit dulu CREATE TABLE di atas agar tidak ikut ke-rollback jika ALTER TABLE gagal
        conn.commit()
        
        kolom_baru = [
            ("tinggi_badan", "INTEGER DEFAULT 0"),
            ("berat_badan", "INTEGER DEFAULT 0"),
            ("bmi", "REAL DEFAULT 0.0"),
            ("reminder_harian", "INTEGER DEFAULT 1"),
        ]
        for kolom, tipe in kolom_baru:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {kolom} {tipe}")
                conn.commit()
                logger.info("Kolom '%s' berhasil ditambahkan ke tabel users.", kolom)
            except Exception:
                conn.rollback()
                pass  # Kolom sudah ada, abaikan

        conn.close()
        logger.info("Database siap digunakan.")
    except Exception as e:
        global STATUS_DATABASE
        STATUS_DATABASE = f"Kritis: Inisialisasi DB gagal! 🚨\nError: `{str(e)}`"
        logger.error(STATUS_DATABASE)


# ──────────────────────────────────────────────
# Fungsi CRUD Database
# ──────────────────────────────────────────────
def get_or_create_user(user_id: int, nama: str = "") -> dict:
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()

    cursor.execute(
        f"SELECT user_id, nama, alergi, menu, reminder, bergabung, tinggi_badan, berat_badan, bmi, reminder_harian FROM users WHERE user_id = {p}",
        (user_id,),
    )
    row = cursor.fetchone()
    if row is None:
        waktu_gabung = datetime.now().strftime("%Y-%m-%d %H:%M")
        cursor.execute(
            f"INSERT INTO users (user_id, nama, bergabung, tinggi_badan, berat_badan, bmi, reminder_harian) VALUES ({p}, {p}, {p}, 0, 0, 0.0, 1)",
            (user_id, nama, waktu_gabung),
        )
        conn.commit()
        row = (user_id, nama, "Tidak ada", "", 0, waktu_gabung, 0, 0, 0.0, 1)
    elif nama and row[1] != nama:
        cursor.execute(f"UPDATE users SET nama = {p} WHERE user_id = {p}", (nama, user_id))
        conn.commit()
        row = (row[0], nama, row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9])
    conn.close()

    return {
        "user_id": row[0],
        "nama": row[1],
        "alergi": row[2],
        "menu": row[3],
        "reminder": row[4],
        "bergabung": row[5],
        "tinggi_badan": row[6],
        "berat_badan": row[7],
        "bmi": row[8],
        "reminder_harian": row[9],
    }


def update_alergi(user_id: int, alergi: str) -> None:
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    cursor.execute(f"UPDATE users SET alergi = {p} WHERE user_id = {p}", (alergi, user_id))
    conn.commit()
    conn.close()


def update_menu(user_id: int, menu: str) -> None:
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    cursor.execute(f"UPDATE users SET menu = {p}, reminder = 1 WHERE user_id = {p}", (menu, user_id))
    conn.commit()
    conn.close()


def update_bmi_data(user_id: int, tinggi: int, berat: int, bmi: float) -> None:
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    cursor.execute(
        f"UPDATE users SET tinggi_badan = {p}, berat_badan = {p}, bmi = {p} WHERE user_id = {p}",
        (tinggi, berat, bmi, user_id),
    )
    conn.commit()
    conn.close()


def update_reminder_harian_status(user_id: int, status: int) -> None:
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    cursor.execute(f"UPDATE users SET reminder_harian = {p} WHERE user_id = {p}", (status, user_id))
    conn.commit()
    conn.close()


def simpan_riwayat(user_id: int, keluhan: str, menu: str, jawaban_ai: str) -> None:
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        f"INSERT INTO riwayat (user_id, keluhan, menu, jawaban_ai, waktu) VALUES ({p}, {p}, {p}, {p}, {p})",
        (user_id, keluhan, menu, jawaban_ai, waktu),
    )
    conn.commit()
    conn.close()


def ambil_riwayat(user_id: int, limit: int = 10) -> list:
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    cursor.execute(
        f"SELECT keluhan, menu, waktu FROM riwayat WHERE user_id = {p} ORDER BY id DESC LIMIT {p}",
        (user_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def hitung_total_konsultasi(user_id: int) -> int:
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    cursor.execute(f"SELECT COUNT(*) FROM riwayat WHERE user_id = {p}", (user_id,))
    total = cursor.fetchone()[0]
    conn.close()
    return total


def reset_user_data(user_id: int) -> None:
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    cursor.execute(f"DELETE FROM riwayat WHERE user_id = {p}", (user_id,))
    cursor.execute(f"DELETE FROM chat_history WHERE user_id = {p}", (user_id,))
    cursor.execute(f"DELETE FROM mood_log WHERE user_id = {p}", (user_id,))
    cursor.execute(
        f"UPDATE users SET alergi = 'Tidak ada', menu = '', reminder = 0, tinggi_badan = 0, berat_badan = 0, bmi = 0.0, reminder_harian = 1 WHERE user_id = {p}",
        (user_id,),
    )
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# 🧠 Chat Memory — Simpan & Ambil Riwayat Chat
# ──────────────────────────────────────────────
def simpan_chat(user_id: int, role: str, pesan: str) -> None:
    """Simpan satu baris chat ke database (role = 'user' atau 'assistant')."""
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        f"INSERT INTO chat_history (user_id, role, pesan, waktu) VALUES ({p}, {p}, {p}, {p})",
        (user_id, role, pesan, waktu),
    )
    conn.commit()
    conn.close()


def ambil_chat_history(user_id: int, limit: int = 10) -> list:
    """Ambil N chat terakhir (dari yang paling lama ke terbaru) untuk konteks AI."""
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    cursor.execute(
        f"SELECT role, pesan, waktu FROM chat_history WHERE user_id = {p} ORDER BY id DESC LIMIT {p}",
        (user_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return list(reversed(rows))  # Balik agar urutan kronologis (lama → baru)


def hapus_chat_history(user_id: int) -> None:
    """Hapus seluruh riwayat chat user — AI akan 'lupa' percakapan lama."""
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    cursor.execute(f"DELETE FROM chat_history WHERE user_id = {p}", (user_id,))
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# 😊 Mood Tracker — Simpan & Ambil Mood Harian
# ──────────────────────────────────────────────
def simpan_mood(user_id: int, mood: str, catatan: str = "") -> None:
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        f"INSERT INTO mood_log (user_id, mood, catatan, waktu) VALUES ({p}, {p}, {p}, {p})",
        (user_id, mood, catatan, waktu),
    )
    conn.commit()
    conn.close()


def ambil_mood_terakhir(user_id: int) -> dict | None:
    conn = dapatkan_koneksi()
    cursor = conn.cursor()
    p = dapatkan_placeholder()
    cursor.execute(
        f"SELECT mood, catatan, waktu FROM mood_log WHERE user_id = {p} ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"mood": row[0], "catatan": row[1], "waktu": row[2]}
    return None


# ──────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────
def bersihkan_alergi(teks: str) -> str:
    teks = teks.lower().strip()
    items = [item.strip() for item in teks.split(",") if item.strip()]
    return ", ".join(items)


def ekstrak_nama_menu(respons: str) -> str:
    match = re.search(r"(?:Menu|Rekomendasi Menu)\s*:\s*([^\n]+)", respons, re.IGNORECASE)
    if match:
        return match.group(1).replace("*", "").strip()
    for line in respons.split("\n"):
        if any(keyword in line.lower() for keyword in ["tumis", "nasi", "sup", "bubur", "sayur", "rebus", "ikan", "ayam", "tahu", "tempe"]):
            return line.replace("*", "").strip()
    return "Menu Sehat & Nutrisi Lokal"


def dapatkan_keyboard_utama() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🥗 Kelola Alergi"), KeyboardButton("👤 Profil Saya")],
        [KeyboardButton("⚖️ Hitung BMI"), KeyboardButton("📋 Riwayat Menu")],
        [KeyboardButton("😊 Mood Hari Ini"), KeyboardButton("💧 Pengingat Minum")],
        [KeyboardButton("📖 Bantuan & Tips")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, input_field_placeholder="Ketik keluhan kesehatan atau pilih menu...")


def dapatkan_kategori_bmi(bmi: float) -> str:
    if bmi <= 0:
        return "Belum diisi"
    elif bmi < 18.5:
        return "Kurus (Kurang Berat Badan) ⚠️"
    elif bmi < 24.9:
        return "Normal (Ideal) ✅"
    elif bmi < 29.9:
        return "Kelebihan Berat Badan ⚠️"
    else:
        return "Obesitas 🚨"


# ──────────────────────────────────────────────
# Bangun System Instruction dinamis untuk Gemini
# ──────────────────────────────────────────────
def bangun_system_instruction(user_data: dict, mood_data: dict | None = None) -> str:
    alergi = user_data["alergi"]
    tb = user_data["tinggi_badan"]
    bb = user_data["berat_badan"]
    bmi = user_data["bmi"]
    kategori = dapatkan_kategori_bmi(bmi)

    info_fisik = f"Tinggi Badan: {tb} cm, Berat Badan: {bb} kg, BMI: {bmi:.1f} ({kategori})." if tb > 0 else "Data fisik belum diisi pengguna."

    # Info mood
    info_mood = ""
    if mood_data:
        info_mood = (
            f"\n## MOOD TERAKHIR PENGGUNA:\n"
            f"- Mood: {mood_data['mood']} (dicatat pada {mood_data['waktu']})\n"
        )
        if mood_data.get("catatan"):
            info_mood += f"- Catatan: {mood_data['catatan']}\n"
        info_mood += "Pertimbangkan mood pengguna saat memberikan rekomendasi. Jika mood buruk, berikan makanan comfort food yang sehat dan kata-kata penyemangat yang lebih empati.\n"

    instruksi = (
        "Kamu adalah seorang Dokter, Spesialis Nutrisi, dan Ahli Gizi Ramah Indonesia yang sangat berpengalaman.\n"
        "Tugasmu adalah memberikan analisis keluhan kesehatan pengguna dan memberikan rekomendasi menu sehat "
        "lokal Indonesia beserta tips gaya hidup/pola tidur medis yang sangat lengkap dan solutif. Jangan memotong penjelasan penting!\n\n"
        "## DATA FISIK PENGGUNA SAAT INI:\n"
        f"- {info_fisik}\n"
        "Gunakan data fisik di atas untuk menganalisis kebutuhan kalori, porsi makan, atau anjuran nutrisi mereka secara personal.\n"
        f"{info_mood}\n"
        "## ATURAN MUTLAK YANG WAJIB DIPATUHI:\n\n"
        "### 1. RENCANA MENU HARUS MURAH & LOKAL INDONESIA\n"
        "- Gunakan bahan makanan lokal yang terjangkau di pasar tradisional (tahu, tempe, telur, bayam, kangkung, daun kelor, hati ayam, pisang, pepaya, ubi, singkong, kacang hijau, lele, ikan teri, dll).\n"
        "- DILARANG keras menyarankan bahan impor mahal seperti salmon, tuna segar premium, blueberry, quinoa, oatmeal, asparagus, chia seed, dll.\n"
        "- Estimasi total harga bahan harus ramah kantong (Rp 5.000 - Rp 25.000).\n\n"
        "### 2. FILTER ALERGI KETAT\n"
        f"- Pengguna memiliki ALERGI terhadap: **{alergi}**.\n"
    )

    if alergi.lower() != "tidak ada":
        instruksi += (
            "- DILARANG KERAS merekomendasikan menu yang mengandung bahan-bahan tersebut beserta seluruh turunannya.\n"
        )

    instruksi += (
        "\n### 3. PERCAKAPAN BERKELANJUTAN (CHAT MEMORY)\n"
        "- Kamu memiliki akses ke riwayat percakapan sebelumnya dengan pengguna ini.\n"
        "- Gunakan konteks percakapan sebelumnya untuk memberikan jawaban yang lebih personal dan koheren.\n"
        "- Jika pengguna menyebut sesuatu dari percakapan sebelumnya, kamu HARUS mengingatnya dan merujuknya.\n"
        "- Jangan ulangi menu yang sama persis, berikan variasi!\n\n"
        "### 4. FORMAT RESPON (LENGKAP & DETAIL)\n"
        "Jawab dengan struktur rapi berikut:\n\n"
        "🩺 *ANALISIS MEDIS & KELUHAN*\n"
        "[Berikan penjelasan medis singkat mengenai keluhan mereka]\n\n"
        "🍽️ *REKOMENDASI MENU SEHAT*\n"
        "Menu: [Nama Masakan Indonesia yang Spesifik]\n"
        "Bahan: [Bahan-bahan utama yang murah dan lokal]\n"
        "Alasan Medis Menu: [Kandungan gizi menu ini dan hubungannya dengan penyembuhan keluhan]\n"
        "Estimasi Harga: [Kisaran harga bahan dalam Rupiah]\n\n"
        "💡 *TIPS KESEHATAN TAMBAHAN*\n"
        "- [Tips gaya hidup, pola tidur, atau porsi makan untuk keluhan tersebut]\n"
        "- [Tips tambahan lainnya]\n\n"
        "Gunakan bahasa Indonesia yang sangat ramah, hangat, empati, dan menyemangati!"
    )

    return instruksi


# ══════════════════════════════════════════════
# HANDLER — /start
# ══════════════════════════════════════════════
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.first_name)

    pesan = (
        f"🌿 *Halo, {user.first_name}!* Selamat datang di *Bot Asisten Nutrisi Sehat & Murah* 🇮🇩\n\n"
        "Saya adalah asisten AI yang siap membantu kamu mendapatkan rekomendasi menu "
        "makanan sehat, murah, dan bebas alergi.\n\n"
        "🧠 *Fitur Baru:*\n"
        "• AI kini punya *memori percakapan* — saya ingat chat sebelumnya!\n"
        "• 😊 *Mood Tracker* — catat mood harianmu\n"
        "• 💧 *Pengingat Minum* — jaga hidrasi tubuhmu\n\n"
        "👇 *Silakan gunakan tombol menu di bawah untuk mulai!*"
    )

    await update.message.reply_text(
        pesan,
        parse_mode="Markdown",
        reply_markup=dapatkan_keyboard_utama(),
    )


# ══════════════════════════════════════════════
# HANDLER — Kelola Alergi (Inline Keyboard)
# ══════════════════════════════════════════════
async def kelola_alergi_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_data = get_or_create_user(user.id, user.first_name)

    keyboard = [
        [
            InlineKeyboardButton("🥚 Telur", callback_data="set_alergi_telur"),
            InlineKeyboardButton("🦐 Udang", callback_data="set_alergi_udang"),
        ],
        [
            InlineKeyboardButton("🥜 Kacang", callback_data="set_alergi_kacang"),
            InlineKeyboardButton("🥛 Susu", callback_data="set_alergi_susu"),
        ],
        [
            InlineKeyboardButton("🐟 Ikan Laut", callback_data="set_alergi_ikan"),
            InlineKeyboardButton("🌾 Gandum/Gluten", callback_data="set_alergi_gandum"),
        ],
        [
            InlineKeyboardButton("✅ Hapus Semua Alergi", callback_data="reset_alergi"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    pesan = (
        "🥗 *KELOLA ALERGI KAMU*\n\n"
        f"Status Alergi Saat Ini: *{user_data['alergi']}*\n\n"
        "Klik tombol di bawah untuk menambah alergi secara instan,\n"
        "atau ketik manual dengan format: `alergi telur, kepiting, dll`."
    )

    await update.message.reply_text(pesan, parse_mode="Markdown", reply_markup=reply_markup)


# ══════════════════════════════════════════════
# CALLBACK HANDLER — Proses Klik Tombol Alergi
# ══════════════════════════════════════════════
async def callback_alergi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    user_data = get_or_create_user(user.id, user.first_name)

    await query.answer()

    action = query.data

    if action == "reset_alergi":
        update_alergi(user.id, "Tidak ada")
        await query.edit_message_text(
            "✅ *Semua alergi berhasil dihapus!*\n\n"
            "Sekarang kamu bebas mengonsumsi semua jenis makanan.",
            parse_mode="Markdown",
        )
    elif action.startswith("set_alergi_"):
        bahan = action.replace("set_alergi_", "")
        alergi_sekarang = user_data["alergi"]

        if alergi_sekarang.lower() == "tidak ada":
            alergi_baru = bahan
        else:
            daftar_sekarang = [x.strip() for x in alergi_sekarang.split(",")]
            if bahan not in daftar_sekarang:
                daftar_sekarang.append(bahan)
            alergi_baru = ", ".join(daftar_sekarang)

        update_alergi(user.id, alergi_baru)
        await query.edit_message_text(
            f"✅ *Alergi '{bahan.capitalize()}' berhasil ditambahkan!*\n\n"
            f"Daftar alergi aktif: *{alergi_baru}*",
            parse_mode="Markdown",
        )


# ══════════════════════════════════════════════
# HANDLER — Hitung BMI
# ══════════════════════════════════════════════
async def hitung_bmi_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pesan = (
        "⚖️ *KALKULATOR BMI INDONESIA*\n\n"
        "Untuk menghitung Indeks Massa Tubuh (BMI) Anda, silakan ketik langsung di chat dengan format:\n\n"
        "`bmi [Tinggi Badan dalam cm] [Berat Badan dalam kg]`\n\n"
        "Contoh: `bmi 160 45`"
    )
    await update.message.reply_text(pesan, parse_mode="Markdown")


# ══════════════════════════════════════════════
# HANDLER — Profil
# ══════════════════════════════════════════════
async def profil_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_data = get_or_create_user(user.id, user.first_name)
    total_konsultasi = hitung_total_konsultasi(user.id)
    mood_data = ambil_mood_terakhir(user.id)

    # Format daftar alergi
    alergi = user_data["alergi"]
    if alergi.lower() != "tidak ada":
        daftar = alergi.split(", ")
        alergi_display = "\n".join([f"  🚫 {item.capitalize()}" for item in daftar])
    else:
        alergi_display = "  ✅ Tidak ada alergi tercatat"

    menu_terakhir = user_data["menu"] if user_data["menu"] else "Belum ada"

    tb = user_data["tinggi_badan"]
    bb = user_data["berat_badan"]
    bmi = user_data["bmi"]
    kategori = dapatkan_kategori_bmi(bmi)
    status_fisik = f"{tb} cm / {bb} kg\n📊 Kategori: *{kategori}*" if tb > 0 else "Belum diisi (Ketik `bmi 160 45` untuk mengisi)"

    # Mood terakhir
    mood_display = f"  {mood_data['mood']} (pada {mood_data['waktu']})" if mood_data else "  Belum pernah dicatat"

    # Saklar Reminder Harian
    status_rem = "🔔 Aktif" if user_data["reminder_harian"] == 1 else "🔕 Nonaktif"
    callback_rem = "toggle_reminder_0" if user_data["reminder_harian"] == 1 else "toggle_reminder_1"

    keyboard = [
        [InlineKeyboardButton(f"Reminder Harian: {status_rem}", callback_data=callback_rem)],
        [InlineKeyboardButton("🧠 Hapus Memori Chat AI", callback_data="hapus_chat_memory")],
        [InlineKeyboardButton("🗑️ Hapus Semua Data", callback_data="confirm_reset")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    pesan = (
        "👤 *PROFIL PENGGUNA*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ Nama: *{user_data['nama'] or user.first_name}*\n"
        f"🆔 User ID: `{user.id}`\n"
        f"📅 Bergabung: {user_data['bergabung']}\n"
        f"📊 Total Konsultasi: *{total_konsultasi} kali*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚖️ *Status Fisik & BMI:*\n  {status_fisik}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧬 *Daftar Alergi:*\n{alergi_display}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"😊 *Mood Terakhir:*\n{mood_display}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🍽️ *Menu Terakhir:*\n  {menu_terakhir}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(pesan, parse_mode="Markdown", reply_markup=reply_markup)


# ══════════════════════════════════════════════
# CALLBACK HANDLER — Reset, Toggle Reminder, Hapus Chat Memory
# ══════════════════════════════════════════════
async def callback_misc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if query.data == "confirm_reset":
        reset_user_data(user.id)
        await query.edit_message_text(
            "🗑️ *Semua data profil, data fisik BMI, riwayat konsultasi, chat memory, dan mood log berhasil dihapus bersih!*",
            parse_mode="Markdown",
        )
    elif query.data == "hapus_chat_memory":
        hapus_chat_history(user.id)
        await query.edit_message_text(
            "🧠 *Memori chat AI berhasil dihapus!*\n\n"
            "AI tidak lagi mengingat percakapan sebelumnya. Mulai dari awal yang segar! ✨",
            parse_mode="Markdown",
        )
    elif query.data.startswith("toggle_reminder_"):
        status_baru = int(query.data.replace("toggle_reminder_", ""))
        update_reminder_harian_status(user.id, status_baru)
        status_txt = "diaktifkan" if status_baru == 1 else "dinonaktifkan"
        await query.edit_message_text(
            f"✅ *Pengingat makan harian berhasil {status_txt}!*",
            parse_mode="Markdown",
        )


# ══════════════════════════════════════════════
# HANDLER — 😊 Mood Hari Ini
# ══════════════════════════════════════════════
async def mood_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    mood_data = ambil_mood_terakhir(user.id)

    status_mood = f"\nMood terakhir kamu: *{mood_data['mood']}* (dicatat {mood_data['waktu']})" if mood_data else ""

    keyboard = [
        [
            InlineKeyboardButton("😄 Sangat Baik", callback_data="mood_😄 Sangat Baik"),
            InlineKeyboardButton("🙂 Baik", callback_data="mood_🙂 Baik"),
        ],
        [
            InlineKeyboardButton("😐 Biasa", callback_data="mood_😐 Biasa"),
            InlineKeyboardButton("😔 Kurang", callback_data="mood_😔 Kurang"),
        ],
        [
            InlineKeyboardButton("😢 Buruk", callback_data="mood_😢 Buruk"),
            InlineKeyboardButton("😫 Sangat Buruk", callback_data="mood_😫 Sangat Buruk"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    pesan = (
        "😊 *MOOD TRACKER HARIAN*\n\n"
        "Bagaimana perasaanmu hari ini? Pilih salah satu di bawah.\n"
        "AI akan menyesuaikan rekomendasi nutrisi berdasarkan mood-mu! 🧠\n"
        f"{status_mood}"
    )
    await update.message.reply_text(pesan, parse_mode="Markdown", reply_markup=reply_markup)


async def callback_mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    await query.answer()

    mood = query.data.replace("mood_", "")
    get_or_create_user(user.id, user.first_name)
    simpan_mood(user.id, mood)

    await query.edit_message_text(
        f"✅ *Mood berhasil dicatat!*\n\n"
        f"Mood hari ini: *{mood}*\n\n"
        "AI akan mempertimbangkan mood-mu saat memberikan rekomendasi menu sehat berikutnya. 💚",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════
# HANDLER — 💧 Pengingat Minum Air
# ══════════════════════════════════════════════
async def pengingat_minum_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_data = get_or_create_user(user.id, user.first_name)

    # Hitung kebutuhan air berdasarkan berat badan
    bb = user_data["berat_badan"]
    if bb > 0:
        kebutuhan_ml = bb * 35  # 35ml per kg berat badan
        kebutuhan_liter = kebutuhan_ml / 1000
        info_air = (
            f"💧 *Kebutuhan air harianmu:* ~{kebutuhan_liter:.1f} liter ({kebutuhan_ml} ml)\n"
            f"_(Berdasarkan berat badan {bb} kg × 35ml/kg)_\n\n"
        )
    else:
        info_air = (
            "💧 *Kebutuhan air harian rata-rata:* ~2.0 liter\n"
            "_(Isi data BMI untuk perhitungan personal)_\n\n"
        )

    pesan = (
        "💧 *PENGINGAT MINUM AIR*\n\n"
        f"{info_air}"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 *Tips Hidrasi Sehat:*\n"
        "• Minum segelas air putih segera setelah bangun tidur 🌅\n"
        "• Minum sebelum merasa haus — haus artinya sudah mulai dehidrasi\n"
        "• Bawa botol minum ke mana-mana 🧴\n"
        "• Kurangi minuman manis & berkafein berlebihan\n"
        "• Air kelapa muda & infused water juga sangat baik!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⏰ *Jadwal Minum Ideal:*\n"
        "• 06:00 — Bangun tidur (1 gelas)\n"
        "• 08:00 — Sebelum sarapan (1 gelas)\n"
        "• 10:00 — Pagi hari (1 gelas)\n"
        "• 12:00 — Sebelum makan siang (1 gelas)\n"
        "• 14:00 — Siang hari (1 gelas)\n"
        "• 16:00 — Sore hari (1 gelas)\n"
        "• 18:00 — Sebelum makan malam (1 gelas)\n"
        "• 20:00 — Malam hari (1 gelas)\n\n"
        "💪 _Yuk, jaga hidrasi tubuhmu hari ini!_"
    )

    await update.message.reply_text(pesan, parse_mode="Markdown")


# ══════════════════════════════════════════════
# HANDLER — Riwayat
# ══════════════════════════════════════════════
async def riwayat_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    rows = ambil_riwayat(user.id, limit=5)

    if not rows:
        await update.message.reply_text(
            "📭 *Belum ada riwayat konsultasi.*\n\n"
            "Silakan ketik langsung keluhan kesehatanmu untuk memulai!",
            parse_mode="Markdown",
        )
        return

    pesan = "📋 *5 KONSULTASI TERAKHIR KAMU*\n\n"
    for i, (keluhan, menu, waktu) in enumerate(rows, 1):
        keluhan_singkat = keluhan[:50] + "..." if len(keluhan) > 50 else keluhan
        pesan += (
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"*{i}.* 🕐 {waktu}\n"
            f"   💬 Keluhan: _{keluhan_singkat}_\n"
            f"   🍽️ Menu: *{menu}*\n"
        )

    await update.message.reply_text(pesan, parse_mode="Markdown")


# ══════════════════════════════════════════════
# HANDLER — Bantuan & Tips
# ══════════════════════════════════════════════
async def bantuan_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pesan = (
        "📖 *PANDUAN & TIPS KESEHATAN*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🥗 *CARA KONSULTASI:*\n"
        "Cukup ketik langsung keluhan kesehatanmu di chat ini. Contoh:\n"
        "• _'Badan saya lemas dan kurang darah'_\n"
        "• _'Rekomendasi makanan untuk penderita maag'_\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🧠 *CHAT MEMORY:*\n"
        "AI mengingat percakapan sebelumnya! Kamu bisa bilang:\n"
        "• _'Menu kemarin enak, ada variasi lain?'_\n"
        "• _'Lanjutkan saran kemarin tentang susah tidur'_\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⚖️ *PENGISIAN DATA FISIK (BMI):*\n"
        "Ketik di chat: `bmi [Tinggi cm] [Berat kg]`\n"
        "Contoh: `bmi 165 50`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🧬 *CARA SET ALERGI:*\n"
        "1. Klik tombol *🥗 Kelola Alergi* di bawah.\n"
        "2. Pilih alergi instan dengan tombol,\n"
        "3. Atau ketik manual: `alergi telur, udang, susu`.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "😊 *MOOD TRACKER:*\n"
        "Klik *😊 Mood Hari Ini* untuk catat mood harianmu.\n"
        "AI menyesuaikan rekomendasi berdasarkan perasaanmu!"
    )
    await update.message.reply_text(pesan, parse_mode="Markdown")


# ══════════════════════════════════════════════
# CALLBACK — Pengingat Otomatis (Job Queue)
# ══════════════════════════════════════════════
async def kirim_pengingat(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    nama_menu = job.data

    pesan_pengingat = (
        "🔔 *Waktunya Makan Sehat!*\n\n"
        f"Jangan lupa mengonsumsi menu rekomendasi AI-mu hari ini:\n"
        f"🍽️ *{nama_menu}*\n\n"
        "Tetap semangat dan jaga kesehatan ya! 💪🌿"
    )
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=pesan_pengingat,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Gagal mengirim pengingat ke user %s: %s", chat_id, str(e))


# ══════════════════════════════════════════════
# HANDLER — Pesan Teks Utama
# ══════════════════════════════════════════════
async def pesan_teks_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    teks = update.message.text.strip()

    if not teks:
        return

    # 1. Hubungkan tombol menu keyboard utama
    if teks == "🥗 Kelola Alergi":
        await kelola_alergi_menu(update, context)
        return
    elif teks == "👤 Profil Saya":
        await profil_menu(update, context)
        return
    elif teks == "📋 Riwayat Menu":
        await riwayat_menu(update, context)
        return
    elif teks == "📖 Bantuan & Tips":
        await bantuan_menu(update, context)
        return
    elif teks == "⚖️ Hitung BMI":
        await hitung_bmi_menu(update, context)
        return
    elif teks == "😊 Mood Hari Ini":
        await mood_menu(update, context)
        return
    elif teks == "💧 Pengingat Minum":
        await pengingat_minum_menu(update, context)
        return

    # 2. Cek apakah pengguna mengetik format pendaftaran alergi manual
    cocok_alergi = POLA_ALERGI.match(teks)
    if cocok_alergi:
        teks_alergi = cocok_alergi.group(1).strip()
        get_or_create_user(user.id, user.first_name)

        if teks_alergi.lower() in ("tidak ada", "tidak", "none", "reset", "hapus", "kosong", "ga ada"):
            update_alergi(user.id, "Tidak ada")
            await update.message.reply_text("✅ *Data alergi berhasil direset menjadi 'Tidak ada'!*", parse_mode="Markdown")
            return

        alergi_bersih = bersihkan_alergi(teks_alergi)
        update_alergi(user.id, alergi_bersih)
        await update.message.reply_text(
            f"✅ *Alergi manual berhasil disimpan!*\n\nDaftar alergi aktif: *{alergi_bersih}*",
            parse_mode="Markdown",
        )
        return

    # 3. Cek apakah pengguna mengetik format BMI manual
    cocok_bmi = POLA_BMI.match(teks)
    if cocok_bmi:
        tinggi = int(cocok_bmi.group(1))
        berat = int(cocok_bmi.group(2))
        get_or_create_user(user.id, user.first_name)

        if tinggi > 0 and berat > 0:
            tinggi_meter = tinggi / 100.0
            bmi_val = berat / (tinggi_meter * tinggi_meter)
            update_bmi_data(user.id, tinggi, berat, bmi_val)
            kategori = dapatkan_kategori_bmi(bmi_val)

            await update.message.reply_text(
                f"✅ *Data fisik berhasil disimpan!*\n\n"
                f"📏 Tinggi: *{tinggi} cm*\n"
                f"⚖️ Berat: *{berat} kg*\n"
                f"📊 Indeks Massa Tubuh (BMI): *{bmi_val:.1f}*\n"
                f"⚠️ Status: *{kategori}*\n\n"
                f"AI akan menyesuaikan semua menu nutrisi berdasarkan data fisik ini!",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("⚠️ Angka berat/tinggi harus lebih besar dari 0.")
        return

    # 4. Selain itu, proses sebagai konsultasi kesehatan
    await proses_konsultasi(update, context, user, teks)


# ──────────────────────────────────────────────
# Sub-handler: Proses Konsultasi Kesehatan ke Gemini (dengan Chat Memory)
# ──────────────────────────────────────────────
async def proses_konsultasi(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    keluhan: str,
) -> None:
    user_data = get_or_create_user(user.id, user.first_name)
    mood_data = ambil_mood_terakhir(user.id)

    pesan_tunggu = await update.message.reply_text(
        "⏳ Sedang menganalisis keluhanmu dan menyiapkan rekomendasi menu sehat...\n"
        "Mohon tunggu sebentar ya! 🔍"
    )

    try:
        alergi_pengguna = user_data["alergi"]
        system_instruction = bangun_system_instruction(user_data, mood_data)

        # 🧠 CHAT MEMORY — Ambil 10 chat terakhir dari database
        chat_history = ambil_chat_history(user.id, limit=10)
        konteks_percakapan = ""

        if chat_history:
            konteks_percakapan = "## RIWAYAT PERCAKAPAN SEBELUMNYA (Chat Memory):\n"
            for role, pesan_lama, waktu_lama in chat_history:
                label = "Pengguna" if role == "user" else "Asisten AI"
                # Batasi panjang per pesan agar tidak melebihi token limit
                pesan_potong = pesan_lama[:300] + "..." if len(pesan_lama) > 300 else pesan_lama
                konteks_percakapan += f"[{waktu_lama}] {label}: {pesan_potong}\n"
            konteks_percakapan += "\nGunakan riwayat percakapan di atas untuk menjaga kesinambungan. Jangan ulangi menu yang sama, berikan variasi baru!\n\n"

        prompt_final = f"{konteks_percakapan}Keluhan/pesan baru dari pengguna: {keluhan}"

        # Simpan pesan user ke chat_history SEBELUM kirim ke AI
        simpan_chat(user.id, "user", keluhan)

        response = gemini_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt_final,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                max_output_tokens=1500,
            ),
        )

        jawaban_ai = response.text

        if not jawaban_ai:
            await pesan_tunggu.edit_text("😔 Maaf, AI tidak dapat memberikan rekomendasi saat ini. Silakan coba lagi.")
            return

        nama_menu = ekstrak_nama_menu(jawaban_ai)

        # Simpan ke database
        update_menu(user.id, nama_menu)
        simpan_riwayat(user.id, keluhan, nama_menu, jawaban_ai)

        # Simpan respons AI ke chat_history
        simpan_chat(user.id, "assistant", jawaban_ai)

        info_alergi = (
            f"\n\n🔒 _Filter alergi aktif: {alergi_pengguna}_"
            if alergi_pengguna.lower() != "tidak ada"
            else ""
        )

        try:
            await pesan_tunggu.edit_text(f"{jawaban_ai}{info_alergi}", parse_mode="Markdown")
        except Exception as parse_err:
            if "parse" in str(parse_err).lower():
                # Fallback: Kirim teks polos jika ada karakter markdown yang tidak valid
                await pesan_tunggu.edit_text(f"{jawaban_ai}{info_alergi}")
            else:
                raise parse_err

        # Kirim pengingat 10 detik jika status reminder aktif
        if user_data["reminder_harian"] == 1:
            jobs_lama = context.job_queue.get_jobs_by_name(f"reminder_{user.id}")
            for job in jobs_lama:
                job.schedule_removal()

            context.job_queue.run_once(
                callback=kirim_pengingat,
                when=10,
                chat_id=update.effective_chat.id,
                name=f"reminder_{user.id}",
                data=nama_menu,
            )

    except Exception as e:
        logger.error("Error Gemini: %s", str(e))
        error_str = str(e)
        
        # Intercept error Limit / Quota dari API Gemini
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "Quota exceeded" in error_str:
            pesan_error = "⏳ *Sistem sedang sibuk (Limit AI Tercapai)!*\n\nBatas penggunaan AI sedang penuh karena terlalu banyak permintaan. Mohon tunggu beberapa detik, lalu coba ketik keluhanmu lagi ya! 🙏"
        else:
            # Batasi panjang error teks agar Telegram tidak gagal kirim karena terlalu panjang
            pesan_error = f"❌ *Terjadi kesalahan.*\n\nDetail: `{error_str[:500]}`"
            
        try:
            await pesan_tunggu.edit_text(pesan_error, parse_mode="Markdown")
        except Exception:
            # Fallback tanpa parse_mode jika Markdown gagal
            await pesan_tunggu.edit_text(pesan_error.replace("*", "").replace("`", ""))


# ══════════════════════════════════════════════
# ERROR HANDLER GLOBAL — Kirim error ke chat Telegram
# ══════════════════════════════════════════════
async def error_handler(update: object, context) -> None:
    """Menangkap semua error dan mengirimkan detail ke chat Telegram."""
    logger.error("Exception saat memproses update:", exc_info=context.error)

    # Format traceback
    tb_list = tb_module.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # Batasi panjang pesan Telegram (maks 4096 karakter)
    pesan_error = (
        f"⚠️ <b>Terjadi Error pada Bot!</b>\n\n"
        f"<b>Error:</b> <code>{type(context.error).__name__}: {str(context.error)}</code>\n\n"
        f"<b>Traceback:</b>\n<pre>{tb_string[:3500]}</pre>"
    )

    # Kirim ke chat yang memicu error (jika ada update)
    if update and hasattr(update, "effective_chat") and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=pesan_error,
                parse_mode="HTML",
            )
        except Exception as send_err:
            logger.error("Gagal mengirim pesan error ke chat: %s", send_err)


# ══════════════════════════════════════════════
# MAIN — Jalankan Bot
# ══════════════════════════════════════════════
def main() -> None:
    init_db()

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(callback_alergi, pattern="^(set_alergi_|reset_alergi)"))
    application.add_handler(CallbackQueryHandler(callback_mood, pattern="^mood_"))
    application.add_handler(CallbackQueryHandler(callback_misc, pattern="^(confirm_reset|toggle_reminder_|hapus_chat_memory)"))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, pesan_teks_handler))

    # Daftarkan error handler global
    application.add_error_handler(error_handler)

    logger.info("Bot berjalan dengan Chat Memory, Mood Tracker & fitur lengkap!")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
