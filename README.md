# Kino-Swipe 
[![Docker Pulls](https://img.shields.io/docker/pulls/bergasha/kino-swipe)](https://hub.docker.com/r/bergasha/kino-swipe)

# This is a beta branch and may be unstable
Always trying to decide on a movie to watch together?, This may be the fun solution you've been looking for.
Dating app style swipe right for like swipe left for nope, If you both swipe right on the 
same movie, IT'S A MATCH!! yay.



## Screenshots

<p align="center">
  <img src="https://github.com/user-attachments/assets/b689d2d0-c274-4fe5-aabc-3269d05b2c4d" width="32%" />
  <img src="https://github.com/user-attachments/assets/3e01810c-7e1c-4f64-ae57-8e85332a6b77" width="32%" />
  <img src="https://github.com/user-attachments/assets/708cd372-1cf2-40ca-b275-f42ffd3b2e03" width="32%" />
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/1e4501d3-02b8-4029-9180-20431850b3e0" width="32%" />
  <img src="https://github.com/user-attachments/assets/b4c08186-6885-43ca-ab05-6a56aead1df6" width="32%" />
  <img src="https://github.com/user-attachments/assets/bdca2e04-f3ae-4fe9-bd3c-d890e49953fa" width="32%" />
</p>





## Features
- **Plex Integration:** Connects directly to your server to pull random movies.
- **Jellyfin intergration:** Jellyfin support has been added
- **Real-Time Sync:** Host a room, share a 4-digit code, and swipe with a partner instantly.
- **Visual Feedback:** Faint Red/Green "glow" overlays that react as you drag the posters left or right.
- **Select Genre:** Both sessions will stay in sync while browsing genres.
- **Add to watchlist:** Tap on each match and either open in Plex or add to watchlist for later.
- **Watch trailer** Tap on the main poster in swipedeck for full synopsis and even watch the trailer. 
- **PWA Support:** Add it to your Home Screen for a native app feel.
- **Match Notifications:** Instant alerts when you both swipe right on the same movie.
- **Match History** All matches now live in Match History until you're ready to delete them.
- **Solo Mode** Flying solo? no worries, just host session and flick the solo toggle. (Every right swipe saves to Match History) 

## Coming Soon
~~Match History: Match history folder accessible outside session for easy access.~~   
- **Jellyfin Support:** This is in Beta
  

## Requirements
**One of the following media servers:**
- Plex Media Server + Auth Token
- Jellyfin Media Server + API Key
- **TMDB key for trailers** (Not required but trailers will not work on the back of the posters)
- **HTTPS/Reverse Proxy:** To "Install" the app as a PWA on your phone so it looks like an app, you must access it over an HTTPS connection. If you access it over local ip, it will work in the browser but when added to homescreen it will just act as a shortcut not like an app.

## TMDB API instructions
Only required if you want trailers to work on the rear of the movie posters.

1. Create a free TMDB Account
If you don't already have one, you need to register on the TMDB website:

Go to themoviedb.org/signup.

Verify your email address to activate the account.

2. Access the API Settings
Once logged in:

Click on your Profile Icon in the top right corner of the screen.

Select Settings from the dropdown menu.

On the left-hand sidebar, click on API.

3. Create an API Key
Under the "Request an API Key" section, click on the link for Create.

You will be asked to choose a type of API key. Select Developer.

Accept the Terms of Use.

Fill out the form: * Type of Use: Personal/Educational.

Application Name: Kino-Swipe.

Application URL: (You can put localhost or your server's IP).

Application Summary: "An app to help find movies to watch from my Plex library with a Tinder-style swipe interface."

Submit the form.

4. Copy your API Key
You will now see two different keys. For Kino-Swipe, you need the API Key (v3 auth). It is a long string of numbers and letters.
---

## Deployment

### Option 1: Docker (Recommended)
Copy and paste this into your terminal. Replace the variables with your specific setup.

```bash
services:
  kino-swipe:
    image: bergasha/kino-swipe:beta
    container_name: kino-swipe
    restart: unless-stopped
    ports:
      - "5005:5005"
    environment:
      - PLEX_URL=http://YOUR_PLEX_IP:32400
      - PLEX_TOKEN=YOUR_PLEX_TOKEN
      - TMDB_API_KEY=YOUR_TMDB_API_KEY
      - FLASK_SECRET=ENTER_RANDOM_SECRET_KEY
      - JELLYFIN_URL=http://YOUR_JELLYFIN_IP:8096
      - JELLYFIN_API_KEY=YOUR_JELLYFIN_API_KEY
    volumes:
      - /path/to/your/config:/app/data
```

**Option 2 — Docker Run**
```bash
docker pull bergasha/kino-swipe:beta

docker run -d \
  --name kino-swipe \
  -p 5005:5005 \
  -e PLEX_URL="http://YOUR_PLEX_IP:32400" \
  -e PLEX_TOKEN="YOUR_PLEX_TOKEN" \
  -e TMDB_API_KEY="YOUR_TMDB_API_KEY" \
  -e FLASK_SECRET="ENTER_RANDOM_SECRET_KEY" \
  -e JELLYFIN_URL="http://YOUR_JELLYFIN_IP:8096" \
  -e JELLYFIN_API_KEY="YOUR_JELLYFIN_API_KEY" \
  -v /path/to/your/config:/app/data \
  --restart unless-stopped \
  bergasha/kino-swipe:beta
```

<img src="https://github.com/user-attachments/assets/97e2c08b-5421-4f16-a798-acca2bb76a60" width="100"/>

"This product uses the TMDB API but is not endorsed or certified by TMDB."
