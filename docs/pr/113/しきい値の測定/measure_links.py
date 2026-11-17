"""project-index links のパスの照合の所要時間を測る（選択の正規表現と、trie で接頭辞をまとめた正規表現）。"""
import os, re, sys, time

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
SKIP_PATHS = {".claude/worktrees"}
BEFORE = r"(?<![A-Za-z0-9_\-./])"
AFTER = r"(?![A-Za-z0-9_\-/])"
MAX_READ = 1_048_576


def walk(root):
    out = []
    for folder, dirs, files in os.walk(root):
        rel = os.path.relpath(folder, root)
        rel = "" if rel == "." else rel
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and (f"{rel}/{d}" if rel else d) not in SKIP_PATHS]
        out += [f"{rel}/{f}" if rel else f for f in files]
    return out


def trie_pattern(paths):
    trie = {}
    for p in paths:
        node = trie
        for ch in p:
            node = node.setdefault(ch, {})
        node[""] = {}

    def build(node):
        alts = []
        end = "" in node
        for ch in sorted(k for k in node if k):
            alts.append(re.escape(ch) + build(node[ch]))
        if not alts:
            return ""
        body = alts[0] if len(alts) == 1 else "(?:" + "|".join(alts) + ")"
        # 長い一致を先に試し、終端なら空でも一致させる
        return f"(?:{body})?" if end else body

    return re.compile(BEFORE + "(" + build(trie) + ")" + AFTER)


def alternation_pattern(paths):
    alts = "|".join(re.escape(p) for p in sorted(paths, key=len, reverse=True))
    return re.compile(BEFORE + "(" + alts + ")" + AFTER)


def run(root, label, pattern, sources):
    t = time.time()
    hits = 0
    largest = (0, None, 0.0)
    for s in sources:
        with open(os.path.join(root, s), "rb") as f:
            text = f.read(MAX_READ).decode("utf-8", "replace")
        t1 = time.time()
        hits += sum(1 for _ in pattern.finditer(text))
        dt = time.time() - t1
        if len(text) > largest[0]:
            largest = (len(text), s, dt)
    print(f"{label}: 全体 {time.time() - t:.2f} 秒・一致 {hits} 件・最大の文書 {largest[1]}（{largest[0]} 文字）{largest[2]:.3f} 秒")


root = sys.argv[1]
files = walk(root)
candidates = [p for p in files if "/" in p]
sources = [p for p in files if p.endswith((".md", ".yaml", ".yml"))]
print(f"ファイル {len(files)}・候補のパス {len(candidates)}・指す側 {len(sources)}")
t = time.time(); tp = trie_pattern(candidates); print(f"trie の正規表現の組み立て {time.time() - t:.2f} 秒")
run(root, "trie", tp, sources)
if "--alternation" in sys.argv:
    t = time.time(); ap = alternation_pattern(candidates); print(f"選択の正規表現の組み立て {time.time() - t:.2f} 秒")
    run(root, "選択", ap, sources)
