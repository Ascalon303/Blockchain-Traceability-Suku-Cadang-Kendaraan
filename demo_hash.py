"""
demo_hash.py -- demo hashing untuk Tugas 2 (implementasi hashing) dan Tugas 3 (praktikum).

Isi:
  Bagian 1. Sifat hash SHA-256 (hashlib): deterministik, panjang tetap, avalanche effect.
  Bagian 2. Data domain (suku cadang kendaraan) di dalam TRANSAKSI ikut menentukan
            hash block (lewat Merkle root), dan mengubah data setelah block jadi
            merusak hash tersimpan, PoW, dan tanda tangan transaksi.
  Bagian 3. Kenapa dua transaksi berisi data SAMA tetap punya tx_id/hash berbeda
            (kunci AES acak + nonce + timestamp).

Pemakaian:
  python demo_hash.py

Simpan seluruh keluaran sebagai tangkapan layar untuk laporan.
"""
import copy
import hashlib
import json

import blockchain_core_traceability_suku_cadang_kendaraan as core


def sha256_hex(teks: str) -> str:
    return hashlib.sha256(teks.encode("utf-8")).hexdigest()


def bit_beda(a_hex: str, b_hex: str) -> int:
    """Hitung jumlah bit yang berbeda antara dua hash (XOR lalu hitung bit 1)."""
    return bin(int(a_hex, 16) ^ int(b_hex, 16)).count("1")


def garis(judul: str):
    print("\n" + "=" * 70)
    print(judul)
    print("=" * 70)


# ---------------------------------------------------------------------
def bagian1():
    garis("BAGIAN 1. SIFAT HASH SHA-256 (hashlib)")

    teks = "Filter Oli Honda Beat"
    h1 = sha256_hex(teks)
    h2 = sha256_hex(teks)
    print(f"Input        : {teks!r}")
    print(f"SHA-256      : {h1}")
    print(f"Panjang hash : {len(h1)} karakter hex = {len(h1) * 4} bit (tetap, berapa pun panjang input)")
    print(f"Deterministik: hash input yang sama dihitung dua kali -> sama? {h1 == h2}")

    panjang = sha256_hex("a" * 100000)
    print(f"Input 100.000 karakter tetap menghasilkan {len(panjang) * 4} bit")

    print("\n--- Avalanche effect: ubah SATU karakter ---")
    teks2 = "Filter Oli Honda Beaa"          # karakter terakhir t -> a
    h3 = sha256_hex(teks2)
    beda = bit_beda(h1, h3)
    print(f"Input asli   : {teks!r}")
    print(f"Hash asli    : {h1}")
    print(f"Input diubah : {teks2!r}")
    print(f"Hash diubah  : {h3}")
    print(f"Bit berbeda  : {beda} dari 256 ({beda / 256 * 100:.1f}%)  -> idealnya mendekati 50%")

    # Rata-rata di semua posisi karakter: bukti bahwa ini bukan kebetulan satu kasus.
    total = 0
    for i in range(len(teks)):
        ubahan = teks[:i] + ("a" if teks[i] != "a" else "b") + teks[i + 1:]
        total += bit_beda(h1, sha256_hex(ubahan))
    rata = total / len(teks)
    print(f"Rata-rata bit berbeda untuk perubahan 1 karakter di {len(teks)} posisi berbeda: "
          f"{rata:.1f} / 256 ({rata / 256 * 100:.1f}%)")


# ---------------------------------------------------------------------
def buat_block_contoh():
    """Satu transaksi bertanda tangan dimasukkan ke block 1 lalu ditambang."""
    core.get_or_create_author("Produsen")
    tx = core.make_transaction("Produsen", "SP-002", "Filter Oli Honda Beat",
                               "Produsen", "Distributor", "VH-010", "PRODUCED")
    blk = core.Block(1, [tx], core.GENESIS_HASH)
    hasil, percobaan, detik = core.mine_with_retry(blk)
    return tx, blk, percobaan, detik


def coba_ubah(blk, nama, perubah):
    """Terapkan satu perubahan ke block, tampilkan dampaknya, lalu kembalikan."""
    h_asli = blk.hash
    simpan = (copy.deepcopy(blk.transactions), blk.timestamp)
    perubah(blk)
    h_baru = core.compute_hash(blk)
    beda = bit_beda(h_asli, h_baru)
    print(f"\nPerubahan    : {nama}")
    print(f"  hash dihitung ulang : {h_baru}")
    print(f"  hash berubah?       : {h_baru != h_asli} ({beda}/256 bit berbeda)")
    print(f"  cocok dg hash tersimpan di block? : {h_baru == blk.hash}")
    print(f"  PoW masih valid?    : {core.verify_pow(blk)}")
    print(f"  tanda tangan transaksi valid? : {core.verify_transaction(blk.transactions[0])[0]}")
    blk.transactions, blk.timestamp = simpan


def bagian2():
    garis("BAGIAN 2. DATA DOMAIN IKUT MENENTUKAN HASH BLOCK")

    tx, blk, percobaan, detik = buat_block_contoh()
    tampil = dict(tx)
    tampil["envelope"] = {k: v[:24] + "..." for k, v in tx["envelope"].items()}
    tampil["signature"] = tx["signature"][:24] + "..."
    print("Transaksi domain (suku cadang kendaraan), bertanda tangan pengirim:")
    print(json.dumps(tampil, indent=2))
    print("Detail (part_name, origin, destination, vehicle_id) ada di envelope TERENKRIPSI;")
    print("part_id dan status terlihat semua node untuk aturan urutan status.")

    print(f"\nMenambang block (DIFFICULTY = {core.DIFFICULTY!r}, hash harus diawali string itu)...")
    print(f"Merkle root  : {blk.merkle_root}")
    print(f"Hash block   : {blk.hash}")
    print(f"Nonce        : {blk.nonce} | percobaan: {percobaan:,} | waktu: {detik:.3f} detik")
    print(f"PoW valid?   : {core.verify_pow(blk)} | tanda tangan transaksi valid? {core.verify_transaction(tx)[0]}")
    print(f"Catatan: hash diawali {core.DIFFICULTY!r} karena memenuhi DIFFICULTY.")

    print("\n--- Sekarang data transaksi di dalam block diubah SETELAH block jadi ---")

    coba_ubah(blk, "part_id SP-002 -> SP-003",
              lambda b: b.transactions[0].__setitem__("part_id", "SP-003"))

    coba_ubah(blk, "status PRODUCED -> SHIPPED",
              lambda b: b.transactions[0].__setitem__("status", "SHIPPED"))

    # part_name ada di dalam amplop terenkripsi, jadi mengubahnya = mengganti ciphertext.
    def ganti_isi_terenkripsi(b):
        _, pub = core.get_or_create_author("Produsen")
        b.transactions[0]["envelope"] = core.hybrid_encrypt('{"part_name": "Filter Oli PALSU"}', pub)

    coba_ubah(blk, "isi terenkripsi (part_name) diganti", ganti_isi_terenkripsi)

    coba_ubah(blk, "timestamp block diubah +1 detik",
              lambda b: setattr(b, "timestamp", round(b.timestamp + 1, 3)))

    print("\n--- Setelah semua perubahan dikembalikan ---")
    h_pulih = core.compute_hash(blk)
    print(f"Hash sama dengan semula? {h_pulih == blk.hash}")
    print(f"PoW valid? {core.verify_pow(blk)} | tanda tangan transaksi valid? "
          f"{core.verify_transaction(blk.transactions[0])[0]}")

    print("\nKesimpulan: setiap transaksi (part_id, status, isi terenkripsi, tanda tangan) masuk ke")
    print("Merkle root -> hash block. Mengubah satu field mengubah hash, sehingga hash tersimpan")
    print("tidak cocok, PoW tidak lagi memenuhi difficulty, dan tanda tangan transaksi tidak valid.")


# ---------------------------------------------------------------------
def bagian3():
    garis("BAGIAN 3. DATA SAMA, HASH BERBEDA (kunci AES acak + nonce + timestamp)")

    core.get_or_create_author("Produsen")
    t1 = core.make_transaction("Produsen", "SP-002", "Filter Oli Honda Beat",
                               "Produsen", "Distributor", "VH-010", "PRODUCED")
    t2 = core.make_transaction("Produsen", "SP-002", "Filter Oli Honda Beat",
                               "Produsen", "Distributor", "VH-010", "PRODUCED")
    b1 = core.Block(1, [t1], core.GENESIS_HASH, timestamp=1.0)
    b2 = core.Block(1, [t2], core.GENESIS_HASH, timestamp=1.0)
    print("Dua transaksi dibuat dari data yang IDENTIK, dan dua block memakai timestamp yang sama:")
    print(f"  tx_id transaksi 1 : {t1['tx_id']}")
    print(f"  tx_id transaksi 2 : {t2['tx_id']}")
    print(f"  hash block 1      : {core.compute_hash(b1)}")
    print(f"  hash block 2      : {core.compute_hash(b2)}")
    print(f"  sama? {core.compute_hash(b1) == core.compute_hash(b2)}")
    print("Penyebab: tiap transaksi memakai kunci AES acak dan nonce acak untuk amplop enkripsi,")
    print("sehingga ciphertext (dan tx_id, Merkle root, hash) berbeda. Karena itu bukti 'data mengubah")
    print("hash' dilakukan dengan mengubah field pada block yang SAMA (Bagian 2), bukan membandingkan dua block.")


if __name__ == "__main__":
    bagian1()
    bagian2()
    bagian3()
