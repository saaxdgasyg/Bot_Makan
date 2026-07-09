"""
Bot Telegram: Asisten Nutrisi Sehat & Murah ala Indonesia
=========================================================
Fitur:
  - Menu Navigasi berbasis Tombol (Reply Keyboard / Inline Keyboard)
  - Registrasi alergi TANPA slash & dengan Tombol (Segregasi User ID Ketat)
  - Fitur Hitung BMI (Berat & Tinggi Badan disimpan di Database per User)
  - Konsultasi kesehatan personal berbasis data fisik & alergi terkini
  - Pengingat otomatis 10 detik (simulasi) + Fitur Saklar Reminder Harian
  - Database PostgreSQL (dengan auto-fallback ke SQLite untuk lokal)
  - Fitur: Profil, Riwayat, Bantuan, Reset Data, Kalkulator BMI
"""

import logging
import sqlite3
import os
import re
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

def dapatkan_koneksi():
    """Membuka koneksi ke PostgreSQL dengan fallback otomatis ke SQLite jika gagal."""
    global USE_POSTGRES
    if USE_POSTGRES:
        try:
            url = urlparse.urlparse(DATABASE_URL)
            dbname = url.path[1:]
            user = url.username
            password = url.password
            host = url.hostname
            port = url.port
            
            # Tambahkan timeout 5 detik agar bot tidak hang/loading tanpa batas
            conn = psycopg2.connect(
                dbname=dbname,
                user=user,
                password=password,
                host=host,
                port=port,
                connect_timeout=5
            )
            return conn
        except Exception as e:
            logger.error("Gagal menyambung ke PostgreSQL, beralih otomatis ke SQLite! Error: %s", str(e))
            USE_POSTGRES = False # Nonaktifkan postgres untuk pemanggilan selanjutnya
            return sqlite3.connect(DB_PATH)
    else:
        return sqlite3.connect(DB_PATH)

def dapatkan_placeholder():
    return "%s" if USE_POSTGRES else "?"

def init_db() -> None:
    """Inisialisasi tabel dengan kolom tambahan BMI & status reminder."""
    conn = dapatkan_koneksi()
    cursor = conn.cursor()

    if USE_POSTGRES:
        logger.info("Menggunakan database PostgreSQL.")
        cursor.execute(
            """
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
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS riwayat (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                keluhan     TEXT NOT NULL,
                menu        VARCHAR(255) NOT NULL,
                jawaban_ai  TEXT NOT NULL,
                waktu       VARCHAR(50) NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            """
        )
    else:
        logger.info("Menggunakan database SQLite.")
        cursor.execute(
            """
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
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS riwayat (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                keluhan     TEXT    NOT NULL,
                menu        TEXT    NOT NULL,
                jawaban_ai  TEXT    NOT NULL,
                waktu       TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            """
        )

    # Migrasi kolom lama jika SQLite belum punya kolom baru (untuk keamanan)
    if not USE_POSTGRES:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN tinggi_badan INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE users ADD COLUMN berat_badan INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE users ADD COLUMN bmi REAL DEFAULT 0.0")
            cursor.execute("ALTER TABLE users ADD COLUMN reminder_harian INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass # Kolom sudah ada

    conn.commit()
    conn.close()
    logger.info("Database siap digunakan.")


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
    cursor.execute(
        f"UPDATE users SET alergi = 'Tidak ada', menu = '', reminder = 0, tinggi_badan = 0, berat_badan = 0, bmi = 0.0, reminder_harian = 1 WHERE user_id = {p}",
        (user_id,),
    )
    conn.commit()
    conn.close()


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
        [KeyboardButton("📖 Bantuan & Tips")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, placeholder_keyboard="Pilih menu atau ketik keluhan...")


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
def bangun_system_instruction(user_data: dict) -> str:
    alergi = user_data["alergi"]
    tb = user_data["tinggi_badan"]
    bb = user_data["berat_badan"]
    bmi = user_data["bmi"]
    kategori = dapatkan_kategori_bmi(bmi)

    info_fisik = f"Tinggi Badan: {tb} cm, Berat Badan: {bb} kg, BMI: {bmi:.1f} ({kategori})." if tb > 0 else "Data fisik belum diisi pengguna."

    instruksi = (
        "Kamu adalah seorang Dokter, Spesialis Nutrisi, dan Ahli Gizi Ramah Indonesia yang sangat berpengalaman.\n"
        "Tugasmu adalah memberikan analisis keluhan kesehatan pengguna dan memberikan rekomendasi menu sehat "
        "lokal Indonesia beserta tips gaya hidup/pola tidur medis yang sangat lengkap dan solutif. Jangan memotong penjelasan penting!\n\n"
        "## DATA FISIK PENGGUNA SAAT INI:\n"
        f"- {info_fisik}\n"
        "Gunakan data fisik di atas untuk menganalisis kebutuhan kalori, porsi makan, atau anjuran nutrisi mereka secara personal.\n\n"
        "## ATURAN MUTLAK YANG WAJIB DIPATUHI:\n\n"
        "### 1. RENCANA MENU HARUS MURAH & LOKAL INDONESIA\n"
        "- Gunakan bahan makanan lokal yang terjangkau di pasar tradisional (tahu, tempe, telur, bayam, kangkung, daun kelor, hati ayam, pisang, pepaya, ubi, singkong, kacang hijau, lele, ikan teri, dll).\n"
        "- DILARANG keras menyarankan bahan impor mahal seperti salmon, tuna segar premium, blueberry, quinoa, oatmeal, asparagus, chia seed, dll.\n"
        "- Estimasi total harga bahan harus ramah kantong (Rp 5.000 - Rp 25.000).\n\n"
        "### 2. FILTER ALERGI KETAT\n"
        f"- Pengguna memiliki ALERGI terhadap: **{alergi}**.\n"
    )

    if alergi.lower() != "tidak ada":
        daftar_alergi = [a.strip() for a in alergi.split(",")]
        instruksi += (
            "- DILARANG KERAS merekomendasikan menu yang mengandung bahan-bahan tersebut beserta seluruh turunannya.\n"
        )

    instruksi += (
        "\n### 3. FORMAT RESPON (LENGKAP & DETAIL)\n"
        "Jawab dengan struktur rapi berikut:\n\n"
        "🩺 *ANALISIS MEDIS & KELUHAN*\n"
        "[Berikan penjelasan medis singkat mengenai keluhan mereka (misal: kenapa susah tidur, bagaimana cara menambah berat badan sesuai data fisiknya di umur mereka, dll). Berikan saran medis yang jelas dan solutif!]\n\n"
        "🍽️ *REKOMENDASI MENU SEHAT*\n"
        "Menu: [Nama Masakan Indonesia yang Spesifik]\n"
        "Bahan: [Bahan-bahan utama yang murah dan lokal]\n"
        "Alasan Medis Menu: [Kandungan gizi menu ini dan hubungannya dengan penyembuhan keluhan]\n"
        "Estimasi Harga: [Kisaran harga bahan dalam Rupiah, misal: Rp 10.000 - Rp 15.000]\n\n"
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
        "makanan sehat, murah, dan bebas alergi. Kamu bisa menggunakan tombol di bawah untuk menavigasi bot ini!\n\n"
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

    # Saklar Reminder Harian
    status_rem = "🔔 Aktif" if user_data["reminder_harian"] == 1 else "🔕 Nonaktif"
    callback_rem = "toggle_reminder_0" if user_data["reminder_harian"] == 1 else "toggle_reminder_1"

    keyboard = [
        [InlineKeyboardButton(f"Reminder Harian: {status_rem}", callback_data=callback_rem)],
        [InlineKeyboardButton("🗑️ Hapus Semua Data", callback_data="confirm_reset")]
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
        f"🍽️ *Menu Terakhir:*\n  {menu_terakhir}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(pesan, parse_mode="Markdown", reply_markup=reply_markup)


# ══════════════════════════════════════════════
# CALLBACK HANDLER — Reset & Toggle Reminder
# ══════════════════════════════════════════════
async def callback_misc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if query.data == "confirm_reset":
        reset_user_data(user.id)
        await query.edit_message_text(
            "🗑️ *Semua data profil, data fisik BMI, dan riwayat konsultasi kamu berhasil dihapus bersih!*",
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
        "⚖️ *PENGISIAN DATA FISIK (BMI):*\n"
        "Ketik di chat: `bmi [Tinggi cm] [Berat kg]`\n"
        "Contoh: `bmi 165 50`\n"
        "Data ini membantu AI memberi rekomendasi gizi yang pas!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🧬 *CARA SET ALERGI:*\n"
        "1. Klik tombol *🥗 Kelola Alergi* di bawah.\n"
        "2. Pilih alergi instan dengan tombol yang tersedia,\n"
        "3. Atau ketik manual di chat: `alergi telur, udang, susu`."
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
# HANDLER — Pesan Teks Utama (Menangani Teks Biasa/Tombol Menu/Alergi/BMI)
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
            parse_mode="Markdown"
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
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⚠️ Angka berat/tinggi harus lebih besar dari 0.")
        return

    # 4. Selain itu, proses sebagai konsultasi kesehatan
    await proses_konsultasi(update, context, user, teks)


# ──────────────────────────────────────────────
# Sub-handler: Proses Konsultasi Kesehatan ke Gemini
# ──────────────────────────────────────────────
async def proses_konsultasi(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    keluhan: str,
) -> None:
    user_data = get_or_create_user(user.id, user.first_name)

    pesan_tunggu = await update.message.reply_text(
        "⏳ Sedang menganalisis keluhanmu dan menyiapkan rekomendasi menu sehat...\n"
        "Mohon tunggu sebentar ya! 🔍"
    )

    try:
        alergi_pengguna = user_data["alergi"]
        system_instruction = bangun_system_instruction(user_data)

        # Ambil riwayat percakapan terakhir (maksimal 3 riwayat terakhir)
        riwayat_terakhir = ambil_riwayat(user.id, limit=3)
        konteks_percakapan = ""
        
        if riwayat_terakhir:
            konteks_percakapan = "Berikut adalah riwayat konsultasi terakhir dari pengguna ini untuk menjaga kesinambungan percakapan:\n"
            for r_keluhan, r_menu, r_waktu in reversed(riwayat_terakhir):
                konteks_percakapan += f"- Waktu: {r_waktu} | Keluhan: '{r_keluhan}' | Menu Direkomendasikan: '{r_menu}'\n"
            konteks_percakapan += "\nGunakan informasi di atas untuk melanjutkan konsultasi jika keluhan baru ini berhubungan dengan keluhan sebelumnya. Jangan rekomendasikan menu yang sama persis jika keluhannya mirip, berikan variasi menu baru!\n\n"

        prompt_final = f"{konteks_percakapan}Keluhan kesehatan baru saya saat ini: {keluhan}"

        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_final,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                max_output_tokens=1024,
            ),
        )

        jawaban_ai = response.text

        if not jawaban_ai:
            await pesan_tunggu.edit_text("😔 Maaf, AI tidak dapat memberikan rekomendasi saat ini. Silakan coba lagi.")
            return

        nama_menu = ekstrak_nama_menu(jawaban_ai)

        update_menu(user.id, nama_menu)
        simpan_riwayat(user.id, keluhan, nama_menu, jawaban_ai)

        info_alergi = (
            f"\n\n🔒 _Filter alergi aktif: {alergi_pengguna}_"
            if alergi_pengguna.lower() != "tidak ada"
            else ""
        )

        await pesan_tunggu.edit_text(f"{jawaban_ai}{info_alergi}", parse_mode="Markdown")

        # Kirim pengingat 10 detik jika status reminder aktif
        if user_data["reminder_harian"] == 1:
            # Hapus job lama
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
        await pesan_tunggu.edit_text(
            f"❌ *Terjadi kesalahan.*\n\nDetail: `{str(e)}`",
            parse_mode="Markdown",
        )


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
    application.add_handler(CallbackQueryHandler(callback_misc, pattern="^(confirm_reset|toggle_reminder_)"))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, pesan_teks_handler))

    logger.info("Bot berjalan dengan fitur pemisahan user ID ketat & hitung BMI!")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
