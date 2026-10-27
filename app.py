import json
import secrets
import sys
import tempfile
import uuid
from decimal import Decimal
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
from recon import (
    LOGICAL_FIELDS,
    _clean_text,
    auto_map,
    create_report,
    detect_header_row,
    get_sheet_names,
    read_sheet_rows,
    reconcile,
)
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

    if tool_key == "reconciliation":
        return render_template("recon.html", tool=tool, active="automation")

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


def _recon_dir(token):
    base = Path(tempfile.gettempdir()) / "automonous_recon" / token
    base.mkdir(parents=True, exist_ok=True)
    return base


@app.route("/automation/recon/preview", methods=["POST"])
def recon_preview():
    file_a = request.files.get("file_a")
    file_b = request.files.get("file_b")

    if not file_a or not file_a.filename or not file_b or not file_b.filename:
        flash("Please choose both Excel files.", "error")
        return redirect(url_for("automation_tool_page", tool_key="reconciliation"))

    if not (file_a.filename.lower().endswith(".xlsx") and file_b.filename.lower().endswith(".xlsx")):
        flash("Only .xlsx files are supported.", "error")
        return redirect(url_for("automation_tool_page", tool_key="reconciliation"))

    token = uuid.uuid4().hex
    rdir = _recon_dir(token)
    path_a = rdir / "file_a.xlsx"
    path_b = rdir / "file_b.xlsx"
    file_a.save(path_a)
    file_b.save(path_b)

    sheets_a = get_sheet_names(str(path_a))
    sheets_b = get_sheet_names(str(path_b))

    sheet_a = request.form.get("sheet_a") or (sheets_a[0] if sheets_a else None)
    sheet_b = request.form.get("sheet_b") or (sheets_b[0] if sheets_b else None)

    rows_a = read_sheet_rows(str(path_a), sheet_a)
    rows_b = read_sheet_rows(str(path_b), sheet_b)

    header_a = detect_header_row(rows_a)
    header_b = detect_header_row(rows_b)

    headers_a = [_clean_text(c) for c in (rows_a[header_a] if rows_a else [])]
    headers_b = [_clean_text(c) for c in (rows_b[header_b] if rows_b else [])]

    mapping = auto_map(headers_a, headers_b)

    metadata = {
        "token": token,
        "path_a": str(path_a),
        "path_b": str(path_b),
        "file_a_name": file_a.filename,
        "file_b_name": file_b.filename,
        "sheets_a": sheets_a,
        "sheets_b": sheets_b,
        "sheet_a": sheet_a,
        "sheet_b": sheet_b,
        "header_a": header_a,
        "header_b": header_b,
        "mapping": mapping,
    }
    (rdir / "meta.json").write_text(json.dumps(metadata))

    return render_template(
        "recon_map.html",
        tool=get_automation_tool("reconciliation"),
        active="automation",
        token=token,
        metadata=metadata,
        headers_a=headers_a,
        headers_b=headers_b,
        rows_a=rows_a[:16],
        rows_b=rows_b[:16],
        logical_fields=LOGICAL_FIELDS,
    )


@app.route("/automation/recon/run", methods=["POST"])
def recon_run():
    token = request.form.get("token")
    if not token:
        flash("Session expired. Please upload the files again.", "error")
        return redirect(url_for("automation_tool_page", tool_key="reconciliation"))

    rdir = _recon_dir(token)
    meta_path = rdir / "meta.json"
    if not meta_path.exists():
        flash("Session expired. Please upload the files again.", "error")
        return redirect(url_for("automation_tool_page", tool_key="reconciliation"))

    metadata = json.loads(meta_path.read_text())

    sheet_a = request.form.get("sheet_a") or metadata["sheet_a"]
    sheet_b = request.form.get("sheet_b") or metadata["sheet_b"]
    try:
        header_a = int(request.form.get("header_a", metadata["header_a"]))
    except ValueError:
        header_a = metadata["header_a"]
    try:
        header_b = int(request.form.get("header_b", metadata["header_b"]))
    except ValueError:
        header_b = metadata["header_b"]

    # Rebuild mapping from form
    mapping = {}
    for field, label in LOGICAL_FIELDS:
        mapping[field] = {
            "a": request.form.get(f"map_{field}_a") or None,
            "b": request.form.get(f"map_{field}_b") or None,
        }
        # keep auto if not provided
        if mapping[field]["a"] is None and mapping[field]["b"] is None:
            old = metadata.get("mapping", {}).get(field, {})
            mapping[field]["a"] = old.get("a")
            mapping[field]["b"] = old.get("b")

    date_format = request.form.get("date_format", "auto")
    try:
        tolerance = Decimal(request.form.get("tolerance", "1"))
    except Exception:
        tolerance = Decimal("1")

    from recon import reconcile, create_report

    result = reconcile(
        metadata["path_a"],
        sheet_a,
        header_a,
        metadata["path_b"],
        sheet_b,
        header_b,
        mapping,
        date_format=date_format,
        tolerance=tolerance,
    )

    report_path = rdir / "report.xlsx"
    create_report(result, str(report_path))

    # Store result summary only (not full rows) in meta
    metadata["summary"] = result["summary"]
    metadata["report"] = str(report_path)
    metadata["sheet_a"] = sheet_a
    metadata["sheet_b"] = sheet_b
    metadata["header_a"] = header_a
    metadata["header_b"] = header_b
    metadata["mapping"] = mapping
    meta_path.write_text(json.dumps(metadata))

    # Prepare display rows (limit)
    display_rows = []
    for r in result["results"][:300]:
        a = r["a"] or {}
        b = r["b"] or {}
        display_rows.append({
            "inv_a": a.get("invoice_number", ""),
            "inv_b": b.get("invoice_number", ""),
            "norm_a": a.get("_invoice_norm", ""),
            "norm_b": b.get("_invoice_norm", ""),
            "gstin_a": a.get("gstin", ""),
            "gstin_b": b.get("gstin", ""),
            "supplier_a": a.get("supplier", ""),
            "supplier_b": b.get("supplier", ""),
            "date_a": a.get("invoice_date", ""),
            "date_b": b.get("invoice_date", ""),
            "value_a": a.get("invoice_value", ""),
            "value_b": b.get("invoice_value", ""),
            "row_a": a.get("_row", ""),
            "row_b": b.get("_row", ""),
            "score": r["score"],
            "status": r["status"],
            "discrepancies": "; ".join(r["discrepancies"]),
        })

    return render_template(
        "recon_results.html",
        tool=get_automation_tool("reconciliation"),
        active="automation",
        token=token,
        summary=result["summary"],
        display_rows=display_rows,
        total_results=len(result["results"]),
        excluded_a=result["excluded_a"],
        excluded_b=result["excluded_b"],
    )


@app.route("/automation/recon/download/<token>")
def recon_download(token):
    rdir = Path(tempfile.gettempdir()) / "automonous_recon" / token
    report = rdir / "report.xlsx"
    if not report.exists():
        abort(404)
    return send_file(report, as_attachment=True, download_name="reconciliation_report.xlsx")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)