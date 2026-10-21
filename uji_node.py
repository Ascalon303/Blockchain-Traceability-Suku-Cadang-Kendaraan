# -*- coding: utf-8 -*-
"""Uji dua node: serangan, penyimpanan chain.json, dan kode status HTTP.

Jalankan: python uji_node.py        (memakai port 9101 dan 9102)
"""
import copy
import json
import os
import sys
import time

import blockchain_core_traceability_suku_cadang_kendaraan as core
import uji_util as u
from uji_util import Node, cek, http_req

PA, PB = 9101, 9102
A = Node("A", PA, ["Produsen"], [f"127.0.0.1:{PB}"])
B = Node("B", PB, ["Distributor"], [f"127.0.0.1:{PA}"])
try:
    print("== 1. Dua node, transaksi dan block tersiar ==")
    A.start(); B.start()
    time.sleep(1.0)
    st, r = A.buat_tx("Produsen", "SP-1", "PRODUCED")
    cek("A membuat transaksi (ditandatangani) -> 201", st == 201, str(r))
    cek("B menerima transaksi di pool-nya", B.status()["pool"] == 1)
    st, r = B.tambang()
    cek("B menambang block 1", st == 201 and r["block"]["index"] == 1)
    cek("A menerima block 1 dan pool-nya kosong", A.status()["jumlah_block"] == 1 and A.status()["pool"] == 0)
    st, r = B.buat_tx("Distributor", "SP-1", "SHIPPED")
    cek("B membuat transaksi SHIPPED, A menerimanya", st == 201 and A.status()["pool"] == 1)

    print("== 2. Serangan terhadap transaksi ==")
    tx = B.req("GET", "/transactions")[1]["transactions"][0]
    rusak = copy.deepcopy(tx); rusak["status"] = "RECEIVED"
    st, r = A.req("POST", "/transactions", {"transaction": rusak})
    cek("isi transaksi diubah (tx_id sama) -> 409", st == 409, r.get("reason"))
    # transaksi bertanda tangan KEY LAIN tetapi mengaku sebagai Produsen
    kunci_asli = core.AUTHOR_KEYS.get("Produsen")
    core.AUTHOR_KEYS["Produsen"] = core.generate_keypair()
    try:
        palsu = core.make_transaction("Produsen", "SP-77", "x", "x", "x", "x", "PRODUCED")
    finally:
        if kunci_asli: core.AUTHOR_KEYS["Produsen"] = kunci_asli
        else: del core.AUTHOR_KEYS["Produsen"]
    st, r = A.req("POST", "/transactions", {"transaction": palsu})
    cek("transaksi bertanda tangan key lain -> 409", st == 409 and "tanda tangan" in r.get("reason", ""), r.get("reason"))
    palsu2 = copy.deepcopy(palsu); palsu2["sender"] = "Penyusup"
    st, r = A.req("POST", "/transactions", {"transaction": palsu2})
    cek("pengirim bukan aktor berwenang -> 409", st == 409, r.get("reason"))
    st, r = A.req("POST", "/transactions", {"transaction": {"sender": "Produsen"}})
    cek("transaksi dengan field tidak lengkap -> 409", st == 409, r.get("reason"))

    print("== 3. Serangan terhadap block, key, dan kunci jaringan ==")
    st, r = B.tambang()
    cek("B menambang block 2", st == 201)
    rantai = A.req("GET", "/chain")[1]["blocks"]
    b = copy.deepcopy(rantai[2]); b["transactions"][0]["status"] = "INSTALLED"
    st, r = A.req("POST", "/blocks", {"block": b})
    cek("block diubah isinya (hash klaim lama) -> 409", st == 409, r.get("reason"))
    b = copy.deepcopy(rantai[2]); b["nonce"] += 1
    st, r = A.req("POST", "/blocks", {"block": b})
    cek("nonce diubah (PoW/hash tidak cocok) -> 409", st == 409, r.get("reason"))
    b = copy.deepcopy(rantai[2]); del b["previous_hash"]
    st, r = A.req("POST", "/blocks", {"block": b})
    cek("block berformat cacat -> 409", st == 409, r.get("reason"))
    _, pem_baru = None, core.public_key_to_pem(core.generate_keypair()[1])
    st, r = A.req("POST", "/keys", {"author": "Produsen", "public_key_pem": pem_baru})
    cek("key aktor yang sudah terdaftar tidak bisa ditimpa -> 409", st == 409, r.get("reason"))
    cek("rantai A tetap 2 block dan valid setelah semua serangan",
        A.status()["jumlah_block"] == 2 and A.status()["chain_valid"])

    print("== 4. Kode status HTTP ==")
    def req(m, p, obj=None, **kw): return http_req(PB, m, p, obj, **kw)
    st, j = req("POST", "/blocks", mentah=b"[1,2,3]")
    cek("body JSON bukan objek -> 400", st == 400 and j.get("type") == "ERROR", st)
    st, j = req("POST", "/blocks", mentah=b"bukan json")
    cek("body bukan JSON -> 400", st == 400, st)
    st, j = req("GET", "/tidak-ada")
    cek("path tidak dikenal -> 404", st == 404, st)
    st, j = req("DELETE", "/chain")
    cek("metode salah -> 405", st == 405, st)
    st, j = req("POST", "/blocks", header={"Content-Length": "99999999999"})
    cek("body terlalu besar -> 413", st == 413, st)
    st, j = req("POST", "/peers", {"peer": "format-salah"})
    cek("POST /peers format salah -> 400", st == 400, st)
    st, j = req("POST", "/mine", {"max_tx": 0})
    cek("POST /mine dengan max_tx tidak valid -> 409", st == 409, st)
    st, j = req("GET", "/status")
    cek("GET /status -> 200 dengan ringkasan node",
        st == 200 and j["type"] == "STATUS" and j["difficulty"] == core.DIFFICULTY and j["chain_valid"] is True)
    st, j = req("POST", "/mine", {})
    cek("POST /mine saat pool kosong -> 409", st == 409 and "kosong" in j.get("reason", ""), j.get("reason"))

    print("== 5. Penyimpanan: chain dan pool bertahan setelah node dimatikan ==")
    B.buat_tx("Distributor", "SP-1", "SHIPPED")      # SHIPPED sudah ada di chain -> ditolak
    st, r = B.buat_tx("Dealer", "SP-1", "SHIPPED")   # B tidak memegang Dealer -> ditolak
    st, r = A.buat_tx("Produsen", "SP-2", "PRODUCED")
    cek("transaksi baru masuk pool B (ada yang pending saat dimatikan)", st == 201 and B.status()["pool"] == 1)
    time.sleep(2.5)                                    # beri waktu autosave
    ujung = B.status()["ujung_hash"]
    B.stop()
    cek("node B berhenti dan menyimpan state", "State disimpan" in B.log())
    B2 = Node("B", PB, ["Distributor"], [f"127.0.0.1:{PA}"], data_dir=B.data_dir, tmp=B.tmp).start()
    time.sleep(1.0)
    s = B2.status()
    cek("setelah restart: 2 block, ujung sama, chain valid", s["jumlah_block"] == 2 and s["ujung_hash"] == ujung and s["chain_valid"])
    cek("setelah restart: transaksi pending ikut pulih", s["pool"] == 1)
    cek("log menyebut chain dimuat dari disk", "Dimuat dari" in B2.log())
    B2.stop()

    print("== 6. Berkas chain.json yang dimanipulasi DITOLAK saat dimuat ==")
    path = os.path.join(B.data_dir, "chain.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data["chain"][1]["transactions"][0]["status"] = "INSTALLED"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    B3 = Node("B", PB, ["Distributor"], [], data_dir=B.data_dir, tmp=B.tmp).start()
    time.sleep(0.5)
    cek("node menolak berkas yang dimanipulasi dan mulai dari genesis",
        B3.status()["jumlah_block"] == 0 and "DITOLAK saat validasi" in B3.log())
    B3.stop()
finally:
    A.stop()
    try: B.stop()
    except Exception: pass
sys.exit(u.ringkasan())
