import hashlib
import json
import os
import struct
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# =========================================================
# BLOCKCHAIN TRACEABILITY SUKU CADANG KENDARAAN -- v2
# =========================================================
# Perubahan dari versi sebelumnya (sesuai masukan dosen):
#   1. PoW dibuat lebih profesional: header mining dipisah dari
#      Merkle root konten (tidak dihitung ulang tiap percobaan nonce),
#      target pakai perbandingan integer 256-bit (bukan prefix string),
#      difficulty per-block yang bisa menyesuaikan diri (retarget),
#      dan penanganan saat ruang nonce habis (extra_nonce + timestamp).
#   1b. (Revisi 3, Tugas 6) PoW memakai DIFFICULTY berupa STRING ala soal
#      (DIFFICULTY = "0000" -> "00000") dan fungsi mine_block versi soal.
#      Kode PoW lama (per-bit, integer 256-bit, retarget) tidak dihapus:
#      ada sebagai komentar di bagian PALING BAWAH berkas ([ARSIP]).
#   2. Analisis hash sandwich vs level keamanan hash -- lihat bagian [6].
#   3. Tidak ada lagi data hardcode dieksekusi otomatis saat import;
#      block baru dimasukkan lewat CLI interaktif atau file JSON.
#   4. Modul network terpisah (node.py) supaya 2 laptop bisa jadi
#      2 node yang saling terhubung & tukar block.
#   5. add_block_to_chain menjamin PoW selesai (dan valid) SEBELUM
#      block disentuh lebih lanjut (ditandatangani / dimasukkan ke chain).
# =========================================================

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

# [4] FIELD-LEVEL HASHING + MERKLE ROOT

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

# [5] BLOCK
#
# [PERBAIKAN PROFESIONAL] Konten block dipecah jadi dua kelompok:
#   - content_root: Merkle root dari field yang TIDAK berubah selama mining
#     (id, author, part_id, status, envelope, parent_id, parent_hash, salt).
#     Dihitung SEKALI saat block dibuat.
#   - header mining: timestamp, nonce, extra_nonce -- field (revisi 3: difficulty_bits
#     tidak lagi ikut; difficulty kini string global DIFFICULTY) --
#     yang berubah-ubah selama pencarian PoW. Ini meniru desain header block
#     Bitcoin (Merkle root dipisah dari nonce) sehingga tiap percobaan nonce
#     TIDAK perlu membangun ulang seluruh pohon Merkle (sebelumnya:
#     compute_content_root() dipanggil ulang -- termasuk 12 hash leaf +
#     beberapa level Merkle -- di SETIAP percobaan nonce, sangat boros).
#     Sekarang tiap percobaan nonce cuma 1x SHA-256 atas header kecil (<64 byte)
#     + hash sandwich -- jauh lebih efisien dan mendekati praktik nyata.


class Block:
    def __init__(self, id, author, transaction, parent_id=None, parent_hash=None):
        self.id = id
        self.author = author
        self.parent_id = parent_id
        self.parent_hash = parent_hash
        self.timestamp = round(time.time(), 3)
        self.salt = os.urandom(8).hex()
        self.nonce = 0
        self.extra_nonce = 0
        # [ARSIP] self.difficulty_bits = DEFAULT_DIFFICULTY_BITS if difficulty_bits is None else difficulty_bits
        # (difficulty tidak lagi disimpan per block; lihat DIFFICULTY di bagian [9])
        self.signature = None

        # part_id & status disimpan PLAINTEXT sebagai metadata block (terpisah
        # dari envelope terenkripsi) supaya validasi urutan transaksi tidak
        # perlu mendekripsi data milik author lain. Field sensitif lain
        # (part_name, origin, destination, vehicle_id) tetap di dalam envelope.
        self.part_id = transaction["part_id"]
        self.status = transaction["status"]

        transaction_json = json.dumps(transaction, sort_keys=True)
        _, public_key = get_or_create_author(author)
        self.envelope = hybrid_encrypt(transaction_json, public_key)

        # [PENTING -- KEAMANAN] content_root SENGAJA TIDAK disimpan sebagai
        # atribut/cache di sini. Kalau di-cache, memanipulasi field block
        # (envelope, part_id, status, dst) SETELAH block dibuat tidak akan
        # mengubah hash yang dihasilkan compute_hash() -- signature & parent_hash
        # yang tercatat di anaknya tetap terlihat "valid" walau isinya sudah
        # dipalsukan. Karena itu content_root SELALU dihitung ulang dari nilai
        # field yang tersimpan SAAT ITU JUGA lewat compute_content_root(block)
        # di bawah -- lihat penjelasan lengkap di compute_hash().


# [6] HASH SANDWICH -- DIHAPUS (masukan dosen poin 2, keputusan akhir)
#
# PERTANYAAN: apakah melapis Merkle root dengan hash sandwich (cascade
# SHA-256 -> SHA3-256 -> BLAKE2b) MENINGKATKAN LEVEL keamanan hash block?
#
# JAWABAN: TIDAK, dan setelah dianalisis lebih jauh, lapisan ini juga TIDAK
# DIPERLUKAN sama sekali -- makanya dihapus dari compute_hash() di bawah.
# Alasannya dua lapis:
#
#   1) Cascade sekuensial H3(H2(H1(x))) levelnya dibatasi oleh hash TERAKHIR
#      (H3) dalam rantai, BUKAN jumlah/gabungan ketiganya. Untuk membobol
#      digest akhir, penyerang cukup mencari collision/preimage pada H3 dari
#      INPUT APAPUN yang menghasilkan digest tsb -- ia tidak wajib membobol
#      H1 dan H2 sekaligus. Digest tetap 32 byte (256 bit) di tiap tahap --
#      ruang hash tidak melebar. Urutan resepnya pun ditentukan dari block_id
#      yang PUBLIK, bukan rahasia, jadi tidak ada nilai "security by
#      obscurity" juga.
#
#   2) Yang lebih mendasar: pada saat hash sandwich dijalankan, Merkle root
#      (content_root, dibangun dari SHA-256 berlapis lewat build_merkle_root)
#      DAN header_digest (SHA-256 atas content_root + field mining) SUDAH
#      merupakan satu digest final yang mencakup SELURUH isi block. Tidak ada
#      data baru yang digabungkan oleh hash sandwich -- ia cuma memutar ulang
#      digest yang sudah final lewat hash lain, tanpa menambah cakupan
#      (coverage) apa pun. Karena itu hash sandwich bukan cuma "tidak
#      menaikkan level", tapi juga REDUNDAN -- tidak menutup celah apa pun
#      yang sebelumnya masih terbuka.
#
# Kalau suatu saat proyek ini butuh proteksi tambahan terhadap risiko satu
# algoritma hash suatu saat ditemukan lemah, pendekatan yang benar secara
# kriptografis adalah COMBINER PARALEL (bukan cascade) -- menggabungkan dua
# digest yang dihitung INDEPENDEN dari input yang sama, misal
# H1(x) XOR H2(x), BUKAN memasukkan output satu hash sbg input hash
# berikutnya. Combiner semacam ini terbukti tetap collision-resistant selama
# SALAH SATU dari H1 atau H2 masih aman ("robust combiner") -- sifat yang
# tidak dimiliki cascade sekuensial. Contoh (tidak dipakai, sekadar referensi
# kalau suatu saat diperlukan):
#
#   def hash_combiner_demo(data: bytes) -> bytes:
#       a = hashlib.sha256(data).digest()
#       b = hashlib.sha3_256(data).digest()
#       return bytes(x ^ y for x, y in zip(a, b))
#
# KESIMPULAN: compute_hash() di bawah cukup memakai SATU kali SHA-256 atas
# header (yang sudah mencakup content_root + field mining). Ini secara
# kriptografis setara kekuatannya dengan versi sandwich sebelumnya (levelnya
# toh dibatasi hash terakhir), tapi lebih sederhana, lebih cepat, dan tidak
# mengklaim proteksi yang sebenarnya tidak ada.


def compute_content_root(block):
    """SELALU dihitung ulang dari NILAI FIELD block SAAT INI -- tidak pernah
    dari cache/atribut tersimpan. Ini yang menjamin manipulasi field APAPUN
    pada block manapun (bukan cuma oleh anaknya lewat parent_hash) pasti
    mengubah hash block tsb. Lihat catatan keamanan di compute_hash()."""
    leaves = [
        hash_leaf("FIELD:id", block.id),
        hash_leaf("FIELD:author", block.author),
        hash_leaf("FIELD:part_id", block.part_id),
        hash_leaf("FIELD:status", block.status),
        hash_leaf("FIELD:envelope.ciphertext", block.envelope["ciphertext"]),
        hash_leaf("FIELD:envelope.nonce", block.envelope["nonce"]),
        hash_leaf("FIELD:envelope.encrypted_key", block.envelope["encrypted_key"]),
        hash_leaf("FIELD:parent_id", block.parent_id),
        hash_leaf("FIELD:parent_hash", block.parent_hash),
        hash_leaf("FIELD:salt", block.salt),
    ]
    return build_merkle_root(leaves)


def _header_hash(content_root: bytes, timestamp: float, nonce: int, extra_nonce: int) -> str:
    """Hash header kecil (content_root + field mining) -- SATU kali SHA-256,
    tanpa hash sandwich (lihat analisis di bagian [6] di atas kenapa lapisan
    tambahan itu dihapus). Dipakai bersama oleh compute_hash() (selalu fresh)
    dan mine_block() (pakai snapshot lokal demi kecepatan) supaya logikanya
    tidak pernah bercabang/berbeda."""
    header = (
        content_root
        + struct.pack(">d", timestamp)
        + struct.pack(">Q", nonce)
        + struct.pack(">I", extra_nonce)
        # [ARSIP] + struct.pack(">H", difficulty_bits)   -- difficulty bukan bagian header lagi
    )
    return hashlib.sha256(header).hexdigest()


def compute_hash(block) -> str:
    """Hash RESMI sebuah block -- dipakai untuk sign, verify signature,
    verify PoW, dan validasi chain. SELALU menghitung ulang content_root dari
    field block SAAT INI (compute_content_root, bukan cache), sehingga:
      - Kalau isi block ini sendiri diubah (envelope/part_id/status/dst),
        hash-nya berubah -> signature-nya sendiri jadi tidak valid lagi.
      - Kalau block INI adalah parent dari block lain, dan isinya diubah,
        hash yg dihitung ulang di sini juga akan berbeda dari parent_hash
        yang dicatat anaknya -> is_chain_valid() menangkapnya juga lewat
        jalur itu.
    Dua jalur deteksi ini independen; MENGHILANGKAN salah satunya (mis. lewat
    caching content_root) membuka celah manipulasi tanpa terdeteksi -- inilah
    bug yang diperbaiki di revisi sebelumnya."""
    content_root = compute_content_root(block)
    return _header_hash(content_root, block.timestamp, block.nonce, block.extra_nonce)

# [7] SIGN & VERIFY BLOCK

def sign_block(block):
    private_key, _ = get_or_create_author(block.author)
    block.signature = sign_data(compute_hash(block), private_key)


def verify_block_signature(block) -> bool:
    try:
        public_key = get_public_key(block.author)
    except KeyError:
        return False
    if block.signature is None:
        return False
    return verify_data(compute_hash(block), block.signature, public_key)


def read_block_transaction(block):
    if block.author not in AUTHOR_KEYS:
        raise PermissionError(
            f"Node ini tidak memegang private key '{block.author}' -- tidak bisa membuka isi transaksi"
        )
    private_key, _ = get_or_create_author(block.author)
    return json.loads(hybrid_decrypt(block.envelope, private_key))

# [8] VALIDASI ATURAN TRANSAKSI

ALLOWED_TRANSITIONS = {
    "PRODUCED": None,
    "SHIPPED": "PRODUCED",
    "RECEIVED": "SHIPPED",
    "INSTALLED": "RECEIVED",
}


def validate_transaction(transaction, parent_block=None):
    required_fields = {"part_id", "part_name", "origin", "destination", "vehicle_id", "status"}
    if not required_fields.issubset(transaction.keys()):
        return False, "Field transaksi tidak lengkap"

    status = transaction["status"]
    if status not in ALLOWED_TRANSITIONS:
        return False, f"Status transaksi tidak dikenal: {status}"

    required_previous_status = ALLOWED_TRANSITIONS[status]
    if required_previous_status is None:
        return True, "Transaksi produksi valid"

    if parent_block is None:
        return False, "Transaksi sebelumnya tidak ditemukan"
    if parent_block.part_id != transaction["part_id"]:
        return False, "Part ID tidak sesuai dengan riwayat sebelumnya"
    if parent_block.status != required_previous_status:
        return False, f"Urutan status tidak valid: {parent_block.status} -> {status}"

    return True, "Transaksi valid"

# [9] PROOF OF WORK -- versi soal Tugas 6: DIFFICULTY berupa STRING
#
# Difficulty adalah string awalan hash, BUKAN jumlah bit:
#     DIFFICULTY = "0000"   -> hash (hex) harus diawali "0000"
# Tugas 6: ubah menjadi "00000" lalu catat perubahan waktu menambang.
# Tiap tambahan satu karakter "0" membuat kerja rata-rata 16x lebih besar
# (1 digit hex = 4 bit): "0000" ~ 65.536 percobaan, "00000" ~ 1.048.576.
#
# Konsekuensi dibanding versi lama (per-bit + retarget):
#   - DIFFICULTY adalah konstanta GLOBAL, tidak disimpan di dalam block dan
#     tidak ada retarget. Semua node HARUS memakai nilai yang sama; kalau
#     berbeda, block dari node lain ditolak ("PoW tidak valid").
#   - Header hash tidak lagi memuat difficulty_bits.
#
# Yang dipertahankan dari versi lama: header mining dipisah dari Merkle root
# konten (content_root dihitung SEKALI per putaran, bukan tiap percobaan) dan
# penanganan nonce habis (extra_nonce + timestamp) lewat mine_with_retry().
#
# Kode PoW LAMA (integer 256-bit per bit + retarget) TIDAK dihapus: lihat blok
# "[ARSIP]" di bagian PALING BAWAH berkas ini.

DIFFICULTY = "0000"    # tingkat kesulitan proof of work (Tugas 6: ubah menjadi "00000")


def mine_block(block, difficulty=DIFFICULTY, max_try=500000):
    """Cari nonce sampai hash block diawali `difficulty`. Return (nonce, hash)
    atau (None, None) bila `max_try` percobaan habis.

    Bentuknya sama dengan fungsi pada soal. Dua penyesuaian untuk berkas ini:
      - block adalah objek Block (block.nonce), bukan dict;
      - hash per percobaan dihitung dari content_root yang dihitung SEKALI di
        luar loop (hasilnya sama dengan compute_hash(block)), lalu kandidat
        diverifikasi ulang dengan compute_hash() resmi sebelum diterima."""
    content_root = compute_content_root(block)
    for i in range(max_try):
        block.nonce = i
        hasil = _header_hash(content_root, block.timestamp, block.nonce, block.extra_nonce)
        if hasil.startswith(difficulty):
            if compute_hash(block) == hasil:
                return i, hasil

    block.nonce = None
    return None, None


def mine_with_retry(block, difficulty=DIFFICULTY, max_try=500000, max_rounds=64):
    """Panggil mine_block berulang. Satu putaran (max_try) bisa habis tanpa hasil
    (mis. "00000" butuh ~1 juta percobaan rata-rata, jauh di atas 500.000);
    maka extra_nonce dinaikkan dan timestamp diperbarui, lalu dicoba lagi.
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

# [10] GATE: VALIDASI + WHITELIST + PoW SEBELUM BLOCK DIBUAT (masukan poin 5)
#
# Urutan di add_block_to_chain() dijamin sbb, dan block TIDAK PERNAH masuk
# chain_map sebelum semua tahap ini lolos:
#   1. Cek wewenang author (whitelist)
#   2. Cek urutan status transaksi terhadap parent
#   3. Bentuk block KANDIDAT (belum masuk chain_map)
#   4. WAJIB lolos PoW -- kalau gagal, exception dilempar, kandidat dibuang
#   5. Baru ditandatangani (memakai hash final pasca-PoW)
#   6. BARU DI SINI block dimasukkan ke chain_map


class TransactionRejected(Exception):
    pass


class ConsensusRejected(Exception):
    pass


def add_block_to_chain(chain_map, next_id, author, transaction, parent_id=None,
                        difficulty=DIFFICULTY, max_rounds=64):
    if next_id in chain_map:
        raise TransactionRejected(f"Block id {next_id} sudah dipakai di chain ini")

    if author not in AUTHORIZED_ACTORS:
        raise ConsensusRejected(f"Author '{author}' tidak terdaftar sebagai aktor berwenang menulis transaksi")

    parent_block = None
    if parent_id is not None:
        if parent_id not in chain_map:
            raise TransactionRejected(f"Parent block {parent_id} tidak ditemukan di chain")
        parent_block = chain_map[parent_id]

    valid, message = validate_transaction(transaction, parent_block)
    if not valid:
        raise TransactionRejected(f"Block ditolak, tidak dibuat (id={next_id}, author={author}): {message}")

    parent_hash = compute_hash(parent_block) if parent_block is not None else None

    # Kandidat dibentuk di sini -- BELUM ada jejaknya di chain_map.
    candidate = Block(next_id, author, transaction, parent_id=parent_id,
                       parent_hash=parent_hash)

    block_hash, attempts, elapsed = mine_with_retry(candidate, difficulty=difficulty,
                                                    max_rounds=max_rounds)
    if block_hash is None:
        raise ConsensusRejected(f"PoW gagal ditemukan untuk block {next_id} setelah {attempts} percobaan")

    candidate.mining_attempts = attempts   # untuk eksperimen difficulty (tidak ikut hash)
    sign_block(candidate)          # sah ditandatangani hanya setelah PoW final
    chain_map[next_id] = candidate  # baru DI SINI resmi masuk chain
    return candidate, elapsed

# [11] VALIDASI CHAIN

def is_chain_valid(latest_block, chain_map):
    cur = latest_block
    while cur:
        if not verify_block_signature(cur):
            return False, f"Signature tidak valid pada block {cur.id}"
        if not verify_pow(cur):
            return False, f"PoW tidak memenuhi difficulty pada block {cur.id}"
        # [ARSIP] pemeriksaan difficulty_bits terhadap aturan retarget dinonaktifkan:
        # difficulty kini string global (DIFFICULTY), tidak disimpan per block.
        # Kode lamanya ada di blok [ARSIP] paling bawah berkas ini.
        if cur.parent_id is None:
            break
        if cur.parent_id not in chain_map:
            return False, f"Parent block {cur.parent_id} tidak ditemukan"
        parent = chain_map[cur.parent_id]
        if cur.parent_hash != compute_hash(parent):
            return False, f"Parent hash mismatch pada block {cur.id}"
        cur = parent
    return True, "Chain valid"


def demo_cascading_tamper_detection(chain_map, tip_block):
    """[BUKTI KEAMANAN] Menjawab pertanyaan: 'bagaimana jika peretas mengubah
    data block DI TENGAH, lalu juga menambal parent_hash pada block-block
    sesudahnya supaya kelihatan tetap cocok?'

    Jawaban: TETAP TERDETEKSI. Sebabnya, parent_hash yang disimpan sebuah
    block ikut menjadi salah satu leaf yang dihash ke content_root block
    ITU SENDIRI (lihat compute_content_root -- "FIELD:parent_hash"), dan
    hash itulah yang ditandatangani lewat sign_block(). Akibatnya, menambal
    parent_hash di satu block mengubah hash block tsb sendiri, yang berarti
    signature LAMA-nya (dibuat sebelum ditambal) langsung tidak valid --
    KECUALI peretas juga memegang private key author block itu untuk
    menandatangani ulang. Dan karena block berikutnya ikut menyimpan
    parent_hash ke block ini, efeknya MERAMBAT ke semua block sesudahnya
    sampai ke ujung chain -- peretas harus membobol private key SETIAP
    author dari titik manipulasi sampai block terakhir, bukan cuma satu.

    Fungsi ini men-demo-kan itu pada SALINAN block (deepcopy sederhana lewat
    rekonstruksi manual), TIDAK mengubah chain_map asli."""
    import copy

    print("=== DEMO: manipulasi block tengah + tambal parent_hash di bawahnya ===")

    # Ambil salinan independen supaya chain asli tidak ikut rusak.
    salinan = {}
    urutan = []
    cur = tip_block
    while cur:
        salinan[cur.id] = copy.deepcopy(cur)
        urutan.append(cur.id)
        cur = chain_map.get(cur.parent_id) if cur.parent_id is not None else None
    urutan.reverse()  # dari genesis ke tip

    if len(urutan) < 2:
        print("Butuh minimal 2 block untuk demo ini.")
        return

    target_id = urutan[len(urutan) // 2]  # pilih salah satu block di tengah
    target = salinan[target_id]
    print(f"Target manipulasi: block {target_id} (author={target.author})")

    valid_sebelum, msg_sebelum = is_chain_valid(salinan[urutan[-1]], salinan)
    print("Status SEBELUM manipulasi:", valid_sebelum, "|", msg_sebelum)

    # 1) Ubah isi block target
    target.envelope["ciphertext"] = os.urandom(
        len(bytes.fromhex(target.envelope["ciphertext"]))
    ).hex()

    # 2) Coba tambal parent_hash di SEMUA block sesudahnya secara berantai
    idx = urutan.index(target_id)
    for child_id in urutan[idx + 1:]:
        child = salinan[child_id]
        parent_id = child.parent_id
        child.parent_hash = compute_hash(salinan[parent_id])

    valid_sesudah, msg_sesudah = is_chain_valid(salinan[urutan[-1]], salinan)
    print("Status SESUDAH manipulasi + tambal berantai:", valid_sesudah, "|", msg_sesudah)
    print("\nRincian signature tiap block pasca-tambal:")
    for bid in urutan:
        blk = salinan[bid]
        tertambal = " (ditambal)" if bid in urutan[idx + 1:] else (" (target)" if bid == target_id else "")
        print(f"  Block {bid} ({blk.author}){tertambal}: signature valid? {verify_block_signature(blk)}")

    print("\nKesimpulan: menambal parent_hash TIDAK cukup -- signature setiap")
    print("block yang ditambal ikut rusak karena parent_hash adalah bagian dari")
    print("apa yang ditandatangani, dan peretas tidak memegang private key")
    print("author-author tsb untuk menandatangani ulang.")

# [12] MODE DINAMIS (masukan dosen poin 3)
#
# Tidak ada lagi part_001..004 yang otomatis dieksekusi saat file di-import.
# Block baru masuk lewat add_transaction() (dipanggil dari CLI, dari file
# JSON, atau dari node.py saat menerima transaksi via jaringan).


def new_transaction(part_id, part_name, origin, destination, vehicle_id, status):
    return {
        "part_id": part_id, "part_name": part_name, "origin": origin,
        "destination": destination, "vehicle_id": vehicle_id, "status": status,
    }


def next_block_id(chain_map):
    return max(chain_map.keys(), default=0) + 1


def add_transaction(chain_map, author, part_id, part_name, origin, destination,
                     vehicle_id, status, parent_id=None):
    tx = new_transaction(part_id, part_name, origin, destination, vehicle_id, status)
    next_id = next_block_id(chain_map)
    return add_block_to_chain(chain_map, next_id, author, tx, parent_id=parent_id)


def load_transactions_from_json(chain_map, path):
    """Format file JSON: list of object, tiap object jadi kwargs add_transaction().
    Contoh isi file ada di contoh_transaksi.json."""
    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)
    hasil = []
    for item in items:
        blk, elapsed = add_transaction(chain_map, **item)
        hasil.append((blk, elapsed))
    return hasil


def print_chain(chain_map):
    if not chain_map:
        print("Chain masih kosong.")
        return
    for bid in sorted(chain_map):
        blk = chain_map[bid]
        print(f"\nBlock {blk.id}")
        print("  Author       :", blk.author, f"({ACTOR_ROLES.get(blk.author, '?')})")
        print("  Status       :", blk.status)
        print("  Part ID      :", blk.part_id)
        print("  Difficulty   :", repr(DIFFICULTY), "(awalan hash)")
        print("  Nonce        :", blk.nonce)
        print("  Parent ID    :", blk.parent_id if blk.parent_id is not None else "-")
        print("  Parent hash  :", (blk.parent_hash[:24] + "...") if blk.parent_hash else "-")
        print("  Hash         :", compute_hash(blk)[:24] + "...")
        print("  Signature    :", "VALID" if verify_block_signature(blk) else "INVALID")
        if blk.author in AUTHOR_KEYS:
            try:
                tx = read_block_transaction(blk)
                print("  Part Name    :", tx["part_name"])
                print("  Origin       :", tx["origin"])
                print("  Destination  :", tx["destination"])
                print("  Vehicle ID   :", tx["vehicle_id"])
            except Exception as e:
                print("  (gagal dekripsi isi:", type(e).__name__, ")")
        else:
            print("  (isi terenkripsi -- node ini tidak memegang private key author)")


def pilih_dari_daftar(daftar, label):
    """Tampilkan daftar bernomor dan minta user pilih salah satu lewat angka
    (menghindari salah ketik manual pada field yang nilainya sudah terbatas)."""
    print(f"Pilih {label}:")
    for i, item in enumerate(daftar, start=1):
        print(f"  {i}) {item}")
    while True:
        pilihan = input(f"Nomor {label}: ").strip()
        if pilihan.isdigit() and 1 <= int(pilihan) <= len(daftar):
            return daftar[int(pilihan) - 1]
        print("Nomor tidak valid, coba lagi.")


def run_cli():
    chain_map = {}
    print("=== BLOCKCHAIN TRACEABILITY SUKU CADANG (mode interaktif) ===")
    while True:
        print("\n1) Tambah transaksi baru")
        print("2) Tampilkan riwayat chain")
        print("3) Validasi chain")
        print("4) Muat transaksi dari file JSON")
        print("5) Demo: buktikan manipulasi block tengah tetap terdeteksi")
        print("6) Keluar")
        pilihan = input("Pilih menu: ").strip()

        if pilihan == "1":
            author = pilih_dari_daftar(ACTOR_ORDER, "author")
            part_id = input("Part ID: ").strip()
            part_name = input("Nama part: ").strip()
            origin = input("Origin: ").strip()
            destination = input("Destination: ").strip()
            vehicle_id = input("Vehicle ID: ").strip()
            status = pilih_dari_daftar(list(ALLOWED_TRANSITIONS.keys()), "status")
            parent_raw = input("Parent block id (kosongkan jika block pertama): ").strip()
            parent_id = int(parent_raw) if parent_raw else None
            try:
                blk, elapsed = add_transaction(chain_map, author, part_id, part_name,
                                                origin, destination, vehicle_id, status,
                                                parent_id=parent_id)
                print(f"-> Block {blk.id} ditambang & ditambahkan "
                      f"(nonce={blk.nonce}, extra_nonce={blk.extra_nonce}, "
                      f"difficulty={DIFFICULTY!r}, waktu={elapsed:.3f}s)")
            except (TransactionRejected, ConsensusRejected) as e:
                print("Ditolak:", e)

        elif pilihan == "2":
            print_chain(chain_map)

        elif pilihan == "3":
            if not chain_map:
                print("Chain kosong.")
            else:
                latest_id = max(chain_map)
                valid, msg = is_chain_valid(chain_map[latest_id], chain_map)
                print("Valid?", valid, "|", msg)

        elif pilihan == "4":
            path = input("Path file JSON: ").strip()
            try:
                hasil = load_transactions_from_json(chain_map, path)
                for blk, elapsed in hasil:
                    print(f"-> Block {blk.id} dari file berhasil ditambang ({elapsed:.3f}s)")
            except (OSError, json.JSONDecodeError, TypeError,
                    TransactionRejected, ConsensusRejected) as e:
                print("Gagal memuat:", e)

        elif pilihan == "5":
            if not chain_map:
                print("Chain kosong, tambah transaksi dulu.")
            else:
                demo_cascading_tamper_detection(chain_map, chain_map[max(chain_map)])

        elif pilihan == "6":
            print("Selesai.")
            break
        else:
            print("Pilihan tidak dikenal.")


if __name__ == "__main__":
    run_cli()


# =====================================================================
# [ARSIP] KODE LAMA -- PoW per-bit (integer 256-bit) + retarget
# =====================================================================
# Semua baris di bawah ini adalah KOMENTAR (tidak dijalankan). Ini kode PoW
# asli SEBELUM diganti dengan versi string (DIFFICULTY = "0000") untuk Tugas 6.
# Disimpan utuh supaya bisa ditunjukkan dan diaktifkan kembali.
#
# Cara mengaktifkan kembali: kembalikan semua potongan di bawah ke tempat
# asalnya (bagian [5], [9], [10], [11]), hapus mine_block / mine_with_retry /
# verify_pow versi string, lalu kembalikan juga perubahan di node.py (cari
# komentar "arsip" di sana) dan skrip uji/eksperimen.
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
# --- (2) Block.__init__ (bagian [5]) ---
#     def __init__(self, id, author, transaction, parent_id=None, parent_hash=None,
#                  difficulty_bits=None):
#         ...
#         self.difficulty_bits = DEFAULT_DIFFICULTY_BITS if difficulty_bits is None else difficulty_bits
#
# --- (3) _header_hash (bagian [5]); header memuat difficulty_bits ---
# def _header_hash(content_root: bytes, timestamp: float, nonce: int, extra_nonce: int,
#                   difficulty_bits: int) -> str:
#     """Hash header kecil (content_root + field mining) -- SATU kali SHA-256,
#     tanpa hash sandwich (lihat analisis di bagian [6] di atas kenapa lapisan
#     tambahan itu dihapus). Dipakai bersama oleh compute_hash() (selalu fresh)
#     dan mine_block() (pakai snapshot lokal demi kecepatan) supaya logikanya
#     tidak pernah bercabang/berbeda."""
#     header = (
#         content_root
#         + struct.pack(">d", timestamp)
#         + struct.pack(">Q", nonce)
#         + struct.pack(">I", extra_nonce)
#         + struct.pack(">H", difficulty_bits)
#     )
#     return hashlib.sha256(header).hexdigest()
#
# --- (4) compute_hash, baris terakhir ---
#     return _header_hash(content_root, block.timestamp, block.nonce,
#                          block.extra_nonce, block.difficulty_bits)
#
# --- (5) add_block_to_chain (bagian [10]) ---
# def add_block_to_chain(chain_map, next_id, author, transaction, parent_id=None,
#                         difficulty_bits=None, max_rounds=64):
#     if next_id in chain_map:
#         raise TransactionRejected(f"Block id {next_id} sudah dipakai di chain ini")
#
#     if author not in AUTHORIZED_ACTORS:
#         raise ConsensusRejected(f"Author '{author}' tidak terdaftar sebagai aktor berwenang menulis transaksi")
#
#     parent_block = None
#     if parent_id is not None:
#         if parent_id not in chain_map:
#             raise TransactionRejected(f"Parent block {parent_id} tidak ditemukan di chain")
#         parent_block = chain_map[parent_id]
#
#     valid, message = validate_transaction(transaction, parent_block)
#     if not valid:
#         raise TransactionRejected(f"Block ditolak, tidak dibuat (id={next_id}, author={author}): {message}")
#
#     parent_hash = compute_hash(parent_block) if parent_block is not None else None
#     if difficulty_bits is None:
#         difficulty_bits = compute_next_difficulty(chain_map, parent_block)
#
#     # Kandidat dibentuk di sini -- BELUM ada jejaknya di chain_map.
#     candidate = Block(next_id, author, transaction, parent_id=parent_id,
#                        parent_hash=parent_hash, difficulty_bits=difficulty_bits)
#
#     block_hash, attempts, elapsed = mine_block(candidate, max_rounds=max_rounds)
#     if block_hash is None:
#         raise ConsensusRejected(f"PoW gagal ditemukan untuk block {next_id} setelah {attempts} percobaan")
#
#     candidate.mining_attempts = attempts   # untuk eksperimen difficulty (tidak ikut hash)
#     sign_block(candidate)          # sah ditandatangani hanya setelah PoW final
#     chain_map[next_id] = candidate  # baru DI SINI resmi masuk chain
#     return candidate, elapsed
#
# --- (6) is_chain_valid: pemeriksaan difficulty (bagian [11]) ---
#         # [PERBAIKAN] difficulty_bits yang tercatat di block harus sama dengan
#         # hasil aturan retarget dari parent-nya. Tanpa ini, block dengan
#         # difficulty_bits=0 (PoW trivial) tetap dianggap valid.
#         parent_utk_diff = chain_map.get(cur.parent_id) if cur.parent_id is not None else None
#         if cur.parent_id is not None and parent_utk_diff is None:
#             return False, f"Parent block {cur.parent_id} tidak ditemukan"
#         if cur.difficulty_bits != compute_next_difficulty(chain_map, parent_utk_diff):
#             return False, f"difficulty_bits block {cur.id} tidak sesuai aturan retarget"
# =====================================================================
# [AKHIR ARSIP]
# =====================================================================
