"""演示占位文件：由 DICT-001 任务完成，不含真实辞书处理逻辑。"""


def parse_query(text):
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return {"filters": {}, "semantic_query": text}
