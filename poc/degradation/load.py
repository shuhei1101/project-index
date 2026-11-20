"""PoC（#237）: 本番の実測から決めた負荷を PoC のサーバーへ送り、呼び出しごとの結果と計測を記録する。

- 32 本の並列のクライアントが、約 45 回/分で文書の MCP の全てのツールを呼ぶ
- 55 秒で接続を切り、同じ呼び出しを 1 回やり直す（Claude Code の時間切れとエージェントのやり直し）
- 読み込む worktree を 10 個から始め、2 分ごとに 1 個ずつ増やす
- 配信元の複製の既定のブランチへ約 20 回/時で commit を追加する
- 1 分ごとに管理の MCP の status を呼び、30 秒ごとに RSS・スレッドごとの CPU を記録し、5 分ごとに SIGUSR1 を送る
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import itertools
import json
import os
import random
import signal
import subprocess
import time
from pathlib import Path

import httpx

# ツールごとの割合（本番の直近 5 時間の実測から、少ないツールを本番より多くしたもの）
TOOL_WEIGHTS = {
    "search_docs": 70.0,
    "write_docs": 20.0,
    "describe": 4.0,
    "trace_related": 1.5,
    "list_changes": 1.5,
    "list_match_words": 1.5,
    "delete_docs": 1.5,
}
REF_SHARE = 0.05  # search_docs のうち ref を指す割合
REAL_WRITE_SHARE = 0.8  # write_docs・delete_docs のうち dry_run にしない割合
CLIENT_TIMEOUT_SEC = 55.0
MARKER = " [poc]"


class Recorder:
    """結果を JSON Lines で追記する。"""

    def __init__(self, path: Path) -> None:
        self._file = path.open("a", buffering=1)
        self.started = time.time()

    def write(self, kind: str, **values: object) -> None:
        values.update(kind=kind, t=round(time.time() - self.started, 3), at=time.time())
        self._file.write(json.dumps(values, ensure_ascii=False) + "\n")


class Mcp:
    """stateless の Streamable HTTP の MCP へ tools/call を送る。"""

    def __init__(self, base: str, path: str) -> None:
        self._client = httpx.AsyncClient(base_url=base, timeout=CLIENT_TIMEOUT_SEC)
        self._path = path
        self._ids = itertools.count(1)

    async def call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        body = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = await self._client.post(
            self._path,
            json=body,
            headers={"Accept": "application/json, text/event-stream"},
        )
        response.raise_for_status()
        return response.json()


def result_text(reply: dict[str, object]) -> tuple[bool, str]:
    """tools/call の応答から、エラーかと本文を取り出す。"""
    result = reply.get("result") or {}
    if "error" in reply:
        return True, json.dumps(reply["error"], ensure_ascii=False)[:300]
    content = result.get("content") or [{}]
    text = str(content[0].get("text", ""))
    return bool(result.get("isError")), text


class Load:
    """負荷の 1 回分の状態（worktree・文書の ID・書き込みの切り替え）。"""

    def __init__(self, args: argparse.Namespace, recorder: Recorder) -> None:
        self.args = args
        self.recorder = recorder
        self.docs = Mcp(f"http://127.0.0.1:{args.port}", "/mcp/")
        self.admin = Mcp(f"http://127.0.0.1:{args.port}", "/_admin/mcp/")
        rows = [line.split(" ", 1) for line in Path(args.root, "worktrees.txt").read_text().splitlines()]
        random.Random(args.seed).shuffle(rows)
        self.worktrees = [(repo, path) for repo, path in rows]
        self.active = min(args.initial_worktrees, len(self.worktrees))
        self.ids: dict[str, list[str]] = {}
        self.descriptions: dict[tuple[str, str], str] = {}
        self.marked: dict[tuple[str, str], bool] = {}
        self.rng = random.Random(args.seed + 1)

    def pick_worktree(self) -> tuple[str, str]:
        return self.rng.choice(self.worktrees[: self.active])

    async def prepare(self) -> None:
        """配信元ごとに、description を持つ文書の ID と元の description を集める。"""
        develop = {repo: path for repo, path in self.worktrees if path.endswith("/develop")}
        for repo, path in develop.items():
            try:
                reply = await self.docs.call(
                    "search_docs",
                    {
                        "cwd": path,
                        "filter": {"field": "description", "op": "exists"},
                        "fields": ["id", "description"],
                        "format": "json",
                        "limit": 100,
                    },
                )
            except httpx.HTTPError as error:
                self.recorder.write("prepare", repo=repo, error=repr(error))
                continue
            is_error, text = result_text(reply)
            if is_error:
                self.recorder.write("prepare", repo=repo, error=text[:300])
                continue
            # 本文が YAML の文書（description をキーとして持つ）だけを書き込みの対象にする
            items = [
                item
                for item in json.loads(text).get("items", [])
                if str(item.get("path", "")).endswith(".yaml")
                and isinstance(item.get("values", {}).get("description"), str)
            ]
            self.ids[repo] = [item["id"] for item in items]
            for item in items:
                self.descriptions[(repo, item["id"])] = item["values"]["description"]
            ids = self.ids[repo]
            self.recorder.write("prepare", repo=repo, ids=len(ids))

    def arguments(self, tool: str, repo: str, path: str, session: str) -> dict[str, object]:
        """ツールごとの引数を組み立てる。"""
        base: dict[str, object] = {"cwd": path, "session_id": session}
        ids = self.ids.get(repo) or []
        doc_id = self.rng.choice(ids) if ids else None
        real = self.rng.random() < REAL_WRITE_SHARE
        match tool:
            case "search_docs":
                roll = self.rng.random()
                if roll < REF_SHARE:
                    base |= {"ref": "develop", "view": "summary", "limit": 20}
                elif roll < REF_SHARE * 2:
                    base |= {"source": "*", "view": "summary", "limit": 20}
                elif doc_id and roll < 0.5:
                    base |= {"filter": {"field": "id", "op": "eq", "values": [doc_id]}, "view": "full"}
                else:
                    base |= {"view": "summary", "limit": 20}
            case "write_docs":
                if not doc_id:
                    return base | {"operations": [], "dry_run": True}
                key = (path, doc_id)
                marked = not self.marked.get(key, False)
                original = self.descriptions[(repo, doc_id)]
                value = original + MARKER if marked else original
                if real:
                    self.marked[key] = marked
                base |= {
                    "operations": [{"op": "update", "id": doc_id, "set": {"description": value}}],
                    "dry_run": not real,
                }
            case "delete_docs":
                base |= {"targets": [{"id": doc_id or "missing", "expected_version": "0"}], "dry_run": not real}
            case "trace_related":
                base |= {"from_ids": [doc_id] if doc_id else [], "depth": 2}
            case "list_changes" | "list_match_words" | "describe":
                pass
        return base

    async def call_once(self, client: int, tool: str, arguments: dict[str, object], repo: str, path: str, attempt: int) -> bool:
        """1 回呼び、時間切れなら True を返す。"""
        started = time.perf_counter()
        status = "ok"
        detail = ""
        try:
            is_error, text = result_text(await self.docs.call(tool, arguments))
            if is_error:
                status = "error"
                detail = text.splitlines()[0][:200] if text else ""
        except httpx.TimeoutException:
            status = "timeout"
        except httpx.HTTPError as error:
            status = "http_error"
            detail = repr(error)[:200]
        self.recorder.write(
            "call",
            client=client,
            tool=tool,
            repo=repo,
            worktree=path,
            attempt=attempt,
            dry_run=arguments.get("dry_run"),
            ref=arguments.get("ref"),
            status=status,
            detail=detail,
            sec=round(time.perf_counter() - started, 3),
        )
        if status == "ok" and tool == "delete_docs" and arguments.get("dry_run") is False:
            # 実際に削除できたら、次の呼び出しのために worktree を commit の状態へ戻す
            await asyncio.to_thread(subprocess.run, ["git", "-C", path, "checkout", "-q", "HEAD", "--", "."], check=False)
        return status == "timeout"

    async def client(self, index: int, deadline: float) -> None:
        """1 本のクライアント。平均の間隔で呼び出しを続ける。"""
        interval = 60.0 * self.args.clients / self.args.rate
        session = f"poc-{index}"
        tools = list(TOOL_WEIGHTS)
        weights = list(TOOL_WEIGHTS.values())
        await asyncio.sleep(self.rng.uniform(0, interval))
        while time.monotonic() < deadline:
            tool = self.rng.choices(tools, weights)[0]
            repo, path = self.pick_worktree()
            arguments = self.arguments(tool, repo, path, session)
            timed_out = await self.call_once(index, tool, arguments, repo, path, 1)
            if timed_out:
                await self.call_once(index, tool, arguments, repo, path, 2)
            await asyncio.sleep(self.rng.expovariate(1 / interval))

    async def grow(self, deadline: float) -> None:
        while time.monotonic() < deadline and self.active < len(self.worktrees):
            await asyncio.sleep(self.args.worktree_interval)
            self.active += 1
            self.recorder.write("worktrees", active=self.active)

    async def commits(self, deadline: float) -> None:
        develop = [path for _, path in self.worktrees if path.endswith("/develop")]
        interval = 3600.0 / self.args.commits_per_hour
        while time.monotonic() < deadline:
            await asyncio.sleep(self.rng.expovariate(1 / interval))
            path = self.rng.choice(develop)
            marker = Path(path, ".poc-commit")
            marker.write_text(f"{time.time()}\n")
            done = await asyncio.to_thread(
                subprocess.run,
                ["git", "-C", path, "commit", "-q", "-m", "poc: advance", "--", ".poc-commit"],
                check=False,
            )
            if done.returncode != 0:
                await asyncio.to_thread(subprocess.run, ["git", "-C", path, "add", ".poc-commit"], check=False)
                done = await asyncio.to_thread(
                    subprocess.run, ["git", "-C", path, "commit", "-q", "-m", "poc: advance"], check=False
                )
            self.recorder.write("commit", worktree=path, code=done.returncode)

    async def status(self, deadline: float) -> None:
        while time.monotonic() < deadline:
            started = time.perf_counter()
            status = "ok"
            try:
                is_error, _ = result_text(await self.admin.call("status", {}))
                status = "error" if is_error else "ok"
            except httpx.TimeoutException:
                status = "timeout"
            except httpx.HTTPError as error:
                status = repr(error)[:100]
            self.recorder.write("status", status=status, sec=round(time.perf_counter() - started, 3))
            await asyncio.sleep(60)

    async def sample(self, deadline: float) -> None:
        """30 秒ごとに RSS とスレッドごとの CPU、5 分ごとに SIGUSR1 のスタックを記録する。"""
        pid = self.args.server_pid
        previous: dict[str, int] = {}
        last_dump = 0.0
        while time.monotonic() < deadline:
            threads: dict[str, int] = {}
            names: dict[str, str] = {}
            with contextlib.suppress(OSError):
                for task in Path(f"/proc/{pid}/task").iterdir():
                    stat = (task / "stat").read_text()
                    name = stat[stat.index("(") + 1 : stat.rindex(")")]
                    fields = stat[stat.rindex(")") + 2 :].split()
                    threads[task.name] = int(fields[11]) + int(fields[12])
                    names[task.name] = name
            rss = 0
            with contextlib.suppress(OSError):
                for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        rss = int(line.split()[1]) // 1024
            cpu = {f"{names[tid]}:{tid}": ticks - previous.get(tid, ticks) for tid, ticks in threads.items()}
            previous = threads
            self.recorder.write("sample", rss_mb=rss, threads=len(threads), cpu_ticks=cpu)
            if time.monotonic() - last_dump >= 300:
                last_dump = time.monotonic()
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGUSR1)
                self.recorder.write("stack_dump", names=names)
            await asyncio.sleep(30)


async def run(args: argparse.Namespace) -> None:
    recorder = Recorder(Path(args.out))
    load = Load(args, recorder)
    await load.prepare()
    deadline = time.monotonic() + args.duration
    tasks = [load.client(i, deadline) for i in range(args.clients)]
    tasks += [load.grow(deadline), load.commits(deadline), load.status(deadline), load.sample(deadline)]
    await asyncio.gather(*tasks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--server-pid", type=int, required=True)
    parser.add_argument("--root", default="/tmp/pi-poc")
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=float, default=3600)
    parser.add_argument("--clients", type=int, default=32)
    parser.add_argument("--rate", type=float, default=45, help="全体の呼び出しの数（回/分）")
    parser.add_argument("--initial-worktrees", type=int, default=10)
    parser.add_argument("--worktree-interval", type=float, default=120)
    parser.add_argument("--commits-per-hour", type=float, default=20)
    parser.add_argument("--seed", type=int, default=197)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
