# -*- coding: utf-8 -*-
"""Uji TIGA node saling terhubung (ketentuan C.2: jaringan multi-node).

Jalankan: python uji_3node.py        (memakai port 9131, 9132, 9133)

Memeriksa: transaksi bertanda tangan disiarkan ke seluruh node dan masuk pool
masing-masing; transaksi tidak sah ditolak; block yang ditambang satu node
disiarkan dan diterima dua node lain; pool dikosongkan setelah block diterima;
block tidak sah ditolak; ketiga rantai identik dan valid; log console lengkap.
"""
import copy
import json
import sys
import time

import uji_util as u
from uji_util import Node, cek, http_req

P = {"A": 9131, "B": 9132, "C": 9133}


def alamat(*nama):
    return [f"127.0.0.1:{P[n]}" for n in nama]


def tunggu_sama(nodes, kunci, nilai, detik=8.0):
    batas = time.time() + detik
    while time.time() < batas:
        if all(n.status()[kunci] == nilai for n in nodes):
            return True
        time.sleep(0.2)
    return False


A = Node("A", P["A"], ["Produsen"], alamat("B", "C"))
B = Node("B", P["B"], ["Distributor"], alamat("A", "C"))
C = Node("C", P["C"], ["Dealer"], alamat("A", "B"))
semua = [A, B, C]
try:
    print("== 1. Tiga node dijalankan bertahap (tiap node saling mengenal) ==")
    A.start(); B.start(); C.start()
    time.sleep(1.5)
    cek("ketiga node hidup dengan genesis yang sama",
        len({n.status()["ujung_hash"] for n in semua}) == 1 and all(n.status()["jumlah_block"] == 0 for n in semua))
    cek("tiap node punya 2 peer", all(len(n.status()["peers"]) == 2 for n in semua))

    print("== 2. Transaksi bertanda tangan: dibuat di A, disiarkan ke B dan C ==")
    st, r = A.buat_tx("Produsen", "SP-1", "PRODUCED")
    cek("A membuat transaksi PRODUCED -> 201", st == 201 and r.get("created"), f"{st} {r}")
    cek("transaksi masuk pool di A, B, dan C", tunggu_sama(semua, "pool", 1))
    tx = B.req("GET", "/transactions")[1]["transactions"][0]
    cek("transaksi di B memuat tanda tangan dan tx_id", tx["signature"] and tx["tx_id"] and tx["sender"] == "Produsen")

    print("== 3. Transaksi tidak sah ditolak sebelum masuk pool ==")
    rusak = copy.deepcopy(tx); rusak["part_id"] = "SP-HACK"
    st, r = B.req("POST", "/transactions", {"transaction": rusak})
    cek("isi transaksi diubah -> 409", st == 409 and "manipulasi" in r.get("reason", ""), r.get("reason"))
    palsu = copy.deepcopy(tx); palsu["signature"] = "ab" * 64
    st, r = B.req("POST", "/transactions", {"transaction": palsu})
    cek("tanda tangan dipalsukan -> 409", st == 409, r.get("reason"))
    st, r = C.buat_tx("Dealer", "SP-9", "SHIPPED")
    cek("urutan status salah (SHIPPED tanpa PRODUCED) -> 409", st == 409, r.get("reason"))
    st, r = C.buat_tx("Produsen", "SP-9", "PRODUCED")
    cek("node C tidak memegang key Produsen -> 409", st == 409, r.get("reason"))
    st, r = A.buat_tx("Produsen", "SP-1", "PRODUCED")
    cek("PRODUCED kedua untuk part yang sama -> 409", st == 409, r.get("reason"))

    print("== 4. B menambang block dari pool; A dan C menerima lewat broadcast ==")
    st, r = B.tambang()
    cek("B menambang block 1 -> 201", st == 201 and r["block"]["index"] == 1, f"{st}")
    blk = r["block"]
    cek("block memuat daftar transaksi, previous_hash, nonce, hash",
        len(blk["transactions"]) == 1 and blk["previous_hash"] and isinstance(blk["nonce"], int) and blk["hash"].startswith("0000"))
    cek("A, B, C punya 1 block", tunggu_sama(semua, "jumlah_block", 1))
    cek("pool dikosongkan di ketiga node setelah block diterima rantai", tunggu_sama(semua, "pool", 0))
    cek("ketiga node punya ujung rantai yang sama", len({n.status()["ujung_hash"] for n in semua}) == 1)

    print("== 5. Dua transaksi dari dua node -> satu block berisi dua transaksi ==")
    st1, _ = B.buat_tx("Distributor", "SP-1", "SHIPPED")
    st2, _ = C.buat_tx("Dealer", "SP-1", "RECEIVED")
    cek("SHIPPED (B) dan RECEIVED (C) diterima", st1 == 201 and st2 == 201)
    cek("kedua transaksi ada di pool ketiga node", tunggu_sama(semua, "pool", 2))
    st, r = C.tambang()
    cek("C menambang block 2 berisi 2 transaksi", st == 201 and len(r["block"]["transactions"]) == 2, f"{st}")
    cek("A, B, C punya 2 block dan pool kosong",
        tunggu_sama(semua, "jumlah_block", 2) and tunggu_sama(semua, "pool", 0))

    print("== 6. Block tidak sah ditolak ==")
    rantai = A.req("GET", "/chain")[1]["blocks"]
    b2 = copy.deepcopy(rantai[2])
    b2["transactions"][0]["status"] = "INSTALLED"
    st, r = B.req("POST", "/blocks", {"block": b2})
    cek("block dengan isi dimanipulasi -> 409", st == 409, r.get("reason"))
    b2 = copy.deepcopy(rantai[2]); b2["hash"] = "f" * 64
    st, r = C.req("POST", "/blocks", {"block": b2})
    cek("block dengan hash palsu -> 409", st == 409, r.get("reason"))
    b3 = copy.deepcopy(rantai[2]); b3["index"] = 3; b3["previous_hash"] = rantai[2]["hash"]
    st, r = A.req("POST", "/blocks", {"block": b3})
    cek("block tanpa PoW yang benar -> 409", st == 409, r.get("reason"))
    cek("rantai tidak berubah setelah serangan", all(n.status()["jumlah_block"] == 2 for n in semua))

    print("== 7. Validasi seluruh rantai di tiap node ==")
    cek("chain_valid = True di A, B, C", all(n.status()["chain_valid"] for n in semua))
    cek("isi rantai identik di tiga node (index, previous_hash, nonce, hash)",
        len({json.dumps([(b["index"], b["previous_hash"], b["nonce"], b["hash"]) for b in n.req("GET", "/chain")[1]["blocks"]])
             for n in semua}) == 1)
    A.menu("5", tunggu=1.0)
    cek("menu 5 (validasi chain) mencetak hasil di console", "[CHAIN] VALID" in A.log())

    print("== 8. Log console memuat setiap langkah ==")
    for tag, node in [("[TX] DITERIMA", B), ("[POOL]", B), ("[MINING] mulai", B), ("[MINING] SELESAI", B),
                      ("[BROADCAST] block #1", B), ("[BLOCK] DITERIMA block #1", A),
                      ("[BLOCK] DITERIMA block #2", A), ("[TX] DITOLAK", B), ("[BLOCK] DITOLAK", B),
                      ("pool", C)]:
        cek(f"log node {node.nama} memuat '{tag}'", tag in node.log() or tag.lower() in node.log().lower())
finally:
    for n in semua:
        n.stop()
sys.exit(u.ringkasan())
