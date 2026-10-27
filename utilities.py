"""Registry of general-purpose utility tools.

These are lightweight helpers (calculators, converters, formatters) that do not
depend on the credential vault or portal automation. They are registered here
as plugins so new utilities can be added without touching the core app.
"""

UTILITIES = {
    "pdf_merge": {
        "key": "pdf_merge",
        "name": "PDF Merger",
        "description": "Combine multiple PDF files into one, with drag-and-drop reordering.",
        "status": "ready",
    },
    "pdf_to_word": {
        "key": "pdf_to_word",
        "name": "PDF to Word",
        "description": "OCR a PDF (including scanned pages) and convert it to a .docx file.",
        "status": "ready",
    },
}


def get_utility(tool_key):
    return UTILITIES.get(tool_key)


def list_utilities():
    return list(UTILITIES.values())