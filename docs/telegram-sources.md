# Telegram sources

PriceGauger separates message collection from market interpretation. Both Telegram modes produce the same `SourceMessage` records before messages are converted into search plans.

## Public web mode

No Telegram account or API credentials are required. Supply one or more public channel names or links:

```bash
python telegram_worker.py \
  --mode web \
  --channels "https://t.me/Middle_East_Spectator,@another_public_channel" \
  --interval 60
```

This mode reads Telegram's public preview pages. It is the default onboarding mode, but it may expose less history and metadata than account mode.

Environment equivalent:

```dotenv
TELEGRAM_SOURCE_MODE=web
TELEGRAM_CHANNELS=https://t.me/Middle_East_Spectator,@another_public_channel
```

## Account mode with Telethon

Account mode uses Telegram's MTProto API through Telethon. Each user signs in with their own Telegram account. The application credentials identify the PriceGauger client; the local session identifies the user.

```dotenv
TELEGRAM_SOURCE_MODE=account
TELEGRAM_CHANNELS=https://t.me/Middle_East_Spectator,@another_channel
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=replace_me
TELEGRAM_SESSION_PATH=.data/pricegauger-telegram
```

Run one authentication and ingestion cycle:

```bash
python telegram_worker.py --mode account --once
```

On the first run, Telethon requests the user's phone number, Telegram login code, and two-step-verification password when enabled. Later runs reuse the local session.

Session files are credentials. They are excluded by `.gitignore` and must never be committed or shared.

## Accepted channel input

The following forms normalize to the same channel identifier:

```text
Middle_East_Spectator
@Middle_East_Spectator
https://t.me/Middle_East_Spectator
https://t.me/s/Middle_East_Spectator
```

Multiple channels are comma-separated. Duplicate entries are removed while preserving input order.

## Architecture

```text
TelegramWebSource ─┐
                   ├─> SourceMessage -> TelegramSearchPlan -> existing worker pipeline
TelethonSource ────┘
```

The rest of PriceGauger depends only on normalized messages. Additional adapters, such as a hosted feed or Telegram Bot API source, can therefore be added without changing market-state processing.
