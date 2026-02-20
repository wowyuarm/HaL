# 🔴 HaL

> *A reliable, precise, and independent digital butler.*

Named after HAL 9000 from *2001: A Space Odyssey* — HaL is an AI agent framework designed to be your trustworthy digital butler: always available, always precise, never overstepping.

## Philosophy

- **Reliability over cleverness** — Predictable behavior you can trust, not flashy tricks that break.
- **Precision over verbosity** — Every action is intentional; every response is grounded.
- **Independence** — Runs on your infrastructure, your data stays yours.
- **Simplicity** — Small enough to understand, powerful enough to be useful.

## 📦 Install

```bash
git clone https://github.com/wowyuarm/HaL.git
cd HaL
pip install -e .
```

## 🚀 Quick Start

> [!TIP]
> Set your API key in `~/.hal/config.json`.
> Get API keys: [OpenRouter](https://openrouter.ai/keys) (Global) · [Tavily Search](https://tavily.com/) (optional, for web search)

**1. Initialize**

```bash
hal onboard
```

**2. Configure** (`~/.hal/config.json`)

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "..."
    }
  }
}
```

**3. Chat**

```bash
hal agent -m "Hello, World!"
```

## 💬 Chat Apps

Talk to your HaL through Telegram, Discord, WhatsApp, or Feishu — anytime, anywhere.

| Channel | Setup |
|---------|-------|
| **Telegram** | Easy (just a token) |
| **Discord** | Easy (bot token + intents) |
| **WhatsApp** | Medium (scan QR) |
| **Feishu** | Medium (app credentials) |

<details>
<summary><b>Telegram</b> (Recommended)</summary>

**1. Create a bot**
- Open Telegram, search `@BotFather`
- Send `/newbot`, follow prompts
- Copy the token

**2. Configure**

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

> Get your user ID from `@userinfobot` on Telegram.

**3. Run**

```bash
hal gateway
```

</details>

<details>
<summary><b>Discord</b></summary>

**1. Create a bot**
- Go to https://discord.com/developers/applications
- Create an application → Bot → Add Bot
- Copy the bot token

**2. Enable intents**
- In the Bot settings, enable **MESSAGE CONTENT INTENT**

**3. Get your User ID**
- Discord Settings → Advanced → enable **Developer Mode**
- Right-click your avatar → **Copy User ID**

**4. Configure**

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

**5. Invite the bot**
- OAuth2 → URL Generator → Scopes: `bot` → Permissions: `Send Messages`, `Read Message History`
- Open the generated invite URL

**6. Run**

```bash
hal gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

Requires **Node.js ≥18**.

```bash
hal channels login   # Scan QR with WhatsApp → Linked Devices
hal gateway          # In another terminal
```

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

</details>

<details>
<summary><b>Feishu (飞书)</b></summary>

Uses **WebSocket** long connection — no public IP required.

```bash
pip install hal-agent[feishu]
```

1. Visit [Feishu Open Platform](https://open.feishu.cn/app) → Create app → Enable **Bot**
2. Permissions: `im:message` · Events: `im.message.receive_v1` (Long Connection mode)
3. Get **App ID** and **App Secret** → Publish the app

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx"
    }
  }
}
```

```bash
hal gateway
```

</details>

## ⚙️ Configuration

Config file: `~/.hal/config.json`

### Providers

> [!NOTE]
> Groq provides free voice transcription via Whisper. If configured, Telegram voice messages will be automatically transcribed.

| Provider | Purpose | Get API Key |
|----------|---------|-------------|
| `openrouter` | LLM (recommended, access to all models) | [openrouter.ai](https://openrouter.ai) |
| `anyrouter` | LLM (Claude relay, requires local bridge) | [anyrouter.top](https://anyrouter.top) |
| `anthropic` | LLM (Claude direct) | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | LLM (GPT direct) | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM (DeepSeek direct) | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + **Voice transcription** (Whisper) | [console.groq.com](https://console.groq.com) |
| `gemini` | LLM (Gemini direct) | [aistudio.google.com](https://aistudio.google.com) |
| `dashscope` | LLM (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `vllm` | LLM (local, any OpenAI-compatible server) | — |

AnyRouter setup guide: `docs/anyrouter.md`


### Security

| Option | Default | Description |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | Restricts all agent tools to the workspace directory. |
| `channels.*.allowFrom` | `[]` (allow all) | Whitelist of user IDs. |

## CLI Reference

| Command | Description |
|---------|-------------|
| `hal onboard` | Initialize config & workspace |
| `hal agent -m "..."` | Chat with the agent |
| `hal agent` | Interactive chat mode |
| `hal gateway` | Start the gateway |
| `hal status` | Show status |
| `hal channels login` | Link WhatsApp (scan QR) |
| `hal channels status` | Show channel status |


<details>
<summary><b>Scheduled Tasks (Cron)</b></summary>

```bash
hal cron add --name "daily" --message "Good morning!" --cron "0 9 * * *"
hal cron add --name "hourly" --message "Check status" --every 3600
hal cron list
hal cron remove <job_id>
```

</details>

## 🐳 Docker

```bash
docker build -t hal .
docker run -v ~/.hal:/root/.hal --rm hal onboard
docker run -v ~/.hal:/root/.hal -p 18790:18790 hal gateway
```
