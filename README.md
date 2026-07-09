# 🌿 Bot Asisten Nutrisi Sehat & Murah ala Indonesia

Bot Telegram berbasis AI yang memberikan rekomendasi menu makanan sehat, murah, dan lokal Indonesia berdasarkan keluhan kesehatan pengguna — dilengkapi filter alergi ketat dan pengingat otomatis.

---

## 📁 Struktur Proyek

```
Botmakan/
├── main.py              # Kode utama bot
├── requirements.txt     # Daftar dependensi Python
├── Dockerfile           # Konfigurasi Docker untuk Railway
├── .gitignore           # File yang diabaikan Git
└── README.md            # Panduan ini
```

---

## ⚙️ Persiapan Sebelum Deploy

### 1. Buat Bot Telegram
1. Buka Telegram, cari **@BotFather**.
2. Ketik `/newbot`, ikuti instruksinya.
3. Salin **token bot** yang diberikan (contoh: `7123456789:AAH...`).

### 2. Dapatkan API Key Gemini
1. Buka [Google AI Studio](https://aistudio.google.com/apikey).
2. Klik **Create API Key**.
3. Salin API Key yang dihasilkan.

---

## 🚀 Panduan Deploy ke Railway (via GitHub)

### Langkah 1: Inisialisasi Git & Push ke GitHub

```bash
# Masuk ke folder proyek
cd Botmakan

# Inisialisasi repository Git
git init

# Tambahkan semua file
git add .

# Commit pertama
git commit -m "Initial commit: Bot Asisten Nutrisi Sehat"

# Buat repository baru di GitHub (via browser):
#   1. Buka https://github.com/new
#   2. Beri nama repository, misal: "bot-nutrisi-sehat"
#   3. Pilih "Private" agar token aman
#   4. Jangan centang "Add a README" (sudah ada)
#   5. Klik "Create repository"

# Hubungkan dengan repository GitHub (ganti URL sesuai milikmu)
git remote add origin https://github.com/USERNAME/bot-nutrisi-sehat.git

# Push kode ke GitHub
git branch -M main
git push -u origin main
```

### Langkah 2: Hubungkan GitHub ke Railway

1. Buka [Railway.app](https://railway.app/) dan login dengan akun GitHub.
2. Klik **"New Project"** → **"Deploy from GitHub repo"**.
3. Pilih repository **bot-nutrisi-sehat** yang baru dibuat.
4. Railway akan otomatis mendeteksi `Dockerfile` dan mulai build.

### Langkah 3: Atur Environment Variables di Railway

> ⚠️ **PENTING**: Jangan pernah tulis token langsung di kode! Gunakan Environment Variables.

1. Di dashboard Railway, klik service/project kamu.
2. Buka tab **"Variables"**.
3. Tambahkan 2 variabel berikut:

| Variable Name    | Value                          |
|------------------|--------------------------------|
| `TELEGRAM_TOKEN` | Token bot dari BotFather       |
| `GEMINI_API_KEY` | API Key dari Google AI Studio  |

4. Klik **"Add"** untuk masing-masing variabel.
5. Railway akan otomatis melakukan **redeploy** setelah variabel ditambahkan.

### Langkah 4: Verifikasi Bot Berjalan

1. Buka tab **"Deployments"** di Railway, pastikan statusnya **"Active"**.
2. Cek tab **"Logs"** untuk memastikan tidak ada error.
3. Buka Telegram, cari bot kamu, dan ketik `/start`.

---

## 🧪 Cara Menjalankan Secara Lokal (Opsional)

```bash
# Buat virtual environment
python -m venv .venv

# Aktifkan virtual environment
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# Install dependensi
pip install -r requirements.txt

# Set environment variables
# Windows (PowerShell):
$env:TELEGRAM_TOKEN = "TOKEN_BOT_KAMU_DI_SINI"
$env:GEMINI_API_KEY = "API_KEY_GEMINI_DI_SINI"

# Windows (CMD):
set TELEGRAM_TOKEN=TOKEN_BOT_KAMU_DI_SINI
set GEMINI_API_KEY=API_KEY_GEMINI_DI_SINI

# Linux/Mac:
export TELEGRAM_TOKEN="TOKEN_BOT_KAMU_DI_SINI"
export GEMINI_API_KEY="API_KEY_GEMINI_DI_SINI"

# Jalankan bot
python main.py
```

---

## 📱 Cara Menggunakan Bot

| Perintah / Aksi | Fungsi |
|---|---|
| `/start` | Memulai bot dan melihat panduan |
| `/alergi telur, udang, kacang` | Mendaftarkan alergi (pisah koma) |
| `/alergi tidak ada` | Menghapus/reset data alergi |
| Ketik keluhan biasa | Konsultasi kesehatan ke AI |

### Contoh Penggunaan:

```
Pengguna: /alergi telur, udang
Bot:      ✅ Data alergi berhasil disimpan!
          🚫 Telur
          🚫 Udang

Pengguna: Saya lemas karena anemia
Bot:      🍽️ REKOMENDASI MENU SEHAT
          Menu: Tumis Bayam Hati Ayam
          Bahan: bayam, hati ayam, bawang putih, bawang merah, tomat
          Alasan Medis: Bayam kaya zat besi, hati ayam sumber vitamin B12...
          Estimasi Harga: Rp 12.000 - Rp 18.000
          💡 Tips: Konsumsi bersama jeruk untuk penyerapan zat besi optimal

[10 detik kemudian]
Bot:      🔔 Waktunya Makan Sehat!
          Jangan lupa mengonsumsi menu rekomendasi AI-mu hari ini:
          🍽️ Tumis Bayam Hati Ayam
          Tetap semangat dan jaga kesehatan ya! 💪🌿
```

---

## 🛡️ Keamanan

- Token dan API Key disimpan sebagai **Environment Variables**, bukan di kode.
- File `.gitignore` memastikan database `.db` dan folder `.venv` tidak terunggah ke GitHub.
- Gunakan repository **Private** di GitHub untuk keamanan ekstra.

---

## 📝 Lisensi

Proyek ini dibuat untuk keperluan edukasi dan penggunaan pribadi.
