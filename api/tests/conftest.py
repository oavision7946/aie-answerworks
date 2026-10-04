import os

# Must be set before app.services.llm.openai_service is imported so an OpenAI client exists.
os.environ["OPENAI_API_KEY"] = "test-key"
