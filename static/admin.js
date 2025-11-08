async function login() {
  const pwd = document.getElementById('pwd').value.trim();
  const status = document.getElementById('loginStatus');
  status.textContent = '読込中...';

  try {
    const res = await fetch('/admin/data', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ password: pwd })
    });
    if (!res.ok) {
      const err = await res.json().catch(()=>({detail:'認証エラー'}));
      throw new Error(err.detail || '認証エラー');
    }
    const d = await res.json();
    document.getElementById('loginBox').classList.add('hidden');
    document.getElementById('dash').classList.remove('hidden');
    document.getElementById('totalNum').textContent = d.total_requests ?? 0;

    // 折れ線
    new Chart(document.getElementById('dailyChart'), {
      type: 'line',
      data: { labels: d.daily.labels, datasets: [{ label: '件数', data: d.daily.values }] },
      options: { responsive: true, maintainAspectRatio: false }
    });

    // 円
    new Chart(document.getElementById('labelPie'), {
      type: 'pie',
      data: { labels: ['低','中','高'], datasets: [{ data: [d.by_label.low, d.by_label.mid, d.by_label.high] }] },
      options: { responsive: true, maintainAspectRatio: false }
    });

    status.textContent = '';
  } catch (e) {
    status.textContent = 'エラー: ' + e.message;
  }
}

document.getElementById('loginBtn').addEventListener('click', login);
