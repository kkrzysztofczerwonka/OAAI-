import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

print("Available models:")
for m in genai.list_models():
    if 'embedContent' in m.supported_generation_methods:
        print(f"Embedding model: {m.name}")
    if 'generateContent' in m.supported_generation_methods:
        print(f"Generative model: {m.name}")
