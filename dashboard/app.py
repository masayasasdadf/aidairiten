from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import Optional

from db.database import get_db, init_db
from db.models import Job, Deliverable, JobStatus

app = FastAPI(title="AI総合商社 ダッシュボード")


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI総合商社 ダッシュボード</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #0f1117; color: #e0e0e0; }
  header { background: #1a1d2e; padding: 16px 24px; border-bottom: 1px solid #2a2d3e; }
  header h1 { font-size: 1.4rem; color: #7c8cf8; }
  .stats { display: flex; gap: 16px; padding: 24px; flex-wrap: wrap; }
  .stat-card { background: #1a1d2e; border-radius: 8px; padding: 20px; min-width: 140px; border: 1px solid #2a2d3e; }
  .stat-card .num { font-size: 2rem; font-weight: bold; color: #7c8cf8; }
  .stat-card .label { font-size: 0.8rem; color: #888; margin-top: 4px; }
  .section { padding: 0 24px 24px; }
  h2 { font-size: 1rem; color: #aaa; margin-bottom: 12px; }
  table { width: 100%; border-collapse: collapse; background: #1a1d2e; border-radius: 8px; overflow: hidden; }
  th { background: #2a2d3e; padding: 10px 14px; text-align: left; font-size: 0.8rem; color: #888; }
  td { padding: 10px 14px; font-size: 0.85rem; border-top: 1px solid #2a2d3e; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }
  .badge-new { background: #1e3a5f; color: #60a5fa; }
  .badge-inhouse { background: #1a3a2a; color: #4ade80; }
  .badge-outsource { background: #3a2a1a; color: #fb923c; }
  .badge-qc { background: #3a1a3a; color: #c084fc; }
  .badge-approved { background: #1a3a1a; color: #86efac; }
  .badge-skip { background: #2a2a2a; color: #666; }
  .btn { padding: 4px 12px; border-radius: 4px; border: none; cursor: pointer; font-size: 0.8rem; }
  .btn-approve { background: #166534; color: #86efac; }
  .btn-reject { background: #7f1d1d; color: #fca5a5; }
  a { color: #7c8cf8; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
<header>
  <h1>AI総合商社 ダッシュボード</h1>
</header>

<div class="stats" id="stats">読み込み中...</div>

<div class="section">
  <h2>案件一覧</h2>
  <table>
    <thead>
      <tr>
        <th>タイトル</th>
        <th>プラットフォーム</th>
        <th>カテゴリ</th>
        <th>単価</th>
        <th>スコア</th>
        <th>ステータス</th>
        <th>操作</th>
      </tr>
    </thead>
    <tbody id="jobs-table">読み込み中...</tbody>
  </table>
</div>

<script>
const STATUS_LABELS = {
  new: ['新着', 'badge-new'],
  analyzing: ['分析中', 'badge-new'],
  inhouse: ['自社処理予定', 'badge-inhouse'],
  outsource: ['外注予定', 'badge-outsource'],
  skipped: ['スキップ', 'badge-skip'],
  in_progress: ['生産中', 'badge-inhouse'],
  qc: ['QC中', 'badge-qc'],
  pending_approval: ['承認待ち', 'badge-qc'],
  approved: ['承認済み', 'badge-approved'],
  delivered: ['納品済み', 'badge-approved'],
  rejected: ['NG', 'badge-skip'],
};

async function loadStats() {
  const r = await fetch('/api/stats');
  const d = await r.json();
  document.getElementById('stats').innerHTML = Object.entries(d).map(([k,v]) =>
    `<div class="stat-card"><div class="num">${v}</div><div class="label">${k}</div></div>`
  ).join('');
}

async function loadJobs() {
  const r = await fetch('/api/jobs');
  const jobs = await r.json();
  const rows = jobs.map(j => {
    const [label, cls] = STATUS_LABELS[j.status] || [j.status, 'badge-new'];
    const price = j.price_fixed ? `¥${j.price_fixed.toLocaleString()}` :
      j.price_min ? `¥${j.price_min.toLocaleString()}〜` : '不明';
    const actions = j.status === 'pending_approval'
      ? `<button class="btn btn-approve" onclick="approve(${j.id})">承認</button>
         <button class="btn btn-reject" onclick="reject(${j.id})">却下</button>`
      : '';
    return `<tr>
      <td><a href="${j.url}" target="_blank">${j.title.slice(0,40)}${j.title.length>40?'…':''}</a></td>
      <td>${j.platform}</td>
      <td>${j.category}</td>
      <td>${price}</td>
      <td>${j.score?.toFixed(0) ?? '-'}</td>
      <td><span class="badge ${cls}">${label}</span></td>
      <td>${actions}</td>
    </tr>`;
  });
  document.getElementById('jobs-table').innerHTML = rows.join('') || '<tr><td colspan="7" style="text-align:center;color:#666">案件なし</td></tr>';
}

async function approve(id) {
  await fetch(`/api/jobs/${id}/approve`, {method:'POST'});
  loadJobs();
}
async function reject(id) {
  await fetch(`/api/jobs/${id}/reject`, {method:'POST'});
  loadJobs();
}

loadStats();
loadJobs();
setInterval(() => { loadStats(); loadJobs(); }, 30000);
</script>
</body>
</html>"""


@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    total = db.query(Job).count()
    new = db.query(Job).filter(Job.status == JobStatus.NEW).count()
    inhouse = db.query(Job).filter(Job.status == JobStatus.INHOUSE).count()
    in_progress = db.query(Job).filter(Job.status == JobStatus.IN_PROGRESS).count()
    pending = db.query(Job).filter(Job.status == JobStatus.PENDING_APPROVAL).count()
    approved = db.query(Job).filter(Job.status == JobStatus.APPROVED).count()
    delivered = db.query(Job).filter(Job.status == JobStatus.DELIVERED).count()
    return {
        "総案件数": total,
        "新着": new,
        "自社処理予定": inhouse,
        "生産中": in_progress,
        "承認待ち": pending,
        "承認済み": approved,
        "納品済み": delivered,
    }


@app.get("/api/jobs")
async def get_jobs(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)
    jobs = query.order_by(Job.discovered_at.desc()).limit(100).all()
    return [
        {
            "id": j.id,
            "platform": j.platform,
            "title": j.title,
            "url": j.url,
            "category": j.category.value if j.category else None,
            "status": j.status.value if j.status else None,
            "execution_type": j.execution_type.value if j.execution_type else None,
            "price_fixed": j.price_fixed,
            "price_min": j.price_min,
            "price_max": j.price_max,
            "score": j.score,
            "analysis_notes": j.analysis_notes,
        }
        for j in jobs
    ]


@app.get("/api/jobs/{job_id}/deliverable")
async def get_deliverable(job_id: int, db: Session = Depends(get_db)):
    d = db.query(Deliverable).filter(Deliverable.job_id == job_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return {"content": d.content, "qc_passed": d.qc_passed, "qc_notes": d.qc_notes}


@app.post("/api/jobs/{job_id}/approve")
async def approve_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Not found")
    job.status = JobStatus.APPROVED
    db.commit()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/reject")
async def reject_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Not found")
    job.status = JobStatus.REJECTED
    db.commit()
    return {"ok": True}
