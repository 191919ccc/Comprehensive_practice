import unittest

from python.common.stock_utils import calc_change_pct, detect_market, eastmoney_secid, infer_sector, sina_code, tencent_code


class StockUtilsTests(unittest.TestCase):
    def test_infer_sector(self):
        self.assertEqual(infer_sector("AAPL"), "Consumer Electronics")
        self.assertEqual(infer_sector("UNKNOWN"), "Other")

    def test_calc_change_pct(self):
        self.assertEqual(calc_change_pct(110, 100), 10.0)
        self.assertEqual(calc_change_pct(100, 0), 0.0)

    def test_market_code_helpers(self):
        self.assertEqual(detect_market("600519"), "SH")
        self.assertEqual(detect_market("000001"), "SZ")
        self.assertEqual(eastmoney_secid("AAPL", "NASDAQ"), "105.AAPL")
        self.assertEqual(sina_code("600519"), "sh600519")
        self.assertEqual(tencent_code("AAPL", "NASDAQ"), "usAAPL")


if __name__ == "__main__":
    unittest.main()
