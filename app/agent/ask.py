# -*- coding: utf-8 -*-
"""Agent 模式 CLI 入口。
用法：python -m app.agent.ask "问题" [user_id]
"""

import sys
import io
import asyncio

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        print("用法：python -m app.agent.ask \"问题\" [user_id]")
        sys.exit(1)

    question = sys.argv[1]
    user_id = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"问题：{question}")
    if user_id:
        print(f"用户：{user_id}")
    print()

    from app.agent.loop import run_agent
    result = asyncio.run(run_agent(question, user_id=user_id))

    if result["tool_calls_log"]:
        print("── 工具调用过程 ──")
        for call in result["tool_calls_log"]:
            args_str = ", ".join(f"{k}={v}" for k, v in call["arguments"].items())
            print(f"  第{call['turn']}轮  {call['tool']}({args_str})")
            preview = call["result_preview"].replace("\n", " ")[:120]
            print(f"         → {preview}")
        print()

    print("=" * 60)
    print(result["answer"])
    print("=" * 60)


if __name__ == "__main__":
    main()
