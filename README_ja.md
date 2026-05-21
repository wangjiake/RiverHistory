<p align="center">
  <img src="img/binary-wave-logo.svg" width="128" height="128" alt="River Algorithm Logo">
</p>

# River Algorithm — AI会話履歴特別版

[English](README.md) | [中文](README_zh.md)

![License: AGPL-3.0 + Commercial](https://img.shields.io/badge/License-AGPL--3.0%20%2B%20Commercial-green)
[![X (Twitter)](https://img.shields.io/badge/X-@JKRiverse-000000?logo=x&logoColor=white)](https://x.com/JKRiverse)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/ZnmFrPvXym)
[![Docs](https://img.shields.io/badge/ドキュメント-wangjiake.github.io-06b6d4?logo=readthedocs&logoColor=white)](https://wangjiake.github.io/riverse-docs/ja/)

---

**River Algorithm（河流アルゴリズム）** は、ローカル AI における個人デジタルプロフィール重み付けアルゴリズムです。

既存の AI メモリ（ChatGPT Memory、Claude Memory など）は本質的に**フラットなリスト**です：いくつかの事実を保存するだけで、時間軸も、確信度も、矛盾検出もありません。メモリはクラウドに保存され、プラットフォームが所有しており、別のサービスに移行すればすべてゼロからです。河流アルゴリズムは根本的に異なります — 会話は河のように流れ、重要な情報は泥沙のようにプロフィールとして沈殿し、複数ターンの検証を経て「推測」から「確認」へ、さらに「確立」へと段階的に昇格します。オフライン統合（Sleep）は河の自己浄化として機能し、古い情報を洗い流し、矛盾を解消し、認知をより明確にしていきます。すべてのデータはローカルに保存され、あなたが所有し、プラットフォームを横断して集約されます — AI を変えても失われません。河流アルゴリズムは成長型です：会話が増えるほどローカルデータが蓄積され、AI のあなたへの理解はより深くなります。

本プロジェクトは河流アルゴリズムの**特別版**であり、**ChatGPT / Claude / Gemini** の会話履歴から個人プロフィールを一括抽出することに特化しています — 性格、好み、経験、人間関係、人生の軌跡。AI と交わしたすべての会話は本当のあなたの一部です。このデータはかけがえのないものです。過去の会話には過去のあなたが記録されており、過去は事実です。未来は現在の上に築かれます。

[Riverse](https://github.com/wangjiake/JKRiver) メインプロジェクトと同じデータベースを共有しています。まず本プロジェクトで過去のプロフィールを構築し、その後 Riverse でリアルタイム会話を開始すれば — あなたの AI は初日からあなたを知っています。

> **ご注意：** 現在、個人プロフィール抽出に特化して訓練・微調整された LLM は存在しないため、モデルによって抽出結果に差異が生じ、ハルシネーションも避けられません。また、過去の会話は河流アルゴリズムの対話篇を通じて行われたものではないため、リアルタイムの文脈認識やマルチターン検証が欠けており、**過去のプロフィールは参考情報**であり、Riverse のリアルタイム会話で蓄積されたプロフィールほど正確ではありません。不正確な内容を見つけたら、Web ビューアで直接閉じるか拒否できます。他のデータには影響しません。[Issue](../../issues) の提出も歓迎します。抽出品質の改善を続けています。

> **費用に関する注意：** リモート LLM API（OpenAI、Anthropic など）使用時、大量のコードや非常に長いメッセージを含む会話は多くのトークンを消費します。実行前にエクスポートデータを確認し、不要なコンテンツを削除してください。ローカルモデル（Ollama）は無料です。

### 2026年5月の更新

- **マルチオーナー対応** — すべての業務テーブルに `owner_id` カラムを追加。[JKRiver](https://github.com/wangjiake/JKRiver) のファミリーモードとデータベースを共有する場合、`run.py --owner-name <名前>` で書き込み先の家族メンバーを指定できる。単一アカウント運用は従来通り。
- **`hypotheses` テーブル削除** — ライフサイクルは `user_profile.layer`（'suspected' → 'confirmed'）に統合。書き込みは `save_profile_fact()` に一本化。
- **プロンプト移動** — 多言語プロンプトは `agent/config/prompts/{zh,en,ja}.yaml` に集約。`agent.config.prompts.get_prompt` で読み込み。旧 `agent/core/sleep_prompts.py` は削除。
- **Sleep パイプライン分割** — `agent/sleep/orchestration.py` は4つのステップモジュール（`steps_extract.py` / `steps_analyze.py` / `steps_maintain.py` / `steps_output.py`）に処理を委譲。CLI エントリ `run(owner_id=...)` のシグネチャは変更なし。
- **初期化時に admin アカウント自動播種** — `setup_db.py` が `accounts` テーブルに id=1 の管理者を作成。名前は `settings.yaml.admin_name` 優先、なければ OS ユーザー（`whoami`）。冪等で再実行安全。

### 機能

- ChatGPT / Claude / Gemini からローカルにエクスポートした会話履歴をデータベースにインポート
- LLM駆動のプロフィール抽出（リモートLLM API またはローカル Ollama）
- 矛盾検出とタイムライン追跡
- 月次スナップショットビューア
- 人間関係マッピング
- ローカルWebビューア（中国語 / 英語 / 日本語）

### Docker でクイック体験

Python や PostgreSQL 不要。**[Docker ですぐに体験](https://github.com/wangjiake/JKRiver/tree/main/docker)** — デモデータ付き、OpenAI / DeepSeek / Groq 対応。

---

### 前提条件

- Python 3.11 または 3.12
- PostgreSQL
- LLM API Key（OpenAI、Anthropic など）またはローカル Ollama

### クイックスタート（ソースから）

```bash
# 1. リポジトリをクローン
git clone https://github.com/wangjiake/RiverHistory.git
cd RiverHistory

# 2. 仮想環境を作成して依存関係をインストール
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt

# 3. 設定
# settings.yaml を編集：
#   - database.user: PostgreSQL のユーザー名に変更
#     macOS Homebrew の場合はシステムユーザー名（ターミナルで whoami を実行）
#     Linux/Windows の場合は通常 postgres
#   - openai.api_key: API Key を入力（ローカル Ollama を使う場合は llm_provider を "local" に変更）

# 4. データベースを初期化
# このコマンドは本プロジェクトと Riverse メインプロジェクトの両方に必要な全テーブルを作成します。
# すでに Riverse の schema.sql を実行済みの場合、このステップはスキップできます。
python setup_db.py --db Riverse

# 5. 会話データをインポート
# エクスポートファイルを data/ に配置（詳細は data/README.md を参照）
python import_data.py --chatgpt data/ChatGPT/conversations.json
python import_data.py --claude data/Claude/conversations.json
python import_data.py --gemini "data/Gemini/マイ アクティビティ.html"
# 注意：Geminiのエクスポートファイル名は言語によって異なります。実際のファイル名に合わせてコマンドを変更してください

# 6. プロフィール抽出を実行
#    形式: python run.py <ソース> <件数> [--owner-name <名前>]
#    ソース:        chatgpt / claude / gemini / all
#    件数:          数字 = 最も古いものから N 件処理, max = 全件処理
#    --owner-name:  書き込み先の家族メンバー（accounts.name）を指定。
#                   省略可 — DB にアカウントが1つだけなら自動選択。
#                   JKRiver のファミリーモードと共有時は必須（混入防止）。
#    すべてのコマンドは会話の時系列順（古い順）に処理されます

python run.py chatgpt 50                          # ChatGPT 50件、ownerは自動選択
python run.py claude max --owner-name jk          # Claude 全件、jk アカウントに書き込み
python run.py gemini 100 --owner-name wife        # Gemini 100件、wife アカウントに書き込み
python run.py all max                              # 3ソース混合、ownerは自動選択

# 7. 結果を確認
python web.py --db Riverse
# ブラウザで http://localhost:2345 を開く

# オプション：アクセストークンでページを保護（サーバー展開時推奨）
ACCESS_TOKEN=your-secret python web.py --db Riverse
# 初回アクセス時にトークン入力画面が表示されます
```

> **注意：** `run.py` は自動的にテーブルをクリアしなくなりました。最初からやり直す場合は `python reset_db.py` を先に実行してください。インポート済みソースデータ（chatgpt/claude/gemini/demo テーブル）はそのまま保持されます。

### チャットデータがない場合：デモで体験

プロジェクトにはテストデータが含まれているため、自分のAIチャット履歴をエクスポートしなくても完全なワークフローを体験できます：

| データセット | キャラクター | 言語 | セッション数 | コマンド |
|-------------|-------------|------|-------------|---------|
| `--demo` | 林雨桐 | 中国語 | 50 組 | `python import_data.py --demo` |
| `--demo2` | 沈一帆 | 中国語 | 15 組 | `python import_data.py --demo2` |
| `--demo3` | Jake Morrison | English | 20 組 | `python import_data.py --demo3` |

> `--demo2` と `--demo3` はインポート前にdemoテーブルをクリアします。

```bash
python setup_db.py                  # データベースとテーブルを作成
python import_data.py --demo        # デモテストデータをインポート（または --demo2 / --demo3）
python run.py demo max              # 全デモ会話を処理
python web.py --db Riverse        # 抽出されたプロフィールを確認
```

### プロフィールデータのリセット

インポート済みのソースデータを保持したまま、すべての処理・プロフィールテーブルをクリアします（chatgpt/claude/gemini/demo テーブルは影響を受けません）：

```bash
python reset_db.py                  # プロフィールデータをクリア、ソースデータは保持
python reset_db.py --db mydb        # データベース名を指定
```

### 会話のエクスポート方法

| プラットフォーム | 手順 |
|------------------|------|
| ChatGPT | Settings → Data controls → Export data → `conversations.json` を解凍 |
| Claude | Settings → Account → Export Data → `conversations.json` を解凍 |
| Gemini | [Google Takeout](https://takeout.google.com/) → Gemini Apps を選択 → `Gemini Apps` フォルダを `data/` に配置 |

### LLM設定

**OpenAI API（推奨）：** `settings.yaml` で `llm_provider: "openai"` を設定し、API Keyを入力してください。

**ローカル Ollama：** [Ollama](https://ollama.ai) をインストールし、`ollama pull qwen2.5:14b` でモデルを取得、`llm_provider: "local"` に設定してください。

**プロンプト言語：** `settings.yaml` の `language` フィールドで設定。`"zh"`（中国語）、`"en"`（英語）、`"ja"`（日本語）に対応。LLMプロンプトの言語を制御します（Webインターフェースには影響しません）。

### プロジェクト構成

```
├── settings.yaml          # LLMとデータベースの設定
├── setup_db.py          # データベースとテーブルの初期化
├── import_data.py       # 会話エクスポートファイルをDBにインポート
├── run.py               # プロフィール抽出を実行（知覚 + スリープ統合）
├── web.py               # ローカルWebビューア（Flask、ポート 2345）
├── reset_db.py          # プロフィールテーブルをクリア、ソースデータは保持
├── requirements.txt     # Python依存関係
├── data/                # 会話エクスポートファイル（git-ignore済み）
│   ├── demo.json        # デモ：林雨桐（中国語、50組）
│   ├── demo2.json       # デモ：沈一帆（中国語、15組）
│   └── demo3.json       # デモ：Jake Morrison（英語、20組）
├── agent/
│   ├── perceive.py      # 知覚モジュール — ユーザー入力を分類
│   ├── config/
│   │   ├── __init__.py  # settings.yaml ローダー
│   │   ├── owner.py     # --owner-name → owner_id 解決（accounts テーブル参照）
│   │   ├── prompts.py   # 多言語プロンプトローダー
│   │   └── prompts/     # zh.yaml / en.yaml / ja.yaml プロンプトテキスト
│   ├── storage/         # データベース操作（owner_id 対応モジュラーサブパッケージ）
│   │   ├── _db.py       # 接続とヘルパー
│   │   ├── profile.py   # プロフィール事実 CRUD（旧 hypotheses モジュールを統合）
│   │   ├── observations.py, events.py, conversation.py, ...
│   │   └── parsing.py   # 履歴フォーマットパーサー（Claude/ChatGPT/Gemini）
│   ├── utils/           # LLMクライアント、embedding、clustering
│   └── sleep/           # オフライン抽出パイプライン（モジュラーサブパッケージ）
│       ├── orchestration.py  # run(owner_id) — シングル owner エントリポイント
│       ├── _pipeline_state.py # ステップ間共有 state（owner_id を保持）
│       ├── steps_extract.py  # Step 1-2: 観測 + タグ抽出
│       ├── steps_analyze.py  # Step 3-5: 分類、行動、クロス検証
│       ├── steps_maintain.py # Step 6-7: edges、有効期限、成熟度減衰
│       ├── steps_output.py   # Step 8-: user_model、軌跡、スナップショット
│       ├── extractors.py     # LLM 抽出ヘルパー
│       ├── analysis.py       # LLM 分析ヘルパー
│       ├── disputes.py       # 矛盾解決
│       └── trajectory.py     # 人生軌跡サマリー
└── templates/
    └── profile.html     # Webビューアテンプレート
```

---

## ライセンス

| ライセンス | 用途 |
|-----------|------|
| **AGPL-3.0** | オープンソース、変更は公開必須 |
| **商用ライセンス** | 連絡先：mailwangjk@gmail.com |

## お問い合わせ

- **X (Twitter):** [@JKRiverse](https://x.com/JKRiverse)
- **Discord:** [参加](https://discord.gg/ZnmFrPvXym)
- **Email:** mailwangjk@gmail.com
