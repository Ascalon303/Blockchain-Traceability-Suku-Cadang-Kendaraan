# Image untuk satu node blockchain traceability.
FROM python:3.12-10
WORKDIR /app

# Pasang dependensi dari requirements.txt (hanya 'cryptography').
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Salin semua berkas .py (node.py + blockchain_core_traceability_suku_cadang_kendaraan.py).
COPY *.py ./

# -u = output tidak di-buffer, supaya log langsung terlihat di 'docker attach'/'docker logs'.
# Argumen (--port, --authors, --peers) diberikan lewat 'command' di docker-compose.yml.
ENTRYPOINT ["python", "-u", "node.py"]