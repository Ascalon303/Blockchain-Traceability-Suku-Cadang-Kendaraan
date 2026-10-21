"""
eksperimen_tulis_ulang.py -- Tugas 6 (bagian keamanan): biaya MENULIS ULANG riwayat.

Pertanyaan: kalau penyerang mengubah data pada block ke-k, berapa kerja (PoW)
yang harus ia keluarkan agar rantai tetap tampak valid?

Jawaban teoretis: mengubah block k mengubah hash-nya, sehingga block k+1 (yang
menyimpan parent_hash) juga berubah, dan seterusnya sampai ujung rantai.
Penyerang harus MENAMBANG ULANG block k sampai block terakhir:

    jumlah block diulang = N - k + 1
    percobaan rata-rata  = (N - k + 1) x 16^n      (n = jumlah karakter "0" pada difficulty)

Eksperimen ini mengukurnya langsung pada difficulty yang berbeda.

Asumsi (batas bawah biaya serangan):
  - Penyerang memegang private key semua author, jadi biaya tanda tangan diabaikan.
  - Difficulty berupa string tetap (tanpa retarget) sehingga yang diukur murni pengaruh difficulty.
  - Penyerang bekerja sendirian. Di jaringan nyata ia juga harus mengejar node
    jujur yang terus menambah block, sehingga biaya aslinya lebih besar lagi.

Pemakaian:
  python eksperimen_tulis_ulang.py
  python eksperimen_tulis_ulang.py --difficulty 0000 00000 --blocks 6 --runs 3 --csv hasil_tulis_ulang.csv

Peringatan: "00000" di Python murni = sekitar 1 juta percobaan per block (beberapa detik).
Mulai dengan --difficulty 000 0000 kalau ingin uji cepat.
"""
import argparse
import copy
import csv
import statistics
import sys

import blockchain_core_traceability_suku_cadang_kendaraan as core

def bangun_chain(n, difficulty):
    """Bangun rantai jujur n block (tiap block 1 transaksi PRODUCED untuk part berbeda)
    pada difficulty tetap, di atas genesis. Return (chain, percobaan, detik)."""
    core.get_or_create_author("Produsen")
    chain, total_a, total_t = [], 0, 0.0
    sebelumnya = core.make_genesis()
    for i in range(1, n + 1):
        tx = core.make_transaction("Produsen", f"SP-ATK-{i}", "Filter Oli", "Pabrik", "Gudang",
                                   "VH-1", "PRODUCED")
        blk = core.Block(i, [tx], sebelumnya.hash)
        h, a, t = core.mine_with_retry(blk, difficulty=difficulty)
        if h is None:
            sys.exit(f"PoW gagal pada block {i}")
        chain.append(blk)
        sebelumnya = blk
        total_a += a
        total_t += t
    return chain, total_a, total_t


def tulis_ulang(chain, k, difficulty):
    """Ubah data block ke-k lalu tambang ulang block k..N. Return (percobaan, detik, valid).
    Catatan: penyerang tidak punya private key pengirim, jadi tanda tangan transaksi yang
    diubah tetap tidak valid (is_chain_valid menolaknya). Skrip ini mengukur BIAYA PoW-nya
    saja, yaitu syarat minimum agar hash dan tautan previous_hash kembali konsisten."""
    s = [copy.deepcopy(b) for b in chain]     # rantai asli tidak disentuh
    s[k - 1].transactions[0]["part_id"] = "SP-PALSU"       # manipulasi data
    total_a, total_t = 0, 0.0
    for j in range(k - 1, len(s)):
        blk = s[j]
        if j > k - 1:                         # block sebelumnya berubah -> previous_hash harus diperbarui
            blk.previous_hash = s[j - 1].hash
        blk.nonce = 0
        blk.extra_nonce = 0
        h, a, t = core.mine_with_retry(blk, difficulty=difficulty)
        if h is None:
            sys.exit(f"PoW gagal saat menulis ulang block {blk.index}")
        total_a += a
        total_t += t
    valid = all(core.verify_pow(b, difficulty) for b in s[k - 1:]) and all(
        s[j].previous_hash == s[j - 1].hash for j in range(k, len(s)))
    return total_a, total_t, valid


def main():
    ap = argparse.ArgumentParser(description="Biaya menulis ulang riwayat vs difficulty")
    ap.add_argument("--difficulty", nargs="+", default=["000", "0000", "00000"],
                    help="daftar difficulty (string awalan hash), mis. 0000 00000")
    ap.add_argument("--blocks", type=int, default=6, help="panjang rantai (N)")
    ap.add_argument("--runs", type=int, default=3, help="ulangan serangan per posisi")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    n = args.blocks
    if n < 2:
        sys.exit("--blocks minimal 2")
    for d in args.difficulty:
        if not d or any(c not in "0123456789abcdef" for c in d):
            sys.exit(f"difficulty '{d}' harus string hex tidak kosong, mis. 0000")

    posisi = sorted({n, (n + 1) // 2, 1}, reverse=True)    # ujung, tengah, awal
    mentah, ringkas = [], []

    print(f"Rantai {n} block | posisi serangan k = {posisi} | {args.runs} ulangan per posisi\n")
    for dif in args.difficulty:
        print(f"[{dif!r}] membangun rantai jujur...")
        chain, a_jujur, t_jujur = bangun_chain(n, dif)
        print(f"[{dif!r}] biaya membangun {n} block: {a_jujur:,} percobaan, {t_jujur:.2f} detik")
        for k in posisi:
            diulang = n - k + 1
            aa, tt = [], []
            for r in range(1, args.runs + 1):
                a, t, valid = tulis_ulang(chain, k, dif)
                if not valid:
                    sys.exit("rantai hasil tulis ulang tidak valid (bug)")
                aa.append(a)
                tt.append(t)
                mentah.append((dif, k, diulang, r, a, round(t, 4)))
            ringkas.append((dif, k, diulang, statistics.mean(aa), diulang * 16 ** len(dif),
                            statistics.mean(tt)))
            print(f"[{dif!r}] k={k}: {diulang} block diulang selesai")

    print()
    kepala = ("Difficulty", "k", "Block diulang", "Percobaan rata2", "Teori (n x 16^n)", "Rasio", "Waktu rata2 (s)")
    baris = [(repr(b), str(k), str(d), f"{ra:,.0f}", f"{teori:,}", f"{ra / teori:.2f}", f"{rt:.3f}")
             for (b, k, d, ra, teori, rt) in ringkas]
    lebar = [max(len(kepala[i]), *(len(r[i]) for r in baris)) for i in range(len(kepala))]
    gr = "+-" + "-+-".join("-" * w for w in lebar) + "-+"
    print(gr)
    print("| " + " | ".join(kepala[i].ljust(lebar[i]) for i in range(len(kepala))) + " |")
    print(gr)
    for r in baris:
        print("| " + " | ".join(r[i].rjust(lebar[i]) for i in range(len(kepala))) + " |")
    print(gr)

    # Perbandingan antar difficulty untuk jumlah block diulang yang sama.
    if len(args.difficulty) > 1:
        print("\nKenaikan biaya antar difficulty (jumlah block diulang sama):")
        for d in sorted({r[2] for r in ringkas}):
            seri = [(r[0], r[3]) for r in ringkas if r[2] == d]
            for (b0, a0), (b1, a1) in zip(seri, seri[1:]):
                print(f"  {d} block diulang, {b0!r} -> {b1!r}: x{a1 / a0:,.1f} (teori x{16 ** (len(b1) - len(b0)):,})")
    print("\nKenaikan biaya terhadap jumlah block yang diulang (difficulty sama):")
    for b in args.difficulty:
        seri = [(r[2], r[3]) for r in ringkas if r[0] == b]
        satu = [a for d, a in seri if d == 1]
        if satu:
            for d, a in seri:
                print(f"  {b!r}: {d} block diulang = x{a / satu[0]:.1f} dari biaya 1 block")
    print(f"\nCatatan: tiap sel hanya {args.runs} ulangan, jadi masih berfluktuasi "
          f"(distribusi geometrik). Naikkan --runs untuk hasil lebih stabil.")

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["difficulty", "k", "block_diulang", "run", "percobaan", "waktu_detik"])
            w.writerows(mentah)
        print(f"Data mentah disimpan ke {args.csv}")


if __name__ == "__main__":
    main()