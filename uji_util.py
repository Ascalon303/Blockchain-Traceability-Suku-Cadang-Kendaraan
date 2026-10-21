# -*- coding: utf-8 -*-
"""Pembantu bersama untuk skrip uji jaringan (uji_node, uji_fork, uji_fork_2v3, uji_3node).

Menjalankan node.py sebagai proses terpisah (HTTP di 127.0.0.1) dan memberi
fungsi kecil untuk memanggil endpoint serta membaca log console node.
"""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_hasil = []


def cek(nama, kondisi, info=""):
    _hasil.append(bool(kondisi))
    print(("  [LULUS] " if kondisi else "  [GAGAL] ") + nama + (f"  ({info})" if info else ""))


def ringkasan():
    print(f"\nRingkasan: {sum(_hasil)}/{len(_hasil)} lulus")
    return 0 if all(_hasil) else 1


def http_req(port, metode, path, obj=None, timeout=10, mentah=None, header=None):
    """Panggil endpoint node. Return (status, json atau None)."""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    isi = mentah if mentah is not None else (json.dumps(obj).encode() if obj is not None else None)
    h = dict(header or {})
    if isi is not None and "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    c.request(metode, path, body=isi, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    try:
        return r.status, json.loads(data)
    except ValueError:
        return r.status, None


class Node:
    def __init__(self, nama, port, authors=(), peers=(), data_dir=None, tmp=None):
        self.nama, self.port = nama, port
        self.authors, self.peers = list(authors), list(peers)
        self.tmp = tmp or tempfile.mkdtemp(prefix=f"uji_{nama}_")
        self.data_dir = data_dir or os.path.join(self.tmp, f"data_{port}")
        self.log_path = os.path.join(self.tmp, f"{nama}.log")
        self.proc = None

    def start(self, tunggu=15.0):
        cmd = [sys.executable, "-u", os.path.join(HERE, "node.py"), "--port", str(self.port),
               "--host", "127.0.0.1", "--data-dir", self.data_dir]
        if self.authors:
            cmd += ["--authors", *self.authors]
        if self.peers:
            cmd += ["--peers", *self.peers]
        self._lf = open(self.log_path, "a")
        self.proc = subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.PIPE, stdout=self._lf,
                                     stderr=subprocess.STDOUT, text=True)
        batas = time.time() + tunggu
        while time.time() < batas:
            try:
                st, _ = http_req(self.port, "GET", "/status", timeout=2)
                if st == 200:
                    return self
            except OSError:
                time.sleep(0.2)
        raise RuntimeError(f"node {self.nama} tidak siap; lihat {self.log_path}")

    def stop(self):
        """Tutup dengan rapi (stdin ditutup -> node menyimpan state lalu keluar)."""
        if self.proc is None:
            return
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self._lf.close()
        self.proc = None

    def kill(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait()
            self._lf.close()
            self.proc = None

    def log(self):
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def req(self, metode, path, obj=None, **kw):
        return http_req(self.port, metode, path, obj, **kw)

    def status(self):
        return self.req("GET", "/status")[1]

    def buat_tx(self, sender, part_id, status, nama="Filter Oli"):
        """Buat transaksi lewat POST /transactions/create. Return (status_http, balasan)."""
        return self.req("POST", "/transactions/create", {
            "sender": sender, "part_id": part_id, "part_name": nama, "origin": "Produsen",
            "destination": "Dealer", "vehicle_id": "VH-1", "status": status})

    def tambang(self, max_tx=5):
        return self.req("POST", "/mine", {"max_tx": max_tx}, timeout=90)

    def menu(self, *baris, tunggu=1.0):
        """Kirim input ke menu interaktif node (stdin)."""
        for b in baris:
            self.proc.stdin.write(b + "\n")
        self.proc.stdin.flush()
        time.sleep(tunggu)
