"""Registry of automation tools for repetitive CA workflows.

Each tool is a small, self-contained plugin. A tool entry only describes
metadata for now; the actual implementation lands in its own module and is
wired up through ``run`` (or a dedicated route) as it matures.

Keeping this registry separate from ``tools/`` (which holds tax-portal login
definitions) lets us grow the automation surface without touching the
credential vault.
"""

AUTOMATION_TOOLS = {
    "reconciliation": {
        "key": "reconciliation",
        "name": "2A/2B or R1 with Books Reconciliation Tool",
        "description": "Intelligently reconcile GSTR-2A/2B or GSTR-1 invoice data against your books using fuzzy matching, invoice normalization, discrepancy detection, and downloadable Excel reports.",
        "status": "ready",
    },
}


def get_automation_tool(tool_key):
    return AUTOMATION_TOOLS.get(tool_key)


def list_automation_tools():
    return list(AUTOMATION_TOOLS.values())