# -*- coding: utf-8 -*-
"""Uji EMPAT node, satu node untuk tiap aktor berwenang (sesuai docker_compose.yml).

Jalankan: python uji_4node.py        (memakai port 9181-9184)

  node1 = Produsen, node2 = Distributor, node3 = Dealer, node4 = Bengkel

Satu suku cadang menempuh seluruh siklusnya: PRODUCED (Produsen) -> SHIPPED
(Distributor) -> RECEIVED (Dealer) -> INSTALLED (Bengkel). Tiap transaksi dibuat dan
ditandatangani di node aktornya, tetapi block ditambang oleh node LAIN, lalu
disiarkan ke tiga node sisanya.
"""
import sys
import time

import uji_util as u
from uji_util import Node, cek

AKTOR = {"N1": ("Produsen", 9181), "N2": ("Distributor", 9182),
         "N3": ("Dealer", 9183), "N4": ("Bengkel", 9184)}


def peers_untuk(nama):
    return [f"127.0.0.1:{p}" for k, (_, p) in AKTOR.items() if k != nama]


nodes = {k: Node(k, p, [a], peers_untuk(k)) for k, (a, p) in AKTOR.items()}
semua = list(nodes.values())
N1, N2, N3, N4 = (nodes[k] for k in ("N1", "N2", "N3", "N4"))


def tunggu(kondisi, detik=8.0):
    batas = time.time() + detik
    while time.time() < batas:
        if kondisi():
            return True
        time.sleep(0.2)
    return False


def semua_punya(kunci, nilai):
    return tunggu(lambda: all(n.status()[kunci] == nilai for n in semua))


try:
    print("== 1. Empat node, satu per aktor berwenang ==")
    for n in semua:
        n.start()
    time.sleep(1.5)
    cek("keempat node hidup dengan genesis yang sama",
        len({n.status()["ujung_hash"] for n in semua}) == 1 and all(n.status()["jumlah_block"] == 0 for n in semua))
    cek("tiap node memegang tepat satu aktor, semuanya berbeda",
        sorted(a for n in semua for a in n.status()["aktor_lokal"]) == ["Bengkel", "Dealer", "Distributor", "Produsen"])
    cek("tiap node mengenal 3 peer", all(len(n.status()["peers"]) == 3 for n in semua))

    print("== 2. Siklus satu suku cadang: tiap aktor menandatangani di node sendiri ==")
    langkah = [
        ("Produsen", N1, "PRODUCED", N2),      # transaksi di N1, ditambang N2
        ("Distributor", N2, "SHIPPED", N3),    # transaksi di N2, ditambang N3
        ("Dealer", N3, "RECEIVED", N4),        # transaksi di N3, ditambang N4
        ("Bengkel", N4, "INSTALLED", N1),      # transaksi di N4, ditambang N1
    ]
    for i, (aktor, pembuat, status, penambang) in enumerate(langkah, 1):
        st, r = pembuat.buat_tx(aktor, "SP-1", status, nama="Filter Oli Honda Beat")
        cek(f"{aktor} membuat transaksi {status} di node-nya -> 201", st == 201, str(r.get("reason", "")))
        cek(f"transaksi {status} sampai ke pool keempat node", semua_punya("pool", 1))
        st, r = penambang.tambang()
        cek(f"{penambang.nama} menambang block {i} dari transaksi {aktor}",
            st == 201 and r["block"]["index"] == i and r["block"]["transactions"][0]["sender"] == aktor, f"{st}")
        cek(f"keempat node punya {i} block dan pool kosong",
            semua_punya("jumlah_block", i) and semua_punya("pool", 0))

    print("== 3. Hasil akhir identik di keempat node ==")
    cek("ujung rantai sama di keempat node", len({n.status()["ujung_hash"] for n in semua}) == 1)
    cek("chain_valid = True di keempat node (semua tanda tangan keempat aktor terverifikasi)",
        all(n.status()["chain_valid"] for n in semua))
    rantai = {n.nama: n.req("GET", "/chain")[1]["blocks"] for n in semua}
    cek("urutan pengirim di rantai = Produsen, Distributor, Dealer, Bengkel (di semua node)",
        all([b["transactions"][0]["sender"] for b in rantai[k][1:]] == ["Produsen", "Distributor", "Dealer", "Bengkel"]
            for k in rantai))
    cek("urutan status di rantai = PRODUCED, SHIPPED, RECEIVED, INSTALLED",
        [b["transactions"][0]["status"] for b in rantai["N1"][1:]] == ["PRODUCED", "SHIPPED", "RECEIVED", "INSTALLED"])
    cek("setiap block menyambung ke block sebelumnya (previous_hash)",
        all(rantai["N1"][i]["previous_hash"] == rantai["N1"][i - 1]["hash"] for i in range(1, 5)))

    print("== 4. Siklus sudah selesai: transaksi lanjutan ditolak ==")
    st, r = N2.buat_tx("Distributor", "SP-1", "SHIPPED")
    cek("SHIPPED lagi setelah INSTALLED -> 409", st == 409, r.get("reason"))
    st, r = N1.buat_tx("Produsen", "SP-1", "PRODUCED")
    cek("PRODUCED ulang untuk part yang sama -> 409", st == 409, r.get("reason"))
    cek("tidak ada transaksi nyangkut di pool", all(n.status()["pool"] == 0 for n in semua))

    print("== 5. Log console tiap node memuat langkahnya ==")
    for n, tag in [(N1, "[TX] DITERIMA"), (N2, "[MINING] SELESAI block #1"), (N3, "[BLOCK] DITERIMA block #1"),
                   (N4, "[BLOCK] DITERIMA block #2"), (N4, "[MINING] SELESAI block #3"),
                   (N1, "[BROADCAST] block #4")]:
        cek(f"log {n.nama} memuat '{tag}'", tag in n.log())
finally:
    for n in semua:
        n.stop()
sys.exit(u.ringkasan())
