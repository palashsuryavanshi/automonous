import secrets
import sys
from io import BytesIO
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from automation import run_login_in_thread
from importer import build_template, parse_import
from storage import add_credential, get_credential, load_credentials, remove_credential
from tools import TOOLS, get_tool
from automation_tools import AUTOMATION_TOOLS, get_automation_tool, list_automation_tools
from utilities import UTILITIES, get_utility, list_utilities
from pdf_tools import OcrError, pdf_to_docx
from pypdf import PdfReader, PdfWriter
import updates

updates.start_background_refresh()

_BASE_DIR = (
    Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    if getattr(sys, "frozen", False)
    else Path(__file__).parent
)

app = Flask(
    __name__,
    template_folder=str(_BASE_DIR / "templates"),
    static_folder=str(_BASE_DIR / "static"),
)
app.secret_key = secrets.token_hex(16)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


@app.route("/template")
def download_template():
    return Response(
        build_template(),
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": "attachment; "
            "filename=credentials_template.xlsx"
        },
    )


@app.route("/import", methods=["POST"])
def import_credentials():
    file = request.files.get("file")

    if not file or not file.filename:
        flash("Please choose an .xlsx file to import.", "error")
        return redirect(url_for("manage_credentials"))

    try:
        created, errors = parse_import(file.stream)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("manage_credentials"))

    for tool_key, username, password in created:
        add_credential(tool_key, username, password)

    if created:
        flash(f"Imported {len(created)} credential(s).", "success")

    for row, message in errors:
        flash(f"Row {row}: {message}", "error")

    if not created and not errors:
        flash("The file contains no data to import.", "error")

    return redirect(url_for("manage_credentials"))


@app.context_processor
def inject_updates():
    update = {
        "available": updates.has_update(),
        "current": updates.APP_VERSION,
        "latest": None,
    }
    info = updates.latest_release()
    if info:
        update["latest"] = info
    return {"UPDATE": update}


@app.route("/api/update-check")
def api_update_check():
    info = updates.check_update()
    return {
        "current_version": updates.APP_VERSION,
        "has_update": updates.has_update(),
        "latest": info,
    }


@app.context_processor
def inject_tools():
    return {"TOOLS": TOOLS}


@app.context_processor
def inject_automation_tools():
    return {"AUTOMATION_TOOLS": AUTOMATION_TOOLS}


@app.context_processor
def inject_utilities():
    return {"UTILITIES": UTILITIES}


@app.route("/")
def index():
    credentials = load_credentials()

    accents = {
        "gst": "#ff9800",
        "incometax": "#1971c2",
        "tds": "#0c8599",
    }

    tools = []
    for key, tool in TOOLS.items():
        account_count = len(credentials.get(key, []))
        tools.append(
            {
                **tool,
                "account_count": account_count,
                "accent": accents.get(key, "#1b6a50"),
            }
        )

    return render_template("index.html", tools=tools, active=None)


@app.route("/manage")
def manage_credentials():
    credentials = load_credentials()

    groups = [
        (tool, credentials.get(tool["key"], []))
        for tool in TOOLS.values()
    ]

    return render_template(
        "manage.html",
        groups=groups,
        active="manage",
    )


@app.route("/tool/<tool_key>")
def tool_page(tool_key):
    tool = get_tool(tool_key)
    if not tool:
        abort(404)

    accounts = load_credentials().get(tool_key, [])

    accents = {
        "gst": "#ff9800",
        "incometax": "#1971c2",
        "tds": "#0c8599",
    }

    return render_template(
        "tool_detail.html",
        tool=tool,
        accounts=accounts,
        active=tool_key,
        accent=accents.get(tool_key, "#1b6a50"),
    )


@app.route("/save", methods=["POST"])
def save_credential():
    tool_key = request.form["tool"]

    if not get_tool(tool_key):
        abort(404)

    add_credential(
        tool_key,
        request.form["username"],
        request.form["password"],
    )

    return redirect(url_for("manage_credentials"))


@app.route("/delete", methods=["POST"])
def delete_credential():
    tool_key = request.form["tool"]

    if not get_tool(tool_key):
        abort(404)

    remove_credential(tool_key, request.form["username"])

    return redirect(url_for("manage_credentials"))


@app.route("/tool/<tool_key>/login", methods=["POST"])
def login_run(tool_key):
    tool = get_tool(tool_key)
    if not tool:
        abort(404)

    username = request.form["username"]

    config = tool

    if tool.get("subtypes"):
        subtype_key = request.form.get("subtype") or tool["subtypes"][0]["key"]
        subtype = next(
            (s for s in tool["subtypes"] if s["key"] == subtype_key),
            None,
        )

        if not subtype:
            abort(404)

        config = {**tool, **subtype}

    credentials = get_credential(tool_key, username)

    if credentials:
        run_login_in_thread(config, *credentials)

    return redirect(url_for("tool_page", tool_key=tool_key))


@app.route("/automation")
def automation_hub():
    tools = list_automation_tools()
    return render_template(
        "automation.html",
        tools=tools,
        active="automation",
    )


@app.route("/automation/<tool_key>")
def automation_tool_page(tool_key):
    tool = get_automation_tool(tool_key)
    if not tool:
        abort(404)
    return render_template(
        "automation_tool.html",
        tool=tool,
        active="automation",
    )


@app.route("/utilities")
def utilities_hub():
    tools = list_utilities()
    return render_template(
        "utilities.html",
        tools=tools,
        active="utilities",
    )


@app.route("/utilities/<tool_key>")
def utility_page(tool_key):
    tool = get_utility(tool_key)
    if not tool:
        abort(404)

    if tool_key == "pdf_merge":
        return render_template("pdf_merge.html", tool=tool, active="utilities")

    if tool_key == "pdf_to_word":
        return render_template("pdf_to_word.html", tool=tool, active="utilities")

    return render_template(
        "utility.html",
        tool=tool,
        active="utilities",
    )


@app.route("/utilities/pdf_merge/merge", methods=["POST"])
def pdf_merge_run():
    files = request.files.getlist("files")

    if not files or all(not f.filename for f in files):
        return {"error": "Please choose at least one PDF file."}, 400

    writer = PdfWriter()

    try:
        for uploaded in files:
            if not uploaded or not uploaded.filename:
                continue
            reader = PdfReader(uploaded.stream)
            for page in reader.pages:
                writer.add_page(page)
    except Exception as exc:
        return {"error": f"Could not read one of the PDFs: {exc}"}, 400

    buffer = BytesIO()
    writer.write(buffer)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="merged.pdf",
    )


@app.route("/utilities/pdf_to_word/convert", methods=["POST"])
def pdf_to_word_run():
    uploaded = request.files.get("file")

    if not uploaded or not uploaded.filename:
        return {"error": "Please choose a PDF file."}, 400

    try:
        docx_bytes, _ocr_pdf = pdf_to_docx(uploaded.read())
    except OcrError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:
        return {"error": f"Conversion failed: {exc}"}, 500

    filename = Path(uploaded.filename).stem or "converted"
    return send_file(
        BytesIO(docx_bytes),
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        as_attachment=True,
        download_name=f"{filename}.docx",
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)