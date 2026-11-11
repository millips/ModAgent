# ModAgent English Quick Start (v1.6.0-beta.1 / r29)

ModAgent is a Windows desktop assistant for finding, checking, installing, managing, and rolling back game Mods. Model requests go to your configured LLM provider; searches and downloads contact the relevant services. Credentials are stored locally and are excluded from exported shared collections. See [Privacy](../PRIVACY.md) for details.

## Before you begin

1. Install or unzip ModAgent, then launch it.
2. On the first-run screen, choose **English** under **Display language**.
3. Enter one OpenAI-compatible LLM API key. DeepSeek is the default recommendation. Nexus Mods and Tavily are optional and can be added later.
4. Choose a detected game, or use **Manually import game** to select its folder.

Nexus file verification may need a personal Nexus API key; downloading through its website may also need a browser login. These are separate credentials. Tavily is optional for web search. Saving a key does not verify your provider's balance or network access.

## Browser and login

ModAgent starts its dedicated Chrome, Edge, or Brave session minimized. Use the browser controls in Chat or Settings to show it for login or verification, then minimize it again. If Chrome cannot start, another detected supported browser is tried. If none is installed, Settings provides official installation links and an executable picker; Internet Explorer is not supported.

This release uses the normal shared ModAgent data profile, so upgrading does not intentionally reset API settings, chat history, or browser data. Each browser keeps its own dedicated login profile; switching from Chrome to Edge may require signing in again.

## Safe workflow

1. Create a baseline snapshot before your first change.
2. Describe the Mod you want in the chat, preferably with the game's name, the intended feature, and any exact character/IP name.
3. Review the recommendation list. ModAgent keeps original Mod names, source URLs, paths, and IDs unchanged.
4. Use **Verify details** for candidates that do not yet have a verified source.
5. Generate an installation plan. Read dependency, conflict, version, and file-placement warnings before confirming.
6. After installation, open **Mod Manager** to verify the new package and its source binding.

## Important limits

- ModAgent does not bypass logins, CAPTCHAs, paywalls, or platform download restrictions.
- Steam Workshop files are owned by Steam. ModAgent can recognize them and guide you to Steam's own enable/disable interface, but it does not directly move Workshop-managed files.
- For games without a dedicated adapter, ModAgent uses conservative generic rules. Confirm target paths and package contents before installation.
- A snapshot is a Mod rollback mechanism, not a substitute for backing up save files or personal data.
- Mod copyright, licensing, compatibility, and availability remain with the original authors and source platforms.

## Language behaviour

Changing **Settings → Display language** changes the application UI and new AI-generated explanations. Canonical Mod names, site names, version numbers, file paths, commands, IDs, and URLs intentionally remain in their original form so they stay searchable and usable.
