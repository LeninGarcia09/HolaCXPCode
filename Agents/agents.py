from sympy import sympify
from langdetect import detect

class MathGeekAgent:
    def handle(self, query: str) -> str:
        try:
            # Only evaluate if query contains math operators and digits
            result = sympify(query)
            return f"MathGeek: The result is {result}"
        except Exception:
            return "MathGeek: Sorry, I couldn't compute that."

class EnglishAgent:
    def handle(self, query: str) -> str:
        return f"EnglishAgent: You said '{query}' in English."

class SpanishAgent:
    def handle(self, query: str) -> str:
        return f"SpanishAgent: Has dicho '{query}' en español."

class AgentRegistry:
    def __init__(self):
        self.agents = {}
    def register(self, lang, agent):
        self.agents[lang] = agent
    def get(self, lang):
        return self.agents.get(lang, None)

class PrimaryAgent:
    def __init__(self):
        self.math_agent = MathGeekAgent()
        self.registry = AgentRegistry()
        self.registry.register('en', EnglishAgent())
        self.registry.register('es', SpanishAgent())
        self.context = []

    def route(self, query: str) -> str:
        self.context.append(query)
        if self.is_math_query(query):
            return self.math_agent.handle(query)
        lang = self.detect_language(query)
        agent = self.registry.get(lang)
        if agent:
            return agent.handle(query)
        return f"No agent found for language: {lang}."

    def is_math_query(self, query: str) -> bool:
        # Improved math query detection: must contain at least one digit and one operator
        operators = set('+-*/^=()')
        has_digit = any(c.isdigit() for c in query)
        has_operator = any(c in operators for c in query)
        if has_digit and has_operator:
            try:
                sympify(query)
                return True
            except Exception:
                return False
        return False

    def detect_language(self, query: str) -> str:
        try:
            return detect(query)
        except Exception:
            return 'en'

if __name__ == "__main__":
    agent = PrimaryAgent()
    print("Welcome to the Agentic Framework. Type your query (type 'exit' or 'quit' to stop):")
    while True:
        user_input = input("> ")
        if user_input.lower() in ["exit", "quit"]:
            print("Goodbye!")
            break
        response = agent.route(user_input)
        print(response)
