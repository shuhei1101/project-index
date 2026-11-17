"""稼働中のプロセスの CPU・I/O を 1 秒ごとに /proc から記録する。"""
import json, os, sys, time
pids = [int(p) for p in sys.argv[2].split(",")]
out = open(sys.argv[1], "a")
tick = os.sysconf("SC_CLK_TCK")
def read(pid):
    with open(f"/proc/{pid}/stat") as f:
        fields = f.read().rsplit(")", 1)[1].split()
    cpu = (int(fields[11]) + int(fields[12])) / tick
    io = {}
    with open(f"/proc/{pid}/io") as f:
        for line in f:
            k, v = line.split(":")
            io[k] = int(v)
    return cpu, io
prev = {p: read(p) for p in pids}
while True:
    time.sleep(1)
    row = {"t": time.time(), "load": open("/proc/loadavg").read().split()[0]}
    for p in pids:
        cpu, io = read(p)
        c0, io0 = prev[p]
        row[str(p)] = {"cpu": round(cpu - c0, 3), **{k: io[k] - io0[k] for k in ("read_bytes", "write_bytes", "rchar", "wchar")}}
        prev[p] = (cpu, io)
    out.write(json.dumps(row) + "\n"); out.flush()
