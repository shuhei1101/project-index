#!/usr/bin/env python3
"""単一のクライアントで、温まったワークツリーの 1 回の所要時間が、読み込んだワークツリーの数で変わるかを測る。"""
import httpx, time, json, sys
PORT=int(sys.argv[1]); N=int(sys.argv[2])
c=httpx.Client(base_url=f"http://127.0.0.1:{PORT}",timeout=600)
def call(path, **kw):
    t=time.perf_counter()
    r=c.post("/mcp/",json={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_docs","arguments":{"cwd":path,"view":"summary","limit":5,**kw}}},headers={"Accept":"application/json, text/event-stream"})
    d=time.perf_counter()-t
    err=r.json().get("result",{}).get("isError")
    return round(d,2), err
wts=[l.split(" ",1)[1].strip() for l in open("/tmp/pi-poc/worktrees.txt")]
target="/tmp/pi-poc/repo/ai-monitor/.claude/worktrees/develop"
print("cold",call(target)); print("warm",[call(target)[0] for _ in range(5)])
done=0
for w in wts:
    if w==target: continue
    while True:
        d,e=call(w)
        if not e: break
        time.sleep(2)
    done+=1
    if done in (10,20,40,N):
        print(f"after {done} wts warm",[call(target)[0] for _ in range(5)], flush=True)
    if done>=N: break
