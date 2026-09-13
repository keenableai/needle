from needle.shared.search.queryops import QueryOps

SYSTEM_PROMPT = (
    "Search the web for the user's query, then answer in one short paragraph. "
    "Cite every source you rely on."
)


def user_prompt(ops: QueryOps) -> str:
    parts = [ops.text]
    if ops.after:
        parts.append(f"Only use sources published after {ops.after.isoformat()}.")
    if ops.before:
        parts.append(f"Only use sources published before {ops.before.isoformat()}.")
    return " ".join(parts)
