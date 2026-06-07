# Instruction prefixes used by qwen3-embedding for asymmetric retrieval.
# Must match the values in openviking/adapter/app/adapters/qdrant.py
# (that file is a separate service and cannot import from here).
DOC_PREFIX = "Represent this financial document passage for retrieval: "
QUERY_PREFIX = "Given a user question about a financial report, retrieve relevant passages: "

# OpenViking resource URI root for the BCTN document collection.
RESOURCES_URI = "viking://resources/bctn"

# OpenAI-compatible base URL for Google Gemini.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
