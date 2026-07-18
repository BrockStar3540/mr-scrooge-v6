# Security Policy

Research software, default **OANDA practice** account. Not financial advice.

## Reporting a vulnerability or a leaked secret
Please do **not** open a public issue for security problems — especially if you find a credential, token, account id, or private detail in the repo, its history, or the linked archive.

Use GitHub **private vulnerability reporting**: the **Security** tab → **Report a vulnerability**. If you spot what looks like a live API token or account id, report it privately so it can be revoked — do not post it publicly.

## Handling credentials
- Your broker keys live only in a local, gitignored `config/credentials.local.json` on your own machine. Never commit them.
- Live trading is gated behind an explicit `SCROOGE_ALLOW_LIVE=1` flag **and** a typed confirmation. The default and intended mode is **practice**.
