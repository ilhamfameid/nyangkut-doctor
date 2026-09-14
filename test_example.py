# nyangkut-doctor/test_example.py
import unittest
from typing import List


# ---------- Contoh fungsi (bukan bagian dari bot) ----------
def hitung_rata_rata(angka: List[float]) -> float:
    """Hitung rata-rata dari list angka."""
    if not angka:
        return 0.0
    return sum(angka) / len(angka)


def is_palindrome(teks: str) -> bool:
    """Cek apakah teks palindrome (dibaca sama dari depan & belakang)."""
    bersih = teks.lower().replace(" ", "")
    return bersih == bersih[::-1]


def faktorial(n: int) -> int:
    """Hitung faktorial n (n!)."""
    if n < 0:
        raise ValueError("Tidak bisa faktorial negatif")
    if n <= 1:
        return 1
    return n * faktorial(n - 1)


# ---------- Unit Tests ----------
class TestHitungRataRata(unittest.TestCase):
    def test_list_biasa(self):
        self.assertAlmostEqual(hitung_rata_rata([10, 20, 30]), 20.0)

    def test_list_satu(self):
        self.assertEqual(hitung_rata_rata([42]), 42.0)

    def test_list_kosong(self):
        self.assertEqual(hitung_rata_rata([]), 0.0)

    def test_angka_negatif(self):
        self.assertAlmostEqual(hitung_rata_rata([-5, 5]), 0.0)


class TestIsPalindrome(unittest.TestCase):
    def test_palindrome_sederhana(self):
        self.assertTrue(is_palindrome("racecar"))

    def test_palindrome_dengan_spasi(self):
        self.assertTrue(is_palindrome("nababan"))

    def test_bukan_palindrome(self):
        self.assertFalse(is_palindrome("python"))

    def test_case_insensitive(self):
        self.assertTrue(is_palindrome("Madam"))


class TestFaktorial(unittest.TestCase):
    def test_nol(self):
        self.assertEqual(faktorial(0), 1)

    def test_satu(self):
        self.assertEqual(faktorial(1), 1)

    def test_lima(self):
        self.assertEqual(faktorial(5), 120)

    def test_tiga(self):
        self.assertEqual(faktorial(3), 6)

    def test_negatif_melejit(self):
        with self.assertRaises(ValueError):
            faktorial(-3)


# ---------- Running ----------
if __name__ == "__main__":
    unittest.main()
