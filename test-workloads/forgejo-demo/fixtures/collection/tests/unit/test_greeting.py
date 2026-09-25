"""Run from the collection root with Python's standard-library unittest."""
import unittest

from plugins.filter.greeting import FilterModule, greeting


class GreetingTests(unittest.TestCase):
    def test_default_greeting(self):
        self.assertEqual(greeting("Ada"), "Hello, Ada!")

    def test_name_whitespace(self):
        self.assertEqual(greeting("  Ada  "), "Hello, Ada!")

    def test_filter_registration(self):
        self.assertIs(FilterModule().filters()["greeting"], greeting)


if __name__ == "__main__":
    unittest.main()
