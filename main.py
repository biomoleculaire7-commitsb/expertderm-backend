"""
Backend API — ExpertDerm / SkinSense
--------------------------------------
يربط بين تطبيق الطبيب المعالج (SkinSense) ومنصة الخبير (ExpertDerm).

Endpoints:
  POST /api/cases              -> إحالة حالة جديدة من التطبيق
  GET  /api/cases               -> جلب كل الحالات (تدعم فلترة status)
  GET  /api/cases/{case_id}     -> جلب حالة واحدة بالتفصيل
  POST /api/cases/{case_id}/report -> إرسال تقرير الخبير (من المنصة)
  GET  /api/health              -> فحص أن الخادم يعمل
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import json
import time
import os
import random
import string

DB_PATH = os.environ.get("DB_PATH", "expertderm.db")

app = FastAPI(title="SkinSense / ExpertDerm API")

# السماح بالاتصال من أي أصل (يكفي لهذه المرحلة التجريبية؛ يُفضّل تقييده لاحقًا لدومين تطبيقك فقط)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id TEXT PRIMARY KEY,
            hash TEXT,
            timestamp INTEGER,
            risk TEXT,
            risk_label_ar TEXT,
            risk_label_en TEXT,
            age TEXT,
            sex_ar TEXT,
            sex_en TEXT,
            location_ar TEXT,
            location_en TEXT,
            attending_note_ar TEXT,
            attending_note_en TEXT,
            probs_json TEXT,
            marker INTEGER,
            marker_label_ar TEXT,
            marker_label_en TEXT,
            image_base64 TEXT,
            status TEXT DEFAULT 'pending',
            report_verdict TEXT,
            report_notes TEXT,
            report_timestamp INTEGER
        )
    """)
    # ترقية آمنة لقاعدة بيانات مُنشأة قبل إضافة عمود الصورة (لا يؤثر على تثبيت جديد)
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(cases)").fetchall()}
    if "image_base64" not in existing_cols:
        conn.execute("ALTER TABLE cases ADD COLUMN image_base64 TEXT")
    conn.commit()
    conn.close()


init_db()


# ---------- Schemas ----------
class ProbItem(BaseModel):
    name: str
    val: int
    top: Optional[bool] = False


class CaseReferral(BaseModel):
    age: str
    sex_ar: str
    sex_en: str
    location_ar: str
    location_en: str
    attending_note_ar: str
    attending_note_en: str
    risk: str = "high"
    risk_label_ar: str = "خطورة مرتفعة"
    risk_label_en: str = "High risk"
    probs: List[ProbItem] = []
    marker: int = 74
    marker_label_ar: str = "مشتبه"
    marker_label_en: str = "Suspicious"
    # صورة الآفة مُرمّزة Base64 (بدون البادئة data:image/...;base64,)
    image_base64: Optional[str] = None


class ExpertReport(BaseModel):
    verdict: str
    notes: str


def gen_case_id():
    n = random.randint(1000, 9999)
    letter = random.choice(string.ascii_uppercase.replace("I", "").replace("O", ""))
    digit = random.randint(0, 9)
    return f"PT-{n}-{letter}{digit}"


def gen_hash():
    return "".join(random.choices(string.hexdigits.lower(), k=4)) + "..." + "".join(random.choices(string.hexdigits.lower(), k=4))


def row_to_case(row) -> dict:
    return {
        "id": row["id"],
        "hash": row["hash"],
        "timestamp": row["timestamp"],
        "risk": row["risk"],
        "riskLabel": row["risk_label_ar"],
        "riskLabelEn": row["risk_label_en"],
        "age": row["age"],
        "sex": row["sex_ar"],
        "sexEn": row["sex_en"],
        "location": row["location_ar"],
        "locationEn": row["location_en"],
        "attendingNote": row["attending_note_ar"],
        "attendingNoteEn": row["attending_note_en"],
        "probs": json.loads(row["probs_json"] or "[]"),
        "marker": row["marker"],
        "markerLabel": row["marker_label_ar"],
        "markerLabelEn": row["marker_label_en"],
        "imageBase64": row["image_base64"],
        "status": row["status"],
        "reportVerdict": row["report_verdict"],
        "reportNotes": row["report_notes"],
        "reportTimestamp": row["report_timestamp"],
    }


# ---------- Endpoints ----------
PLATFORM_HTML_PATH = os.path.join(os.path.dirname(__file__), "platform_interface.html")


@app.get("/", response_class=HTMLResponse)
def serve_platform():
    if not os.path.exists(PLATFORM_HTML_PATH):
        return HTMLResponse(
            "<h3>ملف platform_interface.html غير موجود في المستودع. "
            "ارفعه بجانب main.py ثم أعد النشر.</h3>",
            status_code=500,
        )
    with open(PLATFORM_HTML_PATH, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api")
def api_info():
    return {
        "service": "SkinSense/ExpertDerm API",
        "status": "running",
        "docs": "/docs",
        "health_check": "/api/health",
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "SkinSense/ExpertDerm API"}


@app.post("/api/cases")
def create_case(payload: CaseReferral):
    conn = get_db()
    case_id = gen_case_id()
    conn.execute(
        """INSERT INTO cases (
            id, hash, timestamp, risk, risk_label_ar, risk_label_en,
            age, sex_ar, sex_en, location_ar, location_en,
            attending_note_ar, attending_note_en, probs_json,
            marker, marker_label_ar, marker_label_en, image_base64, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            case_id, gen_hash(), int(time.time() * 1000),
            payload.risk, payload.risk_label_ar, payload.risk_label_en,
            payload.age, payload.sex_ar, payload.sex_en,
            payload.location_ar, payload.location_en,
            payload.attending_note_ar, payload.attending_note_en,
            json.dumps([p.dict() for p in payload.probs]),
            payload.marker, payload.marker_label_ar, payload.marker_label_en,
            payload.image_base64,
            "pending",
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    return row_to_case(row)


@app.get("/api/cases")
def list_cases(status: Optional[str] = None):
    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM cases WHERE status=? ORDER BY timestamp DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM cases ORDER BY timestamp DESC").fetchall()
    conn.close()
    return [row_to_case(r) for r in rows]


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return row_to_case(row)


@app.post("/api/cases/{case_id}/report")
def send_report(case_id: str, payload: ExpertReport):
    conn = get_db()
    row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Case not found")
    conn.execute(
        """UPDATE cases SET status=?, report_verdict=?, report_notes=?, report_timestamp=?
           WHERE id=?""",
        ("reported", payload.verdict, payload.notes, int(time.time() * 1000), case_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    return row_to_case(row)
