# Arsip versi sebelum revisi 5

Isi folder ini adalah kode dan dokumen **revisi 4** (rantai per-lineage: satu block = satu
transaksi, `parent_id`, block ditandatangani, tanpa transaction pool). Tidak dipakai lagi oleh
proyek, disimpan agar bisa ditunjukkan dan dibandingkan.

| Berkas | Isi |
|---|---|
| `blockchain_core_versi_lineage.py` | inti revisi 4 (Block dengan `parent_id`, `sign_block`, `is_chain_valid` per lineage) |
| `node_versi_lineage.py` | node revisi 4 (HTTP, `ADD_PEER`, fork per lineage) |
| `dokumentasi_revisi4.md`, `PETUNJUK_revisi4.md`, `penjelasan_node_py_revisi4.md` | dokumen revisi 4 |

Berkas `.py` di sini mengimpor modul dengan nama biasa; untuk menjalankannya, salin
`blockchain_core_versi_lineage.py` menjadi `blockchain_core_traceability_suku_cadang_kendaraan.py`
dan `node_versi_lineage.py` menjadi `node.py` di folder terpisah.
