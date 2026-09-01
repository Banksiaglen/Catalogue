# Hosting the catalogue on GitHub — customer gets a permanent link

## What this does
Every day, GitHub itself (not your computer) logs into the wholesale
site, scrapes the catalogue, and publishes the result at a fixed URL like:

`https://YOUR-USERNAME.github.io/catalogue/`

Customers just open that link. No Python, no downloads, nothing to install.

## One-time setup

### 1. Create a GitHub account (skip if you have one)
Go to github.com and sign up — free.

### 2. Create a new repository
- Click "+" (top right) -> "New repository"
- Name it e.g. `catalogue`
- Set it to **Public** (required for free GitHub Pages) — this is fine,
  the catalogue is meant to be seen by customers anyway. Your actual
  login password is never stored in the code (see step 4).
- Click "Create repository"

### 3. Upload the files
On the repo page, click "Add file" -> "Upload files", and upload:
- `scrape.py`
- `catalogue.html`
- `catalogue.json`
- `.github/workflows/daily-scrape.yml` (you may need to create the
  `.github/workflows/` folders when uploading — GitHub's uploader lets
  you type a path like `.github/workflows/daily-scrape.yml` as the filename)

Commit the files.

### 4. Add your login credentials as secrets (NOT in the code)
- In your repo, go to **Settings -> Secrets and variables -> Actions**
- Click "New repository secret"
- Add one named `BANKSIA_USERNAME` with your login email
- Add another named `BANKSIA_PASSWORD` with your password

These are encrypted and never appear in the code or logs.

### 5. Turn on GitHub Pages
- Go to **Settings -> Pages**
- Under "Source," choose **Deploy from a branch**
- Branch: `main`, folder: `/ (root)`
- Save

GitHub will give you a URL like `https://YOUR-USERNAME.github.io/catalogue/catalogue.html` —
that's the link to send your customer.

### 6. Test it now (don't wait for tomorrow)
- Go to the **Actions** tab in your repo
- Click "Daily catalogue update" -> "Run workflow" -> "Run workflow"
- Wait ~30 seconds, refresh — it should show a green checkmark
- Open your GitHub Pages link to see the real catalogue

## Adjusting the schedule
The workflow runs at 20:00 UTC by default (edit the `cron:` line in
`.github/workflows/daily-scrape.yml` to change it — cron times are always
in UTC, so convert your local "end of day" time accordingly).

## If something goes wrong
Click the **Actions** tab -> click the failed run (red X) -> click "update-catalogue"
to see the full log. Copy any error message and send it to me.
