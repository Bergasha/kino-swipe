(() => {
    const stack = document.getElementById('setup-stack');
    const tagline = document.getElementById('setup-tagline');
    const slots = {};
    const ui = { plexManual: false, plexEditing: false, plexWaiting: false, plexError: '', jfKey: false, jfEditing: false, tmdbEditing: false, jfUrl: '', jfUser: '', signinWaiting: false, signinError: '' };
    let state = { admin: false };
    let plexServers = null;
    let pendingPin = new URLSearchParams(location.search).get('plex_pin');
    if (pendingPin) history.replaceState({}, '', '/setup');

    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

    function h(tag, attrs, ...kids) {
        const el = document.createElement(tag);
        for (const [key, value] of Object.entries(attrs || {})) {
            if (value === false || value === null || value === undefined) continue;
            if (key === 'class') el.className = value;
            else el.setAttribute(key, value === true ? '' : value);
        }
        for (const kid of kids.flat()) {
            if (kid === null || kid === undefined || kid === false) continue;
            el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
        }
        return el;
    }

    let toastTimer = null;
    function toast(message, kind) {
        const el = document.getElementById('toast');
        el.textContent = message;
        el.className = kind ? `${kind} show` : 'show';
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
    }

    async function api(path, body) {
        const options = body === undefined ? {} : {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        };
        let res;
        try {
            res = await fetch('/setup/api/' + path, options);
        } catch (e) {
            throw new Error("Couldn't reach Kino-Swipe.");
        }
        let data = {};
        try { data = await res.json(); } catch (e) {}
        if (res.status === 401 && path !== 'state') {
            await loadState();
            renderAll();
            throw new Error(data.error || 'Please sign in again.');
        }
        if (!res.ok) throw new Error(data.error || `Something went wrong (${res.status}).`);
        return data;
    }

    async function loadState() {
        state = await api('state');
    }

    async function run(btn, label, fn) {
        const original = btn.textContent;
        btn.disabled = true;
        btn.replaceChildren(h('span', { class: 'btn-spinner' }), label);
        try {
            return await fn();
        } finally {
            btn.disabled = false;
            btn.textContent = original;
        }
    }

    function errorBox() {
        const el = h('div', { class: 'setup-error', role: 'alert' });
        return { el, set: message => { el.textContent = message || ''; } };
    }

    function badge(text, kind) {
        return h('span', { class: 'setup-badge' + (kind ? ' ' + kind : '') }, text);
    }

    function card(title, badgeEl, ...body) {
        return h('section', { class: 'glass-card setup-card' },
            h('div', { class: 'setup-head' }, h('h2', null, title), badgeEl),
            ...body);
    }

    function note(...kids) {
        return h('p', { class: 'setup-note' }, ...kids);
    }

    function field(label, input) {
        return h('label', { class: 'field' }, h('span', null, label), input);
    }

    function input(attrs) {
        return h('input', Object.assign({ autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false' }, attrs));
    }

    function button(label, cls, onClick) {
        const el = h('button', { class: 'menu-btn ' + cls, type: 'button' }, label);
        el.addEventListener('click', () => onClick(el));
        return el;
    }

    function linkButton(label, onClick) {
        const el = h('button', { class: 'setup-link', type: 'button' }, label);
        el.addEventListener('click', onClick);
        return el;
    }

    function actions(...buttons) {
        return h('div', { class: 'setup-actions' }, ...buttons);
    }

    const factories = {};

    function mount(name) {
        const el = factories[name]();
        if (slots[name] && slots[name].isConnected) {
            el.style.animation = 'none';
            slots[name].replaceWith(el);
        } else {
            stack.append(el);
        }
        slots[name] = el;
    }

    function refresh(...names) {
        names.forEach(mount);
        mount('finish');
    }

    function renderAll() {
        Object.keys(slots).forEach(key => delete slots[key]);
        stack.replaceChildren();
        if (!state.admin) {
            tagline.textContent = 'Sign in to continue.';
            mount('signin');
            return;
        }
        tagline.textContent = state.claimed ? 'Settings' : "Let's get you set up.";
        ['plex', 'jellyfin', 'tmdb', 'locale', 'finish'].forEach(mount);
    }

    factories.signin = () => {
        if (ui.signinWaiting) {
            return card('Sign in', badge('Working'), note(h('span', { class: 'btn-spinner dark' }), ' Checking your Plex account...'));
        }
        const err = errorBox();
        if (ui.signinError) {
            err.set(ui.signinError);
            ui.signinError = '';
        }
        const options = state.signin || {};
        const kids = [note('This Kino-Swipe is already set up. Sign in as the owner of the media server it uses to change these settings.')];
        if (options.plex) {
            kids.push(button('Sign in with Plex', 'btn-plex', btn => run(btn, 'Opening Plex...', async () => {
                err.set('');
                try {
                    const data = await api('plex/start', {});
                    location.href = data.auth_url;
                } catch (e) {
                    err.set(e.message);
                }
            })));
        }
        if (options.jellyfin) {
            const user = input({ placeholder: 'Jellyfin administrator username' });
            const pass = input({ type: 'password', placeholder: 'Password', autocomplete: 'current-password' });
            const submit = btn => run(btn, 'Signing in...', async () => {
                err.set('');
                try {
                    await api('signin/jellyfin', { username: user.value, password: pass.value });
                    await loadState();
                    renderAll();
                } catch (e) {
                    pass.value = '';
                    err.set(e.message);
                }
            });
            const connect = button('Sign in with Jellyfin', 'btn-jf', submit);
            pass.addEventListener('keydown', e => { if (e.key === 'Enter') submit(connect); });
            kids.push(field('Jellyfin administrator', user), field('Password', pass), connect);
        }
        kids.push(err.el);
        return card('Sign in', badge('Locked'), ...kids);
    };

    function connectedBlock(info, onReconnect, onDisconnect, err) {
        const kids = [note(h('strong', null, info.name || 'Connected'), h('span', { class: 'setup-url' }, info.url))];
        if (info.locked) {
            kids.push(note('Set through environment variables on the container, so it can only be changed there.'));
        } else {
            kids.push(actions(
                button('Reconnect', 'btn-ghost', onReconnect),
                button('Disconnect', 'btn-ghost', btn => run(btn, 'Disconnecting...', onDisconnect))
            ));
        }
        kids.push(err.el);
        return kids;
    }

    factories.plex = () => {
        const info = state.plex;
        const err = errorBox();
        if (ui.plexError) err.set(ui.plexError);

        if (ui.plexWaiting) {
            return card('Plex', badge('Working'), note(h('span', { class: 'btn-spinner dark' }), ' Finishing Plex sign-in...'));
        }

        if (plexServers) return plexChooser(err);

        if (info.ready && !ui.plexEditing) {
            return card('Plex', badge('Connected', 'ok'), ...connectedBlock(info,
                () => { ui.plexEditing = true; refresh('plex'); },
                async () => {
                    try {
                        await api('plex/disconnect', {});
                        await loadState();
                        toast('Plex disconnected', 'ok');
                    } catch (e) {
                        err.set(e.message);
                    }
                    refresh('plex');
                }, err));
        }

        if (info.locked) {
            return card('Plex', badge('Locked'), note('Set through environment variables on the container, so it can only be changed there.'));
        }

        const kids = [note('Sign in with the Plex account that owns your server. Kino-Swipe finds the server for you.')];
        const start = button('Connect with Plex', 'btn-plex', btn => run(btn, 'Opening Plex...', async () => {
            err.set('');
            try {
                const data = await api('plex/start', {});
                location.href = data.auth_url;
            } catch (e) {
                err.set(e.message);
            }
        }));
        kids.push(start);
        if (ui.plexManual) {
            const url = input({ placeholder: 'http://192.168.1.10:32400', inputmode: 'url' });
            const token = input({ type: 'password', placeholder: 'Plex token' });
            kids.push(field('Server address', url), field('Plex token', token),
                button('Save', 'btn-ghost', btn => run(btn, 'Checking...', async () => {
                    err.set('');
                    try {
                        const data = await api('plex/save', { url: url.value, token: token.value });
                        ui.plexManual = false;
                        ui.plexEditing = false;
                        await loadState();
                        toast(data.movieLibrary ? `Connected to ${data.name}` : `Connected to ${data.name}, but no movie library was found`, 'ok');
                        refresh('plex');
                    } catch (e) {
                        err.set(e.message);
                    }
                })));
        }
        kids.push(linkButton(ui.plexManual ? 'Hide manual setup' : 'Enter details manually', () => { ui.plexManual = !ui.plexManual; refresh('plex'); }));
        if (info.ready) kids.push(linkButton('Cancel', () => { ui.plexEditing = false; ui.plexManual = false; refresh('plex'); }));
        kids.push(err.el);
        return card('Plex', badge('Not set up'), ...kids);
    };

    function plexChooser(err) {
        if (!plexServers.length) {
            return card('Plex', badge('No server found'),
                note("That Plex account doesn't own a server. Sign in with the account that owns your server, or enter the details manually."),
                actions(
                    button('Try again', 'btn-plex', () => { plexServers = null; refresh('plex'); }),
                    button('Enter manually', 'btn-ghost', () => { plexServers = null; ui.plexManual = true; refresh('plex'); })
                ), err.el);
        }
        let chosen = null;
        const options = [];
        const custom = input({ placeholder: 'http://192.168.1.10:32400', inputmode: 'url' });
        const select = uri => {
            chosen = uri;
            options.forEach(o => {
                const on = o.uri === uri;
                o.el.classList.toggle('selected', on);
                o.el.setAttribute('aria-checked', on ? 'true' : 'false');
            });
        };
        let best = null;
        const list = h('div', { class: 'server-list', role: 'radiogroup' });
        for (const server of plexServers) {
            for (const conn of server.connections) {
                if (!best || (conn.reachable && !best.reachable)) best = conn;
                const el = h('div', { class: 'server-opt', role: 'radio', tabindex: '0', 'aria-checked': 'false' },
                    h('span', { class: 'dot ' + (conn.reachable ? 'good' : 'bad') }),
                    h('div', null,
                        h('strong', null, server.name),
                        h('span', { class: 'setup-url' }, conn.uri),
                        h('small', null, `${conn.local ? 'Local network' : 'Remote'} · ${conn.reachable ? 'reachable from Kino-Swipe' : "didn't answer from Kino-Swipe"}`)));
                const pick = () => { custom.value = ''; select(conn.uri); };
                el.addEventListener('click', pick);
                el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
                options.push({ el, uri: conn.uri });
                list.append(el);
            }
        }
        if (best) select(best.uri);
        custom.addEventListener('input', () => { if (custom.value.trim()) select(null); });
        const save = button('Use this server', 'btn-plex', btn => run(btn, 'Checking...', async () => {
            err.set('');
            try {
                const data = await api('plex/save', { url: custom.value.trim() || chosen || '' });
                plexServers = null;
                ui.plexEditing = false;
                await loadState();
                toast(data.movieLibrary ? `Connected to ${data.name}` : `Connected to ${data.name}, but no movie library was found`, 'ok');
                refresh('plex');
            } catch (e) {
                err.set(e.message);
            }
        }));
        return card('Plex', badge('Choose server'),
            note('Pick the address Kino-Swipe should use. Green means it answered from inside the Kino-Swipe container.'),
            list, field('Or use a different address', custom), err.el, save,
            linkButton('Cancel', () => { plexServers = null; refresh('plex'); }));
    }

    async function resumePlexPin() {
        const pin = pendingPin;
        pendingPin = null;
        plexServers = null;
        const signingIn = !state.admin;
        let signedIn = false;
        let failure = '';
        if (signingIn) {
            ui.signinWaiting = true;
            mount('signin');
        } else {
            ui.plexError = '';
            ui.plexWaiting = true;
            refresh('plex');
        }
        try {
            for (let i = 0; i < 15 && !signedIn && !plexServers; i++) {
                const data = await api('plex/pin', { pin_id: pin });
                if (data.signedIn) signedIn = true;
                else if (data.servers) plexServers = data.servers;
                else if (!data.pending) break;
                else await sleep(1200);
            }
            if (!signedIn && !plexServers) failure = 'Plex sign-in was not completed. Try again.';
        } catch (e) {
            failure = e.message;
        }
        if (signingIn) {
            ui.signinWaiting = false;
            if (signedIn) {
                await loadState();
                renderAll();
            } else {
                ui.signinError = failure;
                mount('signin');
            }
            return;
        }
        ui.plexWaiting = false;
        ui.plexError = failure;
        refresh('plex');
        ui.plexError = '';
    }

    factories.jellyfin = () => {
        const info = state.jellyfin;
        const err = errorBox();

        if (info.ready && !ui.jfEditing) {
            return card('Jellyfin', badge('Connected', 'ok'), ...connectedBlock(info,
                () => { ui.jfEditing = true; ui.jfUrl = info.url; refresh('jellyfin'); },
                async () => {
                    try {
                        await api('jellyfin/disconnect', {});
                        await loadState();
                        toast('Jellyfin disconnected', 'ok');
                    } catch (e) {
                        err.set(e.message);
                    }
                    refresh('jellyfin');
                }, err));
        }

        if (info.locked) {
            return card('Jellyfin', badge('Locked'), note('Set through environment variables on the container, so it can only be changed there.'));
        }

        const url = input({ placeholder: 'http://jellyfin:8096', inputmode: 'url', value: ui.jfUrl });
        url.addEventListener('input', () => { ui.jfUrl = url.value; });
        const done = async name => {
            ui.jfEditing = false;
            ui.jfKey = false;
            await loadState();
            toast(`Connected to ${name}`, 'ok');
            refresh('jellyfin');
        };
        const kids = [];
        if (ui.jfKey) {
            const key = input({ type: 'password', placeholder: 'API key from Dashboard > API Keys' });
            kids.push(note('Paste an API key you created in the Jellyfin dashboard.'), field('Server address', url), field('API key', key),
                button('Save', 'btn-jf', btn => run(btn, 'Checking...', async () => {
                    err.set('');
                    try {
                        const data = await api('jellyfin/key', { url: url.value, api_key: key.value });
                        await done(data.name);
                    } catch (e) {
                        err.set(e.message);
                    }
                })),
                linkButton('Sign in with an admin account instead', () => { ui.jfKey = false; refresh('jellyfin'); }));
        } else {
            const user = input({ placeholder: 'Administrator username', value: ui.jfUser });
            user.addEventListener('input', () => { ui.jfUser = user.value; });
            const pass = input({ type: 'password', placeholder: 'Password', autocomplete: 'current-password' });
            const submit = btn => run(btn, 'Connecting...', async () => {
                err.set('');
                try {
                    const data = await api('jellyfin/connect', { url: url.value, username: user.value, password: pass.value });
                    pass.value = '';
                    await done(data.name);
                } catch (e) {
                    err.set(e.message);
                }
            });
            const connect = button('Connect', 'btn-jf', submit);
            pass.addEventListener('keydown', e => { if (e.key === 'Enter') submit(connect); });
            kids.push(
                note('Sign in as a Jellyfin administrator. Kino-Swipe uses the password once to create its own API key and never stores it.'),
                field('Server address', url), field('Username', user), field('Password', pass), connect,
                linkButton('Use an API key instead', () => { ui.jfKey = true; refresh('jellyfin'); }));
        }
        if (info.ready) kids.push(linkButton('Cancel', () => { ui.jfEditing = false; ui.jfKey = false; refresh('jellyfin'); }));
        kids.push(err.el);
        return card('Jellyfin', badge('Not set up'), ...kids);
    };

    factories.tmdb = () => {
        const info = state.tmdb;
        const err = errorBox();

        if (info.locked) {
            return card('Trailers and cast', badge(info.ready ? 'On' : 'Locked', info.ready ? 'ok' : ''), note('Set through an environment variable on the container, so it can only be changed there.'));
        }

        if (info.ready && !ui.tmdbEditing) {
            return card('Trailers and cast', badge('On', 'ok'),
                note('Trailers and cast lists are powered by your TMDB key.'),
                actions(
                    button('Replace key', 'btn-ghost', () => { ui.tmdbEditing = true; refresh('tmdb'); }),
                    button('Remove', 'btn-ghost', btn => run(btn, 'Removing...', async () => {
                        try {
                            await api('tmdb', { api_key: '' });
                            await loadState();
                            toast('TMDB key removed', 'ok');
                        } catch (e) {
                            err.set(e.message);
                        }
                        refresh('tmdb');
                    }))
                ), err.el);
        }

        const key = input({ type: 'password', placeholder: 'TMDB v3 API key' });
        const save = button('Save key', 'btn-tmdb', btn => run(btn, 'Checking...', async () => {
            err.set('');
            if (!key.value.trim()) {
                err.set('Paste your TMDB API key first.');
                return;
            }
            try {
                await api('tmdb', { api_key: key.value });
                ui.tmdbEditing = false;
                await loadState();
                toast('Trailers and cast are on', 'ok');
                refresh('tmdb');
            } catch (e) {
                err.set(e.message);
            }
        }));
        const kids = [
            note('Optional. Adds the trailer button and cast list to movie cards. Without a key those are simply hidden.'),
            h('a', { class: 'setup-link', href: 'https://www.themoviedb.org/settings/api', target: '_blank', rel: 'noopener noreferrer' }, 'Get a free TMDB key'),
            field('API key', key), err.el, save,
        ];
        if (info.ready) kids.push(linkButton('Cancel', () => { ui.tmdbEditing = false; refresh('tmdb'); }));
        return card('Trailers and cast', badge('Off'), ...kids);
    };

    factories.locale = () => {
        const info = state.locale;
        const err = errorBox();
        const select = h('select', null,
            h('option', { value: 'en' }, 'English (library called "Movies")'),
            h('option', { value: 'de' }, 'German (library called "Filme")'));
        select.value = info.value;
        select.disabled = info.locked;
        select.addEventListener('change', async () => {
            err.set('');
            try {
                await api('locale', { locale: select.value });
                await loadState();
                toast('Language saved', 'ok');
            } catch (e) {
                err.set(e.message);
            }
        });
        return card('Plex library language', info.locked ? badge('Locked') : null,
            note('Used to find your Plex movie library by name.'),
            field('Language', select), info.locked ? note('Set through an environment variable on the container.') : null, err.el);
    };

    factories.finish = () => {
        const ready = state.plex.ready || state.jellyfin.ready;
        const go = button(ready ? 'Open Kino-Swipe' : 'Connect Plex or Jellyfin to continue', 'btn-plex' + (ready ? '' : ' is-off'), () => { if (ready) location.href = '/'; });
        go.disabled = !ready;
        return h('section', { class: 'setup-finish' },
            go,
            state.claimed ? h('div', { class: 'setup-finish-links' },
                linkButton('Sign out of settings', async () => {
                    try { await api('lock', {}); } catch (e) {}
                    try { await loadState(); } catch (e) { state = { admin: false, signin: {} }; }
                    renderAll();
                })) : null,
            note(state.claimed
                ? 'Signing out locks these settings. To change them later, visit /setup and sign in again as the Plex owner or a Jellyfin admin.'
                : 'You can come back to /setup any time to change these.'));
    };

    (async function boot() {
        try {
            await loadState();
        } catch (e) {
            state = { admin: false, signin: {} };
        }
        renderAll();
        if (pendingPin) resumePlexPin();
    })();
})();
