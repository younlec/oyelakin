/**
 * Deriv Trading Dashboard — Frontend Application
 * Real-time updates via WebSocket, Chart.js for visualizations.
 */

(function () {
    "use strict";

    const API_BASE = window.location.origin;
    const WS_URL = `ws://${window.location.host}/ws`;

    let ws = null;
    let reconnectTimer = null;
    let equityChart = null;
    let winlossChart = null;

    const equityData = [];
    const pnlHistory = [];

    // ── DOM Elements ─────────────────────────────────────────────────────

    const $balance = document.getElementById("stat-balance");
    const $pnl = document.getElementById("stat-pnl");
    const $winrate = document.getElementById("stat-winrate");
    const $trades = document.getElementById("stat-trades");
    const $wl = document.getElementById("stat-wl");
    const $drawdown = document.getElementById("stat-drawdown");
    const $connStatus = document.getElementById("connection-status");
    const $lastUpdate = document.getElementById("last-update");
    const $tradeBody = document.getElementById("trade-body");
    const $riskOpen = document.getElementById("risk-open");
    const $riskConsec = document.getElementById("risk-consec");
    const $riskHalted = document.getElementById("risk-halted");
    const $riskReason = document.getElementById("risk-reason");

    // ── WebSocket ────────────────────────────────────────────────────────

    function connectWS() {
        if (ws && ws.readyState <= 1) return;

        ws = new WebSocket(WS_URL);

        ws.onopen = function () {
            setConnectionStatus(true);
            ws.send("stats");
        };

        ws.onmessage = function (event) {
            try {
                const msg = JSON.parse(event.data);
                handleMessage(msg);
            } catch (e) {
                console.error("WS parse error:", e);
            }
        };

        ws.onclose = function () {
            setConnectionStatus(false);
            scheduleReconnect();
        };

        ws.onerror = function () {
            setConnectionStatus(false);
        };
    }

    function scheduleReconnect() {
        if (reconnectTimer) return;
        reconnectTimer = setTimeout(function () {
            reconnectTimer = null;
            connectWS();
        }, 3000);
    }

    function setConnectionStatus(connected) {
        $connStatus.textContent = connected ? "Connected" : "Disconnected";
        $connStatus.className = "status-badge " + (connected ? "connected" : "disconnected");
    }

    function handleMessage(msg) {
        if (msg.type === "stats" && msg.data) {
            updateStats(msg.data);
        } else if (msg.event === "trade_closed" || msg.event === "trade_opened") {
            if (msg.stats) updateStats(msg.stats);
            if (msg.trade) addTradeRow(msg.trade);
        }
        $lastUpdate.textContent = "Updated: " + new Date().toLocaleTimeString();
    }

    // ── Stats Update ─────────────────────────────────────────────────────

    function updateStats(stats) {
        const balance = stats.balance || 0;
        const pnl = stats.daily_pnl || 0;
        const winRate = stats.win_rate || 0;
        const total = stats.total_trades || 0;
        const wins = stats.wins || 0;
        const losses = stats.losses || 0;
        const dd = stats.drawdown_percent || 0;

        $balance.textContent = "$" + balance.toFixed(2);
        $pnl.textContent = (pnl >= 0 ? "+$" : "-$") + Math.abs(pnl).toFixed(2);
        $pnl.className = "stat-value " + (pnl >= 0 ? "positive" : "negative");
        $winrate.textContent = winRate.toFixed(1) + "%";
        $trades.textContent = total;
        $wl.textContent = wins + " / " + losses;
        $drawdown.textContent = dd.toFixed(2) + "%";
        $drawdown.className = "stat-value " + (dd > 5 ? "negative" : "");

        $riskOpen.textContent = stats.open_trades || 0;
        $riskConsec.textContent = stats.consecutive_losses || 0;
        $riskHalted.textContent = stats.halted ? "YES" : "No";
        $riskHalted.style.color = stats.halted ? "var(--red)" : "var(--green)";
        $riskReason.textContent = stats.halt_reason || "\u2014";

        equityData.push(balance);
        if (equityData.length > 200) equityData.shift();
        updateEquityChart();
        updateWinLossChart(wins, losses);
    }

    // ── Charts ───────────────────────────────────────────────────────────

    function initCharts() {
        const eqCtx = document.getElementById("equity-chart").getContext("2d");
        equityChart = new Chart(eqCtx, {
            type: "line",
            data: {
                labels: [],
                datasets: [{
                    label: "Balance",
                    data: [],
                    borderColor: "#4f8cff",
                    backgroundColor: "rgba(79,140,255,0.1)",
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { display: false },
                    y: {
                        grid: { color: "rgba(45,48,64,0.5)" },
                        ticks: { color: "#8b8fa3" },
                    },
                },
            },
        });

        const wlCtx = document.getElementById("winloss-chart").getContext("2d");
        winlossChart = new Chart(wlCtx, {
            type: "doughnut",
            data: {
                labels: ["Wins", "Losses"],
                datasets: [{
                    data: [0, 0],
                    backgroundColor: ["#22c55e", "#ef4444"],
                    borderWidth: 0,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { color: "#8b8fa3" },
                    },
                },
            },
        });
    }

    function updateEquityChart() {
        if (!equityChart) return;
        equityChart.data.labels = equityData.map(function (_, i) { return i; });
        equityChart.data.datasets[0].data = equityData.slice();
        equityChart.update("none");
    }

    function updateWinLossChart(wins, losses) {
        if (!winlossChart) return;
        winlossChart.data.datasets[0].data = [wins, losses];
        winlossChart.update("none");
    }

    // ── Trade Table ──────────────────────────────────────────────────────

    function addTradeRow(trade) {
        if ($tradeBody.querySelector(".empty-row")) {
            $tradeBody.innerHTML = "";
        }

        const row = document.createElement("tr");
        const pnl = parseFloat(trade.pnl) || 0;
        const pnlClass = pnl >= 0 ? "pnl-positive" : "pnl-negative";
        const statusClass = trade.status === "win" ? "badge-win" : "badge-loss";
        const dirClass = trade.direction === "BUY" ? "badge-buy" : "badge-sell";

        const time = trade.entry_time
            ? new Date(trade.entry_time * 1000).toLocaleTimeString()
            : new Date().toLocaleTimeString();

        row.innerHTML =
            "<td>" + time + "</td>" +
            "<td>" + (trade.trade_id || "") + "</td>" +
            "<td>" + (trade.symbol || "") + "</td>" +
            '<td><span class="badge ' + dirClass + '">' + (trade.direction || "") + "</span></td>" +
            "<td>" + (trade.entry_price ? parseFloat(trade.entry_price).toFixed(5) : "") + "</td>" +
            "<td>" + (trade.exit_price ? parseFloat(trade.exit_price).toFixed(5) : "") + "</td>" +
            "<td>$" + (trade.stake ? parseFloat(trade.stake).toFixed(2) : "0.00") + "</td>" +
            '<td class="' + pnlClass + '">' + (pnl >= 0 ? "+" : "") + pnl.toFixed(4) + "</td>" +
            '<td><span class="badge ' + statusClass + '">' + (trade.status || "") + "</span></td>";

        $tradeBody.insertBefore(row, $tradeBody.firstChild);

        while ($tradeBody.children.length > 50) {
            $tradeBody.removeChild($tradeBody.lastChild);
        }
    }

    function loadTrades() {
        fetch(API_BASE + "/trades?limit=50")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.trades && data.trades.length) {
                    $tradeBody.innerHTML = "";
                    data.trades.reverse().forEach(addTradeRow);
                }
            })
            .catch(function (e) { console.error("Load trades error:", e); });
    }

    // ── Backtest ─────────────────────────────────────────────────────────

    function initBacktest() {
        var form = document.getElementById("backtest-form");
        form.addEventListener("submit", function (e) {
            e.preventDefault();
            var fileInput = document.getElementById("bt-file");
            if (!fileInput.files.length) return;

            var fd = new FormData();
            fd.append("file", fileInput.files[0]);
            fd.append("starting_balance", document.getElementById("bt-balance").value);
            fd.append("stake", document.getElementById("bt-stake").value);
            fd.append("spread", document.getElementById("bt-spread").value);

            var btn = document.getElementById("btn-backtest");
            btn.disabled = true;
            btn.textContent = "Running...";

            fetch(API_BASE + "/backtest", { method: "POST", body: fd })
                .then(function (r) { return r.json(); })
                .then(function (result) {
                    var el = document.getElementById("backtest-results");
                    el.style.display = "block";
                    el.textContent =
                        "Backtest Results\n" +
                        "================\n" +
                        "Total Trades:    " + result.total_trades + "\n" +
                        "Wins:            " + result.wins + "\n" +
                        "Losses:          " + result.losses + "\n" +
                        "Win Rate:        " + (result.win_rate || 0).toFixed(1) + "%\n" +
                        "Net P&L:         $" + (result.net_pnl || 0).toFixed(4) + "\n" +
                        "Max Drawdown:    $" + (result.max_drawdown || 0).toFixed(4) + "\n" +
                        "Drawdown %:      " + (result.max_drawdown_percent || 0).toFixed(2) + "%\n" +
                        "Sharpe Ratio:    " + (result.sharpe_ratio || 0).toFixed(4) + "\n" +
                        "Start Balance:   $" + (result.starting_balance || 0).toFixed(2) + "\n" +
                        "End Balance:     $" + (result.ending_balance || 0).toFixed(2);
                })
                .catch(function (e) {
                    var el = document.getElementById("backtest-results");
                    el.style.display = "block";
                    el.textContent = "Error: " + e.message;
                })
                .finally(function () {
                    btn.disabled = false;
                    btn.textContent = "Run Backtest";
                });
        });
    }

    // ── Init ─────────────────────────────────────────────────────────────

    document.getElementById("btn-refresh").addEventListener("click", function () {
        loadTrades();
        if (ws && ws.readyState === 1) ws.send("stats");
    });

    initCharts();
    initBacktest();
    loadTrades();
    connectWS();

    setInterval(function () {
        if (ws && ws.readyState === 1) {
            ws.send("ping");
        }
    }, 15000);
})();
