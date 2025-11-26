import os, requests, json

url = "https://api.groq.com/openai/v1/chat/completions"
api_key = os.getenv("GROQ_API_KEY")

print("[DEBUG] Using key:", api_key[:10])

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}",
}

data = {
    "model": "llama3-8b-8192",
    "messages": [
        {"role": "system", "content": "You are Groq test assistant."},
        {"role": "user", "content": "Say hello from Groq."},
    ],
}

print("[Groq] Sending request...")
resp = requests.post(url, headers=headers, json=data)
print("[Groq] Status:", resp.status_code)
print(resp.text)
