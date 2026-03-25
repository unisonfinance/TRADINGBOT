"""Quick script to rebrand base.html to TrekBot."""
path = r'g:\0000000000000 UT UNISON TRANSFERS\000000000000000000000000000 FIREBASSE PROJECTS\00000 BACK UP APPS\000000 TRADING_BOT\TRADING_BOT_V0001\web\templates\base.html'

with open(path, 'r', encoding='utf-8') as f:
    c = f.read()

# 1) Rename window title
c = c.replace('{% block title %}Crypto RBI Bot{% endblock %}', '{% block title %}TrekBot{% endblock %}')

# 2) Add favicon after the stylesheet link
old_css = "    <link rel=\"stylesheet\" href=\"{{ url_for('static', filename='style.css') }}\">"
new_css = ("    <link rel=\"icon\" type=\"image/x-icon\" href=\"{{ url_for('static', filename='favicon.ico') }}\">\n"
           "    <link rel=\"stylesheet\" href=\"{{ url_for('static', filename='style.css') }}\">")
c = c.replace(old_css, new_css, 1)

# 3) Replace the old logo SVG with the image
old_txt = (
    '            <div class="logo-orb">\n'
    '                <svg width="20" height="20" viewBox="0 0 24 24" fill="none">\n'
    '                    <polygon points="12,2 22,7 22,17 12,22 2,17 2,7" fill="currentColor" opacity="0.9"/>\n'
    '                    <polygon points="12,6 18,9.5 18,16.5 12,20 6,16.5 6,9.5" fill="white" opacity="0.25"/>\n'
    '                </svg>\n'
    '            </div>\n'
    '            <div class="logo-text-wrap">\n'
    '                <span class="logo-text">RBI BOT</span>\n'
    '                <span class="logo-sub">CRYPTO TRADING</span>\n'
    '            </div>'
)

new_txt = (
    '            <div class="logo-orb logo-orb-img">\n'
    "                <img src=\"{{ url_for('static', filename='logo.svg') }}\" alt=\"TrekBot\" width=\"36\" height=\"36\" style=\"display:block;\">\n"
    '            </div>\n'
    '            <div class="logo-text-wrap">\n'
    '                <span class="logo-text">TREKBOT</span>\n'
    '                <span class="logo-sub">CRYPTO TRADING</span>\n'
    '            </div>'
)

if old_txt in c:
    c = c.replace(old_txt, new_txt, 1)
    print('Logo replaced OK')
else:
    # Show what we actually have around logo-orb
    idx = c.find('logo-orb')
    print('NOT FOUND. Context around logo-orb:')
    print(repr(c[max(0, idx-20):idx+300]))

with open(path, 'w', encoding='utf-8') as f:
    f.write(c)
print('Done')
