import re, sys, os, subprocess, statistics
from pathlib import Path
JP = re.compile(r'[぀-ヿ一-鿿]')
def md_metrics(text):
    lines = text.splitlines()
    if lines and lines[0].strip()=='---':
        for i,l in enumerate(lines[1:],1):
            if l.strip()=='---': lines=lines[i+1:]; break
    inside=False; code=0; heads=0; prose=[]
    for l in lines:
        if l.lstrip().startswith('```'):
            inside=not inside; code+=1; continue
        if inside: code+=1; continue
        if re.match(r'#{1,6}\s', l): heads+=1
        prose.append(l)
    n=max(len(lines),1)
    chars=[c for c in ''.join(prose) if not c.isspace() and c not in '|-*#`[]()>:.,_/']
    jp=sum(1 for c in chars if JP.match(c))/max(len(chars),1)
    return heads, code/n, jp
for root in sys.argv[1:]:
    files = subprocess.run(['git','-C',root,'ls-files','-z'],capture_output=True,text=True).stdout.split('\0')
    md=[f for f in files if f.endswith('.md')]
    allsizes=sorted((os.path.getsize(os.path.join(root,f)) for f in files if f and os.path.isfile(os.path.join(root,f))), reverse=True)
    res={'few':0,'code':0,'nonjp':0,'any':0}
    rows=[]
    for f in md:
        if not os.path.isfile(os.path.join(root,f)): continue
        t=Path(root,f).read_text(errors='ignore')
        h,c,j=md_metrics(t)
        a=h<2; b=c>=0.5; d=j<0.1
        res['few']+=a; res['code']+=b; res['nonjp']+=d; res['any']+=(a or b or d)
        rows.append((f,h,round(c,2),round(j,2),a or b or d))
    print(root, 'md', len(md), res)
    print(' sizes top5', allsizes[:5], 'p99', allsizes[len(allsizes)//100] if allsizes else 0, 'count', len(allsizes))
    for r in [r for r in rows if r[4]][:15]: print('  next', r)
