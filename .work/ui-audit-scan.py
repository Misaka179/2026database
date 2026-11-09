import re, glob, os

os.chdir(os.path.join(os.path.dirname(__file__), '..', 'web'))

acts = set()
pages = set()
for f in glob.glob('*.js') + glob.glob('*.html'):
    s = open(f, encoding='utf-8').read()
    acts |= set(re.findall(r'data-action="([a-z0-9-]+)"', s))
    acts |= set(re.findall(r"dataset\.action = '([a-z0-9-]+)'", s))
    pages |= set(re.findall(r'data-page="([a-z0-9-]+)"', s))

handled = set()
for f in glob.glob('*.js'):
    s = open(f, encoding='utf-8').read()
    handled |= set(re.findall(r"name === '([a-z0-9-]+)'", s))
    handled |= set(re.findall(r'name === "([a-z0-9-]+)"', s))
    handled |= set(re.findall(r'name===\'([a-z0-9-]+)\'', s))

print('ACTIONS_NOT_HANDLED:', sorted(a for a in acts if a not in handled))
print('HANDLED_BUT_UNUSED:', sorted(h for h in handled if h not in acts))
print('PAGES:', sorted(pages))
