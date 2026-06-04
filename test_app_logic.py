import unittest
from app import get_access_token, fetch_and_prepare_data

class TestApp(unittest.TestCase):
    def test_token(self):
        token = get_access_token()
        self.assertTrue(len(token) > 50)

    def test_data_fetch(self):
        df = fetch_and_prepare_data()
        self.assertFalse(df.empty)
        self.assertIn('Symbol', df.columns)
        self.assertIn('instrument_key', df.columns)

if __name__ == '__main__':
    unittest.main()
