from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

import asyncio

from agents.chat_agent import chat as chat_agent_run, fetch_history, PERSONAS as CHAT_THREADS
from db.control import get_state as get_control_state, pause as pause_ops, resume as resume_ops
from db.credentials import all_credentials_masked, set_credential, CREDENTIAL_KEYS
from db.database import get_db, init_db
from db.models import Job, Deliverable, Directive, JobStatus
from dashboard.events import get_events, log_event
from pipeline import run_pipeline, go_job, skip_job, cycle_state


_VALID_TARGETS = {"all", "analysis", "execution", "qc"}


class DirectiveIn(BaseModel):
    target: str = Field(..., description="all / analysis / execution / qc")
    instruction: str = Field(..., min_length=1, max_length=2000)


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class CredentialIn(BaseModel):
    key: str
    value: str = ""

app = FastAPI(title="AI総合商社 ダッシュボード")


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/healthz")
async def healthz():
    """Render の health check 用。DB も LLM も叩かず即200を返す。"""

    return {"ok": True}


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
  .feed { max-height: 70vh; overflow-y: auto; }
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

  /* 業務状態バナー */
  .control-banner { margin: 0 24px 12px; padding: 10px 16px; border-radius: 8px; display: flex; gap: 12px; align-items: center; font-size: 0.9rem; }
  .control-banner.paused { background: #3a1d1d; border: 1px solid #7f1d1d; color: #fca5a5; }
  .control-banner.active { background: #1a2a1d; border: 1px solid #166534; color: #86efac; }
  .control-banner button { background: transparent; border: 1px solid currentColor; color: inherit; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 0.8rem; margin-left: auto; }
  .control-banner button:hover { background: rgba(255,255,255,0.05); }

  /* チャット */
  .chat-section { padding: 0 24px 24px; }
  .chat-panel { background: #1a1d2e; border: 1px solid #2a2d3e; border-radius: 10px; overflow: hidden; }
  .chat-panel h3 { font-size: 0.85rem; color: #aaa; padding: 10px 14px; background: #15182a; border-bottom: 1px solid #2a2d3e; letter-spacing: 0.05em; display:flex; align-items:center; gap:8px; }
  .chat-tabs { display: flex; background: #0f1117; border-bottom: 1px solid #2a2d3e; }
  .chat-tabs .tab { background: transparent; color: #888; border: none; padding: 10px 18px; cursor: pointer; font-size: 0.85rem; font-family: inherit; border-bottom: 2px solid transparent; }
  .chat-tabs .tab:hover { color: #ccc; }
  .chat-tabs .tab.active { color: #7c8cf8; border-bottom-color: #7c8cf8; background: #1a1d2e; }
  .chat-history { height: 360px; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; background: #15182a; }
  .msg { max-width: 80%; padding: 8px 12px; border-radius: 10px; font-size: 0.88rem; line-height: 1.5; word-break: break-word; white-space: pre-wrap; }
  .msg.user { background: #2a3a5e; color: #e0e7ff; align-self: flex-end; border-bottom-right-radius: 2px; }
  .msg.assistant { background: #2a2d3e; color: #ddd; align-self: flex-start; border-bottom-left-radius: 2px; }
  .msg.tool { background: #3a2a1d; color: #fde68a; align-self: stretch; font-family: ui-monospace, monospace; font-size: 0.75rem; }
  .msg .meta { font-size: 0.7rem; color: #888; margin-top: 4px; }
  .chat-form { display: flex; gap: 8px; padding: 12px; background: #1a1d2e; border-top: 1px solid #2a2d3e; }
  .chat-form input { flex: 1; background: #0f1117; color: #e0e0e0; border: 1px solid #3a3d5e; border-radius: 6px; padding: 9px 12px; font-size: 0.88rem; font-family: inherit; }
  .chat-form button { background: #7c8cf8; border: none; color: white; padding: 9px 18px; border-radius: 6px; cursor: pointer; font-size: 0.88rem; font-weight: 600; }
  .chat-form button:hover { background: #6373d8; }
  .chat-form button:disabled { opacity: 0.5; cursor: not-allowed; }
  .chat-empty { color: #555; text-align: center; padding: 40px 0; font-size: 0.85rem; }
  .typing { color: #666; font-size: 0.8rem; font-style: italic; }

  /* 認証情報 */
  .creds-section { padding: 0 24px 18px; }
  .creds-panel { background: #1a1d2e; border: 1px solid #2a2d3e; border-radius: 10px; }
  .creds-panel h3 { font-size: 0.85rem; color: #aaa; padding: 10px 14px; background: #15182a; border-bottom: 1px solid #2a2d3e; cursor: pointer; user-select: none; display: flex; align-items: center; gap: 8px; }
  .creds-panel h3 .toggle { margin-left: auto; color: #666; font-size: 0.75rem; }
  .creds-body { padding: 14px; display: none; }
  .creds-body.open { display: block; }
  .creds-grid { display: grid; grid-template-columns: 200px 1fr 100px 80px; gap: 8px; align-items: center; font-size: 0.82rem; }
  .creds-grid > .row-label { color: #aaa; }
  .creds-grid > .row-status { color: #666; font-family: ui-monospace, monospace; font-size: 0.75rem; }
  .creds-grid > input { background: #0f1117; color: #e0e0e0; border: 1px solid #3a3d5e; border-radius: 5px; padding: 6px 10px; font-size: 0.82rem; font-family: inherit; }
  .creds-grid > .row-btn { display:flex; gap:4px; }
  .creds-grid > .row-btn button { padding: 5px 8px; border-radius: 4px; border: 1px solid #3a3d5e; background: transparent; color: #ccc; cursor: pointer; font-size: 0.72rem; }
  .creds-grid > .row-btn button:hover { background: #2a2d3e; }
  .creds-note { color: #666; font-size: 0.72rem; margin-top: 8px; line-height: 1.5; }
</style>
</head>
<body>
<header>
  <h1>AI総合商社 ダッシュボード</h1>
  <div style="display:flex;align-items:center;gap:12px">
    <button id="cycle-btn" onclick="startCycle()" style="background:#7c8cf8;border:none;color:white;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:0.85rem;font-weight:600">🔍 巡回開始</button>
    <div class="clock" id="clock">--:--:--</div>
  </div>
</header>

<div class="stats" id="stats">読み込み中...</div>

<div class="control-banner active" id="control-banner" style="display:none">
  <span id="control-text"></span>
  <button onclick="resumeOps()" id="control-resume" style="display:none">即時再開</button>
</div>

<div class="creds-section">
  <div class="creds-panel">
    <h3 onclick="toggleCreds()">🔐 認証情報・APIキー <span class="toggle" id="creds-toggle">[展開]</span></h3>
    <div class="creds-body" id="creds-body">
      <div class="creds-grid" id="creds-grid"></div>
      <div class="creds-note">
        ここで設定した値は DB に保存され、Render の環境変数より優先されます。<br>
        DeepSeek API キー: <a href="https://platform.deepseek.com/" target="_blank">platform.deepseek.com</a> で取得（残高チャージ忘れずに）
      </div>
    </div>
  </div>
</div>

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

<div class="chat-section">
  <div class="chat-panel">
    <h3>💬 部門との対話 <span style="color:#666;font-weight:400;font-size:0.75rem;margin-left:auto">統括は業務停止/再開などの実コマンドを実行できる</span></h3>
    <div class="chat-tabs" id="chat-tabs">
      <button type="button" class="tab active" data-thread="ceo">統括(COO)</button>
      <button type="button" class="tab" data-thread="analysis">分析部</button>
      <button type="button" class="tab" data-thread="execution">制作部</button>
      <button type="button" class="tab" data-thread="qc">QC部</button>
    </div>
    <div class="chat-history" id="chat-history"></div>
    <form class="chat-form" id="chat-form" onsubmit="return submitChat(event)">
      <input id="chat-input" type="text" placeholder="メッセージを送る…（例: 24時間業務停止しろ / 文体を関西弁に）" maxlength="4000" autocomplete="off" required />
      <button type="submit" id="chat-submit">送信</button>
    </form>
  </div>
</div>

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
  reported: ['🔔 上申(GO待ち)', 'badge-qc'],
  inhouse: ['制作キュー', 'badge-inhouse'], outsource: ['外注待ち', 'badge-outsource'],
  skipped: ['見送り', 'badge-skip'], in_progress: ['生産中', 'badge-inhouse'],
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
      let actions = '';
      if (j.status === 'reported') {
        const goLabel = j.execution_type === 'outsource' ? 'GO(外注)' : 'GO(受注)';
        actions = `<button class="btn btn-approve" onclick="goJob(${j.id})">${goLabel}</button>
                   <button class="btn btn-reject" onclick="skipJob(${j.id})">見送る</button>`;
      } else if (j.status === 'pending_approval') {
        actions = `<button class="btn btn-approve" onclick="approve(${j.id})">承認</button>
                   <button class="btn btn-reject" onclick="reject(${j.id})">却下</button>`;
      }
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
async function goJob(id)   { await fetch(`/api/jobs/${id}/go`,      {method:'POST'}); refreshAll(); }
async function skipJob(id) { await fetch(`/api/jobs/${id}/skip`,    {method:'POST'}); refreshAll(); }

async function startCycle() {
  const btn = document.getElementById('cycle-btn');
  btn.disabled = true;
  try {
    const r = await fetch('/api/cycle/run', { method: 'POST' });
    if (r.status === 409) { alert('既に巡回中です'); }
    else if (!r.ok) { alert('巡回開始失敗: ' + r.status); }
    loadActivity();
    pollCycleState();
  } finally {
    setTimeout(() => { btn.disabled = false; }, 1500);
  }
}

async function pollCycleState() {
  try {
    const r = await fetch('/api/cycle/state');
    const s = await r.json();
    const btn = document.getElementById('cycle-btn');
    if (s.running) {
      btn.textContent = `🌀 巡回中… (${s.phase || '...'})`;
      btn.disabled = true;
      setTimeout(pollCycleState, 2000);
    } else {
      btn.textContent = '🔍 巡回開始';
      btn.disabled = false;
      refreshAll();
    }
  } catch (e) { console.warn('cycle state', e); }
}

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

// ---- 認証情報 ----
const CRED_LABELS = {
  deepseek_api_key: 'DeepSeek API キー',
  deepseek_base_url: 'DeepSeek BaseURL',
  crowdworks_email: 'CrowdWorks メール',
  crowdworks_password: 'CrowdWorks パスワード',
  lancers_email: 'Lancers メール',
  lancers_password: 'Lancers パスワード',
  coconala_email: 'Coconala メール',
  coconala_password: 'Coconala パスワード',
};

function toggleCreds() {
  const body = document.getElementById('creds-body');
  const tog = document.getElementById('creds-toggle');
  body.classList.toggle('open');
  tog.textContent = body.classList.contains('open') ? '[折りたたむ]' : '[展開]';
  if (body.classList.contains('open')) loadCredentials();
}

async function loadCredentials() {
  try {
    const r = await fetch('/api/credentials');
    const d = await r.json();
    const grid = document.getElementById('creds-grid');
    const rows = Object.entries(CRED_LABELS).map(([k, label]) => {
      const meta = d[k] || { set: false, preview: '' };
      const ph = meta.set ? `現在: ${meta.preview} (上書きで再設定)` : '未設定';
      return `
        <div class="row-label">${label}</div>
        <input id="cred-${k}" type="text" placeholder="${ph}" autocomplete="off" />
        <div class="row-status">${meta.set ? '✓ 設定済み' : '— 未設定'}</div>
        <div class="row-btn">
          <button onclick="saveCred('${k}')">保存</button>
          ${meta.set ? `<button onclick="clearCred('${k}')">削除</button>` : ''}
        </div>
      `;
    }).join('');
    grid.innerHTML = rows;
  } catch (e) { console.warn('credentials failed', e); }
}

async function saveCred(key) {
  const el = document.getElementById('cred-' + key);
  const value = el.value.trim();
  if (!value) { alert('値を入力してください'); return; }
  const r = await fetch('/api/credentials', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ key, value }),
  });
  if (r.ok) { el.value = ''; loadCredentials(); loadActivity(); }
  else { alert('保存失敗: ' + r.status); }
}

async function clearCred(key) {
  if (!confirm('この値を削除する？')) return;
  await fetch('/api/credentials', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ key, value: '' }),
  });
  loadCredentials(); loadActivity();
}

function refreshAll() { loadStats(); loadJobs(); loadActivity(); loadDirectives(); loadControl(); }

async function loadControl() {
  try {
    const r = await fetch('/api/control');
    const s = await r.json();
    const banner = document.getElementById('control-banner');
    const text = document.getElementById('control-text');
    const btn = document.getElementById('control-resume');
    if (s.paused) {
      banner.className = 'control-banner paused';
      banner.style.display = 'flex';
      btn.style.display = 'inline-block';
      const until = s.paused_until ? new Date(s.paused_until).toLocaleString('ja-JP') : '?';
      text.textContent = `🛑 業務停止中（再開予定: ${until}） — ${s.pause_reason || ''}`;
    } else {
      banner.style.display = 'none';
    }
  } catch (e) { console.warn('control failed', e); }
}

async function resumeOps() {
  if (!confirm('業務を即時再開する？')) return;
  await fetch('/api/control/resume', { method: 'POST' });
  loadControl(); loadActivity();
}

// ---- チャット ----
let currentThread = 'ceo';

function setupChatTabs() {
  document.querySelectorAll('#chat-tabs .tab').forEach(t => {
    t.addEventListener('click', () => {
      document.querySelectorAll('#chat-tabs .tab').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      currentThread = t.dataset.thread;
      loadChat();
    });
  });
}

async function loadChat() {
  try {
    const r = await fetch(`/api/chat/${currentThread}`);
    const items = await r.json();
    const el = document.getElementById('chat-history');
    if (!items.length) {
      el.innerHTML = '<div class="chat-empty">まだ会話はありません。気軽に話しかけてみてください。</div>';
      return;
    }
    el.innerHTML = items.filter(m => m.role !== 'tool').map(m => `
      <div class="msg ${m.role}">${escapeHtml(m.content)}</div>
    `).join('');
    el.scrollTop = el.scrollHeight;
  } catch (e) { console.warn('chat history failed', e); }
}

async function submitChat(ev) {
  ev.preventDefault();
  const input = document.getElementById('chat-input');
  const btn = document.getElementById('chat-submit');
  const text = input.value.trim();
  if (!text) return false;
  input.value = '';
  btn.disabled = true;

  // 楽観的に user message を即表示 + typing インジケータ
  const el = document.getElementById('chat-history');
  if (el.querySelector('.chat-empty')) el.innerHTML = '';
  el.insertAdjacentHTML('beforeend', `<div class="msg user">${escapeHtml(text)}</div>`);
  el.insertAdjacentHTML('beforeend', `<div class="msg assistant typing" id="typing-indicator">考え中…</div>`);
  el.scrollTop = el.scrollHeight;

  try {
    const r = await fetch(`/api/chat/${currentThread}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: text }),
    });
    document.getElementById('typing-indicator')?.remove();
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      el.insertAdjacentHTML('beforeend', `<div class="msg assistant" style="color:#f87171">エラー: ${escapeHtml(err.detail || r.status)}</div>`);
    } else {
      const data = await r.json();
      el.insertAdjacentHTML('beforeend', `<div class="msg assistant">${escapeHtml(data.reply)}</div>`);
      if (data.tool_calls && data.tool_calls.length) {
        // ツール実行があったので各種ステート更新
        loadDirectives(); loadControl(); loadActivity(); loadStats();
      }
    }
    el.scrollTop = el.scrollHeight;
  } finally {
    btn.disabled = false;
    input.focus();
  }
  return false;
}

setupChatTabs();

// 初回 + ポーリング
refreshAll();
loadChat();
pollCycleState();
setInterval(loadActivity, 3000);          // 活動ログは速めに
setInterval(() => { loadStats(); loadJobs(); loadDirectives(); loadControl(); }, 15000);
setInterval(() => { document.getElementById('clock').textContent = new Date().toTimeString().slice(0,8); }, 1000);
</script>
</body>
</html>"""


@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    total = db.query(Job).count()
    reported = db.query(Job).filter(Job.status == JobStatus.REPORTED).count()
    in_progress = db.query(Job).filter(Job.status == JobStatus.IN_PROGRESS).count()
    qc = db.query(Job).filter(Job.status == JobStatus.QC).count()
    pending = db.query(Job).filter(Job.status == JobStatus.PENDING_APPROVAL).count()
    approved = db.query(Job).filter(Job.status == JobStatus.APPROVED).count()
    skipped = db.query(Job).filter(Job.status == JobStatus.SKIPPED).count()
    return {
        "総案件数": total,
        "上申待ち(GO待ち)": reported,
        "生産中": in_progress + qc,
        "承認待ち": pending,
        "承認済み": approved,
        "見送り": skipped,
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
async def get_activity(limit: int = 200):
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


@app.get("/api/control")
async def get_control():
    return get_control_state()


@app.post("/api/control/resume")
async def post_resume():
    resume_ops()
    log_event("system", "業務再開", "UI操作", level="success")
    return {"ok": True}


@app.get("/api/cycle/state")
async def get_cycle():
    return cycle_state()


@app.post("/api/cycle/run")
async def post_cycle_run():
    state = cycle_state()
    if state["running"]:
        raise HTTPException(status_code=409, detail="既に巡回中")
    log_event("system", "巡回開始指示", "UIから手動トリガ", level="success")
    asyncio.create_task(run_pipeline())
    return {"ok": True, "started": True}


@app.post("/api/jobs/{job_id}/go")
async def post_job_go(job_id: int):
    state = cycle_state()
    # GO は内部で execute → QC まで走らせるので、巡回と並行しても基本問題ないが
    # ロックは軽くしておく（巡回サイクルは別ロック）
    asyncio.create_task(go_job(job_id))
    return {"ok": True, "scheduled": True}


@app.post("/api/jobs/{job_id}/skip")
async def post_job_skip(job_id: int):
    return skip_job(job_id)


@app.get("/api/credentials")
async def get_credentials():
    return all_credentials_masked()


@app.post("/api/credentials")
async def post_credential(payload: CredentialIn):
    if payload.key not in CREDENTIAL_KEYS:
        raise HTTPException(status_code=400, detail=f"key は {CREDENTIAL_KEYS} のいずれか")
    set_credential(payload.key, payload.value.strip())
    log_event(
        "system",
        "認証情報更新",
        f"{payload.key} ({'設定' if payload.value else 'クリア'})",
        level="success",
    )
    return {"ok": True}


@app.get("/api/chat/{thread}")
async def get_chat_history(thread: str, limit: int = 100):
    if thread not in CHAT_THREADS:
        raise HTTPException(status_code=404, detail=f"thread は {sorted(CHAT_THREADS)} のいずれか")
    return fetch_history(thread, limit=limit)


@app.post("/api/chat/{thread}")
async def post_chat(thread: str, payload: ChatIn):
    if thread not in CHAT_THREADS:
        raise HTTPException(status_code=404, detail=f"thread は {sorted(CHAT_THREADS)} のいずれか")
    try:
        result = await chat_agent_run(thread, payload.message.strip())
    except Exception as e:
        log_event("chat", thread, f"エラー: {e}", level="error")
        raise HTTPException(status_code=500, detail=str(e))
    return result


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
