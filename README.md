# Kino-Swipe 
[![Docker Pulls](https://img.shields.io/docker/pulls/bergasha/kino-swipe)](https://hub.docker.com/r/bergasha/kino-swipe)

Always trying to decide on a movie to watch together?, This may be the fun solution you've been looking for.
Dating app style swipe right for like swipe left for nope, If you both swipe right on the 
same movie, IT'S A MATCH!! yay.



## Screenshots
<img width="320" height="640" alt="1" src="https://github.com/user-attachments/assets/4517d22b-aba7-419f-8fc1-19cf5b93af8d" />
<img width="320" height="640" alt="2" src="https://github.com/user-attachments/assets/d23fad4e-6f39-4ba8-9840-d1c8b745cd38" />
<img width="320" height="640" alt="3" src="https://github.com/user-attachments/assets/f95ae259-8a1d-4021-a344-ea0dc288f905" />
<img width="320" height="640" alt="4" src="https://github.com/user-attachments/assets/3dea1bdc-3bb4-43aa-879d-ae5b6b85b6ef" />
<img width="320" height="640" alt="5" src="https://github.com/user-attachments/assets/3f1199eb-c21e-405c-8b27-7323585efe5c" />


<div align="center">
  <video src="https://github.com/user-attachments/assets/37a2a485-ef1f-4c45-9eea-7a858323e01a" 
    width="750" 
    autoplay 
    loop 
    muted 
    playsinline>
  </video>
</div>




## Features
- **Plex Integration:** Connects directly to your server to pull random movies.
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
  

## Requirements
- **Plex Media Server**
- **Plex Auth Token**
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
    image: bergasha/kino-swipe:latest
    container_name: kino-swipe
    ports:
      - "5005:5005"
    environment:
      - PLEX_URL=https://YOUR_PLEX_IP:32400
      - PLEX_TOKEN=YOUR_PLEX_TOKEN
      - FLASK_SECRET=SomeRandomString
      - TMDB_API_KEY=your_copied_tmdb_key_here
    volumes:
      - ./data:/app/data
      - ./static:/app/static
    restart: unless-stopped
```

**Option 2 — Docker Run**
```bash
docker run -d \
  --name kino-swipe \
  -p 5005:5005 \
  -e PLEX_URL=https://YOUR_PLEX_IP:32400 \
  -e PLEX_TOKEN=YOUR_PLEX_TOKEN \
  -e FLASK_SECRET=SomeRandomString \
  -e TMDB_API_KEY=your_copied_tmdb_key_here \
  -v ./data:/app/data \
  -v ./static:/app/static \
  --restart unless-stopped \
  bergasha/kino-swipe:latest
```

<img src="https://github.com/user-attachments/assets/97e2c08b-5421-4f16-a798-acca2bb76a60" width="100"/>

"This product uses the TMDB API but is not endorsed or certified by TMDB."
