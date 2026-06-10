#!/usr/bin/env python3
import os
from weasyprint import HTML, CSS

html_content = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>
  @font-face {
    font-family: 'IPAGothic';
    src: url('/usr/share/fonts/truetype/fonts-japanese-gothic.ttf');
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'IPAGothic', sans-serif;
    font-size: 10pt;
    color: #222;
    background: #fff;
    padding: 30px 40px;
  }

  /* Top accent bar */
  .top-bar {
    height: 8px;
    background: linear-gradient(to right, #1a1a1a 60%, #c00 100%);
    margin-bottom: 16px;
  }

  /* Header area */
  .header-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 6px;
  }
  .header-left {
    font-size: 9pt;
    color: #333;
    line-height: 1.7;
  }
  .invoice-title {
    font-size: 32pt;
    font-weight: bold;
    color: #1a1a1a;
    letter-spacing: 4px;
  }

  /* Logo */
  .logo {
    font-size: 22pt;
    font-weight: bold;
    font-style: italic;
    color: #1a1a1a;
    margin-bottom: 12px;
    font-family: 'IPAGothic', sans-serif;
  }

  /* FOR/FROM section */
  .for-from-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 20px;
  }
  .for-from-table td {
    vertical-align: top;
    padding: 6px 8px;
  }
  .label-cell {
    background: #1a1a1a;
    color: #fff;
    font-weight: bold;
    font-size: 9pt;
    text-align: center;
    width: 44px;
    padding: 6px 4px;
  }
  .for-content {
    padding-left: 14px;
  }
  .for-name {
    font-size: 11pt;
    font-weight: bold;
    margin-bottom: 2px;
  }
  .tantou {
    font-size: 12pt;
    font-weight: bold;
    margin-top: 6px;
  }
  .amount-label {
    font-size: 9pt;
    color: #333;
  }
  .amount-value {
    font-size: 28pt;
    font-weight: bold;
    color: #1a1a1a;
    text-align: right;
    padding-right: 10px;
  }
  .from-content {
    font-size: 9.5pt;
    line-height: 1.7;
    padding-left: 14px;
  }

  /* Divider line */
  .divider {
    border: none;
    border-top: 2px solid #1a1a1a;
    margin: 10px 0;
  }

  /* Items table */
  .items-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 6px;
  }
  .items-table th {
    background: #fff;
    border-bottom: 2px solid #1a1a1a;
    padding: 5px 8px;
    text-align: left;
    font-size: 9.5pt;
    font-weight: bold;
  }
  .items-table th.right {
    text-align: right;
  }
  .items-table td {
    padding: 5px 8px;
    font-size: 9.5pt;
    border-bottom: 1px solid #ddd;
  }
  .items-table td.right {
    text-align: right;
  }
  .items-table td.center {
    text-align: center;
  }
  .col-date  { width: 50px; }
  .col-item  { }
  .col-qty   { width: 70px; text-align: center; }
  .col-price { width: 100px; text-align: right; }
  .col-amt   { width: 110px; text-align: right; }

  /* Blank rows */
  .blank-row td {
    height: 24px;
    border-bottom: 1px solid #ddd;
  }

  /* Totals section */
  .totals-section {
    margin-top: 10px;
    display: flex;
    justify-content: flex-end;
  }
  .totals-table {
    border-collapse: collapse;
    width: 320px;
  }
  .totals-table td {
    padding: 5px 10px;
    font-size: 10pt;
  }
  .totals-table .total-label {
    text-align: left;
    font-weight: bold;
  }
  .totals-table .total-value {
    text-align: right;
    font-weight: bold;
    font-size: 14pt;
  }
  .totals-table .sub-label {
    text-align: left;
    color: #333;
  }
  .totals-table .sub-value {
    text-align: right;
    color: #333;
  }
  .totals-table tr.total-row td {
    border-top: 2px solid #1a1a1a;
    border-bottom: 2px solid #1a1a1a;
  }

  /*備考 section */
  .biko-section {
    margin-top: 30px;
    border-top: 1px solid #999;
    padding-top: 8px;
  }
  .biko-title {
    font-weight: bold;
    font-size: 10pt;
    margin-bottom: 8px;
  }
  .biko-row {
    display: flex;
    gap: 16px;
    margin-bottom: 6px;
    font-size: 10pt;
    align-items: baseline;
  }
  .biko-key {
    min-width: 80px;
    color: #333;
  }
  .biko-val {
    color: #1a1a1a;
  }
  .biko-val.due {
    font-size: 15pt;
    font-weight: bold;
  }

  /* Bottom accent */
  .bottom-bar {
    height: 6px;
    background: linear-gradient(to right, #c00 0%, #1a1a1a 40%);
    margin-top: 20px;
  }
</style>
</head>
<body>

<div class="top-bar"></div>

<!-- Header -->
<div class="header-row">
  <div class="header-left">
    2026/6/1<br>
    ING-000025<br>
    株式会社GLOBE　マンガ倉庫甘木店
  </div>
  <div class="invoice-title">請求書</div>
</div>

<!-- Logo -->
<div class="logo">Akatsuki</div>

<hr class="divider">

<!-- FOR / FROM / Amount -->
<table class="for-from-table">
  <tr>
    <td class="label-cell">FOR</td>
    <td class="for-content">
      <div class="for-name">株式会社GLOBE　マンガ倉庫甘木店　御中</div>
      <div class="tantou">濱川 様</div>
    </td>
    <td style="width:160px; vertical-align:middle;">
      <div class="amount-label">御請求金額</div>
    </td>
    <td style="width:180px; vertical-align:middle; text-align:right;">
      <div class="amount-value">¥ 98,780</div>
    </td>
  </tr>
  <tr>
    <td class="label-cell">FROM</td>
    <td class="from-content" colspan="3">
      株式会社Akatsuki<br>
      〒814-0022　福岡県福岡市早良区原3丁目17-44<br>
      ライズTビル 201号室
    </td>
  </tr>
</table>

<hr class="divider">

<!-- Items table -->
<table class="items-table">
  <thead>
    <tr>
      <th class="col-date">日付</th>
      <th>品目</th>
      <th class="col-qty right" style="text-align:right;">数量</th>
      <th class="col-price right">単価（税別）</th>
      <th class="col-amt right">金額（税別）</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>5/31</td>
      <td>ReviewMaster利用料</td>
      <td class="right">1</td>
      <td class="right">19,800</td>
      <td class="right">19,800</td>
    </tr>
    <tr>
      <td>5/31</td>
      <td>LINE運用代行費</td>
      <td class="right">1</td>
      <td class="right">15,000</td>
      <td class="right">15,000</td>
    </tr>
    <tr>
      <td>5/31</td>
      <td>ジモティーAds　配信費</td>
      <td class="right">1</td>
      <td class="right">50,000</td>
      <td class="right">50,000</td>
    </tr>
    <tr>
      <td>5/31</td>
      <td>ジモティーAds　運用手数料</td>
      <td class="right">1</td>
      <td class="right">5,000</td>
      <td class="right">5,000</td>
    </tr>
    <tr class="blank-row"><td></td><td></td><td></td><td></td><td></td></tr>
    <tr class="blank-row"><td></td><td></td><td></td><td></td><td></td></tr>
    <tr class="blank-row"><td></td><td></td><td></td><td></td><td></td></tr>
  </tbody>
</table>

<!-- Totals -->
<div class="totals-section">
  <table class="totals-table">
    <tr class="total-row">
      <td class="total-label">合計（税別）</td>
      <td class="total-value">89,800</td>
    </tr>
    <tr><td colspan="2" style="height:10px;"></td></tr>
    <tr>
      <td class="sub-label">10%対象</td>
      <td class="sub-value" style="text-align:right; font-weight:bold;">89,800</td>
    </tr>
    <tr>
      <td class="sub-label">（消費税</td>
      <td class="sub-value" style="text-align:right;">8,980　）</td>
    </tr>
  </table>
</div>

<!-- 備考 -->
<div class="biko-section">
  <div class="biko-title">備考</div>
  <div class="biko-row">
    <span class="biko-key">お振込先：</span>
    <span class="biko-val">GMOあおぞら銀行　法人営業部<br>
    &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;普通　2548572　カ)アカツキ</span>
  </div>
  <div class="biko-row">
    <span class="biko-key">お支払期限：</span>
    <span class="biko-val due">2026/6/30</span>
  </div>
</div>

<div class="bottom-bar"></div>

</body>
</html>
"""

output_path = "/home/user/aidairiten/請求書_マンガ倉庫甘木店_ING-000025.pdf"

HTML(string=html_content).write_pdf(
    output_path,
    stylesheets=[CSS(string='@page { size: A4; margin: 0; }')]
)

print(f"PDF generated: {output_path}")
