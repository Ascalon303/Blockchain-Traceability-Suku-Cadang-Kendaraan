"""
node.py -- lapisan jaringan untuk blockchain traceability (versi 2 laptop)

Tiap laptop menjalankan file ini sebagai satu NODE. Tiap node "memiliki"
sebagian aktor (mis. laptop 1 = Produsen & Distributor, laptop 2 = Dealer &
Bengkel): private key aktor HANYA ada di laptop pemiliknya (disimpan di
--data-dir/keys/). Node lain hanya menerima PUBLIC KEY-nya supaya bisa
memverifikasi signature, tanpa bisa membuka isi transaksi.

Transport: HTTP (revisi 4; sebelumnya TCP dengan JSON satu baris per pesan).
Server memakai http.server.ThreadingHTTPServer dan client memakai
http.client (pustaka standar, tanpa dependensi baru). Body dan balasan
berupa JSON. Port dan alamat peer tidak berubah (host:port).

  Endpoint                 Body (JSON)                         Balasan / status
  GET  /chain              -                                   200 {"type":"CHAIN","blocks":[...]}
  POST /blocks             {"block": {...}}                    200 OK / 409 REJECT / 400 ERROR
  GET  /keys               -                                   200 {"type":"KEYS","keys":{author: pem}}
  POST /keys               {"author":..,"public_key_pem":..}   200 OK / 409 REJECT
  POST /peers              {"peer": "host:port"}               201 OK / 200 (sudah ada) / 400 REJECT
  GET  /peers              -                                   200 {"type":"PEERS","peers":[...]}
  POST /nodes/resolve      -                                   200 hasil sinkron + resolusi fork
  GET  /status             -                                   200 ringkasan node

  Kode status: 200/201 sukses, 400 permintaan cacat, 404 path tidak dikenal,
  405 metode salah, 409 ditolak (block palsu/fork, key bentrok), 411/413
  ukuran body bermasalah, 500 galat internal. Isi balasan tetap memuat
  "type" (OK/REJECT/ERROR/...) seperti protokol TCP lama.

  Contoh: curl -X POST localhost:9001/peers -H "Content-Type: application/json" \
               -d '{"peer": "localhost:9002"}'

  # >>> TAMBAH (Tugas 4): POST /peers (sebelumnya pesan TCP ADD_PEER)
  # >>> TAMBAH (Tugas 5): POST /nodes/resolve (sebelumnya hanya lewat menu 3)

Kode transport TCP lama tidak dihapus: ada sebagai komentar [ARSIP] di paling
bawah berkas ini.

Perubahan dari versi sebelumnya:
  1. SATU fungsi validasi block (validate_block) dipakai oleh NEW_BLOCK DAN
     sinkronisasi -- termasuk cek PoW terhadap DIFFICULTY (string global).
     (Revisi 3: difficulty_bits per block dan retarget diganti DIFFICULTY
     string global; kode lamanya ada sebagai komentar "arsip" di sini dan
     di bagian [ARSIP] paling bawah berkas inti.)
  2. Format & rentang semua field block dicek sebelum dipakai; pesan cacat
     dijawab ERROR/REJECT, thread tidak lagi mati diam-diam.
  3. REGISTER_AUTHOR tidak bisa menimpa public key yang sudah terdaftar.
  4. Block dengan id sama tapi isi berbeda (fork) ditolak dengan jelas,
     bukan dijawab "OK".
  5. Sinkron DUA ARAH (tukar public key, tarik chain, dorong chain), jadi
     urutan menyalakan node tidak lagi menentukan berhasil/tidaknya.
  6. Keypair aktor disimpan ke file, sehingga restart tidak mengganti key.
  7. Resolusi fork (longest-chain rule): resolve_fork(), panjang_chain(),
     chain_utama(), terintegrasi ke sinkronisasi, dengan keluaran [FORK] yang
     menjelaskan titik cabang, panjang tiap sisi, keputusan, dan block orphan.
  8. Peer bisa ditambah/dihapus saat node berjalan (menu 6) -- untuk
     mensimulasikan partisi jaringan saat eksperimen fork.
  # >>> TAMBAH: dua poin baru di bawah ini
  9. (Tugas 4) POST /peers: peer bisa ditambahkan dari luar proses saat
     node berjalan, tanpa restart dan tanpa lewat menu.
 10. (Tugas 7) Chain disimpan ke <data-dir>/chain.json (autosave + saat
     keluar) dan dimuat + divalidasi ulang saat node start.

KETERBATASAN (jujur):
  - Chain disimpan sebagai dict {id: Block}. Jika dua node membuat block
    dengan id yang sama pada saat yang sama, salah satunya ditolak (fork).
    Menu "tambah transaksi" sinkron dulu untuk memperkecil peluang ini,
    tetapi tidak menghilangkannya sepenuhnya.
  # >>> UBAH: poin lama "Chain tidak disimpan ke disk" diganti, karena
  # >>> sekarang chain disimpan ke chain.json.
  - Chain disimpan ke chain.json per node (autosave tiap ~2 detik). Perubahan
    dalam jeda autosave bisa hilang jika proses dimatikan paksa (mis. kill -9).
    File ini TIDAK dienkripsi dan tidak menyimpan private key.
  - Public key memakai model "pertama kali terlihat dipercaya": siapa yang
    mendaftarkan key suatu aktor lebih dulu, key itulah yang dipakai.
"""

import argparse
import http.client
import json
import math
import os
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from blockchain_core_traceability_suku_cadang_kendaraan import (
    ALLOWED_TRANSITIONS,
    AUTHORIZED_ACTORS,
    AUTHOR_KEYS,
    PUBLIC_KEY_REGISTRY,
    DIFFICULTY,
    # arsip: MIN_DIFFICULTY_BITS, MAX_DIFFICULTY_BITS,
    Block,
    TransactionRejected,
    ConsensusRejected,
    add_transaction,
    compute_hash,
    # arsip: compute_next_difficulty,
    get_or_create_author,
    is_chain_valid,
    pilih_dari_daftar,
    print_chain,
    public_key_from_pem,
    public_key_to_pem,
    register_public_key,
    validate_transaction,
    verify_block_signature,
    verify_pow,
)

CHAIN_LOCK = threading.Lock()
KEY_LOCK = threading.Lock()

# >>> TAMBAH (Tugas 4): lock untuk list `peers`.
# >>> Alasan: list peers bisa diubah oleh dua thread sekaligus -- thread menu
# >>> CLI (menu 6) dan thread server (pesan ADD_PEER). Lock mencegah bentrok.
PEER_LOCK = threading.Lock()

MAX_MSG_BYTES = 10 * 1024 * 1024   # batas ukuran satu pesan
MAX_HEX = 20000                    # batas panjang field hex (ciphertext dst.)


# ---------- (de)serialisasi block untuk dikirim lewat jaringan ----------

def block_to_dict(b: Block) -> dict:
    return {
        "id": b.id, "author": b.author, "parent_id": b.parent_id,
        "parent_hash": b.parent_hash, "timestamp": b.timestamp, "salt": b.salt,
        "nonce": b.nonce, "extra_nonce": b.extra_nonce,
        # arsip: "difficulty_bits": b.difficulty_bits,
        "part_id": b.part_id,
        "status": b.status, "envelope": b.envelope, "signature": b.signature,
    }


def block_from_dict(d: dict) -> Block:
    """Rekonstruksi Block dari dict TANPA memanggil __init__ (supaya tidak
    re-enkripsi ulang dengan key acak baru -- envelope harus dipakai apa
    adanya). content_root tidak pernah di-cache, jadi compute_hash() selalu
    menghitung fresh dan manipulasi field saat transit pasti terdeteksi oleh
    verify_pow() / verify_block_signature(). Format field harus sudah dicek
    lewat check_block_format() sebelum fungsi ini dipanggil."""
    blk = Block.__new__(Block)
    blk.id = d["id"]
    blk.author = d["author"]
    blk.parent_id = d["parent_id"]
    blk.parent_hash = d["parent_hash"]
    blk.timestamp = d["timestamp"]
    blk.salt = d["salt"]
    blk.nonce = d["nonce"]
    blk.extra_nonce = d["extra_nonce"]
    # arsip: blk.difficulty_bits = d["difficulty_bits"]
    blk.part_id = d["part_id"]
    blk.status = d["status"]
    blk.envelope = d["envelope"]
    blk.signature = d["signature"]
    return blk


# ---------- validasi block (SATU tempat, dipakai NEW_BLOCK & sinkronisasi) ----------

FIELD_BLOCK = ("id", "author", "parent_id", "parent_hash", "timestamp", "salt",
               "nonce", "extra_nonce", "part_id", "status",   # arsip: + "difficulty_bits"
               "envelope", "signature")


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _hex(x, maks=MAX_HEX) -> bool:
    if not isinstance(x, str) or not x or len(x) > maks or len(x) % 2:
        return False
    try:
        bytes.fromhex(x)
        return True
    except ValueError:
        return False


def check_block_format(d):
    """Cek bentuk & rentang field. Return pesan error, atau None kalau OK."""
    if not isinstance(d, dict):
        return "block bukan objek JSON"
    for k in FIELD_BLOCK:
        if k not in d:
            return f"field '{k}' tidak ada"

    if not _int(d["id"]) or d["id"] < 1:
        return "id harus bilangan bulat >= 1"

    pid, ph = d["parent_id"], d["parent_hash"]
    if (pid is None) != (ph is None):
        return "parent_id dan parent_hash harus sama-sama ada atau sama-sama kosong"
    if pid is not None:
        if not _int(pid) or pid < 1 or pid >= d["id"]:
            return "parent_id harus bilangan bulat >= 1 dan lebih kecil dari id"
        if not _hex(ph, 64) or len(ph) != 64:
            return "parent_hash harus 64 karakter hex"

    ts = d["timestamp"]
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts) or ts <= 0:
        return "timestamp tidak valid"
    if not isinstance(d["salt"], str) or len(d["salt"]) > 64:
        return "salt tidak valid"
    if not _int(d["nonce"]) or not (0 <= d["nonce"] < 2 ** 64):
        return "nonce di luar rentang"
    if not _int(d["extra_nonce"]) or not (0 <= d["extra_nonce"] < 2 ** 32):
        return "extra_nonce di luar rentang"
    # arsip: if not _int(d["difficulty_bits"]) or not (MIN_DIFFICULTY_BITS <= d["difficulty_bits"] <= MAX_DIFFICULTY_BITS):
    # arsip:     return f"difficulty_bits harus {MIN_DIFFICULTY_BITS}..{MAX_DIFFICULTY_BITS}"
    for k in ("author", "part_id", "status"):
        if not isinstance(d[k], str) or not d[k] or len(d[k]) > 128:
            return f"field '{k}' harus string tidak kosong"

    env = d["envelope"]
    if not isinstance(env, dict):
        return "envelope bukan objek"
    for k in ("ciphertext", "nonce", "encrypted_key"):
        if not _hex(env.get(k)):
            return f"envelope.{k} bukan hex yang valid"
    if not _hex(d["signature"]):
        return "signature bukan hex yang valid"
    return None


def validate_block(blk: Block, chain_map: dict):
    """Validasi penuh sebuah block terhadap chain lokal. CHAIN_LOCK harus
    sudah dipegang pemanggil. Return (True, '') atau (False, alasan)."""
    if blk.author not in AUTHORIZED_ACTORS:
        return False, "author tidak berwenang"

    parent = None
    if blk.parent_id is not None:
        parent = chain_map.get(blk.parent_id)
        if parent is None:
            return False, "parent block belum dikenal node ini"

    # Urutan status dicek dari part_id/status plaintext saja (isi transaksi
    # lengkap tetap terenkripsi, sesuai desain semula).
    pseudo_tx = {
        "part_id": blk.part_id, "status": blk.status,
        "part_name": "-", "origin": "-", "destination": "-", "vehicle_id": "-",
    }
    valid, message = validate_transaction(pseudo_tx, parent)
    if not valid:
        return False, message

    if parent is not None and blk.parent_hash != compute_hash(parent):
        return False, "parent_hash mismatch"

    # arsip: diharapkan = compute_next_difficulty(chain_map, parent)
    # arsip: if blk.difficulty_bits != diharapkan:
    # arsip:     return False, f"difficulty_bits {blk.difficulty_bits} tidak sesuai aturan retarget (seharusnya {diharapkan})"

    if not verify_pow(blk):   # hash harus diawali DIFFICULTY (string global)
        return False, "PoW tidak valid"

    if not verify_block_signature(blk):
        return False, "signature tidak valid (public key author belum terdaftar di node ini?)"
    return True, ""


def terima_block(d, chain_map: dict):
    """Cek format + validasi + masukkan ke chain. CHAIN_LOCK harus dipegang.
    Return (kode, alasan); kode: 'BARU' | 'ADA' | 'TOLAK' | 'FORK'."""
    err = check_block_format(d)
    if err:
        return "TOLAK", f"format block tidak valid: {err}"
    try:
        blk = block_from_dict(d)
    except (KeyError, TypeError, ValueError) as e:
        return "TOLAK", f"block tidak dapat dibaca: {e}"

    if blk.id in chain_map:
        if compute_hash(chain_map[blk.id]) == compute_hash(blk):
            return "ADA", "sudah ada di chain lokal"
        return "FORK", (f"id block {blk.id} sudah dipakai block lain dengan isi berbeda "
                        f"(fork) -- block ini ditolak")

    ok, alasan = validate_block(blk, chain_map)
    if not ok:
        return "TOLAK", alasan

    chain_map[blk.id] = blk
    return "BARU", "diterima"


# ---------- resolusi fork (aturan rantai terpanjang) ----------
#
# Chain disimpan sebagai {id: Block}. Satu node menyimpan SELURUH buku besar
# (kumpulan lineage part: PRODUCED -> SHIPPED -> RECEIVED -> INSTALLED).
# Dua node dikatakan FORK jika ada id block yang sama tetapi isinya (hash)
# berbeda. Aturan penyelesaian (longest-chain rule):
#   - buku besar peer dibangun ulang dari nol & divalidasi penuh dulu;
#   - panjang = jumlah block VALID; yang lebih panjang menang;
#   - jika menang peer -> chain lokal diganti; block lokal yang tidak ada di
#     chain baru menjadi ORPHAN (author-nya perlu mengajukan ulang transaksinya);
#   - jika SERI -> tetap pakai chain lokal (first-seen); fork berlanjut sampai
#     salah satu pihak menambah block, lalu pihak yang kalah menyusul saat sinkron.

RIWAYAT_FORK = []


def label_block(b) -> str:
    return f"{b.id} ({b.author}/{b.status}/{b.part_id})"


def panjang_chain(chain_map: dict) -> int:
    """Panjang chain = jumlah block valid di buku besar."""
    return len(chain_map)


def _lineage(chain_map: dict):
    """Untuk tiap akar (block tanpa parent): semua jalur akar -> ujung."""
    anak = {}
    for b in chain_map.values():
        if b.parent_id is not None:
            anak.setdefault(b.parent_id, []).append(b.id)
    hasil = []
    for akar in sorted(i for i, b in chain_map.items() if b.parent_id is None):
        jalur = []

        def dfs(i, path):
            path = path + [i]
            if i not in anak:
                jalur.append(path)
                return
            for c in sorted(anak[i]):
                dfs(c, path)

        dfs(akar, [])
        hasil.append((akar, jalur))
    return hasil


def chain_utama(chain_map: dict) -> list:
    """Chain utama tiap lineage = jalur akar -> ujung TERPANJANG (seri: ujung
    ber-id lebih kecil). Return list (akar, jalur_utama, jalur_cabang_lain)."""
    hasil = []
    for akar, jalur in _lineage(chain_map):
        utama = max(jalur, key=lambda j: (len(j), -j[-1]))
        lain = [j for j in jalur if j is not utama]
        hasil.append((akar, utama, lain))
    return hasil


def bangun_kandidat(blocks):
    """Bangun buku besar kandidat dari daftar block peer, dari nol, dengan
    validasi penuh tiap block. Return (peta_valid, daftar_ditolak)."""
    kandidat, ditolak = {}, []
    dicek = [d for d in blocks if isinstance(d, dict) and _int(d.get("id"))]
    for d in sorted(dicek, key=lambda x: x["id"]):
        err = check_block_format(d)
        if err:
            ditolak.append((d["id"], err))
            continue
        blk = block_from_dict(d)
        if blk.id in kandidat:
            ditolak.append((blk.id, "id duplikat dalam daftar peer"))
            continue
        ok, alasan = validate_block(blk, kandidat)
        if ok:
            kandidat[blk.id] = blk
        else:
            ditolak.append((blk.id, alasan))
    return kandidat, ditolak


def resolve_fork(chain_map: dict, blocks, sumber="peer") -> dict:
    """Selesaikan fork antara chain lokal dan chain peer. CHAIN_LOCK harus
    dipegang. Mengubah chain_map di tempat bila peer menang. Return info."""
    kandidat, ditolak = bangun_kandidat(blocks)
    p_lokal, p_peer = panjang_chain(chain_map), panjang_chain(kandidat)

    beda = [i for i in chain_map
            if i in kandidat and compute_hash(chain_map[i]) != compute_hash(kandidat[i])]
    info = {
        "sumber": sumber, "waktu": time.strftime("%H:%M:%S"),
        "titik_cabang": min(beda) if beda else None,
        "panjang_lokal": p_lokal, "panjang_peer": p_peer,
        "peer_ditolak": ditolak, "orphan": [], "ditambah": 0,
    }

    if p_peer > p_lokal:
        info["keputusan"] = "GANTI"
        info["orphan"] = [label_block(b) for i, b in sorted(chain_map.items())
                          if i not in kandidat or compute_hash(kandidat[i]) != compute_hash(b)]
        info["ditambah"] = sum(1 for i, b in kandidat.items()
                               if i not in chain_map or compute_hash(chain_map[i]) != compute_hash(b))
        chain_map.clear()
        chain_map.update(kandidat)
    elif p_peer < p_lokal:
        info["keputusan"] = "PERTAHANKAN"
    else:
        info["keputusan"] = "SERI"
    RIWAYAT_FORK.append(info)
    return info


def cetak_fork(info: dict):
    k = info["keputusan"]
    penjelasan = {
        "GANTI": "chain lokal DIGANTI chain peer (peer lebih panjang)",
        "PERTAHANKAN": "chain lokal DIPERTAHANKAN (lokal lebih panjang)",
        "SERI": "panjang SAMA -> chain lokal dipertahankan (first-seen); "
                "fork berlanjut sampai salah satu menambah block",
    }[k]
    print(f"[FORK] Percabangan terdeteksi dengan {info['sumber']}")
    print(f"       titik cabang   : block id {info['titik_cabang']}")
    print(f"       panjang lokal  : {info['panjang_lokal']} block")
    print(f"       panjang peer   : {info['panjang_peer']} block valid "
          f"({len(info['peer_ditolak'])} ditolak saat validasi)")
    print(f"       keputusan      : {k} -> {penjelasan}")
    if info["orphan"]:
        print(f"       block orphan   : {', '.join(info['orphan'])}")
        print("       (transaksi orphan perlu diajukan ulang oleh author-nya)")


def tampilkan_fork(chain_map: dict):
    print("\n=== CHAIN UTAMA & FORK ===")
    if not chain_map:
        print("Chain masih kosong.")
    else:
        lineage = chain_utama(chain_map)
        cabang = sum(len(lain) for _, _, lain in lineage)
        print(f"Panjang chain: {panjang_chain(chain_map)} block | "
              f"lineage (part): {len(lineage)} | cabang samping: {cabang}")

        def teks(path):
            return " -> ".join(f"{i}[{chain_map[i].status}]" for i in path)

        for akar, utama, lain in lineage:
            print(f"Lineage block {akar} (part {chain_map[akar].part_id})")
            print(f"  chain utama : {teks(utama)}")
            for j in lain:
                print(f"  cabang      : {teks(j)}")
    if RIWAYAT_FORK:
        print("\nRiwayat resolusi fork:")
        for n, f in enumerate(RIWAYAT_FORK, 1):
            print(f"  {n}) {f['waktu']} dengan {f['sumber']}: lokal {f['panjang_lokal']} vs "
                  f"peer {f['panjang_peer']} -> {f['keputusan']}"
                  f"{' | orphan: ' + str(len(f['orphan'])) if f['orphan'] else ''}")
    else:
        print("\nBelum ada fork yang terdeteksi.")


# ---------- manajemen public key & keypair ----------

def daftarkan_key(author, pem):
    """Daftarkan public key author milik node lain. Key yang sudah terdaftar
    TIDAK boleh ditimpa dengan key berbeda. Return (ok, alasan)."""
    if not isinstance(author, str) or not isinstance(pem, str):
        return False, "author/public_key_pem harus string"
    if author not in AUTHORIZED_ACTORS:
        return False, "author tidak berwenang"
    try:
        pub = public_key_from_pem(pem)
    except Exception:
        return False, "public key PEM tidak valid"
    if not isinstance(pub, rsa.RSAPublicKey) or pub.key_size < 2048:
        return False, "public key harus RSA minimal 2048 bit"

    with KEY_LOCK:
        ada = None
        if author in AUTHOR_KEYS:
            ada = AUTHOR_KEYS[author][1]
        elif author in PUBLIC_KEY_REGISTRY:
            ada = PUBLIC_KEY_REGISTRY[author]
        if ada is not None:
            if public_key_to_pem(ada) == public_key_to_pem(pub):
                return True, "sudah terdaftar"
            return False, "public key author ini sudah terdaftar dan BERBEDA -- ditolak"
        register_public_key(author, pub)
    return True, "terdaftar"


def semua_key_publik() -> dict:
    with KEY_LOCK:
        hasil = {a: public_key_to_pem(k[1]) for a, k in AUTHOR_KEYS.items()}
        for a, k in PUBLIC_KEY_REGISTRY.items():
            hasil.setdefault(a, public_key_to_pem(k))
    return hasil


def load_or_create_keys(author, data_dir):
    """Muat private key author dari file; kalau belum ada, buat lalu simpan.
    File key TIDAK dienkripsi -- lindungi folder data dir ini."""
    folder = os.path.join(data_dir, "keys")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{author}.pem")
    if os.path.exists(path):
        with open(path, "rb") as f:
            priv = serialization.load_pem_private_key(f.read(), password=None)
        AUTHOR_KEYS[author] = (priv, priv.public_key())
        print(f"[NODE] Key '{author}' dimuat dari {path}")
    else:
        priv, _ = get_or_create_author(author)
        pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(path, "wb") as f:
            f.write(pem)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        print(f"[NODE] Key '{author}' dibuat & disimpan di {path}")


# =====================================================================
# >>> TAMBAH (Tugas 7): PENYIMPANAN CHAIN KE BERKAS JSON
# >>> Tiga fungsi baru: simpan_chain, muat_chain, autosave.
# >>> Letak: tepat di bawah load_or_create_keys, karena fungsi-fungsi yang
# >>> dipanggil di sini (semua_key_publik, block_to_dict, bangun_kandidat,
# >>> daftarkan_key) semuanya sudah didefinisikan di atas.
# =====================================================================

def simpan_chain(chain_map, path):
    """Tulis chain + public key semua aktor ke satu berkas JSON.

    Kenapa public key ikut disimpan: saat dimuat nanti, tiap block divalidasi
    ulang (termasuk signature), dan itu butuh public key aktor milik node lain.
    Private key TIDAK pernah ditulis ke sini (sudah ada di folder keys/).

    Kenapa ditulis ke .tmp lalu os.replace: kalau node mati di tengah menulis,
    chain.json lama tetap utuh (penulisan atomik)."""
    with CHAIN_LOCK:   # kunci supaya chain tidak berubah selagi disalin
        data = {"keys": semua_key_publik(),
                "blocks": [block_to_dict(chain_map[i]) for i in sorted(chain_map)]}
    # Node tanpa --authors (mis. node5 di Docker) belum punya folder data,
    # jadi pastikan foldernya ada sebelum menulis.
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def muat_chain(chain_map, path):
    """Baca chain.json saat node start. Return jumlah block yang berhasil dimuat.

    Urutan penting: public key dimuat DULU (daftarkan_key), baru block
    divalidasi lewat bangun_kandidat -- validasi penuh (PoW, signature,
    parent_hash, urutan status) dijalankan ulang untuk TIAP block. Jadi kalau
    file JSON diutak-atik tangan, block yang rusak otomatis ditolak."""
    if not os.path.exists(path):
        return 0   # node baru, belum ada berkas -> mulai dari chain kosong
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[NODE] chain.json tidak terbaca: {e}")
        return 0
    if not isinstance(data, dict):
        print("[NODE] chain.json bukan objek JSON, diabaikan")
        return 0
    keys = data.get("keys", {})
    if isinstance(keys, dict):
        for a, pem in keys.items():
            daftarkan_key(a, pem)
    blocks = data.get("blocks", [])
    if not isinstance(blocks, list):
        blocks = []
    kandidat, ditolak = bangun_kandidat(blocks)
    with CHAIN_LOCK:
        chain_map.update(kandidat)
    print(f"[NODE] Dimuat {len(kandidat)} block dari {path} ({len(ditolak)} ditolak)")
    return len(kandidat)


def autosave(chain_map, path, jeda=2):
    """Thread latar belakang: tiap `jeda` detik, cek apakah chain berubah;
    kalau ya, simpan ke disk.

    Dipilih autosave (bukan memanggil simpan_chain di tiap tempat) supaya
    kita tidak perlu mengubah menu 1, terima_block, maupun resolve_fork --
    semua sumber perubahan chain otomatis tersimpan."""
    terakhir = None
    while True:
        time.sleep(jeda)
        with CHAIN_LOCK:
            snap = json.dumps([block_to_dict(chain_map[i]) for i in sorted(chain_map)],
                              sort_keys=True)
        if snap != terakhir:
            try:
                simpan_chain(chain_map, path)
                terakhir = snap
            except OSError as e:
                # Jangan biarkan thread mati diam-diam kalau disk bermasalah.
                print(f"[NODE] Autosave gagal: {e}")


# ---------- logika pesan (bebas transport) ----------

# >>> UBAH (Tugas 4): tambah parameter `peers=None`.
# >>> Default None dipilih supaya uji_node.py / uji_fork.py yang memanggil
# >>> fungsi ini TANPA peers tetap berjalan seperti semula.
def handle_message(msg: dict, chain_map: dict, peers=None, owned_authors=None) -> dict:
    """Logika satu pesan: dict masuk -> dict balasan. Tidak tahu apa-apa soal HTTP;
    tipe pesan dipetakan dari (metode, path) oleh NodeHandler di bawah."""
    mtype = msg.get("type")

    # >>> TAMBAH (Tugas 4): seluruh blok ADD_PEER ini = padanan POST /peers.
    # >>> Letak: setelah baris `mtype = ...` dan SEBELUM cabang REGISTER_AUTHOR.
    # >>> Fungsi: menambahkan alamat ke daftar peers saat node berjalan, tanpa restart.
    if mtype == "ADD_PEER":
        if peers is None:
            # Server dijalankan tanpa list peers (mis. dari skrip uji) -> tolak dengan jelas.
            return {"type": "REJECT", "reason": "node ini tidak mendukung ADD_PEER"}
        try:
            # parse_satu_peer (sudah ada di bawah) mengubah "localhost:5002"
            # menjadi ("localhost", 5002) sekaligus memvalidasi format & port.
            peer = parse_satu_peer(str(msg.get("peer", "")))
        except ValueError as e:
            return {"type": "REJECT", "reason": str(e)}
        with PEER_LOCK:
            if peer in peers:                       # cegah duplikat
                return {"type": "OK", "note": "peer sudah ada"}
            peers.append(peer)                      # INTI FITUR: list diubah saat node jalan
            daftar = [f"{h}:{p}" for h, p in peers]
        print(f"[NODE] Peer ditambahkan lewat ADD_PEER: {peer[0]}:{peer[1]}")
        # Catatan: hanya menambah ke daftar, TIDAK langsung sinkron.
        # Untuk menjalankan resolve fork, pakai menu 3 di node ini.
        return {"type": "OK", "peers": daftar}

    if mtype == "REGISTER_AUTHOR":
        ok, alasan = daftarkan_key(msg.get("author"), msg.get("public_key_pem"))
        if ok:
            return {"type": "OK", "note": alasan}
        print(f"[NODE] REGISTER_AUTHOR ditolak: {alasan}")
        return {"type": "REJECT", "reason": alasan}

    if mtype == "GET_KEYS":
        return {"type": "KEYS", "keys": semua_key_publik()}

    if mtype == "GET_CHAIN":
        with CHAIN_LOCK:
            blocks = [block_to_dict(b) for b in chain_map.values()]
        return {"type": "CHAIN", "blocks": blocks}

    if mtype == "NEW_BLOCK":
        d = msg.get("block")
        with CHAIN_LOCK:
            kode, alasan = terima_block(d, chain_map)
        if kode == "BARU":
            print(f"[NODE] Memverifikasi & menerima block {d['id']} dari jaringan "
                  f"(author={d['author']}, status={d['status']})")
            return {"type": "OK"}
        if kode == "ADA":
            return {"type": "OK", "note": alasan}
        idb = d.get("id") if isinstance(d, dict) else "?"
        print(f"[NODE] Block {idb} DITOLAK: {alasan}")
        return {"type": "REJECT", "reason": alasan}

    if mtype == "GET_PEERS":
        if peers is None:
            return {"type": "REJECT", "reason": "node ini tidak mendukung daftar peer"}
        with PEER_LOCK:
            daftar = [f"{h}:{p}" for h, p in peers]
        return {"type": "PEERS", "peers": daftar}

    if mtype == "GET_STATUS":
        with CHAIN_LOCK:
            jumlah = panjang_chain(chain_map)
        with PEER_LOCK:
            daftar = [f"{h}:{p}" for h, p in (peers or [])]
        return {"type": "STATUS", "aktor_lokal": list(owned_authors or []),
                "jumlah_block": jumlah, "peers": daftar, "difficulty": DIFFICULTY}

    # >>> TAMBAH (Tugas 5): padanan POST /nodes/resolve -- menjalankan sinkron dua
    # >>> arah dengan SEMUA peer (sama seperti menu 3), termasuk resolusi fork
    # >>> (longest-chain rule). Keluaran [FORK] tercetak di konsol node ini.
    if mtype == "RESOLVE":
        if peers is None:
            return {"type": "REJECT", "reason": "node ini tidak mendukung RESOLVE"}
        with PEER_LOCK:
            daftar = list(peers)
        fork_sebelum = len(RIWAYAT_FORK)
        hasil = [{"peer": f"{h}:{p}",
                  "terjangkau": sinkron_peer(h, p, chain_map, owned_authors or [])}
                 for h, p in daftar]
        with CHAIN_LOCK:
            jumlah = panjang_chain(chain_map)
        return {"type": "OK", "hasil": hasil, "jumlah_block": jumlah,
                "fork_ditangani": len(RIWAYAT_FORK) - fork_sebelum}

    return {"type": "ERROR", "reason": f"tipe pesan tidak dikenal: {mtype}"}


# ---------- transport HTTP ----------

# Satu tabel rute dipakai server DAN client, jadi alamat endpoint tidak pernah
# berbeda antara kedua sisi. Format: tipe pesan -> (metode HTTP, path).
RUTE_HTTP = {
    "GET_CHAIN":       ("GET",  "/chain"),
    "NEW_BLOCK":       ("POST", "/blocks"),
    "GET_KEYS":        ("GET",  "/keys"),
    "REGISTER_AUTHOR": ("POST", "/keys"),
    "ADD_PEER":        ("POST", "/peers"),          # Tugas 4
    "GET_PEERS":       ("GET",  "/peers"),
    "RESOLVE":         ("POST", "/nodes/resolve"),  # Tugas 5
    "GET_STATUS":      ("GET",  "/status"),
}
_TIPE_DARI_RUTE = {rute: tipe for tipe, rute in RUTE_HTTP.items()}
_PATH_DIKENAL = {path for _, path in RUTE_HTTP.values()}


class _BodyError(Exception):
    def __init__(self, status, pesan):
        super().__init__(pesan)
        self.status = status


def _status_http(metode: str, path: str, reply: dict) -> int:
    """Terjemahkan balasan (dict) menjadi kode status HTTP."""
    tipe = reply.get("type")
    if tipe == "REJECT":
        return 400 if path == "/peers" else 409     # format peer salah = 400; block/key ditolak = 409
    if tipe == "ERROR":
        return 400
    if metode == "POST" and path == "/peers" and "peers" in reply:
        return 201                                   # peer baru dibuat
    return 200


class NodeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"   # satu permintaan per koneksi (tanpa keep-alive)
    server_version = "TraceNode/1.0"
    timeout = 10                    # batas waktu baca per koneksi (detik)

    def log_message(self, format, *args):
        pass                        # dibisukan: konsol dipakai menu interaktif

    def _balas(self, status: int, reply: dict):
        data = json.dumps(reply).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass                    # klien sudah pergi

    def send_error(self, code, message=None, explain=None):
        # Galat tingkat protokol (request line rusak, metode tak dikenal, dst.)
        # juga dijawab JSON, bukan halaman HTML bawaan.
        self._balas(code, {"type": "ERROR",
                           "reason": message or self.responses.get(code, ("galat",))[0]})

    def _baca_body(self) -> dict:
        if self.headers.get("Transfer-Encoding"):
            raise _BodyError(411, "Transfer-Encoding tidak didukung; kirim Content-Length")
        teks = (self.headers.get("Content-Length") or "").strip()
        if not teks:
            return {}
        try:
            panjang = int(teks)
        except ValueError:
            raise _BodyError(400, "Content-Length tidak valid")
        if panjang < 0:
            raise _BodyError(400, "Content-Length tidak valid")
        if panjang > MAX_MSG_BYTES:
            raise _BodyError(413, "body terlalu besar")
        if panjang == 0:
            return {}
        mentah = self.rfile.read(panjang)
        if len(mentah) < panjang:
            raise _BodyError(400, "body tidak lengkap")
        try:
            obj = json.loads(mentah.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise _BodyError(400, "JSON tidak valid")
        if not isinstance(obj, dict):
            raise _BodyError(400, "body harus berupa objek JSON")
        return obj

    def _proses(self):
        metode = self.command
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        tipe = _TIPE_DARI_RUTE.get((metode, path))
        if tipe is None:
            if path in _PATH_DIKENAL:
                return self._balas(405, {"type": "ERROR",
                                         "reason": f"metode {metode} tidak didukung untuk {path}"})
            return self._balas(404, {"type": "ERROR", "reason": f"endpoint tidak dikenal: {path}"})
        try:
            body = self._baca_body() if metode != "GET" else {}
        except _BodyError as e:
            return self._balas(e.status, {"type": "ERROR", "reason": str(e)})
        msg = dict(body)
        msg["type"] = tipe          # tipe ditentukan rute, bukan isi body
        try:
            reply = handle_message(msg, self.server.chain_map, self.server.peers,
                                   self.server.owned_authors)
        except Exception as e:      # jangan biarkan thread mati tanpa balasan
            print(f"[NODE] Error memproses {metode} {path} dari {self.client_address[0]}: "
                  f"{type(e).__name__}: {e}")
            return self._balas(500, {"type": "ERROR", "reason": "pesan tidak dapat diproses"})
        self._balas(_status_http(metode, path, reply), reply)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _proses


class NodeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 50

    def __init__(self, alamat, chain_map, peers=None, owned_authors=None):
        self.chain_map = chain_map
        self.peers = peers
        self.owned_authors = list(owned_authors or [])
        super().__init__(alamat, NodeHandler)

    def server_bind(self):
        # HTTPServer.server_bind memanggil getfqdn() yang bisa lambat (DNS) dan
        # tidak dibutuhkan di sini.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def buat_server(host: str, port: int, chain_map: dict, peers=None, owned_authors=None):
    srv = NodeHTTPServer((host, port), chain_map, peers, owned_authors)
    print(f"[NODE] Mendengarkan HTTP di http://{host}:{port}")
    return srv


def terima_koneksi(srv):
    srv.serve_forever(poll_interval=0.2)


def start_server(host: str, port: int, chain_map: dict, peers=None, owned_authors=None):
    terima_koneksi(buat_server(host, port, chain_map, peers, owned_authors))


# ---------- client (menghubungi peer) ----------

def send_message(host: str, port: int, msg: dict, timeout=5) -> dict:
    """Kirim satu pesan ke peer lewat HTTP dan kembalikan balasannya (dict).
    Antarmuka dict-in/dict-out dipertahankan supaya seluruh pemanggil lama
    tidak berubah; tipe pesan diterjemahkan ke (metode, path) lewat RUTE_HTTP.
    Kegagalan jaringan/protokol dilaporkan sebagai OSError."""
    tipe = msg.get("type")
    rute = RUTE_HTTP.get(tipe)
    if rute is None:
        return {"type": "ERROR", "reason": f"tipe pesan tidak dikenal: {tipe}"}
    metode, path = rute
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        if metode == "GET":
            conn.request("GET", path)
        else:
            isi = json.dumps({k: v for k, v in msg.items() if k != "type"}).encode("utf-8")
            conn.request(metode, path, body=isi, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        mentah = resp.read(MAX_MSG_BYTES + 1)
    except http.client.HTTPException as e:
        raise OSError(f"balasan HTTP tidak valid: {e}")
    finally:
        conn.close()
    if len(mentah) > MAX_MSG_BYTES:
        raise OSError("balasan terlalu besar")
    if not mentah:
        return {"type": "ERROR", "reason": "tidak ada balasan"}
    try:
        balasan = json.loads(mentah.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"type": "ERROR", "reason": "balasan peer bukan JSON"}
    if not isinstance(balasan, dict):
        return {"type": "ERROR", "reason": "balasan peer bukan objek JSON"}
    return balasan



def kirim_keys_ke_peer(host, port, owned_authors):
    """Kirim public key tiap author milik node ini ke satu peer."""
    for author in owned_authors:
        _, public_key = get_or_create_author(author)
        payload = {"type": "REGISTER_AUTHOR", "author": author,
                   "public_key_pem": public_key_to_pem(public_key)}
        reply = send_message(host, port, payload)
        if reply.get("type") != "OK":
            print(f"[NODE] Peer {host}:{port} menolak key '{author}': {reply.get('reason')}")


def tarik_keys(host, port) -> int:
    """Ambil public key yang dikenal peer. Return jumlah key baru."""
    reply = send_message(host, port, {"type": "GET_KEYS"})
    keys = reply.get("keys")
    if reply.get("type") != "KEYS" or not isinstance(keys, dict):
        return 0
    baru = 0
    for author, pem in keys.items():
        ok, alasan = daftarkan_key(author, pem)
        if ok and alasan == "terdaftar":
            baru += 1
        elif not ok:
            print(f"[NODE] Key '{author}' dari {host}:{port} diabaikan: {alasan}")
    return baru


def _konflik_id(d, chain_map: dict) -> bool:
    """True jika id block ini sudah ada di chain lokal dengan isi berbeda."""
    if check_block_format(d):
        return False
    blk = block_from_dict(d)
    lama = chain_map.get(blk.id)
    return lama is not None and compute_hash(lama) != compute_hash(blk)


def sync_chain_from_peer(host: str, port: int, chain_map: dict):
    """Tarik chain peer. Tanpa konflik id: TIAP block divalidasi penuh lalu
    digabung. Ada konflik id (fork): jalankan resolve_fork().
    Return (diterima, ditolak, info_fork atau None)."""
    reply = send_message(host, port, {"type": "GET_CHAIN"})
    blocks = reply.get("blocks")
    if reply.get("type") != "CHAIN" or not isinstance(blocks, list):
        return 0, 0, None
    kandidat = [d for d in blocks if isinstance(d, dict) and _int(d.get("id"))]
    sumber = f"{host}:{port}"
    with CHAIN_LOCK:
        if any(_konflik_id(d, chain_map) for d in kandidat):
            info = resolve_fork(chain_map, kandidat, sumber)
            cetak_fork(info)
            return info["ditambah"], len(info["peer_ditolak"]), info
        ditambah = ditolak = 0
        for d in sorted(kandidat, key=lambda x: x["id"]):
            kode, alasan = terima_block(d, chain_map)
            if kode == "BARU":
                ditambah += 1
            elif kode in ("TOLAK", "FORK"):
                ditolak += 1
                print(f"[NODE] Block {d['id']} dari {sumber} ditolak saat sinkron: {alasan}")
    return ditambah, ditolak, None


def dorong_chain_ke_peer(host, port, chain_map: dict):
    """Kirim semua block lokal ke peer (peer memvalidasi sendiri)."""
    with CHAIN_LOCK:
        daftar = [block_to_dict(chain_map[i]) for i in sorted(chain_map)]
    diterima = ditolak = 0
    ada_fork = False
    for d in daftar:
        reply = send_message(host, port, {"type": "NEW_BLOCK", "block": d})
        if reply.get("type") == "OK":
            diterima += 1
        else:
            ditolak += 1
            if "fork" in str(reply.get("reason", "")).lower():
                ada_fork = True
    return diterima, ditolak, ada_fork


def sinkron_peer(host, port, chain_map, owned_authors, verbose=True) -> bool:
    """Sinkron dua arah dengan satu peer: tukar public key, tarik chain,
    lalu dorong chain lokal. Return False kalau peer tidak terjangkau."""
    try:
        kirim_keys_ke_peer(host, port, owned_authors)
        key_baru = tarik_keys(host, port)
        tambah, tolak_tarik, _info = sync_chain_from_peer(host, port, chain_map)
        dorong_ok, dorong_tolak, ada_fork = dorong_chain_ke_peer(host, port, chain_map)
    except OSError as e:
        print(f"[NODE] Gagal menghubungi {host}:{port}: {e}")
        return False
    if verbose:
        print(f"[NODE] Sinkron {host}:{port} -> key baru: {key_baru} | "
              f"block diterima: {tambah} (ditolak {tolak_tarik}) | "
              f"block terkirim: {dorong_ok} (ditolak peer {dorong_tolak})")
    if dorong_tolak and ada_fork:
        print(f"[NODE] Peer {host}:{port} menolak block lokal karena fork; peer akan "
              f"menyusul saat ia sinkron (menu 3 di peer).")
    return True


def broadcast_block(block: Block, peers, chain_map, owned_authors):
    payload = {"type": "NEW_BLOCK", "block": block_to_dict(block)}
    # >>> UBAH (Tugas 4): `peers` -> `list(peers)`.
    # >>> Alasan: list peers bisa bertambah dari thread server (ADD_PEER) saat loop
    # >>> berjalan; salinan mencegah error "list changed size during iteration".
    for host, port in list(peers):
        try:
            reply = send_message(host, port, payload)
            print(f"[NODE] Kirim block {block.id} ke {host}:{port} -> {reply}")
            if reply.get("type") == "REJECT":
                print(f"[NODE] Ditolak {host}:{port}; mencoba sinkron dua arah...")
                sinkron_peer(host, port, chain_map, owned_authors)
        except OSError as e:
            print(f"[NODE] Gagal kirim block {block.id} ke {host}:{port}: {e}")


# ---------- CLI node ----------

def parse_satu_peer(teks):
    pesan = f"Format peer salah: '{teks}' (harus host:port, contoh 192.168.1.5:9001)"
    try:
        host, port = teks.rsplit(":", 1)
        port = int(port)
    except ValueError:
        raise ValueError(pesan)
    if not host or not (1 <= port <= 65535):
        raise ValueError(pesan)
    return (host, port)


def parse_peers(peer_args):
    peers = []
    for p in peer_args or []:
        try:
            peers.append(parse_satu_peer(p))
        except ValueError as e:
            raise SystemExit(str(e))
    return peers


def kelola_peer(peers, chain_map, owned_authors):
    """Tambah/hapus peer saat node berjalan. Menghapus peer = memutus
    hubungan keluar (berguna untuk membuat fork saat eksperimen)."""
    print("Peer saat ini:")
    for i, (h, p) in enumerate(list(peers), 1):   # >>> UBAH: list(peers), alasan sama seperti di atas
        print(f"  {i}) {h}:{p}")
    if not peers:
        print("  (kosong)")
    aksi = input("(t)ambah / (h)apus / Enter=kembali: ").strip().lower()
    if aksi == "t":
        try:
            peer = parse_satu_peer(input("Alamat peer (host:port): ").strip())
        except ValueError as e:
            print(e)
            return
        # >>> UBAH: cek + append dibungkus PEER_LOCK, karena thread server
        # >>> (ADD_PEER) bisa mengubah list yang sama pada saat bersamaan.
        with PEER_LOCK:
            if peer in peers:
                print("Peer sudah ada.")
                return
            peers.append(peer)
        sinkron_peer(peer[0], peer[1], chain_map, owned_authors)
    elif aksi == "h":
        if not peers:
            return
        n = input("Nomor peer yang dihapus: ").strip()
        # >>> UBAH: pop dibungkus PEER_LOCK (alasan sama)
        with PEER_LOCK:
            if n.isdigit() and 1 <= int(n) <= len(peers):
                h, p = peers.pop(int(n) - 1)
                print(f"Peer {h}:{p} dihapus (tidak lagi dihubungi node ini).")
            else:
                print("Nomor tidak valid.")


def tampilkan_validasi(chain_map):
    with CHAIN_LOCK:
        if not chain_map:
            print("Chain kosong.")
            return
        punya_anak = {b.parent_id for b in chain_map.values() if b.parent_id is not None}
        ujung = [i for i in sorted(chain_map) if i not in punya_anak]
        for i in ujung:
            valid, msg = is_chain_valid(chain_map[i], chain_map)
            print(f"Rantai berujung di block {i}: valid={valid} | {msg}")


def run_node(host, port, owned_authors, peers, data_dir):
    chain_map = {}

    for author in owned_authors:
        load_or_create_keys(author, data_dir)

    # >>> TAMBAH (Tugas 7): muat chain dari disk + jalankan autosave.
    # >>> Letak: SETELAH key dimuat (validasi butuh key) dan SEBELUM server/sinkron
    # >>> dimulai, supaya chain hasil muat ikut dikirim ke peer saat sinkron awal.
    chain_file = os.path.join(data_dir, "chain.json")   # di Docker: ikut volume ./data/nodeX
    muat_chain(chain_map, chain_file)                   # pulihkan chain (divalidasi ulang)
    threading.Thread(target=autosave, args=(chain_map, chain_file), daemon=True).start()

    srv = buat_server(host, port, chain_map, peers, owned_authors)
    # >>> UBAH (Tugas 4): tambah `peers` di args. Ini list YANG SAMA dengan yang
    # >>> dipakai menu 1/3/6, jadi peer yang masuk lewat ADD_PEER langsung
    # >>> terlihat oleh menu dan broadcast tanpa restart.
    threading.Thread(target=terima_koneksi, args=(srv,), daemon=True).start()

    for h, p in list(peers):   # >>> UBAH: list(peers) (alasan: lihat broadcast_block)
        sinkron_peer(h, p, chain_map, owned_authors)

    print(f"\n=== NODE aktif di {host}:{port} | aktor lokal: {owned_authors or '(tidak ada)'} ===")
    try:
        while True:
            print("\n1) Tambah transaksi baru (pakai salah satu aktor lokal)")
            print("2) Tampilkan riwayat chain lokal")
            print("3) Sinkron dua arah dengan peer")
            print("4) Validasi chain lokal")
            print("5) Tampilkan chain utama & fork")
            print("6) Kelola peer (tambah/hapus)")
            print("7) Keluar")
            pilihan = input("Pilih menu: ").strip()

            if pilihan == "1":
                if not owned_authors:
                    print("Node ini tidak memiliki aktor (private key) manapun, tidak bisa menulis block.")
                    continue
                author = pilih_dari_daftar(owned_authors, "author (aktor lokal)")
                part_id = input("Part ID: ").strip()
                part_name = input("Nama part: ").strip()
                origin = input("Origin: ").strip()
                destination = input("Destination: ").strip()
                vehicle_id = input("Vehicle ID: ").strip()
                status = pilih_dari_daftar(list(ALLOWED_TRANSITIONS.keys()), "status")
                parent_raw = input("Parent block id (kosongkan jika block pertama): ").strip()
                try:
                    parent_id = int(parent_raw) if parent_raw else None
                except ValueError:
                    print("Parent block id harus berupa angka.")
                    continue

                # Sinkron dulu supaya id block baru tidak bentrok dengan peer.
                for h, p in list(peers):   # >>> UBAH: list(peers)
                    sinkron_peer(h, p, chain_map, owned_authors, verbose=False)

                try:
                    with CHAIN_LOCK:
                        blk, elapsed = add_transaction(chain_map, author, part_id, part_name,
                                                        origin, destination, vehicle_id, status,
                                                        parent_id=parent_id)
                    percobaan = getattr(blk, "mining_attempts", "?")
                    print(f"-> Block {blk.id} berhasil ditambang lokal (difficulty={DIFFICULTY!r}, "
                          f"nonce={blk.nonce}, percobaan={percobaan}, waktu={elapsed:.3f}s), "
                          f"menyiarkan ke peer...")
                    broadcast_block(blk, peers, chain_map, owned_authors)
                except (TransactionRejected, ConsensusRejected) as e:
                    print("Ditolak:", e)

            elif pilihan == "2":
                with CHAIN_LOCK:
                    print_chain(chain_map)

            elif pilihan == "3":
                if not peers:
                    print("Tidak ada peer. Jalankan node dengan --peers host:port.")
                for h, p in list(peers):   # >>> UBAH: list(peers)
                    sinkron_peer(h, p, chain_map, owned_authors)

            elif pilihan == "4":
                tampilkan_validasi(chain_map)

            elif pilihan == "5":
                with CHAIN_LOCK:
                    tampilkan_fork(chain_map)

            elif pilihan == "6":
                kelola_peer(peers, chain_map, owned_authors)

            elif pilihan == "7":
                print("Node berhenti.")
                break
            else:
                print("Pilihan tidak dikenal.")
    except (EOFError, KeyboardInterrupt):
        print("\nNode berhenti.")
    finally:
        # >>> TAMBAH (Tugas 7): simpan terakhir kali SETIAP kali node keluar
        # >>> (menu 7, Ctrl+C, maupun EOF). `finally` menjamin ini selalu jalan,
        # >>> jadi tidak perlu menulis simpan_chain di dua tempat.
        # >>> Autosave tiap 2 detik tetap berguna untuk kasus proses dimatikan paksa.
        try:
            simpan_chain(chain_map, chain_file)
            print(f"[NODE] Chain disimpan ke {chain_file}")
        except OSError as e:
            print(f"[NODE] Gagal menyimpan chain: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jalankan satu node blockchain traceability.")
    parser.add_argument("--host", default="0.0.0.0", help="alamat bind server node ini")
    parser.add_argument("--port", type=int, required=True, help="port server node ini")
    parser.add_argument("--authors", nargs="*", default=[],
                         help="aktor yang PRIVATE KEY-nya dipegang node ini, contoh: Produsen Distributor")
    parser.add_argument("--peers", nargs="*", default=[],
                         help="daftar peer format host:port, contoh: 192.168.1.5:9001")
    parser.add_argument("--data-dir", default=None,
                         help="folder penyimpanan key & chain.json (default: data_<port>)")
    args = parser.parse_args()

    for a in args.authors:
        if a not in AUTHORIZED_ACTORS:
            parser.error(f"author '{a}' tidak dikenal; pilih dari: {sorted(AUTHORIZED_ACTORS)}")

    run_node(args.host, args.port, args.authors, parse_peers(args.peers),
             args.data_dir or f"data_{args.port}")



# =====================================================================
# [ARSIP] TRANSPORT TCP LAMA (JSON satu baris per pesan)
# =====================================================================
# Semua baris di bawah ini adalah KOMENTAR (tidak dijalankan). Ini lapisan
# jaringan asli sebelum diganti HTTP (revisi 4). handle_message() dan seluruh
# logika blockchain TIDAK berubah; hanya cara pesan dikirim/diterima.
#
# Cara mengaktifkan kembali: kembalikan potongan di bawah, hapus bagian
# "transport HTTP" (RUTE_HTTP .. send_message), kembalikan `import socket`,
# dan di run_node kembalikan dua baris pembuatan server yang tertera di (3).
#
# --- (1) Server: _recv_line ---
# def _recv_line(conn) -> bytes:
#     data = b""
#     while not data.endswith(b"\n"):
#         chunk = conn.recv(65536)
#         if not chunk:
#             break
#         data += chunk
#         if len(data) > MAX_MSG_BYTES:
#             raise ValueError("pesan terlalu besar")
#     return data
#
# --- (2) Server: _handle_conn, buat_server, terima_koneksi, start_server, send_message ---
# # >>> UBAH (Tugas 4): tambah parameter `peers=None` supaya bisa diteruskan ke handle_message.
# def _handle_conn(conn, addr, chain_map, peers=None):
#     with conn:
#         conn.settimeout(10)
#         try:
#             raw = _recv_line(conn)
#             if not raw:
#                 return
#             try:
#                 msg = json.loads(raw.decode("utf-8"))
#             except (json.JSONDecodeError, UnicodeDecodeError):
#                 reply = {"type": "ERROR", "reason": "JSON tidak valid"}
#             else:
#                 if not isinstance(msg, dict):
#                     reply = {"type": "ERROR", "reason": "pesan harus berupa objek JSON"}
#                 else:
#                     # >>> UBAH: tambah argumen ketiga `peers`
#                     reply = handle_message(msg, chain_map, peers)
#         except Exception as e:  # jangan biarkan thread mati tanpa balasan
#             print(f"[NODE] Error memproses pesan dari {addr}: {type(e).__name__}: {e}")
#             reply = {"type": "ERROR", "reason": "pesan tidak dapat diproses"}
#         try:
#             conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
#         except OSError:
#             pass
#
#
# def buat_server(host: str, port: int):
#     srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#     srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#     srv.bind((host, port))
#     srv.listen(50)
#     print(f"[NODE] Mendengarkan di {host}:{port}")
#     return srv
#
#
# # >>> UBAH (Tugas 4): tambah parameter `peers=None`, diteruskan ke tiap thread koneksi.
# def terima_koneksi(srv, chain_map: dict, peers=None):
#     while True:
#         conn, addr = srv.accept()
#         # >>> UBAH: tambah `peers` di args
#         threading.Thread(target=_handle_conn, args=(conn, addr, chain_map, peers),
#                          daemon=True).start()
#
#
# # >>> UBAH (Tugas 4): tambah parameter `peers=None` (fungsi ini dipakai uji_node.py).
# def start_server(host: str, port: int, chain_map: dict, peers=None):
#     terima_koneksi(buat_server(host, port), chain_map, peers)
#
#
# # ---------- client (menghubungi peer) ----------
#
# def send_message(host: str, port: int, msg: dict, timeout=5) -> dict:
#     with socket.create_connection((host, port), timeout=timeout) as s:
#         s.sendall((json.dumps(msg) + "\n").encode("utf-8"))
#         raw = _recv_line(s)
#     if not raw:
#         return {"type": "ERROR", "reason": "tidak ada balasan"}
#     try:
#         return json.loads(raw.decode("utf-8"))
#     except (json.JSONDecodeError, UnicodeDecodeError):
#         return {"type": "ERROR", "reason": "balasan peer bukan JSON"}
#
# --- (3) run_node: pembuatan server (apa adanya) ---
#     srv = buat_server(host, port)
#     threading.Thread(target=terima_koneksi, args=(srv, chain_map, peers), daemon=True).start()
# =====================================================================
# [AKHIR ARSIP]
# =====================================================================
