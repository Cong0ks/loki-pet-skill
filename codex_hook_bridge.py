# -*- coding: utf-8 -*-
"""Codex hook 入口: 复用 hook_bridge 的 Loki 文件队列协议。"""
import sys

import hook_bridge


def main():
    if "--agent" not in sys.argv:
        sys.argv.extend(["--agent", "codex"])
    hook_bridge.main()


if __name__ == "__main__":
    main()
