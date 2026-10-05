import os

# Keep real provider keys out of tests: nothing here should ever reach a network.
for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LOCAL_LLM_API_KEY"):
    os.environ.pop(key, None)
