import re, glob, os
os.chdir(os.path.join(os.path.dirname(__file__), '..', 'web'))
files = glob.glob('*.js')
acts = set()
for f in files:
    s = open(f, encoding='utf-8').read()
    acts |= set(re.findall(r'data-action="([a-z0-9-]+)"', s))
dead = []
for a in sorted(acts):
    hits = 0
    for f in files:
        s = open(f, encoding='utf-8').read()
        # quoted literal used in logic (not inside a data-action attribute)
        for m in re.finditer(r"'%s'" % re.escape(a), s):
            hits += 1
    if hits == 0:
        dead.append(a)
print('DEAD_ACTIONS:', dead)
print('TOTAL_ACTIONS:', len(acts))
