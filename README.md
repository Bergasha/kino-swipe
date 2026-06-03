<p align="center">
  <img src="https://github.com/user-attachments/assets/01bccced-a75b-4854-8c1d-c25674c99a5b" alt="Kino-Swipe Banner" width="600">
</p>

[![Docker Pulls](https://img.shields.io/docker/pulls/bergasha/kino-swipe)](https://hub.docker.com/r/bergasha/kino-swipe) 
[![GitHub Stars](https://img.shields.io/github/stars/Bergasha/kino-swipe?style=flat-square&logo=github&color=yellow)](https://github.com/Bergasha/kino-swipe/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)


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
- **Plex Home Users** Have kids with restricted accounts? You can now select their profile if they are a Home User to only see suitable movies.
- **Jellyfin Restricted Libraries** Also for Jellyfin users with restricted libraries will only see their movies.
- **Solo Mode:** Flying solo? Host a session and flick the solo toggle — every right swipe saves to your Match History.

---

## Requirements

**Plex**
- Plex Media Server
- Plex Auth Token

**Jellyfin**
- Jellyfin Media Server
- Jellyfin API Key

**Both**
- TMDB API Key *(optional — required for trailers and cast)*
- HTTPS/Reverse Proxy *(required to install as a PWA on your phone)*

> You only need one media server configured. Both can run side by side on the same instance — users pick which one to log into at the login screen.

---

## TMDB API Setup
Only required if you want trailers and cast to work on the rear of the movie posters.

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
    environment:
      - PLEX_URL=https://YOUR_PLEX_IP:32400        # Optional
      - PLEX_TOKEN=YOUR_PLEX_TOKEN                  # Optional
      - JELLYFIN_URL=http://YOUR_JELLYFIN_IP:8096   # Optional
      - JELLYFIN_API_KEY=YOUR_JELLYFIN_API_KEY      # Optional
      - APP_LOCALE=en                               # Optional: use de for Plex library "Filme"
      - FLASK_SECRET=SomeRandomString
      - TMDB_API_KEY=your_tmdb_key_here
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
  -e PLEX_URL=https://YOUR_PLEX_IP:32400 \          # Optional
  -e PLEX_TOKEN=YOUR_PLEX_TOKEN \                   # Optional
  -e JELLYFIN_URL=http://YOUR_JELLYFIN_IP:8096 \    # Optional
  -e JELLYFIN_API_KEY=YOUR_JELLYFIN_API_KEY \       # Optional
  -e APP_LOCALE=en \                                # Optional: use de for Plex library "Filme"
  -e FLASK_SECRET=SomeRandomString \
  -e TMDB_API_KEY=your_tmdb_key_here \
  -v ./data:/app/data \
  -v ./static:/app/static \
  --restart unless-stopped \
  bergasha/kino-swipe:latest
```

> At least Plex or Jellyfin must be configured. Both can be also set at the same time.

**Plex library locale (optional):** defaults to `en` (`Movies`). Set `APP_LOCALE=de` if your Plex movie library is named `Filme`.

---

<img src="https://github.com/user-attachments/assets/97e2c08b-5421-4f16-a798-acca2bb76a60" width="100"/>

*This product uses the TMDB API but is not endorsed or certified by TMDB.*
