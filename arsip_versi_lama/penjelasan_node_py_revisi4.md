# Penjelasan `node.py` — kode asli + penjelasan baris per baris


File ini menampilkan kode asli `node.py` (dengan nomor baris) dipotong per fungsi/bagian, dan di bawah tiap potongan ada penjelasan alur serta sintaksnya. Versi ini menjelaskan `node.py` **setelah** dua perubahan besar: transport jaringan diganti dari TCP ke **HTTP**, dan PoW memakai `DIFFICULTY` berupa string.

## Gambaran alur program

```
python node.py --port 9000 --authors Produsen Distributor --peers 192.168.1.5:9001
      │
      ▼
blok __main__ (baris 1180)  → baca argumen CLI, validasi nama aktor
      │
      ▼
run_node() (baris 1072)
  1. load_or_create_keys   → muat/buat private key tiap aktor lokal
  2. muat_chain            → muat chain.json (divalidasi ulang)
  3. thread autosave       → simpan chain tiap 2 detik bila berubah
  4. buat_server + thread terima_koneksi → node mulai MENDENGARKAN permintaan HTTP
  5. sinkron_peer ke tiap peer awal      → tukar key, tarik & dorong chain (client HTTP: send_message)
  6. loop menu CLI (1–7)
  7. finally: simpan_chain terakhir kali
```

Satu proses punya tiga aktivitas paralel (thread): menu CLI (thread utama), server HTTP (satu thread per permintaan masuk), dan autosave. Itu sebabnya ada banyak `Lock`.

### Perjalanan satu permintaan HTTP

```
klien (curl, atau node lain lewat send_message)
   │  POST /blocks   {"block": {...}}
   ▼
NodeHandler._proses
   │  cari (metode, path) di _TIPE_DARI_RUTE  → tipe pesan "NEW_BLOCK"
   │  _baca_body: cek Content-Length, JSON harus objek
   ▼
handle_message(msg)          (tidak tahu soal HTTP)
   │  terima_block → validate_block → ... → balasan dict {"type": "REJECT", ...}
   ▼
_status_http  → 409           _balas → kirim status + JSON ke klien
```

### Peta endpoint

| Endpoint | Tipe pesan | Dikerjakan oleh | Status utama |
|---|---|---|---|
| `GET /chain` | `GET_CHAIN` | `handle_message` | 200 |
| `POST /blocks` | `NEW_BLOCK` | `terima_block` | 200 / 409 |
| `GET /keys` | `GET_KEYS` | `semua_key_publik` | 200 |
| `POST /keys` | `REGISTER_AUTHOR` | `daftarkan_key` | 200 / 409 |
| `POST /peers` | `ADD_PEER` | `parse_satu_peer` + `peers.append` | 201 / 200 / 400 |
| `GET /peers` | `GET_PEERS` | `handle_message` | 200 |
| `POST /nodes/resolve` | `RESOLVE` | `sinkron_peer` ke semua peer | 200 |
| `GET /status` | `GET_STATUS` | `handle_message` | 200 |

> Catatan: fungsi yang diimpor dari modul `blockchain_core_traceability_suku_cadang_kendaraan` (mis. `verify_pow`, `add_transaction`, `mine_block`) berada di file lain; di sini hanya peran singkatnya yang disebut. Penjelasan nomor baris mengacu ke `node.py` saat ini (1294 baris, termasuk blok arsip di bagian akhir).

---


## Docstring modul  _(baris 1–76)_

```python
   1  """
   2  node.py -- lapisan jaringan untuk blockchain traceability (versi 2 laptop)
   3  
   4  Tiap laptop menjalankan file ini sebagai satu NODE. Tiap node "memiliki"
   5  sebagian aktor (mis. laptop 1 = Produsen & Distributor, laptop 2 = Dealer &
   6  Bengkel): private key aktor HANYA ada di laptop pemiliknya (disimpan di
   7  --data-dir/keys/). Node lain hanya menerima PUBLIC KEY-nya supaya bisa
   8  memverifikasi signature, tanpa bisa membuka isi transaksi.
   9  
  10  Transport: HTTP (revisi 4; sebelumnya TCP dengan JSON satu baris per pesan).
  11  Server memakai http.server.ThreadingHTTPServer dan client memakai
  12  http.client (pustaka standar, tanpa dependensi baru). Body dan balasan
  13  berupa JSON. Port dan alamat peer tidak berubah (host:port).
  14  
  15    Endpoint                 Body (JSON)                         Balasan / status
  16    GET  /chain              -                                   200 {"type":"CHAIN","blocks":[...]}
  17    POST /blocks             {"block": {...}}                    200 OK / 409 REJECT / 400 ERROR
  18    GET  /keys               -                                   200 {"type":"KEYS","keys":{author: pem}}
  19    POST /keys               {"author":..,"public_key_pem":..}   200 OK / 409 REJECT
  20    POST /peers              {"peer": "host:port"}               201 OK / 200 (sudah ada) / 400 REJECT
  21    GET  /peers              -                                   200 {"type":"PEERS","peers":[...]}
  22    POST /nodes/resolve      -                                   200 hasil sinkron + resolusi fork
  23    GET  /status             -                                   200 ringkasan node
  24  
  25    Kode status: 200/201 sukses, 400 permintaan cacat, 404 path tidak dikenal,
  26    405 metode salah, 409 ditolak (block palsu/fork, key bentrok), 411/413
  27    ukuran body bermasalah, 500 galat internal. Isi balasan tetap memuat
  28    "type" (OK/REJECT/ERROR/...) seperti protokol TCP lama.
  29  
  30    Contoh: curl -X POST localhost:9001/peers -H "Content-Type: application/json" \
  31                 -d '{"peer": "localhost:9002"}'
  32  
  33    # >>> TAMBAH (Tugas 4): POST /peers (sebelumnya pesan TCP ADD_PEER)
  34    # >>> TAMBAH (Tugas 5): POST /nodes/resolve (sebelumnya hanya lewat menu 3)
  35  
  36  Kode transport TCP lama tidak dihapus: ada sebagai komentar [ARSIP] di paling
  37  bawah berkas ini.
  38  
  39  Perubahan dari versi sebelumnya:
  40    1. SATU fungsi validasi block (validate_block) dipakai oleh NEW_BLOCK DAN
  41       sinkronisasi -- termasuk cek PoW terhadap DIFFICULTY (string global).
  42       (Revisi 3: difficulty_bits per block dan retarget diganti DIFFICULTY
  43       string global; kode lamanya ada sebagai komentar "arsip" di sini dan
  44       di bagian [ARSIP] paling bawah berkas inti.)
  45    2. Format & rentang semua field block dicek sebelum dipakai; pesan cacat
  46       dijawab ERROR/REJECT, thread tidak lagi mati diam-diam.
  47    3. REGISTER_AUTHOR tidak bisa menimpa public key yang sudah terdaftar.
  48    4. Block dengan id sama tapi isi berbeda (fork) ditolak dengan jelas,
  49       bukan dijawab "OK".
  50    5. Sinkron DUA ARAH (tukar public key, tarik chain, dorong chain), jadi
  51       urutan menyalakan node tidak lagi menentukan berhasil/tidaknya.
  52    6. Keypair aktor disimpan ke file, sehingga restart tidak mengganti key.
  53    7. Resolusi fork (longest-chain rule): resolve_fork(), panjang_chain(),
  54       chain_utama(), terintegrasi ke sinkronisasi, dengan keluaran [FORK] yang
  55       menjelaskan titik cabang, panjang tiap sisi, keputusan, dan block orphan.
  56    8. Peer bisa ditambah/dihapus saat node berjalan (menu 6) -- untuk
  57       mensimulasikan partisi jaringan saat eksperimen fork.
  58    # >>> TAMBAH: dua poin baru di bawah ini
  59    9. (Tugas 4) POST /peers: peer bisa ditambahkan dari luar proses saat
  60       node berjalan, tanpa restart dan tanpa lewat menu.
  61   10. (Tugas 7) Chain disimpan ke <data-dir>/chain.json (autosave + saat
  62       keluar) dan dimuat + divalidasi ulang saat node start.
  63  
  64  KETERBATASAN (jujur):
  65    - Chain disimpan sebagai dict {id: Block}. Jika dua node membuat block
  66      dengan id yang sama pada saat yang sama, salah satunya ditolak (fork).
  67      Menu "tambah transaksi" sinkron dulu untuk memperkecil peluang ini,
  68      tetapi tidak menghilangkannya sepenuhnya.
  69    # >>> UBAH: poin lama "Chain tidak disimpan ke disk" diganti, karena
  70    # >>> sekarang chain disimpan ke chain.json.
  71    - Chain disimpan ke chain.json per node (autosave tiap ~2 detik). Perubahan
  72      dalam jeda autosave bisa hilang jika proses dimatikan paksa (mis. kill -9).
  73      File ini TIDAK dienkripsi dan tidak menyimpan private key.
  74    - Public key memakai model "pertama kali terlihat dipercaya": siapa yang
  75      mendaftarkan key suatu aktor lebih dulu, key itulah yang dipakai.
  76  """
```

- **Baris 1–76**: string multi-baris `""" ... """` di paling atas file. Python tidak menjalankannya; fungsinya dokumentasi (bisa dibaca lewat `__doc__`/`help()`).
- **Baris 1–8**: tujuan file: lapisan jaringan. Tiap laptop menjalankan satu *node* yang memiliki sebagian aktor; private key hanya ada di laptop pemiliknya, node lain hanya menerima public key (cukup untuk memverifikasi signature, tidak cukup untuk membuka isi transaksi).
- **Baris 10–37**: **transport HTTP**. Server memakai `http.server.ThreadingHTTPServer`, client memakai `http.client`; keduanya pustaka standar. Tabel (baris 15–23) mendaftar delapan endpoint beserta body dan balasannya; baris 25–28 daftar kode status; baris 30–31 contoh `curl`. Baris 36–37: kode TCP lama masih ada sebagai komentar `[ARSIP]` di paling bawah file.
- **Baris 39–62**: daftar perubahan dari versi sebelumnya. Poin 9 (`POST /peers`) dan 10 (`chain.json`) adalah tugas 4 dan 7.
- **Baris 64–75**: keterbatasan yang dinyatakan jujur (fork karena id sama, autosave bisa kehilangan perubahan, model kepercayaan public key).
- Komentar `# >>> TAMBAH/UBAH` hanyalah penanda revisi dari pembuat kode.

---


## Import library standar  _(baris 78–89)_

```python
  78  import argparse
  79  import http.client
  80  import json
  81  import math
  82  import os
  83  import socketserver
  84  import threading
  85  import time
  86  from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
  87  
  88  from cryptography.hazmat.primitives import serialization
  89  from cryptography.hazmat.primitives.asymmetric import rsa
```

- `import x` memuat modul `x`; namanya dipakai sebagai `x.fungsi()`.
- `argparse` = argumen CLI, `json` = serialisasi, `math` = `isfinite`, `os` = path/file, `threading` = thread & lock, `time` = sleep/jam.
- **Baris 79**: `http.client` = **client HTTP** (dipakai `send_message`). **Baris 83**: `socketserver` = dasar server socket yang diwarisi server HTTP (dipakai di `server_bind`). Modul `socket` mentah tidak lagi diimpor.
- **Baris 86**: `from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer`: `from paket import nama` mengambil nama tertentu saja. `BaseHTTPRequestHandler` adalah kelas dasar penanganan satu permintaan; `ThreadingHTTPServer` adalah server HTTP yang menjalankan tiap permintaan di thread sendiri.
- **Baris 88–89**: `serialization` untuk baca/tulis key PEM, `rsa` untuk tipe key RSA.

---


## Import dari modul blockchain inti  _(baris 91–114)_

```python
  91  from blockchain_core_traceability_suku_cadang_kendaraan import (
  92      ALLOWED_TRANSITIONS,
  93      AUTHORIZED_ACTORS,
  94      AUTHOR_KEYS,
  95      PUBLIC_KEY_REGISTRY,
  96      DIFFICULTY,
  97      # arsip: MIN_DIFFICULTY_BITS, MAX_DIFFICULTY_BITS,
  98      Block,
  99      TransactionRejected,
 100      ConsensusRejected,
 101      add_transaction,
 102      compute_hash,
 103      # arsip: compute_next_difficulty,
 104      get_or_create_author,
 105      is_chain_valid,
 106      pilih_dari_daftar,
 107      print_chain,
 108      public_key_from_pem,
 109      public_key_to_pem,
 110      register_public_key,
 111      validate_transaction,
 112      verify_block_signature,
 113      verify_pow,
 114  )
```

- Mengimpor konstanta (`ALLOWED_TRANSITIONS`, `AUTHORIZED_ACTORS`, `DIFFICULTY`), kelas (`Block`, exception `TransactionRejected`, `ConsensusRejected`), dan fungsi (`compute_hash`, `verify_pow`, `add_transaction`, dst.) dari file lain `blockchain_core_traceability_suku_cadang_kendaraan`.
- **Baris 96**: `DIFFICULTY` adalah string global PoW (mis. `"0000"`). **Baris 97 dan 103** (komentar `# arsip`): `MIN/MAX_DIFFICULTY_BITS` dan `compute_next_difficulty` tidak lagi diimpor karena difficulty tidak disimpan per block dan tidak ada retarget.
- Sintaks: `from X import ( a, b, c )`; tanda kurung membolehkan daftar nama dipecah ke banyak baris.

---


## Lock (kunci thread) dan konstanta  _(baris 116–125)_

```python
 116  CHAIN_LOCK = threading.Lock()
 117  KEY_LOCK = threading.Lock()
 118  
 119  # >>> TAMBAH (Tugas 4): lock untuk list `peers`.
 120  # >>> Alasan: list peers bisa diubah oleh dua thread sekaligus -- thread menu
 121  # >>> CLI (menu 6) dan thread server (pesan ADD_PEER). Lock mencegah bentrok.
 122  PEER_LOCK = threading.Lock()
 123  
 124  MAX_MSG_BYTES = 10 * 1024 * 1024   # batas ukuran satu pesan
 125  MAX_HEX = 20000                    # batas panjang field hex (ciphertext dst.)
```

- `threading.Lock()` membuat kunci: hanya satu thread yang boleh memegangnya sekaligus. Dipakai dengan `with LOCK:` sehingga otomatis dilepas.
- `CHAIN_LOCK` melindungi `chain_map`, `KEY_LOCK` melindungi daftar key, `PEER_LOCK` melindungi list `peers`. Perlu karena program punya beberapa thread (menu CLI, server, autosave).
- `MAX_MSG_BYTES = 10 * 1024 * 1024` = 10 MB. `MAX_HEX = 20000` = batas panjang string hex.
- Penamaan HURUF BESAR adalah konvensi untuk konstanta.

---


## block_to_dict: Block → dict  _(baris 128–138)_

```python
 128  # ---------- (de)serialisasi block untuk dikirim lewat jaringan ----------
 129  
 130  def block_to_dict(b: Block) -> dict:
 131      return {
 132          "id": b.id, "author": b.author, "parent_id": b.parent_id,
 133          "parent_hash": b.parent_hash, "timestamp": b.timestamp, "salt": b.salt,
 134          "nonce": b.nonce, "extra_nonce": b.extra_nonce,
 135          # arsip: "difficulty_bits": b.difficulty_bits,
 136          "part_id": b.part_id,
 137          "status": b.status, "envelope": b.envelope, "signature": b.signature,
 138      }
```

- `def block_to_dict(b: Block) -> dict:` mendefinisikan fungsi. `b: Block` dan `-> dict` adalah *type hint* (petunjuk tipe, tidak dipaksa saat runtime).
- Mengembalikan dict literal `{ "kunci": nilai, ... }` berisi **12 field** block agar bisa diubah jadi JSON dan dikirim lewat jaringan.
- **Baris 135**: komentar `# arsip` menandai field `difficulty_bits` yang sudah dicabut (difficulty kini string global `DIFFICULTY`, bukan bagian block).

---


## block_from_dict: dict → Block  _(baris 141–162)_

```python
 141  def block_from_dict(d: dict) -> Block:
 142      """Rekonstruksi Block dari dict TANPA memanggil __init__ (supaya tidak
 143      re-enkripsi ulang dengan key acak baru -- envelope harus dipakai apa
 144      adanya). content_root tidak pernah di-cache, jadi compute_hash() selalu
 145      menghitung fresh dan manipulasi field saat transit pasti terdeteksi oleh
 146      verify_pow() / verify_block_signature(). Format field harus sudah dicek
 147      lewat check_block_format() sebelum fungsi ini dipanggil."""
 148      blk = Block.__new__(Block)
 149      blk.id = d["id"]
 150      blk.author = d["author"]
 151      blk.parent_id = d["parent_id"]
 152      blk.parent_hash = d["parent_hash"]
 153      blk.timestamp = d["timestamp"]
 154      blk.salt = d["salt"]
 155      blk.nonce = d["nonce"]
 156      blk.extra_nonce = d["extra_nonce"]
 157      # arsip: blk.difficulty_bits = d["difficulty_bits"]
 158      blk.part_id = d["part_id"]
 159      blk.status = d["status"]
 160      blk.envelope = d["envelope"]
 161      blk.signature = d["signature"]
 162      return blk
```

- **Baris 148**: `Block.__new__(Block)` membuat objek **tanpa memanggil `__init__`**. Kalau `__init__` dipanggil, block akan mengenkripsi ulang dengan key acak baru, padahal `envelope` harus dipakai apa adanya.
- **Baris 149–161**: mengisi atribut satu per satu: `blk.id = d["id"]`, dst. (`d["id"]` mengambil nilai dict berdasar kunci; error `KeyError` bila tidak ada, makanya format dicek dulu). Baris 157 adalah komentar `# arsip`: `difficulty_bits` tidak lagi dibaca.
- **Baris 162**: `return blk`.
- Hash tidak di-cache, sehingga manipulasi data saat transit ketahuan oleh `verify_pow` dan `verify_block_signature`.

---


## FIELD_BLOCK: daftar field wajib  _(baris 165–169)_

```python
 165  # ---------- validasi block (SATU tempat, dipakai NEW_BLOCK & sinkronisasi) ----------
 166  
 167  FIELD_BLOCK = ("id", "author", "parent_id", "parent_hash", "timestamp", "salt",
 168                 "nonce", "extra_nonce", "part_id", "status",   # arsip: + "difficulty_bits"
 169                 "envelope", "signature")
```

- Tuple (daftar tak bisa diubah, ditulis dengan `( )`) berisi **12 nama field** yang wajib ada di setiap block. Komentar di akhir baris 168 mencatat bahwa `"difficulty_bits"` dulu termasuk.
- Baris panjang dipecah di dalam tanda kurung tanpa perlu karakter lanjutan.

---


## _int: cek bilangan bulat sungguhan  _(baris 172–173)_

```python
 172  def _int(x) -> bool:
 173      return isinstance(x, int) and not isinstance(x, bool)
```

- `isinstance(x, int)` mengecek tipe. Di Python `True`/`False` adalah subclass `int`, maka `and not isinstance(x, bool)` mengecualikan boolean.
- Awalan `_` pada nama = fungsi "internal".

---


## _hex: cek string hex valid  _(baris 176–183)_

```python
 176  def _hex(x, maks=MAX_HEX) -> bool:
 177      if not isinstance(x, str) or not x or len(x) > maks or len(x) % 2:
 178          return False
 179      try:
 180          bytes.fromhex(x)
 181          return True
 182      except ValueError:
 183          return False
```

- `maks=MAX_HEX` = parameter dengan nilai default.
- **Baris 177**: gagal jika bukan string, kosong (`not x`), lebih panjang dari `maks`, atau panjangnya ganjil (`len(x) % 2` bernilai 1 → dianggap `True`).
- **Baris 179–183**: `bytes.fromhex(x)` dicoba; bila bukan hex ia melempar `ValueError`, ditangkap `except ValueError` → `return False`.
- Sintaks `try: ... except Tipe: ...` menangkap error tanpa menghentikan program.

---


## check_block_format: validasi bentuk & rentang field  _(baris 186–229)_

```python
 186  def check_block_format(d):
 187      """Cek bentuk & rentang field. Return pesan error, atau None kalau OK."""
 188      if not isinstance(d, dict):
 189          return "block bukan objek JSON"
 190      for k in FIELD_BLOCK:
 191          if k not in d:
 192              return f"field '{k}' tidak ada"
 193  
 194      if not _int(d["id"]) or d["id"] < 1:
 195          return "id harus bilangan bulat >= 1"
 196  
 197      pid, ph = d["parent_id"], d["parent_hash"]
 198      if (pid is None) != (ph is None):
 199          return "parent_id dan parent_hash harus sama-sama ada atau sama-sama kosong"
 200      if pid is not None:
 201          if not _int(pid) or pid < 1 or pid >= d["id"]:
 202              return "parent_id harus bilangan bulat >= 1 dan lebih kecil dari id"
 203          if not _hex(ph, 64) or len(ph) != 64:
 204              return "parent_hash harus 64 karakter hex"
 205  
 206      ts = d["timestamp"]
 207      if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts) or ts <= 0:
 208          return "timestamp tidak valid"
 209      if not isinstance(d["salt"], str) or len(d["salt"]) > 64:
 210          return "salt tidak valid"
 211      if not _int(d["nonce"]) or not (0 <= d["nonce"] < 2 ** 64):
 212          return "nonce di luar rentang"
 213      if not _int(d["extra_nonce"]) or not (0 <= d["extra_nonce"] < 2 ** 32):
 214          return "extra_nonce di luar rentang"
 215      # arsip: if not _int(d["difficulty_bits"]) or not (MIN_DIFFICULTY_BITS <= d["difficulty_bits"] <= MAX_DIFFICULTY_BITS):
 216      # arsip:     return f"difficulty_bits harus {MIN_DIFFICULTY_BITS}..{MAX_DIFFICULTY_BITS}"
 217      for k in ("author", "part_id", "status"):
 218          if not isinstance(d[k], str) or not d[k] or len(d[k]) > 128:
 219              return f"field '{k}' harus string tidak kosong"
 220  
 221      env = d["envelope"]
 222      if not isinstance(env, dict):
 223          return "envelope bukan objek"
 224      for k in ("ciphertext", "nonce", "encrypted_key"):
 225          if not _hex(env.get(k)):
 226              return f"envelope.{k} bukan hex yang valid"
 227      if not _hex(d["signature"]):
 228          return "signature bukan hex yang valid"
 229      return None
```

Mengembalikan **teks error**, atau `None` jika semuanya benar.
- **188–189**: `d` harus `dict`.
- **190–192**: tiap nama di `FIELD_BLOCK` harus ada di `d` (`for ... in`, `k not in d`; f-string `f"field '{k}' ..."` menyisipkan nilai `k`).
- **194–195**: `id` bilangan bulat ≥ 1.
- **197–204**: `pid, ph = d["parent_id"], d["parent_hash"]` (assign dua variabel sekaligus). `(pid is None) != (ph is None)` adalah trik XOR: keduanya harus sama-sama kosong atau sama-sama terisi. Bila ada: `parent_id` ≥ 1 dan < `id`, `parent_hash` 64 karakter hex (panjang SHA-256).
- **206–208**: `timestamp` harus angka (int/float), bukan bool, hingga (`math.isfinite` menolak NaN/inf), dan > 0.
- **209–210**: `salt` string, maksimal 64 karakter.
- **211–214**: `nonce` dalam [0, 2⁶⁴), `extra_nonce` dalam [0, 2³²). `2 ** 64` = pangkat; `0 <= x < y` adalah perbandingan berantai.
- **215–216**: dua baris komentar `# arsip` (pemeriksaan rentang `difficulty_bits`). Pemeriksaan ini sudah tidak ada karena block tidak lagi membawa `difficulty_bits`.
- **217–219**: `author`, `part_id`, `status` harus string tidak kosong ≤ 128 karakter.
- **221–226**: `envelope` harus dict yang memuat `ciphertext`, `nonce`, `encrypted_key` berupa hex valid. `env.get(k)` mengembalikan `None` bila kunci tidak ada (tidak error).
- **227–229**: `signature` harus hex; lalu `return None` = lolos.

---


## validate_block: validasi penuh terhadap chain lokal  _(baris 232–266)_

```python
 232  def validate_block(blk: Block, chain_map: dict):
 233      """Validasi penuh sebuah block terhadap chain lokal. CHAIN_LOCK harus
 234      sudah dipegang pemanggil. Return (True, '') atau (False, alasan)."""
 235      if blk.author not in AUTHORIZED_ACTORS:
 236          return False, "author tidak berwenang"
 237  
 238      parent = None
 239      if blk.parent_id is not None:
 240          parent = chain_map.get(blk.parent_id)
 241          if parent is None:
 242              return False, "parent block belum dikenal node ini"
 243  
 244      # Urutan status dicek dari part_id/status plaintext saja (isi transaksi
 245      # lengkap tetap terenkripsi, sesuai desain semula).
 246      pseudo_tx = {
 247          "part_id": blk.part_id, "status": blk.status,
 248          "part_name": "-", "origin": "-", "destination": "-", "vehicle_id": "-",
 249      }
 250      valid, message = validate_transaction(pseudo_tx, parent)
 251      if not valid:
 252          return False, message
 253  
 254      if parent is not None and blk.parent_hash != compute_hash(parent):
 255          return False, "parent_hash mismatch"
 256  
 257      # arsip: diharapkan = compute_next_difficulty(chain_map, parent)
 258      # arsip: if blk.difficulty_bits != diharapkan:
 259      # arsip:     return False, f"difficulty_bits {blk.difficulty_bits} tidak sesuai aturan retarget (seharusnya {diharapkan})"
 260  
 261      if not verify_pow(blk):   # hash harus diawali DIFFICULTY (string global)
 262          return False, "PoW tidak valid"
 263  
 264      if not verify_block_signature(blk):
 265          return False, "signature tidak valid (public key author belum terdaftar di node ini?)"
 266      return True, ""
```

Mengembalikan tuple `(True, "")` atau `(False, alasan)`. Urutan pengecekan:
1. **235–236**: `author` harus ada di `AUTHORIZED_ACTORS`.
2. **238–242**: jika ada `parent_id`, parent diambil dengan `chain_map.get(...)` (aman, `None` jika tidak ada). Parent tak dikenal → ditolak.
3. **246–252**: dibuat `pseudo_tx` hanya dari `part_id` dan `status` (isi lengkap transaksi terenkripsi, field lain diisi `"-"`). `validate_transaction` memastikan urutan status sah (misalnya PRODUCED → SHIPPED → ...). `valid, message = ...` = tuple unpacking.
4. **254–255**: `parent_hash` harus sama dengan `compute_hash(parent)`.
5. **257–259**: tiga baris komentar `# arsip` (cek `difficulty_bits` terhadap aturan retarget). Sudah tidak ada: difficulty kini satu string global.
6. **261–262**: `verify_pow(blk)`: hash block harus diawali `DIFFICULTY` (string global, mis. `"0000"`).
7. **264–265**: `verify_block_signature(blk)`: tanda tangan digital valid.
8. **266**: lolos semua → `(True, "")`.

---


## terima_block: pintu masuk tunggal block dari luar  _(baris 269–291)_

```python
 269  def terima_block(d, chain_map: dict):
 270      """Cek format + validasi + masukkan ke chain. CHAIN_LOCK harus dipegang.
 271      Return (kode, alasan); kode: 'BARU' | 'ADA' | 'TOLAK' | 'FORK'."""
 272      err = check_block_format(d)
 273      if err:
 274          return "TOLAK", f"format block tidak valid: {err}"
 275      try:
 276          blk = block_from_dict(d)
 277      except (KeyError, TypeError, ValueError) as e:
 278          return "TOLAK", f"block tidak dapat dibaca: {e}"
 279  
 280      if blk.id in chain_map:
 281          if compute_hash(chain_map[blk.id]) == compute_hash(blk):
 282              return "ADA", "sudah ada di chain lokal"
 283          return "FORK", (f"id block {blk.id} sudah dipakai block lain dengan isi berbeda "
 284                          f"(fork) -- block ini ditolak")
 285  
 286      ok, alasan = validate_block(blk, chain_map)
 287      if not ok:
 288          return "TOLAK", alasan
 289  
 290      chain_map[blk.id] = blk
 291      return "BARU", "diterima"
```

Mengembalikan `(kode, alasan)` dengan kode `BARU | ADA | TOLAK | FORK`.
- **272–274**: cek format; ada error → `"TOLAK"`.
- **275–278**: `block_from_dict` dibungkus `try/except (KeyError, TypeError, ValueError) as e`. Tuple di `except` menangkap beberapa jenis error; `as e` menyimpan objek error.
- **280–284**: jika `id` sudah ada di chain: hash sama → `"ADA"`, hash beda → `"FORK"` (ditolak).
- **286–288**: belum ada → `validate_block`; gagal → `"TOLAK"`.
- **290–291**: lolos → `chain_map[blk.id] = blk` (menambah ke dict) → `"BARU"`.

---


## Komentar aturan fork + RIWAYAT_FORK  _(baris 294–307)_

```python
 294  # ---------- resolusi fork (aturan rantai terpanjang) ----------
 295  #
 296  # Chain disimpan sebagai {id: Block}. Satu node menyimpan SELURUH buku besar
 297  # (kumpulan lineage part: PRODUCED -> SHIPPED -> RECEIVED -> INSTALLED).
 298  # Dua node dikatakan FORK jika ada id block yang sama tetapi isinya (hash)
 299  # berbeda. Aturan penyelesaian (longest-chain rule):
 300  #   - buku besar peer dibangun ulang dari nol & divalidasi penuh dulu;
 301  #   - panjang = jumlah block VALID; yang lebih panjang menang;
 302  #   - jika menang peer -> chain lokal diganti; block lokal yang tidak ada di
 303  #     chain baru menjadi ORPHAN (author-nya perlu mengajukan ulang transaksinya);
 304  #   - jika SERI -> tetap pakai chain lokal (first-seen); fork berlanjut sampai
 305  #     salah satu pihak menambah block, lalu pihak yang kalah menyusul saat sinkron.
 306  
 307  RIWAYAT_FORK = []
```

- Komentar menjelaskan *longest-chain rule*: yang lebih panjang menang; seri → tetap chain lokal (first-seen); block lokal yang kalah menjadi **orphan**.
- `RIWAYAT_FORK = []` adalah list global yang mencatat tiap kejadian resolusi fork.

---


## label_block dan panjang_chain  _(baris 310–316)_

```python
 310  def label_block(b) -> str:
 311      return f"{b.id} ({b.author}/{b.status}/{b.part_id})"
 312  
 313  
 314  def panjang_chain(chain_map: dict) -> int:
 315      """Panjang chain = jumlah block valid di buku besar."""
 316      return len(chain_map)
```

- `label_block` memformat teks seperti `3 (Dealer/RECEIVED/P001)` dengan f-string.
- `panjang_chain` = `len(chain_map)`, yaitu jumlah block valid.

---


## _lineage: semua jalur akar → ujung  _(baris 319–339)_

```python
 319  def _lineage(chain_map: dict):
 320      """Untuk tiap akar (block tanpa parent): semua jalur akar -> ujung."""
 321      anak = {}
 322      for b in chain_map.values():
 323          if b.parent_id is not None:
 324              anak.setdefault(b.parent_id, []).append(b.id)
 325      hasil = []
 326      for akar in sorted(i for i, b in chain_map.items() if b.parent_id is None):
 327          jalur = []
 328  
 329          def dfs(i, path):
 330              path = path + [i]
 331              if i not in anak:
 332                  jalur.append(path)
 333                  return
 334              for c in sorted(anak[i]):
 335                  dfs(c, path)
 336  
 337          dfs(akar, [])
 338          hasil.append((akar, jalur))
 339      return hasil
```

- **321–324**: membangun peta `anak` (`parent_id → [id anak]`). `anak.setdefault(k, []).append(x)` membuat list kosong bila kunci belum ada, lalu menambah `x`.
- **326**: `sorted(i for i, b in chain_map.items() if b.parent_id is None)` memakai *generator expression* untuk mencari akar (block tanpa parent).
- **329–335**: fungsi bersarang `dfs` (*depth-first search*, rekursif). `path = path + [i]` membuat list **baru** supaya tiap cabang punya salinan sendiri. Jika `i` tidak punya anak (ujung), jalur disimpan ke `jalur`; jika punya, turun ke tiap anak (urut).
- **337–339**: `dfs(akar, [])`, hasilnya `(akar, daftar_jalur)` ditambah ke `hasil`.

---


## chain_utama: pilih jalur terpanjang  _(baris 342–350)_

```python
 342  def chain_utama(chain_map: dict) -> list:
 343      """Chain utama tiap lineage = jalur akar -> ujung TERPANJANG (seri: ujung
 344      ber-id lebih kecil). Return list (akar, jalur_utama, jalur_cabang_lain)."""
 345      hasil = []
 346      for akar, jalur in _lineage(chain_map):
 347          utama = max(jalur, key=lambda j: (len(j), -j[-1]))
 348          lain = [j for j in jalur if j is not utama]
 349          hasil.append((akar, utama, lain))
 350      return hasil
```

- `max(jalur, key=lambda j: (len(j), -j[-1]))`: `lambda` = fungsi anonim. Kuncinya tuple; Python membandingkan tuple elemen demi elemen, jadi yang terpanjang menang, dan bila seri yang id ujungnya lebih kecil menang (karena `-j[-1]`).
- `[j for j in jalur if j is not utama]`: *list comprehension*; `is not` membandingkan identitas objek.
- Mengembalikan list tuple `(akar, jalur_utama, cabang_lain)`.

---


## bangun_kandidat: bangun buku besar dari nol + validasi penuh  _(baris 353–372)_

```python
 353  def bangun_kandidat(blocks):
 354      """Bangun buku besar kandidat dari daftar block peer, dari nol, dengan
 355      validasi penuh tiap block. Return (peta_valid, daftar_ditolak)."""
 356      kandidat, ditolak = {}, []
 357      dicek = [d for d in blocks if isinstance(d, dict) and _int(d.get("id"))]
 358      for d in sorted(dicek, key=lambda x: x["id"]):
 359          err = check_block_format(d)
 360          if err:
 361              ditolak.append((d["id"], err))
 362              continue
 363          blk = block_from_dict(d)
 364          if blk.id in kandidat:
 365              ditolak.append((blk.id, "id duplikat dalam daftar peer"))
 366              continue
 367          ok, alasan = validate_block(blk, kandidat)
 368          if ok:
 369              kandidat[blk.id] = blk
 370          else:
 371              ditolak.append((blk.id, alasan))
 372      return kandidat, ditolak
```

- **356**: `kandidat, ditolak = {}, []` mengisi dua variabel sekaligus (dict kosong dan list kosong).
- **357**: list comprehension menyaring hanya item yang dict dan punya `id` bulat.
- **358**: `sorted(..., key=lambda x: x["id"])` mengurutkan menurut id, sehingga parent selalu diproses sebelum anaknya.
- **359–362**: format salah → catat ke `ditolak` → `continue` (lompat ke iterasi berikut).
- **364–366**: id duplikat dalam daftar peer ditolak.
- **367–371**: `validate_block(blk, kandidat)` divalidasi terhadap `kandidat` (bukan chain lokal); lolos → masuk, gagal → `ditolak`.
- **372**: `return kandidat, ditolak` (mengembalikan tuple).

---


## resolve_fork: selesaikan fork (longest-chain rule)  _(baris 375–403)_

```python
 375  def resolve_fork(chain_map: dict, blocks, sumber="peer") -> dict:
 376      """Selesaikan fork antara chain lokal dan chain peer. CHAIN_LOCK harus
 377      dipegang. Mengubah chain_map di tempat bila peer menang. Return info."""
 378      kandidat, ditolak = bangun_kandidat(blocks)
 379      p_lokal, p_peer = panjang_chain(chain_map), panjang_chain(kandidat)
 380  
 381      beda = [i for i in chain_map
 382              if i in kandidat and compute_hash(chain_map[i]) != compute_hash(kandidat[i])]
 383      info = {
 384          "sumber": sumber, "waktu": time.strftime("%H:%M:%S"),
 385          "titik_cabang": min(beda) if beda else None,
 386          "panjang_lokal": p_lokal, "panjang_peer": p_peer,
 387          "peer_ditolak": ditolak, "orphan": [], "ditambah": 0,
 388      }
 389  
 390      if p_peer > p_lokal:
 391          info["keputusan"] = "GANTI"
 392          info["orphan"] = [label_block(b) for i, b in sorted(chain_map.items())
 393                            if i not in kandidat or compute_hash(kandidat[i]) != compute_hash(b)]
 394          info["ditambah"] = sum(1 for i, b in kandidat.items()
 395                                 if i not in chain_map or compute_hash(chain_map[i]) != compute_hash(b))
 396          chain_map.clear()
 397          chain_map.update(kandidat)
 398      elif p_peer < p_lokal:
 399          info["keputusan"] = "PERTAHANKAN"
 400      else:
 401          info["keputusan"] = "SERI"
 402      RIWAYAT_FORK.append(info)
 403      return info
```

- **378**: bangun kandidat dari block peer.
- **379**: hitung panjang lokal & peer (`p_lokal, p_peer = ..., ...`).
- **381–382**: `beda` = id yang ada di kedua sisi tetapi hash-nya berbeda, yaitu titik fork.
- **383–388**: dict `info` untuk laporan. `min(beda) if beda else None` = ekspresi ternary. `time.strftime("%H:%M:%S")` = jam sekarang.
- **390–397**: peer lebih panjang → keputusan `"GANTI"`. Block lokal yang tidak ada/berbeda di chain baru dicatat sebagai **orphan**; `sum(1 for ... if ...)` menghitung block yang berubah. Lalu `chain_map.clear()` + `chain_map.update(kandidat)` mengganti isi dict **di tempat** (objek sama, jadi referensi di thread lain ikut berubah).
- **398–401**: lokal lebih panjang → `"PERTAHANKAN"`; sama panjang → `"SERI"`.
- **402–403**: catat ke `RIWAYAT_FORK`, return `info`.

---


## cetak_fork: laporan [FORK]  _(baris 406–422)_

```python
 406  def cetak_fork(info: dict):
 407      k = info["keputusan"]
 408      penjelasan = {
 409          "GANTI": "chain lokal DIGANTI chain peer (peer lebih panjang)",
 410          "PERTAHANKAN": "chain lokal DIPERTAHANKAN (lokal lebih panjang)",
 411          "SERI": "panjang SAMA -> chain lokal dipertahankan (first-seen); "
 412                  "fork berlanjut sampai salah satu menambah block",
 413      }[k]
 414      print(f"[FORK] Percabangan terdeteksi dengan {info['sumber']}")
 415      print(f"       titik cabang   : block id {info['titik_cabang']}")
 416      print(f"       panjang lokal  : {info['panjang_lokal']} block")
 417      print(f"       panjang peer   : {info['panjang_peer']} block valid "
 418            f"({len(info['peer_ditolak'])} ditolak saat validasi)")
 419      print(f"       keputusan      : {k} -> {penjelasan}")
 420      if info["orphan"]:
 421          print(f"       block orphan   : {', '.join(info['orphan'])}")
 422          print("       (transaksi orphan perlu diajukan ulang oleh author-nya)")
```

- **408–413**: dict `penjelasan` dibuat lalu langsung diambil nilainya dengan `[k]`.
- **414–422**: banyak `print(f"...")`. Perhatikan `info['sumber']`: kutip tunggal di dalam f-string berkutip ganda agar tidak bentrok. `', '.join(list)` menggabungkan elemen dengan koma.

---


## tampilkan_fork: menu 5  _(baris 425–450)_

```python
 425  def tampilkan_fork(chain_map: dict):
 426      print("\n=== CHAIN UTAMA & FORK ===")
 427      if not chain_map:
 428          print("Chain masih kosong.")
 429      else:
 430          lineage = chain_utama(chain_map)
 431          cabang = sum(len(lain) for _, _, lain in lineage)
 432          print(f"Panjang chain: {panjang_chain(chain_map)} block | "
 433                f"lineage (part): {len(lineage)} | cabang samping: {cabang}")
 434  
 435          def teks(path):
 436              return " -> ".join(f"{i}[{chain_map[i].status}]" for i in path)
 437  
 438          for akar, utama, lain in lineage:
 439              print(f"Lineage block {akar} (part {chain_map[akar].part_id})")
 440              print(f"  chain utama : {teks(utama)}")
 441              for j in lain:
 442                  print(f"  cabang      : {teks(j)}")
 443      if RIWAYAT_FORK:
 444          print("\nRiwayat resolusi fork:")
 445          for n, f in enumerate(RIWAYAT_FORK, 1):
 446              print(f"  {n}) {f['waktu']} dengan {f['sumber']}: lokal {f['panjang_lokal']} vs "
 447                    f"peer {f['panjang_peer']} -> {f['keputusan']}"
 448                    f"{' | orphan: ' + str(len(f['orphan'])) if f['orphan'] else ''}")
 449      else:
 450          print("\nBelum ada fork yang terdeteksi.")
```

- **427–428**: chain kosong → pesan.
- **430–433**: `lineage = chain_utama(...)`, `cabang = sum(len(lain) for _, _, lain in lineage)` (`_` = nilai yang diabaikan).
- **435–436**: fungsi bersarang `teks(path)` merangkai `"1[PRODUCED] -> 2[SHIPPED]"` dengan `" -> ".join(...)`.
- **438–442**: cetak tiap lineage: chain utama dan cabang samping.
- **443–450**: riwayat fork; `enumerate(RIWAYAT_FORK, 1)` = penomoran mulai 1; ada ternary di dalam f-string untuk jumlah orphan.

---


## daftarkan_key: daftarkan public key aktor lain  _(baris 453–480)_

```python
 453  # ---------- manajemen public key & keypair ----------
 454  
 455  def daftarkan_key(author, pem):
 456      """Daftarkan public key author milik node lain. Key yang sudah terdaftar
 457      TIDAK boleh ditimpa dengan key berbeda. Return (ok, alasan)."""
 458      if not isinstance(author, str) or not isinstance(pem, str):
 459          return False, "author/public_key_pem harus string"
 460      if author not in AUTHORIZED_ACTORS:
 461          return False, "author tidak berwenang"
 462      try:
 463          pub = public_key_from_pem(pem)
 464      except Exception:
 465          return False, "public key PEM tidak valid"
 466      if not isinstance(pub, rsa.RSAPublicKey) or pub.key_size < 2048:
 467          return False, "public key harus RSA minimal 2048 bit"
 468  
 469      with KEY_LOCK:
 470          ada = None
 471          if author in AUTHOR_KEYS:
 472              ada = AUTHOR_KEYS[author][1]
 473          elif author in PUBLIC_KEY_REGISTRY:
 474              ada = PUBLIC_KEY_REGISTRY[author]
 475          if ada is not None:
 476              if public_key_to_pem(ada) == public_key_to_pem(pub):
 477                  return True, "sudah terdaftar"
 478              return False, "public key author ini sudah terdaftar dan BERBEDA -- ditolak"
 479          register_public_key(author, pub)
 480      return True, "terdaftar"
```

- **458–461**: tipe harus string dan author harus berwenang.
- **462–465**: `public_key_from_pem(pem)` di dalam `try/except Exception`; gagal → "PEM tidak valid".
- **466–467**: harus `RSAPublicKey` berukuran ≥ 2048 bit.
- **469**: `with KEY_LOCK:` agar tidak bentrok antar-thread.
- **470–474**: cari key yang sudah ada: di `AUTHOR_KEYS` (isinya tuple `(priv, pub)`, maka diambil `[1]`) atau di `PUBLIC_KEY_REGISTRY`.
- **475–478**: sudah ada dan sama → `"sudah terdaftar"`; sudah ada tapi beda → **ditolak** (tidak boleh menimpa).
- **479–480**: belum ada → `register_public_key`. Model kepercayaan: *trust on first use*.

---


## semua_key_publik  _(baris 483–488)_

```python
 483  def semua_key_publik() -> dict:
 484      with KEY_LOCK:
 485          hasil = {a: public_key_to_pem(k[1]) for a, k in AUTHOR_KEYS.items()}
 486          for a, k in PUBLIC_KEY_REGISTRY.items():
 487              hasil.setdefault(a, public_key_to_pem(k))
 488      return hasil
```

- **485**: *dict comprehension* `{a: pem for a, k in ...}` membuat dict `author → PEM` dari key lokal.
- **486–487**: `hasil.setdefault(a, ...)` hanya mengisi bila kunci belum ada, jadi key lokal diprioritaskan.

---


## load_or_create_keys: muat/buat private key  _(baris 491–515)_

```python
 491  def load_or_create_keys(author, data_dir):
 492      """Muat private key author dari file; kalau belum ada, buat lalu simpan.
 493      File key TIDAK dienkripsi -- lindungi folder data dir ini."""
 494      folder = os.path.join(data_dir, "keys")
 495      os.makedirs(folder, exist_ok=True)
 496      path = os.path.join(folder, f"{author}.pem")
 497      if os.path.exists(path):
 498          with open(path, "rb") as f:
 499              priv = serialization.load_pem_private_key(f.read(), password=None)
 500          AUTHOR_KEYS[author] = (priv, priv.public_key())
 501          print(f"[NODE] Key '{author}' dimuat dari {path}")
 502      else:
 503          priv, _ = get_or_create_author(author)
 504          pem = priv.private_bytes(
 505              encoding=serialization.Encoding.PEM,
 506              format=serialization.PrivateFormat.PKCS8,
 507              encryption_algorithm=serialization.NoEncryption(),
 508          )
 509          with open(path, "wb") as f:
 510              f.write(pem)
 511          try:
 512              os.chmod(path, 0o600)
 513          except OSError:
 514              pass
 515          print(f"[NODE] Key '{author}' dibuat & disimpan di {path}")
```

- **494–496**: `os.path.join` merangkai path `data_dir/keys/<author>.pem`; `os.makedirs(..., exist_ok=True)` membuat folder tanpa error bila sudah ada.
- **497–501**: file ada → `open(path, "rb")` (mode baca biner) di dalam `with`, lalu `load_pem_private_key(..., password=None)`. Disimpan sebagai tuple `(priv, priv.public_key())`.
- **502–515**: belum ada → `get_or_create_author` membuat keypair (`priv, _ =` mengabaikan elemen kedua). `private_bytes(...)` mengubah ke PEM format PKCS8 tanpa enkripsi; ditulis dengan mode `"wb"`. `os.chmod(path, 0o600)` membatasi izin hanya untuk pemilik (`0o` = angka oktal); gagal → `pass` (diabaikan, mis. di Windows).

---


## simpan_chain: simpan chain ke chain.json (atomik)  _(baris 518–544)_

```python
 518  # =====================================================================
 519  # >>> TAMBAH (Tugas 7): PENYIMPANAN CHAIN KE BERKAS JSON
 520  # >>> Tiga fungsi baru: simpan_chain, muat_chain, autosave.
 521  # >>> Letak: tepat di bawah load_or_create_keys, karena fungsi-fungsi yang
 522  # >>> dipanggil di sini (semua_key_publik, block_to_dict, bangun_kandidat,
 523  # >>> daftarkan_key) semuanya sudah didefinisikan di atas.
 524  # =====================================================================
 525  
 526  def simpan_chain(chain_map, path):
 527      """Tulis chain + public key semua aktor ke satu berkas JSON.
 528  
 529      Kenapa public key ikut disimpan: saat dimuat nanti, tiap block divalidasi
 530      ulang (termasuk signature), dan itu butuh public key aktor milik node lain.
 531      Private key TIDAK pernah ditulis ke sini (sudah ada di folder keys/).
 532  
 533      Kenapa ditulis ke .tmp lalu os.replace: kalau node mati di tengah menulis,
 534      chain.json lama tetap utuh (penulisan atomik)."""
 535      with CHAIN_LOCK:   # kunci supaya chain tidak berubah selagi disalin
 536          data = {"keys": semua_key_publik(),
 537                  "blocks": [block_to_dict(chain_map[i]) for i in sorted(chain_map)]}
 538      # Node tanpa --authors (mis. node5 di Docker) belum punya folder data,
 539      # jadi pastikan foldernya ada sebelum menulis.
 540      os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
 541      tmp = path + ".tmp"
 542      with open(tmp, "w", encoding="utf-8") as f:
 543          json.dump(data, f, indent=2)
 544      os.replace(tmp, path)
```

- **535–537**: di dalam `CHAIN_LOCK`, chain disalin ke dict `data` (public key + list block terurut id). Lock dilepas sebelum menulis ke disk agar tidak lama menahan thread lain.
- **540**: `os.path.dirname(path) or "."` memastikan folder ada.
- **541–544**: **penulisan atomik**: tulis ke `chain.json.tmp`, lalu `os.replace(tmp, path)` menggantinya sekaligus. Jika node mati di tengah penulisan, file lama tetap utuh. `json.dump(data, f, indent=2)` menulis JSON rapi.

---


## muat_chain: baca chain.json saat start  _(baris 547–576)_

```python
 547  def muat_chain(chain_map, path):
 548      """Baca chain.json saat node start. Return jumlah block yang berhasil dimuat.
 549  
 550      Urutan penting: public key dimuat DULU (daftarkan_key), baru block
 551      divalidasi lewat bangun_kandidat -- validasi penuh (PoW, signature,
 552      parent_hash, urutan status) dijalankan ulang untuk TIAP block. Jadi kalau
 553      file JSON diutak-atik tangan, block yang rusak otomatis ditolak."""
 554      if not os.path.exists(path):
 555          return 0   # node baru, belum ada berkas -> mulai dari chain kosong
 556      try:
 557          with open(path, encoding="utf-8") as f:
 558              data = json.load(f)
 559      except (OSError, json.JSONDecodeError) as e:
 560          print(f"[NODE] chain.json tidak terbaca: {e}")
 561          return 0
 562      if not isinstance(data, dict):
 563          print("[NODE] chain.json bukan objek JSON, diabaikan")
 564          return 0
 565      keys = data.get("keys", {})
 566      if isinstance(keys, dict):
 567          for a, pem in keys.items():
 568              daftarkan_key(a, pem)
 569      blocks = data.get("blocks", [])
 570      if not isinstance(blocks, list):
 571          blocks = []
 572      kandidat, ditolak = bangun_kandidat(blocks)
 573      with CHAIN_LOCK:
 574          chain_map.update(kandidat)
 575      print(f"[NODE] Dimuat {len(kandidat)} block dari {path} ({len(ditolak)} ditolak)")
 576      return len(kandidat)
```

- **554–555**: file tidak ada → `return 0` (mulai dari chain kosong).
- **556–561**: baca JSON dalam `try/except (OSError, json.JSONDecodeError)`.
- **562–564**: isi harus dict.
- **565–568**: **public key didaftarkan lebih dulu**, karena verifikasi signature membutuhkannya.
- **569–572**: block divalidasi ulang lewat `bangun_kandidat` (wewenang author, urutan status, parent_hash, PoW, signature), jadi file yang diedit manual tidak bisa menyusupkan block palsu.
- **573–576**: hasil dimasukkan ke `chain_map` di dalam `CHAIN_LOCK`.

---


## autosave: thread penyimpan otomatis  _(baris 579–598)_

```python
 579  def autosave(chain_map, path, jeda=2):
 580      """Thread latar belakang: tiap `jeda` detik, cek apakah chain berubah;
 581      kalau ya, simpan ke disk.
 582  
 583      Dipilih autosave (bukan memanggil simpan_chain di tiap tempat) supaya
 584      kita tidak perlu mengubah menu 1, terima_block, maupun resolve_fork --
 585      semua sumber perubahan chain otomatis tersimpan."""
 586      terakhir = None
 587      while True:
 588          time.sleep(jeda)
 589          with CHAIN_LOCK:
 590              snap = json.dumps([block_to_dict(chain_map[i]) for i in sorted(chain_map)],
 591                                sort_keys=True)
 592          if snap != terakhir:
 593              try:
 594                  simpan_chain(chain_map, path)
 595                  terakhir = snap
 596              except OSError as e:
 597                  # Jangan biarkan thread mati diam-diam kalau disk bermasalah.
 598                  print(f"[NODE] Autosave gagal: {e}")
```

- Loop abadi `while True` yang dijalankan di thread latar.
- **588**: `time.sleep(jeda)` menunggu 2 detik.
- **589–591**: di dalam lock, chain dijadikan string JSON (`snap`); `sort_keys=True` agar urutan konsisten.
- **592–598**: bila `snap` berbeda dari `terakhir`, `simpan_chain` dipanggil. Error disk ditangkap dan dicetak agar thread tidak mati diam-diam.

---


## handle_message: router semua pesan masuk  _(baris 601–695)_

```python
 601  # ---------- logika pesan (bebas transport) ----------
 602  
 603  # >>> UBAH (Tugas 4): tambah parameter `peers=None`.
 604  # >>> Default None dipilih supaya uji_node.py / uji_fork.py yang memanggil
 605  # >>> fungsi ini TANPA peers tetap berjalan seperti semula.
 606  def handle_message(msg: dict, chain_map: dict, peers=None, owned_authors=None) -> dict:
 607      """Logika satu pesan: dict masuk -> dict balasan. Tidak tahu apa-apa soal HTTP;
 608      tipe pesan dipetakan dari (metode, path) oleh NodeHandler di bawah."""
 609      mtype = msg.get("type")
 610  
 611      # >>> TAMBAH (Tugas 4): seluruh blok ADD_PEER ini = padanan POST /peers.
 612      # >>> Letak: setelah baris `mtype = ...` dan SEBELUM cabang REGISTER_AUTHOR.
 613      # >>> Fungsi: menambahkan alamat ke daftar peers saat node berjalan, tanpa restart.
 614      if mtype == "ADD_PEER":
 615          if peers is None:
 616              # Server dijalankan tanpa list peers (mis. dari skrip uji) -> tolak dengan jelas.
 617              return {"type": "REJECT", "reason": "node ini tidak mendukung ADD_PEER"}
 618          try:
 619              # parse_satu_peer (sudah ada di bawah) mengubah "localhost:5002"
 620              # menjadi ("localhost", 5002) sekaligus memvalidasi format & port.
 621              peer = parse_satu_peer(str(msg.get("peer", "")))
 622          except ValueError as e:
 623              return {"type": "REJECT", "reason": str(e)}
 624          with PEER_LOCK:
 625              if peer in peers:                       # cegah duplikat
 626                  return {"type": "OK", "note": "peer sudah ada"}
 627              peers.append(peer)                      # INTI FITUR: list diubah saat node jalan
 628              daftar = [f"{h}:{p}" for h, p in peers]
 629          print(f"[NODE] Peer ditambahkan lewat ADD_PEER: {peer[0]}:{peer[1]}")
 630          # Catatan: hanya menambah ke daftar, TIDAK langsung sinkron.
 631          # Untuk menjalankan resolve fork, pakai menu 3 di node ini.
 632          return {"type": "OK", "peers": daftar}
 633  
 634      if mtype == "REGISTER_AUTHOR":
 635          ok, alasan = daftarkan_key(msg.get("author"), msg.get("public_key_pem"))
 636          if ok:
 637              return {"type": "OK", "note": alasan}
 638          print(f"[NODE] REGISTER_AUTHOR ditolak: {alasan}")
 639          return {"type": "REJECT", "reason": alasan}
 640  
 641      if mtype == "GET_KEYS":
 642          return {"type": "KEYS", "keys": semua_key_publik()}
 643  
 644      if mtype == "GET_CHAIN":
 645          with CHAIN_LOCK:
 646              blocks = [block_to_dict(b) for b in chain_map.values()]
 647          return {"type": "CHAIN", "blocks": blocks}
 648  
 649      if mtype == "NEW_BLOCK":
 650          d = msg.get("block")
 651          with CHAIN_LOCK:
 652              kode, alasan = terima_block(d, chain_map)
 653          if kode == "BARU":
 654              print(f"[NODE] Memverifikasi & menerima block {d['id']} dari jaringan "
 655                    f"(author={d['author']}, status={d['status']})")
 656              return {"type": "OK"}
 657          if kode == "ADA":
 658              return {"type": "OK", "note": alasan}
 659          idb = d.get("id") if isinstance(d, dict) else "?"
 660          print(f"[NODE] Block {idb} DITOLAK: {alasan}")
 661          return {"type": "REJECT", "reason": alasan}
 662  
 663      if mtype == "GET_PEERS":
 664          if peers is None:
 665              return {"type": "REJECT", "reason": "node ini tidak mendukung daftar peer"}
 666          with PEER_LOCK:
 667              daftar = [f"{h}:{p}" for h, p in peers]
 668          return {"type": "PEERS", "peers": daftar}
 669  
 670      if mtype == "GET_STATUS":
 671          with CHAIN_LOCK:
 672              jumlah = panjang_chain(chain_map)
 673          with PEER_LOCK:
 674              daftar = [f"{h}:{p}" for h, p in (peers or [])]
 675          return {"type": "STATUS", "aktor_lokal": list(owned_authors or []),
 676                  "jumlah_block": jumlah, "peers": daftar, "difficulty": DIFFICULTY}
 677  
 678      # >>> TAMBAH (Tugas 5): padanan POST /nodes/resolve -- menjalankan sinkron dua
 679      # >>> arah dengan SEMUA peer (sama seperti menu 3), termasuk resolusi fork
 680      # >>> (longest-chain rule). Keluaran [FORK] tercetak di konsol node ini.
 681      if mtype == "RESOLVE":
 682          if peers is None:
 683              return {"type": "REJECT", "reason": "node ini tidak mendukung RESOLVE"}
 684          with PEER_LOCK:
 685              daftar = list(peers)
 686          fork_sebelum = len(RIWAYAT_FORK)
 687          hasil = [{"peer": f"{h}:{p}",
 688                    "terjangkau": sinkron_peer(h, p, chain_map, owned_authors or [])}
 689                   for h, p in daftar]
 690          with CHAIN_LOCK:
 691              jumlah = panjang_chain(chain_map)
 692          return {"type": "OK", "hasil": hasil, "jumlah_block": jumlah,
 693                  "fork_ditangani": len(RIWAYAT_FORK) - fork_sebelum}
 694  
 695      return {"type": "ERROR", "reason": f"tipe pesan tidak dikenal: {mtype}"}
```

**`handle_message(msg, chain_map, peers=None, owned_authors=None)` tidak tahu apa-apa soal HTTP**: ia menerima satu dict dan mengembalikan satu dict balasan (baris 606–608). Pemetaan dari alamat HTTP ke `msg["type"]` dilakukan `NodeHandler` (lihat di bawah). Parameter `peers` dan `owned_authors` diisi oleh server; `None` berarti node dijalankan tanpa fitur itu (mis. dari skrip uji).

`mtype = msg.get("type")`, lalu rangkaian `if`:
- **ADD_PEER (614–632)**: dipanggil oleh `POST /peers`. `peers is None` → ditolak. Alamat diurai `parse_satu_peer`; format salah → `REJECT` (menjadi HTTP 400). Di dalam `PEER_LOCK`: cek duplikat (balasan `OK` dengan `note`, menjadi HTTP 200), `peers.append(peer)`, dan buat `daftar` dengan list comprehension `[f"{h}:{p}" for h, p in peers]` (balasan berisi `peers`, menjadi HTTP 201). Ini mengubah list yang sama dengan yang dipakai menu CLI sehingga langsung terlihat tanpa restart. Hanya **menambah**, tidak langsung sinkron.
- **REGISTER_AUTHOR (634–639)**: `POST /keys`. Memanggil `daftarkan_key`, membalas `OK` atau `REJECT` (HTTP 409 bila key bentrok).
- **GET_KEYS (641–642)**: `GET /keys`, membalas semua public key.
- **GET_CHAIN (644–647)**: `GET /chain`. Menyalin semua block jadi list dict di dalam `CHAIN_LOCK`, lalu membalas `CHAIN`.
- **NEW_BLOCK (649–661)**: `POST /blocks`. `terima_block` dipanggil di dalam lock. `BARU`/`ADA` → `OK`; selain itu (`TOLAK`/`FORK`) → `REJECT` + alasan (menjadi HTTP 409). `d.get("id") if isinstance(d, dict) else "?"` = ternary agar aman bila `d` bukan dict.
- **GET_PEERS (663–668)** *(baru)*: `GET /peers`. Membalas daftar peer sebagai teks `host:port`, dibaca di dalam `PEER_LOCK`.
- **GET_STATUS (670–676)** *(baru)*: `GET /status`. Membalas ringkasan node: aktor lokal, jumlah block (`panjang_chain`), daftar peer, dan `DIFFICULTY`. `(peers or [])` memakai list kosong bila `peers` bernilai `None`.
- **RESOLVE (678–693)** *(baru, Tugas 5)*: `POST /nodes/resolve`. Menyalin daftar peer di dalam `PEER_LOCK`, lalu memanggil `sinkron_peer` untuk **tiap peer** (sama seperti menu 3: tukar key, tarik chain, resolusi fork, dorong chain). `fork_sebelum` mencatat panjang `RIWAYAT_FORK` agar balasan bisa melaporkan berapa fork yang ditangani. Keluaran `[FORK]` tercetak di konsol node ini.
- **695**: tipe lain → `ERROR` (menjadi HTTP 400).

---


## RUTE_HTTP: tabel endpoint (dipakai server dan client)  _(baris 698–713)_

```python
 698  # ---------- transport HTTP ----------
 699  
 700  # Satu tabel rute dipakai server DAN client, jadi alamat endpoint tidak pernah
 701  # berbeda antara kedua sisi. Format: tipe pesan -> (metode HTTP, path).
 702  RUTE_HTTP = {
 703      "GET_CHAIN":       ("GET",  "/chain"),
 704      "NEW_BLOCK":       ("POST", "/blocks"),
 705      "GET_KEYS":        ("GET",  "/keys"),
 706      "REGISTER_AUTHOR": ("POST", "/keys"),
 707      "ADD_PEER":        ("POST", "/peers"),          # Tugas 4
 708      "GET_PEERS":       ("GET",  "/peers"),
 709      "RESOLVE":         ("POST", "/nodes/resolve"),  # Tugas 5
 710      "GET_STATUS":      ("GET",  "/status"),
 711  }
 712  _TIPE_DARI_RUTE = {rute: tipe for tipe, rute in RUTE_HTTP.items()}
 713  _PATH_DIKENAL = {path for _, path in RUTE_HTTP.values()}
```

- **Baris 700–701**: komentar: **satu** tabel dipakai server dan client, sehingga alamat endpoint tidak bisa berbeda di kedua sisi.
- **Baris 702–711**: dict `tipe pesan → (metode HTTP, path)` dengan delapan entri. Contoh: `"ADD_PEER": ("POST", "/peers")` artinya pesan `ADD_PEER` dikirim sebagai `POST /peers`. Komentar `# Tugas 4` dan `# Tugas 5` menandai dua endpoint dari soal.
- **`_TIPE_DARI_RUTE`**: *dict comprehension* `{rute: tipe for tipe, rute in RUTE_HTTP.items()}` yang **membalik** tabel: kunci `(metode, path)`, nilai tipe pesan. Dipakai server untuk mengetahui jenis pesan dari permintaan masuk.
- **`_PATH_DIKENAL`**: *set comprehension* berisi semua path yang ada. Dipakai untuk membedakan 404 (path tidak ada) dari 405 (path ada tetapi metode salah).

---


## _BodyError dan _status_http  _(baris 716–731)_

```python
 716  class _BodyError(Exception):
 717      def __init__(self, status, pesan):
 718          super().__init__(pesan)
 719          self.status = status
 720  
 721  
 722  def _status_http(metode: str, path: str, reply: dict) -> int:
 723      """Terjemahkan balasan (dict) menjadi kode status HTTP."""
 724      tipe = reply.get("type")
 725      if tipe == "REJECT":
 726          return 400 if path == "/peers" else 409     # format peer salah = 400; block/key ditolak = 409
 727      if tipe == "ERROR":
 728          return 400
 729      if metode == "POST" and path == "/peers" and "peers" in reply:
 730          return 201                                   # peer baru dibuat
 731      return 200
```

- **Baris 716–719**: exception buatan `_BodyError(status, pesan)`: pewarisan dari `Exception`, membawa kode status HTTP. `super().__init__(pesan)` mengisi teks galat.
- **`_status_http(metode, path, reply)`** menerjemahkan balasan `dict` menjadi kode status:
  - `REJECT` → **400** bila path `/peers` (format peer salah), selain itu **409** (block palsu/fork, key bentrok).
  - `ERROR` → **400**.
  - `POST /peers` yang berhasil menambah peer (balasan memuat `peers`) → **201 Created**.
  - selain itu **200**.
- `400 if path == "/peers" else 409` adalah ekspresi ternary.

---


## NodeHandler: menangani satu permintaan HTTP  _(baris 734–810)_

```python
 734  class NodeHandler(BaseHTTPRequestHandler):
 735      protocol_version = "HTTP/1.0"   # satu permintaan per koneksi (tanpa keep-alive)
 736      server_version = "TraceNode/1.0"
 737      timeout = 10                    # batas waktu baca per koneksi (detik)
 738  
 739      def log_message(self, format, *args):
 740          pass                        # dibisukan: konsol dipakai menu interaktif
 741  
 742      def _balas(self, status: int, reply: dict):
 743          data = json.dumps(reply).encode("utf-8")
 744          try:
 745              self.send_response(status)
 746              self.send_header("Content-Type", "application/json; charset=utf-8")
 747              self.send_header("Content-Length", str(len(data)))
 748              self.end_headers()
 749              self.wfile.write(data)
 750          except OSError:
 751              pass                    # klien sudah pergi
 752  
 753      def send_error(self, code, message=None, explain=None):
 754          # Galat tingkat protokol (request line rusak, metode tak dikenal, dst.)
 755          # juga dijawab JSON, bukan halaman HTML bawaan.
 756          self._balas(code, {"type": "ERROR",
 757                             "reason": message or self.responses.get(code, ("galat",))[0]})
 758  
 759      def _baca_body(self) -> dict:
 760          if self.headers.get("Transfer-Encoding"):
 761              raise _BodyError(411, "Transfer-Encoding tidak didukung; kirim Content-Length")
 762          teks = (self.headers.get("Content-Length") or "").strip()
 763          if not teks:
 764              return {}
 765          try:
 766              panjang = int(teks)
 767          except ValueError:
 768              raise _BodyError(400, "Content-Length tidak valid")
 769          if panjang < 0:
 770              raise _BodyError(400, "Content-Length tidak valid")
 771          if panjang > MAX_MSG_BYTES:
 772              raise _BodyError(413, "body terlalu besar")
 773          if panjang == 0:
 774              return {}
 775          mentah = self.rfile.read(panjang)
 776          if len(mentah) < panjang:
 777              raise _BodyError(400, "body tidak lengkap")
 778          try:
 779              obj = json.loads(mentah.decode("utf-8"))
 780          except (json.JSONDecodeError, UnicodeDecodeError):
 781              raise _BodyError(400, "JSON tidak valid")
 782          if not isinstance(obj, dict):
 783              raise _BodyError(400, "body harus berupa objek JSON")
 784          return obj
 785  
 786      def _proses(self):
 787          metode = self.command
 788          path = self.path.split("?", 1)[0].rstrip("/") or "/"
 789          tipe = _TIPE_DARI_RUTE.get((metode, path))
 790          if tipe is None:
 791              if path in _PATH_DIKENAL:
 792                  return self._balas(405, {"type": "ERROR",
 793                                           "reason": f"metode {metode} tidak didukung untuk {path}"})
 794              return self._balas(404, {"type": "ERROR", "reason": f"endpoint tidak dikenal: {path}"})
 795          try:
 796              body = self._baca_body() if metode != "GET" else {}
 797          except _BodyError as e:
 798              return self._balas(e.status, {"type": "ERROR", "reason": str(e)})
 799          msg = dict(body)
 800          msg["type"] = tipe          # tipe ditentukan rute, bukan isi body
 801          try:
 802              reply = handle_message(msg, self.server.chain_map, self.server.peers,
 803                                     self.server.owned_authors)
 804          except Exception as e:      # jangan biarkan thread mati tanpa balasan
 805              print(f"[NODE] Error memproses {metode} {path} dari {self.client_address[0]}: "
 806                    f"{type(e).__name__}: {e}")
 807              return self._balas(500, {"type": "ERROR", "reason": "pesan tidak dapat diproses"})
 808          self._balas(_status_http(metode, path, reply), reply)
 809  
 810      do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _proses
```

`class NodeHandler(BaseHTTPRequestHandler)` adalah **pewarisan**: kelas dasar mengurai request line dan header; kita hanya menambahkan perilaku. Satu objek `NodeHandler` dibuat untuk **tiap permintaan masuk**.
- **735–737**: `protocol_version = "HTTP/1.0"` = satu permintaan per koneksi, koneksi ditutup setelah dijawab (tidak ada koneksi menggantung). `timeout = 10` = batas waktu baca (detik), sehingga klien yang lambat atau tidak mengirim apa-apa tidak menahan thread selamanya.
- **739–740**: `log_message` ditimpa menjadi kosong. Tanpa ini setiap permintaan dicetak ke layar dan mengganggu menu interaktif.
- **742–751**: `_balas(status, reply)`: dict diubah ke JSON lalu `bytes`; `send_response` menulis status, dua header (`Content-Type`, `Content-Length`), `end_headers()` menutup header, `wfile.write` mengirim isi. `except OSError` karena klien bisa saja sudah pergi.
- **753–757**: `send_error` ditimpa: galat tingkat protokol (request line rusak, metode tak dikenal) juga dijawab JSON `{"type":"ERROR"}`, bukan halaman HTML bawaan. `self.responses` adalah dict teks status standar.
- **`_baca_body` (759–784)** membaca dan memvalidasi body, mengembalikan dict atau melempar `_BodyError`:
  - `Transfer-Encoding` ditolak (**411**): body harus berpanjang jelas.
  - `Content-Length` kosong → `{}`; bukan angka atau negatif → **400**; lebih dari `MAX_MSG_BYTES` (10 MB) → **413**, dan body **tidak dibaca**.
  - `self.rfile.read(panjang)` membaca tepat sebanyak itu; kurang → **400**.
  - JSON harus valid (**400**) dan harus berupa **objek** (`dict`), bukan list atau angka (**400**).
- **`_proses` (786–808)** adalah inti routing:
  1. `metode = self.command`; `path = self.path.split("?", 1)[0].rstrip("/") or "/"` membuang query string dan garis miring di akhir.
  2. `_TIPE_DARI_RUTE.get((metode, path))`: tidak ketemu → **405** bila path dikenal, selain itu **404**.
  3. Body dibaca (kecuali `GET`); `_BodyError` → status dari galat itu.
  4. `msg = dict(body); msg["type"] = tipe`: salinan body ditambah tipe dari **rute**, sehingga tipe tidak bisa dipalsukan lewat body.
  5. `handle_message(...)` dipanggil dengan state milik server (`self.server.chain_map` dst.). Exception apa pun → dicetak dan dijawab **500**, jadi thread tidak mati diam-diam.
  6. `_balas(_status_http(...), reply)` mengirim status dan JSON.
- **810**: `do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _proses`: penugasan berantai, satu fungsi diberi lima nama. `BaseHTTPRequestHandler` memanggil `do_<METODE>`; dengan semua diarahkan ke `_proses`, metode yang salah (mis. `DELETE /chain`) menjadi **405**, bukan galat 501 bawaan.

---


## NodeHTTPServer: server HTTP milik node  _(baris 813–828)_

```python
 813  class NodeHTTPServer(ThreadingHTTPServer):
 814      daemon_threads = True
 815      allow_reuse_address = True
 816      request_queue_size = 50
 817  
 818      def __init__(self, alamat, chain_map, peers=None, owned_authors=None):
 819          self.chain_map = chain_map
 820          self.peers = peers
 821          self.owned_authors = list(owned_authors or [])
 822          super().__init__(alamat, NodeHandler)
 823  
 824      def server_bind(self):
 825          # HTTPServer.server_bind memanggil getfqdn() yang bisa lambat (DNS) dan
 826          # tidak dibutuhkan di sini.
 827          socketserver.TCPServer.server_bind(self)
 828          self.server_name, self.server_port = self.server_address[:2]
```

- **813**: `ThreadingHTTPServer` = `HTTPServer` + `ThreadingMixIn`: **satu thread per permintaan**, jadi beberapa node bisa mengirim bersamaan tanpa saling menunggu.
- **814–816**: `daemon_threads = True` (thread permintaan tidak menahan proses saat keluar), `allow_reuse_address = True` (bisa restart cepat di port yang sama), `request_queue_size = 50` (antrean koneksi yang menunggu).
- **818–822**: menyimpan `chain_map`, `peers`, `owned_authors` pada objek server; handler mengaksesnya lewat `self.server`. `peers` adalah **objek list yang sama** dengan yang dipakai menu CLI, jadi peer yang masuk lewat `POST /peers` langsung terlihat. `super().__init__(alamat, NodeHandler)` membuat dan mengikat socket.
- **824–828**: `server_bind` ditimpa untuk menghindari `getfqdn()` bawaan `HTTPServer` yang bisa lambat (pencarian DNS) dan tidak dibutuhkan. `TCPServer.server_bind(self)` mengikat socket; lalu `server_name` dan `server_port` diisi dari `server_address`.

---


## buat_server, terima_koneksi, start_server  _(baris 831–842)_

```python
 831  def buat_server(host: str, port: int, chain_map: dict, peers=None, owned_authors=None):
 832      srv = NodeHTTPServer((host, port), chain_map, peers, owned_authors)
 833      print(f"[NODE] Mendengarkan HTTP di http://{host}:{port}")
 834      return srv
 835  
 836  
 837  def terima_koneksi(srv):
 838      srv.serve_forever(poll_interval=0.2)
 839  
 840  
 841  def start_server(host: str, port: int, chain_map: dict, peers=None, owned_authors=None):
 842      terima_koneksi(buat_server(host, port, chain_map, peers, owned_authors))
```

- **`buat_server` (831–834)**: membuat `NodeHTTPServer` pada `(host, port)` dengan state node, mencetak alamat `http://host:port`, dan mengembalikannya.
- **`terima_koneksi` (837–838)**: `srv.serve_forever(poll_interval=0.2)` = loop menerima permintaan tanpa henti; dijalankan di thread latar oleh `run_node`.
- **`start_server` (841–842)**: gabungan keduanya (membuat lalu langsung menerima). Dipakai skrip uji untuk menjalankan "peer jahat" di thread.

---


## send_message: sisi klien (HTTP)  _(baris 845–880)_

```python
 845  # ---------- client (menghubungi peer) ----------
 846  
 847  def send_message(host: str, port: int, msg: dict, timeout=5) -> dict:
 848      """Kirim satu pesan ke peer lewat HTTP dan kembalikan balasannya (dict).
 849      Antarmuka dict-in/dict-out dipertahankan supaya seluruh pemanggil lama
 850      tidak berubah; tipe pesan diterjemahkan ke (metode, path) lewat RUTE_HTTP.
 851      Kegagalan jaringan/protokol dilaporkan sebagai OSError."""
 852      tipe = msg.get("type")
 853      rute = RUTE_HTTP.get(tipe)
 854      if rute is None:
 855          return {"type": "ERROR", "reason": f"tipe pesan tidak dikenal: {tipe}"}
 856      metode, path = rute
 857      conn = http.client.HTTPConnection(host, port, timeout=timeout)
 858      try:
 859          if metode == "GET":
 860              conn.request("GET", path)
 861          else:
 862              isi = json.dumps({k: v for k, v in msg.items() if k != "type"}).encode("utf-8")
 863              conn.request(metode, path, body=isi, headers={"Content-Type": "application/json"})
 864          resp = conn.getresponse()
 865          mentah = resp.read(MAX_MSG_BYTES + 1)
 866      except http.client.HTTPException as e:
 867          raise OSError(f"balasan HTTP tidak valid: {e}")
 868      finally:
 869          conn.close()
 870      if len(mentah) > MAX_MSG_BYTES:
 871          raise OSError("balasan terlalu besar")
 872      if not mentah:
 873          return {"type": "ERROR", "reason": "tidak ada balasan"}
 874      try:
 875          balasan = json.loads(mentah.decode("utf-8"))
 876      except (json.JSONDecodeError, UnicodeDecodeError):
 877          return {"type": "ERROR", "reason": "balasan peer bukan JSON"}
 878      if not isinstance(balasan, dict):
 879          return {"type": "ERROR", "reason": "balasan peer bukan objek JSON"}
 880      return balasan
```

- **Antarmuka tetap dict masuk, dict keluar**: pemanggil lama (`sinkron_peer`, `broadcast_block`, dst.) tidak berubah; hanya isi fungsinya yang kini berbicara HTTP.
- **852–856**: `RUTE_HTTP.get(tipe)` menerjemahkan tipe pesan menjadi `(metode, path)`. Tipe tidak dikenal → dict `ERROR` tanpa menyentuh jaringan.
- **857**: `http.client.HTTPConnection(host, port, timeout=timeout)` membuat koneksi (belum mengirim apa-apa).
- **859–865**: `GET` dikirim tanpa body. Metode lain: body = isi pesan **tanpa kunci `"type"`** (`{k: v for k, v in msg.items() if k != "type"}` = dict comprehension), diubah ke JSON dan dikirim dengan header `Content-Type: application/json`. `getresponse()` menunggu balasan; `resp.read(MAX_MSG_BYTES + 1)` membaca paling banyak 10 MB + 1 byte.
- **866–869**: balasan HTTP yang cacat (`HTTPException`) diubah menjadi `OSError`, sehingga seluruh kode lama yang menangkap `OSError` (peer mati, timeout, atau balasan rusak) tetap cukup. `finally` selalu menutup koneksi.
- **870–880**: balasan lebih dari 10 MB → `OSError`; kosong, bukan JSON, atau JSON yang **bukan objek** → dict `ERROR`. Dengan begitu pemanggil selalu menerima dict, dan balasan peer yang rusak tidak bisa mematikan node.

---


## kirim_keys_ke_peer  _(baris 884–892)_

```python
 884  def kirim_keys_ke_peer(host, port, owned_authors):
 885      """Kirim public key tiap author milik node ini ke satu peer."""
 886      for author in owned_authors:
 887          _, public_key = get_or_create_author(author)
 888          payload = {"type": "REGISTER_AUTHOR", "author": author,
 889                     "public_key_pem": public_key_to_pem(public_key)}
 890          reply = send_message(host, port, payload)
 891          if reply.get("type") != "OK":
 892              print(f"[NODE] Peer {host}:{port} menolak key '{author}': {reply.get('reason')}")
```

Untuk tiap aktor lokal: ambil public key (`_, public_key = ...` mengabaikan private key), bungkus dalam pesan `REGISTER_AUTHOR`, kirim; bila balasan bukan `OK`, cetak alasan penolakan.

---


## tarik_keys  _(baris 895–908)_

```python
 895  def tarik_keys(host, port) -> int:
 896      """Ambil public key yang dikenal peer. Return jumlah key baru."""
 897      reply = send_message(host, port, {"type": "GET_KEYS"})
 898      keys = reply.get("keys")
 899      if reply.get("type") != "KEYS" or not isinstance(keys, dict):
 900          return 0
 901      baru = 0
 902      for author, pem in keys.items():
 903          ok, alasan = daftarkan_key(author, pem)
 904          if ok and alasan == "terdaftar":
 905              baru += 1
 906          elif not ok:
 907              print(f"[NODE] Key '{author}' dari {host}:{port} diabaikan: {alasan}")
 908      return baru
```

- Kirim `GET_KEYS`; validasi balasan harus `KEYS` dan `keys` berupa dict.
- `keys.items()` mengulang pasangan `(author, pem)`. Tiap key didaftarkan; `baru += 1` hanya bila hasilnya `"terdaftar"` (bukan `"sudah terdaftar"`). `elif not ok` mencetak key yang ditolak.

---


## _konflik_id  _(baris 911–917)_

```python
 911  def _konflik_id(d, chain_map: dict) -> bool:
 912      """True jika id block ini sudah ada di chain lokal dengan isi berbeda."""
 913      if check_block_format(d):
 914          return False
 915      blk = block_from_dict(d)
 916      lama = chain_map.get(blk.id)
 917      return lama is not None and compute_hash(lama) != compute_hash(blk)
```

`True` bila id block ini sudah ada di chain lokal dengan hash berbeda. Format salah dianggap bukan konflik. `lama is not None and ...` memakai *short-circuit*: bagian kanan hanya dievaluasi bila kiri benar.

---


## sync_chain_from_peer: tarik chain peer  _(baris 920–943)_

```python
 920  def sync_chain_from_peer(host: str, port: int, chain_map: dict):
 921      """Tarik chain peer. Tanpa konflik id: TIAP block divalidasi penuh lalu
 922      digabung. Ada konflik id (fork): jalankan resolve_fork().
 923      Return (diterima, ditolak, info_fork atau None)."""
 924      reply = send_message(host, port, {"type": "GET_CHAIN"})
 925      blocks = reply.get("blocks")
 926      if reply.get("type") != "CHAIN" or not isinstance(blocks, list):
 927          return 0, 0, None
 928      kandidat = [d for d in blocks if isinstance(d, dict) and _int(d.get("id"))]
 929      sumber = f"{host}:{port}"
 930      with CHAIN_LOCK:
 931          if any(_konflik_id(d, chain_map) for d in kandidat):
 932              info = resolve_fork(chain_map, kandidat, sumber)
 933              cetak_fork(info)
 934              return info["ditambah"], len(info["peer_ditolak"]), info
 935          ditambah = ditolak = 0
 936          for d in sorted(kandidat, key=lambda x: x["id"]):
 937              kode, alasan = terima_block(d, chain_map)
 938              if kode == "BARU":
 939                  ditambah += 1
 940              elif kode in ("TOLAK", "FORK"):
 941                  ditolak += 1
 942                  print(f"[NODE] Block {d['id']} dari {sumber} ditolak saat sinkron: {alasan}")
 943      return ditambah, ditolak, None
```

- **924–927**: kirim `GET_CHAIN`, validasi balasan.
- **928**: saring block yang dict dan punya id bulat.
- **930**: seluruh proses di dalam `CHAIN_LOCK`.
- **931–934**: `any(_konflik_id(d, chain_map) for d in kandidat)` benar bila ada satu saja konflik → jalankan `resolve_fork`, `cetak_fork`, lalu return.
- **935–942**: tanpa konflik: tiap block (urut id) lewat `terima_block`, hitung `ditambah` dan `ditolak`. `ditambah = ditolak = 0` memberi nilai awal sama ke dua variabel.
- **943**: return `(ditambah, ditolak, None)`.

---


## dorong_chain_ke_peer  _(baris 946–960)_

```python
 946  def dorong_chain_ke_peer(host, port, chain_map: dict):
 947      """Kirim semua block lokal ke peer (peer memvalidasi sendiri)."""
 948      with CHAIN_LOCK:
 949          daftar = [block_to_dict(chain_map[i]) for i in sorted(chain_map)]
 950      diterima = ditolak = 0
 951      ada_fork = False
 952      for d in daftar:
 953          reply = send_message(host, port, {"type": "NEW_BLOCK", "block": d})
 954          if reply.get("type") == "OK":
 955              diterima += 1
 956          else:
 957              ditolak += 1
 958              if "fork" in str(reply.get("reason", "")).lower():
 959                  ada_fork = True
 960      return diterima, ditolak, ada_fork
```

Salin chain lokal di dalam lock, lalu kirim tiap block sebagai `NEW_BLOCK` (urut id). Peer memvalidasi sendiri. Hitung yang diterima/ditolak; bila alasan penolakan mengandung kata "fork", `ada_fork = True`.

---


## sinkron_peer: sinkron dua arah  _(baris 963–981)_

```python
 963  def sinkron_peer(host, port, chain_map, owned_authors, verbose=True) -> bool:
 964      """Sinkron dua arah dengan satu peer: tukar public key, tarik chain,
 965      lalu dorong chain lokal. Return False kalau peer tidak terjangkau."""
 966      try:
 967          kirim_keys_ke_peer(host, port, owned_authors)
 968          key_baru = tarik_keys(host, port)
 969          tambah, tolak_tarik, _info = sync_chain_from_peer(host, port, chain_map)
 970          dorong_ok, dorong_tolak, ada_fork = dorong_chain_ke_peer(host, port, chain_map)
 971      except OSError as e:
 972          print(f"[NODE] Gagal menghubungi {host}:{port}: {e}")
 973          return False
 974      if verbose:
 975          print(f"[NODE] Sinkron {host}:{port} -> key baru: {key_baru} | "
 976                f"block diterima: {tambah} (ditolak {tolak_tarik}) | "
 977                f"block terkirim: {dorong_ok} (ditolak peer {dorong_tolak})")
 978      if dorong_tolak and ada_fork:
 979          print(f"[NODE] Peer {host}:{port} menolak block lokal karena fork; peer akan "
 980                f"menyusul saat ia sinkron (menu 3 di peer).")
 981      return True
```

Urutan: kirim key lokal → tarik key peer → tarik chain → dorong chain. Jika `OSError` (peer mati/tidak terjangkau): cetak pesan dan `return False`. Bila `verbose`, ringkasan dicetak. Jika peer menolak karena fork, diberi saran agar peer menjalankan menu 3.
- Catatan HTTP: `OSError` mencakup koneksi ditolak, timeout, dan balasan HTTP cacat (yang diubah `send_message` menjadi `OSError`), jadi satu `except` menutup semua kegagalan jaringan.

---


## broadcast_block: siarkan block baru ke semua peer  _(baris 984–997)_

```python
 984  def broadcast_block(block: Block, peers, chain_map, owned_authors):
 985      payload = {"type": "NEW_BLOCK", "block": block_to_dict(block)}
 986      # >>> UBAH (Tugas 4): `peers` -> `list(peers)`.
 987      # >>> Alasan: list peers bisa bertambah dari thread server (ADD_PEER) saat loop
 988      # >>> berjalan; salinan mencegah error "list changed size during iteration".
 989      for host, port in list(peers):
 990          try:
 991              reply = send_message(host, port, payload)
 992              print(f"[NODE] Kirim block {block.id} ke {host}:{port} -> {reply}")
 993              if reply.get("type") == "REJECT":
 994                  print(f"[NODE] Ditolak {host}:{port}; mencoba sinkron dua arah...")
 995                  sinkron_peer(host, port, chain_map, owned_authors)
 996          except OSError as e:
 997              print(f"[NODE] Gagal kirim block {block.id} ke {host}:{port}: {e}")
```

- `for host, port in list(peers):` memakai **salinan** list, supaya tidak muncul error "list changed size during iteration" bila thread server menambah peer saat loop berjalan.
- Bila peer membalas `REJECT`, node otomatis memicu `sinkron_peer`. `OSError` per peer ditangkap sehingga satu peer mati tidak menghentikan pengiriman ke yang lain.

---


## parse_satu_peer: urai 'host:port'  _(baris 1000–1011)_

```python
1000  # ---------- CLI node ----------
1001  
1002  def parse_satu_peer(teks):
1003      pesan = f"Format peer salah: '{teks}' (harus host:port, contoh 192.168.1.5:9001)"
1004      try:
1005          host, port = teks.rsplit(":", 1)
1006          port = int(port)
1007      except ValueError:
1008          raise ValueError(pesan)
1009      if not host or not (1 <= port <= 65535):
1010          raise ValueError(pesan)
1011      return (host, port)
```

- `teks.rsplit(":", 1)` memecah dari **kanan** sebanyak satu kali: `"192.168.1.5:9001"` → `["192.168.1.5", "9001"]` (unpacking ke `host, port`).
- `int(port)` bisa melempar `ValueError`; ditangkap lalu dilempar ulang dengan pesan yang lebih jelas (`raise ValueError(pesan)`).
- Host tidak boleh kosong dan port 1–65535. Hasil: tuple `(host, port)`.

---


## parse_peers  _(baris 1014–1021)_

```python
1014  def parse_peers(peer_args):
1015      peers = []
1016      for p in peer_args or []:
1017          try:
1018              peers.append(parse_satu_peer(p))
1019          except ValueError as e:
1020              raise SystemExit(str(e))
1021      return peers
```

`peer_args or []` menangani `None`. Satu peer salah format → `raise SystemExit(str(e))` menghentikan program dengan pesan itu.

---


## kelola_peer: menu 6  _(baris 1024–1057)_

```python
1024  def kelola_peer(peers, chain_map, owned_authors):
1025      """Tambah/hapus peer saat node berjalan. Menghapus peer = memutus
1026      hubungan keluar (berguna untuk membuat fork saat eksperimen)."""
1027      print("Peer saat ini:")
1028      for i, (h, p) in enumerate(list(peers), 1):   # >>> UBAH: list(peers), alasan sama seperti di atas
1029          print(f"  {i}) {h}:{p}")
1030      if not peers:
1031          print("  (kosong)")
1032      aksi = input("(t)ambah / (h)apus / Enter=kembali: ").strip().lower()
1033      if aksi == "t":
1034          try:
1035              peer = parse_satu_peer(input("Alamat peer (host:port): ").strip())
1036          except ValueError as e:
1037              print(e)
1038              return
1039          # >>> UBAH: cek + append dibungkus PEER_LOCK, karena thread server
1040          # >>> (ADD_PEER) bisa mengubah list yang sama pada saat bersamaan.
1041          with PEER_LOCK:
1042              if peer in peers:
1043                  print("Peer sudah ada.")
1044                  return
1045              peers.append(peer)
1046          sinkron_peer(peer[0], peer[1], chain_map, owned_authors)
1047      elif aksi == "h":
1048          if not peers:
1049              return
1050          n = input("Nomor peer yang dihapus: ").strip()
1051          # >>> UBAH: pop dibungkus PEER_LOCK (alasan sama)
1052          with PEER_LOCK:
1053              if n.isdigit() and 1 <= int(n) <= len(peers):
1054                  h, p = peers.pop(int(n) - 1)
1055                  print(f"Peer {h}:{p} dihapus (tidak lagi dihubungi node ini).")
1056              else:
1057                  print("Nomor tidak valid.")
```

- **1027–1031**: tampilkan peer dengan `enumerate(list(peers), 1)`; pola `for i, (h, p) in ...` = unpacking bersarang.
- **1032**: `input(...).strip().lower()` membaca pilihan pengguna, membuang spasi, dan menjadikannya huruf kecil.
- **862–875 (tambah)**: urai alamat; di dalam `PEER_LOCK` cek duplikat lalu `append`; setelah lock dilepas langsung `sinkron_peer`.
- **876–886 (hapus)**: `n.isdigit()` memeriksa input angka; `peers.pop(int(n) - 1)` menghapus (indeks list mulai dari 0). Menghapus peer = memutus hubungan keluar, berguna untuk mensimulasikan partisi jaringan/fork.

---


## tampilkan_validasi: menu 4  _(baris 1060–1069)_

```python
1060  def tampilkan_validasi(chain_map):
1061      with CHAIN_LOCK:
1062          if not chain_map:
1063              print("Chain kosong.")
1064              return
1065          punya_anak = {b.parent_id for b in chain_map.values() if b.parent_id is not None}
1066          ujung = [i for i in sorted(chain_map) if i not in punya_anak]
1067          for i in ujung:
1068              valid, msg = is_chain_valid(chain_map[i], chain_map)
1069              print(f"Rantai berujung di block {i}: valid={valid} | {msg}")
```

- **1065**: *set comprehension* `{b.parent_id for ...}` mengumpulkan semua id yang menjadi parent.
- **1066**: `ujung` = id yang bukan parent siapa pun (ujung rantai).
- **1067–1069**: tiap ujung divalidasi dengan `is_chain_valid` lalu dicetak.

---


## run_node (1): inisialisasi  _(baris 1072–1094)_

```python
1072  def run_node(host, port, owned_authors, peers, data_dir):
1073      chain_map = {}
1074  
1075      for author in owned_authors:
1076          load_or_create_keys(author, data_dir)
1077  
1078      # >>> TAMBAH (Tugas 7): muat chain dari disk + jalankan autosave.
1079      # >>> Letak: SETELAH key dimuat (validasi butuh key) dan SEBELUM server/sinkron
1080      # >>> dimulai, supaya chain hasil muat ikut dikirim ke peer saat sinkron awal.
1081      chain_file = os.path.join(data_dir, "chain.json")   # di Docker: ikut volume ./data/nodeX
1082      muat_chain(chain_map, chain_file)                   # pulihkan chain (divalidasi ulang)
1083      threading.Thread(target=autosave, args=(chain_map, chain_file), daemon=True).start()
1084  
1085      srv = buat_server(host, port, chain_map, peers, owned_authors)
1086      # >>> UBAH (Tugas 4): tambah `peers` di args. Ini list YANG SAMA dengan yang
1087      # >>> dipakai menu 1/3/6, jadi peer yang masuk lewat ADD_PEER langsung
1088      # >>> terlihat oleh menu dan broadcast tanpa restart.
1089      threading.Thread(target=terima_koneksi, args=(srv,), daemon=True).start()
1090  
1091      for h, p in list(peers):   # >>> UBAH: list(peers) (alasan: lihat broadcast_block)
1092          sinkron_peer(h, p, chain_map, owned_authors)
1093  
1094      print(f"\n=== NODE aktif di {host}:{port} | aktor lokal: {owned_authors or '(tidak ada)'} ===")
```

- **1073**: `chain_map = {}` = penyimpanan chain `{id: Block}`.
- **1075–1076**: muat/buat key semua aktor lokal.
- **1081–1083**: tentukan `chain_file`, muat chain dari disk, lalu jalankan thread `autosave`. Letaknya sengaja setelah key dimuat (validasi butuh key) dan sebelum sinkron (agar chain hasil muat ikut dikirim ke peer).
- **1085**: membuat server HTTP dengan state node (`chain_map`, `peers`, `owned_authors`). **1089**: thread `terima_koneksi(srv)` berjalan menerima permintaan; `peers` yang diteruskan adalah **objek list yang sama** dengan yang dipakai menu.
- **1091–1092**: sinkron awal ke tiap peer (HTTP lewat `send_message`).
- **1094**: banner status; `owned_authors or '(tidak ada)'` menampilkan teks cadangan bila list kosong.

---


## run_node (2): loop menu  _(baris 1095–1104)_

```python
1095      try:
1096          while True:
1097              print("\n1) Tambah transaksi baru (pakai salah satu aktor lokal)")
1098              print("2) Tampilkan riwayat chain lokal")
1099              print("3) Sinkron dua arah dengan peer")
1100              print("4) Validasi chain lokal")
1101              print("5) Tampilkan chain utama & fork")
1102              print("6) Kelola peer (tambah/hapus)")
1103              print("7) Keluar")
1104              pilihan = input("Pilih menu: ").strip()
```

- `try: while True:` = loop menu tanpa henti, dibungkus `try` untuk menangkap Ctrl+C/EOF di bawah.
- Menu dicetak, lalu `pilihan = input("Pilih menu: ").strip()`.

---


## run_node (3): menu 1 – tambah transaksi  _(baris 1106–1139)_

```python
1106              if pilihan == "1":
1107                  if not owned_authors:
1108                      print("Node ini tidak memiliki aktor (private key) manapun, tidak bisa menulis block.")
1109                      continue
1110                  author = pilih_dari_daftar(owned_authors, "author (aktor lokal)")
1111                  part_id = input("Part ID: ").strip()
1112                  part_name = input("Nama part: ").strip()
1113                  origin = input("Origin: ").strip()
1114                  destination = input("Destination: ").strip()
1115                  vehicle_id = input("Vehicle ID: ").strip()
1116                  status = pilih_dari_daftar(list(ALLOWED_TRANSITIONS.keys()), "status")
1117                  parent_raw = input("Parent block id (kosongkan jika block pertama): ").strip()
1118                  try:
1119                      parent_id = int(parent_raw) if parent_raw else None
1120                  except ValueError:
1121                      print("Parent block id harus berupa angka.")
1122                      continue
1123  
1124                  # Sinkron dulu supaya id block baru tidak bentrok dengan peer.
1125                  for h, p in list(peers):   # >>> UBAH: list(peers)
1126                      sinkron_peer(h, p, chain_map, owned_authors, verbose=False)
1127  
1128                  try:
1129                      with CHAIN_LOCK:
1130                          blk, elapsed = add_transaction(chain_map, author, part_id, part_name,
1131                                                          origin, destination, vehicle_id, status,
1132                                                          parent_id=parent_id)
1133                      percobaan = getattr(blk, "mining_attempts", "?")
1134                      print(f"-> Block {blk.id} berhasil ditambang lokal (difficulty={DIFFICULTY!r}, "
1135                            f"nonce={blk.nonce}, percobaan={percobaan}, waktu={elapsed:.3f}s), "
1136                            f"menyiarkan ke peer...")
1137                      broadcast_block(blk, peers, chain_map, owned_authors)
1138                  except (TransactionRejected, ConsensusRejected) as e:
1139                      print("Ditolak:", e)
```

- **1107–1109**: tidak punya aktor lokal → pesan dan `continue` (kembali ke awal loop).
- **1110–1117**: pilih aktor lewat `pilih_dari_daftar`, isi data transaksi dengan `input`. `list(ALLOWED_TRANSITIONS.keys())` = daftar status yang diizinkan.
- **1118–1122**: `int(parent_raw) if parent_raw else None` (ternary); input bukan angka → `ValueError` → pesan + `continue`.
- **1124–1126**: **sinkron dulu** dengan semua peer (`verbose=False`) agar id block baru tidak bentrok.
- **1128–1132**: `with CHAIN_LOCK:` memanggil `add_transaction(...)` (menambang block lewat PoW string: hash harus diawali `DIFFICULTY`). Hasilnya tuple `(blk, elapsed)`.
- **1133**: `getattr(blk, "mining_attempts", "?")` mengambil atribut dengan nilai cadangan.
- **1134–1136**: f-string; `{DIFFICULTY!r}` mencetak difficulty (string global) lengkap dengan tanda kutip, `{elapsed:.3f}` mencetak 3 angka desimal.
- **1137**: `broadcast_block(...)` menyiarkan ke peer.
- **1138–1139**: `except (TransactionRejected, ConsensusRejected) as e` menangkap penolakan dari aturan bisnis/konsensus.

---


## run_node (4): menu 2–7  _(baris 1141–1165)_

```python
1141              elif pilihan == "2":
1142                  with CHAIN_LOCK:
1143                      print_chain(chain_map)
1144  
1145              elif pilihan == "3":
1146                  if not peers:
1147                      print("Tidak ada peer. Jalankan node dengan --peers host:port.")
1148                  for h, p in list(peers):   # >>> UBAH: list(peers)
1149                      sinkron_peer(h, p, chain_map, owned_authors)
1150  
1151              elif pilihan == "4":
1152                  tampilkan_validasi(chain_map)
1153  
1154              elif pilihan == "5":
1155                  with CHAIN_LOCK:
1156                      tampilkan_fork(chain_map)
1157  
1158              elif pilihan == "6":
1159                  kelola_peer(peers, chain_map, owned_authors)
1160  
1161              elif pilihan == "7":
1162                  print("Node berhenti.")
1163                  break
1164              else:
1165                  print("Pilihan tidak dikenal.")
```

- **2**: `print_chain` di dalam `CHAIN_LOCK`.
- **3**: sinkron manual ke semua peer (pesan bila tidak ada peer).
- **4**: `tampilkan_validasi`.
- **5**: `tampilkan_fork` di dalam lock.
- **6**: `kelola_peer`.
- **7**: cetak "Node berhenti." lalu `break` keluar dari loop.
- `else`: "Pilihan tidak dikenal".
- Rantai `if / elif / else` memilih tepat satu cabang.

---


## run_node (5): except & finally  _(baris 1166–1177)_

```python
1166      except (EOFError, KeyboardInterrupt):
1167          print("\nNode berhenti.")
1168      finally:
1169          # >>> TAMBAH (Tugas 7): simpan terakhir kali SETIAP kali node keluar
1170          # >>> (menu 7, Ctrl+C, maupun EOF). `finally` menjamin ini selalu jalan,
1171          # >>> jadi tidak perlu menulis simpan_chain di dua tempat.
1172          # >>> Autosave tiap 2 detik tetap berguna untuk kasus proses dimatikan paksa.
1173          try:
1174              simpan_chain(chain_map, chain_file)
1175              print(f"[NODE] Chain disimpan ke {chain_file}")
1176          except OSError as e:
1177              print(f"[NODE] Gagal menyimpan chain: {e}")
```

- `except (EOFError, KeyboardInterrupt)`: menangkap Ctrl+D (EOF) dan Ctrl+C agar keluar dengan rapi.
- `finally:` **selalu** dijalankan, apa pun cara keluarnya (menu 7, Ctrl+C, EOF). Di sini `simpan_chain` dipanggil terakhir kali; jika gagal (`OSError`), pesannya dicetak. Ini sebabnya penyimpanan tidak perlu ditulis di banyak tempat.

---


## Titik masuk program (__main__)  _(baris 1180–1197)_

```python
1180  if __name__ == "__main__":
1181      parser = argparse.ArgumentParser(description="Jalankan satu node blockchain traceability.")
1182      parser.add_argument("--host", default="0.0.0.0", help="alamat bind server node ini")
1183      parser.add_argument("--port", type=int, required=True, help="port server node ini")
1184      parser.add_argument("--authors", nargs="*", default=[],
1185                           help="aktor yang PRIVATE KEY-nya dipegang node ini, contoh: Produsen Distributor")
1186      parser.add_argument("--peers", nargs="*", default=[],
1187                           help="daftar peer format host:port, contoh: 192.168.1.5:9001")
1188      parser.add_argument("--data-dir", default=None,
1189                           help="folder penyimpanan key & chain.json (default: data_<port>)")
1190      args = parser.parse_args()
1191  
1192      for a in args.authors:
1193          if a not in AUTHORIZED_ACTORS:
1194              parser.error(f"author '{a}' tidak dikenal; pilih dari: {sorted(AUTHORIZED_ACTORS)}")
1195  
1196      run_node(args.host, args.port, args.authors, parse_peers(args.peers),
1197               args.data_dir or f"data_{args.port}")
```

- `if __name__ == "__main__":` hanya jalan bila file dieksekusi langsung (bukan saat di-`import`, misalnya oleh skrip uji).
- **1181**: `argparse.ArgumentParser(description=...)` membuat parser.
- **1182–1189**: `add_argument` mendefinisikan opsi: `--host` (default `0.0.0.0` = semua antarmuka jaringan), `--port` (`type=int`, `required=True`), `--authors` dan `--peers` (`nargs="*"` = nol atau lebih nilai), `--data-dir` (default `None`).
- **1190**: `args = parser.parse_args()` membaca argumen. `--data-dir` otomatis menjadi `args.data_dir` (tanda `-` jadi `_`).
- **1192–1194**: tiap nama aktor divalidasi terhadap `AUTHORIZED_ACTORS`; salah → `parser.error(...)` menampilkan pesan lalu keluar. `sorted(AUTHORIZED_ACTORS)` mengurutkan untuk tampilan.
- **1196–1197**: memanggil `run_node(...)`. `args.data_dir or f"data_{args.port}"` memakai `data_<port>` bila `--data-dir` tidak diisi.

---


## [ARSIP] transport TCP lama (komentar di paling bawah file)  _(baris 1201–1212)_

```python
1201  # =====================================================================
1202  # [ARSIP] TRANSPORT TCP LAMA (JSON satu baris per pesan)
1203  # =====================================================================
1204  # Semua baris di bawah ini adalah KOMENTAR (tidak dijalankan). Ini lapisan
1205  # jaringan asli sebelum diganti HTTP (revisi 4). handle_message() dan seluruh
1206  # logika blockchain TIDAK berubah; hanya cara pesan dikirim/diterima.
1207  #
1208  # Cara mengaktifkan kembali: kembalikan potongan di bawah, hapus bagian
1209  # "transport HTTP" (RUTE_HTTP .. send_message), kembalikan `import socket`,
1210  # dan di run_node kembalikan dua baris pembuatan server yang tertera di (3).
1211  #
1212  # --- (1) Server: _recv_line ---
```

- Semua baris sesudah penanda `[ARSIP]` sampai akhir file adalah **komentar** (tiap baris diawali `#`), jadi tidak dijalankan. Isinya kode lapisan jaringan **TCP asli** sebelum diganti HTTP: `_recv_line`, `_handle_conn`, versi TCP dari `buat_server`/`terima_koneksi`/`start_server`/`send_message`, dan dua baris pembuatan server di `run_node`.
- Disimpan utuh agar bisa ditunjukkan dan diaktifkan kembali. Cara mengaktifkan kembali ada di komentar itu sendiri.
- Logika blockchain (`handle_message`, validasi, fork, penyimpanan) **tidak ikut berubah**; hanya cara pesan dikirim dan diterima.

---


## Ringkasan sintaks Python yang sering muncul

| Sintaks | Arti |
|---|---|
| `with X:` | pakai resource/lock dan lepaskan otomatis di akhir blok |
| `try / except / else / finally` | tangani error; `else` jalan bila tak ada error; `finally` selalu jalan |
| `f"...{x}..."` | f-string: menyisipkan nilai variabel ke teks |
| `[x for x in ...]`, `{k: v for ...}`, `{x for ...}` | list / dict / set comprehension |
| `lambda a: ...` | fungsi anonim satu ekspresi |
| `a, b = fungsi()` | unpacking tuple |
| `x if kondisi else y` | ekspresi ternary |
| `def f(x, y=None)` | parameter dengan nilai default |
| `x: int`, `-> dict` | type hint (dokumentatif) |
| `threading.Thread(target=f, args=(...), daemon=True).start()` | jalankan `f` paralel di thread latar |
| `class A(B):` | kelas turunan: mewarisi semua metode `B` dan boleh menimpa (override) sebagian |
| `super().__init__(...)` | memanggil `__init__` kelas induk |
| `a = b = c = f` | penugasan berantai: satu nilai diberi beberapa nama |
| `{kunci: nilai for ... in ...}` / `{x for ...}` | dict / set comprehension (dipakai `_TIPE_DARI_RUTE`, `_PATH_DIKENAL`) |
| `raise X(...)` | melempar exception; ditangkap `except X` di pemanggil |
| `http.client.HTTPConnection(host, port, timeout=5)` | client HTTP bawaan; `.request(metode, path, body=..., headers=...)` lalu `.getresponse()` |
