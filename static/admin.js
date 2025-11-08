async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {})
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

document.getElementById("loginBtn").addEventListener("click", async () => {
  const pwd = document.getElementById("adminPwd").value.trim();
  const msg = document.getElementById("loginMsg");
  msg.textContent = "認証中…";
  try {
    const d = await postJSON("/admin/data", { password: pwd });
    document.getElementById("loginBox").classList.add("hidden");
    document.getElementById("dash").classList.remove("hidden");

    // Summary counters
    document.getElementById("todayCount").textContent = d.today_count;
    document.getElementById("totalCount").textContent = d.requests_total;
    document.getElementById("okErr").textContent = `${d.requests_ok} / ${d.requests_error}`;

    // Daily line
    new Chart(document.getElementById("dailyChart"), {
      type: "line",
      data: {
        labels: d.daily.labels,
        datasets: [{ label: "利用数", data: d.daily.values }]
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } }
    });

    // Label pie
    new Chart(document.getElementById("labelPie"), {
      type: "pie",
      data: {
        labels: ["低", "中", "高"],
        datasets: [{ data: [d.labels.low, d.labels.mid, d.labels.high] }]
      },
      options: { responsive: true, maintainAspectRatio: false }
    });

  } catch (e) {
    msg.textContent = "認証に失敗しました：" + e.message;
  }
});
