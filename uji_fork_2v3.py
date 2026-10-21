# -*- coding: utf-8 -*-
"""Uji Tugas 5: fork 2 block vs 3 block dan longest-chain rule.

Jalankan: python uji_fork_2v3.py        (memakai port 9121 dan 9122)

Skenario persis dari soal:
  1. Dua node dijalankan TANPA peer sama sekali.
  2. Node A menambang 2 block, node B menambang 3 block -> rantai keduanya berbeda.
  3. Kedua node dihubungkan lewat POST /peers (tanpa restart).
  4. POST /nodes/resolve dijalankan: rantai yang lebih panjang (B, 3 block) menang;
     2 block A menjadi ORPHAN dan transaksinya kembali ke transaction pool A.
"""
import sys
import time

import uji_util as u
from uji_util import Node, cek, http_req

PA, PB = 9121, 9122
A = Node("A", PA, ["Produsen", "Distributor"])
B = Node("B", PB, ["Dealer", "Bengkel"])
try:
    print("== 1. Dua node tanpa peer; A menambang 2 block, B menambang 3 block ==")
    A.start(); B.start()
    A.buat_tx("Produsen", "SP-A", "PRODUCED"); A.tambang()
    A.buat_tx("Distributor", "SP-A", "SHIPPED"); A.tambang()
    B.buat_tx("Dealer", "SP-B", "PRODUCED"); B.tambang()
    B.buat_tx("Dealer", "SP-B", "SHIPPED"); B.tambang()
    B.buat_tx("Bengkel", "SP-B", "RECEIVED"); B.tambang()
    sa, sb = A.status(), B.status()
    cek("A punya 2 block, B punya 3 block", sa["jumlah_block"] == 2 and sb["jumlah_block"] == 3)
    cek("rantai A dan B berbeda (ujung berbeda)", sa["ujung_hash"] != sb["ujung_hash"])
    cek("tidak ada peer sama sekali di kedua node", sa["peers"] == [] and sb["peers"] == [])
    hash_a1 = A.req("GET", "/chain")[1]["blocks"][1]["hash"]

    print("== 2. Hubungkan lewat POST /peers (tanpa restart) ==")
    s1, r1 = A.req("POST", "/peers", {"peer": f"127.0.0.1:{PB}"})
    s2, r2 = B.req("POST", "/peers", {"peer": f"127.0.0.1:{PA}"})
    cek("POST /peers ke A -> 201", s1 == 201 and r1.get("peers") == [f"127.0.0.1:{PB}"], f"{s1} {r1}")
    cek("POST /peers ke B -> 201", s2 == 201 and r2.get("peers") == [f"127.0.0.1:{PA}"], f"{s2} {r2}")
    s3, r3 = A.req("POST", "/peers", {"peer": f"127.0.0.1:{PB}"})
    cek("POST /peers duplikat -> 200 'peer sudah ada'", s3 == 200 and r3.get("note") == "peer sudah ada")
    s4, r4 = A.req("POST", "/peers", {"peer": "format-salah"})
    cek("POST /peers format salah -> 400", s4 == 400 and r4.get("type") == "REJECT")
    cek("GET /peers menampilkan peer", A.req("GET", "/peers")[1]["peers"] == [f"127.0.0.1:{PB}"])
    cek("A mencatat penambahan peer di console", "Peer ditambahkan lewat POST /peers" in A.log())

    print("== 3. Resolve di A (POST /nodes/resolve): A mengambil rantai B yang lebih panjang ==")
    sr, rr = A.req("POST", "/nodes/resolve", timeout=60)
    time.sleep(0.5)
    cek("resolve -> 200 dan 1 fork ditangani", sr == 200 and rr.get("fork_ditangani") == 1, f"{sr} {rr}")
    sa, sb = A.status(), B.status()
    cek("A kini punya 3 block, ujung sama dengan B", sa["jumlah_block"] == 3 and sa["ujung_hash"] == sb["ujung_hash"])
    cek("rantai A seluruhnya identik dengan B",
        [b["hash"] for b in A.req("GET", "/chain")[1]["blocks"]] == [b["hash"] for b in B.req("GET", "/chain")[1]["blocks"]])
    cek("block A lama (#1 milik A) tidak ada lagi di rantai utama",
        hash_a1 not in [b["hash"] for b in A.req("GET", "/chain")[1]["blocks"]])
    log_a = A.log()
    cek("log A memuat laporan [FORK] dan keputusan longest-chain",
        "[FORK] terdeteksi" in log_a and "LEBIH PANJANG" in log_a)
    cek("log A menyebut 2 block menjadi ORPHAN", "2 block lokal menjadi ORPHAN" in log_a)
    cek("2 transaksi dari block orphan kembali ke pool A", sa["pool"] == 2, f"pool={sa['pool']}")
    cek("A mencatat fork di riwayat (menu 8)", "GANTI" in log_a or "diganti" in log_a)

    print("== 4. Resolve di B: tidak ada fork lagi ==")
    sr, rr = B.req("POST", "/nodes/resolve", timeout=60)
    cek("resolve di B -> 200 tanpa fork", sr == 200 and rr.get("fork_ditangani") == 0, f"{sr} {rr}")
    cek("B juga menerima 2 transaksi pending dari A", B.status()["pool"] == 2)

    print("== 5. Transaksi orphan ditambang ulang dan rantai kembali sama ==")
    st, r = A.tambang()
    cek("A menambang block 4 dari 2 transaksi yang dikembalikan", st == 201 and len(r["block"]["transactions"]) == 2, f"{st}")
    cek("A dan B sama-sama 4 block dengan pool kosong",
        A.status()["jumlah_block"] == 4 and B.status()["jumlah_block"] == 4
        and A.status()["pool"] == 0 and B.status()["pool"] == 0)
    cek("ujung rantai A dan B sama", A.status()["ujung_hash"] == B.status()["ujung_hash"])
    cek("chain valid di kedua node", A.status()["chain_valid"] and B.status()["chain_valid"])
finally:
    A.stop(); B.stop()
sys.exit(u.ringkasan())
