"""Registry of automation tools for repetitive CA workflows.

Each tool is a small, self-contained plugin. A tool entry only describes
metadata for now; the actual implementation lands in its own module and is
wired up through ``run`` (or a dedicated route) as it matures.

Keeping this registry separate from ``tools/`` (which holds tax-portal login
definitions) lets us grow the automation surface without touching the
credential vault.
"""

AUTOMATION_TOOLS = {}


def get_automation_tool(tool_key):
    return AUTOMATION_TOOLS.get(tool_key)


def list_automation_tools():
    return list(AUTOMATION_TOOLS.values())