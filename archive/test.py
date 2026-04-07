import httpx
from openai import OpenAI

proxy = "http://127.0.0.1:7897"

http_client = httpx.Client(
    proxies=proxy,
    timeout=60
)

client = OpenAI(
    base_url="https://api.gptsapi.net/v1",
    api_key="sk-8HYde44d635a4371ebb7140ae13ffb8d296c582524fxiJYO",
    http_client=http_client
)

resp = client.responses.create(
    model="gpt-5.4",
    input="Reply only: test ok"
)

print(resp.output_text)