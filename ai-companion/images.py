import asyncio
import json
import random
import re
import uuid
from pathlib import Path

import aiohttp

# Pojistka: cokoliv, co naznačuje nezletilost, se nevygeneruje. Tohle neobcházej.
BLOCKED = re.compile(
    r"\b(child|children|kid|kids|minor|minors|underage|teen|teens|teenage|"
    r"teenager|young girl|little girl|schoolgirl|school girl|loli|lolita|"
    r"shota|preteen|pre-teen|juvenile|infant|toddler|baby face|petite child|"
    r"1[0-7] ?(yo|y/o|year old|years old)|[1-9] ?(yo|y/o|year old|years old)|"
    r"dítě|děti|holčička|školačka|nezletil\w*|puberťačk\w*|teenager\w*)\b",
    re.IGNORECASE,
)

ALWAYS_NEGATIVE = (
    "child, minor, teen, young-looking, childlike, loli, underage, "
    "school uniform"
)


class BlockedPrompt(Exception):
    pass


class ComfyUI:
    def __init__(self, cfg: dict, persona: dict, base_dir: Path):
        self.cfg = cfg
        self.persona = persona
        self.url = cfg["comfyui_url"].rstrip("/")
        self.workflow = json.loads(
            (base_dir / cfg.get("workflow_file", "workflow_sdxl.json")).read_text(
                encoding="utf-8"
            )
        )
        self.client_id = uuid.uuid4().hex

    def build_prompts(self, scene: str) -> tuple[str, str]:
        if BLOCKED.search(scene) or BLOCKED.search(self.persona["appearance"]):
            raise BlockedPrompt(scene)
        age = int(self.persona["age"])
        positive = ", ".join(
            p.strip()
            for p in (
                f"photo of an adult woman, {age} years old",
                self.persona["appearance"],
                scene,
                self.persona.get("photo_style", ""),
            )
            if p and p.strip()
        )
        negative = ", ".join(
            p for p in (self.persona.get("photo_negative", ""), ALWAYS_NEGATIVE) if p
        )
        return positive, negative

    def _fill(self, positive: str, negative: str) -> dict:
        seed = self.cfg.get("seed", -1)
        values = {
            "checkpoint": self.cfg["checkpoint"],
            "width": int(self.cfg.get("width", 832)),
            "height": int(self.cfg.get("height", 1216)),
            "steps": int(self.cfg.get("steps", 28)),
            "cfg": float(self.cfg.get("cfg", 6.0)),
            "sampler": self.cfg.get("sampler", "dpmpp_2m"),
            "scheduler": self.cfg.get("scheduler", "karras"),
            "seed": random.randint(0, 2**48) if seed in (-1, None) else int(seed),
            "positive": positive,
            "negative": negative,
        }

        def walk(node):
            if isinstance(node, dict):
                return {k: walk(v) for k, v in node.items()}
            if isinstance(node, list):
                return [walk(v) for v in node]
            if isinstance(node, str):
                m = re.fullmatch(r"\{\{(\w+)\}\}", node)
                if m and m.group(1) in values:
                    return values[m.group(1)]
            return node

        return walk(self.workflow)

    async def generate(self, scene: str) -> bytes:
        positive, negative = self.build_prompts(scene)
        workflow = self._fill(positive, negative)
        timeout = aiohttp.ClientTimeout(total=self.cfg.get("timeout_seconds", 180))
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(
                f"{self.url}/prompt",
                json={"prompt": workflow, "client_id": self.client_id},
            ) as r:
                if r.status != 200:
                    raise RuntimeError(f"ComfyUI /prompt {r.status}: {await r.text()}")
                prompt_id = (await r.json())["prompt_id"]

            # Čeká, až je obrázek hotový.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.cfg.get("timeout_seconds", 180)
            outputs = None
            while loop.time() < deadline:
                async with s.get(f"{self.url}/history/{prompt_id}") as r:
                    hist = await r.json()
                if prompt_id in hist:
                    entry = hist[prompt_id]
                    status = entry.get("status", {})
                    if status.get("status_str") == "error":
                        raise RuntimeError(f"ComfyUI chyba: {status}")
                    outputs = entry.get("outputs")
                    if outputs:
                        break
                await asyncio.sleep(1.0)
            if not outputs:
                raise TimeoutError("ComfyUI nestihl vygenerovat obrázek")

            img = next(
                img
                for out in outputs.values()
                for img in out.get("images", [])
            )
            params = {
                "filename": img["filename"],
                "subfolder": img.get("subfolder", ""),
                "type": img.get("type", "output"),
            }
            async with s.get(f"{self.url}/view", params=params) as r:
                r.raise_for_status()
                data = await r.read()

            if self.cfg.get("swap_vram", True):
                try:
                    await s.post(
                        f"{self.url}/free",
                        json={"unload_models": True, "free_memory": True},
                    )
                except aiohttp.ClientError:
                    pass
        return data
