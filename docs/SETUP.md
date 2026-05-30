# Setup Instructions â€” NSE Earnings Monitor on GitHub Actions

## Step 1: Create a Telegram Bot
1. Open Telegram and search for **@BotFather**.
2. Send `/newbot`.
3. Follow the prompts.
4. Copy the bot token.

## Step 2: Get your Chat ID
1. Open a chat with your bot.
2. Press **Start** or send a message.
3. Open:
   `https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates`
4. Find:
   `result[0].message.chat.id`

## Step 3: Create a GitHub Repository
1. Create a new repository on GitHub.
2. Recommended: make it private.

## Step 4: Upload this project
Upload the folder contents so these paths exist:
- `.github/workflows/monitor.yml`
- `config.json`
- `requirements.txt`
- `src/...`
- `state/...`
- `docs/SETUP.md`

## Step 5: Add GitHub Secrets
Go to:
**Settings â†’ Secrets and variables â†’ Actions**

Add:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Step 6: Enable GitHub Actions
Open the **Actions** tab and enable workflows if prompted.

## Step 7: Run manually once
Open the workflow:
**NSE Earnings Monitor**
Then click:
**Run workflow**

## Step 8: Automatic schedule
The workflow is configured to run every 5 minutes.

## Notes
- Nifty 200 list is downloaded from NSE every run.
- State is stored in `state/processed_filings.json`.
- Duplicate alerts are prevented by the state file.
