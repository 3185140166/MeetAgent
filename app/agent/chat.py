# -*- coding: utf-8 -*-
"""多轮对话 CLI 入口。
用法：python -m app.agent.chat [user_id]
输入 'exit' 退出，'clear' 清空对话历史。
"""

import sys
import io
import asyncio

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def main():
    user_id = sys.argv[1] if len(sys.argv) > 1 else None
    from app.agent.loop import run_agent

    print("=" * 50)
    print("MeetAgent 多轮对话")
    print(f"用户：{user_id or '全局'}")
    print("exit 退出 | clear 清空历史")
    print("=" * 50)

    history = []

    while True:
        try:
            question = input("\n你：").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n对话结束。")
            break

        if not question:
            continue
        if question.lower() in ("exit", "quit", "退出"):
            print("对话结束。")
            break
        if question.lower() in ("clear", "清空"):
            history = []
            print("（对话历史已清空）")
            continue

        result = asyncio.run(run_agent(question, user_id=user_id, history=history))
        history = result["history"]

        if result["tool_calls_log"]:
            tools_used = ", ".join(c["tool"] for c in result["tool_calls_log"])
            print(f"  [工具: {tools_used}]")

        print(f"\n助手：{result['answer']}")


if __name__ == "__main__":
    main()
