<p align="center">
  <img src="img/binary-wave-logo.svg" width="128" height="128" alt="River Algorithm Logo">
</p>

# River Algorithm — AI Chat History Edition

[中文](README_zh.md) | [日本語](README_ja.md)

![License: AGPL-3.0 + Commercial](https://img.shields.io/badge/License-AGPL--3.0%20%2B%20Commercial-green)
[![X (Twitter)](https://img.shields.io/badge/X-@JKRiverse-000000?logo=x&logoColor=white)](https://x.com/JKRiverse)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/ZnmFrPvXym)
[![Docs](https://img.shields.io/badge/Docs-wangjiake.github.io-06b6d4?logo=readthedocs&logoColor=white)](https://wangjiake.github.io/riverse-docs/)

---

**River Algorithm** is a personal digital profile weighting algorithm for local AI systems.

Existing AI memory systems (ChatGPT Memory, Claude Memory, etc.) are essentially **flat lists**: a handful of facts with no temporal dimension, no confidence levels, no contradiction detection. Memories live in the cloud, owned by the platform — switch providers and you start from zero. The River Algorithm is fundamentally different — conversations flow like water, key information settles like sediment into profiles, progressively upgrading from "suspected" to "confirmed" to "established" through multi-turn verification. Offline consolidation (Sleep) acts as the river's self-purification: washing away outdated information, resolving contradictions, making cognition clearer over time. All data is stored locally, owned by you, aggregated across platforms — never lost when you switch AI providers. The River Algorithm is designed to grow: the more you talk, the more local data accumulates, and the deeper the AI understands you.

This project is a **special edition** of the River Algorithm, focused on batch-extracting personal profiles from your **ChatGPT / Claude / Gemini** conversation history — personality, preferences, experiences, relationships, life trajectory. Every conversation you've had with AI is a piece of the real you. This data is invaluable: past conversations record who you were, and the past is fact. The future builds on the present.

Shares the same database with the [Riverse](https://github.com/wangjiake/JKRiver) main project. Use this project to populate your historical profile first, then start real-time conversations with Riverse — your AI knows you from day one.

> **Note:** No LLM today is specifically trained or fine-tuned for personal profile extraction, so results will vary across models — some hallucinations are inevitable. Also, since historical conversations were not conducted through the River Algorithm's conversation module, they lack real-time context awareness and multi-turn verification — **historical profiles are for reference only** and are less accurate than profiles built through live Riverse conversations. If you spot anything inaccurate, you can close or reject it directly in the web viewer without affecting other data. Feel free to open an [Issue](../../issues) — I'm continuously improving extraction quality.

> **Cost warning:** When using a remote LLM API (OpenAI, Anthropic, etc.), conversations with lots of code or very long messages can consume significant tokens. Review and clean your export data before running. Local models (Ollama) are free.

### Features

- Import your locally exported ChatGPT / Claude / Gemini conversation history into the database
- LLM-powered profile extraction (remote LLM API or local Ollama)
- Contradiction detection & timeline tracking
- Monthly snapshot viewer
- Relationship mapping
- Local web viewer (Chinese / English / Japanese)

### Quick Try with Docker

Don't want to install Python or PostgreSQL? **[Run with Docker](https://github.com/wangjiake/Riverse-Docker)** — includes demo data, supports OpenAI / DeepSeek / Groq.

---

### Prerequisites

- Python 3.11 or 3.12
- PostgreSQL
- LLM API Key (e.g. OpenAI, Anthropic) or local Ollama

### Quick Start (from source)

```bash
# 1. Clone the repository
git clone https://github.com/wangjiake/RiverHistory.git
cd RiverHistory

# 2. Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt

# 3. Configure
# Edit settings.yaml:
#   - database.user: change to your PostgreSQL username
#     macOS Homebrew is usually your system username (run whoami in terminal)
#     Linux/Windows is usually postgres
#   - openai.api_key: enter your API key (or set llm_provider to "local" for Ollama)

# 4. Initialize database
# This creates all tables needed for both this project and the Riverse main project.
# If you have already run Riverse's schema.sql, you can skip this step.
python setup_db.py --db Riverse

# 5. Import conversation data
# Place your export files in data/ (see data/README.md for details)
python import_data.py --chatgpt data/ChatGPT/conversations.json
python import_data.py --claude data/Claude/conversations.json
python import_data.py --gemini "data/Gemini/My Activity.html"
# Note: The Gemini export filename varies by language. Adjust the filename accordingly.

# 6. Run profile extraction
#    Format: python run.py <source> <count>
#    source: chatgpt / claude / gemini / all
#    count:  a number = process N conversations starting from the oldest
#            max     = process all conversations
#    All commands process conversations in chronological order (oldest first)

python run.py chatgpt 50       # ChatGPT only, 50 oldest conversations
python run.py claude max       # Claude only, all conversations
python run.py gemini 100       # Gemini only, 100 oldest conversations
python run.py all max           # All 3 sources merged together, sorted by time, process all (excludes demo)

# 7. View results
python web.py --db Riverse
# Open http://localhost:2345 in your browser
```

> **Note:** Each `run.py` execution automatically clears all profile tables before writing new data. Source data tables are not affected. Safe to re-run at any time.

### No Chat Data? Try the Demo

The project includes built-in test data, so you can experience the full workflow without exporting your own AI chat history:

| Dataset | Character | Language | Sessions | Command |
|---------|-----------|----------|----------|---------|
| `--demo` | Lin Yutong | Chinese | 50 | `python import_data.py --demo` |
| `--demo2` | Shen Yifan | Chinese | 15 | `python import_data.py --demo2` |
| `--demo3` | Jake Morrison | English | 20 | `python import_data.py --demo3` |

> `--demo2` and `--demo3` clear the demo table before importing.

```bash
python setup_db.py                  # Create database and tables
python import_data.py --demo        # Import demo test data (or --demo2 / --demo3)
python run.py demo max              # Process all demo conversations
python web.py --db Riverse        # View the extracted profile
```

### Reset Profile Data

Clear all processing and profile tables while keeping imported source data (chatgpt/claude/gemini/demo tables are not affected):

```bash
python reset_db.py                  # Clear profile data, keep source data
python reset_db.py --db mydb        # Specify database name
```

### Exporting Conversations

| Platform | Steps |
|----------|-------|
| ChatGPT | Settings → Data controls → Export data → Extract `conversations.json` |
| Claude | Settings → Account → Export Data → Extract `conversations.json` |
| Gemini | [Google Takeout](https://takeout.google.com/) → Select Gemini Apps → Put `Gemini Apps` folder into `data/` |

### LLM Configuration

**OpenAI API (recommended):** Set `llm_provider: "openai"` in `settings.yaml` and enter your API key.

**Local Ollama:** Install [Ollama](https://ollama.ai), pull a model with `ollama pull qwen2.5:14b`, and set `llm_provider: "local"`.

**Prompt language:** Set the `language` field in `settings.yaml`. Supported values: `"zh"` (Chinese), `"en"` (English), `"ja"` (Japanese). This controls the language of LLM prompts, not the web interface.

### Project Structure

```
├── settings.yaml          # LLM and database configuration
├── setup_db.py          # Initialize database and tables
├── import_data.py       # Import conversation exports into database
├── run.py               # Run profile extraction (perceive + sleep)
├── web.py               # Local web viewer (Flask, port 2345)
├── reset_db.py          # Clear profile tables, keep source data
├── requirements.txt     # Python dependencies
├── data/                # Conversation export files (git-ignored)
│   ├── demo.json        # Demo: Lin Yutong (Chinese, 50 sessions)
│   ├── demo2.json       # Demo: Shen Yifan (Chinese, 15 sessions)
│   └── demo3.json       # Demo: Jake Morrison (English, 20 sessions)
├── agent/
│   ├── perceive.py      # Perception module — classify user input
│   ├── config/          # Configuration loader
│   ├── storage/         # Database operations (modular subpackage)
│   │   ├── _db.py       # Connection & helpers
│   │   ├── profile.py   # Profile facts CRUD
│   │   ├── hypotheses.py # Hypothesis lifecycle
│   │   ├── observations.py, events.py, conversation.py, ...
│   │   └── parsing.py   # History format parsers (Claude/ChatGPT/Gemini)
│   ├── utils/           # LLM client
│   ├── core/
│   │   └── sleep_prompts.py  # Multilingual prompts (zh/en/ja)
│   └── sleep/           # Offline extraction pipeline (modular subpackage)
│       ├── orchestration.py  # Main run() entry point
│       ├── extractors.py     # Observation & fact extraction
│       ├── analysis.py       # Behavioral analysis & cross-verification
│       ├── disputes.py       # Contradiction resolution
│       └── trajectory.py     # Life trajectory summary
└── templates/
    └── profile.html     # Web viewer template
```

---

## License

| License | Usage |
|---------|-------|
| **AGPL-3.0** | Open source, modifications must be open-sourced |
| **Commercial** | Contact: mailwangjk@gmail.com |

## Contact

- **X (Twitter):** [@JKRiverse](https://x.com/JKRiverse)
- **Discord:** [Join](https://discord.gg/ZnmFrPvXym)
- **Email:** mailwangjk@gmail.com
