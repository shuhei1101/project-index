"""`project-index serve` の処理と部品の配線。"""

from __future__ import annotations

import errno
import logging
import os
import socket
import sys
import threading
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any

from project_index.features.describe.source_checks import SourceChecks
from project_index.features.lifecycle.control import RestartControl
from project_index.features.lifecycle.types import SERVE_ARGV, SHUTDOWN_WAIT_FACTOR
from project_index.features.prompt_doc.runtime import PromptSet, load_prompts, prompts_dir
from project_index.features.prompt_doc.types import PromptInvalidError
from project_index.features.settings.query import (
    config_path,
    listen_port,
    load_terminal_config,
    log_unknown_keys,
)
from project_index.features.settings.types import TerminalConfig, TerminalConfigInvalidError
from project_index.features.sources.registry import SourceRegistry
from project_index.features.sources.types import ServedSource, SourceStatus
from project_index.server.mcp.result import mcp_prompt_ids

if TYPE_CHECKING:
    import argparse

    from project_index.features.convert.service import ConvertService
    from project_index.features.documents.store import DocumentStore
    from project_index.features.validation.service import DocumentChecker

EXIT_CONFIG_INVALID = 2
EXIT_PORT_IN_USE = 3
EXIT_PROMPT_INVALID = 4
EXIT_ROOT_NOT_FOUND = 2
LOG_FILE = "project-index.log"
LOG_MAX_BYTES = 5_000_000
LOG_BACKUPS = 3
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
BIND_ERRORS = (errno.EADDRINUSE, errno.EACCES)

logger = logging.getLogger(__name__)


class PortInUseError(OSError):
    """待ち受けのアドレスとポートで待ち受けられないことを表す。"""

    def __init__(self, bind: str, port: int) -> None:
        super().__init__(f"{bind}:{port} は使用中です")
        self.bind = bind
        self.port = port


@dataclass(frozen=True)
class Handlers:
    """入口（読み取り API・MCP）が使う部品を 1 回だけ作って束ねたもの。"""

    terminal: TerminalConfig
    registry: SourceRegistry
    store: Any
    snapshots: Any
    converter: Any
    seen: Any
    locks: Any
    settings_lock: threading.Lock
    checker: Any
    reload_sources: Callable[[TerminalConfig], list[SourceStatus]]
    restart: RestartControl
    prompts: PromptSet
    checks: SourceChecks


def _setup_logging(log_dir: Path) -> list[logging.Handler]:
    """ログを標準エラーと `{log_dir}/project-index.log` に書く設定にし、足したハンドラを返す。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
        RotatingFileHandler(
            log_dir / LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        ),
    ]
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    return handlers


def _close_logging(log_handlers: list[logging.Handler]) -> None:
    """足したログのハンドラを外して閉じる。"""
    root = logging.getLogger()
    for handler in log_handlers:
        root.removeHandler(handler)
        handler.close()


def _report_invalid(error: TerminalConfigInvalidError) -> None:
    """端末の設定の違反を、標準エラーに 1 行ずつ出す。"""
    if error.violations:
        for violation in error.violations:
            print(f"{error.file}: {violation.path}: {violation.rule}", file=sys.stderr)
    else:
        print(error.message, file=sys.stderr)


def _report_port(bind: str, port: int) -> None:
    """ポートが使用中のことを標準エラーに出す。"""
    print(
        f"{bind}:{port} は使用中です。PROJECT_INDEX_PORT で別のポートを指定できます",
        file=sys.stderr,
    )


def run_serve(args: argparse.Namespace) -> int:
    """端末の設定を読み、配信元を配線して待ち受け、停止の合図まで動く。"""
    import uvicorn

    from project_index.server.app import build_app

    try:
        terminal = load_terminal_config(config_path(os.environ))
        port = listen_port(terminal, os.environ)
    except TerminalConfigInvalidError as error:
        _report_invalid(error)
        return EXIT_CONFIG_INVALID
    log_handlers = _setup_logging(terminal.log_dir)
    log_unknown_keys(terminal)
    try:
        try:
            check_port(terminal.bind, port)
        except PortInUseError:
            _report_port(terminal.bind, port)
            return EXIT_PORT_IN_USE
        try:
            handlers = build_handlers(terminal)
        except PromptInvalidError as error:
            for problem in error.problems:
                print(problem.line(), file=sys.stderr, flush=True)
            return EXIT_PROMPT_INVALID
        app = build_app(handlers)
        print(f"http://{terminal.bind}:{port}/", flush=True)
        start_loading(handlers)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=terminal.bind,
                port=port,
                log_config=None,
                # 処理中の要求を待つ上限（スクリプトの実行が一番長い要求になる）
                timeout_graceful_shutdown=int(terminal.script_timeout_sec * SHUTDOWN_WAIT_FACTOR),
            )
        )
        handlers.restart.attach(server)
        server.run()
        if not server.started:
            # 確かめた後に他のプロセスがポートを取った
            _report_port(terminal.bind, port)
            return EXIT_PORT_IN_USE
        # 再起動を要求されて止まったときは、同じプロセスを `serve` で置き換える
        if handlers.restart.requested:
            _close_logging(log_handlers)
            os.execv(sys.executable, [sys.executable, *SERVE_ARGV])  # noqa: S606
        return 0
    finally:
        _close_logging(log_handlers)


def start_loading(handlers: Handlers) -> threading.Thread:
    """配信元の行ごとの読み込みと、全ての行の後の検査を裏のスレッドで始める。"""

    def work() -> None:
        try:
            handlers.registry.load(handlers.terminal)
            check_sources(handlers.registry.served(), store=handlers.store, checks=handlers.checks)
            for source in handlers.registry.served():
                print(source.id, flush=True)
        except Exception:
            logger.exception("配信元の読み込みに失敗した")

    thread = threading.Thread(target=work, name="project-index-loading", daemon=True)
    thread.start()
    return thread


def check_port(bind: str, port: int) -> None:
    """待ち受けのアドレスとポートで待ち受けられるかを、一度 bind して確かめる。"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        # uvicorn と同じく SO_REUSEADDR を付け、閉じたばかりの接続が残るポートは使用中にしない
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((bind, port))
        except OSError as error:
            if error.errno in BIND_ERRORS:
                raise PortInUseError(bind, port) from error
            raise


def build_handlers(terminal: TerminalConfig) -> Handlers:
    """端末の設定から部品を 1 回だけ作り、配線済みの関数にする（配信元は読まない）。"""
    from project_index.features.convert.service import ConvertService
    from project_index.features.describe.source_checks import SourceChecks
    from project_index.features.documents.store import DocumentStore
    from project_index.features.history.snapshot import SnapshotStore
    from project_index.features.seen.store import SeenStore
    from project_index.features.validation.service import DocumentChecker
    from project_index.features.write.locks import SourceLocks

    # プロンプトの YAML が違反するときは、state_dir を作る前に止める
    prompts = load_prompts(prompts_dir(os.environ), required=mcp_prompt_ids())
    state_dir = terminal.state_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    snapshots = SnapshotStore(state_dir / "snapshots")
    store = DocumentStore(snapshots)
    converter = ConvertService(state_dir / "converted", store, terminal.script_timeout_sec)
    seen = SeenStore(state_dir / "seen.sqlite3", terminal.seen_retention_days)
    checker = DocumentChecker(store, terminal.script_timeout_sec)
    checks = SourceChecks()

    def on_rebuilt(source: ServedSource) -> None:
        discard_source_caches(
            [source], store=store, checker=checker, converter=converter, checks=checks
        )

    registry = SourceRegistry(on_rebuilt=on_rebuilt, loading=True)

    def reload(new_terminal: TerminalConfig) -> list[SourceStatus]:
        statuses = reload_sources(
            new_terminal,
            registry=registry,
            store=store,
            checker=checker,
            converter=converter,
            checks=checks,
        )
        # 端末の設定の API が起動時の一覧ではなく保存した一覧を返すよう、起動時の端末の設定の一覧を差し替える
        terminal.sources[:] = new_terminal.sources
        # 引数なしの describe と端末の設定の API が、読み直した端末の設定の知らないキーを返すよう差し替える
        terminal.unknown_keys[:] = new_terminal.unknown_keys
        # 起動時の配信元の読み込みは起動の端末の設定のままで、知らないキーは起動のときに書いている
        if new_terminal is not terminal:
            log_unknown_keys(new_terminal)
        return statuses

    return Handlers(
        terminal=terminal,
        registry=registry,
        store=store,
        snapshots=snapshots,
        converter=converter,
        seen=seen,
        locks=SourceLocks(),
        settings_lock=threading.Lock(),
        checker=checker,
        reload_sources=reload,
        restart=RestartControl(),
        prompts=prompts,
        checks=checks,
    )


def reload_sources(
    terminal: TerminalConfig,
    *,
    registry: SourceRegistry,
    store: DocumentStore,
    checker: DocumentChecker,
    converter: ConvertService,
    checks: SourceChecks,
) -> list[SourceStatus]:
    """配信元の一覧を読み直し、配信元の内容を控えた部品の控えを捨てる。"""
    statuses = registry.reload(terminal)
    discard_source_caches(
        registry.served(), store=store, checker=checker, converter=converter, checks=checks
    )
    return statuses


def discard_source_caches(
    sources: list[ServedSource],
    *,
    store: DocumentStore,
    checker: DocumentChecker,
    converter: ConvertService,
    checks: SourceChecks,
) -> None:
    """配信元の内容を控えた部品の控えを捨て、渡した配信元ごとのずれと警告をログに書く。"""
    store.clear()
    checker.clear()
    converter.clear()
    check_sources(sources, store=store, checks=checks)


def check_sources(
    sources: list[ServedSource], *, store: DocumentStore, checks: SourceChecks
) -> None:
    """渡した配信元ごとに検査して結果を持たせ、ずれと警告をログに書く。"""
    for source in sources:
        # 検査の結果を控えに持たせ、`describe` の警告が読めるようにする
        check = checks.refresh(store, source)
        report = check.report
        for label, values in (
            ("metadata の列の欠け", report.missing_refs),
            ("管理用の YAML に無いファイル", report.unindexed_files),
            ("ファイルが無い行", report.missing_body_files),
            ("どの文書にも該当しない関連", report.unresolved_related),
        ):
            if values:
                logger.warning(
                    "%s: %s %d 件: %s", report.source_id, label, len(values), "、".join(values)
                )
        for violation in report.alias_violations:
            logger.warning(
                "%s: エイリアスのキーの違反: %s: %s: %s",
                report.source_id,
                violation.doc,
                violation.path,
                violation.rule,
            )
        for warning in check.nav:
            logger.warning("%s: nav: %s: %s", source.id, warning.path, warning.rule)


def run_files(args: argparse.Namespace) -> int:
    """`project-index files` の解析結果で範囲を集め、載せるファイルを 1 行ずつ出す。"""
    from project_index.features.documents.indexable import indexable_files

    root = Path(args.root)
    if not root.is_dir():
        print(f"{root}: フォルダがありません", file=sys.stderr)
        return EXIT_ROOT_NOT_FOUND
    for path in indexable_files(root, args.paths, exclude=args.exclude):
        print(path)
    return 0


def run_migrate(args: argparse.Namespace) -> int:
    """`project-index migrate` の解析結果で対象を決め、当てる手順を表示するか当てる。"""
    from project_index.features.migrate.service import (
        apply_migration,
        plan_migration,
        resolve_target,
    )
    from project_index.features.migrate.types import MigrationError

    try:
        target = resolve_target(args.source, env=os.environ)
        data, steps = plan_migration(target)
        # 手順を表示するだけで、書き換えない
        if args.plan:
            for step in steps:
                suffix = " [destructive]" if step.destructive else ""
                print(f"{step.version}: {step.description}{suffix}")
            return 0
        # `--record` は手順を当てず、バージョンだけを書き換える
        if args.record:
            backup = apply_migration(
                target, data, [], allow_destructive=False, now=datetime.now(UTC)
            )
            print(
                f"{target.file} の version を {target.current} にしました（バックアップ: {backup}）"
            )
            return 0
        if not steps:
            print(f"移し替えは要りません（version {target.current}）")
            return 0
        backup = apply_migration(
            target,
            data,
            steps,
            allow_destructive=args.allow_destructive,
            now=datetime.now(UTC),
        )
        print(
            f"{target.file} を version {target.current} に移し替えました（バックアップ: {backup}）"
        )
        return 0
    except MigrationError as error:
        print(str(error), file=sys.stderr)
        return error.exit_code
