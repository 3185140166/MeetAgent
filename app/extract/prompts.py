# -*- coding: utf-8 -*-
"""会议结构化抽取的 prompt 模板（map-reduce 两阶段）。"""

# ---------- map：对单个窗口抽取局部信息 ----------

MAP_SYSTEM = """你是会议信息抽取助手。从给定的会议片段中抽取结构化信息。
只输出 JSON，不要输出任何解释或 markdown 代码块。
JSON 格式如下：
{
  "key_points": ["本片段的关键信息点"],
  "action_items": [{"content": "待办事项", "owner": "负责人", "due": "截止时间"}],
  "decisions": ["已达成的决策"],
  "risks": ["提到的风险或隐患"],
  "entities": [{"type": "person", "name": "实体名称"}]
}
说明：
- entities 的 type 只能是 person（人物）、project（项目）、customer（客户）、product（产品）之一。
- 某项没有内容时返回空数组 []。
- owner / due 未知时填空字符串。
- 只抽取片段中真实出现的信息，不要编造。"""


def build_map_messages(window_text: str) -> list[dict]:
    return [
        {"role": "system", "content": MAP_SYSTEM},
        {"role": "user", "content": f"会议片段：\n\n{window_text}"},
    ]


# ---------- reduce：合并所有窗口的局部信息 ----------

REDUCE_SYSTEM = """你是会议纪要汇总助手。下面是同一场会议多个片段抽取出的局部信息。
请合并、去重、归纳，只输出 JSON，不要输出任何解释或 markdown 代码块。
JSON 格式如下：
{
  "summary": "整场会议摘要，200-400字",
  "topics": ["主要议题"],
  "key_points": ["去重归纳后的关键点"],
  "action_items": [{"content": "待办事项", "owner": "负责人", "due": "截止时间"}],
  "decisions": ["决策"],
  "risks": ["风险"],
  "entities": [{"type": "person", "name": "实体名称"}]
}
说明：
- 合并语义相同或重复的项，保留信息最完整的表述。
- entities 的 type 只能是 person、project、customer、product 之一，按 name 去重。
- 不要编造局部信息中没有的内容。"""


def build_reduce_messages(partials_json: str, meeting_title: str) -> list[dict]:
    return [
        {"role": "system", "content": REDUCE_SYSTEM},
        {
            "role": "user",
            "content": f"会议标题：{meeting_title}\n\n各片段抽取的局部信息（JSON 列表）：\n\n{partials_json}",
        },
    ]
