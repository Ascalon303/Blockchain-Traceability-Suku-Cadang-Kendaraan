# Menjalankan blockchain sebagai node di 2 laptop (dengan Docker)

Dua laptop = dua node dalam satu jaringan. Tiap laptop memegang aktor yang berbeda,
karena satu aktor hanya boleh dipegang SATU node (private key aktor hanya ada di laptop pemiliknya).

| | Laptop 1 | Laptop 2 |
|---|---|---|
| Aktor | Produsen, Distributor | Dealer, Bengkel |
| Port | 9001 | 9002 |
| Berkas compose | `docker-compose.laptop1.yml` | `docker-compose.laptop2.yml` |
| Nama container | `node-laptop1` | `node-laptop2` |
| `PEER_ADDR` di `.env` | alamat laptop 2 (`IP:9002`) | alamat laptop 1 (`IP:9001`) |

Berkas compose 3 node dan 5 node (`docker_compose.yml`, `docker-compose_5_node.yml`) tetap untuk
Bagian 2 praktikum (semua node di satu mesin). Nama berkas di komputer Anda mungkin berbeda;
sesuaikan dengan `docker compose -f <namaberkas> ...`.

---

## 1. Persiapan (di KEDUA laptop)

1. Kedua laptop satu jaringan (WiFi yang sama atau hotspot HP). WiFi kampus sering memblokir
   komunikasi antar-klien; kalau tes koneksi di langkah 3 gagal, pindah ke hotspot HP.
2. Cari IP masing-masing: `ipconfig` (Windows, lihat *IPv4 Address*) atau `ip a` (Linux/Mac).
   Contoh di bawah: laptop 1 = `192.168.1.10`, laptop 2 = `192.168.1.11`. Ganti dengan IP Anda.
3. Pasang Docker (Docker Desktop untuk Windows/Mac) dan salin folder proyek ini ke kedua laptop.

## 2. Firewall (di KEDUA laptop)

Izinkan koneksi masuk ke port node.

- Windows (PowerShell sebagai Administrator):
  `netsh advfirewall firewall add rule name="node-blockchain" dir=in action=allow protocol=TCP localport=9001-9002`
- Linux: `sudo ufw allow 9001:9002/tcp`

## 3. Isi `.env` lalu jalankan

Di **laptop 1**:
```
cp .env.example .env           # Windows: copy .env.example .env
# edit .env  ->  PEER_ADDR=192.168.1.11:9002
docker compose -f docker-compose.laptop1.yml up -d --build
docker attach node-laptop1
```

Di **laptop 2**:
```
cp .env.example .env
# edit .env  ->  PEER_ADDR=192.168.1.10:9001
docker compose -f docker-compose.laptop2.yml up -d --build
docker attach node-laptop2
```

Hal yang perlu diperhatikan:
- `PEER_ADDR` wajib diisi. Kalau kosong, compose berhenti dengan pesan yang meminta Anda mengisinya.
- Menu muncul setelah `docker attach`. Keluar dari attach TANPA menghentikan node: tekan
  **Ctrl+P lalu Ctrl+Q**. Untuk menghentikan node, pilih menu 7.
- Urutan menyalakan laptop bebas. Node yang menyala lebih dulu akan terhubung saat laptop lain menyusul
  (lewat menu 3, atau otomatis saat laptop lain start).
- Log tanpa attach: `docker logs node-laptop1`. Hentikan dan hapus container:
  `docker compose -f docker-compose.laptop1.yml down` (data di `./data/laptop1` tetap ada).
- Folder `./data/laptopN` berisi **private key** dan `chain.json`. Jangan dihapus selama node masih dipakai,
  dan jangan dimasukkan ke repositori (sudah ada di `.gitignore`).

Tes koneksi bila perlu (node di laptop tujuan harus sudah berjalan):
- Windows: `Test-NetConnection 192.168.1.10 -Port 9001`
- Linux/Mac: `nc -vz 192.168.1.10 9001` atau `curl http://192.168.1.10:9001/status`

## 4. Memastikan kedua laptop terhubung

1. Di log saat start harus ada baris `Sinkron <IP>:<port> -> key baru: ...`.
2. Laptop 1, menu 1: Produsen, status `PRODUCED`, parent kosong. Lalu menu 1 lagi: Distributor,
   status `SHIPPED`, parent 1. Log menampilkan `berhasil ditambang lokal` lalu `Kirim block ... ke <IP>:9002`.
3. Laptop 2, menu 2: block 1 dan 2 muncul (isinya terenkripsi, karena private key ada di laptop 1).
4. Bandingkan di kedua laptop: **Nonce, Parent ID, Parent hash, dan Hash** tiap block harus sama persis.
5. Laptop 2, menu 1: Dealer, status `RECEIVED`, parent 2. Di laptop 1 muncul `menerima block 3`.
6. Kedua laptop, menu 4: hasilnya `valid=True`.

## 5. Skenario lain

- **Node mati lalu hidup lagi.** Matikan satu laptop, tambah block di laptop lain (log: `Gagal kirim block ...`).
  Nyalakan lagi: chain dimuat dari `chain.json`, lalu block yang tertinggal diambil dari peer
  (log: `Dimuat N block ...` dan `block diterima: M`).
- **Fork.** Menu 6 → `h` untuk memutus peer di kedua laptop, tambah block berbeda dengan id yang sama,
  lalu sambung lagi (menu 6 → `t`). Menu 5 menampilkan chain utama dan riwayat resolusi fork.
  Aturannya: chain valid yang lebih panjang menang; seri tetap memakai chain lokal.
- **Menambah peer dari luar proses (`POST /peers`, HTTP).** Peer hanya ditambahkan ke daftar, tidak langsung
  sinkron. Panggil `POST /nodes/resolve` sesudahnya (atau pakai menu 3):
  ```
  curl -X POST http://192.168.1.11:9002/peers -H "Content-Type: application/json" -d '{"peer": "192.168.1.10:9001"}'
  curl -X POST http://192.168.1.11:9002/nodes/resolve
  curl http://192.168.1.11:9002/peers
  curl http://192.168.1.11:9002/status
  ```
  Balasan: `201` peer baru, `200` sudah ada, `400` format salah. Di Windows PowerShell gunakan `curl.exe` dengan
  tanda kutip ganda yang di-escape, atau `Invoke-RestMethod -Method Post -Uri http://192.168.1.11:9002/peers
  -ContentType application/json -Body '{"peer":"192.168.1.10:9001"}'`.
  Catatan: endpoint tidak memakai autentikasi atau TLS; siapa pun yang bisa menjangkau port node dapat memanggilnya.

## 6. Tanpa Docker

```
pip install -r requirements.txt
# laptop 1
python node.py --port 9001 --authors Produsen Distributor --peers 192.168.1.11:9002
# laptop 2
python node.py --port 9002 --authors Dealer Bengkel --peers 192.168.1.10:9001
```
Key dan `chain.json` tersimpan di `data_<port>/` (ubah dengan `--data-dir`).

## 7. Masalah yang sering muncul

| Gejala | Penyebab dan solusi |
|---|---|
| `Gagal kirim block ... Connection refused` / timeout | Node lawan belum jalan, IP salah, atau firewall menutup port. Cek dengan tes koneksi di bagian 3. |
| Antar laptop tidak bisa terhubung di WiFi kampus | Client isolation. Pakai hotspot HP atau jaringan lain. |
| Container langsung berhenti | Menu butuh `stdin_open` dan `tty` (sudah ada di compose). Jangan jalankan dengan cara lain tanpa dua opsi itu. |
| `ditolak ... signature tidak valid` | Public key aktor belum sampai ke node itu. Jalankan menu 3 (sinkron dua arah). |
| `public key ... BERBEDA -- ditolak` | Dua node memegang aktor yang sama, atau folder `data` salah satu node terhapus lalu key dibuat ulang. Satu aktor hanya boleh di satu node. |
| `chain.json` lama menolak block (`N ditolak`) | Folder `data` dari versi kode yang berbeda. Hapus `chain.json` (key boleh dipertahankan). |
| `port is already allocated` | Port 9001/9002 dipakai proses lain. Hentikan container lama: `docker compose -f ... down`. |

## 8. Skrip pengujian dan eksperimen (opsional)

| Perintah | Fungsi | Port |
|---|---|---|
| `python uji_node.py` | 26 uji: sinkron, serangan, restart, kode status HTTP | 9101, 9102, 9199 |
| `python uji_fork.py` | 12 uji: fork GANTI / SERI / PERTAHANKAN | 9111, 9112 |
| `python uji_fork_2v3.py` | 20 uji: fork 2 vs 3 block lewat `POST /peers` dan `POST /nodes/resolve` | 9121, 9122 |
| `python demo_hash.py` | Demo hashing dan efek avalanche | - |
| `python eksperimen_difficulty.py --difficulty 0000 00000 --runs 20 --csv hasil.csv` | Waktu mining dan percobaan per difficulty | - |
| `python eksperimen_tulis_ulang.py --difficulty 0000 00000 --blocks 6 --runs 10` | Biaya menulis ulang riwayat | - |

Pakai `--runs` besar (10 sampai 20). Dengan sampel kecil, angka bisa menyimpang jauh dari teori
(mis. kenaikan 16 → 20 bit teorinya x16, tetapi 3 ulangan bisa menghasilkan x15 sampai x54).
