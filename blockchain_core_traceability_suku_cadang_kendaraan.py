# -*- coding: utf-8 -*-
# =========================================================
# BLOCKCHAIN TRACEABILITY SUKU CADANG KENDARAAN -- INTI (revisi 5)
#
# Revisi 5 menyesuaikan kode dengan ketentuan C.2 "Fitur Wajib":
#
#   Struktur block ........... [5]  class Block: index, timestamp, daftar
#                                   transaksi, previous_hash, nonce, hash
#   Transaksi bertanda tangan  [4]  make_transaction / validate_transaction:
#                                   ditandatangani private key PENGIRIM dan
#                                   diverifikasi node sebelum diterima
#   Transaction pool ......... [8]  class Ledger: add_to_pool, build_candidate,
#                                   mine_pending; pool dikosongkan setelah
#                                   block diterima rantai (_prune_pool)
#   Proof of work ............ [6]  DIFFICULTY (string), mine_block, verify_pow;
#                                   nonce disimpan di block
#   Validasi chain ........... [7]  validate_block, is_chain_valid,
#                                   demo_manipulasi (deteksi data dimanipulasi)
#   Jaringan multi-node ...... node.py (HTTP) + Ledger.receive_block dan
#                                   Ledger.consider_chain (longest-chain rule)
#   Log console .............. setiap langkah mencetak baris berawalan [TAG]
#
# Perbedaan besar dari revisi 4 (arsipnya ada di arsip_versi_lama/):
#   - Rantai LINEAR dengan block genesis (bukan banyak lineage per part).
#   - Satu block memuat DAFTAR transaksi (bukan satu transaksi).
#   - Yang ditandatangani adalah TRANSAKSI (bukan block). Block cukup memenuhi
#     PoW dan memuat Merkle root dari transaksinya.
#   - Hash block disimpan sebagai atribut dan diverifikasi ulang.
#   - Aturan status (PRODUCED -> SHIPPED -> RECEIVED -> INSTALLED) kini dicek
#     terhadap status TERAKHIR tiap part_id di rantai, bukan terhadap block induk.
# =========================================================

import copy
import hashlib
import json
import math
import os
import struct
import threading
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# [1] IDENTITAS AKTOR -> KEYPAIR RSA

def generate_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


AUTHOR_KEYS = {}          # author -> (private_key, public_key) -- HANYA untuk author yg dimiliki node ini
PUBLIC_KEY_REGISTRY = {}  # author -> public_key -- untuk author milik NODE LAIN (hasil sinkronisasi jaringan)


def get_or_create_author(name):
    if name not in AUTHOR_KEYS:
        AUTHOR_KEYS[name] = generate_keypair()
    return AUTHOR_KEYS[name]


def register_public_key(author, public_key):
    """Dipanggil saat node menerima public key milik author dari peer (lihat node.py)."""
    PUBLIC_KEY_REGISTRY[author] = public_key


def get_public_key(author):
    """Ambil public key author, baik yang private key-nya dipegang node ini,
    maupun yang cuma diketahui public key-nya lewat sinkronisasi jaringan."""
    if author in AUTHOR_KEYS:
        return AUTHOR_KEYS[author][1]
    if author in PUBLIC_KEY_REGISTRY:
        return PUBLIC_KEY_REGISTRY[author]
    raise KeyError(f"Public key untuk author '{author}' tidak ditemukan di node ini")


def public_key_to_pem(public_key) -> str:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def public_key_from_pem(pem_str: str):
    return serialization.load_pem_public_key(pem_str.encode("utf-8"))


ACTOR_ROLES = {
    "Produsen": "producer",
    "Distributor": "distributor",
    "Dealer": "dealer",
    "Bengkel": "workshop",
    "Auditor": "auditor",
}

AUTHORIZED_ACTORS = {"Produsen", "Distributor", "Dealer", "Bengkel"}
ACTOR_ORDER = ["Produsen", "Distributor", "Dealer", "Bengkel"]  # urutan tetap untuk menu bernomor

# [2] HYBRID ENCRYPTION: AES-256-GCM + RSA-OAEP

def hybrid_encrypt(plaintext: str, public_key):
    aes_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = AESGCM(aes_key).encrypt(nonce, plaintext.encode("utf-8"), None)
    encrypted_key = public_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(), label=None,
        ),
    )
    return {
        "ciphertext": ciphertext.hex(),
        "nonce": nonce.hex(),
        "encrypted_key": encrypted_key.hex(),
    }


def hybrid_decrypt(envelope, private_key):
    encrypted_key = bytes.fromhex(envelope["encrypted_key"])
    aes_key = private_key.decrypt(
        encrypted_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(), label=None,
        ),
    )
    nonce = bytes.fromhex(envelope["nonce"])
    ciphertext = bytes.fromhex(envelope["ciphertext"])
    return AESGCM(aes_key).decrypt(nonce, ciphertext, None).decode("utf-8")

# [3] DIGITAL SIGNATURE RSA-PSS

def sign_data(data_str: str, private_key):
    signature = private_key.sign(
        data_str.encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return signature.hex()


def verify_data(data_str: str, signature_hex: str, public_key) -> bool:
    try:
        public_key.verify(
            bytes.fromhex(signature_hex),
            data_str.encode("utf-8"),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False

# [3b] HASH DAUN DAN MERKLE ROOT

def hash_leaf(label, value):
    tagged = f"{label}:{value}".encode("utf-8")
    return hashlib.sha256(tagged).digest()


def build_merkle_root(leaves):
    level = leaves[:]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    return level[0]

# [4] TRANSAKSI BERTANDA TANGAN
#
# Satu transaksi = satu perubahan status sebuah suku cadang:
#   sender    : aktor pengirim (pemegang private key yang menandatangani)
#   timestamp : waktu transaksi dibuat
#   part_id   : id suku cadang  } terlihat semua node, dipakai untuk aturan status
#   status    : status baru     }
#   envelope  : detail (part_name, origin, destination, vehicle_id) TERENKRIPSI
#               dengan public key pengirim -- hanya pengirim yang bisa membukanya
#   tx_id     : SHA-256 dari seluruh isi di atas (identitas + bukti isi tak berubah)
#   signature : tanda tangan RSA-PSS pengirim atas tx_id
#
# Node memverifikasi tx_id dan signature SEBELUM menerima transaksi ke pool
# dan sekali lagi saat memvalidasi block.

ALLOWED_TRANSITIONS = {
    "PRODUCED": None,
    "SHIPPED": "PRODUCED",
    "RECEIVED": "SHIPPED",
    "INSTALLED": "RECEIVED",
}

MAX_HEX = 20000                 # batas panjang field hex (ciphertext dst.)
MAX_TX_PER_BLOCK = 5            # jumlah transaksi maksimum yang ditambang dalam satu block
MAX_TX_PER_BLOCK_NET = 500      # batas wajar block dari jaringan (anti block raksasa)
TX_FIELDS = ("sender", "timestamp", "part_id", "status", "envelope", "tx_id", "signature")


class TransactionRejected(Exception):
    pass


class ConsensusRejected(Exception):
    pass


class PoolEmpty(Exception):
    pass


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _is_hex(s, exact=None, maxlen=None):
    if not isinstance(s, str) or not s:
        return False
    if exact is not None and len(s) != exact:
        return False
    if maxlen is not None and len(s) > maxlen:
        return False
    try:
        bytes.fromhex(s)
    except ValueError:
        return False
    return True


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def check_tx_format(tx):
    """Periksa BENTUK transaksi (tipe, rentang). Return pesan error atau None."""
    if not isinstance(tx, dict):
        return "transaksi harus berupa objek"
    for f in TX_FIELDS:
        if f not in tx:
            return f"field '{f}' tidak ada"
    if not isinstance(tx["sender"], str) or tx["sender"] not in AUTHORIZED_ACTORS:
        return "sender tidak berwenang"
    ts = tx["timestamp"]
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts) or ts < 0:
        return "timestamp transaksi tidak valid"
    if not isinstance(tx["part_id"], str) or not (1 <= len(tx["part_id"]) <= 64):
        return "part_id harus string 1..64 karakter"
    if not isinstance(tx["status"], str) or tx["status"] not in ALLOWED_TRANSITIONS:
        return f"status tidak dikenal: {tx['status']!r}"
    env = tx["envelope"]
    if not isinstance(env, dict) or set(env) != {"ciphertext", "nonce", "encrypted_key"}:
        return "envelope tidak valid"
    for k, v in env.items():
        if not _is_hex(v, maxlen=MAX_HEX):
            return f"envelope.{k} bukan hex yang valid"
    if not _is_hex(tx["tx_id"], exact=64):
        return "tx_id harus 64 karakter hex"
    if not _is_hex(tx["signature"], maxlen=1024):
        return "signature bukan hex yang valid"
    return None


def tx_hash(tx) -> str:
    """Hash isi transaksi (tanpa tx_id dan signature). Dihitung ulang tiap verifikasi."""
    body = {k: tx[k] for k in ("sender", "timestamp", "part_id", "status", "envelope")}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def make_transaction(sender, part_id, part_name, origin, destination, vehicle_id, status):
    """Buat transaksi dan TANDATANGANI dengan private key sender (harus dipegang node ini)."""
    if sender not in AUTHOR_KEYS:
        raise PermissionError(f"Node ini tidak memegang private key '{sender}' -- tidak bisa menandatangani")
    private_key, public_key = AUTHOR_KEYS[sender]
    detail = {"part_name": part_name, "origin": origin,
              "destination": destination, "vehicle_id": vehicle_id}
    tx = {
        "sender": sender,
        "timestamp": round(time.time(), 3),
        "part_id": part_id,
        "status": status,
        "envelope": hybrid_encrypt(_canonical(detail), public_key),
    }
    tx["tx_id"] = tx_hash(tx)
    tx["signature"] = sign_data(tx["tx_id"], private_key)
    return tx


def verify_transaction(tx):
    """Verifikasi integritas dan tanda tangan. Return (ok, alasan)."""
    err = check_tx_format(tx)
    if err:
        return False, err
    if tx_hash(tx) != tx["tx_id"]:
        return False, "isi transaksi dimanipulasi (tx_id tidak cocok dengan isinya)"
    try:
        public_key = get_public_key(tx["sender"])
    except KeyError:
        return False, f"public key pengirim '{tx['sender']}' belum dikenal node ini"
    if not verify_data(tx["tx_id"], tx["signature"], public_key):
        return False, "tanda tangan transaksi tidak valid"
    return True, ""


def read_transaction_details(tx):
    """Buka envelope (hanya bisa jika node ini memegang private key pengirim)."""
    if tx["sender"] not in AUTHOR_KEYS:
        raise PermissionError(f"Node ini tidak memegang private key '{tx['sender']}' -- isi terenkripsi")
    private_key, _ = AUTHOR_KEYS[tx["sender"]]
    return json.loads(hybrid_decrypt(tx["envelope"], private_key))


class ChainState:
    """Ringkasan rantai yang dibutuhkan untuk memvalidasi transaksi baru:
    status terakhir tiap part_id dan himpunan tx_id yang sudah ada."""

    def __init__(self):
        self.parts = {}
        self.tx_ids = set()

    def copy(self):
        c = ChainState()
        c.parts = dict(self.parts)
        c.tx_ids = set(self.tx_ids)
        return c

    def apply(self, tx):
        self.parts[tx["part_id"]] = tx["status"]
        self.tx_ids.add(tx["tx_id"])


def state_of_chain(chain) -> ChainState:
    st = ChainState()
    for blk in chain:
        for tx in blk.transactions:
            st.apply(tx)
    return st


def validate_transaction(tx, state: ChainState):
    """Validasi lengkap satu transaksi terhadap `state`. Return (ok, alasan).
    Urutan: bentuk -> tx_id dan tanda tangan -> duplikat -> aturan status.
    Integritas diperiksa SEBELUM duplikat: transaksi yang isinya diubah tetapi
    memakai tx_id yang sudah ada harus DITOLAK, bukan dianggap duplikat."""
    ok, alasan = verify_transaction(tx)       # sudah memeriksa bentuk
    if not ok:
        return False, alasan
    if tx["tx_id"] in state.tx_ids:
        return False, "transaksi sudah ada (duplikat)"

    status = tx["status"]
    syarat = ALLOWED_TRANSITIONS[status]
    terakhir = state.parts.get(tx["part_id"])
    if syarat is None:
        if terakhir is not None:
            return False, f"part_id '{tx['part_id']}' sudah pernah diproduksi (status terakhir {terakhir})"
        return True, ""
    if terakhir is None:
        return False, f"urutan status tidak valid: part '{tx['part_id']}' belum ada -> {status}"
    if terakhir != syarat:
        return False, f"urutan status tidak valid: {terakhir} -> {status}"
    return True, ""


# [5] BLOCK
#
# Struktur sesuai ketentuan C.2:
#   index, timestamp, transactions (DAFTAR), previous_hash, nonce, hash
# ditambah dua field turunan:
#   merkle_root : Merkle root dari seluruh transaksi (mengikat daftar transaksi
#                 ke hash block; ubah satu transaksi -> merkle_root berubah)
#   extra_nonce : cadangan ketika ruang nonce satu putaran habis
#
# hash = SHA-256( index | timestamp | previous_hash | merkle_root | nonce | extra_nonce )
# Hash DISIMPAN di block, tetapi tidak pernah dipercaya begitu saja: validasi
# selalu menghitung ulang dari isi block (compute_hash) lalu membandingkannya.

GENESIS_PREVIOUS_HASH = "0" * 64


class Block:
    def __init__(self, index, transactions, previous_hash, timestamp=None):
        self.index = index
        self.timestamp = round(time.time(), 3) if timestamp is None else timestamp
        self.transactions = list(transactions)
        self.previous_hash = previous_hash
        self.nonce = 0
        self.extra_nonce = 0
        self.merkle_root = compute_merkle_root(self.transactions)
        self.hash = None

    def __repr__(self):
        return f"<Block #{self.index} {len(self.transactions)} tx hash={str(self.hash)[:12]}>"


def compute_merkle_root(transactions) -> str:
    """Merkle root (hex) dari daftar transaksi. Daun = hash(tx_hash + signature),
    sehingga block juga terikat pada tanda tangan tiap transaksi."""
    if not transactions:
        return hashlib.sha256(b"").hexdigest()
    leaves = [hash_leaf("TX", f"{tx_hash(tx)}:{tx['signature']}") for tx in transactions]
    return build_merkle_root(leaves).hex()


def _header_prefix(index, timestamp, previous_hash, merkle_root) -> bytes:
    return (struct.pack(">Q", index) + struct.pack(">d", timestamp)
            + bytes.fromhex(previous_hash) + bytes.fromhex(merkle_root))


def _header_hash(prefix: bytes, nonce: int, extra_nonce: int) -> str:
    return hashlib.sha256(prefix + struct.pack(">Q", nonce) + struct.pack(">I", extra_nonce)).hexdigest()


def compute_hash(block) -> str:
    """Hash RESMI block. SELALU menghitung ulang Merkle root dari daftar transaksi
    SAAT INI (bukan memakai block.merkle_root yang tersimpan), sehingga manipulasi
    isi transaksi mengubah hash ini dan terdeteksi saat dibandingkan dengan
    block.hash yang tersimpan."""
    prefix = _header_prefix(block.index, block.timestamp, block.previous_hash,
                            compute_merkle_root(block.transactions))
    return _header_hash(prefix, block.nonce, block.extra_nonce)


def make_genesis():
    """Block genesis deterministik: sama persis di semua node (tanpa transaksi, tanpa PoW)."""
    g = Block(0, [], GENESIS_PREVIOUS_HASH, timestamp=0.0)
    g.hash = compute_hash(g)
    return g


GENESIS_HASH = make_genesis().hash


def block_to_dict(b) -> dict:
    return {
        "index": b.index, "timestamp": b.timestamp,
        "transactions": copy.deepcopy(b.transactions),   # salinan: dict hasil tidak boleh berbagi isi dengan block asli
        "previous_hash": b.previous_hash, "merkle_root": b.merkle_root,
        "nonce": b.nonce, "extra_nonce": b.extra_nonce, "hash": b.hash,
    }


def check_block_format(d):
    """Periksa BENTUK dict block dari jaringan/disk. Return pesan error atau None."""
    if not isinstance(d, dict):
        return "block harus berupa objek"
    for f in ("index", "timestamp", "transactions", "previous_hash", "merkle_root",
              "nonce", "extra_nonce", "hash"):
        if f not in d:
            return f"field '{f}' tidak ada"
    if not _is_int(d["index"]) or d["index"] < 0:
        return "index harus bilangan bulat >= 0"
    ts = d["timestamp"]
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts) or ts < 0:
        return "timestamp block tidak valid"
    if not isinstance(d["transactions"], list) or len(d["transactions"]) > MAX_TX_PER_BLOCK_NET:
        return f"transactions harus list (maksimum {MAX_TX_PER_BLOCK_NET})"
    for i, tx in enumerate(d["transactions"]):
        err = check_tx_format(tx)
        if err:
            return f"transaksi ke-{i}: {err}"
    for f in ("previous_hash", "merkle_root", "hash"):
        if not _is_hex(d[f], exact=64):
            return f"{f} harus 64 karakter hex"
    if not _is_int(d["nonce"]) or not (0 <= d["nonce"] < 2 ** 64):
        return "nonce di luar rentang"
    if not _is_int(d["extra_nonce"]) or not (0 <= d["extra_nonce"] < 2 ** 32):
        return "extra_nonce di luar rentang"
    return None


def block_from_dict(d) -> Block:
    """Bangun Block dari dict TANPA menghitung ulang apa pun (hash dan merkle_root
    dibawa apa adanya, lalu diperiksa oleh validate_block)."""
    blk = Block.__new__(Block)
    blk.index = d["index"]
    blk.timestamp = d["timestamp"]
    blk.transactions = copy.deepcopy(d["transactions"])
    blk.previous_hash = d["previous_hash"]
    blk.merkle_root = d["merkle_root"]
    blk.nonce = d["nonce"]
    blk.extra_nonce = d["extra_nonce"]
    blk.hash = d["hash"]
    return blk


# [6] PROOF OF WORK -- DIFFICULTY berupa STRING
#
# hash (hex) block harus diawali string DIFFICULTY:
#     DIFFICULTY = "0000"   ->  hash.startswith("0000")
# Tugas 6: ubah menjadi "00000" lalu catat perubahan waktu menambang. Tiap
# tambahan satu "0" membuat kerja rata-rata 16x lebih besar ("0000" ~ 65.536
# percobaan, "00000" ~ 1.048.576). DIFFICULTY adalah konstanta global yang
# HARUS sama di semua node. Nonce disimpan di block supaya PoW dapat
# diverifikasi ulang oleh siapa pun.
#
# Kode PoW lama (per-bit, integer 256-bit, retarget) tidak dihapus: lihat blok
# "[ARSIP]" di bagian PALING BAWAH berkas ini.

DIFFICULTY = "0000"    # tingkat kesulitan proof of work (Tugas 6: ubah menjadi "00000")


def mine_block(block, difficulty=DIFFICULTY, max_try=500000):
    """Cari nonce sampai hash block diawali `difficulty`. Return (nonce, hash)
    atau (None, None) bila `max_try` percobaan habis. Bentuknya sama dengan
    fungsi pada soal; bedanya prefix header dan Merkle root dihitung SEKALI
    di luar loop, lalu hasil akhir diverifikasi ulang dengan compute_hash()."""
    block.merkle_root = compute_merkle_root(block.transactions)
    prefix = _header_prefix(block.index, block.timestamp, block.previous_hash, block.merkle_root)
    for i in range(max_try):
        block.nonce = i
        hasil = _header_hash(prefix, i, block.extra_nonce)
        if hasil.startswith(difficulty):
            if compute_hash(block) == hasil:
                block.hash = hasil
                return i, hasil

    block.nonce = None
    return None, None


def mine_with_retry(block, difficulty=DIFFICULTY, max_try=500000, max_rounds=64):
    """Panggil mine_block berulang. Satu putaran (max_try) bisa habis tanpa hasil
    (mis. "00000" butuh ~1 juta percobaan rata-rata); maka extra_nonce dinaikkan
    dan timestamp diperbarui, lalu dicoba lagi.
    Return (hash, total_percobaan, detik); hash = None bila semua putaran gagal."""
    start = time.time()
    total = 0
    for _ in range(max_rounds):
        nonce, hasil = mine_block(block, difficulty, max_try)
        if hasil is not None:
            return hasil, total + nonce + 1, time.time() - start
        total += max_try
        block.extra_nonce += 1
        block.timestamp = round(time.time(), 3)
    return None, total, time.time() - start


def verify_pow(block, difficulty=DIFFICULTY) -> bool:
    if block.nonce is None:
        return False
    return compute_hash(block).startswith(difficulty)


# [7] VALIDASI BLOCK DAN CHAIN

def validate_block(block, prev, state: ChainState, difficulty=DIFFICULTY):
    """Validasi satu block terhadap block sebelumnya dan state rantai sampai prev.
    Return (ok, alasan, state_baru). Urutan pemeriksaan sengaja dari yang paling
    murah ke yang paling mahal, dan alasan menyebut LAPISAN yang menangkap."""
    if block.index != prev.index + 1:
        return False, f"index {block.index} tidak berurutan setelah block {prev.index}", None
    if block.previous_hash != prev.hash:
        return False, "previous_hash tidak cocok dengan hash block sebelumnya (rantai terputus)", None
    if not block.transactions:
        return False, "block tidak memuat transaksi", None
    if block.merkle_root != compute_merkle_root(block.transactions):
        return False, "Merkle root tidak cocok dengan daftar transaksi (data dimanipulasi)", None
    if block.hash != compute_hash(block):
        return False, "hash tersimpan tidak cocok dengan isi block (data dimanipulasi)", None
    if not verify_pow(block, difficulty):
        return False, "PoW tidak valid (hash tidak diawali difficulty)", None

    st = state.copy()
    for i, tx in enumerate(block.transactions):
        ok, alasan = validate_transaction(tx, st)
        if not ok:
            return False, f"transaksi ke-{i}: {alasan}", None
        st.apply(tx)
    return True, "", st


def is_chain_valid(chain, difficulty=DIFFICULTY):
    """Periksa SELURUH rantai: genesis, lalu tiap block (hash, previous_hash,
    Merkle root, PoW, tanda tangan dan aturan tiap transaksi). Return (ok, alasan)."""
    if not chain:
        return False, "rantai kosong"
    g = chain[0]
    if (g.index != 0 or g.transactions or g.previous_hash != GENESIS_PREVIOUS_HASH
            or g.hash != GENESIS_HASH or compute_hash(g) != GENESIS_HASH):
        return False, "Block 0: genesis tidak sesuai"
    st = ChainState()
    for i in range(1, len(chain)):
        ok, alasan, st2 = validate_block(chain[i], chain[i - 1], st, difficulty)
        if not ok:
            return False, f"Block {i}: {alasan}"
        st = st2
    return True, f"Chain valid ({len(chain) - 1} block + genesis)"


# [8] LEDGER: RANTAI + TRANSACTION POOL + KONSENSUS
#
# Satu objek Ledger = keadaan satu node: rantai (list Block, mulai dari genesis),
# pool transaksi pending, dan riwayat fork. Semua metode aman antar-thread
# (RLock). Penambangan (PoW, lama) sengaja dilakukan DI LUAR lock.

def _default_log(tag, pesan):
    print(f"[{tag}] {pesan}")


class Ledger:
    def __init__(self, log=None):
        self.lock = threading.RLock()
        self.chain = [make_genesis()]
        self.pool = []              # transaksi pending (dict), urutan kedatangan
        self.fork_history = []
        self.log = log or _default_log

    # ---------- keadaan ----------

    def tip(self):
        with self.lock:
            return self.chain[-1]

    def panjang(self) -> int:
        """Jumlah block TANPA genesis (agar angka sama dengan jumlah block yang ditambang)."""
        with self.lock:
            return len(self.chain) - 1

    def state_chain(self) -> ChainState:
        with self.lock:
            return state_of_chain(self.chain)

    def _state_with_pool(self) -> ChainState:
        st = state_of_chain(self.chain)
        for tx in self.pool:
            st.apply(tx)
        return st

    def chain_dicts(self):
        with self.lock:
            return [block_to_dict(b) for b in self.chain]

    def pool_snapshot(self):
        with self.lock:
            return copy.deepcopy(self.pool)

    # ---------- transaction pool ----------

    def add_to_pool(self, tx):
        """Verifikasi transaksi lalu masukkan ke pool. Return (status, alasan);
        status: "NEW" | "DUPLICATE" | "REJECT"."""
        with self.lock:
            tx_id = tx.get("tx_id") if isinstance(tx, dict) else None
            ok, alasan = verify_transaction(tx)     # integritas dulu, baru duplikat
            if not ok:
                self.log("TX", f"DITOLAK {str(tx_id)[:12] if tx_id else '?'}: {alasan}")
                return "REJECT", alasan
            if (tx_id in {t["tx_id"] for t in self.pool}
                    or tx_id in state_of_chain(self.chain).tx_ids):
                return "DUPLICATE", "transaksi sudah ada di pool/chain"
            ok, alasan = validate_transaction(tx, self._state_with_pool())
            if not ok:
                self.log("TX", f"DITOLAK {str(tx_id)[:12] if tx_id else '?'}: {alasan}")
                return "REJECT", alasan
            self.pool.append(copy.deepcopy(tx))
            self.log("TX", f"DITERIMA {tx['tx_id'][:12]} {tx['sender']} {tx['part_id']} -> {tx['status']} "
                           f"(tanda tangan valid)")
            self.log("POOL", f"{len(self.pool)} transaksi pending")
            return "NEW", ""

    def _prune_pool(self):
        """Sinkronkan pool dengan rantai: buang transaksi yang sudah masuk block atau
        yang tidak valid lagi; sisanya dipertahankan dalam urutan semula."""
        sebelum = len(self.pool)
        st = state_of_chain(self.chain)
        masuk = set(st.tx_ids)
        sisa = [t for t in self.pool if t["tx_id"] not in masuk]
        sudah_masuk = sebelum - len(sisa)

        keep = []
        maju = True
        while maju and sisa:
            maju = False
            for t in list(sisa):
                ok, _ = validate_transaction(t, st)
                if ok:
                    keep.append(t)
                    st.apply(t)
                    sisa.remove(t)
                    maju = True
        for t in sisa:
            self.log("POOL", f"transaksi {t['tx_id'][:12]} dibuang (tidak valid lagi terhadap rantai)")
        self.pool = keep
        if sudah_masuk:
            self.log("POOL", f"{sudah_masuk} transaksi sudah masuk block -> dihapus dari pool "
                             f"(sisa pool: {len(self.pool)})")

    # ---------- penambangan ----------

    def build_candidate(self, max_tx=MAX_TX_PER_BLOCK):
        """Bentuk block kandidat dari isi pool (maks `max_tx`), hanya transaksi yang
        valid berurutan terhadap rantai. Return Block atau None bila tidak ada."""
        with self.lock:
            st = state_of_chain(self.chain)
            terpilih, sisa = [], list(self.pool)
            maju = True
            while maju and len(terpilih) < max_tx:
                maju = False
                for t in list(sisa):
                    if len(terpilih) >= max_tx:
                        break
                    ok, _ = validate_transaction(t, st)
                    if ok:
                        terpilih.append(copy.deepcopy(t))
                        st.apply(t)
                        sisa.remove(t)
                        maju = True
            if not terpilih:
                return None
            tip = self.chain[-1]
            return Block(tip.index + 1, terpilih, tip.hash)

    def mine_pending(self, max_tx=MAX_TX_PER_BLOCK, difficulty=DIFFICULTY):
        """Tambang satu block dari isi pool lalu masukkan ke rantai lokal.
        Return (block, percobaan, detik). Pool dikosongkan dari transaksi yang masuk."""
        for _ in range(3):
            cand = self.build_candidate(max_tx)
            if cand is None:
                raise PoolEmpty("pool kosong: tidak ada transaksi valid untuk ditambang")
            self.log("MINING", f"mulai block #{cand.index} ({len(cand.transactions)} transaksi) "
                               f"difficulty={difficulty!r}")
            # [BARU - Checkpoint 5] Cetak isi block kandidat sebelum PoW dimulai: nilai
            # previous_hash yang dipakai dan daftar transaksi yang diambil dari pool.
            # Hanya log; tidak mengubah logika penambangan.
            self.log("MINING", f"kandidat: previous_hash={cand.previous_hash[:16]}... transaksi di block:")
            for t in cand.transactions:
                self.log("MINING", f"   - {t['tx_id'][:12]} {t['sender']} {t['part_id']} -> {t['status']}")
            hasil, percobaan, detik = mine_with_retry(cand, difficulty)     # di luar lock
            if hasil is None:
                raise ConsensusRejected("PoW gagal ditemukan")
            with self.lock:
                tip = self.chain[-1]
                if cand.previous_hash != tip.hash:
                    self.log("MINING", "ujung rantai berubah saat menambang (ada block baru) -> ulangi")
                    continue
                ok, alasan, _ = validate_block(cand, tip, state_of_chain(self.chain), difficulty)
                if not ok:
                    raise ConsensusRejected(alasan)
                self.chain.append(cand)
                self.log("MINING", f"SELESAI block #{cand.index}: nonce={cand.nonce} "
                                   f"percobaan={percobaan:,} waktu={detik:.3f}s hash={cand.hash[:16]}...")
                self._prune_pool()
                # [BARU - Checkpoint 7, sisi penambang] Bukti block diterima rantai lokal:
                # index block baru, panjang rantai bertambah, dan sisa pool (harus 0 bila
                # semua transaksi pending ikut masuk block).
                self.log("CHAIN", f"block #{cand.index} masuk rantai lokal; panjang rantai = "
                                  f"{len(self.chain)} block (termasuk genesis), pool pending = {len(self.pool)}")
                return cand, percobaan, detik
        raise ConsensusRejected("ujung rantai terus berubah saat menambang")

    # ---------- menerima block dari jaringan ----------

    def receive_block(self, d, difficulty=DIFFICULTY):
        """Terima satu block dari peer. Return (status, alasan); status:
        "ADDED" | "DUPLICATE" | "REJECT" (tidak sah) | "FORK" (tidak menyambung ke
        ujung rantai lokal -> pengirim/penerima perlu sinkron)."""
        err = check_block_format(d)
        if err:
            self.log("BLOCK", f"DITOLAK (format): {err}")
            return "REJECT", f"format block tidak valid: {err}"
        blk = block_from_dict(d)
        if blk.hash != compute_hash(blk):           # integritas dulu: hash yang diklaim harus cocok dengan isi
            self.log("BLOCK", f"DITOLAK block #{blk.index}: hash tersimpan tidak cocok dengan isi (data dimanipulasi)")
            return "REJECT", "hash tersimpan tidak cocok dengan isi block (data dimanipulasi)"
        with self.lock:
            tip = self.chain[-1]
            if blk.index <= tip.index:
                if self.chain[blk.index].hash == blk.hash:
                    return "DUPLICATE", "block sudah ada"
                self.log("BLOCK", f"block #{blk.index} dari peer bercabang dari rantai lokal (fork)")
                return "FORK", f"index {blk.index} sudah terisi block lain (fork); perlu sinkron"
            if blk.index != tip.index + 1 or blk.previous_hash != tip.hash:
                self.log("BLOCK", f"block #{blk.index} tidak menyambung ke ujung lokal #{tip.index}")
                return "FORK", "block tidak menyambung ke ujung rantai lokal; perlu sinkron"
            ok, alasan, _ = validate_block(blk, tip, state_of_chain(self.chain), difficulty)
            if not ok:
                self.log("BLOCK", f"DITOLAK block #{blk.index}: {alasan}")
                return "REJECT", alasan
            self.chain.append(blk)
            self.log("BLOCK", f"DITERIMA block #{blk.index} ({len(blk.transactions)} transaksi) "
                              f"hash={blk.hash[:16]}...")
            self._prune_pool()
            # [BARU - Checkpoint 7, sisi penerima] Log yang sama untuk node yang menerima block
            # dari peer, supaya penambahan panjang rantai dan pool kosong terlihat di node tujuan.
            self.log("CHAIN", f"panjang rantai = {len(self.chain)} block (termasuk genesis), "
                              f"pool pending = {len(self.pool)}")
            return "ADDED", ""

    # ---------- longest-chain rule ----------

    def consider_chain(self, dicts, difficulty=DIFFICULTY):
        """Pertimbangkan rantai lengkap dari peer. Rantai diganti HANYA jika sah dan
        LEBIH PANJANG (longest-chain rule). Return dict dengan kunci "status":
        REJECT | SAMA | PERTAHANKAN | SERI | DIPERPANJANG | GANTI."""
        if not isinstance(dicts, list) or not dicts:
            return {"status": "REJECT", "alasan": "rantai harus berupa list tidak kosong"}
        for i, d in enumerate(dicts):
            err = check_block_format(d)
            if err:
                return {"status": "REJECT", "alasan": f"block ke-{i}: {err}"}
        blocks = [block_from_dict(d) for d in dicts]
        ok, alasan = is_chain_valid(blocks, difficulty)
        if not ok:
            self.log("SYNC", f"rantai dari peer DITOLAK: {alasan}")
            return {"status": "REJECT", "alasan": alasan}

        with self.lock:
            own = self.chain
            k = 0
            while k < min(len(own), len(blocks)) and own[k].hash == blocks[k].hash:
                k += 1
            lp, lq = len(own), len(blocks)
            if k == lp == lq:
                return {"status": "SAMA", "panjang": lp - 1}
            if k == lq:      # rantai peer adalah awalan rantai kita
                return {"status": "PERTAHANKAN", "panjang": lp - 1,
                        "alasan": "rantai peer lebih pendek (awalan rantai lokal)"}
            if k == lp:      # rantai kita adalah awalan rantai peer -> perpanjang saja
                self.chain = blocks
                self.log("SYNC", f"rantai diperpanjang dari {lp - 1} ke {lq - 1} block")
                self._prune_pool()
                return {"status": "DIPERPANJANG", "panjang": lq - 1}

            # ---- FORK: kedua rantai bercabang setelah block #k-1 ----
            catatan = {
                "waktu": time.strftime("%H:%M:%S"), "titik_cabang": k - 1,
                "panjang_lokal": lp - 1, "panjang_peer": lq - 1,
                "blok_lokal": [(b.index, b.hash[:12], len(b.transactions)) for b in own[k:]],
                "blok_peer": [(b.index, b.hash[:12], len(b.transactions)) for b in blocks[k:]],
            }
            if lq > lp:
                catatan["keputusan"] = "GANTI"
                orphan = [t for b in own[k:] for t in b.transactions]
                self.chain = blocks
                dikembalikan, dibuang = 0, 0
                ids_baru = state_of_chain(self.chain).tx_ids
                for t in orphan:
                    if t["tx_id"] in ids_baru:
                        continue
                    if self._requeue(t):
                        dikembalikan += 1
                    else:
                        dibuang += 1
                self._prune_pool()
                catatan["tx_dikembalikan"], catatan["tx_dibuang"] = dikembalikan, dibuang
                self.fork_history.append(catatan)
                self.cetak_fork(catatan)
                return {"status": "GANTI", "panjang": lq - 1, "fork": catatan}
            catatan["keputusan"] = "SERI" if lq == lp else "PERTAHANKAN"
            self.fork_history.append(catatan)
            self.cetak_fork(catatan)
            return {"status": catatan["keputusan"], "panjang": lp - 1, "fork": catatan}

    def _requeue(self, tx) -> bool:
        """Kembalikan transaksi dari block yang dibuang ke pool bila masih valid."""
        if tx["tx_id"] in {t["tx_id"] for t in self.pool}:
            return False
        ok, _ = validate_transaction(tx, self._state_with_pool())
        if ok:
            self.pool.append(copy.deepcopy(tx))
        return ok

    def cetak_fork(self, c):
        self.log("FORK", f"terdeteksi: rantai bercabang setelah block #{c['titik_cabang']}")
        self.log("FORK", f"  panjang lokal = {c['panjang_lokal']} block, panjang peer = {c['panjang_peer']} block")
        self.log("FORK", f"  block lokal setelah titik cabang : {c['blok_lokal']}")
        self.log("FORK", f"  block peer  setelah titik cabang : {c['blok_peer']}")
        if c["keputusan"] == "GANTI":
            self.log("FORK", f"  KEPUTUSAN: rantai peer LEBIH PANJANG -> rantai lokal diganti (longest-chain rule)")
            self.log("FORK", f"  {len(c['blok_lokal'])} block lokal menjadi ORPHAN (dibuang dari rantai utama); "
                             f"{c.get('tx_dikembalikan', 0)} transaksinya dikembalikan ke pool, "
                             f"{c.get('tx_dibuang', 0)} dibuang (tidak valid lagi)")
        elif c["keputusan"] == "SERI":
            self.log("FORK", "  KEPUTUSAN: panjang SAMA -> rantai lokal dipertahankan; menunggu block berikutnya")
        else:
            self.log("FORK", "  KEPUTUSAN: rantai lokal LEBIH PANJANG -> dipertahankan; rantai peer diabaikan")

    # ---------- validasi dan penyimpanan ----------

    def validate(self, difficulty=DIFFICULTY):
        with self.lock:
            return is_chain_valid(self.chain, difficulty)

    def load_state(self, chain_dicts, pool_dicts, difficulty=DIFFICULTY):
        """Muat rantai dan pool dari penyimpanan. Rantai divalidasi ulang penuh.
        Return (ok, pesan)."""
        for i, d in enumerate(chain_dicts):
            err = check_block_format(d)
            if err:
                return False, f"block ke-{i}: {err}"
        blocks = [block_from_dict(d) for d in chain_dicts]
        ok, alasan = is_chain_valid(blocks, difficulty)
        if not ok:
            return False, alasan
        with self.lock:
            self.chain = blocks
            self.pool = []
            for t in pool_dicts:
                if check_tx_format(t) is None:
                    self._requeue(t)
            self._prune_pool()
        return True, f"{len(blocks) - 1} block dan {len(self.pool)} transaksi pending dimuat"


# [9] TAMPILAN, DEMO DETEKSI MANIPULASI, DAN CLI MANDIRI

def print_chain(chain):
    print("\n=== CHAIN ===")
    for blk in chain:
        print(f"Block #{blk.index}" + ("  (genesis)" if blk.index == 0 else ""))
        print(f"  hash          : {blk.hash}")
        print(f"  previous_hash : {blk.previous_hash}")
        print(f"  merkle_root   : {blk.merkle_root}")
        print(f"  timestamp     : {blk.timestamp}")
        print(f"  nonce         : {blk.nonce} (extra_nonce {blk.extra_nonce})")
        print(f"  transaksi     : {len(blk.transactions)}")
        for tx in blk.transactions:
            print(f"    - {tx['tx_id'][:12]}  {tx['sender']:<11} {tx['part_id']:<10} {tx['status']}")
            try:
                d = read_transaction_details(tx)
                print(f"        detail: {d['part_name']} | {d['origin']} -> {d['destination']} | {d['vehicle_id']}")
            except PermissionError:
                print("        detail: (terenkripsi -- node ini tidak memegang private key pengirim)")


def pilih_dari_daftar(daftar, label):
    """Tampilkan daftar bernomor dan minta user pilih salah satu lewat angka."""
    print(f"Pilih {label}:")
    for i, item in enumerate(daftar, start=1):
        print(f"  {i}) {item}")
    while True:
        pilihan = input(f"Nomor {label}: ").strip()
        if pilihan.isdigit() and 1 <= int(pilihan) <= len(daftar):
            return daftar[int(pilihan) - 1]
        print("Nomor tidak valid, coba lagi.")


def demo_manipulasi(chain, difficulty=DIFFICULTY):
    """Peragakan lima cara memanipulasi data pada SALINAN rantai dan lapisan
    yang menangkapnya. Rantai asli tidak disentuh. Return daftar
    (judul, terdeteksi, alasan)."""
    if len(chain) < 2:
        return [("Demo manipulasi", False, "butuh minimal 1 block selain genesis")]
    hasil = []

    def salinan():
        return copy.deepcopy(chain)

    def remine(b):
        b.merkle_root = compute_merkle_root(b.transactions)
        mine_with_retry(b, difficulty)

    def periksa(judul, c):
        ok, alasan = is_chain_valid(c, difficulty)
        hasil.append((judul, not ok, alasan))

    k = 1
    c = salinan()
    c[k].transactions[0]["part_id"] += "-X"
    periksa(f"A. Ubah part_id transaksi di block {k} (tanpa menyentuh hash)", c)

    c = salinan()
    c[k].transactions[0]["part_id"] += "-X"
    c[k].merkle_root = compute_merkle_root(c[k].transactions)
    c[k].hash = compute_hash(c[k])
    while c[k].hash.startswith(difficulty):      # hindari lolos PoW secara kebetulan
        c[k].nonce += 1
        c[k].hash = compute_hash(c[k])
    periksa(f"B. Ubah transaksi + hitung ulang Merkle root dan hash block {k} (tanpa mining)", c)

    c = salinan()
    t = c[k].transactions[0]
    t["part_id"] += "-X"
    t["tx_id"] = tx_hash(t)
    remine(c[k])
    periksa(f"C. Ubah transaksi, hitung ulang tx_id, lalu tambang ulang block {k} (tanpa private key)", c)

    if len(chain) >= 3:
        c = salinan()
        c[k].timestamp = round(c[k].timestamp + 1, 3)
        remine(c[k])
        periksa(f"D. Ubah timestamp block {k} lalu tambang ulang (block {k} sendiri valid)", c)
    else:
        hasil.append(("D. Efek berantai ke block berikutnya", False,
                      "butuh minimal 2 block selain genesis untuk diperagakan"))

    c = salinan()
    c[k].previous_hash = "f" * 64
    periksa(f"E. Putuskan previous_hash block {k}", c)
    return hasil


def load_transactions_from_json(ledger, path):
    """Muat daftar transaksi dari JSON lalu masukkan ke pool. Setiap entri berisi
    author, part_id, part_name, origin, destination, vehicle_id, status."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ditambah = ditolak = 0
    for item in data:
        get_or_create_author(item["author"])
        tx = make_transaction(item["author"], item["part_id"], item["part_name"], item["origin"],
                              item["destination"], item["vehicle_id"], item["status"])
        status, _ = ledger.add_to_pool(tx)
        if status == "NEW":
            ditambah += 1
        else:
            ditolak += 1
    return ditambah, ditolak


def run_cli():
    """Mode mandiri (tanpa jaringan): pool, mining, validasi, demo manipulasi."""
    ledger = Ledger()
    for a in ACTOR_ORDER:
        get_or_create_author(a)
    while True:
        print("\n1) Buat transaksi baru (masuk pool)")
        print("2) Lihat pool")
        print("3) Tambang block dari pool")
        print("4) Tampilkan chain")
        print("5) Validasi chain")
        print("6) Demo deteksi manipulasi data")
        print("7) Muat transaksi dari contoh_transaksi.json")
        print("0) Keluar")
        pilihan = input("Pilih menu: ").strip()
        if pilihan == "1":
            sender = pilih_dari_daftar(ACTOR_ORDER, "pengirim")
            part_id = input("part_id: ").strip()
            part_name = input("part_name: ").strip()
            origin = input("origin: ").strip()
            dest = input("destination: ").strip()
            veh = input("vehicle_id: ").strip()
            status = pilih_dari_daftar(list(ALLOWED_TRANSITIONS), "status")
            tx = make_transaction(sender, part_id, part_name, origin, dest, veh, status)
            st, alasan = ledger.add_to_pool(tx)
            print("-> masuk pool" if st == "NEW" else f"-> {st}: {alasan}")
        elif pilihan == "2":
            for t in ledger.pool_snapshot():
                print(f"  {t['tx_id'][:12]} {t['sender']} {t['part_id']} {t['status']}")
            print(f"({len(ledger.pool)} transaksi pending)")
        elif pilihan == "3":
            try:
                ledger.mine_pending()
            except (PoolEmpty, ConsensusRejected) as e:
                print(f"Gagal: {e}")
        elif pilihan == "4":
            print_chain(ledger.chain)
        elif pilihan == "5":
            print(ledger.validate())
        elif pilihan == "6":
            for judul, terdeteksi, alasan in demo_manipulasi(ledger.chain):
                print(f"{'[TERDETEKSI]' if terdeteksi else '[LOLOS!]    '} {judul}\n      -> {alasan}")
        elif pilihan == "7":
            print(load_transactions_from_json(ledger, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                   "contoh_transaksi.json")))
        elif pilihan == "0":
            break
        else:
            print("Pilihan tidak dikenal.")


if __name__ == "__main__":
    run_cli()

# =====================================================================
# [ARSIP] KODE LAMA -- PoW per-bit (integer 256-bit) + retarget
# =====================================================================
# Semua baris di bawah ini adalah KOMENTAR (tidak dijalankan). Ini kode PoW
# lama (difficulty per bit, perbandingan integer, retarget) sebelum diganti
# DIFFICULTY berupa string. Disimpan agar bisa ditunjukkan. Keterangan: PoW
# lama menyimpan `difficulty_bits` di setiap block; struktur block revisi 5
# tidak memilikinya, jadi mengaktifkannya kembali berarti mengubah Block juga
# (versi lengkap sebelum revisi 5 ada di arsip_versi_lama/).
#
# --- (1) Konstanta dan fungsi PoW lama (bagian [9], apa adanya) ---
# DEFAULT_DIFFICULTY_BITS = 16      # setara prefix hex "0000" (16 bit nol di depan)
# MIN_DIFFICULTY_BITS = 8
# MAX_DIFFICULTY_BITS = 24
# TARGET_BLOCK_SECONDS = 0.3        # target rata-rata waktu mining per block (didemokan ringan)
# RETARGET_WINDOW = 3               # jumlah block terakhir yang dipakai sbg sampel retarget
# NONCE_SPACE = 2 ** 32             # ruang nonce per "putaran" sebelum extra_nonce naik
#
#
# def difficulty_target(bits: int) -> int:
#     """Ubah 'bits' (jumlah bit nol di depan yang disyaratkan) jadi ambang batas integer 256-bit."""
#     bits = max(0, min(256, bits))
#     return 1 << (256 - bits)
#
#
# def hash_meets_difficulty(hash_hex: str, bits: int) -> bool:
#     return int(hash_hex, 16) < difficulty_target(bits)
#
#
# def compute_next_difficulty(chain_map, parent_block, target_seconds=TARGET_BLOCK_SECONDS,
#                              window=RETARGET_WINDOW, min_bits=MIN_DIFFICULTY_BITS,
#                              max_bits=MAX_DIFFICULTY_BITS):
#     """Retarget sederhana: bandingkan rata-rata selisih timestamp beberapa
#     block terakhir dengan target waktu, lalu naikkan/turunkan difficulty 1 bit."""
#     if parent_block is None:
#         return DEFAULT_DIFFICULTY_BITS
#
#     samples = []
#     cur = parent_block
#     for _ in range(window):
#         if cur.parent_id is None or cur.parent_id not in chain_map:
#             break
#         prev = chain_map[cur.parent_id]
#         samples.append(cur.timestamp - prev.timestamp)
#         cur = prev
#
#     if not samples:
#         return parent_block.difficulty_bits
#
#     avg = sum(samples) / len(samples)
#     bits = parent_block.difficulty_bits
#     if avg < target_seconds * 0.5:
#         bits = min(max_bits, bits + 1)
#     elif avg > target_seconds * 2:
#         bits = max(min_bits, bits - 1)
#     return bits
#
#
# def mine_block(block, max_rounds=64):
#     """Cari nonce yang memenuhi difficulty_bits milik block.
#
#     content_root dihitung SEKALI di sini sbg variabel LOKAL (bukan atribut
#     tersimpan di objek) -- aman dipakai berulang selama loop karena block ini
#     masih kandidat privat yang belum dibagikan/disentuh pihak lain selama
#     mining berlangsung. Begitu kandidat nonce ditemukan, hasilnya divalidasi
#     ulang lewat compute_hash() resmi (yang SELALU menghitung fresh) sebelum
#     diterima -- menjaga agar tidak ada state block yang diam-diam berubah
#     di luar dugaan selama pencarian."""
#     start = time.time()
#     attempts = 0
#     content_root = compute_content_root(block)
#     for _round in range(max_rounds):
#         for n in range(NONCE_SPACE):
#             block.nonce = n
#             attempts += 1
#             h = _header_hash(content_root, block.timestamp, block.nonce,
#                               block.extra_nonce, block.difficulty_bits)
#             if hash_meets_difficulty(h, block.difficulty_bits):
#                 final_hash = compute_hash(block)
#                 if final_hash == h:
#                     return final_hash, attempts, time.time() - start
#                 # Kalau tidak cocok (semestinya tidak pernah terjadi kecuali
#                 # ada bug), jangan diterima -- lanjutkan pencarian.
#         # Ruang nonce (32-bit) habis dalam 1 putaran -- perpanjang ruang
#         # pencarian lewat extra_nonce & perbarui timestamp, lalu coba lagi.
#         block.extra_nonce += 1
#         block.timestamp = round(time.time(), 3)
#     return None, attempts, time.time() - start
#
#
# def verify_pow(block) -> bool:
#     if block.nonce is None:
#         return False
#     return hash_meets_difficulty(compute_hash(block), block.difficulty_bits)
#
# =====================================================================
# [AKHIR ARSIP]
# =====================================================================