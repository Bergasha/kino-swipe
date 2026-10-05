        if ('serviceWorker' in navigator) navigator.serviceWorker.register("/sw.js");

        let movieStack = [];
        let swipeHistory = [];
        let globalCurrentX = 0;
        let serverMachineId = null;
        let currentGenre = "All";
        let isHistoryView = false;
        let isSoloMode = false;
        let lastSeenMatchTs = null;
        let matchTimeoutToken = null;

        const PLEX_NEON_PALETTE = [
            { color: '#b967ff', dim: '#5a2d8a', off: '#251140' },
            { color: '#ff3131', dim: '#8a0606', off: '#330000' },
            { color: '#39ff14', dim: '#0f7a08', off: '#052e02' },
            { color: '#ff2fa0', dim: '#8a1055', off: '#330018' },
            { color: '#ff8c00', dim: '#7a3c00', off: '#331900' },
        ];
        const BLOOM_PALETTE = ['140, 90, 255', '255, 60, 60', '40, 220, 120', '255, 60, 160', '255, 140, 0', '0, 160, 255', '0, 210, 200', '229, 160, 13'];
        (function pickBlooms() {
            const a = Math.floor(Math.random() * BLOOM_PALETTE.length);
            let b = Math.floor(Math.random() * BLOOM_PALETTE.length);
            while (b === a) b = Math.floor(Math.random() * BLOOM_PALETTE.length);
            document.documentElement.style.setProperty('--bloom-a-rgb', BLOOM_PALETTE[a]);
            document.documentElement.style.setProperty('--bloom-b-rgb', BLOOM_PALETTE[b]);
        })();

        function startNeonFlicker() {
            if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
            const variants = ['a', 'b', 'c'];
            const run = () => {
                document.querySelectorAll('.main-title').forEach(t => {
                    if (t.offsetParent === null) return;
                    t.classList.remove('flicker');
                    void t.offsetWidth;
                    t.dataset.flick = variants[Math.floor(Math.random() * variants.length)];
                    t.classList.add('flicker');
                });
                setTimeout(run, 3500 + Math.random() * 9000);
            };
            setTimeout(run, 1200 + Math.random() * 2500);
        }

        let plexNeonPick = null;
        function getPlexNeonPick() {
            if (!plexNeonPick) {
                plexNeonPick = PLEX_NEON_PALETTE[Math.floor(Math.random() * PLEX_NEON_PALETTE.length)];
            }
            return plexNeonPick;
        }

        function showToast(msg) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.classList.add('show');
            setTimeout(() => t.classList.remove('show'), 2800);
        }

        function getBackend() { return localStorage.getItem('backend') || 'plex'; }
        async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
            const controller = new AbortController();
            const id = setTimeout(() => controller.abort(), timeoutMs);
            try {
                return await fetch(url, { ...options, signal: controller.signal });
            } finally {
                clearTimeout(id);
            }
        }
        function escapeHtml(str) {
            if (str === null || str === undefined) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }
        function getAuthToken() { return localStorage.getItem(getBackend() === 'jellyfin' ? 'jf_token' : 'plex_token'); }
        function getUserId() { return localStorage.getItem(getBackend() === 'jellyfin' ? 'jf_user_id' : 'plex_id'); }
        function getMoviesHeaders() {
            const headers = { 'X-Backend': getBackend() };
            if (getBackend() === 'jellyfin') {
                headers['X-Jellyfin-Token'] = getAuthToken();
                headers['X-Jellyfin-User-ID'] = getUserId();
            } else {
                headers['X-Plex-Token'] = getAuthToken();
                headers['X-Plex-User-ID'] = getUserId();
            }
            return headers;
        }

        function openProfileSwitcher() {
            document.getElementById('main-menu').classList.add('hidden');
            showPlexProfilePicker();
        }

        async function showPlexProfilePicker() {
            const token = localStorage.getItem('plex_token');
            if (!token) return;
            try {
                const res = await fetch('/auth/plex-home-users', {
                    headers: { 'X-Plex-Token': token }
                });
                const data = await res.json();
                const users = data.users || [];
                if (users.length <= 1) {
                    await finishPlexLogin();
                    return;
                }
                const list = document.getElementById('plex-profile-list');
                list.innerHTML = '';
                users.forEach(u => {
                    const btn = document.createElement('button');
                    btn.className = 'plex-profile-btn';
                    btn.innerHTML = `
                        <img class="plex-profile-avatar" src="${escapeHtml(u.thumb || '/static/sad.png')}" onerror="this.src='/static/sad.png'">
                        <div>
                            <div class="plex-profile-name">${escapeHtml(u.title)}</div>
                            ${u.restricted ? '<div class="plex-profile-restricted">🔒 Restricted</div>' : ''}
                        </div>`;
                    btn.onclick = () => doSwitchUser(u.id);
                    list.appendChild(btn);
                });
                document.getElementById('login-section').classList.add('hidden');
                document.getElementById('plex-profile-modal').classList.remove('hidden');
            } catch (e) {
                console.error('Could not fetch Plex home users', e);
                await finishPlexLogin();
            }
        }

        async function doSwitchUser(userId) {
            const token = localStorage.getItem('plex_token');
            try {
                const res = await fetch('/auth/plex-switch-user', {
                    method: 'POST',
                    headers: { 'X-Plex-Token': token, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ userId })
                });
                if (res.ok) {
                    const data = await res.json();
                    localStorage.setItem('plex_token', data.authToken);
                    document.getElementById('plex-profile-modal').classList.add('hidden');
                    await finishPlexLogin();
                } else {
                    console.error('Switch user failed');
                    await finishPlexLogin();
                }
            } catch (e) {
                console.error('Switch user error', e);
                await finishPlexLogin();
            }
        }

        async function skipProfileSelect() {
            document.getElementById('plex-profile-modal').classList.add('hidden');
            await finishPlexLogin();
        }

        async function checkHomeUsersCountAsync(token) {
            if (!token || getBackend() !== 'plex') return;
            setTimeout(async () => {
                try {
                    const res = await fetch('/auth/plex-home-users', { headers: { 'X-Plex-Token': token } });
                    const data = await res.json();
                    const users = data.users || [];
                    if (users.length > 1) {
                        document.getElementById('switch-profile-btn').classList.remove('hidden');
                    } else {
                        document.getElementById('switch-profile-btn').classList.add('hidden');
                    }
                } catch (e) {
                    console.error('Could not verify home users count in background:', e);
                }
            }, 50);
        }

        async function finishPlexLogin() {
            document.getElementById('login-section').classList.add('hidden');
            document.getElementById('plex-profile-modal').classList.add('hidden');
            document.getElementById('main-menu').classList.remove('hidden');
            updateUIColors(getBackend());
            loadGenres();

            await fetchAndStorePlexId();
            await fetchServerInfo();
            
            const token = localStorage.getItem('plex_token');
            await checkHomeUsersCountAsync(token);
            await checkHomescreenSyncAsync();
        }

        async function fetchAndStorePlexId() {
            const token = localStorage.getItem('plex_token');
            if (!token) return;
            try {
                const res = await fetchWithTimeout(`https://plex.tv/api/v2/user?X-Plex-Token=${token}`, { headers: { 'Accept': 'application/json' } });
                const data = await res.json();
                if (data.id) localStorage.setItem('plex_id', String(data.id));
            } catch (e) { console.error("Could not fetch Plex ID", e); }
        }

        async function fetchServerInfo() {
            if (serverMachineId) return serverMachineId;
            try {
                const response = await fetchWithTimeout('/server-info', {
                    headers: { 'X-Backend': getBackend() }
                });
                if (response.ok) {
                    const data = await response.json();
                    serverMachineId = data.backend === 'plex' ? data.machineIdentifier : data.name;
                    updateUIColors(getBackend());
                    return serverMachineId;
                }
            } catch (e) { console.error("Could not fetch server info", e); }
            return null;
        }

        function updateUIColors(backend) {
            const palette = backend === 'jellyfin'
                ? { accent: '#00a4dc', hi: '#46d4ff', lo: '#0080c4', rgb: '0, 164, 220' }
                : { accent: '#e5a00d', hi: '#ffc63d', lo: '#d98200', rgb: '229, 160, 13' };
            const root = document.documentElement.style;
            root.setProperty('--accent', palette.accent);
            root.setProperty('--accent-hi', palette.hi);
            root.setProperty('--accent-lo', palette.lo);
            root.setProperty('--accent-rgb', palette.rgb);
            document.documentElement.dataset.backend = backend;

            document.getElementById('switch-profile-btn').style.display = backend === 'jellyfin' ? 'none' : '';

            const homescreenLabel = document.getElementById('homescreen-toggle-label');
            if (homescreenLabel) homescreenLabel.textContent = backend === 'jellyfin' ? 'Show matches in Jellyfin favourites' : 'Show matches on Plex home screen';

            const brandTitle = document.querySelector('#branding .main-title');
            if (brandTitle) {
                if (backend === 'jellyfin') {
                    brandTitle.style.setProperty('--neon-color', '#00a4dc');
                    brandTitle.style.setProperty('--neon-dim', '#003a4d');
                    brandTitle.style.setProperty('--neon-off', '#001a26');
                } else {
                    const pick = getPlexNeonPick();
                    brandTitle.style.setProperty('--neon-color', pick.color);
                    brandTitle.style.setProperty('--neon-dim', pick.dim);
                    brandTitle.style.setProperty('--neon-off', pick.off);
                }
            }
        }

        async function applyAvailableBackends() {
            try {
                const res = await fetchWithTimeout('/auth/available-backends');
                const data = await res.json();
                const plexBtn = document.getElementById('login-btn');
                const jfBtn = document.getElementById('jf-login-btn');
                const divider = document.getElementById('login-or-divider');
                if (data.plex === false) plexBtn.classList.add('hidden');
                if (data.jellyfin === false) jfBtn.classList.add('hidden');
                if (data.plex === false || data.jellyfin === false) divider.classList.add('hidden');
            } catch (e) { console.error('Could not check available backends', e); }
        }

        async function loginWithPlex() {
            const btn = document.getElementById('login-btn');
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = 'Connecting…';
            try {
                const resp = await fetchWithTimeout("/auth/plex-url");
                const data = await resp.json();
                if (data.auth_url) {
                    window.location.href = data.auth_url;
                } else {
                    showToast(data.error || "Could not reach Plex, try again");
                }
            } catch (e) {
                console.error('Plex login init failed', e);
                showToast("Could not reach Plex, try again");
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }

        function toggleJfModal() { document.getElementById('jellyfin-modal').classList.toggle('hidden'); }

        async function loginWithJellyfin() {
            const username = document.getElementById('jf-username').value;
            const password = document.getElementById('jf-password').value;
            const res = await fetch('/auth/jellyfin-login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            const data = await res.json();
            if (res.ok) {
                localStorage.setItem('jf_token', data.accessToken);
                localStorage.setItem('jf_user_id', data.userId);
                localStorage.setItem('backend', 'jellyfin');
                location.reload();
            } else showToast(data.error || "Wrong username or password");
        }

        function confirmQuit() {
            document.getElementById('quit-modal').classList.remove('hidden');
        }

        async function doQuit() {
            await fetch('/room/quit', { method: 'POST' });
            localStorage.removeItem('active_room');
            isSoloMode = false;
            if (sseRetryTimer) { clearTimeout(sseRetryTimer); sseRetryTimer = null; }
            if (sseSource) { sseSource.close(); sseSource = null; }
            location.reload();
        }

        function toggleGenreModal() { document.getElementById('genre-modal').classList.toggle('hidden'); }

        async function selectGenre(genre) {
            document.querySelectorAll('.genre-item').forEach(el => {
                if(el.innerText === genre || (genre === 'All' && el.innerText === 'All Movies')) el.classList.add('active');
                else el.classList.remove('active');
            });
            toggleGenreModal();
            const url = genre === 'All' ? '/movies?genre=All' : `/movies?genre=${encodeURIComponent(genre)}`;
            const res = await fetch(url, { headers: getMoviesHeaders() });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                alert(`Unable to reach server: ${err.error || res.status}`);
                return;
            }
            movieStack = await res.json();
            currentGenre = genre;
            document.getElementById('genre-pill').innerText = genre === 'All' ? 'Genres ▾' : genre + ' ▾';
            swipeHistory = [];
            renderInitialDeck();
        }

        async function addToWatchlist(event, id) {
            event.stopPropagation();
            const btn = event.currentTarget;
            const originalText = btn.innerText;
            btn.innerText = "ADDING...";
            btn.disabled = true;
            
            const headers = { "Content-Type": "application/json" };
            if (getBackend() === 'jellyfin') {
                headers["X-Jellyfin-Token"] = getAuthToken();
                headers["X-Jellyfin-User-ID"] = getUserId();
            } else {
                headers["X-Plex-Token"] = getAuthToken();
            }

            try {
                const res = await fetch("/watchlist/add", {
                    method: "POST",
                    headers: headers,
                    body: JSON.stringify({ movie_id: id })
                });
                if (res.ok) {
                    btn.innerText = "ADDED";
                    btn.classList.add('added');
                } else {
                    btn.innerText = "FAILED";
                    setTimeout(() => { btn.innerText = originalText; btn.disabled = false; }, 2000);
                }
            } catch (err) { btn.innerText = "ERROR"; }
        }

        async function activateSoloMode() {
            const res = await fetch('/room/go-solo', { method: 'POST' });
            if (res.ok) {
                isSoloMode = true;
                loadMovies(true);
            }
        }

        async function handleSoloToggle(checkbox) {
            document.getElementById('solo-toggle-track').classList.toggle('on', checkbox.checked);
            if (checkbox.checked) await activateSoloMode();
        }

        async function handleHomescreenToggle(checkbox) {
            const enabled = checkbox.checked;
            document.getElementById('homescreen-toggle-track').classList.toggle('on', enabled);
            try {
                const headers = getMoviesHeaders();
                headers['Content-Type'] = 'application/json';
                await fetch('/homescreen/toggle', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ enabled })
                });
            } catch (e) { console.error('Could not update homescreen sync setting:', e); }
        }

        async function checkHomescreenSyncAsync() {
            try {
                const res = await fetch('/homescreen/status', { headers: getMoviesHeaders() });
                const data = await res.json();
                if (!data.available) return;
                document.getElementById('homescreen-toggle-row').classList.remove('hidden');
                document.getElementById('homescreen-toggle').checked = !!data.enabled;
                document.getElementById('homescreen-toggle-track').classList.toggle('on', !!data.enabled);
            } catch (e) { console.error('Could not check homescreen sync status:', e); }
        }

        const loadMovies = async (solo = false) => {
            isSoloMode = solo;
            lastSeenMatchTs = Date.now() / 1000;
            const res = await fetch('/movies', { headers: getMoviesHeaders() });
            movieStack = await res.json();
            document.getElementById('branding').classList.add('hidden');
            document.getElementById('controls-area').classList.add('hidden');
            document.getElementById('game-area').classList.remove('hidden');
            document.getElementById('matches-pill').classList.remove('hidden');
            document.getElementById('quit-pill').classList.remove('hidden');
            document.getElementById('action-dock').classList.remove('hidden');
            document.getElementById('undo-btn').classList.remove('hidden');

            if (isSoloMode) {
                document.getElementById('matches-pill').innerText = 'Shortlist';
                document.getElementById('solo-badge').classList.remove('hidden');
            } else {
                document.getElementById('matches-pill').innerText = 'Matches';
                document.getElementById('solo-badge').classList.add('hidden');
            }

            renderInitialDeck();
            startPolling();
        };

        async function openMatches(asHistory) {
            isHistoryView = asHistory;
            document.getElementById('delete-all-btn').classList.toggle('hidden', !asHistory);
            const serverId = await fetchServerInfo();
            if (!serverId) return;
            const label = isSoloMode && !asHistory ? "Your Shortlist" : asHistory ? "Match History" : "Your Matches";
            document.getElementById('modal-title').innerText = label;
            
            const headers = getMoviesHeaders();
            const url = asHistory ? '/matches?view=history' : '/matches';
            const res = await fetch(url, { headers: headers });
            const data = await res.json();
            const list = document.getElementById('matches-list');
            const emptyLabel = asHistory ? 'history' : isSoloMode ? 'shortlist' : 'matches';
            list.innerHTML = data.length ? '' : `<p class="empty">No ${emptyLabel} yet</p>`;

            data.forEach((m, i) => {
                const card = document.createElement('div');
                card.className = 'mini-poster';
                card.style.animationDelay = `${Math.min(i, 12) * 45}ms`;
                let openBtn;
                if (getBackend() === 'plex') {
                    const plexLink = `https://app.plex.tv/desktop/#!/server/${serverId}/details?key=%2Flibrary%2Fmetadata%2F${m.movie_id}`;
                    openBtn = `<a href="${plexLink}" class="plex-open-btn" target="_blank" rel="noopener noreferrer">OPEN IN PLEX</a>`;
                } else {
                    openBtn = ``;
                }

                card.innerHTML = `
                    <div class="mini-inner">
                        <div class="mini-front">
                            <img src="${escapeHtml(m.thumb)}" alt="${escapeHtml(m.title)}">
                            <div class="mini-label">${escapeHtml(m.title)}</div>
                        </div>
                        <div class="mini-back">
                            <div class="mini-title-text">${escapeHtml(m.title)}</div>
                            <div class="stats-row">
                                ${m.rating ? `<span class="stat-badge rating">${escapeHtml(m.rating)}</span>` : ''}
                                ${m.duration ? `<span class="stat-badge">${escapeHtml(m.duration)}</span>` : ''}
                                ${m.year ? `<span class="stat-badge">${escapeHtml(m.year)}</span>` : ''}
                            </div>
                            ${openBtn}
                            <button class="mini-btn" onclick="addToWatchlist(event, '${m.movie_id}')">SAVE TO WATCHLIST</button>
                            <button class="mini-btn danger" onclick="deleteMatch(event, '${m.movie_id}')">DELETE</button>
                        </div>
                    </div>
                `;
                card.onclick = (e) => { if (!e.target.closest('a') && !e.target.closest('button')) card.classList.toggle('flipped'); };
                list.appendChild(card);
            });
            document.getElementById('matches-modal').classList.remove('hidden');
        }

        let pendingDeleteId = null;

        function closeDeleteModal() {
            document.getElementById('delete-modal').classList.add('hidden');
            document.getElementById('delete-modal-overlay').classList.add('hidden');
            pendingDeleteId = null;
        }

        async function deleteMatch(event, id) {
            event.stopPropagation();
            pendingDeleteId = id;
            document.querySelector('#delete-modal h3').innerText = 'Delete Match?';
            document.querySelector('#delete-modal p').innerText = 'This will remove the match from your list.';
            document.getElementById('delete-modal-overlay').classList.remove('hidden');
            document.getElementById('delete-modal').classList.remove('hidden');
            document.getElementById('delete-confirm-btn').onclick = async () => {
                const headers = getMoviesHeaders();
                headers["Content-Type"] = "application/json";

                await fetch("/matches/delete", { 
                    method: "POST", 
                    headers: headers, 
                    body: JSON.stringify({ movie_id: pendingDeleteId }) 
                });
                closeDeleteModal();
                openMatches(isHistoryView);
            };
        }

        function deleteAllMatches() {
            document.querySelector('#delete-modal h3').innerText = 'Delete All History?';
            document.querySelector('#delete-modal p').innerText = 'This will permanently remove every match in your history.';
            document.getElementById('delete-modal-overlay').classList.remove('hidden');
            document.getElementById('delete-modal').classList.remove('hidden');
            document.getElementById('delete-confirm-btn').onclick = async () => {
                const headers = getMoviesHeaders();
                headers["Content-Type"] = "application/json";

                await fetch("/matches/delete-all", {
                    method: "POST",
                    headers: headers,
                    body: JSON.stringify({ view: 'history' })
                });
                closeDeleteModal();
                openMatches(isHistoryView);
            };
        }

        function _bindStaticHandlers() {
            const undoBtn = document.getElementById('undo-btn');
            if (undoBtn) undoBtn.onclick = async () => {
                if (swipeHistory.length === 0) {
                    undoBtn.classList.remove('undo-shake');
                    void undoBtn.offsetWidth;
                    undoBtn.classList.add('undo-shake');
                    setTimeout(() => undoBtn.classList.remove('undo-shake'), 400);
                    return;
                }
                const lastMovie = swipeHistory.pop();
                const headers = getMoviesHeaders();
                headers['Content-Type'] = 'application/json';

                await fetch('/undo', { 
                    method: 'POST', 
                    headers: headers, 
                    body: JSON.stringify({ movie_id: lastMovie.id }) 
                });
                movieStack.unshift(lastMovie);
                renderInitialDeck();
            };
            const matchesPill = document.getElementById('matches-pill');
            if (matchesPill) matchesPill.onclick = () => openMatches(false);
            const nopeBtn = document.getElementById('nope-btn');
            if (nopeBtn) nopeBtn.onclick = () => { if (navigator.vibrate) navigator.vibrate(10); swipeTopCard('left'); };
            const likeBtn = document.getElementById('like-btn');
            if (likeBtn) likeBtn.onclick = () => { if (navigator.vibrate) navigator.vibrate(10); swipeTopCard('right'); };
        }

        const END_QUOTES = [
            { quote: "That's a wrap.", attr: "— Every director, ever" },
            { quote: "I'll be back.", attr: "— The Terminator (1984)" },
            { quote: "There's no place like home.", attr: "— The Wizard of Oz (1939)" },
            { quote: "You've seen everything. Time to just pick one.", attr: "— Common sense" },
            { quote: "After all, tomorrow is another day.", attr: "— Gone with the Wind (1939)" },
            { quote: "Roads? Where we're going, we don't need roads.", attr: "— Back to the Future (1985)" },
            { quote: "He touched the butt.", attr: "— Finding Nemo (2003)" },
        ];

        function renderInitialDeck() {
            const deck = document.getElementById('swipe-deck');
            deck.innerHTML = '';
            if (movieStack.length === 0) {
                const q = END_QUOTES[Math.floor(Math.random() * END_QUOTES.length)];
                const el = document.createElement('div');
                el.id = 'end-of-deck';
                el.innerHTML = `
                    <div class="end-quote">"${q.quote}"</div>
                    <div class="end-attr">${q.attr}</div>
                    <div class="end-sub">You've swiped everything in this genre.</div>
                    <button class="menu-btn end-btn" onclick="toggleGenreModal()">Try Another Genre</button>
                `;
                deck.appendChild(el);
                return;
            }
            movieStack.slice(0, 5).reverse().forEach(m => deck.appendChild(createCard(m)));
            initDrag(deck.lastElementChild);
        }

        function createCard(m) {
            const c = document.createElement('div');
            c.className = 'movie-card';
            const star = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.9L12 17.8 5.8 21.1 7 14.2 2 9.3l6.9-1z"/></svg>';
            c.dataset.id = m.id; c.dataset.title = m.title; c.dataset.thumb = m.thumb;
            c.innerHTML = `
                <div class="card-inner">
                    <div class="card-front">
                        <img src="${escapeHtml(m.thumb)}" draggable="false" ondragstart="return false;">
                        <div class="card-meta">
                            <h3>${escapeHtml(m.title)}</h3>
                            <div class="meta-chips">
                                ${m.rating ? `<span class="chip rating">${star}${escapeHtml(m.rating)}</span>` : ''}
                                ${m.year ? `<span class="chip">${escapeHtml(m.year)}</span>` : ''}
                                ${m.duration ? `<span class="chip">${escapeHtml(m.duration)}</span>` : ''}
                            </div>
                        </div>
                        <div class="stamp-yes">👍</div>
                        <div class="stamp-no">👎</div>
                    </div>
                    <div class="card-back">
                        <div class="movie-title">${escapeHtml(m.title)}</div>
                        <div class="stats-row">
                            ${m.rating ? `<span class="stat-badge rating">${star}${escapeHtml(m.rating)}</span>` : ''}
                            ${m.duration ? `<span class="stat-badge">${escapeHtml(m.duration)}</span>` : ''}
                            ${m.year ? `<span class="stat-badge">${escapeHtml(m.year)}</span>` : ''}
                        </div>
                        <div id="vid-${m.id}" class="trailer-box"></div>
                        <button class="trailer-btn" onclick="watchTrailer(event, '${m.id}', this)">WATCH TRAILER</button>
                        <div class="back-content"><p>${escapeHtml(m.summary) || 'No description available.'}</p></div>
                        <div id="cast-${m.id}" class="cast-row"></div>
                        <div class="flip-hint">Tap to flip back</div>
                    </div>
                </div>
            `;
            c.addEventListener('click', async (e) => {
                if (!e.target.classList.contains('trailer-btn') && Math.abs(globalCurrentX) < 5) {
                    c.classList.toggle('flipped');
                    if (c.classList.contains('flipped')) {
                        const castEl = document.getElementById(`cast-${m.id}`);
                        if (castEl && castEl.dataset.loaded !== 'true') {
                            castEl.dataset.loaded = 'true';
                            castEl.innerHTML = '<span style="font-size:0.7rem;color:#6e6e84;">Loading cast...</span>';
                            try {
                                const res = await fetch(`/cast/${m.id}`, { headers: { 'X-Backend': getBackend() } });
                                const data = await res.json();
                                if (data.cast && data.cast.length > 0) {
                                    castEl.innerHTML = data.cast.map(actor => `
                                        <div class="cast-member">
                                            ${actor.profile_path
                                                ? `<img src="${escapeHtml(actor.profile_path)}" alt="${escapeHtml(actor.name)}" loading="lazy">`
                                                : `<div class="no-photo">🎬</div>`}
                                            <span>${escapeHtml(actor.name)}</span>
                                        </div>
                                    `).join('');
                                } else {
                                    castEl.innerHTML = '';
                                }
                            } catch(err) {
                                castEl.innerHTML = '';
                            }
                        }
                    }
                }
            });
            return c;
        }

        async function watchTrailer(event, id, btn) {
            event.stopPropagation();
            const container = document.getElementById(`vid-${id}`);
            const backContent = container.closest('.card-back').querySelector('.back-content');
            if (container.style.display === 'block') {
                container.style.display = 'none'; container.innerHTML = ''; btn.innerText = 'WATCH TRAILER';
                backContent.style.display = '';
            } else {
                btn.innerText = 'LOADING...';
                const res = await fetch(`/get-trailer/${id}`, { headers: { 'X-Backend': getBackend() } });
                const data = await res.json();
                if (data.youtube_key) {
                    backContent.style.display = 'none';
                    container.style.display = 'block';
                    container.innerHTML = `<iframe src="https://www.youtube.com/embed/${data.youtube_key}?autoplay=1&playsinline=1" allow="autoplay; encrypted-media" allowfullscreen></iframe>`;
                    btn.innerText = 'CLOSE TRAILER';
                } else btn.innerText = 'TRAILER NOT FOUND';
            }
        }

        function launchConfetti() {
            if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
            const host = document.getElementById('confetti');
            const style = getComputedStyle(document.documentElement);
            const colors = [style.getPropertyValue('--accent-hi').trim(), style.getPropertyValue('--accent-lo').trim(), '#ffffff', '#ff4fa3', '#7c5cff', '#3ddc97'];
            for (let i = 0; i < 46; i++) {
                const p = document.createElement('i');
                p.style.background = colors[i % colors.length];
                p.style.setProperty('--x', `${(Math.random() * 2 - 1) * 48}vw`);
                p.style.setProperty('--y', `${55 + Math.random() * 55}vh`);
                p.style.setProperty('--r', `${Math.random() * 900 - 450}deg`);
                p.style.setProperty('--d', `${1.5 + Math.random() * 1.1}s`);
                p.style.width = `${6 + Math.random() * 6}px`;
                p.style.height = `${10 + Math.random() * 8}px`;
                p.addEventListener('animationend', () => p.remove());
                host.appendChild(p);
            }
        }

        function presentMatchNotification(data) {
            if (navigator.vibrate) navigator.vibrate([30, 50, 30]);

            if (data.solo) {
                showSoloAddStamp();
                return;
            }

            launchConfetti();

            if (matchTimeoutToken) clearTimeout(matchTimeoutToken);

            const _titleEl = document.getElementById('matched-movie-title');
            _titleEl.innerText = data.title;
            const _len = (data.title || '').length;
            _titleEl.style.fontSize = _len <= 15 ? '1.6rem' : _len <= 30 ? '1.25rem' : _len <= 45 ? '1rem' : '0.82rem';
            document.getElementById('match-popup-poster').src = data.thumb || '';

            const heading = document.getElementById('match-heading');
            heading.innerText = "IT'S A MATCH!";
            document.getElementById('match-solo-label').classList.add('hidden');

            const banner = document.getElementById('match-overlay');
            banner.classList.add('show');
            
            matchTimeoutToken = setTimeout(() => {
                triggerDismissMatch();
            }, 2000);
        }

        function showSoloAddStamp() {
            const stamp = document.getElementById('solo-add-stamp');
            if (getBackend() === 'jellyfin') stamp.classList.add('jf');
            else stamp.classList.remove('jf');
            stamp.innerText = 'Added to Shortlist';

            const tilt = (Math.random() * 20 - 10).toFixed(1);
            stamp.style.setProperty('--tilt', `${tilt}deg`);

            stamp.classList.add('show');
            clearTimeout(stamp._hideTimer);
            stamp._hideTimer = setTimeout(() => {
                stamp.classList.remove('show');
            }, 1000);
        }

        function triggerDismissMatch() {
            const banner = document.getElementById('match-overlay');
            banner.classList.remove('show');
            if (matchTimeoutToken) {
                clearTimeout(matchTimeoutToken);
                matchTimeoutToken = null;
            }
        }

        function initMatchOverlaySwipeDismiss() {
            const banner = document.getElementById('match-overlay');
            if (!banner) return;
            let startY = 0, currentY = 0, isDragging = false;

            const onMove = (e) => {
                if (!isDragging) return;
                const y = e.clientY || (e.touches && e.touches[0].clientY);
                currentY = Math.min(0, y - startY);
                banner.style.transition = 'none';
                banner.style.transform = `translateY(${currentY}px)`;
                banner.style.opacity = String(Math.max(0.3, 1 - Math.abs(currentY) / 150));
            };

            const onEnd = () => {
                if (!isDragging) return;
                isDragging = false;
                window.removeEventListener('pointermove', onMove);
                window.removeEventListener('pointerup', onEnd);
                banner.style.transition = '';
                banner.style.opacity = '';
                banner.style.transform = '';

                if (Math.abs(currentY) > 60) {
                    triggerDismissMatch();
                } else {
                    matchTimeoutToken = setTimeout(() => {
                        triggerDismissMatch();
                    }, 3000);
                }
                currentY = 0;
            };

            banner.addEventListener('pointerdown', (e) => {
                isDragging = true;
                startY = e.clientY || (e.touches && e.touches[0].clientY);
                if (matchTimeoutToken) { clearTimeout(matchTimeoutToken); matchTimeoutToken = null; }
                banner.setPointerCapture(e.pointerId);
                window.addEventListener('pointermove', onMove);
                window.addEventListener('pointerup', onEnd);
            });
        }

        function initDrag(card) {
            if (!card) return;
            let startX, isDragging = false;
            globalCurrentX = 0;
            const glowLeft = document.getElementById('glow-left');
            const glowRight = document.getElementById('glow-right');
            const onMove = (e) => {
                if (!isDragging) return;
                const x = e.clientX || (e.touches && e.touches[0].clientX);
                globalCurrentX = x - startX;
                if (card.classList.contains('flipped')) return;
                card.style.transition = 'none';
                card.style.transform = `translate(${globalCurrentX}px, ${Math.abs(globalCurrentX)/10}px) rotate(${globalCurrentX / 10}deg)`;
            
                const cardInner = card.querySelector('.card-inner');
                if (cardInner) {
                    if (globalCurrentX > 10) {
                        const intensity = Math.min(Math.abs(globalCurrentX) / 30, 1);
                        cardInner.style.boxShadow = `0 0 ${20 + intensity * 60}px rgba(76, 175, 80, ${0.4 + intensity * 0.6})`;
                        card.querySelector('.stamp-yes').style.opacity = intensity;
                        card.querySelector('.stamp-no').style.opacity = 0;
                    } else if (globalCurrentX < -10) {
                        const intensity = Math.min(Math.abs(globalCurrentX) / 30, 1);
                        cardInner.style.boxShadow = `0 0 ${20 + intensity * 60}px rgba(211, 47, 47, ${0.4 + intensity * 0.6})`;
                        card.querySelector('.stamp-no').style.opacity = intensity;
                        card.querySelector('.stamp-yes').style.opacity = 0;
                    } else {
                        cardInner.style.boxShadow = '';
                        card.querySelector('.stamp-yes').style.opacity = 0;
                        card.querySelector('.stamp-no').style.opacity = 0;
                    }
                }
            };
            const onEnd = async () => {
                if (!isDragging) return; isDragging = false;
        
                window.removeEventListener('pointermove', onMove);
                window.removeEventListener('pointerup', onEnd);
                
                const cardInner = card.querySelector('.card-inner');
                if (cardInner) {
                    cardInner.style.boxShadow = '';
                    const yes = card.querySelector('.stamp-yes');
                    const no = card.querySelector('.stamp-no');
                    if (yes) yes.style.opacity = 0;
                    if (no) no.style.opacity = 0;
                }

                if (card.classList.contains('flipped')) { globalCurrentX = 0; return; }
                card.style.transition = 'transform 0.4s ease, opacity 0.3s ease';
                if (Math.abs(globalCurrentX) > 120) {
                    const dir = globalCurrentX > 0 ? 'right' : 'left';
                    card.dataset.swiping = '1';
                    card.style.transform = `translate(${globalCurrentX > 0 ? 1000 : -1000}px, 0px) rotate(${globalCurrentX / 5}deg)`;
                    card.style.opacity = '0';
                    const movieData = movieStack[0]; swipeHistory.push(movieData);
                    
                    const swipeHeaders = getMoviesHeaders();
                    swipeHeaders['Content-Type'] = 'application/json';

                    fetch('/room/swipe', { 
                        method: 'POST', 
                        headers: swipeHeaders, 
                        body: JSON.stringify({ 
                            movie_id: card.dataset.id, title: card.dataset.title, thumb: card.dataset.thumb, direction: dir,
                            plex_id: getUserId()
                        }) 
                    })
                    .then(r => r.json()).then(data => { 
                        if (data.match) { 
                            presentMatchNotification(data);
                        } 
                    });
                    setTimeout(() => { card.remove(); movieStack.shift(); if (movieStack[4]) document.getElementById('swipe-deck').prepend(createCard(movieStack[4])); initDrag(document.getElementById('swipe-deck').lastElementChild); globalCurrentX = 0; if (movieStack.length === 0) renderInitialDeck(); }, 300);
                } else { card.style.transform = ''; setTimeout(() => globalCurrentX = 0, 50); }
            };
            card.onpointerdown = (e) => {
                if (e.target.tagName === 'BUTTON') return;
                isDragging = true; startX = e.clientX || (e.touches && e.touches[0].clientX);
                card.setPointerCapture(e.pointerId);
                window.addEventListener('pointermove', onMove); window.addEventListener('pointerup', onEnd);
            };
        }

        document.getElementById('host-btn').onclick = async () => {
            const btn = document.getElementById('host-btn');
            btn.disabled = true;
            btn.innerHTML = '<span class="btn-spinner"></span>Creating...';
            
            const createHeaders = getMoviesHeaders();
            const res = await fetch('/room/create', {
                method: 'POST',
                headers: createHeaders
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                alert(`Unable to reach server: ${err.error || res.status}`);
                btn.disabled = false;
                btn.innerHTML = 'Host Session';
                return;
            }
            const data = await res.json();
            localStorage.setItem('active_room', 'hosting');
            document.getElementById('session-display').innerText = data.pairing_code;
            btn.classList.add('hidden');
            btn.disabled = false;
            btn.innerHTML = 'Host Session';
            document.getElementById('session-info').classList.remove('hidden');
            startPolling();
        };

        async function joinRoom() {
            const code = document.getElementById('join-code').value;
            const btn = document.getElementById('join-btn');
            btn.disabled = true;
            btn.innerHTML = '<span class="btn-spinner"></span>Joining...';
            
            const joinHeaders = getMoviesHeaders();
            joinHeaders['Content-Type'] = 'application/json';

            const res = await fetch('/room/join', { 
                method: 'POST', 
                headers: joinHeaders, 
                body: JSON.stringify({ code }) 
            });
            if (res.ok) { localStorage.setItem('active_room', 'joined'); loadMovies(false); }
            else {
                const data = await res.json();
                showToast(data.error || "Invalid Code");
                btn.disabled = false;
                btn.innerHTML = 'Join Session';
            }
        }

        async function loadGenres() {
            try {
                const res = await fetch('/genres', {
                    headers: { 'X-Backend': getBackend() }
                });
                const genres = await res.json();
                const list = document.getElementById('genre-list');
                list.querySelectorAll('.genre-dynamic').forEach(el => el.remove());
                genres.forEach(g => {
                    const el = document.createElement('div');
                    el.className = 'genre-item genre-dynamic';
                    el.textContent = g;
                    el.onclick = () => selectGenre(g);
                    list.appendChild(el);
                });
            } catch (e) { console.error('Could not load genres', e); }
        }

        let sseSource = null;
        let sseRetryDelay = 2000;
        let sseRetryTimer = null;

        const startPolling = () => {
            if (sseSource) { sseSource.close(); sseSource = null; }
            if (sseRetryTimer) { clearTimeout(sseRetryTimer); sseRetryTimer = null; }
            sseSource = new EventSource('/room/stream');
            sseSource.onopen = () => { sseRetryDelay = 2000; };
            sseSource.onerror = () => {
                sseSource.close(); sseSource = null;
                if (localStorage.getItem('active_room')) {
                    sseRetryTimer = setTimeout(() => {
                        sseRetryDelay = Math.min(sseRetryDelay * 2, 30000);
                        startPolling();
                    }, sseRetryDelay);
                }
            };
            sseSource.onmessage = async (event) => {
                const d = JSON.parse(event.data);
                if (d.closed) {
                    sseSource.close();
                    localStorage.removeItem('active_room');
                    location.reload();
                    return;
                }
                if (d.genre && d.genre !== currentGenre) {
                    currentGenre = d.genre;
                    document.getElementById('genre-pill').innerText = currentGenre === 'All' ? 'Genres ▾' : currentGenre + ' ▾';
                    const movieRes = await fetch('/movies', { headers: getMoviesHeaders() });
                    movieStack = await movieRes.json(); swipeHistory = []; renderInitialDeck();
                }
                if (d.ready && document.getElementById('game-area').classList.contains('hidden')) {
                    loadMovies(d.solo || false);
                }
                if (d.last_match && !isSoloMode) {
                    const matchTs = d.last_match.ts;
                    if (matchTs > lastSeenMatchTs) {
                        lastSeenMatchTs = matchTs;
                        presentMatchNotification(d.last_match);
                    }
                }
            };
        };

        function swipeTopCard(dir) {
            const card = document.querySelector('.movie-card:last-child');
            if (!card || card.classList.contains('flipped') || card.dataset.swiping) return;
            card.dataset.swiping = '1';

            const stamp = card.querySelector(dir === 'right' ? '.stamp-yes' : '.stamp-no');
            if (stamp) stamp.style.opacity = 1;
            const inner = card.querySelector('.card-inner');
            if (inner) inner.style.boxShadow = dir === 'right' ? '0 0 80px rgba(61, 220, 151, 0.9)' : '0 0 80px rgba(255, 77, 109, 0.9)';

            const moveX = dir === 'right' ? 1000 : -1000;
            card.style.transition = 'transform 0.45s ease, opacity 0.35s ease';
            card.style.transform = `translate(${moveX}px, 40px) rotate(${dir === 'right' ? 22 : -22}deg)`;
            card.style.opacity = '0';

            const movieData = movieStack[0];
            swipeHistory.push(movieData);

            const swipeHeaders = getMoviesHeaders();
            swipeHeaders['Content-Type'] = 'application/json';

            fetch('/room/swipe', {
                method: 'POST',
                headers: swipeHeaders,
                body: JSON.stringify({
                    movie_id: card.dataset.id,
                    title: card.dataset.title,
                    thumb: card.dataset.thumb,
                    direction: dir,
                    plex_id: getUserId()
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.match) {
                    presentMatchNotification(data);
                }
            });

            setTimeout(() => {
                card.remove();
                movieStack.shift();
                if (movieStack[4]) {
                    document.getElementById('swipe-deck').prepend(createCard(movieStack[4]));
                }
                initDrag(document.getElementById('swipe-deck').lastElementChild);
                if (movieStack.length === 0) renderInitialDeck();
            }, 300);
        }

        document.addEventListener('keydown', async (e) => {
            const card = document.querySelector('.movie-card:last-child');
            if (!card) return;

            if (e.key === 'ArrowDown') {
                card.classList.toggle('flipped');
                return;
            }

            if (e.key === 'ArrowUp') {
                if (swipeHistory.length === 0) return;
                const lastMovie = swipeHistory.pop();
                const headers = getMoviesHeaders();
                headers['Content-Type'] = 'application/json';

                await fetch('/undo', {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify({ movie_id: lastMovie.id })
                });
                movieStack.unshift(lastMovie);
                renderInitialDeck();
                return;
            }

            if (e.key === 'ArrowRight') swipeTopCard('right');
            if (e.key === 'ArrowLeft') swipeTopCard('left');
        });

        const boot = async () => {
            startNeonFlicker();
            _bindStaticHandlers();
            initMatchOverlaySwipeDismiss();

            const params = new URLSearchParams(window.location.search);
            const pinId = params.get('pin_id');
            if (pinId) {
                try {
                    const pendingPin = await fetchWithTimeout(`/auth/check-returned-pin?pin_id=${pinId}`);
                    const result = await pendingPin.json();
                    if (result.authToken) {
                        localStorage.setItem("plex_token", result.authToken);
                        localStorage.setItem("backend", "plex");
                        window.history.replaceState({}, '', '/');
                        await finishPlexLogin();
                        if (localStorage.getItem('active_room')) startPolling();
                        return;
                    }
                } catch (e) {
                    console.error('Pin check failed or timed out', e);
                    window.history.replaceState({}, '', '/');
                }
            }

            const backend = getBackend();
            const token = getAuthToken();

            if (token) {
                // Reveal the UI immediately using cached data; refresh details in the background.
                updateUIColors(backend);
                document.getElementById('login-section').classList.add('hidden');
                document.getElementById('main-menu').classList.remove('hidden');
                loadGenres();
                if (localStorage.getItem('active_room')) startPolling();

                if (backend === 'plex') fetchAndStorePlexId();
                fetchServerInfo();
                if (backend === 'plex') checkHomeUsersCountAsync(token);
                checkHomescreenSyncAsync();
            } else {
                document.getElementById('login-section').classList.remove('hidden');
                applyAvailableBackends();
            }
        };

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', boot);
        } else {
            boot();
        }

