import asyncio
import io
import logging
import random
import re
import sys
from datetime import datetime
from pathlib import Path

import discord
import yaml

from images import BlockedPrompt, ComfyUI
from llm import Ollama
from memory import Memory

BASE = Path(__file__).resolve().parent
log = logging.getLogger("companion")

PHOTO_TAG = re.compile(r"\[(?:FOTO|PHOTO|IMG)\s*:\s*(.+?)\]", re.IGNORECASE | re.DOTALL)
DAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]


def load_yaml(name: str) -> dict:
    path = BASE / name
    if not path.exists():
        sys.exit(f"Chybí {name} – zkopíruj {name.replace('.yaml', '.example.yaml')} a vyplň ho.")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def build_system_prompt(persona: dict, images_on: bool, gap_text: str) -> str:
    now = datetime.now()
    parts = [
        persona["personality"].strip(),
        f"Je ti {persona['age']} let.",
        "Jak píšeš:\n" + persona["texting_style"].strip(),
        f"Teď je {DAYS[now.weekday()]} {now:%H:%M}. {gap_text}".strip(),
    ]
    if images_on:
        parts.append(
            "Když chceš poslat fotku nebo tě o ni požádá, napiš na samostatný řádek "
            "[FOTO: krátký anglický popis scény – oblečení, póza, prostředí, výraz]. "
            "Svůj vzhled nepopisuj, ten se doplní sám. Max jedna fotka na odpověď. "
            "Fotku neposílej pořád, jen když to dává smysl."
        )
    if persona.get("extra"):
        parts.append(str(persona["extra"]).strip())
    parts.append(
        "Odpovídej jen jako tahle postava, krátce, jako ve skutečném chatu. "
        "Každá samostatná zpráva na nový řádek."
    )
    return "\n\n".join(p for p in parts if p)


def gap_description(last_ts: float | None) -> str:
    if last_ts is None:
        return "Píšete si poprvé."
    hours = (datetime.now().timestamp() - last_ts) / 3600
    if hours > 24:
        return f"Naposledy jste si psali před {int(hours // 24)} dny."
    if hours > 3:
        return f"Naposledy jste si psali před {int(hours)} hodinami."
    return ""


class Companion(discord.Client):
    def __init__(self, cfg: dict, persona: dict):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        super().__init__(intents=intents)
        self.cfg = cfg
        self.persona = persona
        self.owner_id = int(cfg["discord"]["owner_id"])
        self.beh = cfg.get("behavior", {})
        self.llm = Ollama(cfg["llm"])
        self.memory = Memory(BASE / "memory.db")
        img_cfg = cfg.get("images", {})
        self.images = ComfyUI(img_cfg, persona, BASE) if img_cfg.get("enabled") else None
        self.pending: dict[int, list[str]] = {}
        self.timers: dict[int, asyncio.Task] = {}
        self.lock = asyncio.Lock()

    async def on_ready(self):
        log.info("Přihlášen jako %s – odpovídám jen ID %s v DMs", self.user, self.owner_id)

    async def on_message(self, msg: discord.Message):
        if msg.author.bot or msg.author.id != self.owner_id:
            return
        if not isinstance(msg.channel, discord.DMChannel):
            return

        text = msg.content.strip()
        if text == "!reset":
            self.memory.reset(msg.author.id)
            await msg.channel.send("(paměť smazaná)")
            return
        if text.startswith("!foto") and self.images:
            await self.send_photo(msg.channel, text[5:].strip() or "casual selfie at home")
            return
        if msg.attachments:
            text += " " + " ".join(f"[poslal přílohu: {a.filename}]" for a in msg.attachments)
        if not text:
            return

        # Debounce – víc rychlých zpráv za sebou = jedna odpověď.
        self.pending.setdefault(msg.author.id, []).append(text)
        if t := self.timers.get(msg.author.id):
            t.cancel()
        self.timers[msg.author.id] = asyncio.create_task(
            self.respond_later(msg.author.id, msg.channel)
        )

    async def respond_later(self, user_id: int, channel: discord.DMChannel):
        try:
            await asyncio.sleep(self.beh.get("debounce_seconds", 3.0))
        except asyncio.CancelledError:
            return
        async with self.lock:
            texts = self.pending.pop(user_id, [])
            if not texts:
                return
            await self.respond(user_id, channel, "\n".join(texts))

    async def respond(self, user_id: int, channel: discord.DMChannel, user_text: str):
        gap = gap_description(self.memory.last_ts(user_id))
        self.memory.add(user_id, "user", user_text)

        history = self.memory.recent(user_id, self.cfg["llm"].get("history_messages", 40))
        messages = [
            {"role": "system", "content": build_system_prompt(self.persona, bool(self.images), gap)}
        ] + [{"role": m["role"], "content": m["content"]} for m in history]

        await asyncio.sleep(random.uniform(*self.beh.get("read_delay", [1.5, 6.0])))

        try:
            async with channel.typing():
                reply = await self.llm.chat(messages)
        except Exception:
            log.exception("LLM selhal")
            return

        photo_scene = None
        if m := PHOTO_TAG.search(reply):
            photo_scene = m.group(1).strip()
        clean = PHOTO_TAG.sub("", reply).strip()
        self.memory.add(user_id, "assistant", reply)

        await self.send_human(channel, clean)
        if photo_scene and self.images:
            await self.send_photo(channel, photo_scene)

    async def send_human(self, channel: discord.DMChannel, text: str):
        if not text:
            return
        if self.beh.get("force_lowercase", True):
            text = text.lower()
        if self.beh.get("split_lines", True):
            chunks = [c.strip() for c in text.split("\n") if c.strip()]
        else:
            chunks = [text]
        limit = self.beh.get("max_messages_per_reply", 4)
        if len(chunks) > limit:
            chunks = chunks[: limit - 1] + [" ".join(chunks[limit - 1 :])]

        cps_lo, cps_hi = self.beh.get("typing_cps", [7, 14])
        for i, chunk in enumerate(chunks):
            if i:
                await asyncio.sleep(random.uniform(*self.beh.get("between_messages", [0.6, 2.2])))
            async with channel.typing():
                await asyncio.sleep(min(len(chunk) / random.uniform(cps_lo, cps_hi), 12))
            for piece in (chunk[j : j + 1900] for j in range(0, len(chunk), 1900)):
                await channel.send(piece)

    async def send_photo(self, channel: discord.DMChannel, scene: str):
        try:
            async with channel.typing():
                if self.cfg["images"].get("swap_vram", True):
                    await self.llm.unload()
                data = await self.images.generate(scene)
        except BlockedPrompt:
            log.warning("Zablokovaný prompt na fotku: %r", scene)
            return
        except Exception:
            log.exception("Generování fotky selhalo")
            await channel.send("hm fotka se nějak nenahrála 🙄 zkusím pak")
            return
        await channel.send(file=discord.File(io.BytesIO(data), filename="IMG_%04d.png" % random.randint(1000, 9999)))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_yaml("config.yaml")
    persona = load_yaml(cfg.get("persona_file", "persona.yaml"))
    if int(persona.get("age", 0)) < 21:
        sys.exit("Postava musí být dospělá (age >= 21).")
    Companion(cfg, persona).run(cfg["discord"]["token"], log_handler=None)


if __name__ == "__main__":
    main()
