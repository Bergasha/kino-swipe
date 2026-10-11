<p align="center">
  <img src="https://github.com/user-attachments/assets/4e45835c-95b8-4b1f-90b3-b19ef05d95e5" alt="Kino-Swipe Banner" width="600">
</p>

[![Docker Pulls](https://img.shields.io/docker/pulls/bergasha/kino-swipe)](https://hub.docker.com/r/bergasha/kino-swipe) 
[![GitHub Stars](https://img.shields.io/github/stars/Bergasha/kino-swipe?style=flat-square&logo=github&color=yellow)](https://github.com/Bergasha/kino-swipe/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
![Unraid](https://img.shields.io/badge/Unraid-Community%20Apps-f15a2c?logo=unraid)
## This is the Beta version and may be unstable; please use the main branch unless you want bleeding edge.

Always trying to decide on a movie to watch together? This may be the fun solution you've been looking for.
Dating app style — swipe right to like, swipe left to pass. If you both swipe right on the same movie, **IT'S A MATCH!!**


**Supports Plex & Jellyfin**

---

## Screenshots

<details>
<summary>Click to view screenshots</summary>

<br>

<p align="center">
  <img src="https://github.com/user-attachments/assets/1c5eb50e-a488-4a05-8c6a-5659cf783aba" width="32%" />
  <img src="https://github.com/user-attachments/assets/042c9d4f-5d5e-4815-852f-07d929e2ef8e" width="32%" />
  <img src="https://github.com/user-attachments/assets/87f64b9e-919b-47ec-b6e4-495e587af732" width="32%" />
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/76a68e48-dc70-43a9-b637-f74287fbddce" width="32%" />
  <img src="https://github.com/user-attachments/assets/dedd8c0a-3941-401f-9177-a385660b9689" width="32%" />
  <img src="https://github.com/user-attachments/assets/3346713b-ba96-4919-9355-31f3cd19abf8" width="32%" />
  <img src="https://github.com/user-attachments/assets/37a41d5e-7c61-4b8e-a0b5-27c0df04a3bc" width="32%" />
  <img src="https://github.com/user-attachments/assets/872efa1e-43d2-4a7f-b0eb-02696e6db24a" width="32%" />
</p>

</details>

---
## Performance Note (First-Time Run)

When you click **Host Session** or select a new genre for the absolute first time, **Kino-Swipe** caches your media library locally in a SQLite database to ensure instant loading speeds later. 

* **First run / New genre:** May take **5–15 seconds** depending on the size of your Plex or Jellyfin library while it builds the initial local dataset.
* **Subsequent runs:** **Instantaneous.** The app shuffles and serves cards out of the local cache immediately.
* **Automatic Updates:** The cache automatically and silently updates in a background thread every 24 hours, meaning you will never experience that initial setup delay again after the first run.
* **Plex Homescreen Sync:** Matches on Plex homescreen are only visable to the user who made the match, All other remote or admin users will not see those matches.

---  
## Features
- **Plex & Jellyfin Integration:** Connects directly to your Plex or Jellyfin server to pull movies.
- **Coloured sessions:** Plex Yellow lets you know you're in a Plex session and Jellyfin Blue for Jellyfin.
- **Real-Time Sync:** Host a room, share a 4-digit code, and swipe with a partner instantly.
- **Visual Feedback:** Faint Red/Green glow with thumbs-up or thumbs-down overlays that react as you drag posters left or right.
- **Select Genre:** Both sessions stay in sync while browsing genres.
- **Add to Watchlist:** Tap a match to open in Plex or save to watchlist/favourites for later.
- **Watch Trailer:** Tap the poster for full synopsis, cast, and trailer via TMDB.
- **PWA Support:** Add to your Home Screen for a native app feel.
- **Match Notifications:** Instant alerts with haptic feedback when you both swipe right on the same movie.
- **Match History:** All matches saved to history until you're ready to delete them.
- **Plex-Homescreen-Sync:** Each match will automatically show on a per-users Plex Homescreen (Until deleted from Kino).
- **Plex Home Users** Have kids with restricted accounts? You can now select their profile if they are a Home User to only see suitable movies.
- **Jellyfin Restricted Libraries** Also for Jellyfin users with restricted libraries will only see their movies.
- **Solo Mode:** Flying solo? Host a session and flick the solo toggle — every right swipe saves to your Match History.

---

## Requirements

- Plex Media Server and/or Jellyfin Media Server
- A TMDB API Key *(optional, only needed for trailers and cast)*
- HTTPS/Reverse Proxy *(required to install as a PWA on your phone)*

> You only need one media server. Both can run side by side on the same instance, and users pick which one to log into at the login screen.

No tokens or API keys need to go in the container config. Everything is entered in the setup page the first time you open the app (see [First-Time Setup](#first-time-setup)).

---

## TMDB API Setup
Only required if you want trailers and cast to work on the rear of the movie posters. Paste the key into the setup page (or set `TMDB_API_KEY`).

<details>
<summary>Click to expand TMDB setup instructions</summary>

<br>

1. **Create a free TMDB account** at [themoviedb.org/signup](https://www.themoviedb.org/signup) and verify your email.

2. **Access API settings** — click your profile icon → Settings → API.

3. **Create an API Key** — click Create, select Developer, accept the Terms of Use, and fill out the form:
   - Type of Use: Personal/Educational
   - Application Name: Kino-Swipe
   - Application URL: your server IP or localhost
   - Summary: "A Tinder-style movie picker for Plex/Jellyfin."

4. **Copy your API Key (v3 auth)** — the long string of numbers and letters.

</details>

---

## Deployment

### Option 1: Docker Compose

```yaml
services:
  kino-swipe:
    image: bergasha/kino-swipe:latest
    container_name: kino-swipe
    ports:
      - "5005:5005"
    volumes:
      - ./data:/app/data
      - ./static:/app/static
    restart: unless-stopped
```

### Option 2: Docker Run

```bash
docker run -d \
  --name kino-swipe \
  -p 5005:5005 \
  -v ./data:/app/data \
  -v ./static:/app/static \
  --restart unless-stopped \
  bergasha/kino-swipe:latest
```

### Option 3: Unraid

Install **Kino Swipe** from Community Applications. Every variable is optional, so you can leave them all blank and finish the setup in the app.

> Keep `/app/data` mapped to a persistent folder. Your settings, matches and library cache are stored there.

---

## First-Time Setup

Open `http://YOUR_SERVER_IP:5005`. If nothing is configured yet you are taken straight to the setup page (it is always available later at `/setup`, or via the cog on the login screen).

1. **Sign in** as the server owner. This is how the app knows you are allowed to change settings, so there is no setup code to find in the logs.
   - **Plex:** sign in with Plex. You must be the owner of a Plex server. Your server is found automatically.
   - **Jellyfin:** enter the URL of your server and sign in as an administrator. Kino-Swipe creates its own "KinoSwipe" API key, and your password is not stored.
2. **TMDB (optional):** paste your TMDB API key to enable trailers and cast.
3. **Plex library language (optional):** choose the language your Plex movie library is named in (`Movies`, `Filme`, ...).
4. Press **Open Kino**. Friends and family just use the normal login screen, no setup needed.

Once a server is connected, the setup page is locked to its owner or admin. Use **Sign out of settings** at the bottom of the setup page to lock it again. Signing back in at `/setup` as the Plex owner or a Jellyfin admin unlocks it for 6 hours.

> **Important:** complete the setup (sign in as the server owner) **before** exposing Kino-Swipe to the internet. Until a server is connected anyone who can reach the app can open the setup page.

**Locked out or changed servers?** Start the container once with `KINO_RESET_SETUP=1`, finish the setup again, then remove the variable.

---

## Environment Variables (Optional)

Everything above can still be set through environment variables, which is handy for automated or locked-down deployments. A value set this way always wins and is shown as locked in the setup page.

| Variable | Description |
|---|---|
| `PLEX_URL` | URL of your Plex server, e.g. `https://YOUR_PLEX_IP:32400` |
| `PLEX_TOKEN` | Your Plex auth token |
| `JELLYFIN_URL` | URL of your Jellyfin server, e.g. `http://YOUR_JELLYFIN_IP:8096` |
| `JELLYFIN_API_KEY` | A Jellyfin API key |
| `TMDB_API_KEY` | TMDB API key for trailers and cast |
| `APP_LOCALE` | Plex library language, `en` (`Movies`, default) or `de` (`Filme`) |
| `FLASK_SECRET` | Session secret. Generated and stored automatically if not set |
| `KINO_RESET_SETUP` | Set to `1` for one start to clear the stored setup and admin |

If you upgrade from an older version that used these variables, nothing changes: the app is treated as already set up.

---

<img src="https://github.com/user-attachments/assets/97e2c08b-5421-4f16-a798-acca2bb76a60" width="100"/>

*This product uses the TMDB API but is not endorsed or certified by TMDB.*
