# Dokumentasi Perubahan dan Fungsi Kode
**Proyek:** Blockchain Traceability Suku Cadang Kendaraan (Tugas 2 / Praktikum 2)

Dokumen ini berisi: (1) status pekerjaan, (2) daftar berkas, (3) perubahan sebelum dan sesudah, (4) fungsi tiap fungsi kode, (5) alur kerja, (6) pemetaan ke tugas dan checkpoint, (7) keterbatasan.

---

## 1. Status pekerjaan

### Sudah selesai dan terverifikasi
| Item | Bukti |
|---|---|
| Nama modul inti sudah benar | `uji_node.py` dan `uji_fork.py` berjalan |
| `ADD_PEER` dan penyimpanan `chain.json` | `uji_node.py` **20/20**, `uji_fork.py` **12/12** |
| PoW dengan `DIFFICULTY` string (revisi 3) | `uji_node.py` **20/20**, `uji_fork.py` **12/12**, `uji_fork_2v3.py` **16/16** dijalankan ulang setelah perubahan; `uji_fork_2v3.py` juga lulus 16/16 setelah `DIFFICULTY` diubah menjadi `"00000"` |
| Transport HTTP (revisi 4) | `uji_node.py` **26/26**, `uji_fork.py` **12/12**, `uji_fork_2v3.py` **20/20**; `curl` sungguhan: `POST /peers` dengan body dari soal dijawab 201, format salah 400, block cacat 409, path tidak dikenal 404 |
| Skrip eksperimen setelah perubahan | `demo_hash.py`, `eksperimen_difficulty.py --difficulty 0000 00000`, `eksperimen_tulis_ulang.py --difficulty 000 0000` berjalan; difficulty bukan string hex ditolak dengan pesan jelas |
| `cryptography` terpasang | `python -c "import cryptography"` mencetak versi |

### Sudah dibuat, tetapi BELUM dijalankan
| Item | Yang perlu dilakukan |
|---|---|
| `demo_hash.py` | `python demo_hash.py`, lalu tangkapan layar |
| `uji_fork_2v3.py` | `python uji_fork_2v3.py`, lalu tangkapan layar `A.log` |
| `eksperimen_tulis_ulang.py` | `python eksperimen_tulis_ulang.py --difficulty 0000 00000 --blocks 6 --runs 3` |
| Docker (`Dockerfile`, dua file compose) | `docker compose up -d --build` lalu `docker compose ps` |

### Belum dikerjakan (di luar kode)
| Item | Catatan |
|---|---|
| Konfirmasi ke dosen | Tanpa Genesis block (rantai berupa beberapa lineage; checkpoint 1). Transport sudah HTTP sejak revisi 4, jadi `POST /peers`, `/nodes/resolve`, dan status 409 sesuai soal |
| Tangkapan layar 8 checkpoint | Lihat bagian 6.2 |
| Diagram orisinal | Alur hashing, PoW, dan mekanisme pembanding (bobot 20%) |
| Mekanisme konsensus B (mis. PoS) | Belum dianalisis |
| Tabel perbandingan PoW vs pembanding | Bobot 35% |
| Laporan | Maksimal 10 halaman, minimal 5 referensi jurnal/whitepaper, APA Style |
| Pencantuman penggunaan AI | Wajib di akhir laporan |
| Jawaban tertulis Tugas 2 | Mengapa tiap node harus tahu semua node lain (tulis dengan kata sendiri) |
| Jadwal presentasi | Dokumen tugas menyebut pertemuan ke-6 dan ke-7 |

---

## 2. Daftar berkas

| Berkas | Status | Fungsi |
|---|---|---|
| `blockchain_core_traceability_suku_cadang_kendaraan.py` | **Diganti nama** (dulu `Blockchain_Traceability_suku_cadang.py`) | Inti blockchain |
| `node.py` | **Diubah** (revisi 3: tanpa `difficulty_bits`) | Lapisan jaringan; cek difficulty/retarget dinonaktifkan, PoW dicek terhadap `DIFFICULTY` |
| `uji_node.py` | **Diubah** | Uji otomatis: sinkron, serangan, restart; serangan "difficulty menyimpang" diganti "PoW lemah" (revisi 3) |
| `uji_fork.py` | Tetap | Uji otomatis skenario fork GANTI / SERI / PERTAHANKAN |
| `eksperimen_difficulty.py` | **Diubah** (revisi 3) | Waktu mining vs difficulty; argumen `--difficulty 0000 00000` (string), bukan `--bits` |
| `contoh_transaksi.json` | Tetap | Contoh input transaksi |
| `petunjuk.md` | **Diganti total** | Petunjuk pemakaian |
| `demo_hash.py` | **Baru** | Demo hashing dan avalanche effect (revisi 3: memakai `DIFFICULTY` string) |
| `uji_fork_2v3.py` | **Baru** | Fork 2 vs 3 block lewat `POST /peers` dan `POST /nodes/resolve` (HTTP) |
| `eksperimen_tulis_ulang.py` | **Baru** | Biaya menulis ulang riwayat |
| `Dockerfile`, `requirements.txt` | **Baru** | Image Docker |
| `docker_compose.yml`, `docker-compose_5_node.yml` | **Baru** | Orkestrasi 3 dan 5 node |
| `blockchain_core_traceability_suku_cadang_kendaraan.py` (revisi 2) | **Diubah** (fungsi `print_chain`) | Menu 2 kini menampilkan Nonce, Parent ID, dan Parent hash |
| `blockchain_core_traceability_suku_cadang_kendaraan.py` (revisi 3) | **Diubah** (bagian [5], [9], [10], [11]) | PoW memakai `DIFFICULTY = "0000"` (string) dan `mine_block` versi soal; kode PoW lama (per-bit + retarget) dijadikan komentar di bagian paling bawah (`[ARSIP]`). Lihat 3.4 |
| `docker-compose.laptop1.yml`, `docker-compose.laptop2.yml` | **Baru** | Satu node per laptop untuk dua laptop fisik |
| `.env.example` | **Baru** | Contoh `PEER_ADDR` (alamat laptop lawan) |
| `.gitignore`, `.dockerignore` | **Baru** | Mengecualikan `data/`, `data_*/`, `chain.json`, `.env` (berisi private key) dari repositori dan image |
| `PETUNJUK.md` | **Ditulis ulang** (revisi 2) | Petunjuk dua laptop dengan Docker, verifikasi, dan pemecahan masalah |

---

## 3. Perubahan: sebelum dan sesudah

### 3.1 `node.py` (10 perubahan)

Logika inti tidak diubah: validasi block, fork/longest-chain, penanganan key, dan sinkronisasi tetap sama. Perubahan revisi 3 di `node.py` hanya mencabut `difficulty_bits` dan retarget (lihat 3.4).

| No | Lokasi | Sebelum | Sesudah | Alasan |
|---|---|---|---|---|
| 1 | Docstring | Protokol 4 pesan; keterbatasan "chain tidak disimpan ke disk" | Ditambah `ADD_PEER`, poin perubahan 9 dan 10; keterbatasan diganti | Dokumentasi mengikuti kode |
| 2 | Bawah `KEY_LOCK` | Hanya `CHAIN_LOCK` dan `KEY_LOCK` | Ditambah `PEER_LOCK` | List `peers` bisa diubah dua thread sekaligus |
| 3 | Bawah `load_or_create_keys` | Tidak ada | Ditambah `simpan_chain`, `muat_chain`, `autosave` | Penyimpanan chain (Tugas 7) |
| 4 | `handle_message` | `handle_message(msg, chain_map)`; pesan `ADD_PEER` dijawab `ERROR` | Parameter `peers=None`; cabang `ADD_PEER` baru | Padanan `POST /peers` (Tugas 4) |
| 5 | `_handle_conn` | Tidak membawa `peers` | Parameter `peers=None`, diteruskan ke `handle_message` | Meneruskan list peers (revisi 4: diganti HTTP, lihat 3.5) |
| 6 | `terima_koneksi`, `start_server` | Tidak membawa `peers` | Parameter `peers=None` | Sama (revisi 4: diganti HTTP, lihat 3.5) |
| 7 | `broadcast_block` | `for ... in peers` | `for ... in list(peers)` | List bisa bertambah saat loop |
| 8 | `kelola_peer` | `append` dan `pop` tanpa lock; iterasi langsung | Dibungkus `PEER_LOCK`; iterasi `list(peers)` | Menu 6 dan `ADD_PEER` mengubah list yang sama |
| 9 | `run_node` | Server dijalankan tanpa `peers`; chain mulai kosong; loop peer langsung | Muat `chain.json` dan jalankan autosave sebelum server; `peers` dikirim ke thread server; loop pakai `list(peers)` | Menyambungkan kedua fitur ke alur utama |
| 10 | Akhir `run_node` | Hanya `except` mencetak "Node berhenti" | Ditambah blok `finally` yang memanggil `simpan_chain` | Chain tersimpan di setiap jalur keluar |

### 3.2 Perbandingan perilaku

| Aspek | Sebelum | Sesudah |
|---|---|---|
| Menambah peer | Hanya lewat `--peers` saat start atau menu 6 (interaktif) | Ditambah `POST /peers` (HTTP) dari luar proses, tanpa restart |
| Isi chain setelah node dimatikan | Hilang; dipulihkan dari peer | Disimpan di `<data-dir>/chain.json`, dimuat dan divalidasi ulang saat start |
| Jika semua node mati bersamaan | Isi chain hilang | Tetap ada di disk masing-masing |
| Log saat restart | `block diterima: N` (dari peer) | `Dimuat N block dari ...` (dari disk) |
| Log saat keluar | `Node berhenti.` | Ditambah `Chain disimpan ke ...` |
| Berkas Docker | Tidak ada | `Dockerfile`, `requirements.txt`, dua file compose |
| Demo hashing / avalanche | Tidak ada | `demo_hash.py` |
| Eksperimen fork 2 vs 3 | Tidak ada (uji_fork memakai 4 vs 3, lalu 5 vs 5) | `uji_fork_2v3.py` |
| Eksperimen keamanan terhadap penulisan ulang | Tidak ada (hanya waktu mining) | `eksperimen_tulis_ulang.py` |

### 3.3 Berkas lain yang berubah

- **`uji_node.py`**, bagian 7 (restart A): satu pengecekan diganti.
  - Sebelum: `cek("A memulihkan 3 block dari B", "block diterima: 3" in la)`
  - Sesudah: `cek("A memuat 3 block dari chain.json (disk)", "Dimuat 3 block" in la)`
  - Alasan: setelah ada penyimpanan JSON, A memuat block dari disk, bukan menariknya dari peer.
- **Nama berkas inti**: `Blockchain_Traceability_suku_cadang.py` menjadi `blockchain_core_traceability_suku_cadang_kendaraan.py`, supaya cocok dengan `import` di berkas lain (Linux/Docker peka huruf besar-kecil).
- **`petunjuk.md`**: perintah `docker run` lama (belum teruji, dan path volume relatifnya bermasalah) diganti dengan Docker Compose; ditambah `ADD_PEER`, `chain.json`, semua skrip eksperimen, dan daftar keterbatasan.


### 3.4 Perubahan PoW (revisi 3): difficulty berupa string, kode lama diarsipkan

**Latar belakang.** Soal Tugas 6 meminta `DIFFICULTY` dinaikkan dari `"0000"` menjadi `"00000"`. Fungsi `mine_block` dari soal dipakai sebagai kode aktif: difficulty berupa **string awalan hash**, bukan jumlah bit. Kode PoW lama (perbandingan integer 256-bit per bit, difficulty per block, retarget) **tidak dihapus**: seluruhnya dijadikan komentar di bagian **paling bawah** berkas inti, di antara penanda `[ARSIP]` dan `[AKHIR ARSIP]`, termasuk cara mengaktifkannya kembali.

| Aspek | Sebelum (arsip) | Sesudah (aktif) |
|---|---|---|
| Satuan difficulty | Jumlah bit (`DEFAULT_DIFFICULTY_BITS = 16`) | String awalan: `DIFFICULTY = "0000"` |
| Syarat lolos | `int(hash, 16) < 1 << (256 - bits)` | `hash.startswith(DIFFICULTY)` |
| Penyimpanan | `difficulty_bits` di tiap block (ikut header hash dan format jaringan) | Konstanta global `DIFFICULTY`; tidak ada di block |
| Penyesuaian | Retarget otomatis (`compute_next_difficulty`) | Tidak ada; difficulty tetap |
| Fungsi menambang | `mine_block(block, max_rounds=64)` mengembalikan `(hash, percobaan, detik)` | `mine_block(block, difficulty=DIFFICULTY, max_try=500000)` mengembalikan `(nonce, hash)` atau `(None, None)` |
| Nonce habis | Ditangani di dalam `mine_block` | Ditangani `mine_with_retry` (membungkus `mine_block`) |
| Tugas 6 | Ubah `DEFAULT_DIFFICULTY_BITS` 16 ke 20 | Ubah `DIFFICULTY` `"0000"` ke `"00000"` |

Satu karakter hex bernilai 4 bit, jadi tiap tambahan satu `"0"` membuat kerja rata-rata 16 kali lipat (`"0000"` sekitar 65.536 percobaan, `"00000"` sekitar 1.048.576).

**Penyesuaian terhadap fungsi di soal.** `mine_block` mengikuti bentuk fungsi soal (`DIFFICULTY`, `max_try=500000`, `startswith`, hasil `(nonce, hash)` atau `(None, None)`). Dua penyesuaian untuk proyek ini: block berupa objek `Block` (`block.nonce`, bukan `block["nonce"]`), dan `content_root` dihitung sekali di luar loop (hasil hash sama dengan `compute_hash(block)` dan kandidat diverifikasi ulang dengan `compute_hash`), sehingga kecepatan tetap sekitar 900 ribu hash per detik.

**Kenapa ada `mine_with_retry`.** Dengan `max_try=500000`, satu putaran untuk `"00000"` (rata-rata sekitar 1 juta percobaan) gagal sekitar 62% kali. `mine_with_retry` memanggil `mine_block` berulang; setiap putaran yang habis menaikkan `extra_nonce` dan memperbarui `timestamp` (perilaku yang sudah ada pada versi lama). Fungsi ini dipakai `add_block_to_chain` dan skrip eksperimen.

**Yang berubah di kode**

| Berkas | Perubahan |
|---|---|
| `blockchain_core_...py` | `DIFFICULTY`, `mine_block` (versi soal), `mine_with_retry`, `verify_pow(block, difficulty)` baru; `Block` dan `_header_hash` tanpa `difficulty_bits`; `add_block_to_chain(..., difficulty=DIFFICULTY)`; `is_chain_valid` tanpa cek retarget; kode lama menjadi komentar `[ARSIP]` di paling bawah |
| `node.py` | `difficulty_bits` dicabut dari `block_to_dict`, `block_from_dict`, `FIELD_BLOCK`, `check_block_format`, dan `validate_block` (baris lama ditandai komentar `arsip`); PoW diperiksa lewat `verify_pow` terhadap `DIFFICULTY` |
| `uji_node.py` | Serangan "block `difficulty_bits` menyimpang" diganti "block dengan PoW lemah (tidak diawali `DIFFICULTY`)", ditolak dengan alasan `PoW tidak valid` |
| `demo_hash.py` | Memakai `Block` tanpa `difficulty_bits` dan `mine_with_retry` |
| `eksperimen_difficulty.py`, `eksperimen_tulis_ulang.py` | Argumen `--bits` diganti `--difficulty` (string, mis. `0000 00000`); teori `2^bit` menjadi `16^n` |

**Dampak yang perlu dijelaskan saat presentasi**
- `DIFFICULTY` harus sama di **semua** node. Node dengan nilai berbeda menolak block node lain (`PoW tidak valid`).
- Format block di jaringan dan di `chain.json` berubah (tidak ada `difficulty_bits`, dan header hash berbeda). Berkas `chain.json` lama tidak kompatibel; hapus folder `data_*` lama sebelum menjalankan.
- Masalah retarget yang menurunkan difficulty di node hidup hilang karena retarget tidak ada lagi: difficulty tetap sehingga perbandingan `"0000"` dan `"00000"` adil.
- Tanpa difficulty per block, celah "block dengan difficulty lemah" tertutup dengan cara lain: PoW selalu dicek terhadap konstanta global.

**Cara mengaktifkan kembali kode lama:** ikuti petunjuk di blok `[ARSIP]` paling bawah berkas inti (kembalikan potongan komentar ke bagian [5], [9], [10], [11], lalu kembalikan baris `arsip` di `node.py` dan skrip uji/eksperimen).


### 3.5 Perubahan transport (revisi 4): TCP menjadi HTTP

**Latar belakang.** Soal memakai istilah HTTP (`POST /peers`, resolve fork, penolakan 409). Lapisan jaringan `node.py` diganti dari socket TCP (JSON satu baris per pesan) menjadi HTTP dengan body JSON. Logika blockchain tidak berubah. Kode TCP lama **tidak dihapus**: dijadikan komentar di bagian `[ARSIP]` paling bawah `node.py`, lengkap dengan petunjuk mengaktifkannya kembali.

| Aspek | Sebelum (arsip) | Sesudah (aktif) |
|---|---|---|
| Transport | Socket TCP, satu baris JSON per pesan | HTTP, body JSON, ada kode status |
| Server | `accept()` dan satu thread per koneksi (`_handle_conn`) | `ThreadingHTTPServer` dan `NodeHandler` |
| Client | `socket.create_connection` | `http.client.HTTPConnection` |
| Penentu jenis pesan | Field `"type"` di dalam pesan | Metode dan path HTTP (field `"type"` tetap ada di balasan) |
| Penolakan | `{"type":"REJECT"}` saja | `{"type":"REJECT"}` dengan status 409 (400 untuk format peer) |
| Dependensi | Pustaka standar | Pustaka standar (`http.server`, `http.client`); tidak ada paket baru |
| Alamat peer | `host:port` | `host:port` (sama) |

**Endpoint**

| Endpoint | Body | Balasan |
|---|---|---|
| `GET /chain` | - | 200 `CHAIN` berisi semua block |
| `POST /blocks` | `{"block": {...}}` | 200 `OK` / 409 `REJECT` / 400 `ERROR` |
| `GET /keys` | - | 200 `KEYS` |
| `POST /keys` | `{"author":..., "public_key_pem":...}` | 200 `OK` / 409 `REJECT` (key bentrok) |
| `POST /peers` | `{"peer": "host:port"}` | **201** peer baru / 200 sudah ada / 400 format salah (Tugas 4) |
| `GET /peers` | - | 200 `PEERS` (baru) |
| `POST /nodes/resolve` | - | 200 hasil sinkron dua arah dengan semua peer dan jumlah fork yang ditangani (Tugas 5, baru) |
| `GET /status` | - | 200 aktor lokal, jumlah block, peers, `DIFFICULTY` (baru) |

Kode status lain: 404 path tidak dikenal, 405 metode salah, 411 `Transfer-Encoding` tidak didukung, 413 body lebih dari 10 MB, 500 galat internal.

**Rancangan.**
- `handle_message(msg, chain_map, peers, owned_authors)` tidak tahu apa pun soal HTTP: dict masuk, dict keluar. `NodeHandler` memetakan (metode, path) ke tipe pesan, memanggil `handle_message`, lalu mengubah balasan menjadi kode status.
- `send_message` tetap berantarmuka dict-masuk dan dict-keluar, sehingga `sinkron_peer`, `broadcast_block`, dan seluruh skrip uji tidak perlu diubah.
- `RUTE_HTTP` adalah satu tabel yang dipakai server dan client, sehingga alamat endpoint tidak bisa berbeda di kedua sisi.
- Server memvalidasi permintaan: `Content-Length` dan batas 10 MB, body harus objek JSON, galat protokol dijawab JSON (bukan halaman HTML), dan galat internal tidak mematikan thread. Client menolak balasan yang bukan objek JSON dan melaporkan kegagalan protokol sebagai `OSError`, sehingga balasan peer yang rusak tidak lagi dapat mematikan node.

**Contoh (`curl`)**
```
curl -X POST localhost:9001/peers -H "Content-Type: application/json" -d '{"peer": "localhost:9002"}'
curl -X POST localhost:9001/nodes/resolve
curl localhost:9001/status
```

**Yang berubah di kode**

| Berkas | Perubahan |
|---|---|
| `node.py` | Impor `http.client`, `http.server`, `socketserver` (tanpa `socket`); `handle_message` mendapat parameter `owned_authors` dan tipe `GET_PEERS`, `GET_STATUS`, `RESOLVE`; `RUTE_HTTP`, `NodeHandler`, `NodeHTTPServer` baru; `buat_server(host, port, chain_map, peers, owned_authors)`, `terima_koneksi(srv)`, `start_server`, `send_message` ditulis ulang untuk HTTP; `run_node` membuat server HTTP; kode TCP lama menjadi komentar `[ARSIP]` |
| `uji_node.py` | Dua pengujian soket mentah diganti permintaan HTTP; ditambah pemeriksaan kode status 400, 404, 405, 409, 413, `GET /status`, `GET /chain` (20 menjadi 26 pemeriksaan) |
| `uji_fork_2v3.py` | Penghubungan peer lewat `POST /peers` (201, 200, 400), `GET /peers`, dan resolve lewat `POST /nodes/resolve` (20 pemeriksaan) |

**Dampak.** Node versi TCP dan versi HTTP tidak bisa saling berkomunikasi, jadi semua node harus memakai kode yang sama. Port, alamat peer, argumen CLI, dan berkas Docker Compose tidak berubah (HTTP berjalan di atas TCP pada port yang sama). Format block dan `chain.json` tidak berubah.

**Cara mengaktifkan kembali TCP:** ikuti petunjuk di blok `[ARSIP]` paling bawah `node.py`.

---

## 4. Fungsi tiap fungsi kode

### 4.1 `blockchain_core_traceability_suku_cadang_kendaraan.py`

**Bagian [1] Identitas aktor (RSA)**
| Fungsi / konstanta | Fungsi |
|---|---|
| `generate_keypair()` | Membuat pasangan kunci RSA 2048 bit |
| `AUTHOR_KEYS` | Kamus `author -> (private, public)`; hanya untuk aktor milik node ini |
| `PUBLIC_KEY_REGISTRY` | Kamus `author -> public key` untuk aktor milik node lain |
| `get_or_create_author(name)` | Mengambil keypair aktor; membuat bila belum ada |
| `register_public_key(author, pk)` | Mencatat public key aktor lain (dipanggil `node.py`) |
| `get_public_key(author)` | Mengambil public key dari `AUTHOR_KEYS` atau registry; `KeyError` bila tidak ada |
| `public_key_to_pem` / `public_key_from_pem` | Konversi public key dari/ke teks PEM untuk dikirim lewat jaringan |
| `ACTOR_ROLES`, `AUTHORIZED_ACTORS`, `ACTOR_ORDER` | Peran aktor, daftar aktor yang berwenang menulis (whitelist), urutan menu |

**Bagian [2] Enkripsi hibrida**
| Fungsi | Fungsi |
|---|---|
| `hybrid_encrypt(plaintext, public_key)` | Mengenkripsi data dengan AES-256-GCM (kunci acak), lalu mengenkripsi kunci AES dengan RSA-OAEP. Hasilnya "amplop" berisi `ciphertext`, `nonce`, `encrypted_key` |
| `hybrid_decrypt(envelope, private_key)` | Kebalikannya; hanya pemegang private key yang bisa membuka |

**Bagian [3] Tanda tangan digital**
| Fungsi | Fungsi |
|---|---|
| `sign_data(data, private_key)` | Menandatangani teks dengan RSA-PSS (SHA-256), hasil hex |
| `verify_data(data, signature, public_key)` | Memeriksa tanda tangan; `True` atau `False` |

**Bagian [4] Hash tingkat field dan Merkle**
| Fungsi | Fungsi |
|---|---|
| `hash_leaf(label, value)` | SHA-256 atas `label:value` (label mencegah dua field berbeda menghasilkan hash yang sama) |
| `build_merkle_root(leaves)` | Menggabungkan daun secara berpasangan sampai tersisa satu hash (Merkle root); jumlah ganjil menduplikasi daun terakhir |

**Bagian [5] dan [6] Block dan hash**
| Fungsi / kelas | Fungsi |
|---|---|
| `Block.__init__` | Membentuk block: timestamp, salt acak, nonce/extra_nonce; `part_id` dan `status` disimpan plaintext, sisa transaksi dienkripsi ke `envelope` |
| `compute_content_root(block)` | Merkle root dari 10 field tetap (id, author, part_id, status, 3 field envelope, parent_id, parent_hash, salt). **Selalu dihitung ulang**, tidak pernah di-cache, agar manipulasi field pasti mengubah hash |
| `_header_hash(content_root, timestamp, nonce, extra_nonce, bits)` | **Satu kali** SHA-256 atas header kecil (meniru header Bitcoin). Dipakai bersama oleh `compute_hash` dan `mine_block` |
| `compute_hash(block)` | Hash **resmi** block: `compute_content_root` lalu `_header_hash`. Dipakai untuk signature, PoW, dan `parent_hash` |

**Bagian [7] Tanda tangan block**
| Fungsi | Fungsi |
|---|---|
| `sign_block(block)` | Menandatangani `compute_hash(block)` dengan private key author |
| `verify_block_signature(block)` | Memeriksa tanda tangan memakai public key author |
| `read_block_transaction(block)` | Mendekripsi isi transaksi (hanya bila node memegang private key author) |

**Bagian [8] Aturan transaksi**
| Fungsi / konstanta | Fungsi |
|---|---|
| `ALLOWED_TRANSITIONS` | Urutan status: `PRODUCED` lalu `SHIPPED` lalu `RECEIVED` lalu `INSTALLED` |
| `validate_transaction(tx, parent)` | Memeriksa kelengkapan field, status dikenal, `part_id` sama dengan parent, dan urutan status benar |

**Bagian [9] Proof of Work**
| Fungsi / konstanta | Fungsi |
|---|---|
| `DIFFICULTY = "0000"` | Difficulty berupa string awalan hash; ubah menjadi `"00000"` untuk Tugas 6. Global, sama di semua node |
| `mine_block(block, difficulty=DIFFICULTY, max_try=500000)` | Fungsi dari soal: mencoba nonce 0..`max_try`-1 sampai `hash.startswith(difficulty)`; return `(nonce, hash)` atau `(None, None)` |
| `mine_with_retry(block, difficulty, max_try, max_rounds)` | Mengulang `mine_block`; tiap putaran habis, `extra_nonce` naik dan `timestamp` diperbarui. Return `(hash, total_percobaan, detik)` |
| *(arsip)* `difficulty_target`, `hash_meets_difficulty`, `compute_next_difficulty`, `mine_block` lama | Versi per-bit dan retarget; ada sebagai komentar `[ARSIP]` di paling bawah berkas |
| `mine_block(block)` | Mencari `nonce` yang memenuhi target. Ruang nonce 32-bit habis, `extra_nonce` naik dan timestamp diperbarui. Return `(hash, percobaan, detik)` |
| `verify_pow(block, difficulty=DIFFICULTY)` | Memeriksa `compute_hash(block)` diawali `difficulty` |

**Bagian [10] Gerbang penambahan block**
| Fungsi / kelas | Fungsi |
|---|---|
| `TransactionRejected`, `ConsensusRejected` | Exception penolakan transaksi atau konsensus |
| `add_block_to_chain(...)` | Urutan wajib: cek whitelist, cek id, cek parent, `validate_transaction`, bentuk kandidat, **mining wajib lolos**, baru tanda tangan, baru masuk `chain_map` |

**Bagian [11] Validasi rantai**
| Fungsi | Fungsi |
|---|---|
| `is_chain_valid(latest_block, chain_map)` | Menelusuri dari ujung ke akar; memeriksa signature, PoW (terhadap `DIFFICULTY`), dan `parent_hash` |
| `demo_cascading_tamper_detection(...)` | Demo: mengubah block tengah lalu menambal `parent_hash` tetap terdeteksi karena signature tiap block ikut rusak |

**Bagian [12] Mode dinamis dan CLI**
| Fungsi | Fungsi |
|---|---|
| `new_transaction(...)` | Membuat dict transaksi |
| `next_block_id(chain_map)` | Id berikutnya (max + 1) |
| `add_transaction(...)` | Membuat transaksi lalu memanggil `add_block_to_chain` |
| `load_transactions_from_json(...)` | Memuat banyak transaksi dari berkas JSON |
| `print_chain`, `pilih_dari_daftar`, `run_cli` | Tampilan rantai, menu bernomor, dan CLI mandiri (tanpa jaringan) |

### 4.2 `node.py`

**Serialisasi dan validasi block**
| Fungsi | Fungsi |
|---|---|
| `block_to_dict(b)` | Block menjadi dict (untuk jaringan dan JSON) |
| `block_from_dict(d)` | Dict menjadi Block **tanpa** memanggil `__init__` (agar amplop tidak dienkripsi ulang) |
| `_int`, `_hex` | Pembantu pengecekan tipe integer (bukan bool) dan string hex |
| `check_block_format(d)` | Memeriksa bentuk dan rentang semua field (tanpa `difficulty_bits` sejak revisi 3); return pesan error atau `None` |
| `validate_block(blk, chain_map)` | **Satu-satunya** validasi penuh: author berwenang, parent dikenal, urutan status, `parent_hash`, PoW terhadap `DIFFICULTY`, signature |
| `terima_block(d, chain_map)` | Format, validasi, lalu masuk chain. Kode: `BARU`, `ADA`, `TOLAK`, `FORK` |

**Fork dan longest-chain**
| Fungsi | Fungsi |
|---|---|
| `label_block(b)` | Teks ringkas `id (author/status/part_id)` |
| `panjang_chain(chain_map)` | Panjang = jumlah block valid |
| `_lineage`, `chain_utama` | Menyusun jalur akar ke ujung per lineage; memilih jalur terpanjang sebagai chain utama |
| `bangun_kandidat(blocks)` | Membangun buku besar dari nol dengan validasi penuh tiap block. Dipakai juga oleh `muat_chain` |
| `resolve_fork(chain_map, blocks)` | Membandingkan panjang lokal vs peer: peer lebih panjang `GANTI` (block lokal yang kalah menjadi orphan), lokal lebih panjang `PERTAHANKAN`, sama `SERI` (lokal dipertahankan) |
| `cetak_fork`, `tampilkan_fork` | Keluaran `[FORK]` dan tampilan chain utama beserta riwayat resolusi |

**Public key dan penyimpanan**
| Fungsi | Fungsi |
|---|---|
| `daftarkan_key(author, pem)` | Mendaftarkan public key aktor lain; key yang sudah ada **tidak boleh ditimpa** dengan key berbeda |
| `semua_key_publik()` | Semua public key yang dikenal node |
| `load_or_create_keys(author, data_dir)` | Memuat private key dari berkas, atau membuat dan menyimpannya |
| **`simpan_chain(chain_map, path)`** (baru) | Menulis chain dan public key ke JSON secara atomik (`.tmp` lalu `os.replace`) |
| **`muat_chain(chain_map, path)`** (baru) | Membaca JSON, mendaftarkan key, lalu memvalidasi ulang tiap block lewat `bangun_kandidat` |
| **`autosave(chain_map, path)`** (baru) | Thread latar: tiap 2 detik menyimpan bila chain berubah |

**Server**
| Fungsi | Fungsi |
|---|---|
| `handle_message(msg, chain_map, peers, owned_authors)` | Logika satu pesan (dict masuk, dict balasan), **tidak tahu soal HTTP**: `REGISTER_AUTHOR`, `GET_KEYS`, `GET_CHAIN`, `NEW_BLOCK`, `ADD_PEER`, dan (revisi 4) `GET_PEERS`, `GET_STATUS`, `RESOLVE` |
| `RUTE_HTTP` | Satu tabel tipe pesan ke (metode, path), dipakai server **dan** client |
| `NodeHandler` | `BaseHTTPRequestHandler`: memetakan (metode, path) ke tipe pesan, membaca dan memvalidasi body JSON, memanggil `handle_message`, menerjemahkan balasan ke kode status (`_status_http`); galat protokol juga dijawab JSON |
| `NodeHTTPServer`, `buat_server`, `terima_koneksi`, `start_server` | `ThreadingHTTPServer` (satu thread per permintaan); membawa `chain_map`, `peers`, `owned_authors` |
| *(arsip)* `_recv_line`, `_handle_conn`, versi TCP dari `buat_server`/`terima_koneksi`/`start_server`/`send_message` | Ada sebagai komentar `[ARSIP]` di paling bawah `node.py` |

**Client dan sinkronisasi**
| Fungsi | Fungsi |
|---|---|
| `send_message(host, port, msg, timeout)` | Client HTTP (`http.client`): menerjemahkan tipe pesan ke (metode, path) lewat `RUTE_HTTP`, mengembalikan balasan sebagai dict; balasan bukan objek JSON menjadi `ERROR`, kegagalan protokol menjadi `OSError` |
| `kirim_keys_ke_peer`, `tarik_keys` | Tukar public key dua arah |
| `_konflik_id(d, chain_map)` | `True` bila id sudah ada di lokal dengan hash berbeda (tanda fork) |
| `sync_chain_from_peer` | Menarik chain peer; tanpa konflik, tiap block divalidasi lalu digabung; ada konflik, `resolve_fork` |
| `dorong_chain_ke_peer` | Mengirim semua block lokal ke peer |
| `sinkron_peer` | Sinkron dua arah: kirim key, tarik key, tarik chain, dorong chain |
| `broadcast_block` | Menyiarkan block baru ke semua peer; bila ditolak, sinkron dua arah |

**CLI**
| Fungsi | Fungsi |
|---|---|
| `parse_satu_peer`, `parse_peers` | Memvalidasi format `host:port` |
| `kelola_peer` | Menu 6: tambah atau hapus peer (hapus = simulasi partisi jaringan) |
| `tampilkan_validasi` | Menu 4: validasi tiap ujung rantai |
| `run_node` | Fungsi utama: memuat key dan chain, menjalankan server dan autosave, sinkron awal, menu interaktif 1 sampai 7, simpan saat keluar |

### 4.3 Skrip eksperimen dan uji

| Berkas | Fungsi |
|---|---|
| `demo_hash.py` | Bagian 1: SHA-256 (deterministik, panjang tetap, avalanche effect, rata-rata di semua posisi karakter). Bagian 2: data domain mengubah hash, PoW, dan signature. Bagian 3: data sama tetapi hash berbeda karena salt dan enkripsi acak |
| `eksperimen_difficulty.py` | Mengukur percobaan dan waktu mining per difficulty (string) dibandingkan teori `16^n` |
| `eksperimen_tulis_ulang.py` | Membangun rantai N block, mengubah block k, menambang ulang block k sampai N, lalu membandingkan biaya dengan `(N-k+1) x 2^bit` |
| `uji_node.py` | 26 pemeriksaan: sinkron, penolakan block menyimpang/kembar/cacat, key tidak bisa ditimpa, peer jahat, restart, dan kode status HTTP (400, 404, 405, 409, 413, `GET /status`, `GET /chain`) |
| `uji_fork.py` | 12 pemeriksaan: GANTI, SERI, PERTAHANKAN, dan kedua node akhirnya identik |
| `uji_fork_2v3.py` | 20 pemeriksaan: dua node tanpa peer, A 2 block vs B 3 block, `POST /peers` (201/200/400), `GET /peers`, `POST /nodes/resolve`, orphan, identik |

---

## 5. Alur kerja

### 5.1 Menambah block (menu 1)
1. Node sinkron dulu dengan semua peer (agar id tidak bentrok).
2. `add_transaction` memanggil `add_block_to_chain`: cek whitelist, validasi urutan status, bentuk kandidat.
3. `mine_with_retry` memanggil `mine_block` sampai hash diawali `DIFFICULTY` (PoW).
4. Setelah PoW lolos, block ditandatangani dan masuk `chain_map`.
5. `broadcast_block` mengirim `NEW_BLOCK` ke semua peer. Peer menjalankan `terima_block` lalu `validate_block`.
6. `autosave` menyimpan ke `chain.json` dalam sekitar 2 detik.

### 5.2 Penyelesaian fork
1. Dua node membuat block dengan id sama dan isi berbeda (misalnya setelah partisi).
2. Saat sinkron, `_konflik_id` mendeteksi id sama dengan hash berbeda.
3. `resolve_fork` membangun buku besar peer dari nol (`bangun_kandidat`) dan membandingkan panjang.
4. Yang lebih panjang menang. Pihak yang kalah mengganti chain-nya, dan block lokal yang tidak ada di chain baru dicatat sebagai orphan.
5. Panjang sama berarti `SERI`: tetap pakai chain lokal sampai salah satu menambah block.

### 5.3 Mengapa penulisan ulang riwayat mahal
Mengubah block k mengubah hash-nya. Block k+1 menyimpan `parent_hash` itu, sehingga ikut berubah, dan seterusnya sampai ujung. Penyerang harus menambang ulang N-k+1 block, masing-masing sekitar `2^bit` percobaan. Menambah 1 bit melipatduakan biaya.

---

## 6. Pemetaan ke tugas dan checkpoint

### 6.1 Tugas Praktikum 2
| No | Tugas | Status | Berkas |
|---|---|---|---|
| 1 | 8 checkpoint dan penjelasan baris kode | Sebagian (lihat 6.2) | `node.py`, compose |
| 2 | 3 menjadi 5 node + penjelasan | Kode dan compose siap; **penjelasan tertulis belum** | `docker-compose_5_node.yml`, `--peers` |
| 3 | Data domain memengaruhi hash | Skrip siap, belum dijalankan | `demo_hash.py` |
| 4 | Endpoint `POST /peers` | Selesai (HTTP sungguhan, body `{"peer": "localhost:5002"}` dijawab 201); terbukti di uji dan dengan `curl` | `node.py` |
| 5 | Fork 2 vs 3 block | Skrip siap dan berjalan (20/20); resolve lewat `POST /nodes/resolve`; tangkapan layar belum | `uji_fork_2v3.py` |
| 6 | Difficulty `0000` ke `00000` | Cukup ubah `DIFFICULTY`; waktu mining dan keamanan: skrip siap dan berjalan, tangkapan layar belum | `eksperimen_difficulty.py`, `eksperimen_tulis_ulang.py` |
| 7 | Simpan chain ke JSON | Selesai, terbukti di uji restart | `node.py` |
| 8 | Repositori | Berkas lengkap; tinggal diunggah | semua |

### 6.2 Padanan 8 checkpoint (transport HTTP; ketiadaan Genesis block **perlu disetujui dosen**)
| No | Checkpoint modul | Padanan di prototipe ini |
|---|---|---|
| 1 | Tiga node, Genesis identik | Tiga node berjalan (`NODE aktif ...`). **Tidak ada Genesis block** (rantai berupa beberapa lineage) |
| 2 | Menambang di node-1, dua baris kirim ke peer | Menu 1 di node1: log `berhasil ditambang lokal`, lalu dua baris `Kirim block 1 ke ...` |
| 3 | Node-2 dan node-3 berisi rantai sama | Menu 2 di node2 dan node3: Nonce, Parent ID, Parent hash, dan Hash tiap block sama (ditampilkan sejak revisi 2) |
| 4 | Node-3 dimatikan, node-1 menambang | Log node1: `Gagal kirim block ... ke node3:9003` |
| 5 | Node-3 hidup lagi lalu resolve | Menu 3 di node3: block yang tertinggal diterima; panjang menjadi 3 |
| 6 | Block palsu ditolak HTTP 409 | `POST /blocks` berisi block palsu dijawab **HTTP 409** dengan `{"type":"REJECT","reason":...}`; contoh pada `uji_node.py` bagian 5 |
| 7 | `docker compose up`, tiga container running | `docker compose ps` |
| 8 | Mining lewat container | `docker attach node1`, lalu menu 1 (interaktif, bukan satu perintah non-interaktif) |

---

## 7. Keterbatasan prototipe (bahan bab Pembahasan)

- Chain berupa `dict {id: Block}`, bukan pohon; cabang yang kalah langsung dibuang.
- Panjang chain = jumlah block valid, bukan *cumulative work* seperti Bitcoin.
- `DIFFICULTY` adalah konstanta global yang harus sama di seluruh node; mengubahnya di satu node membuat block node lain ditolak. Tidak ada retarget otomatis (kode lamanya diarsipkan).
- Granularitas difficulty per karakter hex (kerja x16 per langkah); tidak ada difficulty antara. Versi per-bit tersimpan di arsip.
- Default `max_try=500000` lebih kecil dari rata-rata percobaan untuk `"00000"`, sehingga satu putaran sering habis; ditangani `mine_with_retry`.
- Tidak ada Genesis block.
- Tidak ada peer discovery atau gossip: node hanya mengenal alamat di daftar peer-nya. Karena itu tiap node harus diberi alamat semua node lain; node yang tidak dikenal tidak menerima block, sehingga rantainya tertinggal atau menyimpang.
- Block orphan hanya dilaporkan; tidak ada mempool yang mengembalikan transaksinya.
- Validasi memeriksa urutan status dan daftar aktor berwenang, bukan pemetaan aktor ke status.
- Public key memakai model "pertama kali terlihat dipercaya".
- `chain.json` tidak dienkripsi; autosave tiap sekitar 2 detik, sehingga mematikan paksa proses dapat kehilangan perubahan terakhir.
- Tidak ada finality probabilistik, insentif ekonomi, maupun jaringan terbuka (hanya PoW tertutup dengan aktor terdaftar).
- Endpoint HTTP tanpa autentikasi dan tanpa TLS: siapa pun yang menjangkau port node dapat memanggil `POST /peers` atau `POST /nodes/resolve`. Server memakai HTTP/1.0 (satu permintaan per koneksi). `POST /nodes/resolve` bersifat sinkron, sehingga klien perlu timeout yang cukup panjang.

---

## 8. Docker untuk dua laptop (revisi 2)

**Mengapa compose terpisah.** Compose 3 dan 5 node memakai nama layanan sebagai alamat (`node2:9002`), yang hanya dikenal di dalam satu mesin Docker. Pada dua laptop fisik, peer harus berupa `IP-laptop-lawan:port`, sehingga tiap laptop menjalankan compose-nya sendiri.

| Berkas | Aktor | Port | Peer |
|---|---|---|---|
| `docker-compose.laptop1.yml` | Produsen, Distributor | 9001 | `PEER_ADDR` di `.env` (alamat laptop 2) |
| `docker-compose.laptop2.yml` | Dealer, Bengkel | 9002 | `PEER_ADDR` di `.env` (alamat laptop 1) |

- `PEER_ADDR` dibaca dari `.env` (salin dari `.env.example`), jadi IP tidak tertanam di kode. Bentuk `${PEER_ADDR:?...}` membuat compose berhenti dengan pesan jelas bila nilainya kosong.
- `stdin_open` dan `tty` tetap wajib karena node memakai menu interaktif; menu dipakai lewat `docker attach`.
- Volume `./data/laptopN:/app/data_<port>` menyimpan key dan `chain.json`, sehingga node yang di-restart memakai key yang sama dan memulihkan chain.
- Satu aktor hanya boleh dipegang satu node, maka pembagian aktor pada kedua berkas tidak boleh saling tumpang tindih.

**Sudah diverifikasi.** Argumen `command` diambil langsung dari kedua berkas compose (dengan `PEER_ADDR` diganti alamat lokal) lalu dijalankan sebagai dua proses terpisah, dengan laptop 1 menyala lebih dulu: block dari satu laptop diterima laptop lain, Nonce/Parent hash/Hash identik di kedua sisi, validasi chain `valid=True`, dan `chain.json` serta key dipulihkan setelah restart (10 dari 10 pemeriksaan). Regresi `uji_node.py` (20/20), `uji_fork.py` (12/12), dan `uji_fork_2v3.py` (16/16) tetap lulus.

**Belum diverifikasi.** `docker compose up` yang sebenarnya (Docker tidak tersedia di lingkungan pengujian), jaringan antar dua laptop fisik, dan aturan firewall. Bagian itu harus dicoba langsung mengikuti `PETUNJUK.md`.

Keterbatasan tambahan: setiap berkas compose hanya menerima satu peer lewat `PEER_ADDR`; untuk lebih dari dua laptop, tambahkan alamat peer lain pada `command`.
