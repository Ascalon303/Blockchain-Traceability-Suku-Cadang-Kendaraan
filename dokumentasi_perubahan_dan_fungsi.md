# Dokumentasi revisi 5 — penyesuaian ke ketentuan C.2 "Fitur Wajib"

Dokumen ini menggantikan dokumentasi revisi 4 (arsipnya ada di `arsip_versi_lama/`). Revisi 5
merombak inti dan node supaya mengikuti tabel C.2.

## 1. Status ketentuan C.2

| Komponen | Ketentuan | Implementasi | Bukti uji |
|---|---|---|---|
| Struktur block | index, timestamp, daftar transaksi, previous hash, nonce, hash | `class Block`: `index`, `timestamp`, `transactions` (list), `previous_hash`, `nonce`, `hash` (+ `merkle_root`, `extra_nonce`). Block genesis deterministik (`make_genesis`) | `uji_core.py` bagian 1 dan 4 |
| Transaksi bertanda tangan | Ditandatangani private key pengirim, diverifikasi node sebelum diterima | `make_transaction` menandatangani `tx_id` (RSA-PSS); `verify_transaction` memeriksa `tx_id` dan tanda tangan; `add_to_pool` dan `validate_block` memverifikasi sebelum menerima | `uji_core.py` bagian 2-3, `uji_node.py` bagian 2, `uji_3node.py` bagian 3 |
| Transaction pool | Antrean pending; block dibentuk dari isi pool; pool dikosongkan setelah block diterima rantai | `Ledger.pool`, `add_to_pool`, `build_candidate`, `mine_pending`, `_prune_pool` | `uji_core.py` bagian 3-4, `uji_3node.py` bagian 2, 4, 5 |
| Proof of work | Cari nonce terhadap difficulty target; nonce disimpan di block | `DIFFICULTY` (string), `mine_block`, `mine_with_retry`, `verify_pow`; `block.nonce` tersimpan | `uji_core.py` bagian 4 |
| Validasi chain | Periksa hash dan previous hash seluruh rantai; deteksi data dimanipulasi | `validate_block`, `is_chain_valid`, `demo_manipulasi` (5 skenario), menu 5 dan 9 | `uji_core.py` bagian 5, `uji_node.py` bagian 3 |
| Jaringan multi-node | Minimal 3 node saling broadcast block, longest-chain rule, tolak block tidak sah | HTTP (`node.py`): `broadcast_block`, `broadcast_transaction`, `sinkron_peer`; `Ledger.receive_block`, `Ledger.consider_chain` | `uji_3node.py` (3 node), `uji_4node.py` (4 node, satu per aktor), `uji_2laptop.py` (topologi dua laptop), `uji_fork.py`, `uji_fork_2v3.py` |
| Log console | Setiap checkpoint tercetak jelas | Tag `[NODE] [TX] [POOL] [MINING] [BROADCAST] [BLOCK] [SYNC] [FORK] [CHAIN] [KEY] [MANIPULASI]` | `uji_3node.py` bagian 8 memeriksa isi log |

Catatan: daftar checkpoint bagian D belum tersedia saat dokumen ini ditulis. Setelah daftarnya ada,
pencocokan satu per satu dengan keluaran console perlu dilakukan.

## 2. Perubahan desain dari revisi 4

| Aspek | Revisi 4 | Revisi 5 |
|---|---|---|
| Bentuk rantai | Banyak lineage per part (`parent_id`, mirip DAG), tanpa genesis | **Rantai linear** dengan block genesis; satu `previous_hash` |
| Isi block | Satu transaksi terenkripsi | **Daftar transaksi** (hingga `MAX_TX_PER_BLOCK`, default 5) |
| Yang ditandatangani | Block (author menandatangani hash block) | **Transaksi** (pengirim menandatangani `tx_id`); block cukup memenuhi PoW |
| Hash block | Dihitung, tidak disimpan | **Disimpan** di block dan diverifikasi ulang dari isi |
| Transaction pool | Tidak ada (menu 1 langsung menambang) | **Ada**, disiarkan ke peer, dikosongkan setelah block diterima |
| Aturan status | Terhadap block induk | Terhadap **status terakhir** `part_id` di rantai (dan pool) |
| Fork | Per lineage, `id` global bentrok | Longest-chain pada rantai linear; transaksi block orphan **kembali ke pool** |
| Penambang | Author block | **Node mana pun** |
| Data domain | Seluruhnya di envelope terenkripsi | `part_id` dan `status` terbuka (dibutuhkan aturan status); detail lain di `envelope` terenkripsi |

Yang dipertahankan: enkripsi hibrida (AES-GCM + RSA-OAEP), tanda tangan RSA-PSS, Merkle root,
`DIFFICULTY` string dan `mine_block` versi tugas 6, transport HTTP, penyimpanan atomik, `POST /peers`.
Kode PoW per-bit lama tetap ada sebagai komentar `[ARSIP]` di bagian bawah file inti.

## 3. Struktur data

**Transaksi**

| Field | Isi |
|---|---|
| `sender` | aktor pengirim (pemegang private key) |
| `timestamp` | waktu dibuat |
| `part_id`, `status` | id suku cadang dan status baru (terbuka) |
| `envelope` | `part_name`, `origin`, `destination`, `vehicle_id` terenkripsi dengan public key pengirim |
| `tx_id` | SHA-256 dari seluruh field di atas (kanonik JSON) |
| `signature` | tanda tangan RSA-PSS pengirim atas `tx_id` |

**Block**

| Field | Isi |
|---|---|
| `index` | nomor urut (genesis = 0) |
| `timestamp` | waktu block dibuat |
| `transactions` | daftar transaksi |
| `previous_hash` | hash block sebelumnya (genesis: 64 nol) |
| `merkle_root` | Merkle root dari `hash(tx_hash + signature)` tiap transaksi |
| `nonce`, `extra_nonce` | hasil pencarian PoW |
| `hash` | `SHA-256(index, timestamp, previous_hash, merkle_root, nonce, extra_nonce)` |

**Aturan status:** `PRODUCED` hanya boleh sekali per `part_id`; `SHIPPED` hanya setelah `PRODUCED`;
`RECEIVED` setelah `SHIPPED`; `INSTALLED` setelah `RECEIVED`. Pengirim harus aktor berwenang
(Produsen, Distributor, Dealer, Bengkel); tidak ada pemetaan aktor ke status.

## 4. Alur kerja

1. **Transaksi:** pengirim membuat transaksi, node menandatangani lalu `add_to_pool` memverifikasi
   (bentuk, `tx_id`, tanda tangan, duplikat, aturan status). Transaksi sah masuk pool dan disiarkan ke
   semua peer (`POST /transactions`).
2. **Mining:** node mana pun memanggil `mine_pending`. `build_candidate` memilih transaksi pool yang
   valid berurutan, `mine_with_retry` mencari nonce di luar lock, lalu block ditambahkan ke rantai
   lokal dan `_prune_pool` membuang transaksi yang sudah masuk block.
3. **Siaran:** block dikirim ke semua peer (`POST /blocks`). Peer menjalankan `receive_block`.
4. **Validasi di penerima:** hash tersimpan harus cocok dengan isi, lalu `index`, `previous_hash`,
   Merkle root, PoW, dan tanda tangan serta aturan tiap transaksi. Gagal berarti ditolak (HTTP 409).
5. **Fork:** bila block tidak menyambung ke ujung rantai, penerima menjawab `perlu_sinkron` dan pengirim
   menjalankan `sinkron_peer`: tukar public key, `consider_chain` (longest-chain rule) pada rantai peer,
   dorong rantai sendiri (`POST /chain`), dan tukar isi pool.

**Longest-chain rule (`consider_chain`):** rantai peer harus sah penuh (`is_chain_valid`), lalu:
`SAMA`; `PERTAHANKAN` (peer lebih pendek atau awalan rantai kita); `DIPERPANJANG` (rantai kita awalan
rantai peer); `GANTI` (bercabang dan peer **lebih panjang**: block lokal setelah titik cabang menjadi
orphan, transaksinya dikembalikan ke pool bila masih valid); `SERI` (bercabang dan panjang sama:
rantai lokal dipertahankan sampai ada block berikutnya).

## 5. Endpoint HTTP

| Endpoint | Fungsi | Status utama |
|---|---|---|
| `GET /chain`, `POST /chain` | rantai lengkap; usul rantai (diterima bila sah dan lebih panjang) | 200 / 409 |
| `POST /blocks` | terima satu block | 200 / 409 (`perlu_sinkron` bila tidak menyambung) |
| `GET /transactions` | isi pool | 200 |
| `POST /transactions` | masukkan transaksi bertanda tangan | 201 baru / 200 duplikat / 409 |
| `POST /transactions/create` | buat dan tandatangani dengan key aktor lokal (kemudahan lab) | 201 / 409 |
| `POST /mine` | tambang dari pool lalu siarkan | 201 / 409 (pool kosong) |
| `GET /keys`, `POST /keys` | tukar public key | 200 / 409 bila bentrok |
| `GET /peers`, `POST /peers` | daftar peer; tambah peer (Tugas 4) | 200 / 201 / 400 |
| `POST /nodes/resolve` | sinkron dan resolusi fork dengan semua peer (Tugas 5) | 200 |
| `GET /status` | aktor lokal, jumlah block, ujung hash, pool, peers, difficulty, `chain_valid` | 200 |

Kode lain: 400 permintaan cacat, 404 path tidak dikenal, 405 metode salah, 411/413 ukuran body, 500 galat internal.

## 6. Peta fungsi

**Inti (`blockchain_core_traceability_suku_cadang_kendaraan.py`)**

| Bagian | Fungsi dan kelas |
|---|---|
| Kunci, enkripsi, tanda tangan | `get_or_create_author`, `get_public_key`, `hybrid_encrypt/decrypt`, `sign_data`, `verify_data` |
| Transaksi | `check_tx_format`, `tx_hash`, `make_transaction`, `verify_transaction`, `validate_transaction`, `ChainState` |
| Block | `Block`, `compute_merkle_root`, `compute_hash`, `make_genesis`, `block_to_dict`, `block_from_dict`, `check_block_format` |
| PoW | `DIFFICULTY`, `mine_block`, `mine_with_retry`, `verify_pow` |
| Validasi | `validate_block`, `is_chain_valid`, `demo_manipulasi` |
| Ledger | `Ledger`: `add_to_pool`, `build_candidate`, `mine_pending`, `receive_block`, `consider_chain`, `validate`, `load_state` |
| Tampilan | `print_chain`, `run_cli` (mode mandiri) |

**Node (`node.py`)**

| Bagian | Fungsi dan kelas |
|---|---|
| Key jaringan | `daftarkan_key`, `semua_key_publik`, `load_or_create_keys`, `kirim_keys_ke_peer`, `tarik_keys` |
| Penyimpanan | `simpan_state`, `muat_state`, `autosave` (chain, pool, public key; atomik; divalidasi ulang saat dimuat) |
| HTTP | `RUTE_HTTP`, `NodeHandler`, `NodeHTTPServer`, `send_message` |
| Jaringan | `broadcast_transaction`, `broadcast_block`, `sinkron_peer`, `mine_and_broadcast` |
| Logika pesan | `handle_message` (bebas transport) |
| Menu | `run_node`, `buat_transaksi_menu`, `tampilkan_pool`, `tampilkan_fork`, `kelola_peer` |

## 7. Pengujian

| Skrip | Pemeriksaan | Hasil |
|---|---|---|
| `uji_core.py` | struktur, transaksi, pool, PoW, validasi, manipulasi, fork, penyimpanan | 54/54 |
| `uji_node.py` | dua node, serangan, kode status HTTP, restart, berkas dimanipulasi | 30/30 |
| `uji_3node.py` | tiga node: broadcast transaksi dan block, pool, penolakan, log | 36/36 |
| `uji_4node.py` | empat node, satu per aktor berwenang: siklus PRODUCED, SHIPPED, RECEIVED, INSTALLED, tiap transaksi ditandatangani di node aktornya dan ditambang node lain | 33/33 |
| `uji_2laptop.py` | topologi dua laptop (aktor dan peer seperti `docker-compose.laptop1/2.yml`): pertukaran key, siklus penuh, privasi isi transaksi, laptop mati lalu hidup | 23/23 |
| `uji_fork.py` | fork panjang sama lalu diselesaikan block berikutnya | 10/10 |
| `uji_fork_2v3.py` | Tugas 5: 2 vs 3 block, `POST /peers`, resolve, orphan kembali ke pool | 23/23 |

Dua kelemahan ditemukan dan diperbaiki saat pengujian jaringan: transaksi yang isinya diubah tetapi
memakai `tx_id` yang sudah ada dianggap "duplikat", dan block yang isinya diubah tetapi mengklaim hash
block yang sudah ada dianggap "sudah ada". Keduanya karena pengecekan duplikat dilakukan sebelum
verifikasi integritas; kini integritas diperiksa lebih dulu (kasusnya ada di `uji_core.py`).

## 8. Dampak ke tugas praktikum 2-7

| Tugas | Status |
|---|---|
| 2 (3 menjadi 5 node) | `docker_compose.yml` kini 4 node (satu per aktor: Produsen, Distributor, Dealer, Bengkel); `docker-compose_5_node.yml` = keempat aktor + satu pengamat. Tiap node tetap harus mengenal semua node lain |
| Dua laptop (Docker, HTTP) | `docker-compose.laptop1.yml`, `docker-compose.laptop2.yml`, dan `.env.example` dipertahankan tanpa perubahan (laptop 1 = Produsen + Distributor, laptop 2 = Dealer + Bengkel, peer lewat `PEER_ADDR`). Petunjuk lengkap di `PETUNJUK.md` bagian 9; topologinya diuji lokal oleh `uji_2laptop.py` |
| 3 (data domain mempengaruhi hash) | `demo_hash.py` diperbarui: transaksi masuk Merkle root, ubah satu field mengubah hash dan merusak tanda tangan |
| 4 (`POST /peers`) | tetap, HTTP |
| 5 (fork 2 vs 3) | `uji_fork_2v3.py`; kini juga menunjukkan nasib block orphan: transaksinya kembali ke pool dan ditambang ulang |
| 6 (difficulty) | `DIFFICULTY` string; `eksperimen_difficulty.py` dan `eksperimen_tulis_ulang.py` diperbarui |
| 7 (penyimpanan JSON) | `chain.json` kini memuat rantai, pool, dan public key (versi 2); berkas format lama dicadangkan otomatis |

## 9. Keterbatasan

- Siaran dilakukan langsung oleh pembuat ke semua peer (full mesh); tidak ada gossip multi-hop.
- Endpoint HTTP tanpa autentikasi dan TLS; `POST /transactions/create` dan `POST /mine` dapat dipanggil siapa pun yang menjangkau port (cukup untuk jaringan lab).
- `DIFFICULTY` harus sama di semua node; tidak ada penyesuaian otomatis.
- Longest-chain memakai jumlah block; panjang sama berarti SERI sampai ada block berikutnya.
- Model kepercayaan public key first-come: key yang sudah terdaftar tidak bisa ditimpa, tetapi node yang pertama mendaftarkan key untuk sebuah aktor diterima.
- Private key tidak dienkripsi di disk.
- Satu `part_id` hanya bisa mengikuti satu urutan status; tidak ada transaksi pembatalan.
- `penjelasan_node_py.md` (penjelasan baris per baris) belum dibuat ulang untuk `node.py` revisi 5; versi revisi 4 ada di `arsip_versi_lama/`.
