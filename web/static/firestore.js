/* ═══════════════════════════════════════════════════════════════
   Firestore — Save / Load user data
   Collections:
     users/{uid}/settings    — exchange config, risk settings
     users/{uid}/trades      — trade history
     users/{uid}/backtests   — backtest results
     users/{uid}/bots        — bot configurations
   ═══════════════════════════════════════════════════════════════ */

// ─── Settings ────────────────────────────────────────────────
async function saveSettingsToFirestore(settings) {
    if (!currentUser) { showToast('Not signed in — cloud save skipped', 'error'); return false; }

    try {
        const doc = {
            exchange_id: settings.exchange_id || 'binance',
            api_key: settings.api_key || '',
            sandbox: settings.sandbox || 'false',
            default_symbol: settings.default_symbol || 'BTC/USDT',
            position_size: settings.position_size || '1.0',
            quote_currency: settings.quote_currency || 'USDC',
            max_position_size: settings.max_position_size || '5',
            max_daily_loss: settings.max_daily_loss || '2',
            max_drawdown_pct: settings.max_drawdown_pct || '30',
            updated_at: firebase.firestore.FieldValue.serverTimestamp(),
        };
        // Store full api_secret if provided
        if (settings.api_secret) {
            doc.api_secret = settings.api_secret;
        }

        await db.collection('users').doc(currentUser.uid)
            .collection('settings').doc('exchange').set(doc, { merge: true });

        console.log('Settings saved to Firestore');
        return true;
    } catch (e) {
        console.error('Failed to save settings:', e);
        showToast('Failed to save to cloud: ' + e.message, 'error');
        return false;
    }
}

async function loadSettingsFromFirestore() {
    if (!currentUser) return null;

    try {
        const doc = await db.collection('users').doc(currentUser.uid)
            .collection('settings').doc('exchange').get();

        if (doc.exists) {
            const data = doc.data();
            console.log('Settings loaded from Firestore');
            return data;
        }
        return null;
    } catch (e) {
        console.error('Failed to load settings:', e);
        return null;
    }
}

// ─── Trades ──────────────────────────────────────────────────
async function saveTradeToFirestore(trade) {
    if (!currentUser) return;

    try {
        await db.collection('users').doc(currentUser.uid)
            .collection('trades').add({
                ...trade,
                created_at: firebase.firestore.FieldValue.serverTimestamp(),
            });
    } catch (e) {
        console.error('Failed to save trade:', e);
    }
}

async function loadTradesFromFirestore(limit = 50) {
    if (!currentUser) return [];

    try {
        const snapshot = await db.collection('users').doc(currentUser.uid)
            .collection('trades')
            .orderBy('created_at', 'desc')
            .limit(limit)
            .get();

        return snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
    } catch (e) {
        console.error('Failed to load trades:', e);
        return [];
    }
}

// ─── Backtest Results ────────────────────────────────────────
async function saveBacktestToFirestore(result) {
    if (!currentUser) return;

    try {
        await db.collection('users').doc(currentUser.uid)
            .collection('backtests').add({
                ...result,
                created_at: firebase.firestore.FieldValue.serverTimestamp(),
            });
        console.log('Backtest saved to Firestore');
    } catch (e) {
        console.error('Failed to save backtest:', e);
    }
}

async function loadBacktestsFromFirestore(limit = 20) {
    if (!currentUser) return [];

    try {
        const snapshot = await db.collection('users').doc(currentUser.uid)
            .collection('backtests')
            .orderBy('created_at', 'desc')
            .limit(limit)
            .get();

        return snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
    } catch (e) {
        console.error('Failed to load backtests:', e);
        return [];
    }
}

// ─── Bot Configs ─────────────────────────────────────────────
async function saveBotConfigToFirestore(botConfig) {
    if (!currentUser) return;

    try {
        const docId = `${botConfig.strategy}_${botConfig.symbol.replace('/', '-')}`;
        await db.collection('users').doc(currentUser.uid)
            .collection('bots').doc(docId).set({
                ...botConfig,
                updated_at: firebase.firestore.FieldValue.serverTimestamp(),
            }, { merge: true });
    } catch (e) {
        console.error('Failed to save bot config:', e);
    }
}

async function loadBotConfigsFromFirestore() {
    if (!currentUser) return [];

    try {
        const snapshot = await db.collection('users').doc(currentUser.uid)
            .collection('bots').get();

        return snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
    } catch (e) {
        console.error('Failed to load bot configs:', e);
        return [];
    }
}

// ─── User Profile ────────────────────────────────────────────
async function saveUserProfile(profile) {
    if (!currentUser) return;

    try {
        await db.collection('users').doc(currentUser.uid).set({
            email: currentUser.email,
            ...profile,
            updated_at: firebase.firestore.FieldValue.serverTimestamp(),
        }, { merge: true });
    } catch (e) {
        console.error('Failed to save profile:', e);
    }
}
