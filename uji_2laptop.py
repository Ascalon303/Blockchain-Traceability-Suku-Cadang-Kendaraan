# -*- coding: utf-8 -*-
"""Uji topologi DUA LAPTOP (docker-compose.laptop1.yml dan docker-compose.laptop2.yml),
dijalankan lokal sebagai dua proses.

Jalankan: python uji_2laptop.py        (memakai port 9191 dan 9192)

  Laptop 1 : port 9191 (di Docker 9001), aktor Produsen + Distributor, peer = laptop 2
  Laptop 2 : port 9192 (di Docker 9002), aktor Dealer + Bengkel,       peer = laptop 1

Hanya SATU peer per laptop. Memeriksa: pertukaran key antar laptop, transaksi dan
block saling tersiar lewat HTTP, privasi isi transaksi lintas laptop (terenkripsi),
siklus penuh PRODUCED sampai INSTALLED, serta laptop yang mati lalu hidup kembali
mengejar ketertinggalan.
"""
import sys
import time

import uji_util as u
from uji_util import Node, cek

P1, P2 = 9191, 9192
L1 = Node("L1", P1, ["Produsen", "Distributor"], [f"127.0.0.1:{P2}"])
L2 = Node("L2", P2, ["Dealer", "Bengkel"], [f"127.0.0.1:{P1}"])


def tunggu(kondisi, detik=8.0):
    batas = time.time() + detik
    while time.time() < batas:
        if kondisi():
            return True
        time.sleep(0.2)
    return False


def sama(kunci, nilai):
    return tunggu(lambda: L1.status()[kunci] == nilai and L2.status()[kunci] == nilai)


try:
    print("== 1. Urutan menyalakan laptop bebas: laptop 1 menyala lebih dulu ==")
    L1.start()
    cek("laptop 1 hidup sendirian (peernya belum menyala)", L1.status()["jumlah_block"] == 0)
    L2.start()
    time.sleep(1.5)
    cek("keduanya mengenal peer lawan", len(L1.status()["peers"]) == 1 and len(L2.status()["peers"]) == 1)
    cek("public key keempat aktor sudah dipertukarkan di kedua laptop",
        len(L1.req("GET", "/keys")[1]["keys"]) == 4 and len(L2.req("GET", "/keys")[1]["keys"]) == 4)
    cek("genesis sama di kedua laptop", L1.status()["ujung_hash"] == L2.status()["ujung_hash"])

    print("== 2. Laptop 1 membuat dua transaksi; laptop 2 menerimanya ==")
    st1, _ = L1.buat_tx("Produsen", "SP-1", "PRODUCED", nama="Filter Oli Honda Beat")
    st2, _ = L1.buat_tx("Distributor", "SP-1", "SHIPPED", nama="Filter Oli Honda Beat")
    cek("Produsen dan Distributor membuat transaksi di laptop 1", st1 == 201 and st2 == 201)
    cek("kedua transaksi sampai ke pool laptop 2 lewat HTTP", sama("pool", 2))

    print("== 3. Laptop 2 menambang; block tersiar ke laptop 1 ==")
    st, r = L2.tambang()
    cek("laptop 2 menambang block 1 berisi 2 transaksi", st == 201 and len(r["block"]["transactions"]) == 2, f"{st}")
    cek("laptop 1 menerima block 1 dan pool kedua laptop kosong", sama("jumlah_block", 1) and sama("pool", 0))

    print("== 4. Laptop 2 menyelesaikan siklus; laptop 1 menambang ==")
    st3, _ = L2.buat_tx("Dealer", "SP-1", "RECEIVED", nama="Filter Oli Honda Beat")
    st4, _ = L2.buat_tx("Bengkel", "SP-1", "INSTALLED", nama="Filter Oli Honda Beat")
    cek("Dealer dan Bengkel membuat transaksi di laptop 2", st3 == 201 and st4 == 201)
    cek("kedua transaksi sampai ke pool laptop 1", sama("pool", 2))
    st, r = L1.tambang()
    cek("laptop 1 menambang block 2", st == 201 and r["block"]["index"] == 2)
    cek("kedua laptop punya 2 block, ujung rantai sama, pool kosong",
        sama("jumlah_block", 2) and sama("pool", 0) and L1.status()["ujung_hash"] == L2.status()["ujung_hash"])
    cek("chain valid di kedua laptop", L1.status()["chain_valid"] and L2.status()["chain_valid"])
    rantai = L2.req("GET", "/chain")[1]["blocks"]
    cek("urutan status di rantai: PRODUCED, SHIPPED, RECEIVED, INSTALLED",
        [t["status"] for b in rantai[1:] for t in b["transactions"]] == ["PRODUCED", "SHIPPED", "RECEIVED", "INSTALLED"])

    print("== 5. Privasi isi transaksi lintas laptop ==")
    L1.menu("4", tunggu=1.5)
    L2.menu("4", tunggu=1.5)
    log1, log2 = L1.log(), L2.log()
    cek("laptop 1 bisa membaca detail transaksi aktornya sendiri", "detail: Filter Oli Honda Beat" in log1)
    cek("laptop 1 TIDAK bisa membaca transaksi Dealer/Bengkel (terenkripsi)", "detail: (terenkripsi" in log1)
    cek("laptop 2 TIDAK bisa membaca transaksi Produsen/Distributor (terenkripsi)", "detail: (terenkripsi" in log2)
    cek("laptop 2 bisa membaca detail transaksi aktornya sendiri", "detail: Filter Oli Honda Beat" in log2)

    print("== 6. Laptop 2 mati; laptop 1 tetap bekerja; laptop 2 hidup dan mengejar ==")
    L2.stop()
    L1.buat_tx("Produsen", "SP-2", "PRODUCED", nama="Kampas Rem")
    st, r = L1.tambang()
    cek("laptop 1 menambang block 3 saat laptop 2 mati", st == 201 and L1.status()["jumlah_block"] == 3)
    cek("log laptop 1 mencatat gagal menyiarkan ke laptop 2", "block #3" in L1.log() and "GAGAL" in L1.log())
    L2 = Node("L2", P2, ["Dealer", "Bengkel"], [f"127.0.0.1:{P1}"], data_dir=L2.data_dir, tmp=L2.tmp).start()
    cek("laptop 2 menyala lagi dan mengejar ke 3 block",
        tunggu(lambda: L2.status()["jumlah_block"] == 3), f"{L2.status()['jumlah_block']} block")
    cek("ujung rantai kembali sama dan valid",
        L1.status()["ujung_hash"] == L2.status()["ujung_hash"] and L2.status()["chain_valid"])
    cek("log laptop 2 menyebut rantai dimuat dari disk lalu diperpanjang",
        "Dimuat dari" in L2.log() and "diperpanjang" in L2.log())
finally:
    L1.stop()
    try:
        L2.stop()
    except Exception:
        pass
sys.exit(u.ringkasan())
