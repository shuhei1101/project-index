import json, sys, gzip, re, datetime
lim={'dev-docs':19.7,'claude-balancer':8.3,'aituber':7.1,'knowledge':7.4,'mdmark':13.3,'ai-monitor':23.3,'voice-input':6.7,'gui-support':4.9,'mindstella':13.8,'observability':5.6,'project-index':8.7,'alias-inject':5.1,'rule-inject':6.2,'shuhdev-gateway':5.4}
print("| 計測 | 配信元 | 画面 | 上限 | 超過 | 重なった 1 件の CPU 時間の合計 | CPU 時間で説明できない残り | 要求の合計 | 要求の外（画面のサーバー・ブラウザ） | 配信元の読み込みの完了待ち | 稼働中の project-index の CPU 使用率（平均） | 負荷の平均 |")
print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
for run in sys.argv[1:]:
    R=f"/tmp/poc147/runs/{run}"
    ev=[json.loads(l) for l in open(f"{R}/timing.jsonl")]
    reqs=sorted([e for e in ev if e["ev"]=="req"],key=lambda e:e["t0"])
    units=[e for e in ev if e["ev"]=="unit"]
    live=[json.loads(l) for l in open(f"{R}/live.jsonl")]
    lpid=[k for k in live[0] if k not in("t","load")][0]
    t0=float(open(f"{R}/t0").read())
    loaded=None
    for l in open(f"{R}/pi.log"):
        if '配信元を再読み込みした' in l:
            m=re.match(r'(\S+ \S+)',l); loaded=datetime.datetime.strptime(m.group(1),'%Y-%m-%d %H:%M:%S,%f').timestamp(); break
    pages=[(l.split()[1],int(l.split()[2][:-2])/1000) for l in open(f"{R}/dd2.out") if l.startswith("1 ")]
    firsts={}
    for r in reqs: firsts.setdefault(r["source"],r["t0"])
    for i,(src,sec) in enumerate(pages):
        lo=firsts[src]; hi=firsts[pages[i+1][0]] if i+1<len(pages) else lo+sec
        rs=[r for r in reqs if lo<=r["t0"]<hi]
        cpu=0.0
        for u in units:
            w=u["t1"]-u["t0"]
            if w<=0: continue
            ov=sum(max(0,min(u["t1"],r["t1"])-max(u["t0"],r["t0"])) for r in rs)
            cpu+=u["cpu"]*ov/w
        excess=sec-lim[src]
        if excess<=0: continue
        rsum=sum(r["t1"]-r["t0"] for r in rs)
        wait=max(0,loaded-lo) if src=="dev-docs" and loaded else 0
        lv=[x[lpid]["cpu"] for x in live if lo<=x["t"]<=lo+sec]
        ld=[float(x["load"]) for x in live if lo<=x["t"]<=lo+sec]
        print(f"| {run} | {src} | {sec:.1f} 秒 | {lim[src]} 秒 | {excess:.1f} 秒 | {cpu:.2f} 秒 | {max(0,excess-cpu):.1f} 秒 | {rsum:.1f} 秒 | {sec-rsum:.1f} 秒 | {wait:.1f} 秒 | {100*sum(lv)/len(lv):.0f}% | {sum(ld)/len(ld):.1f} |")
