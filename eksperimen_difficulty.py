"""
eksperimen_difficulty.py -- mengukur pengaruh difficulty terhadap PoW.

Untuk tiap nilai difficulty (string awalan hash, mis. "0000"), tambang beberapa
block lalu catat:
  - percobaan (attempts)  : berapa nonce yang dicoba sampai ketemu
  - waktu mining (detik)
Hasilnya dicetak sebagai tabel dan (opsional) disimpan ke CSV.

Teori: tiap karakter hex bernilai 4 bit, jadi peluang satu percobaan berhasil
= 16^-n untuk difficulty dengan n karakter "0", dan rata-rata percobaan ~ 16^n.
Menambah satu "0" ("0000" -> "00000") melipatenambelaskan rata-rata kerja.

Pemakaian:
  python eksperimen_difficulty.py
  python eksperimen_difficulty.py --difficulty 0000 00000 --runs 20 --csv hasil.csv

Peringatan: 6 karakter nol atau lebih di Python murni bisa memakan menit per block.
"""
import argparse
import csv
import statistics
import sys

import blockchain_core_traceability_suku_cadang_kendaraan as core


def satu_block(difficulty: str):
    """Tambang satu block (tanpa masuk chain) pada difficulty tertentu.
    Return (percobaan, detik)."""
    core.get_or_create_author("Produsen")
    tx = core.make_transaction("Produsen", "EXP-1", "Filter Oli", "Pabrik", "Gudang", "VH-1", "PRODUCED")
    blk = core.Block(1, [tx], core.GENESIS_HASH)   # transaksi (enkripsi acak) berbeda tiap block
    _hash, attempts, elapsed = core.mine_with_retry(blk, difficulty=difficulty)
    return attempts, elapsed


def main():
    ap = argparse.ArgumentParser(description="Eksperimen difficulty PoW")
    ap.add_argument("--difficulty", nargs="+", default=["00", "000", "0000", "00000"],
                    help='daftar difficulty (string awalan hash) yang diuji, mis. 0000 00000')
    ap.add_argument("--runs", type=int, default=10, help="jumlah block per difficulty")
    ap.add_argument("--csv", default=None, help="simpan hasil mentah ke file CSV")
    args = ap.parse_args()

    for d in args.difficulty:
        if not d or any(c not in "0123456789abcdef" for c in d):
            sys.exit(f"difficulty '{d}' harus string hex tidak kosong, mis. 0000")
        if len(d) >= 6:
            print(f"[!] '{d}': bisa sangat lama di Python (rata-rata ~{16 ** len(d):,} percobaan per block)")

    core.get_or_create_author("Produsen")
    mentah, ringkas = [], []

    print(f"Eksperimen: {args.runs} block per difficulty\n")
    for dif in args.difficulty:
        percobaan, waktu = [], []
        for n in range(1, args.runs + 1):
            a, t = satu_block(dif)
            percobaan.append(a)
            waktu.append(t)
            mentah.append((dif, n, a, round(t, 6)))
        rata_a = statistics.mean(percobaan)
        rata_t = statistics.mean(waktu)
        ringkas.append((dif, 16 ** len(dif), rata_a, statistics.median(percobaan),
                        min(percobaan), max(percobaan), rata_t, min(waktu), max(waktu),
                        sum(percobaan) / sum(waktu) if sum(waktu) else 0.0))
        print(f"  selesai difficulty {dif!r}")

    print()
    kepala = ("Difficulty", "16^n", "Percobaan rata2", "Median", "Min", "Maks",
              "Waktu rata2 (s)", "Waktu min", "Waktu maks", "Hash/detik")
    baris = [(repr(b), f"{teori:,}", f"{ra:,.0f}", f"{med:,.0f}", f"{mn:,}", f"{mx:,}",
              f"{rt:.4f}", f"{tmin:.4f}", f"{tmax:.4f}", f"{hps:,.0f}")
             for (b, teori, ra, med, mn, mx, rt, tmin, tmax, hps) in ringkas]
    lebar = [max(len(kepala[i]), *(len(r[i]) for r in baris)) for i in range(len(kepala))]
    garis = "+-" + "-+-".join("-" * w for w in lebar) + "-+"
    print(garis)
    print("| " + " | ".join(kepala[i].ljust(lebar[i]) for i in range(len(kepala))) + " |")
    print(garis)
    for r in baris:
        print("| " + " | ".join(r[i].rjust(lebar[i]) for i in range(len(kepala))) + " |")
    print(garis)

    print("\nRasio rata-rata percobaan terhadap teori 16^n (mendekati 1 = sesuai teori):")
    for (b, teori, ra, *_rest) in ringkas:
        print(f"  {b!r:>8}: {ra / teori:5.2f}")
    if len(ringkas) > 1:
        print("\nKenaikan waktu rata-rata saat difficulty bertambah (teori: x16 per tambahan satu '0'):")
        for (b0, *_a, rt0, _x, _y, _h0), (b1, *_b, rt1, _u, _v, _h1) in zip(ringkas, ringkas[1:]):
            if rt0 > 0:
                print(f"  {b0!r} -> {b1!r}: x{rt1 / rt0:,.1f} (teori x{16 ** (len(b1) - len(b0)):,})")
    print(f"\nCatatan: dengan {args.runs} block per difficulty, rata-rata masih berfluktuasi "
          f"(distribusi geometrik). Naikkan --runs untuk hasil yang lebih stabil.")

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["difficulty", "run", "percobaan", "waktu_detik"])
            w.writerows(mentah)
        print(f"Data mentah disimpan ke {args.csv}")


if __name__ == "__main__":
    main()
