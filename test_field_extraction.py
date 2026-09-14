
import unittest
from typing import List, Optional, Dict, Any


# ---------- Kopi fungsi dari main.py (supaya test mandiri, nggak butuh import) ----------
_NESTED_CONTAINERS = ("overview", "valuation", "financials", "peers_comparison",
                      "historical_valuation", "quarterly", "annual")


def _extract_year_keys(d):
    """Return year-like keys (4-digit ints 1900-2100) sorted descending,
    or None if not ALL keys are year-like."""
    if not d:
        return None
    year_keys = []
    for k in d.keys():
        try:
            y = int(k)
            if 1900 <= y <= 2100:
                year_keys.append(k)
        except (ValueError, TypeError):
            return None
    if len(year_keys) != len(d):
        return None
    year_keys.sort(key=lambda k: int(k), reverse=True)
    return year_keys


def _get_field(obj, *candidates):
    if isinstance(obj, dict):
        for key in candidates:
            if key in obj and obj[key] not in (None, ""):
                return obj[key]
        for container in _NESTED_CONTAINERS:
            if container in obj:
                res = _get_field(obj[container], *candidates)
                if res not in (None, ""):
                    return res
        # Handle dict with year-like keys (e.g. {"2023": {"eps": ...}, "2024": {...}})
        year_keys = _extract_year_keys(obj)
        if year_keys:
            for yr_key in year_keys:  # newest first
                v = obj[yr_key]
                if isinstance(v, dict):
                    for key in candidates:
                        if key in v and v[key] not in (None, ""):
                            return v[key]
                    # recurse deeper into year dict for nested containers
                    for key in candidates:
                        res = _get_field(v, *candidates)
                        if res not in (None, ""):
                            return res
        # recurse into other nested dicts/lists
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and k not in _NESTED_CONTAINERS and k not in (year_keys or []):
                res = _get_field(v, *candidates)
                if res not in (None, ""):
                    return res
    elif isinstance(obj, list) and len(obj) > 0:
        if all(isinstance(item, dict) for item in obj) and any("year" in item for item in obj):
            items_sorted = sorted(obj, key=lambda x: x.get("year", 0), reverse=True)
        else:
            items_sorted = obj
        for item in items_sorted:
            res = _get_field(item, *candidates)
            if res not in (None, ""):
                return res
    return None


# ---------- Test cases ----------
class TestGetFieldBasics(unittest.TestCase):
    """Test dasar: field ada di top-level, list, nested dict biasa."""

    def test_field_di_top_level(self):
        data = {"name": "BBCA", "pb_mrq": 4.5, "sector": "Financials"}
        self.assertEqual(_get_field(data, "pb_mrq"), 4.5)
        self.assertEqual(_get_field(data, "name"), "BBCA")

    def test_field_kosong_di_top_level(self):
        data = {"name": "BBCA"}
        self.assertIsNone(_get_field(data, "pb_mrq"))

    def test_field_di_list_dikolom_standar(self):
        data = {"daily": [{"date": "2024-01-01", "close": 100},
                          {"date": "2024-01-02", "close": 105}]}
        # Karena list items punya "year" TIDAK ada, jadi urutan dipertahankan
        # Items pertama dicoba dulu
        self.assertEqual(_get_field(data, "close"), 100)
        self.assertEqual(_get_field(data, "date"), "2024-01-01")


class TestGetFieldInNestedContainers(unittest.TestCase):
    """Test: field ada di nested containers yang dikenal (valuation, financials, dst)."""

    def test_pb_mrq_di_valuation(self):
        data = {
            "overview": {"name": "BBCA"},
            "valuation": {"pb_mrq": 4.5, "pe_ttm": 12.3}
        }
        self.assertEqual(_get_field(data, "pb_mrq"), 4.5)
        self.assertEqual(_get_field(data, "pe_ttm"), 12.3)
        self.assertIsNone(_get_field(data, "total_revenue_mrq"))  # nggak ada di mana-mana

    def test_pb_di_historical_valuation(self):
        """Kalau pb_mrq nggak ada tapi pb ada di historical_valuation items,
        get_field akan kembalikan itu."""
        data = {
            "overview": {"symbol": "BBCA"},
            "valuation": {
                "historical_valuation": [
                    {"year": 2023, "pb": 3.8, "pe": 11.0},
                    {"year": 2024, "pb": 4.2, "pe": 13.0}
                ]
            }
        }
        # pb_mrq nggak ada → fallback ke pb di historical items
        self.assertEqual(_get_field(data, "pb_mrq", "pb"), 4.2)

    def test_multiple_nested_containers(self):
        """Field yang sama mungkin ada di beberapa container;
        container pertama yang dikunjungi (urut daftar) yang menang."""
        data = {
            "overview": {"pb_mrq": 5.0},
            "valuation": {"pb_mrq": 4.2}
        }
        # "overview" datang sebelum "valuation" di NESTED_CONTAINERS
        self.assertEqual(_get_field(data, "pb_mrq"), 5.0)

    def test_pbv_rasio_di_peers_comparison(self):
        data = {
            "peers_comparison": {
                "peer_1": {"pbv_ratio": 3.1}
            }
        }
        self.assertEqual(_get_field(data, "pbvRatio", "pbv_ratio"), 3.1)


class TestGetFieldHistoricalValuationEdgeCases(unittest.TestCase):
    """Test skenario khusus yang sebelumnya jadi masalah:
    pb di historical_valuation[n] bisa salah diambil sebagai PBV saat ini."""

    def test_historical_valuation_tanpa_current_pb(self):
        """Skenario: API nggak kasih pb_mrq di valuation top-level,
        cuma ada historical_valuation list."""
        data = {
            "valuation": {
                "historical_valuation": [
                    {"year": 2022, "pb": 2.5},
                    {"year": 2023, "pb": 3.1}
                ]
            }
        }
        # Nggak ada pb_mrq → akan balik ke pb dari historis (worst case)
        result = _get_field(data, "pb_mrq", "pb", "pbv")
        self.assertIsNotNone(result)  # Bukan None
        self.assertEqual(result, 3.1)  # dari year terbaru (sorted descending)

    def test_current_pb_mrq_lebih_diprioritaskan(self):
        """Kalau CURRENT PBV ada di top-level valuation,
        itu yang dikembalikan — bukan historis."""
        data = {
            "valuation": {
                "pb_mrq": 4.5,
                "historical_valuation": [
                    {"year": 2023, "pb": 3.2},
                    {"year": 2024, "pb": 3.8}
                ]
            }
        }
        self.assertEqual(_get_field(data, "pb_mrq", "pb"), 4.5)

    def test_historical_valuation_empty_list(self):
        data = {
            "valuation": {
                "historical_valuation": []
            }
        }
        self.assertIsNone(_get_field(data, "pb_mrq", "pb"))

    def test_historical_valuation_dengan_null_pb(self):
        data = {
            "valuation": {
                "historical_valuation": [
                    {"year": 2023, "pb": None},
                    {"year": 2024, "pb": 4.0}
                ]
            }
        }
        # Yang null dilewati, yang ada dikembalikan
        self.assertEqual(_get_field(data, "pb_mrq", "pb"), 4.0)

    def test_get_field_skip_null_dan_empty_string(self):
        """None dan "" sama-sama dilewati."""
        data = {"a": None, "b": "", "c": 0, "d": "ada"}
        self.assertIsNone(_get_field(data, "a", "b"))
        self.assertEqual(_get_field(data, "c"), 0)
        self.assertEqual(_get_field(data, "d"), "ada")
        self.assertIsNone(_get_field(data, "z"))


class TestGetFieldListSortingBehavior(unittest.TestCase):
    """Test perilaku sorting berdasarkan field 'year' di list items."""

    def test_list_dengan_year_dijadiin_descending(self):
        data = {
            "financials": {
                "historical_eps": [
                    {"year": 2023, "eps": 500},
                    {"year": 2024, "eps": 600}
                ]
            }
        }
        self.assertEqual(_get_field(data, "eps"), 600)  # tahun terbaru dulu

    def test_list_tanpa_year_dibiarkan_urutan_asli(self):
        data = {
            "historical_valuation": [
                {"pb": 2.0, "date": "2023-01-01"},
                {"pb": 3.5, "date": "2024-01-01"}
            ]
        }
        # "year" nggak ada di items → tidak di-sort → ambil item pertama
        self.assertEqual(_get_field(data, "pb"), 2.0)

    def test_list_mixed_dict_non_dict(self):
        """Kalau list campuran dict dan non-dict, pemeriksaan all(isinstance dict)
        gagal → items dijadikan urutan asli."""
        data = ["bukan dict", {"pb": 4.0}]
        # items[0] = string, dicoba _get_field → bukan dict/list → None
        # items[1] = dict → nemu "pb"
        self.assertEqual(_get_field(data, "pb"), 4.0)


class TestGetFieldRealisticCompanyResponse(unittest.TestCase):
    """Test dengan struktur company response yang realistic
    dari Sectors API v2."""

    def test_company_lengkap(self):
        data = {
            "overview": {
                "symbol": "BBCA",
                "name": "Bank Central Asia",
                "sector": "Financials",
                "sub_sector": "Banking"
            },
            "valuation": {
                "pb_mrq": 5.2,
                "pe_ttm": 14.1,
                "historical_valuation": [
                    {"year": 2022, "pb": 4.1, "pe": 11.5},
                    {"year": 2023, "pb": 4.8, "pe": 13.0},
                ]
            },
            "financials": {
                "historical_eps": {
                    "2023": {"eps": 950},
                    "2024": {"eps": 1100}
                },
                "historical_financials": [
                    {"year": 2023, "total_revenue": 25000000000, "net_income": 8000000000},
                    {"year": 2024, "total_revenue": 28000000000, "net_income": 9500000000}
                ]
            }
        }

        self.assertEqual(_get_field(data, "pb_mrq", "pb"), 5.2)
        self.assertEqual(_get_field(data, "pe_ttm", "pe"), 14.1)
        self.assertEqual(_get_field(data, "sector"), "Financials")
        self.assertEqual(_get_field(data, "eps", "eps_ttm"), 1100)
        self.assertEqual(_get_field(data, "total_revenue_mrq", "total_revenue"), 28000000000)

    def test_company_datanya_ripot_laboratorium(self):
        """Company response yang datanya 'riput' — banyak field kosong,
        cuma historical_valuation yang punya PBV."""
        data = {
            "overview": {
                "symbol": "XYZ",
                "name": "Emiten Ujicoba"
            },
            "valuation": {
                # pb_mrq KOSONG
                # pe_ttm KOSONG
                "historical_valuation": [
                    {"year": 2021, "pb": 1.8},
                    {"year": 2022, "pb": 2.1},
                    {"year": 2023, "pb": 2.3}
                ]
            },
            "financials": {}
        }

        # Yang dikembalikan adalah PBV historis termutakhir
        self.assertEqual(_get_field(data, "pb_mrq", "pb"), 2.3)
        self.assertIsNone(_get_field(data, "pe_ttm", "pe"))


class TestGetFieldOrderOfCandidates(unittest.TestCase):
    """Test bahwa urutan candidate keys itu penting:
    key pertama yang ketemu yang dikembalikan."""

    def test_urutan_candidates_important(self):
        data = {"pb": 3.0, "pb_mrq": 5.0}
        # Kalau "pb_mrq" dicoba duluan, hasilnya 5.0
        self.assertEqual(_get_field(data, "pb_mrq", "pb"), 5.0)
        # Kalau "pb" dicoba duluan, hasilnya 3.0
        self.assertEqual(_get_field(data, "pb", "pb_mrq"), 3.0)

    def test_candidate_list_panjang_typical_api(self):
        """Cara main.py panggil: get_field(company, "pb_mrq", "pb", "pbv", ...)."""
        data = {"pb_mrq": 4.5}
        # Versi main.py: get_field(company, "pb_mrq", "pb", "pbv", "price_to_book", "pbvRatio", "pb_ratio")
        self.assertEqual(
            _get_field(data, "pb_mrq", "pb", "pbv", "price_to_book", "pbvRatio", "pb_ratio"),
            4.5
        )


# ---------- Jalankan ----------
if __name__ == "__main__":
    unittest.main()
