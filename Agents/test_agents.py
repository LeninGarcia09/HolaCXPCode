import unittest
from agents import PrimaryAgent

class TestAgenticFramework(unittest.TestCase):
    def setUp(self):
        self.agent = PrimaryAgent()

    def test_math_query(self):
        response = self.agent.route("2 + 2")
        self.assertIn("MathGeek", response)
        self.assertIn("4", response)

    def test_english_query(self):
        response = self.agent.route("Hello, how are you?")
        self.assertIn("EnglishAgent", response)

    def test_spanish_query(self):
        response = self.agent.route("Hola, ¿cómo estás?")
        self.assertIn("SpanishAgent", response)

    def test_exit(self):
        response = self.agent.route("exit")
        self.assertIn("EnglishAgent", response)  # 'exit' is not math or Spanish

if __name__ == "__main__":
    unittest.main()
