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
