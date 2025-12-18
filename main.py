import sqlite3
import os
from datetime import datetime

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

DB = os.environ.get("DB_PATH", "db.sqlite")


def init_db() -> None:
    with sqlite3.connect(DB) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS qr_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            answer TEXT NOT NULL,
            other_text TEXT,
            created_at TEXT NOT NULL
        )
        """)
        conn.commit()


init_db()


def label_answer(a: str) -> str:
    return {
        "rating": "Рейтинг блюд",
        "kcal_bju": "Подбор по КБЖУ",
        "other": "Другое",
        "not_interesting": "Не интересно",
    }.get(a, a)


@app.get("/qr/{source}", response_class=HTMLResponse)
def qr_page(request: Request, source: str, ok: int = 0):
    # ok=1 приходит после submit через redirect -> показываем "Спасибо" и скрываем форму (в html)
    return templates.TemplateResponse(
        "qr.html",
        {"request": request, "source": source, "ok": ok}
    )


@app.post("/submit")
def submit(
    source: str = Form(...),
    answer: str = Form(...),
    other_text: str = Form("")
):
    # Сохраняем other_text только если выбран "other"
    if answer != "other":
        other_text_db = None
    else:
        other_text_db = (other_text or "").strip() or None

    with sqlite3.connect(DB) as conn:
        conn.execute(
            """
            INSERT INTO qr_responses (source, answer, other_text, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (source, answer, other_text_db, datetime.utcnow().isoformat())
        )
        conn.commit()

    # ВАЖНО: редирект, чтобы:
    # 1) не было повторной отправки при refresh
    # 2) "Спасибо" показывалось только после submit
    return RedirectResponse(url=f"/qr/{source}?ok=1", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin():
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row

        total = conn.execute("SELECT COUNT(*) AS c FROM qr_responses").fetchone()["c"]

        by_answer = conn.execute("""
            SELECT answer, COUNT(*) AS c
            FROM qr_responses
            GROUP BY answer
            ORDER BY c DESC
        """).fetchall()

        by_source = conn.execute("""
            SELECT source, COUNT(*) AS c
            FROM qr_responses
            GROUP BY source
            ORDER BY c DESC
        """).fetchall()

        by_source_answer = conn.execute("""
            SELECT source, answer, COUNT(*) AS c
            FROM qr_responses
            GROUP BY source, answer
            ORDER BY source ASC, c DESC
        """).fetchall()

        last_20 = conn.execute("""
            SELECT created_at, source, answer, COALESCE(other_text, '') AS other_text
            FROM qr_responses
            ORDER BY id DESC
            LIMIT 20
        """).fetchall()

    def ul(rows, key1, key2, map1=None):
        items = []
        for r in rows:
            v1 = r[key1]
            if map1:
                v1 = map1(v1)
            items.append(f"<li><b>{v1}</b>: {r[key2]}</li>")
        return "<ul>" + "".join(items) + "</ul>"

    # Матрица: source -> ответы
    matrix = {}
    for r in by_source_answer:
        matrix.setdefault(r["source"], []).append((label_answer(r["answer"]), r["c"]))

    matrix_html = ""
    for src, arr in matrix.items():
        matrix_html += f"<h3 style='margin:12px 0 6px'>{src}</h3><ul>"
        for ans, c in arr:
            matrix_html += f"<li>{ans}: {c}</li>"
        matrix_html += "</ul>"

    last_html = "<table><tr><th>Когда</th><th>Source</th><th>Ответ</th><th>Другое</th></tr>"
    for r in last_20:
        last_html += (
            "<tr>"
            f"<td>{r['created_at']}</td>"
            f"<td>{r['source']}</td>"
            f"<td>{label_answer(r['answer'])}</td>"
            f"<td>{(r['other_text'] or '')[:120]}</td>"
            "</tr>"
        )
    last_html += "</table>"

    html = f"""
    <!doctype html>
    <html lang="ru">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Admin</title>
      <style>
        body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif;padding:20px;max-width:900px;margin:0 auto;color:#111}}
        h1{{margin:0 0 10px}}
        .card{{border:1px solid #e6e6e6;border-radius:12px;padding:14px;margin:12px 0}}
        ul{{margin:8px 0 0 18px}}
        table{{width:100%;border-collapse:collapse;font-size:12px}}
        th,td{{border-bottom:1px solid #eee;padding:8px;text-align:left;vertical-align:top}}
        .muted{{opacity:.7}}
        .grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
        @media (max-width:700px){{.grid{{grid-template-columns:1fr}}}}
      </style>
    </head>
    <body>
      <h1>QR статистика</h1>
      <div class="muted">Всего ответов: <b>{total}</b></div>

      <div class="grid">
        <div class="card">
          <h2 style="margin:0 0 8px;font-size:16px;">По ответам</h2>
          {ul(by_answer, "answer", "c", map1=label_answer)}
        </div>

        <div class="card">
          <h2 style="margin:0 0 8px;font-size:16px;">По зонам (source)</h2>
          {ul(by_source, "source", "c")}
        </div>
      </div>

      <div class="card">
        <h2 style="margin:0 0 8px;font-size:16px;">Зоны × ответы</h2>
        {matrix_html}
      </div>

      <div class="card">
        <h2 style="margin:0 0 8px;font-size:16px;">Последние 20</h2>
        {last_html}
      </div>
    </body>
    </html>
    """
    return HTMLResponse(html)