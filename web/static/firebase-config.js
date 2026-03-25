/* ═══════════════════════════════════════════════════════════════
   Firebase Configuration & Initialization
   ═══════════════════════════════════════════════════════════════ */

const firebaseConfig = {
    apiKey: "AIzaSyCn6hrf2FuZfOUSpS1rabrG6-rMzWyT3xE",
    authDomain: "trading-bot-f3bd5.firebaseapp.com",
    projectId: "trading-bot-f3bd5",
    storageBucket: "trading-bot-f3bd5.firebasestorage.app",
    messagingSenderId: "1011249632225",
    appId: "1:1011249632225:web:4e5fdc84aa3d37157178a0",
    measurementId: "G-C889LC57M6"
};

// Initialize Firebase
firebase.initializeApp(firebaseConfig);

const auth = firebase.auth();
const db = firebase.firestore();

// ─── Auth State ──────────────────────────────────────────────
let currentUser = null;

auth.onAuthStateChanged((user) => {
    currentUser = user;
    if (user) {
        console.log('Signed in as:', user.email);
        document.body.classList.add('authenticated');
        document.body.classList.remove('unauthenticated');
        updateAuthUI(user);
        // Load user settings from Firestore on login
        if (typeof loadSettingsFromFirestore === 'function') {
            loadSettingsFromFirestore();
        }
    } else {
        console.log('Not signed in');
        document.body.classList.remove('authenticated');
        document.body.classList.add('unauthenticated');
        updateAuthUI(null);
        // Redirect to login if not on login page
        if (!window.location.pathname.startsWith('/login')) {
            window.location.href = '/login';
        }
    }
});

function updateAuthUI(user) {
    const logoutBtn = document.getElementById('logoutBtn');

    if (user) {
        const email = user.email || '';
        const name  = email.split('@')[0];
        const ini   = name.charAt(0).toUpperCase();

        // Topbar avatar + short label
        const ua = document.getElementById('userAvatar');
        const us = document.getElementById('userEmailShort');
        if (ua) ua.textContent = ini;
        if (us) us.textContent = name;

        // Dropdown header
        const da = document.getElementById('udAvatar');
        const dn = document.getElementById('udName');
        const de = document.getElementById('udEmail');
        if (da) da.textContent = ini;
        if (dn) dn.textContent = name;
        if (de) de.textContent = email;
    }

    if (logoutBtn) {
        logoutBtn.style.display = user ? 'inline-block' : 'none';
    }
}

function signOut() {
    auth.signOut().then(() => {
        window.location.href = '/login';
    });
}
