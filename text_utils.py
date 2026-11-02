from typing import List

TELEGRAM_MAX_MESSAGE_LENGTH = 4000


def split_telegram_markdown_chunks(text: str, max_len: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> List[str]:
    """
    Splits long AI responses into safe chunks <= max_len characters for Telegram,
    preserving Markdown code fences (```) across boundaries so syntax highlighting never breaks.
    """
    if not text:
        return [""]
    if len(text) <= max_len:
        return [text]

    lines = text.split("\n")
    chunks: List[str] = []
    current_lines: List[str] = []
    current_len = 0
    in_code_block = False
    code_fence_header = "```"

    for line in lines:
        stripped = line.strip()
        line_len = len(line) + 1  # +1 for newline

        # Handle single gigantic line exceeding max_len
        if line_len > max_len - 50:
            if current_lines:
                chunk_str = "\n".join(current_lines)
                if in_code_block:
                    chunk_str += "\n```"
                chunks.append(chunk_str)
                current_lines = [code_fence_header] if in_code_block else []
                current_len = len(code_fence_header) + 1 if in_code_block else 0

            step = max_len - 100
            for i in range(0, len(line), step):
                sub = line[i : i + step]
                if in_code_block:
                    chunks.append(f"{code_fence_header}\n{sub}\n```")
                else:
                    chunks.append(sub)
            continue

        if current_len + line_len > max_len - 20:
            chunk_str = "\n".join(current_lines)
            if in_code_block:
                chunk_str += "\n```"
            chunks.append(chunk_str)
            current_lines = [code_fence_header] if in_code_block else []
            current_len = (len(code_fence_header) + 1) if in_code_block else 0

        if stripped.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_fence_header = stripped
            else:
                in_code_block = False
                code_fence_header = "```"

        current_lines.append(line)
        current_len += line_len

    if current_lines:
        chunk_str = "\n".join(current_lines)
        if in_code_block:
            chunk_str += "\n```"
        chunks.append(chunk_str)

    return chunks
