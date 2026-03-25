"""Rename all 'Crypto RBI Bot' occurrences to 'TrekBot' in template/HTML files."""
import os

files = [
    r'g:\0000000000000 UT UNISON TRANSFERS\000000000000000000000000000 FIREBASSE PROJECTS\00000 BACK UP APPS\000000 TRADING_BOT\TRADING_BOT_V0001\web\templates\backtest.html',
    r'g:\0000000000000 UT UNISON TRANSFERS\000000000000000000000000000 FIREBASSE PROJECTS\00000 BACK UP APPS\000000 TRADING_BOT\TRADING_BOT_V0001\web\templates\dashboard.html',
    r'g:\0000000000000 UT UNISON TRANSFERS\000000000000000000000000000 FIREBASSE PROJECTS\00000 BACK UP APPS\000000 TRADING_BOT\TRADING_BOT_V0001\web\templates\login.html',
    r'g:\0000000000000 UT UNISON TRANSFERS\000000000000000000000000000 FIREBASSE PROJECTS\00000 BACK UP APPS\000000 TRADING_BOT\TRADING_BOT_V0001\web\templates\trading.html',
    r'g:\0000000000000 UT UNISON TRANSFERS\000000000000000000000000000 FIREBASSE PROJECTS\00000 BACK UP APPS\000000 TRADING_BOT\TRADING_BOT_V0001\web\templates\settings.html',
    r'g:\0000000000000 UT UNISON TRANSFERS\000000000000000000000000000 FIREBASSE PROJECTS\00000 BACK UP APPS\000000 TRADING_BOT\TRADING_BOT_V0001\web\app.py',
]

for fpath in files:
    if not os.path.exists(fpath):
        print(f'SKIP (not found): {fpath}')
        continue
    with open(fpath, 'r', encoding='utf-8') as f:
        c = f.read()
    new = c.replace('Crypto RBI Bot', 'TrekBot').replace('CRYPTO RBI BOT', 'TREKBOT')
    if new != c:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(new)
        print(f'Updated: {os.path.basename(fpath)}')
    else:
        print(f'No change: {os.path.basename(fpath)}')

print('Done')
