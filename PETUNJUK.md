# Petunjuk menjalankan (revisi 5)

## 1. Persiapan
- Python 3.10+ dan satu paket: `pip install cryptography` (lihat `requirements.txt`).
- Semua perintah dijalankan dari folder proyek.

## 2. Menjalankan node
Satu node = satu proses `node.py`. Contoh empat node di satu komputer, satu node untuk tiap aktor
berwenang (empat terminal):

```
python node.py --port 9001 --authors Produsen    --peers 127.0.0.1:9002 127.0.0.1:9003 127.0.0.1:9004
python node.py --port 9002 --authors Distributor --peers 127.0.0.1:9001 127.0.0.1:9003 127.0.0.1:9004
python node.py --port 9003 --authors Dealer      --peers 127.0.0.1:9001 127.0.0.1:9002 127.0.0.1:9004
python node.py --port 9004 --authors Bengkel     --peers 127.0.0.1:9001 127.0.0.1:9002 127.0.0.1:9003
```
- `--authors`: aktor yang private key-nya dipegang node ini (Produsen, Distributor, Dealer, Bengkel).
  Satu aktor hanya boleh dipegang satu node; tiap node menyimpan key dan `chain.json` di `data_<port>/`.
- `--peers`: alamat semua node lain (`host:port`). Tiap node harus mengenal semua node lain (full mesh).
- Nyalakan node bertahap (jeda beberapa detik) supaya pertukaran public key terjadi saat node baru bergabung.

## 3. Menu console
```
1) Buat transaksi baru (ditandatangani -> pool -> disiarkan)
2) Lihat transaction pool
3) Tambang block dari pool (lalu siarkan)
4) Tampilkan chain
5) Validasi chain
6) Sinkron + resolve fork (longest-chain) dengan semua peer
7) Kelola peer (tambah/hapus)
8) Riwayat fork
9) Demo deteksi manipulasi data (pada salinan)
0) Keluar
```
Alur biasa: menu 1 di node pengirim, lalu menu 3 di node mana pun (block disiarkan ke semua node),
menu 5 untuk memvalidasi, menu 9 untuk memperagakan deteksi manipulasi.

## 4. Lewat HTTP (curl)
```
curl -X POST localhost:9001/transactions/create -H "Content-Type: application/json" \
  -d '{"sender":"Produsen","part_id":"SP-1","part_name":"Filter Oli","origin":"Produsen","destination":"Dealer","vehicle_id":"VH-1","status":"PRODUCED"}'
curl localhost:9002/transactions                    # transaksi sudah ada di pool node lain
curl -X POST localhost:9002/mine                    # tambang block dari pool lalu siarkan
curl localhost:9003/status                          # jumlah_block, pool, ujung_hash, chain_valid
curl -X POST localhost:9001/peers -H "Content-Type: application/json" -d '{"peer": "localhost:9004"}'
curl -X POST localhost:9001/nodes/resolve           # sinkron dan resolusi fork
```
Daftar endpoint lengkap ada di docstring `node.py` dan di `dokumentasi_perubahan_dan_fungsi.md`.
Di Windows PowerShell gunakan `curl.exe` atau `Invoke-RestMethod`.

## 5. Mode mandiri (tanpa jaringan)
`python blockchain_core_traceability_suku_cadang_kendaraan.py` -- menu untuk transaksi, pool, mining,
validasi, demo manipulasi, dan memuat `contoh_transaksi.json`.

## 6. Pengujian otomatis (semua mandiri, memakai port lokal)
| Perintah | Isi | Port |
|---|---|---|
| `python uji_core.py` | inti: transaksi, pool, PoW, validasi, manipulasi, fork, penyimpanan | - |
| `python uji_node.py` | dua node: serangan, kode status HTTP, restart, berkas dimanipulasi | 9101, 9102 |
| `python uji_3node.py` | **tiga node**: broadcast, pool, block, penolakan, log console | 9131-9133 |
| `python uji_4node.py` | **empat node, satu per aktor**: siklus PRODUCED sampai INSTALLED | 9181-9184 |
| `python uji_2laptop.py` | **topologi dua laptop** (2 aktor per node, 1 peer): siklus penuh, privasi, node mati lalu hidup | 9191, 9192 |
| `python uji_fork.py` | fork panjang sama (SERI) lalu diselesaikan block berikutnya | 9111, 9112 |
| `python uji_fork_2v3.py` | **Tugas 5**: A 2 block vs B 3 block, `POST /peers`, resolve, orphan | 9121, 9122 |

## 7. Skrip bukti untuk laporan
| Perintah | Tugas |
|---|---|
| `python demo_hash.py` | 3 (data domain ikut menentukan hash) |
| `python eksperimen_difficulty.py --difficulty 0000 00000 --runs 20 --csv hasil.csv` | 6 (waktu mining) |
| `python eksperimen_tulis_ulang.py --difficulty 0000 00000 --blocks 6 --runs 10` | 6 (biaya menulis ulang riwayat) |

Tugas 6 pada node hidup: ubah `DIFFICULTY = "0000"` menjadi `"00000"` di
`blockchain_core_traceability_suku_cadang_kendaraan.py` (nilainya harus sama di SEMUA node).

## 8. Docker
`docker_compose.yml` (4 node: Produsen, Distributor, Dealer, Bengkel) dan `docker-compose_5_node.yml`
(5 node: keempat aktor + satu node pengamat):
```
docker compose -f docker_compose.yml up -d --build
docker attach node1          # lepas dengan Ctrl+P lalu Ctrl+Q
```
Untuk dua laptop fisik pakai `docker-compose.laptop1.yml` dan `docker-compose.laptop2.yml` (bagian 9).
Catatan: baris `FROM` di `Dockerfile` perlu tag Python yang valid (mis. `python:3.12-slim`).
Berkas `chain.json` lama (revisi 4) otomatis dicadangkan menjadi `chain.json.format-lama.bak`.

## 9. Dua laptop (Docker, HTTP)

Dua laptop = dua node dalam satu jaringan. Tiap laptop memegang aktor yang berbeda, karena satu aktor
hanya boleh dipegang SATU node (private key aktor hanya ada di laptop pemiliknya). Node berbicara lewat
HTTP, jadi laptop cukup saling menjangkau port node lewat jaringan.

| | Laptop 1 | Laptop 2 |
|---|---|---|
| Aktor | Produsen, Distributor | Dealer, Bengkel |
| Port | 9001 | 9002 |
| Berkas compose | `docker-compose.laptop1.yml` | `docker-compose.laptop2.yml` |
| Nama container | `node-laptop1` | `node-laptop2` |
| `PEER_ADDR` di `.env` | alamat laptop 2 (`IP:9002`) | alamat laptop 1 (`IP:9001`) |

Pembagian aktor ini cukup untuk satu siklus penuh: PRODUCED dan SHIPPED dibuat di laptop 1, RECEIVED dan
INSTALLED dibuat di laptop 2. Berkas `.env.example` berisi contoh isi `.env`.

### 9.1 Persiapan (di KEDUA laptop)

1. Kedua laptop satu jaringan (WiFi yang sama atau hotspot HP). WiFi kampus sering memblokir komunikasi
   antar-klien; kalau tes koneksi gagal, pindah ke hotspot HP.
2. Cari IP masing-masing: `ipconfig` (Windows, lihat *IPv4 Address*) atau `ip a` (Linux/Mac). Contoh di bawah:
   laptop 1 = `192.168.1.10`, laptop 2 = `192.168.1.11`. Ganti dengan IP Anda.
3. Pasang Docker (Docker Desktop untuk Windows/Mac), salin folder proyek ke kedua laptop, dan pastikan
   baris `FROM` di `Dockerfile` memakai tag Python yang valid.

### 9.2 Firewall (di KEDUA laptop)

Izinkan koneksi masuk ke port node (HTTP berjalan di atas TCP).
- Windows (PowerShell sebagai Administrator):
  `netsh advfirewall firewall add rule name="node-blockchain" dir=in action=allow protocol=TCP localport=9001-9002`
- Linux: `sudo ufw allow 9001:9002/tcp`

### 9.3 Isi `.env` lalu jalankan

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
- `PEER_ADDR` wajib diisi; kalau kosong, compose berhenti dengan pesan yang memintanya.
- Keluar dari `docker attach` TANPA menghentikan node: `Ctrl+P` lalu `Ctrl+Q`. Menghentikan node: menu 0.
- Urutan menyalakan laptop bebas. Node yang menyala lebih dulu terhubung saat laptop lain menyusul
  (otomatis saat laptop lain start, atau lewat menu 6).
- Log tanpa attach: `docker logs node-laptop1`. Hentikan dan hapus container:
  `docker compose -f docker-compose.laptop1.yml down` (data di `./data/laptop1` tetap ada).
- Folder `./data/laptopN` berisi **private key** dan `chain.json`; jangan dihapus selama node dipakai dan
  jangan dimasukkan ke repositori (sudah ada di `.gitignore`).

Tes koneksi (node di laptop tujuan harus sudah berjalan):
- Windows: `Test-NetConnection 192.168.1.10 -Port 9001`
- Linux/Mac: `curl http://192.168.1.10:9001/status`

### 9.4 Memastikan kedua laptop terhubung

1. Saat start, log menampilkan baris `[SYNC] rantai <IP>:<port>: ...` (atau `[SYNC] Gagal menghubungi ...`
   bila laptop lawan belum menyala; itu normal).
2. Laptop 1, menu 1: Produsen, `part_id` SP-1, status `PRODUCED`. Menu 1 lagi: Distributor, SP-1, `SHIPPED`.
   Log: `[TX] DITERIMA ...` lalu `[BROADCAST] transaksi ... -> <IP>:9002: OK (baru)`.
3. Laptop 2, menu 2: kedua transaksi sudah ada di pool laptop 2.
4. Laptop 2, menu 3 (menambang): log `[MINING] SELESAI block #1 ...` lalu
   `[BROADCAST] block #1 -> <IP>:9001: DITERIMA`. Pool kedua laptop menjadi kosong.
5. Laptop 2, menu 1: Dealer `RECEIVED`, lalu Bengkel `INSTALLED`. Di laptop 1, menu 3 untuk menambang.
6. Menu 4 di kedua laptop: `hash`, `previous_hash`, dan `nonce` tiap block harus sama persis. Detail transaksi
   aktor laptop lawan tampil `(terenkripsi ...)` karena private key-nya ada di laptop lawan.
7. Menu 5 di kedua laptop: `[CHAIN] VALID`.

### 9.5 Skenario lain

- **Node mati lalu hidup lagi.** Matikan satu laptop, tambang block di laptop lain (log: `[BROADCAST] ... GAGAL`).
  Nyalakan lagi: rantai dimuat dari `chain.json`, lalu otomatis diperpanjang dari peer
  (log: `Dimuat dari ...` dan `[SYNC] rantai diperpanjang dari N ke M block`).
- **Fork.** Jalankan kedua laptop TANPA saling terhubung (kosongkan peer atau putus lewat menu 7), tambang block
  yang berbeda di masing-masing, lalu sambungkan lagi dengan `POST /peers` dan `POST /nodes/resolve` (atau
  menu 6). Rantai sah yang lebih panjang menang; transaksi dari block yang terbuang kembali ke pool.
  Menu 8 menampilkan riwayat fork.
- **Menambah peer dari luar proses (`POST /peers`, HTTP):** lihat bagian 4.

### 9.6 Menguji topologi ini di satu komputer

`python uji_2laptop.py` menjalankan dua node (aktor dan peer persis seperti kedua berkas compose) dan
memeriksa pertukaran key, siklus penuh PRODUCED sampai INSTALLED, privasi isi transaksi, serta laptop yang
mati lalu hidup kembali. Ini tidak menggantikan uji di dua laptop fisik, yang tetap perlu Anda lakukan.
