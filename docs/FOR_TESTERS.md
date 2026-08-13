# Draft Assistant — install guide

A fantasy football draft assistant. It runs entirely on your own machine: no
account, no sign-up, and your draft never leaves your computer.

You do **not** need Python or anything else installed.

---

## Windows

1. Download **`DraftAssistant-Setup-0.1.0.exe`**.
2. Run it. Windows will show a blue **"Windows protected your PC"** box —
   that's because the app isn't signed with a (fairly expensive) certificate,
   not because anything is wrong with it.
   Click **More info**, then **Run anyway**.
3. Click through the installer. It installs just for you and doesn't ask for
   admin rights.
4. Launch **Draft Assistant** from the Start Menu.

To remove it: Settings → Apps → Draft Assistant → Uninstall.

---

## Mac

1. Download **`DraftAssistant-0.1.0-universal2.dmg`**. The one file works on
   both Apple Silicon (M1/M2/M3/M4) and older Intel Macs — you don't need to
   know which you have.

2. Open the `.dmg` and drag **Draft Assistant** onto the **Applications**
   folder.

3. The first launch is blocked, and this part is genuinely annoying — macOS
   refuses to open apps that haven't been through Apple's paid signing process:

   - Open **Applications** and double-click **Draft Assistant**.
   - You'll get *"Apple could not verify 'Draft Assistant' is free of
     malware."* Click **Done**.
   - Open **System Settings → Privacy & Security**, scroll down to the
     Security section. There'll be a line about Draft Assistant being blocked —
     click **Open Anyway**, then confirm.

   You only do this once. After that it opens normally.

---

## Using it

The app opens in its own window. Everything is local — the recommendation
engine runs on your machine, so it works with no internet connection (you only
need one to import a league from Sleeper, ESPN or Yahoo).

Your leagues, settings and draft progress are saved automatically to:

- **Windows:** `%LOCALAPPDATA%\DraftAssistant`
- **Mac:** `~/Library/Application Support/DraftAssistant`

Uninstalling leaves that folder alone, so reinstalling won't lose a draft.

---

## If something goes wrong

The most useful thing you can send back is what you were doing plus anything
that appeared on screen.

**Windows — if the window never appears:** the app needs the Microsoft Edge
WebView2 runtime, which is built into Windows 11 and most Windows 10 installs.
If it's missing, the app should fall back to opening in your normal browser. If
neither happens, try launching it from a terminal to see the error:

```bash
"%LOCALAPPDATA%\Programs\Draft Assistant\DraftAssistant.exe" --browser
```

**Mac — if it bounces and quits:** launch it from Terminal to get the error
message:

```bash
/Applications/Draft\ Assistant.app/Contents/MacOS/DraftAssistant --browser
```

**Either platform — to start completely fresh**, delete the data folder listed
above and reopen the app. It will rebuild it with the default player board.
