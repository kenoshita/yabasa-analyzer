async function analyze() {
  const url = document.getElementById("url").value.trim();
  const text = document.getElementById("text").value.trim();
  const mode = document.getElementById("mode").value;
  const status = document.getElementById("status");
  status.textContent = "診断中...";

  try {
    const res = await fetch("/analyze", {
      method:"POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ url: url || null, text: text || null, mode })
    });
    if (!res.ok) {
      const err = await res.json().catch(()=>({detail:res.statusText}));
      throw new Error(err.detail || "エラー");
    }
    const data = await res.json();
    renderResult(data);
    status.textContent = "完了";
  } catch(e) {
    status.textContent = "エラー: " + e.message;
  }
}

function renderResult(d) {
  document.getElementById("result").classList.remove("hidden");
  document.getElementById("totalScore").textContent = d.total;
  document.getElementById("totalLabel").textContent = d.label;
  document.getElementById("radar").src = "data:image/png;base64," + d.chart_png_base64;

  const scaleList = document.getElementById("scaleList");
  scaleList.innerHTML = "";
  (d.scale_legend?.detail || []).forEach(item => {
    const li = document.createElement("li");
    li.textContent = `${item.score}: ${item.meaning}`;
    scaleList.appendChild(li);
  });

  const tbody = document.querySelector("#scoreTable tbody");
  tbody.innerHTML = "";
  const cats = Object.keys(d.category_scores);
  cats.forEach(cat => {
    const tr = document.createElement("tr");
    const tdC = document.createElement("td");
    tdC.textContent = cat;
    const tdS = document.createElement("td");
    tdS.textContent = d.category_scores[cat];
    const tdM = document.createElement("td");
    const ok = d.measured_flags?.[cat];
    tdM.textContent = ok ? "測定済" : "測定不能";
    if (!ok) tr.classList.add("na");
    tr.appendChild(tdC); tr.appendChild(tdS); tr.appendChild(tdM);
    tbody.appendChild(tr);
  });

  const ev = document.getElementById("evidence");
  ev.innerHTML = "";
  (d.evidence || []).forEach(e => {
    const div = document.createElement("div");
    div.className = "evi";
    // ここは HTML（赤マーク含む）をそのまま表示
    div.innerHTML = `<b>${e.category}</b>：${e.snippet}`;
    ev.appendChild(div);
  });

  const rec = document.getElementById("recommendations");
  rec.innerHTML = "";
  (d.recommendations || []).forEach(r => {
    const li = document.createElement("li");
    li.textContent = `${r.category}: ${r.suggestion}`;
    rec.appendChild(li);
  });

  const reasons = document.getElementById("reasons");
  reasons.innerHTML = "";
  (d.top_reasons || []).forEach(r => {
    const li = document.createElement("li");
    li.textContent = `${r.category}: ${r.reason}（重み${r.weight}）`;
    reasons.appendChild(li);
  });
}

document.getElementById("analyzeBtn").addEventListener("click", analyze);
