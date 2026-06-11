# -*- coding: utf-8 -*-
import sys
import asyncio
import io

from app.qa.service import ask


async def main(question: str, user_id: str = None) -> None:
    print(f"问题：{question}\n")
    print("检索中...\n")

    result = await ask(question, user_id=user_id)

    print("=" * 60)
    print(result["answer"])
    print("=" * 60)

    if result["sources"]:
        print(f"\n引用来源（共 {len(result['sources'])} 个片段）：\n")
        for i, s in enumerate(result["sources"], 1):
            print(f"[{i}] {s['title']} | {s['create_time']} | 发言人：{s['speaker']} | chunk#{s['chunk_index']}")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    if len(sys.argv) < 2:
        print("用法: python -m app.qa.ask \"你的问题\"")
        sys.exit(1)

    question = sys.argv[1]
    user_id = sys.argv[2] if len(sys.argv) > 2 else None

    asyncio.run(main(question, user_id))
