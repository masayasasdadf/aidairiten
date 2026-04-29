from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

from db.database import get_db, init_db
from db.models import Job, Deliverable, Directive, JobStatus
from dashboard.events import get_events, log_event


_VALID_TARGETS = {"all", "analysis", "execution", "qc"}


class DirectiveIn(BaseModel):
    target: str = Field(..., description="all / analysis / execution / qc")
    instruction: str = Field(..., min_length=1, max_length=2000)

app = FastAPI(title="AI総合商社 ダッシュボード")


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return _DASHBOARD_HTML


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI総合商社 ダッシュボード</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e0e0e0; }
  header { background: #1a1d2e; padding: 16px 24px; border-bottom: 1px solid #2a2d3e; display:flex; justify-content:space-between; align-items:center; }
  header h1 { font-size: 1.4rem; color: #7c8cf8; }
  header .clock { font-family: ui-monospace, monospace; color: #888; font-size: 0.85rem; }

  .stats { display: flex; gap: 12px; padding: 18px 24px; flex-wrap: wrap; }
  .stat-card { background: #1a1d2e; border-radius: 8px; padding: 14px 18px; min-width: 110px; border: 1px solid #2a2d3e; }
  .stat-card .num { font-size: 1.6rem; font-weight: bold; color: #7c8cf8; }
  .stat-card .label { font-size: 0.75rem; color: #888; margin-top: 2px; }

  .section { padding: 0 24px 18px; }
  h2 { font-size: 0.9rem; color: #aaa; margin-bottom: 10px; letter-spacing: 0.05em; }

  /* 部門カード */
  .depts { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; padding: 0 24px 18px; }
  .dept { background: #1a1d2e; border: 1px solid #2a2d3e; border-radius: 10px; padding: 14px; transition: border-color 0.3s; }
  .dept.active { border-color: #4ade80; box-shadow: 0 0 0 1px #4ade8033; }
  .dept .head { display:flex; align-items:center; gap:8px; margin-bottom: 6px; }
  .dept .dot { width: 10px; height: 10px; border-radius: 50%; background: #555; }
  .dept.active .dot { background: #4ade80; box-shadow: 0 0 8px #4ade80; animation: pulse 1.4s ease-in-out infinite; }
  .dept .name { font-weight: 600; font-size: 0.95rem; }
  .dept .state { font-size: 0.75rem; color: #888; margin-left: auto; }
  .dept.active .state { color: #4ade80; }
  .dept .last { font-size: 0.8rem; color: #ccc; line-height: 1.5; min-height: 2.4rem; }
  .dept .ago { font-size: 0.7rem; color: #666; margin-top: 6px; font-family: ui-monospace, monospace; }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  /* 2カラムレイアウト */
  .grid2 { display: grid; grid-template-columns: 1fr 1.4fr; gap: 16px; padding: 0 24px 24px; }
  @media (max-width: 1000px) { .grid2 { grid-template-columns: 1fr; } }

  .panel { background: #1a1d2e; border: 1px solid #2a2d3e; border-radius: 10px; overflow: hidden; }
  .panel h3 { font-size: 0.8rem; color: #aaa; padding: 10px 14px; background: #15182a; border-bottom: 1px solid #2a2d3e; letter-spacing: 0.05em; }

  /* 活動ログ */
  .feed { max-height: 60vh; overflow-y: auto; }
  .feed-item { padding: 8px 14px; border-bottom: 1px solid #22253a; font-size: 0.82rem; display: flex; gap: 10px; align-items: flex-start; }
  .feed-item:last-child { border-bottom: none; }
  .feed-item .ts { color: #666; font-family: ui-monospace, monospace; font-size: 0.72rem; min-width: 60px; padding-top: 2px; }
  .feed-item .actor { font-weight: 600; min-width: 80px; padding-top: 2px; }
  .feed-item .msg { color: #ccc; flex: 1; word-break: break-word; }
  .feed-item.lvl-success .actor { color: #4ade80; }
  .feed-item.lvl-warn .actor { color: #fbbf24; }
  .feed-item.lvl-error .actor { color: #f87171; }
  .feed-item.lvl-info .actor { color: #7c8cf8; }
  .feed-empty { padding: 20px; text-align: center; color: #555; font-size: 0.85rem; }

  /* 案件テーブル */
  table { width: 100%; border-collapse: collapse; }
  th { background: #15182a; padding: 9px 12px; text-align: left; font-size: 0.72rem; color: #888; letter-spacing: 0.05em; }
  td { padding: 9px 12px; font-size: 0.82rem; border-top: 1px solid #22253a; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; }
  .badge-new { background: #1e3a5f; color: #60a5fa; }
  .badge-inhouse { background: #1a3a2a; color: #4ade80; }
  .badge-outsource { background: #3a2a1a; color: #fb923c; }
  .badge-qc { background: #3a1a3a; color: #c084fc; }
  .badge-approved { background: #1a3a1a; color: #86efac; }
  .badge-skip { background: #2a2a2a; color: #666; }
  .btn { padding: 3px 10px; border-radius: 4px; border: none; cursor: pointer; font-size: 0.75rem; margin-right: 4px; }
  .btn-approve { background: #166534; color: #86efac; }
  .btn-reject { background: #7f1d1d; color: #fca5a5; }
  a { color: #7c8cf8; text-decoration: none; }
  a:hover { text-decoration: underline; }

  .scroll-x { overflow-x: auto; }

  /* 神の声 */
  .god-section { padding: 0 24px 18px; }
  .god-panel { background: linear-gradient(135deg, #1a1d2e 0%, #2a1d3e 100%); border: 1px solid #5a3d8e; border-radius: 10px; padding: 16px; }
  .god-panel h2 { color: #c084fc; margin-bottom: 10px; display:flex; align-items:center; gap:8px; }
  .god-form { display: flex; gap: 8px; align-items: stretch; flex-wrap: wrap; }
  .god-form select, .god-form input, .god-form button {
    background: #0f1117; color: #e0e0e0; border: 1px solid #3a3d5e; border-radius: 6px; padding: 8px 12px; font-size: 0.85rem; font-family: inherit;
  }
  .god-form input { flex: 1; min-width: 280px; }
  .god-form select { min-width: 130px; cursor: pointer; }
  .god-form button { background: #7c3aed; border-color: #7c3aed; color: white; cursor: pointer; font-weight: 600; padding: 8px 18px; }
  .god-form button:hover { background: #6d28d9; }
  .god-form button:disabled { opacity: 0.5; cursor: not-allowed; }
  .god-list { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
  .god-item { display: flex; gap: 10px; align-items: flex-start; background: #0f1117; padding: 8px 12px; border-radius: 6px; border: 1px solid #2a2d3e; font-size: 0.82rem; }
  .god-item .scope { color: #c084fc; font-weight: 600; min-width: 80px; font-size: 0.75rem; padding-top: 2px; }
  .god-item .text { flex: 1; color: #ddd; word-break: break-word; }
  .god-item .release { background: transparent; border: 1px solid #5a3d5e; color: #c084fc; padding: 2px 8px; border-radius: 4px; cursor: pointer; font-size: 0.72rem; }
  .god-item .release:hover { background: #5a3d5e33; }
  .god-empty { color: #666; font-size: 0.82rem; padding: 6px 0; }
</style>
</head>
<body>
<header>
  <h1>AI総合商社 ダッシュボード</h1>
  <div class="clock" id="clock">--:--:--</div>
</header>

<div class="stats" id="stats">読み込み中...</div>

<div class="god-section">
  <div class="god-panel">
    <h2>⚡ 神の声（上層部からの最重要指示）</h2>
    <form class="god-form" id="god-form" onsubmit="return submitDirective(event)">
      <select id="god-target">
        <option value="all">全社へ</option>
        <option value="analysis">分析部へ</option>
        <option value="execution">制作部へ</option>
        <option value="qc">QC部へ</option>
      </select>
      <input id="god-text" type="text" placeholder="例: スコア80未満の案件はすべて却下せよ / 文体を関西弁にしろ / 工数3時間超は外注扱いにしろ" maxlength="2000" required />
      <button type="submit" id="god-submit">発令</button>
    </form>
    <div class="god-list" id="god-list"><div class="god-empty">アクティブな指示なし</div></div>
  </div>
</div>

<h2 style="padding: 0 24px;">AI部門の稼働状況</h2>
<div class="depts" id="depts"></div>

<div class="grid2">
  <div class="panel">
    <h3>活動ログ（リアルタイム）</h3>
    <div class="feed" id="feed"><div class="feed-empty">待機中…</div></div>
  </div>
  <div class="panel">
    <h3>案件一覧</h3>
    <div class="scroll-x">
      <table>
        <thead><tr>
          <th>タイトル</th><th>プラットフォーム</th><th>カテゴリ</th><th>単価</th><th>スコア</th><th>ステータス</th><th>操作</th>
        </tr></thead>
        <tbody id="jobs-table"><tr><td colspan="7" class="feed-empty">読み込み中…</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<script>
const STATUS_LABELS = {
  new: ['新着', 'badge-new'], analyzing: ['分析中', 'badge-new'],
  inhouse: ['自社処理予定', 'badge-inhouse'], outsource: ['外注予定', 'badge-outsource'],
  skipped: ['スキップ', 'badge-skip'], in_progress: ['生産中', 'badge-inhouse'],
  qc: ['QC中', 'badge-qc'], pending_approval: ['承認待ち', 'badge-qc'],
  approved: ['承認済み', 'badge-approved'], delivered: ['納品済み', 'badge-approved'],
  rejected: ['NG', 'badge-skip'],
};

// actor → 部門メタ
const DEPTS = [
  { actor: 'pipeline',  name: '統括（パイプライン）', icon: '🏢' },
  { actor: 'scraper',   name: '営業部（巡回）',       icon: '🌐' },
  { actor: 'analysis',  name: '分析部',               icon: '🧠' },
  { actor: 'execution', name: '制作部',               icon: '✍️' },
  { actor: 'qc',        name: 'QC部',                 icon: '🔍' },
];

const TARGET_LABEL = { all: '全社', analysis: '分析部', execution: '制作部', qc: 'QC部' };
const ACTIVE_WINDOW_MS = 30 * 1000;  // 直近30秒以内のイベントがあれば「稼働中」

function fmtAgo(iso) {
  if (!iso) return '';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return 'now';
  if (ms < 60_000) return Math.round(ms/1000) + '秒前';
  if (ms < 3600_000) return Math.round(ms/60_000) + '分前';
  return Math.round(ms/3600_000) + '時間前';
}

function fmtClock(iso) {
  const d = new Date(iso);
  return d.toTimeString().slice(0,8);
}

async function loadStats() {
  try {
    const r = await fetch('/api/stats');
    const d = await r.json();
    document.getElementById('stats').innerHTML = Object.entries(d).map(([k,v]) =>
      `<div class="stat-card"><div class="num">${v}</div><div class="label">${k}</div></div>`
    ).join('');
  } catch (e) { console.warn('stats failed', e); }
}

async function loadActivity() {
  try {
    const r = await fetch('/api/activity');
    const events = await r.json();
    renderFeed(events);
    renderDepts(events);
  } catch (e) { console.warn('activity failed', e); }
}

function renderFeed(events) {
  if (!events.length) {
    document.getElementById('feed').innerHTML = '<div class="feed-empty">まだ活動なし。スケジューラの初回サイクル待ち。</div>';
    return;
  }
  document.getElementById('feed').innerHTML = events.map(e => `
    <div class="feed-item lvl-${e.level || 'info'}">
      <div class="ts">${fmtClock(e.ts)}</div>
      <div class="actor">${e.actor}</div>
      <div class="msg"><b>${escapeHtml(e.action)}</b>${e.detail ? ' — ' + escapeHtml(e.detail) : ''}${e.job_id ? ' <span style="color:#666">#'+e.job_id+'</span>' : ''}</div>
    </div>
  `).join('');
}

function renderDepts(events) {
  const now = Date.now();
  const lastByActor = {};
  // 新しい順なので最初に見つけたものが直近
  for (const e of events) {
    if (!lastByActor[e.actor]) lastByActor[e.actor] = e;
  }
  document.getElementById('depts').innerHTML = DEPTS.map(d => {
    const last = lastByActor[d.actor];
    const active = last && (now - new Date(last.ts).getTime()) < ACTIVE_WINDOW_MS;
    const lastTxt = last ? `${last.action}${last.detail ? ' — ' + escapeHtml(last.detail) : ''}` : '—';
    const ago = last ? fmtAgo(last.ts) : '未稼働';
    return `<div class="dept ${active ? 'active' : ''}">
      <div class="head">
        <span class="dot"></span>
        <span class="name">${d.icon} ${d.name}</span>
        <span class="state">${active ? '稼働中' : '待機'}</span>
      </div>
      <div class="last">${lastTxt}</div>
      <div class="ago">${ago}</div>
    </div>`;
  }).join('');
}

async function loadJobs() {
  try {
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
        <td><a href="${j.url}" target="_blank">${escapeHtml(j.title.slice(0,40))}${j.title.length>40?'…':''}</a></td>
        <td>${j.platform}</td>
        <td>${j.category || '-'}</td>
        <td>${price}</td>
        <td>${j.score?.toFixed(0) ?? '-'}</td>
        <td><span class="badge ${cls}">${label}</span></td>
        <td>${actions}</td>
      </tr>`;
    });
    document.getElementById('jobs-table').innerHTML = rows.join('') || '<tr><td colspan="7" class="feed-empty">案件なし</td></tr>';
  } catch (e) { console.warn('jobs failed', e); }
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function approve(id) { await fetch(`/api/jobs/${id}/approve`, {method:'POST'}); refreshAll(); }
async function reject(id)  { await fetch(`/api/jobs/${id}/reject`,  {method:'POST'}); refreshAll(); }

async function loadDirectives() {
  try {
    const r = await fetch('/api/directives');
    const items = await r.json();
    const el = document.getElementById('god-list');
    if (!items.length) { el.innerHTML = '<div class="god-empty">アクティブな指示なし</div>'; return; }
    el.innerHTML = items.map(d => `
      <div class="god-item">
        <div class="scope">${TARGET_LABEL[d.target] || d.target}</div>
        <div class="text">${escapeHtml(d.instruction)}</div>
        <button class="release" onclick="releaseDirective(${d.id})">解除</button>
      </div>
    `).join('');
  } catch (e) { console.warn('directives failed', e); }
}

async function submitDirective(ev) {
  ev.preventDefault();
  const target = document.getElementById('god-target').value;
  const text = document.getElementById('god-text').value.trim();
  if (!text) return false;
  const btn = document.getElementById('god-submit');
  btn.disabled = true;
  try {
    const r = await fetch('/api/directives', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target, instruction: text }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert('発令失敗: ' + (err.detail || r.status));
    } else {
      document.getElementById('god-text').value = '';
      await loadDirectives();
      await loadActivity();
    }
  } finally {
    btn.disabled = false;
  }
  return false;
}

async function releaseDirective(id) {
  if (!confirm('この指示を解除する？')) return;
  await fetch(`/api/directives/${id}`, { method: 'DELETE' });
  loadDirectives();
  loadActivity();
}

function refreshAll() { loadStats(); loadJobs(); loadActivity(); loadDirectives(); }

// 初回 + ポーリング
refreshAll();
setInterval(loadActivity, 3000);          // 活動ログは速めに
setInterval(() => { loadStats(); loadJobs(); loadDirectives(); }, 15000);
setInterval(() => { document.getElementById('clock').textContent = new Date().toTimeString().slice(0,8); }, 1000);
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


@app.get("/api/activity")
async def get_activity(limit: int = 100):
    return get_events(limit=limit)


@app.get("/api/directives")
async def list_directives(db: Session = Depends(get_db)):
    rows = (
        db.query(Directive)
        .filter(Directive.active.is_(True))
        .order_by(Directive.created_at.desc())
        .all()
    )
    return [
        {
            "id": d.id,
            "target": d.target,
            "instruction": d.instruction,
            "created_at": d.created_at.isoformat() + "Z" if d.created_at else None,
        }
        for d in rows
    ]


@app.post("/api/directives")
async def create_directive(payload: DirectiveIn, db: Session = Depends(get_db)):
    target = payload.target.strip().lower()
    if target not in _VALID_TARGETS:
        raise HTTPException(status_code=400, detail=f"target は {sorted(_VALID_TARGETS)} のいずれか")
    instruction = payload.instruction.strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction が空です")

    d = Directive(target=target, instruction=instruction, active=True)
    db.add(d)
    db.commit()
    db.refresh(d)

    scope = "全社" if target == "all" else f"{target}部"
    log_event("god", "神の声", f"[{scope}] {instruction[:120]}", level="warn")
    return {"id": d.id, "target": d.target, "instruction": d.instruction}


@app.delete("/api/directives/{directive_id}")
async def deactivate_directive(directive_id: int, db: Session = Depends(get_db)):
    d = db.query(Directive).filter(Directive.id == directive_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    d.active = False
    d.deactivated_at = datetime.utcnow()
    db.commit()
    scope = "全社" if d.target == "all" else f"{d.target}部"
    log_event("god", "神の声 解除", f"[{scope}] {d.instruction[:120]}", level="warn")
    return {"ok": True}


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
