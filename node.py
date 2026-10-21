# -*- coding: utf-8 -*-
"""
node.py -- satu NODE blockchain traceability suku cadang kendaraan (revisi 5).

Tiap laptop/container menjalankan satu node. Node memegang private key sebagian
aktor (--authors), menyimpan rantai LINEAR + transaction pool, dan berbicara
dengan node lain lewat HTTP (JSON).

Alur utama (ketentuan C.2):
  1. Pengirim membuat TRANSAKSI, menandatanganinya dengan private key-nya, lalu
     node memasukkannya ke TRANSACTION POOL dan menyiarkannya ke peer.
  2. Node mana pun dapat MENAMBANG: block dibentuk dari isi pool, dicari nonce-nya
     (PoW, hash diawali DIFFICULTY), lalu block disiarkan ke semua peer.
  3. Tiap node memverifikasi block (hash, previous_hash, Merkle root, PoW, tanda
     tangan tiap transaksi, aturan status) sebelum menerimanya. Setelah block
     diterima rantai, pool dikosongkan dari transaksi yang sudah masuk block.
  4. Jika rantai bercabang, node memakai LONGEST-CHAIN RULE: rantai sah yang lebih
     panjang menang; transaksi dari block yang terbuang kembali ke pool.

Endpoint HTTP (body dan balasan JSON; "type" tetap ada di balasan):
  GET  /chain                 rantai lengkap (termasuk genesis)
  POST /chain                 {"blocks":[...]}  usulkan rantai (diterima bila sah dan lebih panjang)
  POST /blocks                {"block":{...}}   terima satu block baru
  GET  /transactions          isi transaction pool
  POST /transactions          {"transaction":{...}, "relay":true}  masukkan transaksi bertanda tangan
  POST /transactions/create   {"sender","part_id","part_name","origin","destination","vehicle_id","status"}
                              node menandatangani dengan key aktor lokal (kemudahan lab/demo)
  POST /mine                  {"max_tx":5}  tambang satu block dari pool lalu siarkan
  GET  /keys, POST /keys      tukar public key aktor
  GET  /peers, POST /peers    daftar peer; POST {"peer":"host:port"} (Tugas 4)
  POST /nodes/resolve         sinkron dua arah dengan semua peer + longest-chain rule (Tugas 5)
  GET  /status                ringkasan node

Kode status: 200/201 sukses (201 = sesuatu dibuat), 400 permintaan cacat, 404 path
tidak dikenal, 405 metode salah, 409 ditolak (transaksi/block tidak sah, key bentrok),
411/413 ukuran body, 500 galat internal.

Log console: setiap langkah tercetak dengan tag [NODE] [TX] [POOL] [MINING]
[BROADCAST] [BLOCK] [SYNC] [FORK] [CHAIN] [KEY] [MANIPULASI].

Keterbatasan (jujur):
  - Siaran block/transaksi dilakukan LANGSUNG oleh pembuatnya ke semua peer; tiap
    node harus mengetahui alamat semua node lain (full mesh), tidak ada gossip.
  - Endpoint tanpa autentikasi dan tanpa TLS (cukup untuk jaringan lab tertutup).
  - Longest-chain memakai jumlah block; panjang sama = SERI (rantai lokal dipertahankan
    sampai ada block berikutnya).
  - Model kepercayaan public key: first-come (key yang sudah terdaftar tidak bisa ditimpa).
  - File private key tidak dienkripsi; lindungi folder data.
"""

import argparse
import copy
import http.client
import json
import os
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from blockchain_core_traceability_suku_cadang_kendaraan import (
    ALLOWED_TRANSITIONS,
    AUTHOR_KEYS,
    AUTHORIZED_ACTORS,
    DIFFICULTY,
    MAX_TX_PER_BLOCK,
    PUBLIC_KEY_REGISTRY,
    ConsensusRejected,
    Ledger,
    PoolEmpty,
    block_to_dict,
    demo_manipulasi,
    get_or_create_author,
    make_transaction,
    pilih_dari_daftar,
    print_chain,
    public_key_from_pem,
    public_key_to_pem,
    register_public_key,
)

KEY_LOCK = threading.Lock()
PEER_LOCK = threading.Lock()      # list `peers` bisa diubah thread menu dan thread server sekaligus

MAX_MSG_BYTES = 10 * 1024 * 1024   # batas ukuran satu pesan HTTP
FIELD_TEKS_MAX = 200               # batas panjang field teks pada /transactions/create


# ---------- public key aktor ----------

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


# ---------- penyimpanan (chain + pool) ----------

def simpan_state(ledger, path):
    """Simpan rantai, pool, dan public key ke JSON secara ATOMIK (tulis file
    sementara lalu os.replace) supaya file tidak rusak bila proses mati di tengah."""
    with ledger.lock:
        data = {"version": 2, "chain": ledger.chain_dicts(), "pool": ledger.pool_snapshot()}
    data["public_keys"] = semua_key_publik()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def muat_state(ledger, path):
    """Muat rantai dan pool dari disk (rantai divalidasi ulang penuh). File yang
    rusak, dimanipulasi, atau berformat lama TIDAK dipakai; node mulai dari genesis."""
    if not os.path.exists(path):
        print(f"[NODE] Belum ada {path}: mulai dari block genesis")
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"[NODE] {path} tidak bisa dibaca ({e}); mulai dari genesis")
        return
    if not isinstance(data, dict) or data.get("version") != 2:
        cadangan = path + ".format-lama.bak"
        try:
            os.replace(path, cadangan)
        except OSError:
            cadangan = "(gagal dicadangkan)"
        print(f"[NODE] {path} berformat lama -> dicadangkan ke {cadangan}; mulai dari genesis")
        return
    for author, pem in (data.get("public_keys") or {}).items():
        daftarkan_key(author, pem)
    ok, pesan = ledger.load_state(data.get("chain", []), data.get("pool", []))
    if ok:
        print(f"[NODE] Dimuat dari {path}: {pesan}")
    else:
        print(f"[NODE] {path} DITOLAK saat validasi ({pesan}); mulai dari genesis")


def autosave(ledger, path, interval=2.0):
    """Thread latar: simpan state tiap `interval` detik jika berubah."""
    terakhir = None
    while True:
        time.sleep(interval)
        with ledger.lock:
            snap = json.dumps({"c": ledger.chain_dicts(), "p": ledger.pool_snapshot()}, sort_keys=True)
        if snap != terakhir:
            try:
                simpan_state(ledger, path)
                terakhir = snap
            except OSError as e:
                print(f"[NODE] Autosave gagal: {e}")


# ---------- transport HTTP ----------

# Satu tabel rute dipakai server DAN client: tipe pesan -> (metode HTTP, path).
RUTE_HTTP = {
    "GET_CHAIN":       ("GET",  "/chain"),
    "PUSH_CHAIN":      ("POST", "/chain"),
    "NEW_BLOCK":       ("POST", "/blocks"),
    "GET_POOL":        ("GET",  "/transactions"),
    "ADD_TX":          ("POST", "/transactions"),
    "CREATE_TX":       ("POST", "/transactions/create"),
    "MINE":            ("POST", "/mine"),
    "GET_KEYS":        ("GET",  "/keys"),
    "REGISTER_AUTHOR": ("POST", "/keys"),
    "ADD_PEER":        ("POST", "/peers"),            # Tugas 4
    "GET_PEERS":       ("GET",  "/peers"),
    "RESOLVE":         ("POST", "/nodes/resolve"),    # Tugas 5
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
        return 400 if path == "/peers" else 409     # format peer salah = 400; transaksi/block ditolak = 409
    if tipe == "ERROR":
        return 400
    if reply.get("created") is True:
        return 201                                   # sesuatu dibuat (peer, transaksi, block)
    return 200


class NodeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"   # satu permintaan per koneksi (tanpa keep-alive)
    server_version = "TraceNode/2.0"
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
            reply = handle_message(msg, self.server.ledger, self.server.peers,
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

    def __init__(self, alamat, ledger, peers=None, owned_authors=None):
        self.ledger = ledger
        self.peers = peers
        self.owned_authors = list(owned_authors or [])
        super().__init__(alamat, NodeHandler)

    def server_bind(self):
        # HTTPServer.server_bind memanggil getfqdn() yang bisa lambat (DNS); tidak dibutuhkan.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def buat_server(host: str, port: int, ledger, peers=None, owned_authors=None):
    srv = NodeHTTPServer((host, port), ledger, peers, owned_authors)
    print(f"[NODE] Mendengarkan HTTP di http://{host}:{port}")
    return srv


def terima_koneksi(srv):
    srv.serve_forever(poll_interval=0.2)


def start_server(host: str, port: int, ledger, peers=None, owned_authors=None):
    terima_koneksi(buat_server(host, port, ledger, peers, owned_authors))


def send_message(host: str, port: int, msg: dict, timeout=5) -> dict:
    """Kirim satu pesan ke peer lewat HTTP dan kembalikan balasannya (dict).
    Tipe pesan diterjemahkan ke (metode, path) lewat RUTE_HTTP. Kegagalan
    jaringan/protokol dilaporkan sebagai OSError."""
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


# ---------- daftar peer ----------

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


def kelola_peer(peers, ledger, owned_authors):
    """Tambah/hapus peer saat node berjalan. Menghapus peer = memutus
    hubungan keluar (berguna untuk membuat fork saat eksperimen)."""
    print("Peer saat ini:")
    for i, (h, p) in enumerate(list(peers), 1):
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
        with PEER_LOCK:
            if peer in peers:
                print("Peer sudah ada.")
                return
            peers.append(peer)
        sinkron_peer(peer[0], peer[1], ledger, owned_authors)
    elif aksi == "h":
        if not peers:
            return
        n = input("Nomor peer yang dihapus: ").strip()
        with PEER_LOCK:
            if n.isdigit() and 1 <= int(n) <= len(peers):
                h, p = peers.pop(int(n) - 1)
                print(f"Peer {h}:{p} dihapus (tidak lagi dihubungi node ini).")
            else:
                print("Nomor tidak valid.")


# ---------- operasi jaringan: key, siaran, sinkronisasi ----------

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


def _daftar_peer(peers):
    with PEER_LOCK:
        return list(peers or [])


def broadcast_transaction(tx, peers, ledger, owned_authors):
    """Siarkan transaksi bertanda tangan ke SEMUA peer (relay=False: penerima tidak
    perlu meneruskan lagi). Peer yang belum mengenal key pengirim memicu sinkron."""
    for h, p in _daftar_peer(peers):
        try:
            r = send_message(h, p, {"type": "ADD_TX", "transaction": tx, "relay": False})
        except OSError as e:
            print(f"[BROADCAST] transaksi {tx['tx_id'][:12]} -> {h}:{p} GAGAL ({e})")
            continue
        if r.get("type") == "OK":
            ket = "baru" if r.get("created") else "sudah ada"
            print(f"[BROADCAST] transaksi {tx['tx_id'][:12]} -> {h}:{p}: OK ({ket})")
        elif r.get("perlu_sinkron"):
            print(f"[BROADCAST] transaksi {tx['tx_id'][:12]} -> {h}:{p}: peer belum mengenal key -> sinkron")
            sinkron_peer(h, p, ledger, owned_authors)
        else:
            print(f"[BROADCAST] transaksi {tx['tx_id'][:12]} -> {h}:{p}: DITOLAK ({r.get('reason')})")


def broadcast_block(blk_dict, ledger, peers, owned_authors):
    """Siarkan block baru ke SEMUA peer. Bila peer menjawab 'perlu sinkron'
    (block tidak menyambung / fork / key belum dikenal), jalankan sinkron dua arah."""
    for h, p in _daftar_peer(peers):
        try:
            r = send_message(h, p, {"type": "NEW_BLOCK", "block": blk_dict})
        except OSError as e:
            print(f"[BROADCAST] block #{blk_dict['index']} -> {h}:{p} GAGAL ({e})")
            continue
        if r.get("type") == "OK":
            print(f"[BROADCAST] block #{blk_dict['index']} -> {h}:{p}: DITERIMA ({r.get('status')})")
        elif r.get("perlu_sinkron"):
            print(f"[BROADCAST] block #{blk_dict['index']} -> {h}:{p}: peer tertinggal/bercabang -> sinkron")
            sinkron_peer(h, p, ledger, owned_authors)
        else:
            print(f"[BROADCAST] block #{blk_dict['index']} -> {h}:{p}: DITOLAK ({r.get('reason')})")


def sinkron_peer(host, port, ledger, owned_authors) -> bool:
    """Sinkron DUA ARAH dengan satu peer: tukar public key, tarik rantai peer
    (longest-chain rule), dorong rantai kita, lalu tukar isi pool.
    Return True bila peer terjangkau."""
    try:
        kirim_keys_ke_peer(host, port, owned_authors)
        tarik_keys(host, port)

        r = send_message(host, port, {"type": "GET_CHAIN"})
        if r.get("type") == "CHAIN" and isinstance(r.get("blocks"), list):
            hasil = ledger.consider_chain(r["blocks"])
            print(f"[SYNC] rantai {host}:{port}: {hasil['status']}"
                  + (f" ({hasil['alasan']})" if hasil.get("alasan") else ""))
        else:
            print(f"[SYNC] {host}:{port} tidak memberi rantai yang valid: {r.get('reason')}")

        r2 = send_message(host, port, {"type": "PUSH_CHAIN", "blocks": ledger.chain_dicts()}, timeout=10)
        print(f"[SYNC] rantai kita ke {host}:{port}: {r2.get('status', r2.get('reason'))}")

        rp = send_message(host, port, {"type": "GET_POOL"})
        if rp.get("type") == "POOL" and isinstance(rp.get("transactions"), list):
            for t in rp["transactions"]:
                ledger.add_to_pool(t)
        for t in ledger.pool_snapshot():
            send_message(host, port, {"type": "ADD_TX", "transaction": t, "relay": False})
        return True
    except OSError as e:
        print(f"[SYNC] Gagal menghubungi {host}:{port}: {e}")
        return False


def mine_and_broadcast(ledger, peers, owned_authors, max_tx=MAX_TX_PER_BLOCK):
    """Tambang satu block dari pool lalu siarkan. Return (block, percobaan, detik)."""
    blk, percobaan, detik = ledger.mine_pending(max_tx)
    broadcast_block(block_to_dict(blk), ledger, peers, owned_authors)
    return blk, percobaan, detik


# ---------- logika pesan (bebas transport) ----------

def _str_field(msg, nama):
    v = msg.get(nama)
    if not isinstance(v, str) or not (1 <= len(v) <= FIELD_TEKS_MAX):
        raise ValueError(f"field '{nama}' harus string 1..{FIELD_TEKS_MAX} karakter")
    return v


def handle_message(msg: dict, ledger, peers=None, owned_authors=None) -> dict:
    """Logika satu pesan: dict masuk, dict balasan. Tidak tahu apa pun soal HTTP;
    (metode, path) dipetakan ke tipe pesan oleh NodeHandler."""
    mtype = msg.get("type")
    owned_authors = owned_authors or []

    if mtype == "GET_CHAIN":
        return {"type": "CHAIN", "blocks": ledger.chain_dicts()}

    if mtype == "PUSH_CHAIN":
        hasil = ledger.consider_chain(msg.get("blocks"))
        if hasil["status"] == "REJECT":
            return {"type": "REJECT", "reason": hasil.get("alasan", "rantai ditolak"), "status": "REJECT"}
        return {"type": "OK", "status": hasil["status"], "panjang": hasil.get("panjang")}

    if mtype == "NEW_BLOCK":
        status, alasan = ledger.receive_block(msg.get("block"))
        if status in ("ADDED", "DUPLICATE"):
            return {"type": "OK", "status": status}
        if status == "FORK" or "belum dikenal" in alasan:
            return {"type": "REJECT", "reason": alasan, "perlu_sinkron": True}
        return {"type": "REJECT", "reason": alasan}

    if mtype == "GET_POOL":
        return {"type": "POOL", "transactions": ledger.pool_snapshot()}

    if mtype == "ADD_TX":
        tx = msg.get("transaction")
        status, alasan = ledger.add_to_pool(tx)
        if status == "NEW":
            if msg.get("relay", True) and peers is not None:
                broadcast_transaction(tx, peers, ledger, owned_authors)
            return {"type": "OK", "created": True, "tx_id": tx["tx_id"]}
        if status == "DUPLICATE":
            return {"type": "OK", "note": "transaksi sudah ada", "tx_id": tx.get("tx_id")}
        reply = {"type": "REJECT", "reason": alasan}
        if "belum dikenal" in alasan:
            reply["perlu_sinkron"] = True
        return reply

    if mtype == "CREATE_TX":
        try:
            sender = _str_field(msg, "sender")
            isi = {k: _str_field(msg, k) for k in ("part_id", "part_name", "origin", "destination",
                                                    "vehicle_id", "status")}
        except ValueError as e:
            return {"type": "REJECT", "reason": str(e)}
        if isi["status"] not in ALLOWED_TRANSITIONS:
            return {"type": "REJECT", "reason": f"status tidak dikenal: {isi['status']!r}"}
        if sender not in owned_authors:
            return {"type": "REJECT", "reason": f"node ini tidak memegang private key '{sender}'"}
        tx = make_transaction(sender, isi["part_id"], isi["part_name"], isi["origin"],
                              isi["destination"], isi["vehicle_id"], isi["status"])
        status, alasan = ledger.add_to_pool(tx)
        if status != "NEW":
            return {"type": "REJECT", "reason": alasan}
        if peers is not None:
            broadcast_transaction(tx, peers, ledger, owned_authors)
        return {"type": "OK", "created": True, "tx_id": tx["tx_id"]}

    if mtype == "MINE":
        max_tx = msg.get("max_tx", MAX_TX_PER_BLOCK)
        if not isinstance(max_tx, int) or isinstance(max_tx, bool) or not (1 <= max_tx <= 500):
            return {"type": "REJECT", "reason": "max_tx harus bilangan bulat 1..500"}
        try:
            blk, percobaan, detik = mine_and_broadcast(ledger, peers, owned_authors, max_tx)
        except (PoolEmpty, ConsensusRejected) as e:
            return {"type": "REJECT", "reason": str(e)}
        return {"type": "OK", "created": True, "block": block_to_dict(blk),
                "percobaan": percobaan, "detik": round(detik, 3)}

    if mtype == "REGISTER_AUTHOR":
        ok, alasan = daftarkan_key(msg.get("author"), msg.get("public_key_pem"))
        if ok:
            print(f"[KEY] public key '{msg.get('author')}' dari peer: {alasan}")
            return {"type": "OK"}
        return {"type": "REJECT", "reason": alasan}

    if mtype == "GET_KEYS":
        return {"type": "KEYS", "keys": semua_key_publik()}

    if mtype == "ADD_PEER":
        if peers is None:
            return {"type": "REJECT", "reason": "node ini tidak mendukung penambahan peer dinamis"}
        try:
            peer = parse_satu_peer(str(msg.get("peer", "")))
        except ValueError as e:
            return {"type": "REJECT", "reason": str(e)}
        with PEER_LOCK:
            if peer in peers:
                return {"type": "OK", "note": "peer sudah ada"}
            peers.append(peer)
            daftar = [f"{h}:{p}" for h, p in peers]
        print(f"[NODE] Peer ditambahkan lewat POST /peers: {peer[0]}:{peer[1]}")
        return {"type": "OK", "created": True, "peers": daftar}

    if mtype == "GET_PEERS":
        if peers is None:
            return {"type": "REJECT", "reason": "node ini tidak mendukung daftar peer"}
        return {"type": "PEERS", "peers": [f"{h}:{p}" for h, p in _daftar_peer(peers)]}

    if mtype == "RESOLVE":
        if peers is None:
            return {"type": "REJECT", "reason": "node ini tidak mendukung RESOLVE"}
        fork_sebelum = len(ledger.fork_history)
        hasil = [{"peer": f"{h}:{p}", "terjangkau": sinkron_peer(h, p, ledger, owned_authors)}
                 for h, p in _daftar_peer(peers)]
        return {"type": "OK", "hasil": hasil, "jumlah_block": ledger.panjang(),
                "fork_ditangani": len(ledger.fork_history) - fork_sebelum}

    if mtype == "GET_STATUS":
        ok, _ = ledger.validate()
        return {"type": "STATUS", "aktor_lokal": list(owned_authors), "jumlah_block": ledger.panjang(),
                "ujung_hash": ledger.tip().hash, "pool": len(ledger.pool_snapshot()),
                "peers": [f"{h}:{p}" for h, p in _daftar_peer(peers)], "difficulty": DIFFICULTY,
                "chain_valid": ok}

    return {"type": "ERROR", "reason": f"tipe pesan tidak dikenal: {mtype}"}


# ---------- tampilan menu ----------

def tampilkan_pool(ledger):
    pool = ledger.pool_snapshot()
    print(f"\n=== TRANSACTION POOL ({len(pool)} transaksi pending) ===")
    for i, t in enumerate(pool, 1):
        print(f"  {i}) {t['tx_id'][:12]}  {t['sender']:<11} {t['part_id']:<10} {t['status']}")
    if not pool:
        print("  (kosong)")


def tampilkan_fork(ledger):
    print("\n=== RIWAYAT FORK ===")
    if not ledger.fork_history:
        print("  (belum ada fork)")
    for c in ledger.fork_history:
        ledger.cetak_fork(c)


def buat_transaksi_menu(ledger, peers, owned_authors):
    if not owned_authors:
        print("Node ini tidak memegang aktor (jalankan dengan --authors) -> tidak bisa membuat transaksi.")
        return
    sender = pilih_dari_daftar(owned_authors, "pengirim")
    part_id = input("part_id: ").strip()
    part_name = input("part_name: ").strip()
    origin = input("origin: ").strip()
    dest = input("destination: ").strip()
    veh = input("vehicle_id: ").strip()
    status = pilih_dari_daftar(list(ALLOWED_TRANSITIONS), "status")
    if not all([part_id, part_name, origin, dest, veh]):
        print("Semua field wajib diisi.")
        return
    tx = make_transaction(sender, part_id, part_name, origin, dest, veh, status)
    hasil, alasan = ledger.add_to_pool(tx)
    if hasil == "NEW":
        broadcast_transaction(tx, peers, ledger, owned_authors)
    else:
        print(f"Transaksi tidak masuk pool: {alasan}")


# ---------- menjalankan node ----------

def run_node(host, port, owned_authors, peers, data_dir):
    ledger = Ledger()

    for author in owned_authors:
        load_or_create_keys(author, data_dir)

    state_file = os.path.join(data_dir, "chain.json")    # di Docker: ikut volume ./data/nodeX
    muat_state(ledger, state_file)
    threading.Thread(target=autosave, args=(ledger, state_file), daemon=True).start()

    srv = buat_server(host, port, ledger, peers, owned_authors)
    threading.Thread(target=terima_koneksi, args=(srv,), daemon=True).start()

    for h, p in _daftar_peer(peers):
        sinkron_peer(h, p, ledger, owned_authors)

    print(f"\n=== NODE aktif di {host}:{port} | aktor lokal: {owned_authors or '(tidak ada)'} "
          f"| difficulty {DIFFICULTY!r} ===")
    try:
        while True:
            print("\n1) Buat transaksi baru (ditandatangani -> pool -> disiarkan)")
            print("2) Lihat transaction pool")
            print("3) Tambang block dari pool (lalu siarkan)")
            print("4) Tampilkan chain")
            print("5) Validasi chain")
            print("6) Sinkron + resolve fork (longest-chain) dengan semua peer")
            print("7) Kelola peer (tambah/hapus)")
            print("8) Riwayat fork")
            print("9) Demo deteksi manipulasi data (pada salinan)")
            print("0) Keluar")
            pilihan = input("Pilih menu: ").strip()

            if pilihan == "1":
                buat_transaksi_menu(ledger, peers, owned_authors)
            elif pilihan == "2":
                tampilkan_pool(ledger)
            elif pilihan == "3":
                try:
                    mine_and_broadcast(ledger, peers, owned_authors)
                except (PoolEmpty, ConsensusRejected) as e:
                    print(f"[MINING] Gagal: {e}")
            elif pilihan == "4":
                with ledger.lock:
                    salinan = copy.deepcopy(ledger.chain)
                print_chain(salinan)
            elif pilihan == "5":
                ok, pesan = ledger.validate()
                print(f"[CHAIN] {'VALID' if ok else 'TIDAK VALID'}: {pesan}")
            elif pilihan == "6":
                if not peers:
                    print("[SYNC] Belum ada peer.")
                for h, p in _daftar_peer(peers):
                    sinkron_peer(h, p, ledger, owned_authors)
                print(f"[SYNC] selesai. Panjang rantai lokal: {ledger.panjang()} block")
            elif pilihan == "7":
                kelola_peer(peers, ledger, owned_authors)
            elif pilihan == "8":
                tampilkan_fork(ledger)
            elif pilihan == "9":
                with ledger.lock:
                    salinan = copy.deepcopy(ledger.chain)
                print("[MANIPULASI] Memanipulasi SALINAN rantai (rantai asli tidak berubah):")
                for judul, terdeteksi, alasan in demo_manipulasi(salinan):
                    print(f"  {'[TERDETEKSI]' if terdeteksi else '[LOLOS!]    '} {judul}\n        -> {alasan}")
            elif pilihan == "0":
                break
            else:
                print("Pilihan tidak dikenal.")
    except (EOFError, KeyboardInterrupt):
        print("\n[NODE] Menutup node...")
    finally:
        try:
            simpan_state(ledger, state_file)
            print(f"[NODE] State disimpan ke {state_file}")
        except OSError as e:
            print(f"[NODE] Gagal menyimpan state: {e}")


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
