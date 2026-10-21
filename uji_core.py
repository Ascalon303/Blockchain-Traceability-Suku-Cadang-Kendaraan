# -*- coding: utf-8 -*-
"""Uji otomatis untuk INTI blockchain (tanpa jaringan), per ketentuan C.2.

Jalankan: python uji_core.py
Memeriksa: struktur block, transaksi bertanda tangan, transaction pool,
proof of work, validasi chain + deteksi manipulasi, longest-chain rule.
"""
import copy

import blockchain_core_traceability_suku_cadang_kendaraan as core

hasil = []


def cek(nama, kondisi, info=""):
    hasil.append(bool(kondisi))
    print(("  [LULUS] " if kondisi else "  [GAGAL] ") + nama + (f"  ({info})" if info else ""))


def senyap(tag, pesan):      # log dibisukan agar keluaran uji ringkas
    pass


def ledger_baru():
    return core.Ledger(log=senyap)


def tx(sender, part, status, nama="Filter Oli"):
    return core.make_transaction(sender, part, nama, "Produsen", "Dealer", "VH-1", status)


for a in core.ACTOR_ORDER:
    core.get_or_create_author(a)

print("== 1. Struktur block dan genesis ==")
L = ledger_baru()
g = L.chain[0]
cek("rantai dimulai dari genesis index 0", len(L.chain) == 1 and g.index == 0)
cek("genesis tanpa transaksi, previous_hash nol", g.transactions == [] and g.previous_hash == "0" * 64)
cek("genesis sama di setiap ledger (deterministik)", ledger_baru().chain[0].hash == g.hash == core.GENESIS_HASH)
cek("chain awal valid", L.validate()[0], L.validate()[1])

print("== 2. Transaksi bertanda tangan ==")
t1 = tx("Produsen", "SP-1", "PRODUCED")
cek("transaksi memuat sender, timestamp, part_id, status, envelope, tx_id, signature",
    all(k in t1 for k in core.TX_FIELDS))
cek("transaksi valid diverifikasi", core.verify_transaction(t1)[0])
t_ubah = copy.deepcopy(t1); t_ubah["part_id"] = "SP-X"
ok, alasan = core.verify_transaction(t_ubah)
cek("isi transaksi diubah -> DITOLAK", not ok, alasan)
t_palsu = copy.deepcopy(t1); t_palsu["sender"] = "Dealer"
ok, alasan = core.verify_transaction(t_palsu)
cek("sender dipalsukan (bukan penanda tangan) -> DITOLAK", not ok, alasan)
t_ubah2 = copy.deepcopy(t1); t_ubah2["part_id"] = "SP-X"; t_ubah2["tx_id"] = core.tx_hash(t_ubah2)
ok, alasan = core.verify_transaction(t_ubah2)
cek("isi diubah + tx_id dihitung ulang -> tanda tangan tidak cocok, DITOLAK", not ok, alasan)
cek("detail terenkripsi bisa dibuka pengirim",
    core.read_transaction_details(t1)["part_name"] == "Filter Oli")

print("== 3. Transaction pool dan aturan status ==")
L = ledger_baru()
st, _ = L.add_to_pool(t1)
cek("transaksi valid masuk pool", st == "NEW" and len(L.pool) == 1)
st, _ = L.add_to_pool(t1)
cek("transaksi yang sama dua kali -> DUPLICATE", st == "DUPLICATE" and len(L.pool) == 1)
t_kembar = copy.deepcopy(t1); t_kembar["part_id"] = "SP-HACK"     # tx_id sama dengan yang di pool, isi diubah
st, alasan = L.add_to_pool(t_kembar)
cek("isi diubah dengan tx_id yang sama -> REJECT (bukan dianggap duplikat)", st == "REJECT" and len(L.pool) == 1, alasan)
t_sig = copy.deepcopy(t1); t_sig["signature"] = "ab" * 64
st, alasan = L.add_to_pool(t_sig)
cek("tanda tangan dipalsukan dengan tx_id sama -> REJECT", st == "REJECT", alasan)
st, alasan = L.add_to_pool(tx("Distributor", "SP-2", "SHIPPED"))
cek("SHIPPED tanpa PRODUCED -> DITOLAK", st == "REJECT", alasan)
st, alasan = L.add_to_pool(tx("Produsen", "SP-1", "PRODUCED"))
cek("PRODUCED kedua untuk part yang sama -> DITOLAK", st == "REJECT", alasan)
t2 = tx("Distributor", "SP-1", "SHIPPED")
st, _ = L.add_to_pool(t2)
cek("SHIPPED setelah PRODUCED (dalam pool) -> diterima", st == "NEW" and len(L.pool) == 2)

print("== 4. Block dari isi pool + proof of work ==")
blk, percobaan, detik = L.mine_pending()
cek("block berisi 2 transaksi dari pool", len(blk.transactions) == 2 and blk.index == 1)
cek("pool dikosongkan setelah block masuk rantai", len(L.pool) == 0)
cek("previous_hash = hash genesis", blk.previous_hash == core.GENESIS_HASH)
cek("hash tersimpan = hash dihitung ulang", blk.hash == core.compute_hash(blk))
cek("hash diawali DIFFICULTY dan nonce tersimpan",
    blk.hash.startswith(core.DIFFICULTY) and isinstance(blk.nonce, int), f"nonce={blk.nonce}")
cek("PoW dapat diverifikasi ulang", core.verify_pow(blk))
cek("chain valid setelah mining", L.validate()[0])
try:
    L.mine_pending()
    cek("pool kosong -> mining ditolak", False)
except core.PoolEmpty:
    cek("pool kosong -> mining ditolak (PoolEmpty)", True)

t3 = tx("Dealer", "SP-1", "RECEIVED")
L.add_to_pool(t3)
b2, *_ = L.mine_pending()
cek("block kedua menyambung ke block pertama", b2.previous_hash == blk.hash and b2.index == 2)
cek("status berikutnya mengikuti status terakhir di rantai",
    L.add_to_pool(tx("Produsen", "SP-1", "SHIPPED"))[0] == "REJECT")

print("== 5. Validasi chain dan deteksi manipulasi ==")
ok, alasan = L.validate()
cek("rantai 2 block valid", ok, alasan)
for judul, terdeteksi, alasan in core.demo_manipulasi(L.chain):
    cek("terdeteksi: " + judul, terdeteksi, alasan)
c = copy.deepcopy(L.chain)
c[1].transactions.append(copy.deepcopy(t3))
cek("transaksi disisipkan ke block lama -> terdeteksi", not core.is_chain_valid(c)[0])
c = copy.deepcopy(L.chain)
c[1].hash = "0000" + "a" * 60
cek("hash tersimpan dipalsukan -> terdeteksi", not core.is_chain_valid(c)[0])

print("== 6. Menerima block dari jaringan ==")
L2 = ledger_baru()
st, alasan = L2.receive_block(core.block_to_dict(blk))
cek("block 1 dari peer diterima", st == "ADDED", alasan)
st, _ = L2.receive_block(core.block_to_dict(blk))
cek("block yang sama lagi -> DUPLICATE", st == "DUPLICATE")
d = core.block_to_dict(blk); d["transactions"][0]["status"] = "INSTALLED"    # hash klaim = hash block yang sudah ada
st, alasan = L2.receive_block(d)
cek("isi diubah tetapi mengklaim hash block yang sudah ada -> REJECT (bukan DUPLICATE)", st == "REJECT", alasan)
st, _ = ledger_baru().receive_block(core.block_to_dict(b2))
cek("block yang melompati rantai -> FORK (perlu sinkron)", st == "FORK")
d = core.block_to_dict(b2); d["transactions"][0]["status"] = "INSTALLED"
st, alasan = L2.receive_block(d)
cek("block dengan isi dimanipulasi -> REJECT", st == "REJECT", alasan)
d = core.block_to_dict(b2); d["hash"] = "f" * 64
st, alasan = L2.receive_block(d)
cek("block dengan hash palsu -> REJECT", st == "REJECT", alasan)
d = core.block_to_dict(b2); del d["merkle_root"]
st, alasan = L2.receive_block(d)
cek("block dengan format cacat -> REJECT", st == "REJECT", alasan)
st, _ = L2.receive_block(core.block_to_dict(b2))
cek("block 2 sah diterima", st == "ADDED" and L2.panjang() == 2)

print("== 7. Longest-chain rule dan fork ==")
A, B = ledger_baru(), ledger_baru()
A.add_to_pool(tx("Produsen", "SP-A", "PRODUCED")); A.mine_pending()
A.add_to_pool(tx("Distributor", "SP-A", "SHIPPED")); A.mine_pending()
B.add_to_pool(tx("Dealer", "SP-B", "PRODUCED")); B.mine_pending()
B.add_to_pool(tx("Dealer", "SP-B", "SHIPPED")); B.mine_pending()
B.add_to_pool(tx("Bengkel", "SP-B", "RECEIVED")); B.mine_pending()
cek("A punya 2 block, B punya 3 block (rantai berbeda sejak genesis)", A.panjang() == 2 and B.panjang() == 3)
r = A.consider_chain(B.chain_dicts())
cek("A mengganti rantainya dengan rantai B yang lebih panjang", r["status"] == "GANTI" and A.panjang() == 3, str(r.get("status")))
cek("rantai A kini identik dengan B", [b.hash for b in A.chain] == [b.hash for b in B.chain])
cek("2 block A menjadi orphan; 2 transaksinya kembali ke pool A",
    len(A.pool) == 2 and r["fork"]["tx_dikembalikan"] == 2, f"pool={len(A.pool)}")
r = B.consider_chain(A.chain_dicts())
cek("B menerima rantai identik -> SAMA", r["status"] == "SAMA")
r = ledger_baru().consider_chain(B.chain_dicts())
cek("node baru mengambil rantai B (diperpanjang dari genesis)", r["status"] == "DIPERPANJANG")
r = B.consider_chain(core.block_to_dict(g) and [core.block_to_dict(g)])
cek("rantai peer lebih pendek -> PERTAHANKAN", r["status"] == "PERTAHANKAN")
X, Y = ledger_baru(), ledger_baru()
X.add_to_pool(tx("Produsen", "SP-X", "PRODUCED")); X.mine_pending()
Y.add_to_pool(tx("Produsen", "SP-Y", "PRODUCED")); Y.mine_pending()
r = X.consider_chain(Y.chain_dicts())
cek("panjang sama tapi beda -> SERI, rantai lokal dipertahankan", r["status"] == "SERI" and X.panjang() == 1)
bad = B.chain_dicts(); bad[2]["transactions"][0]["part_id"] = "SP-HACK"
r = ledger_baru().consider_chain(bad)
cek("rantai peer yang dimanipulasi -> REJECT", r["status"] == "REJECT", r.get("alasan"))

print("== 8. Penyimpanan ==")
snap_chain, snap_pool = A.chain_dicts(), A.pool_snapshot()
Z = ledger_baru()
ok, pesan = Z.load_state(snap_chain, snap_pool)
cek("rantai dan pool dapat dimuat ulang dan divalidasi", ok and Z.panjang() == 3 and len(Z.pool) == 2, pesan)
snap_chain[1]["transactions"][0]["status"] = "SHIPPED"
ok, pesan = ledger_baru().load_state(snap_chain, [])
cek("berkas rantai yang dimanipulasi DITOLAK saat dimuat", not ok, pesan)

print(f"\nRingkasan: {sum(hasil)}/{len(hasil)} lulus")
raise SystemExit(0 if all(hasil) else 1)
