# Putting the QB board online (auto-updating)

This gets your board hosted at a public link that **rebuilds itself every morning**
(and any time you push fresh ADP), all free, using GitHub Pages + GitHub Actions.

You only do steps 1–4 once. After that it runs on its own.

---

## Step 1 — Put this project on GitHub

**Easiest: GitHub Desktop (a free app, no command line)**

1. Install GitHub Desktop from desktop.github.com and sign in.
2. **File → Add local repository →** choose `C:\Users\hunte\Projects\nfl-fantasy-models`.
   - If it says "this isn't a Git repository," click the link to **create/initialize** one here.
3. You'll see all your files listed as changes. Type a summary like `QB model + board`
   and click **Commit to main**.
4. Click **Publish repository** (top bar).
   - Name it `nfl-fantasy-models`.
   - **Uncheck "Keep this code private"** — a public repo gives you free Pages *and*
     unlimited Actions minutes. (The board is just public fantasy data.)
   - Click **Publish repository**.

*(Prefer the command line? In the project folder: `git init` · `git add .` ·
`git commit -m "QB model + board"` · `git branch -M main`, then create the repo on
github.com and follow its "push an existing repository" lines.)*

---

## Step 2 — Add the workflow file (on the GitHub website)

The build recipe lives in `.github/workflows/deploy.yml`. That folder is protected, so
it can't be dropped onto your machine automatically — you add it on the website, which
is the normal way anyhow.

1. Open your new repo on **github.com**.
2. Click **Add file → Create new file**.
3. In the name box, type exactly: `.github/workflows/deploy.yml`
   *(the slashes automatically create the folders.)*
4. Open the **`deploy.yml`** file I sent you in the chat, copy **everything** in it,
   and paste it into the big editor box.
5. Click **Commit changes**.

---

## Step 3 — Turn on GitHub Pages

1. In the repo, go to **Settings → Pages**.
2. Under **Build and deployment**, set **Source: GitHub Actions**.
   (No other boxes to fill — just pick that from the dropdown.)

---

## Step 4 — Run it the first time

1. Go to the **Actions** tab.
2. Click **Build & deploy QB board** on the left, then **Run workflow → Run workflow**.
3. It takes about **10 minutes** the first time (it downloads a few seasons of data).
   A green check means it worked.

---

## Step 5 — Your live link

- **Settings → Pages** shows the URL, usually:
  `https://<your-username>.github.io/nfl-fantasy-models/`
- The **board is the home page**. If the backtest page built, it's at `…/backtest.html`.

Share that link, open it on your phone, whatever you like.

---

## Keeping it fresh

- **Automatic:** it rebuilds every morning (~11:23 UTC). Player stats and rosters/depth
  charts refresh from nflverse on their own — no action from you.
- **ADP is still manual** (there's no free ADP feed). When you want fresh ADP: edit
  `data/adp.csv`, then in GitHub Desktop **Commit to main** and **Push**. The site
  rebuilds in ~10 minutes.
- **Change the schedule:** edit the `cron:` line in `deploy.yml` (on GitHub, or locally
  then push). It's in UTC.

---

## If a step turns red

Open the failed run in the **Actions** tab, click the red step to expand its log, and
send me the last ~30 lines. The build also writes a traceback to
`outputs/current_map_debug.txt` if the model itself errors. Most first-run issues are
quick fixes (a dependency or a data quirk) — send me the log and I'll sort it.
