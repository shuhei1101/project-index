import sys,yaml,glob,unicodedata,re,itertools
def norm(s): return re.sub(r'[\s\W_]+','',unicodedata.normalize('NFKC',s).casefold())
def bg(s): return {s[i:i+2] for i in range(len(s)-1)} or {s}
def dice(a,b):
    A,B=bg(norm(a)),bg(norm(b));return 2*len(A&B)/(len(A)+len(B))
for root in sys.argv[1:]:
    rows=[]
    for f in glob.glob(root+'/**/files*.y*ml',recursive=True):
        if '/.claude/' in f[len(root):] or 'node_modules' in f: continue
        try: d=yaml.safe_load(open(f))
        except Exception: continue
        if not isinstance(d,dict) or not isinstance(d.get('files'),list): continue
        rows+=[r.get('description') for r in d['files'] if isinstance(r,dict) and r.get('description')]
    sims=sorted(((dice(a,b),a,b) for a,b in itertools.combinations(rows,2)),reverse=True)
    print(root,len(rows),'pairs',len(sims))
    for t in (0.95,0.9,0.85,0.8,0.7): print(' >=',t,sum(1 for s in sims if s[0]>=t))
    for s in sims[:6]: print('  %.3f'%s[0],s[1][:50],'|',s[2][:50])
