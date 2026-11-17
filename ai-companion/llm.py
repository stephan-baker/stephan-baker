import aiohttp


class Ollama:
    def __init__(self, cfg: dict):
        self.url = cfg["ollama_url"].rstrip("/")
        self.model = cfg["model"]
        self.options = {
            "temperature": cfg.get("temperature", 0.9),
            "top_p": cfg.get("top_p", 0.95),
            "num_ctx": cfg.get("num_ctx", 8192),
        }

    async def chat(self, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": self.options,
        }
        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(f"{self.url}/api/chat", json=payload) as r:
                r.raise_for_status()
                data = await r.json()
        return data["message"]["content"].strip()

    async def unload(self) -> None:
        """Vyhodí model z VRAM (uvolní místo pro Stable Diffusion)."""
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(
                    f"{self.url}/api/generate",
                    json={"model": self.model, "keep_alive": 0},
                )
        except aiohttp.ClientError:
            pass
