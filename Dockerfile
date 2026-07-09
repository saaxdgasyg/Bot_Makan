FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Salin file requirements terlebih dahulu (layer caching Docker)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Salin seluruh kode aplikasi
COPY . .

# Jalankan bot
CMD ["python", "main.py"]
