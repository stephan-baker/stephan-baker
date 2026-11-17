# AI companion – lokální Discord bot

Lokální chat bot s personou, pamětí a lidským stylem psaní (zpoždění, „píše…“, víc krátkých zpráv). Umí posílat fotky generované přes ComfyUI. Odpovídá **jen tobě** (podle `owner_id`) a jen v DMs.

## 1. Co nainstalovat (Windows, 3080 Ti)

1. **Python 3.11+**: https://python.org (při instalaci zaškrtni „Add to PATH“)
2. **Ollama**: https://ollama.com, potom v terminálu:
   ```
   ollama pull mistral-nemo:12b
   ```
   Můžeš si stáhnout i jiný model (uncensored/RP finetuny jsou na ollama.com/library nebo HuggingFace jako GGUF). Pro 12 GB VRAM ber 8B–12B v Q4/Q5.
3. **ComfyUI** (na fotky): https://github.com/comfyanonymous/ComfyUI (portable verze pro Windows). Do `ComfyUI/models/checkpoints/` dej SDXL checkpoint, který chceš (třeba z CivitAI), a spusť ho. Poběží na `http://127.0.0.1:8188`.

## 2. Discord bot

1. https://discord.com/developers/applications → New Application → Bot → **Reset Token** a token si zkopíruj
2. V záložce Bot zapni **Message Content Intent**
3. OAuth2 → URL Generator → scope `bot` → otevři URL a přidej bota na nějaký svůj server (musíte mít společný server, aby ti mohl psát do DMs)
4. Napiš botovi do DMs

## 3. Nastavení a spuštění

```
cd ai-companion
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.yaml config.yaml
copy persona.example.yaml persona.yaml
```

Do `config.yaml` doplň token, svoje `owner_id` a název checkpointu. V `persona.yaml` si nastav postavu, osobnost a styl.

```
python bot.py
```

## Použití

- Normálně jí píšeš. Když pošleš víc zpráv rychle za sebou, odpoví na všechny naráz.
- Fotku pošle sama, když to dává smysl nebo když si o ni řekneš.
- `!foto <anglický popis scény>` pošle fotku napřímo
- `!reset` smaže paměť

## VRAM

12 GB nestačí, aby LLM a SDXL běžely v paměti naráz. S `swap_vram: true` se proto před generováním fotky LLM vyhodí z VRAM a po vygenerování se uvolní ComfyUI. Fotka pak trvá zhruba 10–25 s a další odpověď má pár sekund navíc na načtení modelu. Jestli chceš rychlejší fotky, dej menší LLM (8B) a `swap_vram: false`.

## Pravidla

Postava musí být vymyšlená dospělá osoba. Nedělej ji podle reálného člověka a nepoužívej LoRA nebo fotky skutečných lidí. Bot odmítne start s `age < 21` a fotky s prompty, které naznačují nezletilost, se nevygenerují.
