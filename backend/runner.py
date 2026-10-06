"""Frozen backend entry point. The desktop owns its stdin and lifetime."""
from __future__ import annotations

import argparse
import os
import socket
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', required=True)
    parser.add_argument('--resources', required=True)
    parser.add_argument('--frontend', required=True)
    args = parser.parse_args()
    os.environ['QD_HOME'] = args.home
    os.environ['QD_RESOURCES'] = args.resources
    os.environ['QD_FRONTEND'] = args.frontend
    # Testing bypasses must never reach a shipped application's compile path.
    os.environ.pop('QUESTION_VIEWER_SKIP_LATEX_VALIDATION', None)
    from backend.windows_job import contain_process_tree
    contain_process_tree()
    from backend.runtime import initialize_seed
    initialize_seed()
    from backend.app import app, exports, papers, agent
    from backend.latex_service import cancel_compilations
    import uvicorn
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    config = uvicorn.Config(app, host='127.0.0.1', port=sock.getsockname()[1], log_level='info', timeout_graceful_shutdown=3)
    server = uvicorn.Server(config)

    def shutdown():
        exports.stop()
        papers.stop()
        agent.stop()
        cancel_compilations()
        server.should_exit = True

    app.state.shutdown = shutdown

    def watch_parent():
        import sys
        # A daemon blocked in BufferedReader holds its lock during interpreter
        # shutdown. Raw OS reads avoid the fatal buffered-stdin teardown race.
        try:
            while os.read(sys.stdin.fileno(),4096):pass
        except OSError:pass
        if not server.should_exit:shutdown()

    threading.Thread(target=watch_parent, daemon=True, name='desktop-owner').start()
    print(f'QD_PORT={sock.getsockname()[1]}', flush=True)
    try:
        server.run(sockets=[sock])
    finally:
        shutdown()
        sock.close()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
