# -*- coding: utf-8 -*-
"""Uji fork lewat jaringan: panjang SAMA (SERI) lalu diselesaikan oleh block berikutnya.

Jalankan: python uji_fork.py        (memakai port 9111 dan 9112)

  1. A dan B menambang masing-masing 1 block berbeda (tanpa peer).
  2. Keduanya dihubungkan; resolve -> panjang sama: SERI, rantai lokal dipertahankan.
  3. A menambang block berikutnya dan menyiarkannya; B mendapati block itu tidak
     menyambung -> sinkron -> rantai A (lebih panjang) menang di B.
(Kasus rantai peer lebih pendek / PERTAHANKAN dan penolakan rantai palsu diuji di uji_core.py.)
"""
import sys
import time

import uji_util as u
from uji_util import Node, cek

PA, PB = 9111, 9112
A = Node("A", PA, ["Produsen", "Distributor"])
B = Node("B", PB, ["Dealer"])
try:
    print("== 1. Dua node tanpa peer, masing-masing 1 block berbeda ==")
    A.start(); B.start()
    A.buat_tx("Produsen", "SP-1", "PRODUCED"); A.tambang()
    B.buat_tx("Dealer", "SP-2", "PRODUCED"); B.tambang()
    cek("A=1 block, B=1 block, ujung berbeda",
        A.status()["jumlah_block"] == 1 and B.status()["jumlah_block"] == 1
        and A.status()["ujung_hash"] != B.status()["ujung_hash"])

    print("== 2. Dihubungkan: panjang sama -> SERI ==")
    A.req("POST", "/peers", {"peer": f"127.0.0.1:{PB}"})
    B.req("POST", "/peers", {"peer": f"127.0.0.1:{PA}"})
    ujung_a, ujung_b = A.status()["ujung_hash"], B.status()["ujung_hash"]
    sr, rr = A.req("POST", "/nodes/resolve", timeout=60)
    cek("resolve di A: 1 fork ditangani", sr == 200 and rr["fork_ditangani"] == 1, str(rr))
    cek("panjang sama -> A mempertahankan rantainya (SERI)", A.status()["ujung_hash"] == ujung_a)
    cek("log A menyebut SERI / panjang SAMA", "panjang SAMA" in A.log())
    cek("B juga tidak berubah", B.status()["ujung_hash"] == ujung_b)

    print("== 3. A menambang block berikutnya -> B beralih ke rantai A ==")
    A.buat_tx("Distributor", "SP-1", "SHIPPED")
    time.sleep(0.5)
    st, r = A.tambang()
    cek("A menambang block 2", st == 201 and r["block"]["index"] == 2)
    time.sleep(1.5)
    sb = B.status()
    cek("B beralih ke rantai A (2 block, ujung sama)",
        sb["jumlah_block"] == 2 and sb["ujung_hash"] == A.status()["ujung_hash"], f"{sb['jumlah_block']} block")
    log_b = B.log()
    cek("log B memuat [FORK] dengan keputusan rantai lebih panjang", "[FORK] terdeteksi" in log_b and "LEBIH PANJANG" in log_b)
    cek("transaksi SP-2 dari block orphan B kembali ke pool B", sb["pool"] == 1, f"pool={sb['pool']}")
    cek("chain valid di kedua node", A.status()["chain_valid"] and B.status()["chain_valid"])
finally:
    A.stop(); B.stop()
sys.exit(u.ringkasan())
