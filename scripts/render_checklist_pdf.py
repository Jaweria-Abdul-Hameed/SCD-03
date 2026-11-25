import subprocess
from pathlib import Path

import markdown

md_text = Path("SCD_Assignment03_RAGOps_Implementation_Checklist.md").read_text(
    encoding="utf-8"
)
formatted = md_text.replace(
    "- [x]", '<span class="chk chk-done">&#x2611;</span>'
).replace("- [ ]", '<span class="chk">&#x2610;</span>')
body_html = markdown.markdown(formatted, extensions=["tables", "fenced_code"])

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>CS4032 Assignment 03 - RAGOps Implementation Checklist</title>
<style>
  @page {{ size: A4; margin: 12mm; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; font-size: 8.5pt; color: #1e293b; line-height: 1.35; }}
  h1 {{ font-size: 15pt; color: #0f172a; border-bottom: 2px solid #0284c7; padding-bottom: 4px; margin-bottom: 6px; }}
  h2 {{ font-size: 11pt; color: #0369a1; border-bottom: 1px solid #cbd5e1; padding-bottom: 2px; margin-top: 10px; }}
  h3 {{ font-size: 9.5pt; color: #334155; margin-top: 6px; }}
  ul {{ padding-left: 18px; margin: 4px 0; }}
  li {{ margin-bottom: 2px; list-style-type: none; }}
  .chk {{ font-size: 10pt; color: #64748b; margin-right: 4px; }}
  .chk-done {{ color: #16a34a; font-weight: bold; }}
  code {{ font-family: Consolas, monospace; font-size: 8pt; background: #f1f5f9; padding: 1px 3px; border-radius: 2px; color: #0284c7; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 8pt; margin: 6px 0; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 3px 6px; text-align: left; }}
  th {{ background: #f8fafc; font-weight: bold; }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""

tmp_html = Path("checklist_tmp.html")
tmp_html.write_text(html, encoding="utf-8")

abs_html = tmp_html.resolve().as_uri()
abs_pdf = str(
    Path("SCD_Assignment03_RAGOps_Implementation_Checklist.pdf").resolve()
).replace("\\", "/")

cmd = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "--headless=new",
    "--disable-gpu",
    "--no-pdf-header-footer",
    f"--print-to-pdf={abs_pdf}",
    abs_html,
]
subprocess.run(cmd, check=True)
tmp_html.unlink()
print("Recompiled SCD_Assignment03_RAGOps_Implementation_Checklist.pdf successfully")
